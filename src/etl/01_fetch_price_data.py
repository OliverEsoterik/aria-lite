import pandas as pd
import yfinance as yf
import json, os, time
import psycopg2.extras
from typing import List, Dict, Optional
from sqlalchemy import create_engine, text

# --- Configuration ---
DB_CONN_STR = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
TICKER_LIST_PATH = "../../../data/tickers_to_trade2.json"
DEFAULT_START_DATE = (pd.Timestamp.today() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')

CHUNK_SIZE = 200 # Reduced chunk size for more reliable YF downloads
API_SLEEP_SECONDS = 0.7

def load_tickers(file_path: str) -> List[str]:
    if not os.path.exists(file_path): return []
    with open(file_path, 'r') as f:
        return [t.strip().upper() for t in json.load(f) if t]

def get_ticker_map(engine, tickers: List[str]) -> Dict[str, int]:
    # Process in sub-batches to avoid SQL string length limits
    mapping = {}
    batch_size = 500
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        query = text("SELECT ticker, entity_pk FROM dim_entities WHERE ticker = ANY(:tickers)")
        with engine.connect() as conn:
            result = conn.execute(query, {'tickers': batch})
            for row in result:
                mapping[row.ticker] = row.entity_pk
    return mapping

import time

def get_last_timestamps(engine, tickers: List[str]) -> Dict[str, str]:
    """
    Production-ready fetcher with back-off logic to prevent DB crashes.
    """
    last_dates = {}
    # Reduced from 300 to 100 to lower memory pressure per query
    batch_size = 100 
    
    for i in range(0, len(tickers), batch_size):
        batch = tuple(tickers[i:i+batch_size])
        # Use a parameterized query to allow Postgres to reuse execution plans
        query_str = "SELECT ticker, MAX(timestamp) as last_date FROM market_prices WHERE ticker IN :tickers GROUP BY ticker"
        
        attempt = 0
        max_retries = 3
        
        while attempt < max_retries:
            try:
                with engine.connect() as conn:
                    # Setting a statement timeout prevents the DB from hanging forever
                    conn.execute(text("SET statement_timeout = '10s'"))
                    result = conn.execute(text(query_str), {'tickers': batch})
                    for row in result:
                        if row.last_date:
                            last_dates[row.ticker] = row.last_date.strftime('%Y-%m-%d')
                break # Success, exit retry loop
                
            except Exception as e:
                attempt += 1
                error_msg = str(e).lower()
                
                # If DB is in recovery, wait longer and retry
                if "recovery mode" in error_msg or "connection to server" in error_msg:
                    wait_time = attempt * 10
                    print(f"   ! DB is recovering. Waiting {wait_time}s... (Attempt {attempt})")
                    time.sleep(wait_time)
                else:
                    print(f"   ! Error fetching batch {i}: {e}")
                    break # Non-critical error, skip batch

        # Small breath between batches to let the DB clear its RAM
        time.sleep(0.2)
        
    return last_dates

def download_ohlcv_chunk(tickers: List[str], start: str) -> Optional[pd.DataFrame]:
    print(f"   > Downloading {len(tickers)} tickers from {start}...")
    try:
        data = yf.download(tickers, start=start, progress=False, auto_adjust=False, threads=True, timeout=30)
        
        # 1. Empty Check
        if data is None or data.empty:
            return None
        
        # 2. "Ghost Data" Check (Rows exist, but all columns are NaN)
        # This catches the specific "Batch of 1" error you are seeing.
        if data.dropna(how='all').empty:
            return None

        df = data.copy()

        # 3. Shape Standardization
        if len(tickers) == 1:
            # Single Ticker Logic
            df['Ticker'] = tickers[0] # Force column creation
            if df.index.name != 'Date' and 'Date' not in df.columns:
                df.index.name = 'Date'
            df = df.reset_index()
        else:
            # Multi Ticker Logic
            df = df.stack(level=1, future_stack=True).reset_index()
            df.rename(columns={'level_1': 'Ticker', 'Date': 'timestamp'}, inplace=True)

        # 4. Final Cleanup
        if 'Date' in df.columns: 
            df.rename(columns={'Date': 'timestamp'}, inplace=True)
        
        # Normalize columns to standard set
        df.columns = [c.capitalize() if c in ['open', 'high', 'low', 'close', 'volume'] else c for c in df.columns]
        if 'Adj close' in df.columns: df.rename(columns={'Adj close': 'Adj Close'}, inplace=True)

        return df

    except Exception as e:
        print(f"   ! Download Error: {e}")
        return None

def fast_insert_market_prices(engine, df: pd.DataFrame, ticker_map: Dict[str, int]):
    if df is None or df.empty: return

    # 1. Map and Filter immediately
    df = df.assign(ticker_fk=df['Ticker'].map(ticker_map))
    
    # CRITICAL: Drop rows where yfinance returned NaN for a specific ticker in a multi-ticker batch
    # This prevents overwriting existing DB data with 0.0 during the update phase.
    valid_rows = df.dropna(subset=['ticker_fk', 'Close']).copy()
    
    if valid_rows.empty: return

    # 2. Sanitize and Clip (Industry Standard for Price Integrity)
    rename_map = {
        'Open': 'price_open', 'High': 'price_high', 'Low': 'price_low', 
        'Close': 'price_close', 'Adj Close': 'price_adjusted', 'Volume': 'volume'
    }
    valid_rows = valid_rows.rename(columns=rename_map)
    
    for col in rename_map.values():
        valid_rows[col] = pd.to_numeric(valid_rows[col], errors='coerce').fillna(0).clip(0, 10**12)

    # 3. Use standard ISO format for timestamps
    valid_rows['timestamp'] = pd.to_datetime(valid_rows['timestamp']).dt.strftime('%Y-%m-%d')
    valid_rows['source'] = 'YFINANCE'

    # 4. Upsert Logic (DO UPDATE)
    # Note: We update OHLC as well in case of 'Price Corrections' which Yahoo does frequently
    cols = ['timestamp', 'ticker_fk', 'Ticker', 'price_open', 'price_high', 'price_low', 
            'price_close', 'price_adjusted', 'volume', 'source']
    values = [tuple(x) for x in valid_rows[cols].to_numpy()]

    insert_query = """
        INSERT INTO market_prices (
            timestamp, ticker_fk, ticker, price_open, price_high, 
            price_low, price_close, price_adjusted, volume, source
        ) VALUES %s
        ON CONFLICT (timestamp, ticker_fk) 
        DO UPDATE SET
            price_open = EXCLUDED.price_open,
            price_high = EXCLUDED.price_high,
            price_low = EXCLUDED.price_low,
            price_close = EXCLUDED.price_close,
            price_adjusted = EXCLUDED.price_adjusted,
            volume = EXCLUDED.volume,
            inserted_at = NOW();
    """
    with engine.begin() as conn:
        psycopg2.extras.execute_values(conn.connection.cursor(), insert_query, values)

def main():
    start_time = time.time()
    tickers = load_tickers(TICKER_LIST_PATH)
    engine = create_engine(DB_CONN_STR, pool_pre_ping=True) # Pool_pre_ping checks connection health
    ticker_map = get_ticker_map(engine, tickers)
    
    valid_tickers = [t for t in tickers if t in ticker_map]
    last_dates_map = get_last_timestamps(engine, valid_tickers)

    date_groups = {}
    for t in valid_tickers:
        last_date_str = last_dates_map.get(t)
        if last_date_str:
            start_date = (pd.Timestamp(last_date_str) + pd.DateOffset(days=1)).strftime('%Y-%m-%d')
            if start_date > pd.Timestamp.today().strftime('%Y-%m-%d'): continue
        else:
            start_date = DEFAULT_START_DATE
            
        date_groups.setdefault(start_date, []).append(t)

    for start_date, group_tickers in date_groups.items():
        print(f"\n--- Processing Group: Start {start_date} ({len(group_tickers)} tickers) ---")
        
        for i in range(0, len(group_tickers), CHUNK_SIZE):
            chunk = group_tickers[i : i + CHUNK_SIZE]
            
            try:
                # Wrap the processing in a try/except block
                df_chunk = download_ohlcv_chunk(chunk, start_date)
                if df_chunk is not None:
                    fast_insert_market_prices(engine, df_chunk, ticker_map)
            except Exception as e:
                print(f"   ! CRITICAL BATCH ERROR (Skipping batch): {e}")
            
            time.sleep(API_SLEEP_SECONDS)

    print(f"\n--- Update Complete: {round((time.time() - start_time)/60, 2)} minutes ---")

if __name__ == "__main__":
    main()