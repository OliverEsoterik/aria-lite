"""Shared fixtures for all tests."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlc():
    """20-day OHLC DataFrame with a clear upward trend + known values."""
    np.random.seed(42)
    days = 20
    base = 100.0
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    closes = base + np.cumsum(np.random.randn(days) * 0.5)
    opens = closes + np.random.randn(days) * 0.2
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(days)) * 0.3
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(days)) * 0.3
    return pd.DataFrame({
        "price_open": opens,
        "price_high": highs,
        "price_low": lows,
        "price_close": closes,
    }, index=dates)


@pytest.fixture
def flat_ohlc():
    """Flat prices (no movement) — should produce zero volatility."""
    days = 20
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    return pd.DataFrame({
        "price_open": [100.0] * days,
        "price_high": [100.0] * days,
        "price_low": [100.0] * days,
        "price_close": [100.0] * days,
    }, index=dates)


@pytest.fixture
def sample_fundamentals():
    """Sample fundamentals dict simulating what yfinance.info returns."""
    return {
        "ticker": "TEST",
        "current_price": 150.0,
        "peg": 1.2,
        "fcf_yield": 0.05,
        "fwd_pe": 25.0,
        "trl_eps": 4.0,
        "op_margin": 0.15,
        "profit_margin": 0.10,
        "rev_growth": 0.15,
        "roe": 0.20,
        "debt_to_equity": 50.0,
        "current_ratio": 2.0,
        "eps_rev": 0.05,
        "beta": 1.2,
    }


@pytest.fixture
def sample_rating_row():
    """A row dict with all fields needed by assign_production_rating."""
    return {
        "final_score": 0.55,
        "eps_rev": 0.05,
        "mom_score": 0.20,
        "fwd_pe": 25.0,
        "peg": 1.2,
        "rev_growth": 0.15,
        "op_margin": 0.15,
        "acceleration": 0.08,
        "near_high": 0.98,
        "mom_3m": 0.15,
    }


@pytest.fixture
def sample_tickers():
    return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]