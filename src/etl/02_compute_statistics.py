import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert

# --- CONFIGURATION ---
import os
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
engine = create_engine(DB_URL, pool_size=10, max_overflow=20)
ANNUALIZATION_FACTOR = np.sqrt(252)
BATCH_SIZE = 200  # Process tickers in chunks to save RAM

# --- PRODUCTION UPSERT METHOD ---
def postgres_upsert(table, conn, keys, data_iter):
    """
    Handles 'ON CONFLICT DO UPDATE' efficiently.
    """
    data = [dict(zip(keys, row)) for row in data_iter]
    stmt = insert(table.table).values(data)
    
    # Update all columns except primary keys
    update_cols = {c.name: c for c in stmt.excluded if c.name not in ['timestamp', 'ticker']}
    
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=['timestamp', 'ticker'],
        set_=update_cols
    )
    conn.execute(upsert_stmt)

# --- CALCULATION LOGIC ---
def calculate_metrics(df):
    """
    Hardenized vectorized calculations.
    Handles zero-prices, infinite returns, and minimizes groupby overhead.
    """
    # 1. PRE-COMPUTATION SANITIZATION
    # Replace 0 with NaN to prevent ZeroDivision and log(0) errors
    df['price_adjusted'] = df['price_adjusted'].replace(0, np.nan).fillna(df['price_close'])
    
    # 2. OPTIMIZED GROUPING
    # We group once and use a helper to ensure enough data exists for indicators
    grouped = df.groupby('ticker')

    # 3. TECHNICAL INDICATORS (SMA / RSI)
    # Added guards to ensure the series length is sufficient for the window
    df['sma_252'] = grouped['price_adjusted'].transform(
        lambda x: ta.sma(x, length=252) if len(x) >= 252 else np.nan
    )
    df['rsi_14'] = grouped['price_adjusted'].transform(
        lambda x: ta.rsi(x, length=14) if len(x) >= 14 else np.nan
    )

    # 4. RETURNS (The "Log-Return" Shield)
    # np.log(current / prev) -> results in NaN if either is NaN or 0
    df['log_return'] = grouped['price_adjusted'].transform(lambda x: np.log(x / x.shift(1)))
    
    # Critical: Replace inf/-inf with NaN (happens if price was near 0)
    df['log_return'] = df['log_return'].replace([np.inf, -np.inf], np.nan)

    # 5. ROLLING MOMENTS (Volatility, Skew, Kurtosis)
    # We regroup on log_return for the statistical moments
    g_ret = df.groupby('ticker')['log_return']
    
    # min_periods=10 ensures we don't calculate noise on 1 or 2 days of data
    df['vol_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).std() * np.sqrt(252))
    df['skew_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).skew())
    df['kurt_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).kurt())

    # 6. MAX DRAWDOWN (Rolling 20)
    # Hardened to handle division by zero or rolling windows with all NaNs
    def rolling_dd_hardened(x):
        if x.isnull().all():
            return np.nan
        roll_max = x.rolling(20, min_periods=1).max()
        # Use .divide to handle potential zero max (though we replaced 0 above)
        return x.divide(roll_max.replace(0, np.nan)) - 1

    df['mdd_20'] = grouped['price_adjusted'].transform(rolling_dd_hardened)

    # 7. FINAL CLEANUP
    # Ensure no floating point errors like 1.0000000000000002
    # and cap extreme values if necessary
    return df

# --- CORE BATCH PROCESS ---
def process_ticker_batch(engine, tickers):
    """
    Processes a batch of tickers individually to prevent 
    Memory (OOM) crashes and handle timezone-aware data.
    """
    t_list = tuple(tickers)
    query_max = text("""
        SELECT ticker, MAX(timestamp) as last_ts 
        FROM statistics 
        WHERE ticker IN :tickers 
        GROUP BY ticker
    """)
    
    existing_map = {}
    with engine.connect() as conn:
        res = conn.execute(query_max, {'tickers': t_list}).fetchall()
        for row in res:
            if row.last_ts:
                ts = pd.to_datetime(row.last_ts)
                # Robust timezone handling
                existing_map[row.ticker] = ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')
            else:
                existing_map[row.ticker] = None

    # Process individually to isolate heavy tickers (e.g., Batch 38 fix)
    for ticker in tickers:
        try:
            last_ts = existing_map.get(ticker)
            # Fetch from 2015 if new, else use 400-day buffer for technical indicators
            start_date = last_ts - pd.Timedelta(days=400) if last_ts else pd.Timestamp('2015-01-01').tz_localize('UTC')

            query_prices = text("""
                SELECT timestamp, ticker, price_close, price_adjusted
                FROM market_prices 
                WHERE ticker = :ticker 
                AND timestamp >= :start_date
                ORDER BY timestamp ASC
            """)
            
            with engine.connect() as conn:
                # Set a local timeout for this specific query
                conn.execute(text("SET statement_timeout = '30s'"))
                df = pd.read_sql(query_prices, conn, params={'ticker': ticker, 'start_date': start_date})

            if df.empty:
                continue

            # Standardize DataFrame Timezone
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

            # Calculation
            df = calculate_metrics(df)
            
            # Filter for new rows only
            if last_ts:
                df = df[df['timestamp'] > last_ts]
            
            # Clean up
            df.dropna(subset=['sma_252', 'vol_20'], inplace=True)

            if df.empty:
                continue

            # Upsert
            cols = ['timestamp', 'ticker', 'rsi_14', 'sma_252', 'log_return', 'vol_20', 'mdd_20', 'skew_20', 'kurt_20']
            df[cols].to_sql(
                'statistics', 
                engine, 
                if_exists='append', 
                index=False, 
                method=postgres_upsert,
                chunksize=5000
            )
            print(f"      > Success: {ticker} ({len(df)} rows)")

        except Exception as e:
            print(f"      ! Error processing {ticker}: {e}")
            continue

def main_update_loop(us_only=False, eu_only=False, max_tickers=None):
    print("--- STARTING STATISTICS ENGINE ---")
    
    # 1. FETCH WITH FEEDBACK
    where_clauses = []
    # Quality floor: only tickers with known market cap >= $500M
    where_clauses.append("ticker IN (SELECT ticker FROM dim_entities WHERE market_cap IS NOT NULL AND market_cap >= 500000000)")
    if us_only:
        where_clauses.append("ticker NOT LIKE '%.%'")
    if eu_only:
        where_clauses.append("ticker LIKE '%.%'")
    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    limit_sql = f" LIMIT {max_tickers}" if max_tickers else ""
    ticker_query = text(f"""
        SELECT ticker 
        FROM (SELECT ticker FROM market_prices GROUP BY ticker) sub{where_sql}
        ORDER BY ticker{limit_sql};
    """)

    print("Fetching ticker list from index...")
    start_ts = time.time()
    
    with engine.connect() as conn:
        # We use execution_options to stream if the list is massive
        result = conn.execution_options(stream_results=True).execute(ticker_query)
        
        all_tickers = []
        for row in result:
            all_tickers.append(row[0])
            # FEEDBACK: Print every 500 tickers found
            if len(all_tickers) % 500 == 0:
                print(f"   > Found {len(all_tickers)} tickers so far...")

    elapsed = time.time() - start_ts
    print(f"Total Tickers: {len(all_tickers)} (Fetched in {elapsed:.2f}s)")
    
    if not all_tickers:
        print("!!! No tickers found. Check market_prices table.")
        return

    # 2. THE RESILIENT LOOP (Circuit Breaker)
    i = 0
    while i < len(all_tickers):
        batch = all_tickers[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"\nProcessing Batch {batch_num}/{int(np.ceil(len(all_tickers)/BATCH_SIZE))}...")
        
        try:
            process_ticker_batch(engine, batch)
            i += BATCH_SIZE
            
        except Exception as e:
            err = str(e).lower()
            if "recovery mode" in err or "closed the connection" in err:
                print(f"!!! DB CRASH on Batch {batch_num}. Waiting for recovery...")
                db_up = False
                while not db_up:
                    time.sleep(15)
                    try:
                        with engine.connect() as conn:
                            conn.execute(text("SELECT 1"))
                            db_up = True
                            print(">>> Database is back online. Retrying...")
                    except Exception:
                        print("... database still in recovery ...")
                continue 
            else:
                print(f"!!! Error in Batch {batch_num}: {e}")
                i += BATCH_SIZE

    print("\n--- UPDATE COMPLETE ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute statistics")
    parser.add_argument("--us", action="store_true", help="Only process US tickers (no dot suffix)")
    parser.add_argument("--eu", action="store_true", help="Only process European tickers (with dot suffix)")
    parser.add_argument("--max", type=int, default=None, help="Maximum number of tickers to process")
    args = parser.parse_args()
    main_update_loop(us_only=args.us, eu_only=args.eu, max_tickers=args.max)