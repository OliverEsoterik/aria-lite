# TSMOM Execution Engine — `--positions-file` Input

**Date:** 2025-07-12
**Status:** Draft
**Branch:** `feature/positions-file`

## Problem

The TSMOM execution engine (`04_tsmom_execution_engine.py`) currently accepts portfolio
positions as decimal weights via `--weights-file` (e.g. `{"NVDA": 0.05}`).  The user
wants to supply **absolute dollar/EUR amounts** (`{"NVDA": 10000}`) instead, because
that's what they see in their brokerage account — no mental conversion to percentages.

## Design

### CLI

Add a new optional argument `--positions-file`:

```
python 04_tsmom_execution_engine.py --positions-file data/my_positions.json
```

- **Mutual exclusivity:** `--positions-file` and `--weights-file` are independent.
  If both are supplied, `--positions-file` wins (the engine prints a note and ignores
  `--weights-file`).  If neither is supplied, behaviour is unchanged (equal-weight for
  all tickers in `CURRENT_PORTFOLIO`).

### Input format

JSON file mapping ticker → non-negative number representing current holding in the
user's currency (EUR, USD, etc.):

```json
{
  "NVDA": 10000,
  "MSFT": 8000,
  "GOOG": 0
}
```

- Zero / absent tickers are treated as "not currently held" (weight 0.0).
- Negative values raise a validation error.
- The currency is opaque to the engine — it simply propagates "units" unchanged.

### Internal flow

1. `load_positions(path: str) -> Dict[str, float]` — new function.
   - Opens & validates JSON; exits with error on file-not-found, invalid JSON, or
     negative values.
   - Returns `{ticker: raw_amount}`.
2. In `main()`: if `--positions-file` was given, load positions, compute
   `total = sum(amounts)`, then convert to weights:
   `{ticker: amount / total for ticker, amount in positions.items()}`.
   These weights are passed into `calculate_orders()` — **no engine changes needed**.
3. Track `total_portfolio_value` so the output layer can reconstruct dollar amounts
   from weights.

### Output changes

`print_orders()` gains two format modes:

| Column    | Weights mode (existing) | Positions mode (new)                |
|-----------|------------------------|-------------------------------------|
| Ticker    | `NVDA`                 | `NVDA`                              |
| Curr      | `5.00%`                | `€10,000  (5.00%)`                  |
| Tgt       | `12.50%`               | `€25,000  (12.50%)`                 |
| Delta     | `+7.50%`               | `+€15,000  (+7.50%)`                |
| Action    | `BUY`                  | `BUY`                               |

In positions mode, dollar amounts are derived from target weights × total portfolio
value.  The currency symbol defaults to `€` (user-configurable via an environment
variable `TSMOM_CURRENCY` if desired; `€` is the hardcoded default).

### Makefile

New target mirroring the existing `tsmom-weights`:

```makefile
tsmom-positions: start-db
	@test -n "$(POSITIONS_FILE)" || (echo "[ERROR] Usage: make tsmom-positions POSITIONS_FILE=path/to/positions.json" && exit 1)
	@echo "Running TSMOM Execution Engine with positions file..."
	cd src/etl && python3 04_tsmom_execution_engine.py --positions-file ../../$(POSITIONS_FILE)
```

### Backward compatibility

- `--weights-file` continues to work unchanged.
- Equal-weight default (no flag) is unchanged.
- `CURRENT_PORTFOLIO` in script 03 is still the source of *which tickers* to evaluate;
  `--positions-file` only supplies *current holdings* for those tickers.

### Files changed

| File | Change |
|------|--------|
| `src/etl/04_tsmom_execution_engine.py` | Add `--positions-file` arg, `load_positions()` function, positions-aware output |
| `Makefile` | Add `tsmom-positions` target |

### Non-goals

- No changes to `CURRENT_PORTFOLIO` or script 03.
- No changes to the TSMOM engine logic (`calculate_orders`).
- No interactive prompt mode.
- No database persistence of positions.