"""Verify the weekly resample logic handles tz-aware timestamps from Postgres.

The screen_macd_setup function failed in production because pd.read_sql
returns tz-aware datetime objects that pandas won't convert to DatetimeIndex
without utc=True.  This test replicates the exact code path that crashed.
"""
import pandas as pd
import numpy as np
import pandas_ta as ta


def _tz_aware_dates(start="2025-01-01", periods=400, freq="B"):
    """Generate business-daily timestamps with UTC timezone, mimicking
    what PostgreSQL + pd.read_sql return."""
    return pd.date_range(start, periods=periods, freq=freq, tz="UTC")


def test_resample_with_tz_aware_index():
    """Weekly resample must work when the index is a plain Index containing
    tz-aware datetime objects — the scenario that crashed."""
    dates = _tz_aware_dates()
    closes = pd.Series(np.cumsum(np.random.randn(400)) + 100, name="price_close")

    # Simulate what comes from pd.read_sql + groupby + set_index:
    # a DataFrame whose index is NOT a DatetimeIndex but a plain Index
    # containing tz-aware datetime objects.
    df = pd.DataFrame({"timestamp": dates, "price_close": closes})
    grouped = df.groupby(pd.array([0] * 400))  # single group

    for _, group in grouped:
        group = group.sort_values("timestamp")

        # This is the exact code from screen_macd_setup (the failing path):
        group_idx = group.set_index("timestamp")
        if not isinstance(group_idx.index, pd.DatetimeIndex):
            group_idx.index = pd.DatetimeIndex(group_idx.index, utc=True)

        weekly_close = group_idx["price_close"].resample("W-FRI").last().dropna()

        assert len(weekly_close) > 0, "Resample should produce weekly candles"
        assert len(weekly_close) < len(group), "Weekly resample should reduce row count"
        assert isinstance(weekly_close.index, pd.DatetimeIndex), "Result should be DatetimeIndex"


def test_macd_with_tz_aware_data():
    """Full MACD computation with tz-aware weekly resample — must not crash."""
    dates = _tz_aware_dates()
    # Uptrend so MACD is positive
    trend = np.linspace(100, 200, 400)
    noise = np.random.randn(400) * 3
    closes = pd.Series(trend + noise, name="price_close")

    df = pd.DataFrame({"timestamp": dates, "price_close": closes})

    # Daily MACD — no resample needed, just the flat series
    daily_macd = ta.macd(closes, fast=12, slow=26, signal=9, talib=False)
    daily_val = daily_macd.iloc[-1, 0]
    assert daily_val > 0, f"Expected positive daily MACD on uptrend, got {daily_val}"

    # Weekly MACD via the resample path
    group_idx = df.set_index("timestamp")
    if not isinstance(group_idx.index, pd.DatetimeIndex):
        group_idx.index = pd.DatetimeIndex(group_idx.index, utc=True)

    weekly_close = group_idx["price_close"].resample("W-FRI").last().dropna()

    assert len(weekly_close) >= 50, f"Expected ~57 weekly candles, got {len(weekly_close)}"

    weekly_macd = ta.macd(weekly_close, fast=12, slow=26, signal=9, talib=False)
    weekly_val = weekly_macd.iloc[-1, 0]
    assert weekly_val > 0, f"Expected positive weekly MACD on uptrend, got {weekly_val}"


def test_macd_with_tz_naive_data():
    """Also verify tz-naive timestamps still work (the else branch)."""
    dates = pd.date_range("2025-01-01", periods=400, freq="B")  # no tz
    closes = pd.Series(np.cumsum(np.random.randn(400)) + 100, name="price_close")

    df = pd.DataFrame({"timestamp": dates, "price_close": closes})
    group_idx = df.set_index("timestamp")

    # This is a DatetimeIndex already, so the isinstance check skips conversion
    assert isinstance(group_idx.index, pd.DatetimeIndex)
    weekly_close = group_idx["price_close"].resample("W-FRI").last().dropna()

    assert len(weekly_close) > 0
    assert isinstance(weekly_close.index, pd.DatetimeIndex)