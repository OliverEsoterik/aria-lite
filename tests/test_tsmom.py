import pytest
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'etl'))

from importlib import import_module
engine_mod = import_module('04_tsmom_execution_engine')
TSMOMExecutionEngine = engine_mod.TSMOMExecutionEngine


def make_prices(n_days: int = 300, tickers=('AAPL', 'MSFT'), seed: int = 42) -> pd.DataFrame:
    """Synthetic prices: geometric brownian motion, deterministic seed."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
    data = {}
    for t in tickers:
        returns = rng.normal(0.0005, 0.015, n_days)
        prices = 100.0 * np.exp(np.cumsum(returns))
        data[t] = prices
    return pd.DataFrame(data, index=dates)


def test_engine_instantiates_with_defaults():
    eng = TSMOMExecutionEngine()
    assert eng.target_annual_volatility == 0.15
    assert eng.min_rebalance_threshold == 0.05
    assert eng.sma_window_days == 210
    assert eng.tsmom_window_days == 252
    assert eng.volatility_window_days == 60
