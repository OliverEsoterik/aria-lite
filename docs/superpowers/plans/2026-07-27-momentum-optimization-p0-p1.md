# Momentum Algorithm Optimization: P0 + P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two fine-grain optimizations to the momentum algorithm — Yang-Zhang range-based volatility estimator (P0) and multi-lookback momentum combination (P1).

**Architecture:** Three files need changes — the DB statistics engine (`02_compute_statistics.py`), the production ratings pipeline (`03_generate_production_ratings.py`), and the standalone scoring tool (`score_tickers.py`). Each change is a surgical replacement of a specific calculation, not a structural rewrite.

**Tech Stack:** Python 3, pandas, numpy, pandas_ta, yfinance, SQLAlchemy

**Key constraint:** No structural changes. Every changed line must trace directly to either P0 or P1. No drive-by refactors.

---

## Database Schema Context

The `market_prices` table already has OHLC columns:
```sql
price_open      NUMERIC(24, 8),
price_high      NUMERIC(24, 8),
price_low       NUMERIC(24, 8),
price_close     NUMERIC(24, 8)  NOT NULL,
price_adjusted  NUMERIC(24, 8),
```

The `statistics` table has `vol_20 DOUBLE PRECISION` — this column will be reused for the Yang-Zhang volatility.

## Yang-Zhang Volatility Estimator (P0)

The Yang-Zhang estimator (2000) combines overnight variance, intraday variance, and the Rogers-Satchell range estimator for 7-8x more efficient volatility estimation than close-to-close:

```
σ_yz² = σ_o² + k * σ_c² + (1 - k) * σ_rs²

where:
σ_o² = var(ln(O_i / C_{i-1}))          # overnight variance
σ_c² = var(ln(C_i / O_i))              # intraday variance
σ_rs² = E[ln(H_i/C_i)*ln(H_i/O_i) + ln(L_i/C_i)*ln(L_i/O_i)]  # Rogers-Satchell
k = 0.34 / (1.34 + (n+1)/(n-1))        # optimal weighting parameter
Annualized: σ_yz = sqrt(σ_yz² * 252)
```

## Multi-Lookback Momentum (P1)

Combine three momentum lookback windows (3m, 6m, 12m) with a consistent definition (skip last month to avoid short-term reversal):

```python
mom_3m = (p_1m / p_3m) - 1   # 3-1 month
mom_6m = (p_1m / p_6m) - 1   # 6-1 month
mom_12m = (p_1m / p_12m) - 1  # 12-1 month
mom_combined = 0.3 * mom_3m + 0.3 * mom_6m + 0.4 * mom_12m
```

---

## Task 1: Yang-Zhang in `02_compute_statistics.py`

**Files:**
- Modify: `src/etl/02_compute_statistics.py`

**Interfaces:**
- Consumes: `market_prices` table (OHLC columns already exist)
- Produces: `vol_20` column in `statistics` table (now Yang-Zhang based)

**Rationale for changes:**
- The current query only fetches `price_close` and `price_adjusted`. It needs `price_open`, `price_high`, `price_low` for the Yang-Zhang estimator.
- The current `vol_20` calculation uses close-to-close log returns. This needs to be replaced with the Yang-Zhang function.
- The `calculate_metrics` function operates on one ticker at a time (called per ticker from `process_ticker_batch`), so the Yang-Zhang function operates on individual ticker DataFrames.

- [ ] **Step 1: Extend the SQL query to fetch OHLC data**

Change the query in `process_ticker_batch` from:
```python
query_prices = text("""
    SELECT timestamp, ticker, price_close, price_adjusted
    FROM market_prices 
    WHERE ticker = :ticker 
    AND timestamp >= :start_date
    ORDER BY timestamp ASC
""")
```
to:
```python
query_prices = text("""
    SELECT timestamp, ticker, price_open, price_high, price_low, price_close, price_adjusted
    FROM market_prices 
    WHERE ticker = :ticker 
    AND timestamp >= :start_date
    ORDER BY timestamp ASC
""")
```

- [ ] **Step 2: Add the Yang-Zhang volatility function**

Add this function before `calculate_metrics`:

```python
def yang_zhang_vol(df, period=20, min_periods=10, annualize=True):
    """
    Yang-Zhang range-based volatility estimator.
    Combines overnight variance, intraday variance, and Rogers-Satchell
    for 7-8x more efficient estimation than close-to-close.
    
    Parameters
    ----------
    df : DataFrame with columns: price_open, price_high, price_low, price_close
    period : int, rolling window size (default 20)
    min_periods : int, minimum periods for rolling calc (default 10)
    annualize : bool, multiply by sqrt(252) if True
    
    Returns
    -------
    Series : Yang-Zhang annualized volatility
    """
    # Overnight returns: ln(Open_t / Close_{t-1})
    log_oc = np.log(df['price_open'] / df['price_close'].shift(1))
    # Intraday returns: ln(Close_t / Open_t)
    log_co = np.log(df['price_close'] / df['price_open'])
    
    # Rogers-Satchell component
    log_ho = np.log(df['price_high'] / df['price_open'])
    log_lo = np.log(df['price_low'] / df['price_open'])
    log_hc = np.log(df['price_high'] / df['price_close'])
    log_lc = np.log(df['price_low'] / df['price_close'])
    rs = log_ho * log_hc + log_lo * log_lc
    
    # Rolling variances
    o_var = log_oc.rolling(period, min_periods=min_periods).var()
    c_var = log_co.rolling(period, min_periods=min_periods).var()
    rs_mean = rs.rolling(period, min_periods=min_periods).mean()
    
    # Optimal weighting parameter k
    k = 0.34 / (1.34 + (period + 1) / (period - 1))
    
    # Yang-Zhang variance
    yz_var = o_var + k * c_var + (1 - k) * rs_mean
    
    # Clamp negative values to zero (can happen with very small samples)
    yz_var = yz_var.clip(lower=0)
    
    vol = np.sqrt(yz_var)
    if annualize:
        vol = vol * np.sqrt(252)
    return vol
```

- [ ] **Step 3: Replace the vol_20 calculation in `calculate_metrics`**

Change:
```python
# 5. ROLLING MOMENTS (Volatility, Skew, Kurtosis)
g_ret = df.groupby('ticker')['log_return']

df['vol_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).std() * np.sqrt(252))
df['skew_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).skew())
df['kurt_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).kurt())
```

to:
```python
# 5. ROLLING MOMENTS (Volatility, Skew, Kurtosis)
g_ret = df.groupby('ticker')['log_return']

# Yang-Zhang range-based volatility (uses OHLC, 7-8x more efficient)
df['vol_20'] = grouped.apply(lambda g: yang_zhang_vol(g, period=20, min_periods=10)).reset_index(level=0, drop=True)
df['skew_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).skew())
df['kurt_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).kurt())
```

**IMPORTANT:** The `grouped` variable is already defined earlier as `grouped = df.groupby('ticker')`. It must be used instead of `g_ret` because `yang_zhang_vol` needs all OHLC columns, not just `log_return`. The `g_ret` variable is still needed for `skew_20` and `kurt_20`.

- [ ] **Step 4: Update the upsert column list**

The `vol_20` column is already in the upsert list, so no change needed here:
```python
cols = ['timestamp', 'ticker', 'rsi_14', 'sma_252', 'log_return', 'vol_20', 'mdd_20', 'skew_20', 'kurt_20']
```

This stays the same — `vol_20` now contains Yang-Zhang volatility instead of close-to-close vol.

---

## Task 2: Yang-Zhang in `03_generate_production_ratings.py`

**Files:**
- Modify: `src/etl/03_generate_production_ratings.py`

**Interfaces:**
- Consumes: `market_prices` table (OHLC columns)
- Produces: `annual_vol` in momentum metrics (now Yang-Zhang based)

**Rationale:** The `calculate_momentum_metrics()` function computes its own `annual_vol` from the full price history (not from the pre-computed `vol_20` in statistics). This vol is used in the denominator of `mom_score = mom_12m / vol`. It needs to use the Yang-Zhang estimator.

- [ ] **Step 1: Add the `yang_zhang_vol` function**

Add the same `yang_zhang_vol` function (copy from Task 1) before `calculate_momentum_metrics`. The function is a pure computation with no dependencies, so copying is correct.

- [ ] **Step 2: Extend the query to fetch OHLC data**

Change the query in `calculate_momentum_metrics` from:
```python
query = text("""
    SELECT ticker, price_close, timestamp FROM market_prices 
    WHERE ticker IN :tickers AND timestamp >= NOW() - INTERVAL '400 days'
    ORDER BY ticker, timestamp ASC
""")
```
to:
```python
query = text("""
    SELECT ticker, price_open, price_high, price_low, price_close, timestamp 
    FROM market_prices 
    WHERE ticker IN :tickers AND timestamp >= NOW() - INTERVAL '400 days'
    ORDER BY ticker, timestamp ASC
""")
```

- [ ] **Step 3: Replace the vol calculation in the ticker loop**

In the `for ticker, group in hist_df.groupby('ticker'):` loop, change:

```python
# A. VOLATILITY & RETURNS
group['returns'] = group['price_close'].pct_change()
vol = group['returns'].std() * np.sqrt(252) # Annualized Vol
```

to:
```python
# A. VOLATILITY & RETURNS
group['returns'] = group['price_close'].pct_change()
vol = yang_zhang_vol(group, period=len(group), min_periods=10).iloc[-1] # Yang-Zhang annualized vol
```

**Note:** Using `period=len(group)` computes the vol over the full available history rather than a fixed 20-day window. This matches the original intent of computing a single annualized vol per ticker (the original also used `.std() * sqrt(252)` over the full history). The `.iloc[-1]` takes the last value of the rolling estimator.

---

## Task 3: Yang-Zhang in `score_tickers.py`

**Files:**
- Modify: `skills/portfolio-construction/tools/score_tickers.py`

**Interfaces:**
- Consumes: yfinance OHLC data (already available via `auto_adjust=True`)
- Produces: `annual_vol` in momentum metrics (now Yang-Zhang based)

- [ ] **Step 1: Add the `yang_zhang_vol` function**

Add the same function before `get_momentum`. Same function as Task 1, adapted for a DataFrame with standard column names.

- [ ] **Step 2: Replace the vol calculation in `get_momentum`**

In `get_momentum`, change:
```python
close = hist['Close'].values.flatten()
n = len(close)

returns = np.diff(close) / close[:-1]
vol = np.std(returns) * np.sqrt(252)
```
to:
```python
close = hist['Close'].values.flatten()
n = len(close)

# Build OHLC DataFrame for Yang-Zhang
yz_df = pd.DataFrame({
    'price_open': hist['Open'].values.flatten(),
    'price_high': hist['High'].values.flatten(),
    'price_low': hist['Low'].values.flatten(),
    'price_close': close,
})
vol = yang_zhang_vol(yz_df, period=n, min_periods=10).iloc[-1]
```

- [ ] **Step 3: Fix the `returns` variable for downstream usage**

The `returns` variable is also used later for `pos_days` and `neg_days`. Keep the `returns` calculation but move it after the vol calculation:

```python
# Keep returns for quality metric
returns = np.diff(close) / close[:-1]
```

---

## Task 4: Multi-Lookback Momentum in `03_generate_production_ratings.py`

**Files:**
- Modify: `src/etl/03_generate_production_ratings.py`

**Interfaces:**
- Consumes: `mom_3m`, `mom_6m`, `mom_12m` from price data
- Produces: `mom_score` (now combined momentum), `mom_3m`, `mom_6m`, `mom_12m` in result dict

**IMPORTANT: Fix the pre-existing bug where `mom_3m` is not returned in the result dict, causing `assign_production_rating` to always see `mom_3m = 0`.**

- [ ] **Step 1: Add `p_6m` price point and compute `mom_6m`**

In `calculate_momentum_metrics`, add after the existing price points:

```python
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
```

- [ ] **Step 2: Compute individual momentum at each lookback and combine**

Replace the current momentum computation block:

```python
# C. MOMENTUM SPEEDS
# 12-1 Institutional Momentum (Persistence)
if available_days >= 252:
    p_12m = group['price_close'].iloc[-252]
    mom_12m = (p_1m / p_12m) - 1
else:
    mom_12m = (p_1m / group['price_close'].iloc[0]) - 1 # Fallback for WDC

# 3m Fast Momentum (The Spark)
mom_3m = (p_now / p_3m) - 1
```

with:

```python
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
```

**Definition change:** `mom_3m` changes from `(p_now / p_3m) - 1` to `(p_1m / p_3m) - 1` for consistency with the other lookbacks. This means 3m momentum now also skips the last month, matching the standard Jagadeesh-Titman (1993) methodology.

- [ ] **Step 3: Update acceleration formula**

Change acceleration to use the new `mom_3m` definition consistently:

```python
# D. ELITE FACTORS
# 1. RISK-ADJUSTED (Standard Institutional)
adj_mom = mom_combined / (vol + 1e-6)

# 2. ACCELERATION (Freshness)
# Is the car speeding up? High accel = Fresh breakout.
# Use the current 3m return (including last month) vs 12m to capture the spark
# This is the only measure that includes the most recent month.
acceleration = (p_now / p_3m) - 1 - mom_12m
```

- [ ] **Step 4: Update the result dict to include all components**

Add `mom_3m`, `mom_6m`, `mom_12m` to the returned dict:

```python
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
```

**This fixes the pre-existing bug** where `mom_3m` was referenced in `assign_production_rating` but never returned.

---

## Task 5: Multi-Lookback Momentum in `score_tickers.py`

**Files:**
- Modify: `skills/portfolio-construction/tools/score_tickers.py`

- [ ] **Step 1: Add `p_6m` and compute multi-lookback momentum**

In `get_momentum`, after the existing price points, add:

```python
p_now = close[-1]
p_1m = close[-22] if n >= 22 else close[0]
p_3m = close[-63] if n >= 63 else close[0]
p_6m = close[-126] if n >= 126 else close[0]
p_12m = close[-252] if n >= 252 else close[0]

# Multi-lookback momentum (skip last month to avoid reversal)
mom_3m = (p_1m / p_3m) - 1
mom_6m = (p_1m / p_6m) - 1
mom_12m = (p_1m / p_12m) - 1

# Combined momentum
mom_combined = 0.3 * mom_3m + 0.3 * mom_6m + 0.4 * mom_12m

adj_mom = mom_combined / (vol + 1e-6)

# Acceleration (now includes last month to capture freshness)
acceleration = (p_now / p_3m) - 1 - mom_12m
```

- [ ] **Step 2: Add `mom_6m` to the return dict**

```python
return {
    'ticker': ticker,
    'mom_score': adj_mom,
    'mom_quality': inf_discr,
    'acceleration': acceleration,
    'annual_vol': vol,
    'near_high': p_now / np.max(close),
    'mom_3m': mom_3m,
    'mom_6m': mom_6m,
    'rsi_14': rsi,
    'vol_20': vol_20,
}
```

---

## Verification

After all changes, run these verifications:

- [ ] **Verify imports**: `python3 -c "from src.etl import compute_statistics"` (or equivalent import check)
- [ ] **Verify syntax**: `python3 -m py_compile src/etl/02_compute_statistics.py && python3 -m py_compile src/etl/03_generate_production_ratings.py && python3 -m py_compile skills/portfolio-construction/tools/score_tickers.py`
- [ ] **Verify Yang-Zhang function**: `python3 -c "import numpy as np; import pandas as pd; from src.etl.compute_statistics import yang_zhang_vol"` (or test the function standalone)
- [ ] **Verify no regressions**: Run the ETL pipeline if possible, or at minimum verify the standalone `score_tickers.py` works on a small set of tickers

---

## File-by-File Change Summary

### `src/etl/02_compute_statistics.py`
- **Query change**: Add `price_open, price_high, price_low` to SELECT
- **New function**: `yang_zhang_vol()` — range-based volatility estimator
- **vol_20 change**: Replace close-to-close rolling std with Yang-Zhang

### `src/etl/03_generate_production_ratings.py`
- **New function**: `yang_zhang_vol()` — copy from 02
- **Query change**: Add `price_open, price_high, price_low` to SELECT
- **vol change**: Replace `.std() * sqrt(252)` with Yang-Zhang
- **Multi-lookback**: Add `p_6m`, compute `mom_6m`, combine with 3m+12m
- **Bug fix**: Return `mom_3m` in result dict (was missing)
- **Acceleration**: Keep using `(p_now / p_3m) - 1 - mom_12m` for freshness

### `skills/portfolio-construction/tools/score_tickers.py`
- **New function**: `yang_zhang_vol()` — copy from 02
- **vol change**: Replace `.std() * sqrt(252)` with Yang-Zhang
- **Multi-lookback**: Add `p_6m`, compute `mom_6m`, combine
- **Return dict**: Add `mom_6m`