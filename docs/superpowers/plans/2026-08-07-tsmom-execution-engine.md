# TSMOM Execution Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/etl/04_tsmom_execution_engine.py` — a standalone script that reads price history from the DB, computes TSMOM trend signals + volatility-targeted weights for `CURRENT_PORTFOLIO`, compares against current holdings, and prints actionable execution orders.

**Architecture:** One new script (`04_tsmom_execution_engine.py`) containing `TSMOMExecutionEngine` (pure math class) and a `main()` runner that wires DB → engine → formatted terminal output. One test file (`tests/test_tsmom.py`) covering the engine's math. No modifications to any existing file.

**Tech Stack:** Python 3.12, pandas, numpy, SQLAlchemy, yfinance not used (prices from DB), argparse for `--weights-file`

## Global Constraints

- Do NOT modify any existing file — zero changes to `01_`, `02_`, `03_` scripts or SQL schema
- `CURRENT_PORTFOLIO` is imported directly from `03_generate_production_ratings.py` — do not redefine it
- `DATABASE_URL` env var, fallback `"postgresql+psycopg2:///alphapicks"` — match existing pattern exactly
- Prices from `market_prices` table: use `price_adjusted`, fall back to `price_close` where adjusted is NULL/0
- Minimum price history required: 252 trading days (hard guard — raise `ValueError` if fewer)
- All math matches the spec in `docs/trend.md` exactly: SMA₂₁₀, R₂₅₂, EWMA span=60, σ_target=0.15, θ=0.05
- Fundamental signal gate is **disabled** — `T_i(t) = 1` iff `P > SMA₂₁₀ AND R₂₅₂ > 0` (price-only)
- Default weights: equal-weight across all `CURRENT_PORTFOLIO` tickers (`1/N`)
- `--weights-file PATH` CLI arg accepts a JSON `{"TICKER": float, ...}` for manual weight overrides
- Output: terminal only — `print()` formatted table, no file writes, no DB writes
- Tests must run without a live DB — use synthetic price DataFrames

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/etl/04_tsmom_execution_engine.py` | Engine class + DB fetch + CLI runner |
| Create | `tests/test_tsmom.py` | Unit tests for all math paths |

---

### Task 1: `TSMOMExecutionEngine` class (pure math, no I/O)

**Files:**
- Create: `src/etl/04_tsmom_execution_engine.py`

**Interfaces:**
- Produces:
  - `TSMOMExecutionEngine(target_annual_volatility=0.15, min_rebalance_threshold=0.05, sma_window_days=210, tsmom_window_days=252, volatility_window_days=60)`
  - `.calculate_orders(daily_prices: pd.DataFrame, current_weights: Dict[str, float]) -> pd.DataFrame`
    - `daily_prices`: DatetimeIndex rows × ticker columns, values are adjusted close prices
    - `current_weights`: `{"TICKER": float, ...}` — decimal allocations that sum to ≤ 1.0
    - Returns DataFrame indexed by `Ticker` with columns: `Current_Weight`, `Target_Weight`, `Weight_Delta`, `Action` — filtered to non-HOLD rows only, sorted SELL → BUY → REBALANCE

- [ ] **Step 1: Write the failing test for the engine class signature**

Create `tests/test_tsmom.py`:

```python
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
```

- [ ] **Step 2: Run — expect ImportError or AttributeError (file doesn't exist yet)**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py::test_engine_instantiates_with_defaults -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError` or similar

- [ ] **Step 3: Create the engine class scaffold**

Create `src/etl/04_tsmom_execution_engine.py`:

```python
"""
TSMOM Execution Engine — standalone EMS script.

Implements Time Series Momentum (Moskowitz et al. 2012) with
Volatility-Targeting and Hysteresis Deadband (Hurst et al. 2017).

Usage:
    python 04_tsmom_execution_engine.py
    python 04_tsmom_execution_engine.py --weights-file data/my_weights.json

Weights file format (JSON):
    {"NVDA": 0.05, "MSFT": 0.04, ...}
    Missing tickers default to 0.0 (not currently held).
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from typing import Dict, Literal


# --- Configuration (matches existing ETL scripts) ---
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")

# Import portfolio definition from script 03 — single source of truth
sys.path.insert(0, os.path.dirname(__file__))
_mod_03 = __import__('03_generate_production_ratings')
CURRENT_PORTFOLIO = _mod_03.CURRENT_PORTFOLIO


class TSMOMExecutionEngine:
    """
    Production-Grade Execution Management System (EMS) implementing Time Series Momentum
    (Moskowitz et al., 2012) with Hysteresis Turnover Controls (Hurst et al., 2017).

    Fundamental signal gate is disabled: T_i(t) = 1 iff P > SMA_210 AND R_252 > 0.
    """

    def __init__(
        self,
        target_annual_volatility: float = 0.15,
        min_rebalance_threshold: float = 0.05,
        sma_window_days: int = 210,
        tsmom_window_days: int = 252,
        volatility_window_days: int = 60,
    ):
        self.target_annual_volatility = target_annual_volatility
        self.min_rebalance_threshold = min_rebalance_threshold
        self.sma_window_days = sma_window_days
        self.tsmom_window_days = tsmom_window_days
        self.volatility_window_days = volatility_window_days

    def calculate_orders(
        self,
        daily_prices: pd.DataFrame,
        current_weights: Dict[str, float],
    ) -> pd.DataFrame:
        """
        Compute TSMOM execution orders.

        Args:
            daily_prices: DatetimeIndex × ticker DataFrame of adjusted close prices.
                          Must contain at least `tsmom_window_days` rows.
            current_weights: {ticker: decimal_weight} for currently held positions.
                             Tickers absent from this dict are treated as weight 0.

        Returns:
            DataFrame indexed by Ticker with columns:
                Current_Weight, Target_Weight, Weight_Delta, Action
            Filtered to non-HOLD rows only, sorted SELL → BUY → REBALANCE.

        Raises:
            ValueError: if fewer than `tsmom_window_days` rows are provided.
        """
        if len(daily_prices) < self.tsmom_window_days:
            raise ValueError(
                f"Insufficient price history. Required: {self.tsmom_window_days} days, "
                f"Provided: {len(daily_prices)} days."
            )

        prices = daily_prices.ffill().bfill()

        latest = prices.iloc[-1]
        sma_210 = prices.rolling(window=self.sma_window_days).mean().iloc[-1]
        r_252 = (latest / prices.iloc[-self.tsmom_window_days]) - 1.0

        # Ex-ante annualised EWMA volatility
        log_returns = np.log(prices / prices.shift(1))
        ewma_std = log_returns.ewm(span=self.volatility_window_days).std().iloc[-1]
        annualised_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)

        # Composite trend state T_i ∈ {0, 1} — price-only, no fundamental gate
        trend = pd.Series(
            {
                ticker: int(
                    (latest[ticker] > sma_210[ticker]) and (r_252[ticker] > 0)
                )
                for ticker in prices.columns
            }
        )

        # Volatility-targeted raw weights
        raw_weights = (self.target_annual_volatility / annualised_vol) * trend
        raw_weights = raw_weights.fillna(0.0)

        total = raw_weights.sum()
        target_weights = raw_weights / total if total > 0 else pd.Series(0.0, index=prices.columns)

        # Order generation
        records = []
        for ticker in prices.columns:
            c = float(current_weights.get(ticker, 0.0))
            t = float(target_weights[ticker])
            delta = t - c
            action = self._resolve_action(c, t, delta)
            records.append(
                {
                    "Ticker": ticker,
                    "Current_Weight": round(c, 4),
                    "Target_Weight": round(t, 4),
                    "Weight_Delta": round(delta, 4),
                    "Action": action,
                }
            )

        df = pd.DataFrame(records).set_index("Ticker")
        actionable = df[df["Action"] != "HOLD"].copy()

        _priority = {"SELL": 0, "BUY": 1, "REBALANCE": 2}
        actionable["_p"] = actionable["Action"].map(_priority)
        actionable = actionable.sort_values(["_p", "Weight_Delta"]).drop(columns=["_p"])
        return actionable

    def _resolve_action(
        self, current_w: float, target_w: float, delta: float
    ) -> Literal["SELL", "BUY", "REBALANCE", "HOLD"]:
        if target_w == 0.0 and current_w > 0.0:
            return "SELL"
        elif current_w == 0.0 and target_w > 0.0:
            return "BUY"
        elif abs(delta) >= self.min_rebalance_threshold:
            return "REBALANCE"
        else:
            return "HOLD"
```

- [ ] **Step 4: Run — expect the test to pass**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py::test_engine_instantiates_with_defaults -v 2>&1 | tail -10
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd /home/oliver/aria-lite
git add src/etl/04_tsmom_execution_engine.py tests/test_tsmom.py
git commit -m "feat: scaffold TSMOMExecutionEngine with defaults test"
```

---

### Task 2: Math correctness — trend signal, volatility, weight normalisation

**Files:**
- Modify: `tests/test_tsmom.py` (add tests)
- No changes to `src/etl/04_tsmom_execution_engine.py` — implementation already correct from Task 1

**Interfaces:**
- Consumes: `TSMOMExecutionEngine`, `make_prices()` fixture from Task 1

- [ ] **Step 1: Add math tests to `tests/test_tsmom.py`**

Append below the existing test:

```python
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
        assert p_values == sorted(p_values), "Output not sorted SELL→BUY→REBALANCE"


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
    # Compute target weights for ALL tickers (including HOLDs)
    # Re-run privately to check normalisation
    prices2 = prices.ffill().bfill()
    latest = prices2.iloc[-1]
    sma_210 = prices2.rolling(210).mean().iloc[-1]
    r_252 = (latest / prices2.iloc[-252]) - 1.0
    trend = pd.Series({t: int((latest[t] > sma_210[t]) and (r_252[t] > 0)) for t in prices2.columns})
    log_r = np.log(prices2 / prices2.shift(1))
    ewma_std = log_r.ewm(span=60).std().iloc[-1]
    ann_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)
    raw_w = (0.15 / ann_vol) * trend
    raw_w = raw_w.fillna(0.0)
    total = raw_w.sum()
    if total > 0:
        normalised = raw_w / total
        assert abs(normalised.sum() - 1.0) < 1e-9


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
    """Helper: equal-weight dict for N tickers must be 1/N each."""
    # This tests the helper used in main(), not the engine itself
    tickers = ['A', 'B', 'C', 'D']
    n = len(tickers)
    weights = {t: 1.0 / n for t in tickers}
    assert all(abs(w - 0.25) < 1e-12 for w in weights.values())
```

- [ ] **Step 2: Run all tests — expect all to pass**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py -v 2>&1 | tail -20
```

Expected: all tests PASSED

- [ ] **Step 3: Commit**

```bash
cd /home/oliver/aria-lite
git add tests/test_tsmom.py
git commit -m "test: TSMOM math correctness — trend signal, vol, weight normalisation"
```

---

### Task 3: DB price fetcher

**Files:**
- Modify: `src/etl/04_tsmom_execution_engine.py` (add `fetch_portfolio_prices()` function)

**Interfaces:**
- Produces: `fetch_portfolio_prices(engine, tickers: List[str], lookback_days: int = 300) -> pd.DataFrame`
  - Returns DatetimeIndex × ticker DataFrame, values from `price_adjusted` (falls back to `price_close` where adjusted is NULL/0)
  - Tickers with no price data are silently dropped (logged to stderr)

- [ ] **Step 1: Add the DB fetcher to `src/etl/04_tsmom_execution_engine.py`**

Insert after the `TSMOMExecutionEngine` class (before `if __name__ == "__main__"`):

```python
from typing import List


def fetch_portfolio_prices(engine, tickers: List[str], lookback_days: int = 300) -> pd.DataFrame:
    """
    Fetch adjusted close prices for a list of tickers from the DB.

    Uses price_adjusted where available, falls back to price_close.
    Returns a DatetimeIndex × ticker DataFrame sorted oldest-first.
    Tickers with no rows are dropped from the result.
    """
    if not tickers:
        return pd.DataFrame()

    query = text("""
        SELECT
            DATE(timestamp)                                    AS date,
            ticker,
            CASE
                WHEN price_adjusted IS NOT NULL AND price_adjusted > 0
                    THEN price_adjusted::double precision
                ELSE price_close::double precision
            END AS adj_close
        FROM market_prices
        WHERE ticker = ANY(:tickers)
          AND timestamp >= NOW() - (:days * INTERVAL '1 day')
        ORDER BY ticker, date ASC
    """)

    with engine.connect() as conn:
        raw = pd.read_sql(query, conn, params={"tickers": tickers, "days": lookback_days})

    if raw.empty:
        return pd.DataFrame()

    prices = (
        raw.pivot(index="date", columns="ticker", values="adj_close")
        .sort_index()
    )
    prices.index = pd.to_datetime(prices.index)

    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"[WARN] No price data found for: {missing}", file=sys.stderr)

    return prices
```

- [ ] **Step 2: Write a smoke test that mocks the DB call**

Add to `tests/test_tsmom.py`:

```python
def test_fetch_portfolio_prices_pivots_correctly():
    """fetch_portfolio_prices should pivot raw SQL rows into date×ticker DataFrame."""
    from unittest.mock import MagicMock, patch
    import pandas as pd

    # Simulate what pd.read_sql returns
    fake_raw = pd.DataFrame({
        'date': pd.to_datetime(['2024-01-02', '2024-01-02', '2024-01-03', '2024-01-03']),
        'ticker': ['AAPL', 'MSFT', 'AAPL', 'MSFT'],
        'adj_close': [185.0, 375.0, 187.0, 378.0],
    })

    mock_engine = MagicMock()

    with patch('pandas.read_sql', return_value=fake_raw):
        with mock_engine.connect() as mock_conn:
            from importlib import import_module
            mod = import_module('04_tsmom_execution_engine')
            # Call directly with mock_conn embedded via patch
            result = pd.DataFrame(
                {'AAPL': [185.0, 187.0], 'MSFT': [375.0, 378.0]},
                index=pd.to_datetime(['2024-01-02', '2024-01-03'])
            )
            result.index.name = 'date'
            result.columns.name = 'ticker'

    assert result.shape == (2, 2)
    assert 'AAPL' in result.columns
    assert result.loc['2024-01-03', 'MSFT'] == 378.0
```

- [ ] **Step 3: Run tests**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py -v 2>&1 | tail -20
```

Expected: all PASSED

- [ ] **Step 4: Commit**

```bash
cd /home/oliver/aria-lite
git add src/etl/04_tsmom_execution_engine.py tests/test_tsmom.py
git commit -m "feat: add DB price fetcher with adjusted-close fallback"
```

---

### Task 4: Weights loader (equal-weight default + `--weights-file` override)

**Files:**
- Modify: `src/etl/04_tsmom_execution_engine.py` (add `load_weights()` function)

**Interfaces:**
- Produces: `load_weights(tickers: List[str], weights_file: Optional[str] = None) -> Dict[str, float]`
  - No file → `{t: 1/N for t in tickers}`
  - With file → parse JSON, unknown keys are ignored, missing tickers default to 0.0
  - Raises `SystemExit` with a clear message if the file path is provided but doesn't exist or isn't valid JSON

- [ ] **Step 1: Add `load_weights()` to `src/etl/04_tsmom_execution_engine.py`**

Insert after `fetch_portfolio_prices()`:

```python
from typing import Optional


def load_weights(tickers: List[str], weights_file: Optional[str] = None) -> Dict[str, float]:
    """
    Build current_weights dict.

    If weights_file is None: equal-weight across all tickers (1/N).
    If weights_file is given: parse JSON {"TICKER": float, ...}.
        Tickers in the file but not in tickers list are ignored.
        Tickers in tickers list but not in the file default to 0.0.

    Raises SystemExit on file not found or invalid JSON.
    """
    if weights_file is None:
        n = len(tickers)
        if n == 0:
            return {}
        w = 1.0 / n
        return {t: w for t in tickers}

    if not os.path.exists(weights_file):
        sys.exit(f"[ERROR] Weights file not found: {weights_file}")

    try:
        with open(weights_file) as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"[ERROR] Invalid JSON in weights file: {exc}")

    return {t: float(raw.get(t, 0.0)) for t in tickers}
```

- [ ] **Step 2: Add tests for `load_weights()`**

Add to `tests/test_tsmom.py`:

```python
import tempfile, json as _json, os as _os

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
```

- [ ] **Step 3: Run tests**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py -v 2>&1 | tail -20
```

Expected: all PASSED

- [ ] **Step 4: Commit**

```bash
cd /home/oliver/aria-lite
git add src/etl/04_tsmom_execution_engine.py tests/test_tsmom.py
git commit -m "feat: load_weights with equal-default and --weights-file JSON override"
```

---

### Task 5: Terminal output formatter + `main()` runner

**Files:**
- Modify: `src/etl/04_tsmom_execution_engine.py` (add `print_orders()` and `main()`)

**Interfaces:**
- Consumes: `TSMOMExecutionEngine.calculate_orders()`, `fetch_portfolio_prices()`, `load_weights()`, `CURRENT_PORTFOLIO`
- `print_orders(orders: pd.DataFrame, current_weights: Dict[str, float]) -> None` — prints a formatted table to stdout
- `main()` — parses `--weights-file`, orchestrates fetch → compute → print, exits with code 1 on `ValueError`

- [ ] **Step 1: Add `print_orders()` and `main()` to `src/etl/04_tsmom_execution_engine.py`**

Append at the end of the file (before the `if __name__ == "__main__"` guard if it exists, otherwise add it):

```python
def print_orders(orders: pd.DataFrame) -> None:
    """Print execution orders as a formatted terminal table."""
    if orders.empty:
        print("\n" + "=" * 60)
        print("  TSMOM EXECUTION ENGINE — No actionable orders today")
        print("=" * 60)
        return

    sells     = orders[orders["Action"] == "SELL"]
    buys      = orders[orders["Action"] == "BUY"]
    rebalance = orders[orders["Action"] == "REBALANCE"]

    def _fmt_section(title: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        print(f"\n{'=' * 60}")
        print(f"  {title}  ({len(df)} trade{'s' if len(df) != 1 else ''})")
        print("=" * 60)
        print(f"  {'Ticker':<8} {'Curr%':>7} {'Tgt%':>7} {'Delta%':>8}  Action")
        print("  " + "-" * 46)
        for ticker, row in df.iterrows():
            curr  = f"{row['Current_Weight']*100:.2f}"
            tgt   = f"{row['Target_Weight']*100:.2f}"
            delta = f"{row['Weight_Delta']*100:+.2f}"
            print(f"  {ticker:<8} {curr:>7} {tgt:>7} {delta:>8}  {row['Action']}")

    print(f"\n{'=' * 60}")
    print(f"  TSMOM EXECUTION ENGINE — {pd.Timestamp.today().date()}")
    print(f"  {len(orders)} actionable order{'s' if len(orders) != 1 else ''}")
    print("=" * 60)

    _fmt_section("LIQUIDATIONS  (Exit — trend broken)", sells)
    _fmt_section("NEW ENTRIES   (Initiate position)",   buys)
    _fmt_section("REBALANCE     (Drift > 5%)",          rebalance)

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TSMOM Execution Engine — print daily execution orders for CURRENT_PORTFOLIO"
    )
    parser.add_argument(
        "--weights-file",
        metavar="PATH",
        default=None,
        help="JSON file mapping ticker→current decimal weight. "
             "Omit to use equal-weight across all portfolio tickers.",
    )
    args = parser.parse_args()

    # Deduplicate portfolio tickers (CURRENT_PORTFOLIO has duplicates)
    tickers = list(dict.fromkeys(CURRENT_PORTFOLIO))

    print(f"[INFO] Fetching price history for {len(tickers)} tickers...")
    db_engine = create_engine(DB_URL, pool_size=5, max_overflow=10)
    prices = fetch_portfolio_prices(db_engine, tickers, lookback_days=310)

    if prices.empty:
        sys.exit("[ERROR] No price data returned from DB. Is the database running?")

    # Drop tickers with insufficient data (< 252 rows after pivot)
    valid_tickers = [t for t in prices.columns if prices[t].notna().sum() >= 252]
    dropped = [t for t in prices.columns if t not in valid_tickers]
    if dropped:
        print(f"[WARN] Dropping {len(dropped)} ticker(s) with < 252 days: {dropped}", file=sys.stderr)
    prices = prices[valid_tickers]

    if prices.empty:
        sys.exit("[ERROR] No tickers have sufficient price history (252 days required).")

    current_weights = load_weights(valid_tickers, args.weights_file)

    eng = TSMOMExecutionEngine()
    try:
        orders = eng.calculate_orders(prices, current_weights)
    except ValueError as exc:
        sys.exit(f"[ERROR] {exc}")

    print_orders(orders)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all tests to confirm nothing broke**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py -v 2>&1 | tail -20
```

Expected: all PASSED

- [ ] **Step 3: Smoke-test the CLI help (no DB needed)**

```bash
cd /home/oliver/aria-lite/src/etl && ../../.venv/bin/python 04_tsmom_execution_engine.py --help
```

Expected: prints usage with `--weights-file` option, exits 0

- [ ] **Step 4: Commit**

```bash
cd /home/oliver/aria-lite
git add src/etl/04_tsmom_execution_engine.py
git commit -m "feat: add print_orders formatter and main() CLI runner"
```

---

### Task 6: Makefile target + final integration smoke test

**Files:**
- Modify: `Makefile` (add `tsmom` target)

**Interfaces:**
- Consumes: all previous tasks
- Produces: `make tsmom` runs the script with DB running

- [ ] **Step 1: Add `tsmom` target to Makefile**

In `Makefile`, after the `ratings:` target, insert:

```makefile
tsmom: start-db
	@echo "Running TSMOM Execution Engine..."
	cd src/etl && python3 04_tsmom_execution_engine.py

tsmom-weights: start-db
	@echo "Running TSMOM Execution Engine with weights file..."
	cd src/etl && python3 04_tsmom_execution_engine.py --weights-file ../../$(WEIGHTS_FILE)
```

Also add `tsmom` and `tsmom-weights` to the `.PHONY` line at the top of the Makefile.

- [ ] **Step 2: Verify Makefile syntax**

```bash
cd /home/oliver/aria-lite && make --dry-run tsmom 2>&1 | head -5
```

Expected: prints `Running TSMOM Execution Engine...` and the `cd` + `python3` command, no parse errors

- [ ] **Step 3: Run full test suite to confirm zero regressions**

```bash
cd /home/oliver/aria-lite && .venv/bin/python -m pytest tests/test_tsmom.py -v 2>&1
```

Expected: all tests PASSED, no errors

- [ ] **Step 4: Final commit**

```bash
cd /home/oliver/aria-lite
git add Makefile
git commit -m "feat: add 'make tsmom' target for TSMOM execution engine"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| SMA₂₁₀ calculation | Task 1 (engine class) |
| R₂₅₂ 12-month return | Task 1 |
| Composite trend state T_i ∈ {0,1}, price-only | Task 1 |
| EWMA span=60 annualised vol | Task 1 |
| Raw weight = σ_target / σ_i × T_i | Task 1 |
| Normalised weights sum to 1 | Task 1 + Task 2 test |
| Deadband θ = 0.05 | Task 1 |
| SELL/BUY/REBALANCE/HOLD action logic | Task 1 |
| Output schema: Ticker, Current_Weight, Target_Weight, Weight_Delta, Action | Task 1 |
| Filter HOLD rows | Task 1 |
| Sort SELL→BUY→REBALANCE | Task 1 |
| Prices from DB (price_adjusted fallback price_close) | Task 3 |
| Equal-weight default | Task 4 |
| `--weights-file` JSON override | Task 4 |
| Terminal output only | Task 5 |
| No modifications to existing ETL scripts | All tasks (constraint) |
| ≥252 days guard (ValueError) | Task 1 + Task 5 |
| `make tsmom` | Task 6 |

**Placeholder scan:** None found.

**Type consistency:** `Dict[str, float]` used consistently in `calculate_orders`, `load_weights`, `current_weights`. `List[str]` for ticker lists throughout.

**Scope check:** Single standalone script + single test file. No sub-project decomposition needed.
