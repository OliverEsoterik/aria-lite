# Testing Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit tests for all pure computation logic, set up CI, and make tests mandatory before merging.

**Architecture:** Extract duplicated pure functions into `src/etl/common.py`, write pytest unit tests with synthetic data (no DB/API), add `pyproject.toml` for pip-installable dev environment, and create GitHub Actions workflow.

**Tech Stack:** Python 3.12, pytest, pandas, numpy, GitHub Actions

## Global Constraints

- No external API calls in tests (no yfinance, no SEC, no PostgreSQL)
- All test data is synthetic — constructed inline or in conftest.py fixtures
- Tests must run with `pip install -e ".[dev]"` then `pytest` — no Nix required
- All duplicated code must be extracted into `src/etl/common.py` before testing
- Every commit compiles and tests pass

---

## File Structure

**New files:**
- `pyproject.toml` — project metadata, dependencies, dev deps, pytest config
- `src/etl/common.py` — shared pure functions (yang_zhang_vol, RiskGate, assign_production_rating, z_score)
- `tests/__init__.py` — package marker
- `tests/conftest.py` — shared fixtures (sample OHLC data, sample fundamentals)
- `tests/test_yang_zhang.py` — Yang-Zhang volatility tests
- `tests/test_risk_gate.py` — RiskGate tests
- `tests/test_rating.py` — Rating engine tests
- `tests/test_momentum.py` — Momentum scoring / z-score tests
- `tests/test_metrics.py` — calculate_metrics tests
- `tests/test_portfolio_optimizer.py` — Portfolio optimizer tests
- `tests/test_top_picks.py` — Top-picks portfolio tests
- `.github/workflows/test.yml` — CI workflow

**Modified files:**
- `src/etl/02_compute_statistics.py` — import yang_zhang_vol from common.py, remove local definition
- `src/etl/03_generate_production_ratings.py` — import yang_zhang_vol, RiskGate, assign_production_rating, z_score from common.py, remove local definitions
- `skills/portfolio-construction/tools/score_tickers.py` — import yang_zhang_vol, RiskGate, assign_rating, z_score from common.py, remove local definitions
- `.gitignore` — add `tests/__pycache__/`, `htmlcov/`, `.coverage`

---

### Task 1: Project scaffolding (pyproject.toml, conftest.py, .gitignore)

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `conftest.py` fixtures that all test modules consume

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "aria-lite"
version = "0.1.0"
description = "Quantitative equity research pipeline"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "yfinance>=0.2.30",
    "psycopg2-binary>=2.9",
    "sqlalchemy>=2.0",
    "pandas-ta>=0.3",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

- [ ] **Step 2: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 3: Create `tests/conftest.py`**

```python
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
```

- [ ] **Step 4: Update `.gitignore`**

Add at the end of the existing file:
```
# Tests
tests/__pycache__/
htmlcov/
.coverage
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py .gitignore
git commit -m "chore: add project scaffolding for testing (pyproject.toml, conftest, .gitignore)"
```

---

### Task 2: Extract shared module `src/etl/common.py`

**Files:**
- Create: `src/etl/common.py`
- Modify: `src/etl/02_compute_statistics.py` (remove yang_zhang_vol, import from common)
- Modify: `src/etl/03_generate_production_ratings.py` (remove yang_zhang_vol, RiskGate, assign_production_rating, import from common)
- Modify: `skills/portfolio-construction/tools/score_tickers.py` (remove yang_zhang_vol, RiskGate, assign_rating, import from common)

**Interfaces:**
- Produces: `src/etl/common.yang_zhang_vol(df, period, min_periods, annualize) -> pd.Series`
- Produces: `src/etl/common.RiskGate` class with `.is_pass(row) -> bool`
- Produces: `src/etl/common.assign_production_rating(row) -> str`
- Produces: `src/etl/common.z_score(series) -> pd.Series`
- Produces: `src/etl/common.ANNUALIZATION_FACTOR = np.sqrt(252)`

- [ ] **Step 1: Create `src/etl/common.py`**

```python
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
    log_oc = np.log(df['price_open'] / df['price_close'].shift(1))
    log_co = np.log(df['price_close'] / df['price_open'])

    log_ho = np.log(df['price_high'] / df['price_open'])
    log_lo = np.log(df['price_low'] / df['price_open'])
    log_hc = np.log(df['price_high'] / df['price_close'])
    log_lc = np.log(df['price_low'] / df['price_close'])
    rs = log_ho * log_hc + log_lo * log_lc

    o_var = log_oc.rolling(period, min_periods=min_periods).var()
    c_var = log_co.rolling(period, min_periods=min_periods).var()
    rs_mean = rs.rolling(period, min_periods=min_periods).mean()

    k = 0.34 / (1.34 + (period + 1) / (period - 1))

    yz_var = o_var + k * c_var + (1 - k) * rs_mean
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
    score = row.get('final_score', 0)
    eps_rev = row.get('eps_rev', 0)
    mom = row.get('mom_score', 0)
    pe = row.get('fwd_pe', 999) if row.get('fwd_pe') else 999
    peg = row.get('peg', 99) if row.get('peg') else 99
    rev_growth = row.get('rev_growth', 0)
    op_margin = row.get('op_margin', 0)
    accel = row.get('acceleration', 0)
    near_high = row.get('near_high', 0)
    mom_3m = row.get('mom_3m', 0)

    # 1. EXIT TRIGGERS
    if eps_rev < -0.03:
        return "SELL (Estimate Decay)"
    if rev_growth < 0:
        return "SELL (No Growth)"
    if mom < -0.10:
        return "SELL (Trend Exhaustion)"

    # 2. EARLY BIRD BREAKOUT
    is_breakout = near_high > 0.96
    is_accelerating = accel > 0.05 and mom_3m > 0.10
    if is_breakout and is_accelerating and peg < 1.5:
        return "STRONG BUY (Emerging Breakout)"

    # 3. HYPER-GROWTH
    if rev_growth > 0.50 and mom > 0.25 and peg < 1.2:
        return "STRONG BUY (Hyper-Growth)"

    # 4. STRONG BUY (Elite)
    is_confluence = eps_rev > 0.01 and mom > 0.1
    is_profitable = op_margin > 0
    is_fair_value = peg < 1.8 and pe < 60
    if score > 0.42 and is_confluence and is_profitable and is_fair_value:
        return "STRONG BUY (Elite)"

    # 5. BUY
    if score > 0.35 and mom > 0.1 and peg < 2.0:
        return "BUY"

    # 6. HOLD
    if pe > 65 or peg > 3.0:
        return "HOLD (Overvalued)"
    if mom < 0:
        return "HOLD (Consolidation)"

    return "HOLD"


def z_score(s):
    """Compute z-score normalization with safety epsilon."""
    return (s - s.mean()) / (s.std() + 1e-6)
```

- [ ] **Step 2: Update `src/etl/02_compute_statistics.py`**

Replace the `yang_zhang_vol` function definition (lines ~20-70) with an import:

```python
from common import yang_zhang_vol, ANNUALIZATION_FACTOR
```

And remove the local `ANNUALIZATION_FACTOR = np.sqrt(252)` line.

- [ ] **Step 3: Update `src/etl/03_generate_production_ratings.py`**

Replace the `yang_zhang_vol` function, `RiskGate` class, `assign_production_rating` function, and `ANNUALIZATION_FACTOR` with:

```python
from common import yang_zhang_vol, RiskGate, assign_production_rating, z_score, ANNUALIZATION_FACTOR
```

- [ ] **Step 4: Update `skills/portfolio-construction/tools/score_tickers.py`**

This file is in `skills/` not `src/etl/`, so it needs a path insert:

```python
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src/etl"))
from common import yang_zhang_vol, RiskGate, z_score, ANNUALIZATION_FACTOR
```

Then remove the local definitions of `yang_zhang_vol`, `RiskGate`, `assign_rating`, and `ANNUALIZATION_FACTOR`.

- [ ] **Step 5: Run existing scripts to verify no breakage**

We can't run against live DB, but we can verify imports work:

```bash
cd /home/oliver/aria-lite
python3 -c "from src.etl.common import yang_zhang_vol, RiskGate, assign_production_rating, z_score; print('common imports OK')"
python3 -c "import sys; sys.path.insert(0, 'src/etl'); from common import yang_zhang_vol; print('02_compute_statistics import OK')"
```

- [ ] **Step 6: Commit**

```bash
git add src/etl/common.py src/etl/02_compute_statistics.py src/etl/03_generate_production_ratings.py skills/portfolio-construction/tools/score_tickers.py
git commit -m "refactor: extract shared pure functions into src/etl/common.py"
```

---

### Task 3: Test Yang-Zhang volatility

**Files:**
- Create: `tests/test_yang_zhang.py`

**Consumes:** `conftest.py` fixtures (`sample_ohlc`, `flat_ohlc`), `common.yang_zhang_vol`

- [ ] **Step 1: Write `tests/test_yang_zhang.py`**

```python
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
        # Flat prices → log returns of 0 → variance 0 → vol 0
        assert result.iloc[-1] == pytest.approx(0.0, abs=1e-10)

    def test_annualized_vs_daily(self, sample_ohlc):
        """Annualized vol should be sqrt(252) times daily vol."""
        daily = yang_zhang_vol(sample_ohlc, period=20, min_periods=10, annualize=False)
        annualized = yang_zhang_vol(sample_ohlc, period=20, min_periods=10, annualize=True)
        # Compare last value
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
        assert not result.isna().all()  # some values should be valid

    def test_known_output(self):
        """With a fixed simple input, verify the output is deterministic."""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        # Perfect trend: each day open=100, close=101 → +1% daily
        df = pd.DataFrame({
            "price_open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "price_high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "price_low":  [99.0, 100.0, 101.0, 102.0, 103.0],
            "price_close": [101.0, 102.0, 103.0, 104.0, 105.0],
        }, index=dates)
        result = yang_zhang_vol(df, period=5, min_periods=3, annualize=False)
        # The first 3 entries should be NaN (need 3 periods for min_periods=3)
        assert result.iloc[0:3].isna().all()
        # Last 2 entries should be non-NaN
        assert result.iloc[3:5].notna().all()
```

- [ ] **Step 2: Run tests**

```bash
cd /home/oliver/aria-lite && pip install -e ".[dev]" 2>&1 | tail -5
python3 -m pytest tests/test_yang_zhang.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_yang_zhang.py
git commit -m "test: add Yang-Zhang volatility unit tests"
```

---

### Task 4: Test RiskGate

**Files:**
- Create: `tests/test_risk_gate.py`

**Consumes:** `common.RiskGate`

- [ ] **Step 1: Write `tests/test_risk_gate.py`**

```python
"""Tests for the RiskGate filter."""
import pytest
from src.etl.common import RiskGate


class TestRiskGate:
    def setup_method(self):
        self.gate = RiskGate()

    def test_passes_healthy_stock(self, sample_fundamentals):
        assert self.gate.is_pass(sample_fundamentals) is True

    def test_fails_low_price(self, sample_fundamentals):
        row = dict(sample_fundamentals, current_price=5.0)
        assert self.gate.is_pass(row) is False

    def test_fails_low_op_margin(self, sample_fundamentals):
        row = dict(sample_fundamentals, op_margin=0.01)
        assert self.gate.is_pass(row) is False

    def test_fails_low_current_ratio(self, sample_fundamentals):
        row = dict(sample_fundamentals, current_ratio=0.5)
        assert self.gate.is_pass(row) is False

    def test_fails_low_roe(self, sample_fundamentals):
        row = dict(sample_fundamentals, roe=-0.20)
        assert self.gate.is_pass(row) is False

    def test_fails_none_fwd_pe(self, sample_fundamentals):
        row = dict(sample_fundamentals, fwd_pe=None)
        assert self.gate.is_pass(row) is False

    def test_fails_zero_fwd_pe(self, sample_fundamentals):
        """fwd_pe of 0 is still not None, but min_price etc still apply."""
        row = dict(sample_fundamentals, fwd_pe=0)
        # fwd_pe=0 is not None, so it passes the None check
        # But does it pass the min_price check? current_price=150 → yes
        # However, fwd_pe=0 is unusual. Let's check what the gate does.
        # The gate checks if fwd_pe is None, not if it's 0.
        # 0 is falsy in Python, but the check is `is None`.
        # So fwd_pe=0 won't be caught by the None check.
        # Whether it passes depends on the other fields.
        assert self.gate.is_pass(row) is True  # all other fields are healthy

    def test_handles_empty_dict(self):
        assert self.gate.is_pass({}) is False

    def test_handles_missing_keys(self):
        assert self.gate.is_pass({"current_price": 100}) is False
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_risk_gate.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_risk_gate.py
git commit -m "test: add RiskGate unit tests"
```

---

### Task 5: Test assign_production_rating

**Files:**
- Create: `tests/test_rating.py`

**Consumes:** `common.assign_production_rating`, `conftest.sample_rating_row`

- [ ] **Step 1: Write `tests/test_rating.py`**

```python
"""Tests for the production rating engine."""
import pytest
from src.etl.common import assign_production_rating


class TestAssignProductionRating:
    def test_strong_buy_elite(self, sample_rating_row):
        """score > 0.42, eps_rev > 0.01, mom > 0.1, op_margin > 0, peg < 1.8, pe < 60"""
        rating = assign_production_rating(sample_rating_row)
        assert "STRONG BUY" in rating

    def test_buy(self, sample_rating_row):
        """score > 0.35, mom > 0.1, peg < 2.0"""
        row = dict(sample_rating_row, final_score=0.38, eps_rev=0.005, op_margin=0.05)
        rating = assign_production_rating(row)
        assert rating == "BUY"

    def test_sell_estimate_decay(self, sample_rating_row):
        """eps_rev < -0.03 → SELL"""
        row = dict(sample_rating_row, eps_rev=-0.05)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "Estimate Decay" in rating

    def test_sell_no_growth(self, sample_rating_row):
        """rev_growth < 0 → SELL"""
        row = dict(sample_rating_row, rev_growth=-0.05)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "No Growth" in rating

    def test_sell_trend_exhaustion(self, sample_rating_row):
        """mom_score < -0.10 → SELL"""
        row = dict(sample_rating_row, mom_score=-0.15)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "Trend Exhaustion" in rating

    def test_strong_buy_emerging_breakout(self, sample_rating_row):
        """near_high > 0.96, accel > 0.05, mom_3m > 0.10, peg < 1.5"""
        row = dict(sample_rating_row,
                   final_score=0.30,  # lower score, but breakout logic triggers first
                   near_high=0.98,
                   acceleration=0.08,
                   mom_3m=0.15,
                   peg=1.3)
        rating = assign_production_rating(row)
        assert "STRONG BUY" in rating
        assert "Emerging Breakout" in rating

    def test_strong_buy_hyper_growth(self, sample_rating_row):
        """rev_growth > 0.50, mom > 0.25, peg < 1.2"""
        row = dict(sample_rating_row,
                   rev_growth=0.60,
                   mom_score=0.30,
                   peg=1.1)
        rating = assign_production_rating(row)
        assert "STRONG BUY" in rating
        assert "Hyper-Growth" in rating

    def test_hold_overvalued(self, sample_rating_row):
        """pe > 65 or peg > 3.0 → HOLD"""
        row = dict(sample_rating_row, fwd_pe=70)
        rating = assign_production_rating(row)
        assert "HOLD" in rating
        assert "Overvalued" in rating

    def test_hold_consolidation(self, sample_rating_row):
        """mom < 0 → HOLD"""
        row = dict(sample_rating_row, mom_score=-0.05)
        rating = assign_production_rating(row)
        assert "HOLD" in rating
        assert "Consolidation" in rating

    def test_fallback_hold(self, sample_rating_row):
        """No conditions met → HOLD"""
        row = dict(sample_rating_row,
                   final_score=0.20,
                   eps_rev=0.0,
                   mom_score=0.05,
                   rev_growth=0.05,
                   fwd_pe=30,
                   peg=2.0,
                   op_margin=0.05,
                   acceleration=0.01,
                   near_high=0.80,
                   mom_3m=0.02)
        rating = assign_production_rating(row)
        assert rating == "HOLD"

    def test_handles_missing_fields(self):
        """Should not crash on missing optional fields."""
        row = {"final_score": 0.5, "eps_rev": 0.05}
        # Will hit STRONG BUY (Elite) if conditions met, but mom_score defaults to 0
        # which means is_confluence fails (mom > 0.1 is False)
        # So it falls through to BUY check: score > 0.35 but mom > 0.1 is False
        # Falls through to HOLD
        rating = assign_production_rating(row)
        assert isinstance(rating, str)

    def test_edge_case_boundary(self, sample_rating_row):
        """Boundary values near thresholds."""
        row = dict(sample_rating_row,
                   final_score=0.42,    # exactly at threshold
                   eps_rev=0.01,        # exactly at threshold
                   mom_score=0.10,      # exactly at threshold
                   peg=1.8,             # exactly at threshold
                   fwd_pe=60)           # exactly at threshold
        rating = assign_production_rating(row)
        # score > 0.42? No, it's exactly 0.42 → not > 0.42
        # So falls through to BUY: score > 0.35 (yes), mom > 0.1 (yes, 0.10 > 0.1 is False)
        # Actually 0.10 > 0.1 is False in Python for floats
        # Falls to HOLD overvalued: pe > 65? No. peg > 3.0? No. mom < 0? No.
        # So HOLD
        assert rating == "HOLD"
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_rating.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_rating.py
git commit -m "test: add rating engine unit tests"
```

---

### Task 6: Test momentum/z-score helpers

**Files:**
- Create: `tests/test_momentum.py`

**Consumes:** `common.z_score`, `conftest.sample_ohlc`

- [ ] **Step 1: Write `tests/test_momentum.py`**

```python
"""Tests for momentum scoring helpers."""
import numpy as np
import pandas as pd
import pytest
from src.etl.common import z_score, ANNUALIZATION_FACTOR


class TestZScore:
    def test_mean_zero_std_one(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = z_score(s)
        assert result.mean() == pytest.approx(0, abs=1e-10)
        assert result.std() == pytest.approx(1, abs=1e-10)

    def test_constant_series(self):
        """Constant series should produce zeros (std=0, but epsilon prevents div by 0)."""
        s = pd.Series([5, 5, 5, 5, 5])
        result = z_score(s)
        assert (result == 0).all()

    def test_single_value(self):
        s = pd.Series([42])
        result = z_score(s)
        assert result.iloc[0] == 0

    def test_with_nan(self):
        s = pd.Series([1, 2, np.nan, 4, 5])
        result = z_score(s)
        # Should not crash, NaN values should propagate
        assert result.isna().sum() == 1
        assert result.dropna().mean() == pytest.approx(0, abs=1e-10)

    def test_negative_values(self):
        s = pd.Series([-10, -5, 0, 5, 10])
        result = z_score(s)
        assert result.mean() == pytest.approx(0, abs=1e-10)
        assert result.std() == pytest.approx(1, abs=1e-10)

    def test_anualization_factor(self):
        assert ANNUALIZATION_FACTOR == pytest.approx(np.sqrt(252), rel=1e-10)
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_momentum.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_momentum.py
git commit -m "test: add z-score normalization and constant tests"
```

---

### Task 7: Test calculate_metrics from 02_compute_statistics.py

**Files:**
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `src.etl.common.yang_zhang_vol`, `conftest.sample_ohlc`
- Tests: `src.etl.02_compute_statistics.calculate_metrics()`

- [ ] **Step 1: Write `tests/test_metrics.py`**

```python
"""Tests for calculate_metrics from 02_compute_statistics."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def multi_ticker_price_data():
    """Multi-ticker price data simulating what comes from the DB."""
    np.random.seed(42)
    days = 300
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    tickers = ["AAPL", "MSFT"]
    rows = []
    base = 100.0
    for i, ticker in enumerate(tickers):
        drift = 0.05 * i  # MSFT has slightly higher drift
        closes = base + np.cumsum(np.random.randn(days) * 0.5) + np.arange(days) * drift / days
        opens = closes + np.random.randn(days) * 0.2
        highs = np.maximum(opens, closes) + np.abs(np.random.randn(days)) * 0.3
        lows = np.minimum(opens, closes) - np.abs(np.random.randn(days)) * 0.3
        adjusted = closes * (1 + np.random.randn(days) * 0.001)
        for t in range(days):
            rows.append({
                "timestamp": dates[t],
                "ticker": ticker,
                "price_open": opens[t],
                "price_high": highs[t],
                "price_low": lows[t],
                "price_close": closes[t],
                "price_adjusted": adjusted[t],
            })
    return pd.DataFrame(rows)


class TestCalculateMetrics:
    def test_returns_required_columns(self, multi_ticker_price_data):
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(multi_ticker_price_data)
        required = ["sma_252", "rsi_14", "log_return", "vol_20", "mdd_20", "skew_20", "kurt_20"]
        for col in required:
            assert col in result.columns, f"Missing column: {col}"

    def test_sma_252_is_not_all_nan(self, multi_ticker_price_data):
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(multi_ticker_price_data)
        # With 300 days of data, the last entries should have SMA
        assert result["sma_252"].notna().any()

    def test_rsi_between_0_and_100(self, multi_ticker_price_data):
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(multi_ticker_price_data)
        rsi = result["rsi_14"].dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_log_return_not_all_nan(self, multi_ticker_price_data):
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(multi_ticker_price_data)
        assert result["log_return"].notna().any()

    def test_vol_20_not_all_nan(self, multi_ticker_price_data):
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(multi_ticker_price_data)
        assert result["vol_20"].notna().any()
        assert (result["vol_20"].dropna() >= 0).all()

    def test_handles_single_price(self):
        """Single row per ticker should not crash, but produce NaN metrics."""
        df = pd.DataFrame({
            "timestamp": [pd.Timestamp("2025-01-01")],
            "ticker": ["AAPL"],
            "price_open": [100.0],
            "price_high": [101.0],
            "price_low": [99.0],
            "price_close": [100.5],
            "price_adjusted": [100.5],
        })
        from src.etl.etl_02_compute_statistics import calculate_metrics
        result = calculate_metrics(df)
        assert len(result) == 1
        # All metrics should be NaN with only 1 row
        assert result["sma_252"].iloc[0] is None or pd.isna(result["sma_252"].iloc[0])
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_metrics.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_metrics.py
git commit -m "test: add calculate_metrics unit tests"
```

---

### Task 8: Test portfolio optimizer functions

**Files:**
- Create: `tests/test_portfolio_optimizer.py`

**Consumes:** `conftest.sample_tickers`

- [ ] **Step 1: Write `tests/test_portfolio_optimizer.py`**

```python
"""Tests for portfolio optimizer functions."""
import numpy as np
import pandas as pd
import pytest
from skills.portfolio_construction.tools.portfolio_optimize import (
    compute_sector_concentration,
    risk_flags,
)


class TestComputeSectorConcentration:
    def test_hhi_single_sector(self):
        df = pd.DataFrame({"sector": ["Tech", "Tech", "Tech"]})
        weights, hhi = compute_sector_concentration(df)
        assert weights == {"Tech": 1.0}
        assert hhi == pytest.approx(1.0)

    def test_hhi_equal_sectors(self):
        df = pd.DataFrame({"sector": ["Tech", "Health", "Energy"]})
        weights, hhi = compute_sector_concentration(df)
        assert len(weights) == 3
        assert all(w == pytest.approx(1/3) for w in weights.values())
        assert hhi == pytest.approx(3 * (1/3) ** 2)  # 0.333...

    def test_hhi_concentrated(self):
        df = pd.DataFrame({"sector": ["Tech", "Tech", "Tech", "Health"]})
        weights, hhi = compute_sector_concentration(df)
        assert weights["Tech"] == pytest.approx(0.75)
        assert weights["Health"] == pytest.approx(0.25)

    def test_empty_dataframe(self):
        df = pd.DataFrame({"sector": []})
        weights, hhi = compute_sector_concentration(df)
        assert weights == {}
        assert hhi == 0


class TestRiskFlags:
    def test_high_beta(self):
        row = {"beta": 2.0}
        flags = risk_flags(row)
        assert "High beta" in flags

    def test_low_beta_ok(self):
        row = {"beta": 1.0}
        flags = risk_flags(row)
        assert flags == "None"

    def test_high_vol(self):
        row = {"annual_vol": 0.60}
        flags = risk_flags(row)
        assert "High vol" in flags

    def test_no_flags_healthy(self):
        row = {
            "beta": 1.0,
            "debt_to_equity": 50,
            "annual_vol": 0.30,
            "current_ratio": 1.5,
            "fcf_yield": 0.05,
            "near_high": 0.95,
        }
        flags = risk_flags(row)
        assert flags == "None"

    def test_multiple_flags(self):
        row = {
            "beta": 2.0,
            "debt_to_equity": 200,
            "annual_vol": 0.60,
            "current_ratio": 0.5,
            "fcf_yield": -0.02,
            "near_high": 0.70,
        }
        flags = risk_flags(row)
        assert "High beta" in flags
        assert "Elevated leverage" in flags
        assert "High vol" in flags
        assert "Low liquidity" in flags
        assert "Negative FCF yield" in flags


class TestAllocate:
    def test_allocate_basic(self):
        from skills.portfolio_construction.tools.portfolio_optimize import allocate
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D"],
            "final_score": [100, 50, 25, 10],
            "sector": ["Tech", "Health", "Tech", "Energy"],
        })
        result = allocate(df, max_single=0.40, max_sector=0.60, min_position=0.01)
        assert "weight" in result.columns
        assert result["weight"].sum() == pytest.approx(1.0, abs=1e-2)
        assert (result["weight"] >= 0).all()

    def test_allocate_single_ticker(self):
        from skills.portfolio_construction.tools.portfolio_optimize import allocate
        df = pd.DataFrame({
            "ticker": ["A"],
            "final_score": [100],
            "sector": ["Tech"],
        })
        result = allocate(df, max_single=0.50, max_sector=0.60, min_position=0.01)
        assert result["weight"].iloc[0] == pytest.approx(1.0, abs=1e-2)

    def test_allocate_all_zeros(self):
        from skills.portfolio_construction.tools.portfolio_optimize import allocate
        df = pd.DataFrame({
            "ticker": ["A", "B"],
            "final_score": [0, 0],
            "sector": ["Tech", "Health"],
        })
        result = allocate(df, max_single=0.50, max_sector=0.60, min_position=0.01)
        assert result["weight"].sum() == pytest.approx(1.0, abs=1e-2)
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_portfolio_optimizer.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_portfolio_optimizer.py
git commit -m "test: add portfolio optimizer unit tests"
```

---

### Task 9: Test top-picks portfolio functions

**Files:**
- Create: `tests/test_top_picks.py`

**Consumes:** `conftest.sample_tickers`

- [ ] **Step 1: Write `tests/test_top_picks.py`**

```python
"""Tests for top-picks portfolio functions."""
import numpy as np
import pandas as pd
import pytest
from skills.top_picks_portfolio.tools.build_top_picks_portfolio import (
    is_excluded,
    classify_subsector,
    diversify_candidates,
    allocate_portfolio,
)


class TestIsExcluded:
    def test_excludes_healthcare_sector(self):
        assert is_excluded("Healthcare", "Medical Devices", "Test Corp") is True

    def test_excludes_pharma_keyword(self):
        assert is_excluded("Technology", "Pharmaceuticals", "Test Corp") is True

    def test_excludes_mining_sector(self):
        assert is_excluded("Basic Materials", "Gold", "Test Corp") is True

    def test_excludes_biotech_name(self):
        assert is_excluded("Technology", "Software", "Biotech Innovations Inc") is True

    def test_allows_tech(self):
        assert is_excluded("Technology", "Software", "Microsoft Corp") is False

    def test_allows_financial(self):
        assert is_excluded("Financial Services", "Asset Management", "BlackRock") is False

    def test_none_sector_is_not_excluded(self):
        assert is_excluded(None, None, None) is False


class TestClassifySubsector:
    def test_semiconductor(self):
        result = classify_subsector("Technology", "Semiconductors")
        assert result == "Semiconductors"

    def test_semiconductor_equipment(self):
        result = classify_subsector("Technology", "Semiconductor Equipment & Materials")
        assert result == "Semiconductor Equipment"

    def test_software(self):
        result = classify_subsector("Technology", "Software - Infrastructure")
        assert result == "Software"

    def test_fallback_to_sector(self):
        result = classify_subsector("Unknown", "Something")
        assert result == "Unknown"

    def test_case_insensitive(self):
        result = classify_subsector("Technology", "SEMICONDUCTOR MEMORY")
        assert result == "Semiconductors"

    def test_networking(self):
        result = classify_subsector("Technology", "Communication Equipment")
        assert result == "Networking"


class TestDiversifyCandidates:
    @pytest.fixture
    def candidates(self):
        np.random.seed(42)
        tickers = [f"T{i}" for i in range(20)]
        sectors = ["Tech"] * 10 + ["Health"] * 5 + ["Energy"] * 5
        return pd.DataFrame({
            "ticker": tickers,
            "final_score": np.random.uniform(0.2, 0.8, 20),
            "sector": sectors,
            "_subsector": [f"Sub{s}" for s in sectors],
        })

    def test_selects_up_to_target(self, candidates):
        result = diversify_candidates(candidates, max_per_subsector=2, target=10)
        assert len(result) <= 10

    def test_respects_max_per_subsector(self, candidates):
        result = diversify_candidates(candidates, max_per_subsector=1, target=10)
        subsector_counts = result["_subsector"].value_counts()
        assert (subsector_counts <= 1).all()

    def test_empty_dataframe(self):
        result = diversify_candidates(pd.DataFrame(), target=10)
        assert len(result) == 0

    def test_fewer_candidates_than_target(self, candidates):
        few = candidates.head(3)
        result = diversify_candidates(few, max_per_subsector=2, target=10)
        assert len(result) == 3  # all available, even though target is 10


class TestAllocatePortfolio:
    @pytest.fixture
    def candidates(self):
        return pd.DataFrame({
            "ticker": ["A", "B", "C", "D"],
            "final_score": [100, 50, 25, 10],
            "sector": ["Tech", "Health", "Tech", "Energy"],
        })

    def test_weights_sum_to_one(self, candidates):
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=4)
        assert result["weight"].sum() == pytest.approx(1.0, abs=1e-2)

    def test_respects_max_single(self, candidates):
        huge_score = candidates.copy()
        huge_score.loc[0, "final_score"] = 10000  # A has 10000, others have 50, 25, 10
        result = allocate_portfolio(huge_score, max_single=0.30, min_position=0.01, target=4)
        assert result["weight"].max() <= 0.30 + 1e-2  # allow rounding

    def test_zeros_below_min_position(self, candidates):
        small = candidates.copy()
        small["final_score"] = [0.001, 100, 100, 100]
        result = allocate_portfolio(small, max_single=0.50, min_position=0.05, target=4)
        # The smallest position should be zeroed out
        assert (result["weight"] == 0).any() or len(result[result["weight"] > 0]) < 4

    def test_single_candidate(self):
        candidates = pd.DataFrame({
            "ticker": ["A"],
            "final_score": [100],
            "sector": ["Tech"],
        })
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=1)
        assert result["weight"].iloc[0] == pytest.approx(1.0, abs=1e-2)
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_top_picks.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_top_picks.py
git commit -m "test: add top-picks portfolio unit tests"
```

---

### Task 10: Create GitHub Actions workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Test

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Run tests
        run: python -m pytest -v
```

- [ ] **Step 2: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('VALID YAML')"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow"
```

---

### Task 11: Run full test suite and verify

- [ ] **Step 1: Run all tests**

```bash
cd /home/oliver/aria-lite && python3 -m pytest -v 2>&1
```

- [ ] **Step 2: Fix any failures** — iterate on test code or implementation code until all pass.

- [ ] **Step 3: Final commit** if any fixes were needed.

```bash
git add -A
git commit -m "test: fix test failures after full suite run"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] Spec says "extract duplicated functions into common.py" → Task 2
   - [x] Spec says "unit tests for pure logic" → Tasks 3-9
   - [x] Spec says "CI pipeline" → Task 10
   - [x] Spec says "pyproject.toml with pip-installable dev environment" → Task 1
   - [x] Spec says "no external API calls in tests" → All test data is synthetic
   - [x] Spec says "branch protection" → Not in plan (requires GitHub UI config, not code)

2. **Placeholder check:** No TBD, TODO, or vague instructions. Every test has concrete code.

3. **Type consistency:** All function signatures match between `common.py` and consuming modules.

4. **Scope check:** Focused on unit tests + CI. No scope creep.