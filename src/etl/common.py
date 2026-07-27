"""
Shared pure computation functions for the aria-lite ETL pipeline.

These functions are pure — no I/O, no DB, no API calls. They accept
DataFrames/dicts and return computed results. This module exists because
the same logic was copy-pasted across multiple files.
"""
import numpy as np
import pandas as pd

ANNUALIZATION_FACTOR = np.sqrt(252)


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


class RiskGate:
    """Risk filter that enforces minimum quality thresholds on tickers."""

    def __init__(self):
        self.min_price = 10.0
        self.min_op_margin = 0.05
        self.min_current_ratio = 0.8
        self.min_roe = -0.10

    def is_pass(self, row):
        try:
            if row.get('current_price', 0) < self.min_price:
                return False
            if row.get('op_margin', 0) < self.min_op_margin:
                return False
            if row.get('current_ratio', 0) < self.min_current_ratio:
                return False
            if row.get('roe', 0) < self.min_roe:
                return False
            if row.get('fwd_pe') is None:
                return False
            return True
        except Exception:
            return False


def assign_production_rating(row):
    """
    Assign a rating string based on the scoring model.

    Parameters
    ----------
    row : dict-like with keys: final_score, eps_rev, mom_score, fwd_pe,
          peg, rev_growth, op_margin, acceleration, near_high, mom_3m

    Returns
    -------
    str : Rating like "STRONG BUY (Elite)", "BUY", "HOLD", "SELL (...)"
    """
    # Core variables
    score = row.get('final_score', 0)
    eps_rev = row.get('eps_rev', 0)
    mom = row.get('mom_score', 0)
    pe = row.get('fwd_pe', 999) if row.get('fwd_pe') else 999
    peg = row.get('peg', 99) if row.get('peg') else 99
    rev_growth = row.get('rev_growth', 0)
    op_margin = row.get('op_margin', 0)

    # Early Entry metrics
    accel = row.get('acceleration', 0)
    near_high = row.get('near_high', 0)
    mom_3m = row.get('mom_3m', 0)

    # 1. EXIT TRIGGERS (Aggressive Capital Protection)
    if eps_rev < -0.03:
        return "SELL (Estimate Decay)"
    if rev_growth < 0:
        return "SELL (No Growth)"
    if mom < -0.10:
        return "SELL (Trend Exhaustion)"

    # 2. THE "EARLY BIRD" SIGNAL (Emerging Momentum)
    is_breakout = near_high > 0.96
    is_accelerating = accel > 0.05 and mom_3m > 0.10
    if is_breakout and is_accelerating and peg < 1.5:
        return "STRONG BUY (Emerging Breakout)"

    # 3. HYPER-GROWTH EXCEPTION
    if rev_growth > 0.50 and mom > 0.25 and peg < 1.2:
        return "STRONG BUY (Hyper-Growth)"

    # 4. STRONG BUY (Elite Conviction)
    is_confluence = eps_rev > 0.01 and mom > 0.1
    is_profitable = op_margin > 0
    is_fair_value = peg < 1.8 and pe < 60
    if score > 0.42 and is_confluence and is_profitable and is_fair_value:
        return "STRONG BUY (Elite)"

    # 5. BUY (High Potential)
    if score > 0.35 and mom > 0.1 and peg < 2.0:
        return "BUY"

    # 6. HOLD/OVERVALUED
    if pe > 65 or peg > 3.0:
        return "HOLD (Overvalued)"
    if mom < 0:
        return "HOLD (Consolidation)"

    return "HOLD"


def assign_rating(row):
    """Alias for assign_production_rating used by score_tickers.py."""
    return assign_production_rating(row)


def z_score(s):
    """Compute z-score normalization with safety epsilon."""
    return (s - s.mean()) / (s.std() + 1e-6)