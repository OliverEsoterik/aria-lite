# MAX Flag Ticker Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `data/tickers_to_trade.json` with a `--max` flag that sources tickers from `dim_entities` in market-cap order.

**Architecture:** Four files change: `01_fetch_price_data.py` (core logic — query DB instead of JSON), `run_etl.sh` (pass through `--max`), `Makefile` (expose `MAX` variable), and the JSON file is deleted.

**Tech Stack:** Python 3, argparse, psycopg2/SQLAlchemy, Make, bash

## Global Constraints

- `MAX=0` or unset = no limit (process all tickers)
- `dim_entities` is already populated by `00_populate_entities.py` — no changes to that script
- Ticker order is `entity_pk ASC` (SEC market-cap order)
- Tickernames are normalized to uppercase via the existing `get_ticker_map()` logic
- No changes to steps 02–05

---

### Task 1: Modify `01_fetch_price_data.py` to accept `--max` and query DB

**Files:**
- Modify: `src/etl/01_fetch_price_data.py:1-50`

**Interfaces:**
- Consumes: `--max` CLI arg (optional int),`DATABASE_URL` env var
- Produces: `main()` reads tickers from `dim_entities ORDER BY entity_pk ASC LIMIT N` instead of JSON file

- [ ] **Step 1: Read the current file to confirm exact content**

```bash
cat src/etl/01_fetch_price_data.py
```

- [ ] **Step 2: Remove the `TICKER_LIST_PATH` constant and `load_tickers()` function**

Replace lines 6-11:
```python
import pandas as pd
import yfinance as yf
import json, os, time
import psycopg2.extras
from typing import List, Dict, Optional
from sqlalchemy import create_engine, text

# --- Configuration ---
DB_CONN_STR = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
TICKER_LIST_PATH = "../../data/tickers_to_trade.json"
DEFAULT_START_DATE = (pd.Timestamp.today() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')

CHUNK_SIZE = 200 # Reduced chunk size for more reliable YF downloads
API_SLEEP_SECONDS = 0.7

def load_tickers(file_path: str) -> List[str]:
    if not os.path.exists(file_path): return []
    with open(file_path, 'r') as f:
        return [t.strip().upper() for t in json.load(f) if t]
```

With:
```python
import pandas as pd
import yfinance as yf
import os, time, argparse
import psycopg2.extras
from typing import List, Dict, Optional
from sqlalchemy import create_engine, text

# --- Configuration ---
DB_CONN_STR = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
DEFAULT_START_DATE = (pd.Timestamp.today() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')

CHUNK_SIZE = 200
API_SLEEP_SECONDS = 0.7
```

- [ ] **Step 3: Add a `load_tickers_from_db()` function after the configuration block**

```python
def load_tickers_from_db(engine, max_tickers: Optional[int] = None) -> List[Dict]:
    """Fetch tickers from dim_entities ordered by market cap (entity_pk ASC).

    Returns a list of dicts with keys: ticker, entity_pk.
    If max_tickers is set, only the top N are returned.
    """
    query = "SELECT ticker, entity_pk FROM dim_entities ORDER BY entity_pk ASC"
    params = {}
    if max_tickers:
        query += " LIMIT :max_tickers"
        params = {"max_tickers": max_tickers}

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = [{"ticker": row.ticker, "entity_pk": row.entity_pk} for row in result]

    if not rows:
        print("   ! No tickers found in dim_entities. Run 00_populate_entities.py first.")
        return []

    print(f"   > Loaded {len(rows)} tickers from dim_entities" +
          (f" (top {max_tickers})" if max_tickers else ""))
    return rows
```

- [ ] **Step 4: Add `--max` argument parser**

Add before `main()`:
```python
def parse_args():
    parser = argparse.ArgumentParser(description="Fetch price data from yfinance")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximum number of tickers to process (default: all)")
    return parser.parse_args()
```

- [ ] **Step 5: Modify `main()` to use the new functions**

Replace the current `main()` body:
```python
def main():
    start_time = time.time()
    tickers = load_tickers(TICKER_LIST_PATH)
    engine = create_engine(DB_CONN_STR, pool_pre_ping=True)
    ticker_map = get_ticker_map(engine, tickers)

    valid_tickers = [t for t in tickers if t in ticker_map]
    last_dates_map = get_last_timestamps(engine, valid_tickers)
    ...
```

With:
```python
def main():
    args = parse_args()
    start_time = time.time()

    engine = create_engine(DB_CONN_STR, pool_pre_ping=True)

    # Load tickers from DB instead of JSON file
    ticker_rows = load_tickers_from_db(engine, max_tickers=args.max)
    if not ticker_rows:
        print(">>> No tickers to process. Exiting.")
        return

    # Build ticker_map from the query result (entity_pk already known)
    ticker_map = {row["ticker"]: row["entity_pk"] for row in ticker_rows}
    valid_tickers = list(ticker_map.keys())

    last_dates_map = get_last_timestamps(engine, valid_tickers)
    ...
```

- [ ] **Step 6: Remove the `get_ticker_map()` function entirely**

The function `get_ticker_map()` is no longer needed since `load_tickers_from_db()` already returns `entity_pk` alongside the ticker. The map is built directly in `main()`.

Delete the entire `get_ticker_map()` function block (approximately lines 19-30 in the original file).

- [ ] **Step 7: Run the script with `--help` to verify argparse works**

```bash
cd /home/oliver/aria-lite && python3 src/etl/01_fetch_price_data.py --help
```

Expected output:
```
usage: 01_fetch_price_data.py [-h] [--max MAX]

Fetch price data from yfinance

options:
  -h, --help  show this help message and exit
  --max MAX   Maximum number of tickers to process (default: all)
```

- [ ] **Step 8: Commit**

```bash
git add src/etl/01_fetch_price_data.py
git commit -m "feat: source tickers from dim_entities with --max flag

Remove tickers_to_trade.json dependency. 01_fetch_price_data.py now
queries dim_entities ORDER BY entity_pk ASC (SEC market-cap order)
with an optional --max LIMIT. The --max flag controls how many
tickers get price-fetched; no flag = all tickers."
```

---

### Task 2: Modify `run_etl.sh` to accept and forward `--max`

**Files:**
- Modify: `scripts/run_etl.sh:1-44`

**Interfaces:**
- Consumes: `--max N` CLI arg
- Produces: passes `--max N` to `01_fetch_price_data.py`

- [ ] **Step 1: Read the current file**

```bash
cat scripts/run_etl.sh
```

- [ ] **Step 2: Add `MAX_TICKERS` variable and `--max` parsing**

Add after `SKIP_ENTITY_POPULATION=false`:
```bash
MAX_TICKERS=""
```

Add a new case in the `while` loop:
```bash
        --max)
            MAX_TICKERS="$2"
            shift 2
            ;;
```

Update the usage message to include `--max`.

- [ ] **Step 3: Pass `--max` to `01_fetch_price_data.py`**

Change the `run_step` calls for Step 1 to include the max flag. Find this block:
```bash
# Step 1: Price Data Update
run_step "src/etl/01_fetch_price_data.py"
```

Replace with:
```bash
# Step 1: Price Data Update
if [ -n "$MAX_TICKERS" ]; then
    run_step "src/etl/01_fetch_price_data.py" "--max" "$MAX_TICKERS"
else
    run_step "src/etl/01_fetch_price_data.py"
fi
```

But wait — `run_step` currently takes only one argument (the script path). We need to modify `run_step` to accept optional arguments. Let me check the current `run_step` function.

Looking at the current `run_step`:
```bash
run_step() {
    local script_rel_path=$1
    local script_abs_path="$PROJECT_ROOT/$script_rel_path"
    local script_dir=$(dirname "$script_abs_path")
    local script_file=$(basename "$script_abs_path")

    while true; do
        ...
        python3 "$script_file"
        ...
    done
}
```

We need to pass extra args to `python3 "$script_file"`. Let me modify `run_step` to accept them.

- [ ] **Step 4: Modify `run_step` to forward extra arguments**

Change the function signature to accept `$@` and forward extra args:
```bash
run_step() {
    local script_rel_path=$1
    shift  # Remove the first arg, leaving $@ with extra args
    local extra_args="$@"
    local script_abs_path="$PROJECT_ROOT/$script_rel_path"
    local script_dir=$(dirname "$script_abs_path")
    local script_file=$(basename "$script_abs_path")

    while true; do
        ...
        python3 "$script_file" $extra_args
        ...
    done
}
```

- [ ] **Step 5: Verify the script parses correctly**

```bash
bash -n scripts/run_etl.sh
```

Expected: no output (syntax is valid)

- [ ] **Step 6: Commit**

```bash
git add scripts/run_etl.sh
git commit -m "feat: pass --max through run_etl.sh to 01_fetch_price_data.py"
```

---

### Task 3: Modify Makefile to expose `MAX` variable

**Files:**
- Modify: `Makefile:1-10`

**Interfaces:**
- Consumes: `MAX` environment variable (e.g., `make setup MAX=100`)
- Produces: passes `--max N` to `run_etl.sh`

- [ ] **Step 1: Read the current Makefile header**

```bash
head -10 Makefile
```

- [ ] **Step 2: Add `MAX` variable to the Makefile variable section**

Add after the `.PHONY` line or `SEC_USER_AGENT_EMAIL`:
```makefile
MAX ?=
```

- [ ] **Step 3: Update `setup` target to pass `MAX`**

Change:
```makefile
setup: start-db migrate
	SEC_USER_AGENT_EMAIL=$(SEC_USER_AGENT_EMAIL) ./scripts/run_etl.sh
```

To:
```makefile
setup: start-db migrate
	SEC_USER_AGENT_EMAIL=$(SEC_USER_AGENT_EMAIL) ./scripts/run_etl.sh $(if $(MAX),--max $(MAX),)
```

- [ ] **Step 4: Update `run` target to pass `MAX`**

Change:
```makefile
run: start-db
	@echo "Running daily services..."
	./scripts/run_etl.sh --skip-entities
```

To:
```makefile
run: start-db
	@echo "Running daily services..."
	./scripts/run_etl.sh --skip-entities $(if $(MAX),--max $(MAX),)
```

- [ ] **Step 5: Verify Makefile syntax**

```bash
make -n setup MAX=10
```

Expected output shows the command with `--max 10`.

- [ ] **Step 6: Commit**

```bash
git add Makefile
git commit -m "feat: add MAX variable to Makefile for ticker limiting"
```

---

### Task 4: Delete `tickers_to_trade.json` and verify no remaining references

**Files:**
- Delete: `data/tickers_to_trade.json`

- [ ] **Step 1: Delete the JSON file**

```bash
rm data/tickers_to_trade.json
```

- [ ] **Step 2: Verify no remaining references in source code**

```bash
grep -rn "tickers_to_trade" --include="*.py" --include="*.sh" --include="*.md" --include="*.json" --include="Makefile" .
```

Expected output: no matches (or only matches in the committed spec doc, which is fine)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove data/tickers_to_trade.json

No longer needed — tickers are now sourced from dim_entities
with an optional --max flag to limit how many are processed."
```

---

### Task 5: Functional verification

- [ ] **Step 1: Start the database**

```bash
make start-db
```

- [ ] **Step 2: Run `make setup MAX=5` to verify the pipeline works with a limit**

```bash
SEC_USER_AGENT_EMAIL=your.email@address.com make setup MAX=5
```

Expected:
- `00_populate_entities.py` runs and populates ALL entities
- `01_fetch_price_data.py` loads only the top 5 tickers from `dim_entities`
- `02_compute_statistics.py` and `03_generate_production_ratings.py` run normally

- [ ] **Step 3: Verify only 5 tickers have price data**

```bash
psql -h /tmp -p 5432 -d alphapicks -c "SELECT COUNT(DISTINCT ticker) FROM market_prices;"
```

Expected: 5

- [ ] **Step 4: Verify no `tickers_to_trade.json` references in the repo**

```bash
grep -rn "tickers_to_trade" . --include="*.py" --include="*.sh" --include="Makefile" --include="*.json" 2>/dev/null || echo "No references found"
```

Expected: "No references found" (or only the spec doc)

- [ ] **Step 5: Push the branch**

```bash
git push origin feat/max-flag-for-ticker-limit
```