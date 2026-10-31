"""Tests for the MACD confirmation screen logic."""
import pandas as pd
import numpy as np
import pandas_ta as ta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'etl'))
from importlib import import_module
ratings_mod = import_module('03_generate_production_ratings')


def _make_synthetic_closes(up_trend=True, n_days=400):
    """Generate synthetic close prices with known MACD behavior.
    
    If up_trend=True: prices rise over the series (MACD positive at end)
    If up_trend=False: prices fall over the series (MACD negative at end)
    """
    np.random.seed(42)
    base = np.linspace(100, 100 + (100 if up_trend else -100), n_days)
    noise = np.random.randn(n_days) * 2
    return pd.Series(base + noise)


def test_daily_macd_positive_on_uptrend():
    """Daily MACD should be positive when prices are rising."""
    closes = _make_synthetic_closes(up_trend=True, n_days=400)
    macd_df = ta.macd(closes, fast=12, slow=26, signal=9, talib=False)
    macd_val = macd_df.iloc[-1, 0]
    assert macd_val > 0, f"Expected positive MACD on uptrend, got {macd_val}"


def test_daily_macd_negative_on_downtrend():
    """Daily MACD should be negative when prices are falling."""
    closes = _make_synthetic_closes(up_trend=False, n_days=400)
    macd_df = ta.macd(closes, fast=12, slow=26, signal=9, talib=False)
    macd_val = macd_df.iloc[-1, 0]
    assert macd_val < 0, f"Expected negative MACD on downtrend, got {macd_val}"


def test_weekly_macd_resample_shape():
    """Weekly resample should produce fewer points than daily."""
    np.random.seed(42)
    dates = pd.date_range('2025-01-01', periods=400, freq='B', tz='UTC')
    closes = pd.Series(np.cumsum(np.random.randn(400)) + 100, index=dates, name='price_close')
    
    weekly = closes.resample('W-FRI').last().dropna()
    
    assert len(weekly) < len(closes), "Weekly resample should have fewer points"
    assert len(weekly) >= 50, f"Expected at least ~57 weeks from 400 weekdays, got {len(weekly)}"


def test_weekly_macd_positive_on_uptrend():
    """Weekly MACD should be positive on a sustained uptrend."""
    np.random.seed(42)
    dates = pd.date_range('2025-01-01', periods=400, freq='B', tz='UTC')
    trend = np.linspace(100, 200, 400)
    noise = np.random.randn(400) * 3
    closes = pd.Series(trend + noise, index=dates, name='price_close')
    
    weekly = closes.resample('W-FRI').last().dropna()
    macd_df = ta.macd(weekly, fast=12, slow=26, signal=9, talib=False)
    macd_val = macd_df.iloc[-1, 0]
    
    assert macd_val > 0, f"Expected positive weekly MACD on uptrend, got {macd_val}"


def test_empty_picks_returns_empty():
    """screen_macd_setup returns empty DataFrame when picks_df is empty."""
    picks_df = pd.DataFrame({'ticker': [], 'rating': []})
    result = ratings_mod.screen_macd_setup(picks_df, None)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_no_ticker_column_raises_keyerror():
    """screen_macd_setup raises KeyError if 'ticker' column is missing."""
    picks_df = pd.DataFrame({'rating': ['BUY']})
    import pytest
    with pytest.raises(KeyError):
        ratings_mod.screen_macd_setup(picks_df, None)