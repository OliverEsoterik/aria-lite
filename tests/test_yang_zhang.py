"""Tests for Yang-Zhang range-based volatility estimator."""
import numpy as np
import pandas as pd
import pytest
from src.etl.common import yang_zhang_vol


class TestYangZhangVol:
    def test_returns_series(self, sample_ohlc):
        result = yang_zhang_vol(sample_ohlc, period=20, min_periods=10)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlc)

    def test_flat_prices_zero_vol(self, flat_ohlc):
        """Flat prices should produce near-zero volatility."""
        result = yang_zhang_vol(flat_ohlc, period=5, min_periods=3)
        assert result.iloc[-1] == pytest.approx(0.0, abs=1e-10)

    def test_annualized_vs_daily(self, sample_ohlc):
        """Annualized vol should be sqrt(252) times daily vol."""
        daily = yang_zhang_vol(sample_ohlc, period=20, min_periods=10, annualize=False)
        annualized = yang_zhang_vol(sample_ohlc, period=20, min_periods=10, annualize=True)
        assert annualized.iloc[-1] == pytest.approx(daily.iloc[-1] * np.sqrt(252), rel=1e-10)

    def test_positive_values(self, sample_ohlc):
        """Volatility should always be non-negative."""
        result = yang_zhang_vol(sample_ohlc, period=20, min_periods=10)
        assert (result.dropna() >= 0).all()

    def test_short_dataframe_returns_nans(self):
        """Data shorter than min_periods should produce NaN vol."""
        short = pd.DataFrame({
            "price_open": [100, 101],
            "price_high": [102, 103],
            "price_low": [99, 100],
            "price_close": [101, 102],
        })
        result = yang_zhang_vol(short, period=20, min_periods=10)
        assert result.isna().all()

    def test_with_nan_gaps(self):
        """Should handle NaN values without crashing."""
        dates = pd.date_range("2025-01-01", periods=10, freq="D")
        df = pd.DataFrame({
            "price_open": [100, 101, 102, np.nan, 104, 105, 106, 107, 108, 109],
            "price_high": [101, 102, 103, np.nan, 105, 106, 107, 108, 109, 110],
            "price_low": [99, 100, 101, np.nan, 103, 104, 105, 106, 107, 108],
            "price_close": [100, 101, 102, np.nan, 104, 105, 106, 107, 108, 109],
        }, index=dates)
        result = yang_zhang_vol(df, period=5, min_periods=3)
        assert not result.isna().all()

    def test_known_output_deterministic(self):
        """With a fixed simple input, verify the output is deterministic."""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "price_open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "price_high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "price_low":  [99.0, 100.0, 101.0, 102.0, 103.0],
            "price_close": [101.0, 102.0, 103.0, 104.0, 105.0],
        }, index=dates)
        result = yang_zhang_vol(df, period=5, min_periods=3, annualize=False)
        assert result.iloc[0:3].isna().all()
        assert result.iloc[3:5].notna().all()

    def test_identical_twice(self, sample_ohlc):
        """Deterministic: same input → same output (ignoring NaN positions)."""
        r1 = yang_zhang_vol(sample_ohlc, period=20, min_periods=10)
        r2 = yang_zhang_vol(sample_ohlc, period=20, min_periods=10)
        # Both are NaN at the same positions, non-NaN values should match
        assert r1.isna().equals(r2.isna())
        assert (r1.dropna().values == pytest.approx(r2.dropna().values, rel=1e-10))