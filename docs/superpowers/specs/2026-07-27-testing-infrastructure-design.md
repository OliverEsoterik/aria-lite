# Testing Infrastructure Design

> **Status:** Design Document
> **Date:** 2026-07-27
> **Scope:** Unit tests for aria-lite ETL pipeline and skill tools, CI pipeline, branch protection

## Context

aria-lite is a quantitative equity research pipeline. It ingests SEC entity data, fetches price history from Yahoo Finance, computes technical indicators (Yang-Zhang volatility, RSI, momentum), and generates production ratings. The pipeline also includes portfolio construction tools.

The codebase has zero tests. Pure computation logic is copy-pasted across multiple files. External dependencies (PostgreSQL, Yahoo Finance API, SEC API) are coupled directly into scripts, making testing without a database impossible.

## Goals

1. **Unit-test all pure computation logic** — Yang-Zhang vol, rating engine, risk gate, momentum scoring, portfolio allocation, diversification logic — with synthetic data, no network calls
2. **Make tests runnable without Nix** — a developer or CI runner should need only `pip install -e ".[dev]"` and `pytest`
3. **CI pipeline** — GitHub Actions runs tests on every push/PR to `main`/`develop`
4. **Branch protection** — PRs require passing CI checks before merge

## Non-Goals

- Integration tests with a real database (future work)
- End-to-end tests that hit Yahoo Finance or SEC APIs (future work)
- Tests for the shell script `scripts/run_etl.sh`
- Coverage thresholds or code coverage reporting (add later if needed)

## Design

### 1. Shared Module: `src/etl/common.py`

Currently, these functions are copy-pasted across files:

| Function | Files where duplicated |
|---|---|
| `yang_zhang_vol()` | `02_compute_statistics.py`, `03_generate_production_ratings.py`, `score_tickers.py` |
| `RiskGate` class | `03_generate_production_ratings.py`, `score_tickers.py` |
| `assign_production_rating()` / `assign_rating()` | `03_generate_production_ratings.py`, `score_tickers.py` |
| `z_score()` helper | `03_generate_production_ratings.py`, `score_tickers.py` |

Extract these into `src/etl/common.py` with backward-compatible imports in the original files. This is a pure refactor — no behavior changes.

The `common.py` module will contain:
- `yang_zhang_vol(df, period, min_periods, annualize)` — pure function
- `class RiskGate` — pure logic, no I/O
- `assign_production_rating(row)` — pure function
- `z_score(series)` — pure function
- `ANNUALIZATION_FACTOR` — constant

### 2. Test Framework

**Test runner:** pytest with:
- `pytest-cov` for coverage reporting (optional, configured but not enforced)
- `pytest-xdist` for parallel execution (optional)

**Test location:** `tests/` at project root.

**Test data:** All synthetic. Small DataFrames with known values constructed in `tests/conftest.py` fixtures.

### 3. Test Modules

| Test file | What it tests | Source functions |
|---|---|---|
| `tests/test_yang_zhang.py` | Yang-Zhang volatility estimator | `common.yang_zhang_vol()` |
| `tests/test_risk_gate.py` | Risk gate pass/fail logic | `common.RiskGate` |
| `tests/test_rating.py` | Production rating assignment | `common.assign_production_rating()` |
| `tests/test_momentum.py` | Momentum scoring, z-score normalization | `common.z_score()`, scoring helpers |
| `tests/test_metrics.py` | `calculate_metrics()` from `02_compute_statistics.py` | `02_compute_statistics.calculate_metrics()` |
| `tests/test_portfolio_optimizer.py` | `allocate()`, `compute_sector_concentration()`, `risk_flags()` | `portfolio_optimize.py` |
| `tests/test_top_picks.py` | `classify_subsector()`, `is_excluded()`, `diversify_candidates()`, `allocate_portfolio()` | `build_top_picks_portfolio.py` |

### 4. Build Configuration

Add `pyproject.toml` to project root with:
- Package metadata (name: `aria-lite`)
- Dependencies (pandas, numpy, yfinance, psycopg2, sqlalchemy, pandas-ta, requests)
- Optional dev dependencies (pytest, pytest-cov)
- pytest configuration

This allows `pip install -e ".[dev]"` and `pytest` without Nix.

### 5. CI Pipeline

GitHub Actions workflow (`.github/workflows/test.yml`):
- Trigger: push/PR to `main`, `develop`
- Python 3.12
- Steps: checkout → setup Python → pip install → pytest
- No Nix, no PostgreSQL, no external services

### 6. Branch Protection

Configure GitHub repo settings:
- Require PRs to merge to `main`/`develop`
- Require status checks to pass before merging
- Require CI test workflow to pass

## Alternatives Considered

**A. Keep Nix for CI.** Rejected because it adds complexity, slow cold-start, and fewer developers are familiar with Nix. A `pyproject.toml` is the standard Python approach.

**B. Integration tests with testcontainers-postgres.** Rejected for phase 1 — adds Docker dependency and complexity. Worth considering for phase 2.

**C. Test each copy of duplicated code independently.** Rejected — duplication is a bug attractor and wastes test effort. Extract once, test once.

## Edge Cases

- Yang-Zhang vol with zero prices, NaN gaps, single-row dataframes
- Rating engine with missing fields, None values, extreme values
- Risk gate with missing keys, empty data
- Momentum with < 63 days of data, < 252 days of data
- Portfolio allocation with single ticker, all same sector, scores all zero
- Diversification with fewer candidates than target positions