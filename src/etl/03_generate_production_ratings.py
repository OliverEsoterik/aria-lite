import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
import numpy as np

# --- Configuration ---
import os
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
engine = create_engine(DB_URL, pool_size=10, max_overflow=20)
CURRENT_PORTFOLIO = ['MU', 'GOOG', 'CLS', 'GOOGL', 'AGX', 'LQDA', 'VICR', 'SIMO', 'AAMI', 'DELL', 'TER', 'STRL', 'AGX', 'CRDO', 'CIEN', 'LITE', 'CRDO', 'AMKR', 'KALU', 'BE', 'CLSK', 'IREN', 'SNDK', 'TE', 'TSM', 'ESLT', 'LRCX', 'APH', 'AVGO', 'CRDO', 'CIEN', 'AMD', 'CLS', 'STX', 'WDC', 'FSLR', 'DELL', 'MRVL', 'NU', 'TSM', 'NVDA']

# --- 1. The Risk Gate (Toxic Waste Filter) ---
class RiskGate:
    def __init__(self):
        self.min_price = 10.0           # Institutional floor
        self.min_op_margin = 0.05       # Profitability floor
        self.min_current_ratio = 0.8    # Liquidity floor
        self.min_roe = -0.10            # Solvency floor

    def is_pass(self, row):
        try:
            if row.get('current_price', 0) < self.min_price: return False
            if row.get('op_margin', 0) < self.min_op_margin: return False
            if row.get('current_ratio', 0) < self.min_current_ratio: return False
            if row.get('roe', 0) < self.min_roe: return False
            if row.get('fwd_pe') is None: return False
            return True
        except Exception:
            return False

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
            'sector': info.get('sector', 'N/A'),
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

def yang_zhang_vol(df, period=None, min_periods=10, annualize=True):
    """
    Yang-Zhang range-based volatility estimator.

    Combines overnight variance, open-close variance, and the Rogers-Satchell
    high-low range estimator for 7-8x more efficient estimation than
    close-to-close (Yang & Zhang, 2000).

    Parameters
    ----------
    df : DataFrame
        Must have columns: price_open, price_high, price_low, price_close.
    period : int, optional
        Rolling window size. If None, uses the full series length.
    min_periods : int
        Minimum periods for rolling calc (default 10).
    annualize : bool
        Multiply by sqrt(252) if True.

    Returns
    -------
    Series : Yang-Zhang volatility estimates (annualized by default).
    """
    if period is None:
        period = len(df)

    # Overnight return: ln(Open_t / Close_{t-1})
    log_oc = np.log(df['price_open'] / df['price_close'].shift(1))
    # Intraday return: ln(Close_t / Open_t)
    log_co = np.log(df['price_close'] / df['price_open'])

    # Rogers-Satchell component using high/low range
    log_ho = np.log(df['price_high'] / df['price_open'])
    log_lo = np.log(df['price_low'] / df['price_open'])
    log_hc = np.log(df['price_high'] / df['price_close'])
    log_lc = np.log(df['price_low'] / df['price_close'])
    rs = log_ho * log_hc + log_lo * log_lc

    # Rolling variances
    o_var = log_oc.rolling(period, min_periods=min_periods).var()
    c_var = log_co.rolling(period, min_periods=min_periods).var()
    rs_mean = rs.rolling(period, min_periods=min_periods).mean()

    # Optimal weighting parameter k (Yang & Zhang, 2000, eq. 15)
    k = 0.34 / (1.34 + (period + 1) / (period - 1))

    # Yang-Zhang variance
    yz_var = o_var + k * c_var + (1 - k) * rs_mean
    yz_var = yz_var.clip(lower=0)  # clamp numerical negatives

    vol = np.sqrt(yz_var)
    if annualize:
        vol = vol * np.sqrt(252)
    return vol


def calculate_momentum_metrics(engine, tickers):
    if not tickers: return pd.DataFrame()
    
    query = text("""
        SELECT ticker, price_open, price_high, price_low, price_close, timestamp
        FROM market_prices
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
        
        # A. VOLATILITY & RETURNS (Yang-Zhang range-based estimator, 7-8x more efficient)
        group['returns'] = group['price_close'].pct_change()
        vol = yang_zhang_vol(group, period=len(group), min_periods=63, annualize=True).iloc[-1]
        
        # B. PRICE POINTS (Now, 1m, 3m, 12m)
        p_now = group['price_close'].iloc[-1]
        p_1m = group['price_close'].iloc[-21]
        p_3m = group['price_close'].iloc[-63]
        
        # C. MOMENTUM SPEEDS
        # 12-1 Institutional Momentum (Persistence)
        if available_days >= 252:
            p_12m = group['price_close'].iloc[-252]
            mom_12m = (p_1m / p_12m) - 1
        else:
            mom_12m = (p_1m / group['price_close'].iloc[0]) - 1 # Fallback for WDC

        # 3m Fast Momentum (The Spark)
        mom_3m = (p_now / p_3m) - 1

        # D. ELITE FACTORS
        # 1. RISK-ADJUSTED (Standard Institutional)
        adj_mom = mom_12m / (vol + 1e-6)
        
        # 2. ACCELERATION (Freshness)
        # Is the car speeding up? High accel = Fresh breakout.
        acceleration = mom_3m - mom_12m
        
        # 3. MOMENTUM QUALITY (Quiet vs Loud)
        # sign(Return) * [% Days Positive - % Days Negative]
        pos_days = (group['returns'] > 0).sum()
        neg_days = (group['returns'] < 0).sum()
        inf_discr = np.sign(mom_12m) * (abs(pos_days - neg_days) / available_days)

        results.append({
            'ticker': ticker,
            'mom_score': adj_mom,      # Persistence (Long)
            'mom_quality': inf_discr,   # Consistency (Quietness)
            'acceleration': acceleration, # Freshness (Early Entry)
            'annual_vol': vol,
            'near_high': p_now / group['price_close'].max()
        })

    return pd.DataFrame(results)

# --- 3. The "Elite 10" Rating Logic ---
def assign_production_rating(row):
    # Core variables
    score, eps_rev, mom = row.get('final_score', 0), row.get('eps_rev', 0), row.get('mom_score', 0)
    pe, peg, rev_growth = row.get('fwd_pe', 999), row.get('peg', 99), row.get('rev_growth', 0)
    op_margin = row.get('op_margin', 0)
    
    # NEW: Elite Early Entry metrics from calculate_momentum_metrics
    accel = row.get('acceleration', 0)
    near_high = row.get('near_high', 0)
    mom_3m = row.get('mom_3m', 0)

    # 1. EXIT TRIGGERS (Aggressive Capital Protection)
    if eps_rev < -0.03:    return "SELL (Estimate Decay)"
    if rev_growth < 0:      return "SELL (No Growth)"
    if mom < -0.10:        return "SELL (Trend Exhaustion)"

    # 2. THE "EARLY BIRD" SIGNAL (Emerging Momentum)
    # This catches stocks like WDC early. 
    # Criteria: High 3m speed + positive acceleration + very close to new highs.
    is_breakout = (near_high > 0.96) # Within 4% of 52-week high
    is_accelerating = (accel > 0.05) and (mom_3m > 0.10)
    
    if is_breakout and is_accelerating and peg < 1.5:
        return "STRONG BUY (Emerging Breakout)"

    # 3. HYPER-GROWTH EXCEPTION
    if rev_growth > 0.50 and mom > 0.25 and peg < 1.2:
        return "STRONG BUY (Hyper-Growth)"

    # 4. STRONG BUY (Elite Conviction)
    is_confluence = (eps_rev > 0.01) and (mom > 0.1)
    is_profitable = (op_margin > 0)
    is_fair_value = (peg < 1.8) and (pe < 60)

    if score > 0.42 and is_confluence and is_profitable and is_fair_value:
        return "STRONG BUY (Elite)"

    # 5. BUY (High Potential)
    if score > 0.35 and mom > 0.1 and peg < 2.0:
        return "BUY"

    # 6. HOLD/OVERVALUED
    if pe > 65 or peg > 3.0: return "HOLD (Overvalued)"
    if mom < 0:              return "HOLD (Consolidation)"
    
    return "HOLD"

# --- 4. Main Pipeline Funnel ---
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_today_best_buys(engine, initial_pool_size=800, final_top_n=500):
    # Step A: Fetch Broad Universe
    df = pd.read_sql("SELECT DISTINCT ON (ticker) ticker, sma_252, vol_20, rsi_14 FROM statistics ORDER BY ticker, timestamp DESC", engine)
    if df.empty: return None, None

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
    def z_score(s): return (s - s.mean()) / (s.std() + 1e-6)
    
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
            'ticker', 'sector', 'rating', 'final_score', 'eps_rev', 'mom_score', 'peg', 'fwd_pe', 'rev_growth', 'op_margin', 'near_high', 'current_ratio', 'debt_to_equity', 'roe', 'profit_margin', 'fcf_yield'
        ]

        print("\n" + "="*50)
        print("--- NEW ALPHA DISCOVERIES ---")
        print("="*50)
        print(picks[display_cols].to_string(index=False))

        print("\n" + "="*50)
        print("--- CURRENT PORTFOLIO AUDIT ---")
        print("="*50)
        print(status[display_cols].to_string(index=False))
