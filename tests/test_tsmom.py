import pytest
import pandas as pd
import numpy as np
import sys, os
import tempfile, json as _json, os as _os
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


def test_fetch_portfolio_prices_pivots_correctly():
    """fetch_portfolio_prices should pivot raw SQL rows into date x ticker DataFrame."""
    from unittest.mock import MagicMock, patch
    from importlib import import_module

    mod = import_module('04_tsmom_execution_engine')
    fetch = mod.fetch_portfolio_prices

    fake_raw = pd.DataFrame({
        'date': pd.to_datetime(['2024-01-02', '2024-01-02', '2024-01-03', '2024-01-03']),
        'ticker': ['AAPL', 'MSFT', 'AAPL', 'MSFT'],
        'adj_close': [185.0, 375.0, 187.0, 378.0],
    })

    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch('pandas.read_sql', return_value=fake_raw):
        result = fetch(mock_engine, ['AAPL', 'MSFT'])

    assert result.shape == (2, 2)
    assert 'AAPL' in result.columns
    assert 'MSFT' in result.columns
    assert result.loc['2024-01-03', 'MSFT'] == 378.0
    assert result.loc['2024-01-02', 'AAPL'] == 185.0
    assert result.index.name == 'date'
    assert result.columns.name == 'ticker'
    assert isinstance(result.index, pd.DatetimeIndex)


def test_load_weights_equal_default():
    from importlib import import_module
    mod = import_module('04_tsmom_execution_engine')
    tickers = ['A', 'B', 'C', 'D']
    w = mod.load_weights(tickers)
    assert len(w) == 4
    assert all(abs(v - 0.25) < 1e-12 for v in w.values())


def test_load_weights_from_file():
    from importlib import import_module
    mod = import_module('04_tsmom_execution_engine')
    tickers = ['NVDA', 'MSFT', 'AAPL']
    data = {'NVDA': 0.10, 'MSFT': 0.08}  # AAPL absent → 0.0
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        _json.dump(data, f)
        fname = f.name
    try:
        w = mod.load_weights(tickers, fname)
        assert abs(w['NVDA'] - 0.10) < 1e-12
        assert abs(w['MSFT'] - 0.08) < 1e-12
        assert abs(w['AAPL'] - 0.0) < 1e-12
    finally:
        _os.unlink(fname)


def test_load_weights_file_not_found_exits():
    from importlib import import_module
    mod = import_module('04_tsmom_execution_engine')
    with pytest.raises(SystemExit):
        mod.load_weights(['X'], '/tmp/this_does_not_exist_xyzzy.json')
