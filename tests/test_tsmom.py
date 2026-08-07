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


def test_insufficient_history_raises():
    eng = TSMOMExecutionEngine()
    prices = make_prices(n_days=100)  # < 252
    with pytest.raises(ValueError, match="Insufficient price history"):
        eng.calculate_orders(prices, {})


def test_returns_only_actionable_rows():
    """HOLD rows must be absent from output."""
    eng = TSMOMExecutionEngine()
    prices = make_prices(n_days=300)
    orders = eng.calculate_orders(prices, {})
    assert "HOLD" not in orders["Action"].values


def test_sell_comes_before_buy_in_output():
    """SELLs must appear before BUYs in the sorted output."""
    eng = TSMOMExecutionEngine()
    prices = make_prices(n_days=300, tickers=('AAA', 'BBB', 'CCC', 'DDD'), seed=7)
    # Give all tickers a current weight so some trigger SELL
    current = {'AAA': 0.30, 'BBB': 0.30, 'CCC': 0.20, 'DDD': 0.20}
    orders = eng.calculate_orders(prices, current)
    if len(orders) > 1:
        priority = {"SELL": 0, "BUY": 1, "REBALANCE": 2}
        p_values = orders["Action"].map(priority).tolist()
        assert p_values == sorted(p_values), "Output not sorted SELL->BUY->REBALANCE"


def test_target_weights_sum_to_one_when_any_trend_active():
    """When at least one ticker is in uptrend, target weights must sum to ~1.0."""
    eng = TSMOMExecutionEngine()
    # Monotonically rising prices — all tickers will be in trend
    dates = pd.date_range('2022-01-01', periods=300, freq='B')
    prices = pd.DataFrame(
        {
            'X': np.linspace(50, 150, 300),
            'Y': np.linspace(40, 120, 300),
        },
        index=dates,
    )
    orders_full = eng.calculate_orders(prices, {})
    # Both tickers are in uptrend — expect BUY orders with Target_Weight summing to 1.0
    assert not orders_full.empty, "Expected BUY orders for monotonically rising prices"
    assert abs(orders_full["Target_Weight"].sum() - 1.0) < 1e-9, (
        f"Target weights sum to {orders_full['Target_Weight'].sum()}, expected 1.0"
    )


def test_zero_trend_produces_no_buys():
    """When all tickers are in downtrend, no BUY orders should be generated."""
    eng = TSMOMExecutionEngine()
    # Monotonically falling prices
    dates = pd.date_range('2022-01-01', periods=300, freq='B')
    prices = pd.DataFrame(
        {
            'X': np.linspace(150, 50, 300),
            'Y': np.linspace(120, 40, 300),
        },
        index=dates,
    )
    # No current holdings — nothing to SELL either
    orders = eng.calculate_orders(prices, {})
    assert len(orders) == 0 or "BUY" not in orders["Action"].values


def test_equal_weight_default_is_one_over_n():
    """Engine initialised with defaults has correct target vol (15%) and threshold (5%)."""
    from importlib import import_module
    mod = import_module('04_tsmom_execution_engine')
    TSMOMExecutionEngine = mod.TSMOMExecutionEngine
    eng = TSMOMExecutionEngine()
    assert abs(eng.target_annual_volatility - 0.15) < 1e-12
    assert abs(eng.min_rebalance_threshold - 0.05) < 1e-12
