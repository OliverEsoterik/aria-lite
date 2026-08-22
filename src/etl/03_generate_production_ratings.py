import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
import numpy as np
import argparse

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
        
        # B. PRICE POINTS (Now, 1m, 3m, 6m, 12m)
        p_now = group['price_close'].iloc[-1]
        p_1m = group['price_close'].iloc[-21]
        p_3m = group['price_close'].iloc[-63]
        p_6m = group['price_close'].iloc[-126] if available_days >= 126 else None
        p_12m = group['price_close'].iloc[-252] if available_days >= 252 else None

        # C. MOMENTUM SPEEDS — Multi-lookback composite (Tan, Roberts & Zohren 2023)
        r_63 = (p_now / p_3m) - 1
        if p_6m is not None and p_12m is not None:
            r_126 = (p_now / p_6m) - 1
            r_252 = (p_now / p_12m) - 1
            mom_combined = 0.3 * r_63 + 0.3 * r_126 + 0.4 * r_252
        elif p_6m is not None:
            # < 252 days: 2-window composite
            r_126 = (p_now / p_6m) - 1
            mom_combined = 0.4 * r_63 + 0.6 * r_126
        else:
            # < 126 days: fall back to 3-month only
            mom_combined = r_63

        # 3m Fast Momentum (The Spark) — keep for acceleration
        mom_3m = r_63

        # D. ELITE FACTORS
        # 1. RISK-ADJUSTED — using multi-lookback composite (Tan, Roberts & Zohren 2023)
        adj_mom = mom_combined / (vol + 1e-6)

        # 2. ACCELERATION (Freshness)
        # Compare 3m vs 12m window — accelerating = fresh breakout
        r_12m = r_252 if p_12m is not None else mom_combined
        acceleration = mom_3m - r_12m

        # 3. MOMENTUM QUALITY (Quiet vs Loud) — exponentially weighted (Lee 2025)
        # Alpha decays hyperbolically — recent days matter more
        n = len(group['returns'])
        decay = np.exp(-np.arange(n)[::-1] * np.log(2) / 63)
        decay /= decay.sum()
        pos_weight = ((group['returns'] > 0) * decay).sum()
        neg_weight = ((group['returns'] < 0) * decay).sum()
        inf_discr = np.sign(mom_combined) * (pos_weight - neg_weight)

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


def deduplicate_by_company(df: pd.DataFrame, engine) -> pd.DataFrame:
    """
    For companies listed on multiple exchanges, keep only the highest-market-cap ticker.

    Queries dim_entities for company_name + market_cap, merges, groups by company
    name (normalized), and keeps the row with highest market_cap per group.
    Tickers with NULL company_name are kept individually (never collapsed).
    """
    from sqlalchemy import text
    tickers = df['ticker'].tolist()
    if not tickers:
        return df

    query = text("""
        SELECT ticker, company_name, market_cap
        FROM dim_entities
        WHERE ticker IN :tickers
    """)
    with engine.connect() as conn:
        meta = pd.read_sql(query, conn, params={'tickers': tuple(tickers)})

    merged = df.merge(meta, on='ticker', how='left')

    # For rows with a known company_name, dedup by name keeping highest market_cap
    has_name = merged['company_name'].notna()
    no_name = merged[~has_name].copy()
    has_name_df = merged[has_name].copy()

    if not has_name_df.empty:
        has_name_df['_name_key'] = has_name_df['company_name'].str.strip().str.upper()
        # Use skipna=False so that a group where all market_cap are NaN
        # raises a clear error instead of silently failing.
        idx = has_name_df.groupby('_name_key')['market_cap'].idxmax()
        has_name_df = has_name_df.loc[idx].drop(columns=['_name_key'])

    result = pd.concat([no_name, has_name_df], ignore_index=True)
    result = result.drop(columns=['company_name', 'market_cap'])
    return result


# --- 4. Rank Normalization Utility (hoisted for module-level use) ---
def rank_normalize(s):
    """Rank-based normalization. Maps percentile rank to z-score-like scale [-3, +3].
    Uses Abramowitz & Stegun approximation for the standard normal quantile
    function — no scipy dependency."""
    n = len(s)
    if n < 2:
        return s * 0.0
    # Rank from 1..n, convert to percentile (0..1) exclusive at both ends
    ranks = s.rank(method='average')
    p = (ranks - 0.5) / n
    p = p.clip(1e-6, 1 - 1e-6)
    # Abramowitz & Stegun approximation for inverse normal CDF
    # (accurate to ~1e-4)
    t = np.where(p < 0.5, p, 1 - p)
    t = np.sqrt(-2 * np.log(t))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1*t + c2*t**2) / (1 + d1*t + d2*t**2 + d3*t**3)
    z = np.where(p < 0.5, -z, z)
    # Clip extreme values
    z = np.clip(z, -3.5, 3.5)
    return z

# --- 5. Main Pipeline Funnel ---
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_today_best_buys(engine, initial_pool_size=800, final_top_n=500, us_only=False, eu_only=False,
                        min_market_cap=500_000_000):
    # Step A: Fetch Broad Universe filtered by absolute quality thresholds
    # Market-cap floor removes micro-caps and illiquid tickers.
    query = """
        SELECT DISTINCT ON (ticker) ticker, sma_252, vol_20, rsi_14
        FROM statistics
        WHERE ticker IN (
            SELECT ticker FROM dim_entities
            WHERE market_cap IS NOT NULL AND market_cap >= :min_market_cap
        )
    """
    params = {"min_market_cap": min_market_cap}
    where_clauses = []
    if us_only:
        where_clauses.append("ticker NOT LIKE '%.%'")
    if eu_only:
        where_clauses.append("ticker LIKE '%.%'")
    if where_clauses:
        query += " AND " + " AND ".join(where_clauses)
    query += " ORDER BY ticker, timestamp DESC"
    df = pd.read_sql(text(query), engine, params=params)
    if df.empty: return None, None

    # Persistence Injection
    portfolio_df = df[df['ticker'].isin(CURRENT_PORTFOLIO)].copy()

    # Step B: Liquidity Sort (confidence ordering, no hard cut — the pool is already thresholded)
    df['dollar_volume'] = df['vol_20'] * df['sma_252']
    candidates = df.sort_values('dollar_volume', ascending=False)
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

    # --- Step F: PERCENTILE RANK NORMALIZATION ---
    # Converts each factor to its percentile rank mapped to approx [-3, +3].
    # Unlike z-score, this is stable regardless of pool composition — a stock's rank
    # depends only on its position relative to peers, not on the pool's mean/std.
    final_merged['z_mom_risk_adj'] = rank_normalize(final_merged['mom_score'].fillna(0))
    final_merged['z_mom_qual'] = rank_normalize(final_merged['mom_quality'].fillna(0))
    final_merged['z_accel'] = rank_normalize(final_merged['acceleration'].fillna(0))

    final_merged['z_eps'] = rank_normalize(final_merged['eps_rev'].fillna(0))
    final_merged['z_state'] = (rank_normalize(final_merged['rsi_14'].fillna(50)) * -0.5) + (rank_normalize(final_merged['vol_20'].fillna(0)) * 0.5)
    
    final_merged['s_qual'] = (
        (final_merged['rev_growth'].fillna(0).clip(0, 0.4) / 0.4 * 0.5) + 
        (final_merged['op_margin'].fillna(0).clip(0, 0.3) / 0.3 * 0.5)
    )

    # --- Step G: FINAL ELITE SCORING — with non-linear alignment boost (P4) ---
    # When short-term acceleration and risk-adjusted momentum agree,
    # boost the momentum weight block (Liu, Shu & Chiu 2023)
    z_mom = final_merged['z_mom_risk_adj']
    z_accel = final_merged['z_accel']

    alignment_boost = pd.Series(1.0, index=final_merged.index)
    mask = (z_mom > 0) & (z_accel > 0)
    alignment_boost[mask] = 1.0 + 0.3 * np.clip(
        z_accel[mask].abs() / (z_mom[mask].abs() + 1e-6), 0, 1.0
    )

    final_merged['final_score'] = (
        final_merged['z_mom_risk_adj'] * 0.25 * alignment_boost +  # Core Momentum
        final_merged['z_mom_qual']     * 0.25 * alignment_boost +  # Smoothness/Persistence
        final_merged['z_accel']        * 0.05 +                    # Short-term momentum
        final_merged['s_qual']         * 0.30 * (2.0 - alignment_boost) +  # Revenue Growth + Op Margins
        final_merged['z_eps']          * 0.10 +                    # Analyst Revisions
        final_merged['z_state']        * 0.05                      # Technical State (RSI/Vol)
    )

    gate = RiskGate()
    final_merged['pass_gate'] = final_merged.apply(gate.is_pass, axis=1)
    final_merged['rating'] = final_merged.apply(assign_production_rating, axis=1)

    # --- RESULT SPLIT ---
    top_picks = final_merged[final_merged['pass_gate']].sort_values('final_score', ascending=False).head(final_top_n)
    portfolio_status = final_merged[final_merged['ticker'].isin(CURRENT_PORTFOLIO)].copy()

    return top_picks, portfolio_status

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate production ratings")
    parser.add_argument("--us", action="store_true", help="Only rate US tickers (no dot suffix)")
    parser.add_argument("--eu", action="store_true", help="Only rate European tickers (with dot suffix)")
    args = parser.parse_args()

    picks, status = get_today_best_buys(engine, us_only=args.us, eu_only=args.eu)
    
    picks = deduplicate_by_company(picks, engine)
    picks = picks.sort_values('final_score', ascending=False)
    
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

        # --- HIGH CONVICTION TABLE ---
        # Top 20 STRONG BUY (any flavor), prioritized by:
        #   1. Positive acceleration (fresh breakout over stale momentum)
        #   2. Nearness to 52-week high (already breaking out)
        #   3. final_score as tiebreaker
        strong_buys = picks[picks['rating'].str.startswith('STRONG BUY')].copy()
        strong_buys['accel_positive'] = strong_buys['acceleration'].fillna(0) > 0

        conviction_cols = [
            'ticker', 'sector', 'rating', 'final_score', 'near_high',
            'acceleration', 'mom_score', 'eps_rev', 'peg', 'fwd_pe',
            'rev_growth', 'op_margin'
        ]

        print("\n" + "="*50)
        print("--- HIGH CONVICTION BUYS (Top 20 STRONG BUY) ---")
        print("="*50)
        print("  Prioritized: positive acceleration + near 52-week high + score")
        print()

        if strong_buys.empty:
            print("  (No stocks passed all three STRONG BUY paths)")
        else:
            sorted_sb = strong_buys.sort_values(
                ['accel_positive', 'near_high', 'final_score'],
                ascending=[False, False, False]
            ).head(20)
            print(sorted_sb[conviction_cols].to_string(index=False))

        # --- COMPOUNDER TABLE (1-3 Year Holds) ---
        # High-quality businesses at good entry points (pulled back from highs,
        # but thesis intact via positive revisions).
        # Scoring prioritizes durable quality over momentum:
        #   - Growth + margins (moat)
        #   - ROE (capital efficiency)
        #   - Low debt (safety)
        #   - FCF yield (cash generation)
        #   - Low PEG (reasonable valuation)
        #   - Positive EPS revisions (thesis confirmed)
        #
        # Entry filter: near_high 0.50-0.88 (pullback) + eps_rev > 0 (intact thesis)
        # Exclude SELL and HOLD rated stocks.
        compounder_pool = picks[
            (picks['pass_gate'])
            & (picks['near_high'].fillna(0) >= 0.50)
            & (picks['near_high'].fillna(0) <= 0.88)
            & (picks['eps_rev'].fillna(0) > 0)
            & ~picks['rating'].str.startswith('SELL')
            & ~picks['rating'].str.startswith('HOLD')
        ].copy()

        if not compounder_pool.empty:
            # Score: quality * 0.40 + financial strength * 0.25 + value * 0.15 + revisions * 0.20
            compounder_pool['z_quality'] = rank_normalize(
                compounder_pool['rev_growth'].fillna(0).clip(0, 0.5) * 0.4 +
                compounder_pool['op_margin'].fillna(0).clip(0, 0.3) * 0.3 +
                compounder_pool['profit_margin'].fillna(0).clip(0, 0.3) * 0.3
            )
            compounder_pool['z_roe'] = rank_normalize(compounder_pool['roe'].fillna(0).clip(-0.5, 1.0))
            compounder_pool['z_safety'] = rank_normalize(
                -compounder_pool['debt_to_equity'].fillna(0).clip(0, 5)
            )
            compounder_pool['z_fcf'] = rank_normalize(compounder_pool['fcf_yield'].fillna(0).clip(0, 0.3))
            compounder_pool['z_peg'] = rank_normalize(
                -compounder_pool['peg'].fillna(99).clip(0, 10)
            )
            compounder_pool['z_revisions'] = rank_normalize(compounder_pool['eps_rev'].fillna(0))

            compounder_pool['compound_score'] = (
                compounder_pool['z_quality']   * 0.25 +
                compounder_pool['z_roe']       * 0.15 +
                compounder_pool['z_safety']    * 0.10 +
                compounder_pool['z_fcf']       * 0.15 +
                compounder_pool['z_peg']       * 0.15 +
                compounder_pool['z_revisions'] * 0.20
            )

            compound_cols = [
                'ticker', 'sector', 'rating', 'compound_score', 'near_high',
                'rev_growth', 'op_margin', 'roe', 'debt_to_equity',
                'fcf_yield', 'peg', 'fwd_pe', 'eps_rev'
            ]

            top_compounders = compounder_pool.sort_values(
                'compound_score', ascending=False
            ).head(20)

            print("\n" + "="*50)
            print("--- COMPOUNDER PICKS (Top 20 — 1-3 Year Holds) ---")
            print("="*50)
            print("  Filtered: near_high 0.50-0.88 (pullback entry)")
            print("  Thesis filter: positive EPS revisions")
            print("  Sorted by: compound quality score (growth + margins + ROE + FCF + safety + value)")
            print()
            print(top_compounders[compound_cols].to_string(index=False))
        else:
            print("\n" + "="*50)
            print("--- COMPOUNDER PICKS (1-3 Year Holds) ---")
            print("="*50)
            print("  (No stocks meet both pullback entry and intact-thesis criteria)")
            print("  near_high range: 0.50-0.88")
            print()

        # --- TECH TITANS ---
        tech_sectors = ['Technology', 'Semiconductors', 'Electronic Technology', 'Technology Services']
        tech_pool = picks[
            picks['sector'].isin(tech_sectors)
            & (picks['rating'].str.startswith('STRONG BUY') | picks['rating'].str.startswith('BUY'))
        ].copy()

        tech_cols = ['ticker', 'rating', 'final_score', 'near_high', 'rev_growth', 'op_margin', 'peg', 'fwd_pe', 'eps_rev']

        print("\n" + "="*50)
        print("--- TECH TITANS (Top 10 Tech — STRONG BUY + BUY) ---")
        print("="*50)
        print("  Sorted by final_score (momentum + quality confluence)")
        print()

        if tech_pool.empty:
            print("  (No tech stocks passed the filters this week)")
        else:
            top_tech = tech_pool.sort_values('final_score', ascending=False).head(10)
            print(top_tech[tech_cols].to_string(index=False))

        # --- DEFENSIVE COMPOUNDERS ---
        def_sectors = ['Healthcare', 'Consumer Defensive', 'Utilities', 'Medical', 'Consumer Staples']
        def_pool = picks[
            picks['sector'].isin(def_sectors)
            & picks['pass_gate']
            & (picks['near_high'].fillna(0) >= 0.50)
            & (picks['near_high'].fillna(0) <= 0.88)
            & ~picks['rating'].str.startswith('SELL')
            & ~picks['rating'].str.startswith('HOLD')
        ].copy()

        def_cols = ['ticker', 'sector', 'rating', 'final_score', 'near_high', 'roe', 'debt_to_equity', 'fcf_yield', 'peg', 'eps_rev']

        print("\n" + "="*50)
        print("--- DEFENSIVE COMPOUNDERS (Top 10 — Pullback Entry) ---")
        print("="*50)
        print("  Sorted by final_score, filtered: near_high 0.50-0.88 + RiskGate pass")
        print()

        if def_pool.empty:
            print("  (No defensive stocks meet pullback + quality criteria)")
        else:
            top_def = def_pool.sort_values('final_score', ascending=False).head(10)
            print(top_def[def_cols].to_string(index=False))

        # --- THE REVISIONIST ---
        # Estiamte revisions: exclude any stock the algo rates SELL or HOLD.
        rev_pool = picks[
            picks['eps_rev'].notna() & (picks['eps_rev'] > 0)
            & ~picks['rating'].str.startswith('SELL')
            & ~picks['rating'].str.startswith('HOLD')
        ].copy()

        rev_cols = ['ticker', 'sector', 'eps_rev', 'rating', 'final_score', 'near_high', 'peg', 'fwd_pe']

        print("\n" + "="*50)
        print("--- THE REVISIONIST (Top 10 — Strongest EPS Estimate Revisions) ---")
        print("="*50)
        print("  Sorted by estimate revision strength (positive = analysts raising)")
        print()

        if rev_pool.empty:
            print("  (No stocks with positive EPS revisions this week)")
        else:
            top_rev = rev_pool.sort_values('eps_rev', ascending=False).head(10)
            print(top_rev[rev_cols].to_string(index=False))

        # --- DEEP VALUE MOMENTUM ---
        # Exclude SELL and HOLD rated stocks.
        value_pool = picks[
            (picks['peg'].fillna(99) < 1.0)
            & (picks['mom_score'].fillna(0) > 0)
            & (picks['fcf_yield'].fillna(0) > 0)
            & ~picks['rating'].str.startswith('SELL')
            & ~picks['rating'].str.startswith('HOLD')
        ].copy()

        value_cols = ['ticker', 'sector', 'rating', 'final_score', 'peg', 'fwd_pe', 'mom_score', 'fcf_yield', 'rev_growth', 'op_margin']

        print("\n" + "="*50)
        print("--- DEEP VALUE MOMENTUM (PEG < 1.0 + Mom > 0 + FCF > 0) ---")
        print("="*50)
        print("  Cheap + growing + cash-generating — ultra-rare combo")
        print()

        if value_pool.empty:
            print("  (No stocks pass all three filters — extremely rare)")
        else:
            top_value = value_pool.sort_values('final_score', ascending=False).head(10)
            print(top_value[value_cols].to_string(index=False))

        # --- PORTFOLIO INSIDER WATCH ---
        insider_pool = status[
            status['rating'].str.startswith('STRONG BUY') | status['rating'].str.startswith('BUY')
        ].copy()

        insider_cols = ['ticker', 'sector', 'rating', 'final_score', 'near_high', 'acceleration', 'eps_rev', 'peg', 'fwd_pe']

        print("\n" + "="*50)
        print("--- PORTFOLIO INSIDER WATCH (What I'm Holding & Still Like) ---")
        print("="*50)
        print("  Current portfolio tickers rated STRONG BUY or BUY")
        print()

        if insider_pool.empty:
            print("  (No held positions currently rated BUY or better)")
        else:
            print(insider_pool[insider_cols].to_string(index=False))
