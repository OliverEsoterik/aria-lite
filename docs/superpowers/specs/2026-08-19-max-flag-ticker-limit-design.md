# Replace `tickers_to_trade.json` with a `MAX` flag pipeline parameter

**Date:** 2026-08-19
**Status:** Draft
**Branch:** `feat/max-flag-for-ticker-limit`

## Context

The pipeline currently uses a manually curated `data/tickers_to_trade.json` file (2,501 tickers) to
control which securities `01_fetch_price_data.py` downloads price data for. This file is a separate
artifact that must be maintained independently of the SEC entity data.

The SEC's `company_tickers_exchange.json` already contains all publicly traded companies (~10,387)
ordered by market cap, and is loaded into `dim_entities` by `00_populate_entities.py`. The JSON
file's ticker list is substantially similar to the top-N by market cap, with minor differences
(alternate share classes, ETFs, OTC tickers) that provide no clear benefit over the authoritative
SEC ordering.

## Goals

- Remove the separate `tickers_to_trade.json` file
- Source tickers directly from `dim_entities` (ordered by market cap, via `entity_pk`)
- Allow the user to limit how many tickers get price-fetched via a `MAX` flag
- `make setup` with no flag = process all tickers (current behavior, minus the JSON file)

## Non-goals

- Adding a curation mechanism to the database (no `is_active` column, no tagging)
- Changing how `00_populate_entities.py` works — it always populates all entities
- Changing how steps 02–05 work — they already query the database directly

## Design

### Interface

| Command | Behavior |
|---|---|
| `make setup` | Populate all entities, fetch prices for all tickers |
| `make setup MAX=100` | Populate all entities, fetch prices only for top 100 |
| `make run` | Skip entities, fetch prices for all tickers |
| `make run MAX=100` | Skip entities, fetch prices only for top 100 |

### Data flow

```
make setup MAX=100
  │
  ▼
scripts/run_etl.sh --max 100
  │
  ├── 00_populate_entities.py    ← unchanged
  │
  └── 01_fetch_price_data.py --max 100
        │
        └── Query: SELECT * FROM dim_entities ORDER BY entity_pk ASC LIMIT 100
              │
              └── Fetch yfinance prices for those 100 tickers
```

### Changes by file

#### 1. `Makefile`

- Add `MAX ?=` variable declaration at the top (defaults to empty/unset)
- `setup` target: pass `$(if $(MAX),--max $(MAX),)` to `run_etl.sh`
- `run` target: same, pass `$(if $(MAX),--max $(MAX),)` to `run_etl.sh`

#### 2. `scripts/run_etl.sh`

- Accept `--max N` argument (in addition to existing `--skip-entities`)
- Pass `--max N` to `01_fetch_price_data.py` as `--max N`
- No change to how `00_populate_entities.py` is called — it always runs fully

#### 3. `src/etl/01_fetch_price_data.py`

- Remove the `TICKER_LIST_PATH` constant and `load_tickers()` function
- Add `--max` CLI argument (optional int, default = `None` = no limit)
- Replace `load_tickers(TICKER_LIST_PATH)` with a query against `dim_entities`:
  ```python
  query = "SELECT ticker, entity_pk FROM dim_entities ORDER BY entity_pk ASC"
  params = {}
  if max_tickers:
      query += " LIMIT :max_tickers"
      params = {"max_tickers": max_tickers}
  ```
- Remove the `ticker_map` lookup step — `entity_pk` comes directly from the query result
- Everything else (chunking, yfinance download, upsert to `market_prices`) stays the same

#### 4. `data/tickers_to_trade.json`

- Deleted

### Edge cases

| Case | Behavior |
|---|---|
| `MAX=0` or not set | No limit — process all tickers from `dim_entities` |
| `MAX > total entities` | Process all (LIMIT is a no-op) |
| `make run MAX=100` | Works — entities already populated, processes top 100 |
| `make setup MAX=100` on first run | Entities populated fully, only top 100 get prices |
| `dim_entities` is empty | `01_fetch_price_data.py` exits cleanly with no tickers to process |

### Verification

1. `make setup MAX=10` — only 10 tickers get price data
2. `make setup` (no MAX) — all tickers in `dim_entities` get price data
3. `make run MAX=5` — skips entity population, fetches prices for top 5
4. `make run` (no MAX, entities already populated) — fetches prices for all tickers
5. No remaining references to `tickers_to_trade.json` in the codebase