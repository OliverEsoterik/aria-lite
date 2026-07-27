import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
import numpy as np

# --- Configuration ---
import os
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
engine = create_engine(DB_URL, pool_size=10, max_overflow=20)

from common import yang_zhang_vol, RiskGate, assign_production_rating, z_score, ANNUALIZATION_FACTOR


CURRENT_PORTFOLIO = ['GOOG', 'GOOGL', 'APLD', 'BE', 'CLSK', 'CRWV', 'INTC', 'IREN', 'KEEL', 'RIOT', 'SNDK', 'TE', 'TSM', 'ESLT', 'APH', 'AVGO', 'CRDO', 'VISN', 'CIEN', 'AMD', 'CLS', 'MU', 'BKNG', 'MELI', 'ARES', 'TMO', 'STX', 'ANET', 'FSLR', 'COMM', 'NFLX', 'AS', 'ARM', 'ALAB', 'DELL', 'INCY', 'MRVL', 'NU', 'TTD', 'VEEV', 'WDAY', 'SOFI', 'WDC', 'WLDN', 'BLK', 'META', 'BRK-B', 'PLTR', 'GOOG', 'PEP', 'MSFT', 'NVO', 'ACN', 'ARES', 'JPM', 'BNS', 'AXP', 'V', 'BN', 'IREN', 'PANW', 'NET', 'STX', 'TSM', 'NVDA', 'NOW', 'BX']

# --- 1. The Risk Gate (Toxic Waste Filter) ---
# --- 2. Data Fetching & Momentum Logic ---
def get_extensive_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        fwd_pe = info.get('forwardPE', 0)
        peg = info.get('pegRatio') 
        trl_eps = info.get('trailingEps', 0)

        # Institutional PEG Proxy
        if peg is None or peg == 0:
            f_eps, t_eps = info.get('forwardEps', 0), info.get('trailingEps', 0)
            if f_eps > 0 and t_eps > 0:
                eps_growth = ((f_eps / t_eps) - 1) * 100
                peg = fwd_pe / eps_growth if eps_growth > 2.0 else 99.0
            else: peg = 99.0

        # Standard: FCF Yield = Free Cash Flow / Market Cap
        fcf = info.get('freeCashflow')
        mcap = info.get('marketCap')

        fcf_yield = 0.0
        if fcf and mcap and mcap > 0:
            fcf_yield = fcf / mcap

        # Catalyst Logic (Analyst Revisions)
        eps_rev_val = 0.0
        try:
            trend = stock.eps_trend
            if trend is not None and '0y' in trend.index:
                rev_row = trend.loc['0y']
                curr, ago30 = rev_row.get('current'), rev_row.get('30daysAgo')
                if curr and ago30 and ago30 != 0:
                    eps_rev_val = (curr / ago30) - 1
        except: pass

        return {
            'ticker': ticker,
            'current_price': info.get('currentPrice', 0),
            'peg': round(peg, 3) if peg else 99.0,
            'fcf_yield': round(fcf_yield, 4), # Represented as decimal (0.05 = 5%)
            'fwd_pe': fwd_pe,
            'trl_eps': trl_eps,
            'op_margin': info.get('operatingMargins', 0),
            'profit_margin': info.get('profitMargins', 0),
            'rev_growth': info.get('revenueGrowth', 0),
            'roe': info.get('returnOnEquity', 0),
            'debt_to_equity': info.get('debtToEquity', 0),
            'current_ratio': info.get('currentRatio', 0),
            'eps_rev': eps_rev_val
        }
    except Exception:
        return {'ticker': ticker, 'peg': 99.0, 'eps_rev': 0.0, 'current_price': 0, 'fcf_yield': 0.0}

def calculate_momentum_metrics(engine, tickers):
    if not tickers: return pd.DataFrame()
    
    query = text("""
        SELECT ticker, price_open, price_high, price_low, price_close, timestamp FROM market_prices 
        WHERE ticker IN :tickers AND timestamp >= NOW() - INTERVAL '400 days'
        ORDER BY ticker, timestamp ASC
    """)
    hist_df = pd.read_sql(query, engine, params={'tickers': tuple(tickers)})
    results = []

    for ticker, group in hist_df.groupby('ticker'):
        # DYNAMIC GUARD: Minimum 3 months (63 days) for early entry
        # But we flag 'young' stocks to handle them differently
        available_days = len(group)
        if available_days < 63: continue 
        
        # A. VOLATILITY & RETURNS
        group['returns'] = group['price_close'].pct_change()
        vol = yang_zhang_vol(group, period=len(group), min_periods=10).iloc[-1] # Yang-Zhang annualized vol
        
        # B. PRICE POINTS (Now, 1m, 3m, 6m, 12m)
        p_now = group['price_close'].iloc[-1]
        p_1m = group['price_close'].iloc[-21]
        p_3m = group['price_close'].iloc[-63]

        # 6-month price point (for multi-lookback combination)
        if available_days >= 126:
            p_6m = group['price_close'].iloc[-126]
        else:
            p_6m = group['price_close'].iloc[0]  # fallback

        # 12-month price point
        if available_days >= 252:
            p_12m = group['price_close'].iloc[-252]
        else:
            p_12m = group['price_close'].iloc[0]  # fallback
        
        # C. MOMENTUM SPEEDS (Multi-Lookback)
        # 3m Fast Momentum (skip last month to avoid reversal)
        mom_3m = (p_1m / p_3m) - 1

        # 6m Intermediate Momentum
        mom_6m = (p_1m / p_6m) - 1

        # 12-1 Institutional Momentum (Persistence)
        mom_12m = (p_1m / p_12m) - 1

        # Combined Momentum (weighted average across lookbacks)
        # 3m captures short-term continuation, 6m intermediate, 12m persistence
        mom_combined = 0.3 * mom_3m + 0.3 * mom_6m + 0.4 * mom_12m

        # D. ELITE FACTORS
        # 1. RISK-ADJUSTED (Standard Institutional)
        adj_mom = mom_combined / (vol + 1e-6)
        
        # 2. ACCELERATION (Freshness)
        # Is the car speeding up? High accel = Fresh breakout.
        # Use current 3m return (including last month) vs 12m to capture the spark
        acceleration = (p_now / p_3m) - 1 - mom_12m
        
        # 3. MOMENTUM QUALITY (Quiet vs Loud)
        # sign(Return) * [% Days Positive - % Days Negative]
        pos_days = (group['returns'] > 0).sum()
        neg_days = (group['returns'] < 0).sum()
        inf_discr = np.sign(mom_12m) * (abs(pos_days - neg_days) / available_days)

        results.append({
            'ticker': ticker,
            'mom_score': adj_mom,           # Combined risk-adjusted momentum
            'mom_quality': inf_discr,       # Consistency (Quietness)
            'acceleration': acceleration,   # Freshness (Early Entry)
            'annual_vol': vol,              # Yang-Zhang annualized vol
            'near_high': p_now / group['price_close'].max(),
            'mom_3m': mom_3m,               # 3-month momentum (for rating logic)
            'mom_6m': mom_6m,               # 6-month momentum
            'mom_12m': mom_12m,             # 12-month momentum
        })

    return pd.DataFrame(results)

# --- 3. The "Elite 10" Rating Logic ---
    # Persistence Injection
    portfolio_df = df[df['ticker'].isin(CURRENT_PORTFOLIO)].copy()

    # Step B: Liquidity Filter
    df['dollar_volume'] = df['vol_20'] * df['sma_252']
    candidates = df.sort_values('dollar_volume', ascending=False).head(1500).copy()
    combined_candidates = pd.concat([candidates, portfolio_df]).drop_duplicates('ticker')

    # --- Step C: ELITE MOMENTUM FUNNEL ---
    mom_df = calculate_momentum_metrics(engine, combined_candidates['ticker'].tolist())
    merged_df = combined_candidates.merge(mom_df, on='ticker', how='left')
    
    # Step D: Deep Research Pool
    research_pool = merged_df.sort_values('mom_score', ascending=False).head(initial_pool_size).copy()
    
    # Guarantee Portfolio presence
    missing_p = merged_df[merged_df['ticker'].isin(CURRENT_PORTFOLIO)]
    research_pool = pd.concat([research_pool, missing_p]).drop_duplicates('ticker')

    # --- STEP E: BATCHED ASYNC RESEARCH (API PROTECTED) ---
    print(f"Executing deep research on {len(research_pool)} candidates in batches...")
    tickers_to_research = research_pool['ticker'].tolist()
    all_fund_data = []
    BATCH_SIZE = 50 
    
    for i in range(0, len(tickers_to_research), BATCH_SIZE):
        batch = tickers_to_research[i:i + BATCH_SIZE]
        print(f"Batch {i//BATCH_SIZE + 1}: Fetching {len(batch)} tickers...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_ticker = {executor.submit(get_extensive_fundamentals, t): t for t in batch}
            for future in as_completed(future_to_ticker):
                try:
                    data = future.result()
                    if data:
                        all_fund_data.append(data)
                except Exception as e:
                    print(f"API Error for {future_to_ticker[future]}: {e}")
        
        time.sleep(1.5) # Anti-throttling jittered delay

    fund_df = pd.DataFrame(all_fund_data)
    
    # Production Join: Left join ensures portfolio isn't dropped if API fails for one ticker
    final_merged = research_pool.merge(fund_df, on='ticker', how='left')

    # --- Step F: ELITE Z-SCORE NORMALIZATION ---
    # z_score is imported from common
    
    final_merged['z_mom_risk_adj'] = z_score(final_merged['mom_score'].fillna(0))
    final_merged['z_mom_qual'] = z_score(final_merged['mom_quality'].fillna(0))
    final_merged['z_accel'] = z_score(final_merged['acceleration'].fillna(0))

    final_merged['z_eps'] = z_score(final_merged['eps_rev'].fillna(0))
    final_merged['z_state'] = (z_score(final_merged['rsi_14'].fillna(50)) * -0.5) + (z_score(final_merged['vol_20'].fillna(0)) * 0.5)
    
    final_merged['s_qual'] = (
        (final_merged['rev_growth'].fillna(0).clip(0, 0.4) / 0.4 * 0.5) + 
        (final_merged['op_margin'].fillna(0).clip(0, 0.3) / 0.3 * 0.5)
    )

    # --- Step G: FINAL ELITE SCORING ---
    final_merged['final_score'] = (
        final_merged['z_mom_risk_adj'] * 0.25 + # Core Momentum
        final_merged['z_mom_qual']     * 0.25 + # Smoothness/Persistence
        final_merged['z_accel']        * 0.05 + # Short-term momentum
        final_merged['s_qual']         * 0.30 + # Revenue Growth + Op Margins etc
        final_merged['z_eps']          * 0.10 + # Analyst Revisions
        final_merged['z_state']        * 0.05   # Technical State (RSI/Vol)
    )

    gate = RiskGate()
    final_merged['pass_gate'] = final_merged.apply(gate.is_pass, axis=1)
    final_merged['rating'] = final_merged.apply(assign_production_rating, axis=1)

    # --- RESULT SPLIT ---
    top_picks = final_merged[final_merged['pass_gate']].sort_values('final_score', ascending=False).head(final_top_n)
    portfolio_status = final_merged[final_merged['ticker'].isin(CURRENT_PORTFOLIO)].copy()

    return top_picks, portfolio_status

if __name__ == "__main__":
    picks, status = get_today_best_buys(engine)
    
    if picks is not None:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        
        display_cols = [
            'ticker', 'rating', 'final_score', 'eps_rev', 'mom_score', 'peg', 'fwd_pe', 'rev_growth', 'op_margin', 'near_high', 'current_ratio', 'debt_to_equity', 'roe', 'profit_margin', 'fcf_yield'
        ]

        print("\n" + "="*50)
        print("--- NEW ALPHA DISCOVERIES ---")
        print("="*50)
        print(picks[display_cols].to_string(index=False))

        print("\n" + "="*50)
        print("--- CURRENT PORTFOLIO AUDIT ---")
        print("="*50)
        print(status[display_cols].to_string(index=False))
