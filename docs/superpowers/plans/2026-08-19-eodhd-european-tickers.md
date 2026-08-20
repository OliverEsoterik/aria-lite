# EODHD European Tickers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new script that fetches European stock tickers from the EODHD API and stores them in `dim_entities` alongside existing US tickers, with zero schema changes.

**Architecture:** New `00_populate_european_entities.py` script fetches ticker lists per European exchange from EODHD, maps exchange codes to yfinance suffixes (e.g. `WAR` → `.WA`), constructs full ticker symbols (e.g. `CDR.WA`), and upserts them into `dim_entities` via the same `INSERT ... ON CONFLICT` pattern used by the existing SEC script. Two new Make targets allow running either population script independently.

**Tech Stack:** Python 3, requests, psycopg2, EODHD API

**Global Constraints:**
- Zero schema changes to `dim_entities` or `market_prices`
- Zero changes to existing scripts (`00_populate_entities.py`, `01_fetch_price_data.py`, `run_etl.sh`)
- `entity_identifier` = ISIN for European tickers (CIK for US tickers)
- Ticker format = `{Code}.{suffix}` for yfinance compatibility (e.g. `PKN.WA`, `SIE.DE`)
- EODHD daily limit: 20 calls/day. Full European refresh = ~15 calls. Must support limiting during testing.
- `EODHD_API_TOKEN` env var for the API key
- `SEC_USER_AGENT_EMAIL` env var used as User-Agent for EODHD requests (per their terms)

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/etl/00_populate_european_entities.py` | Create | Fetches European tickers from EODHD, maps suffixes, upserts into `dim_entities` |
| `Makefile` | Modify | Add `update-sec-tickers` and `update-eu-tickers` targets |

---

### Task 1: Create European ticker population script

**Files:**
- Create: `src/etl/00_populate_european_entities.py`
- Test: Run manually against a single exchange (Warsaw — ~600 rows, 1 API call)

**Interfaces:**
- Consumes: `EODHD_API_TOKEN` (env), `SEC_USER_AGENT_EMAIL` (env), `DATABASE_URL` (env)
- Produces: Rows in `dim_entities` with `entity_identifier` = ISIN, `ticker` = `Code.suffix`, `company_name` = Name

- [ ] **Step 1: Create the script**

Write `src/etl/00_populate_european_entities.py` with the following structure:

```python
import requests
import psycopg2
import os
import sys

# --- CONFIGURATION ---
EODHD_TOKEN = os.environ.get("EODHD_API_TOKEN")
if not EODHD_TOKEN:
    print("Error: EODHD_API_TOKEN environment variable not set.")
    sys.exit(1)

HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT_EMAIL", "")}
DB_URL = os.environ.get("DATABASE_URL", "postgresql:///alphapicks")

# EODHD exchange code → yfinance suffix mapping
# For EURONEXT, suffix depends on Country field
EXCHANGE_CONFIG = [
    # (EODHD code, country → suffix mapping, default suffix)
    # Simple: one suffix per exchange
    ("LSE",      {"UK": ".L"},                  ".L"),
    ("XETRA",    {"Germany": ".DE"},             ".DE"),
    ("SW",       {"Switzerland": ".SW"},          ".SW"),
    ("BIT",      {"Italy": ".MI"},               ".MI"),
    ("STO",      {"Sweden": ".ST"},              ".ST"),
    ("HEL",      {"Finland": ".HE"},             ".HE"),
    ("CPH",      {"Denmark": ".CO"},             ".CO"),
    ("OSL",      {"Norway": ".OL"},              ".OL"),
    ("WAR",      {"Poland": ".WA"},              ".WA"),
    ("BME",      {"Spain": ".MC"},              ".MC"),
    ("IR",       {"Ireland": ".IR"},             ".IR"),
    # EURONEXT: multi-country, resolve by Country field
    ("EURONEXT", {
        "France": ".PA",
        "Netherlands": ".AS",
        "Belgium": ".BR",
        "Portugal": ".LS",
    }, ".PA"),  # default to Paris if country unknown
]


def get_suffix(exchange_code: str, country: str) -> str:
    """Return the yfinance suffix for an exchange code + country."""
    for code, country_map, default in EXCHANGE_CONFIG:
        if code == exchange_code:
            return country_map.get(country, default)
    return ""  # unknown exchange, no suffix


def fetch_exchange_symbols(exchange_code: str) -> list:
    """Fetch active common stock symbols from EODHD for one exchange."""
    url = f"https://eodhd.com/api/exchange-symbol-list/{exchange_code}"
    params = {
        "api_token": EODHD_TOKEN,
        "fmt": "json",
        "type": "common_stock",
    }
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()


def load_european_data(exchange_filter: list = None):
    """
    Fetch and load European tickers into dim_entities.

    If exchange_filter is provided, only fetch those exchanges (for testing).
    """
    conn = None
    try:
        exchanges_to_fetch = EXCHANGE_CONFIG
        if exchange_filter:
            exchanges_to_fetch = [
                ec for ec in EXCHANGE_CONFIG if ec[0] in exchange_filter
            ]
            if not exchanges_to_fetch:
                print(f"Warning: no matching exchanges for filter {exchange_filter}")
                return

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        total_upserted = 0
        total_fetched = 0

        for exchange_code, country_map, default_suffix in exchanges_to_fetch:
            print(f"Fetching {exchange_code}...", end=" ", flush=True)
            try:
                symbols = fetch_exchange_symbols(exchange_code)
            except requests.exceptions.RequestException as e:
                print(f"FAILED: {e}")
                continue

            # Filter to Common Stock / Preferred Stock only
            symbols = [s for s in symbols if s.get("Type", "").lower()
                       in ("common stock", "preferred stock")]

            print(f"{len(symbols)} tickers", end="", flush=True)
            total_fetched += len(symbols)

            records = []
            for sym in symbols:
                code = sym.get("Code", "")
                isin = sym.get("Isin", "")
                name = sym.get("Name", "")
                country = sym.get("Country", "")

                if not code or not isin:
                    continue

                suffix = get_suffix(exchange_code, country)
                ticker = f"{code}{suffix}"

                records.append((isin, ticker, name))

            if not records:
                print(" → 0 upserted")
                continue

            sql = """
                INSERT INTO dim_entities (entity_identifier, ticker, company_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (entity_identifier, ticker)
                DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    dw_loaded_at = CURRENT_TIMESTAMP;
            """

            cur.executemany(sql, records)
            conn.commit()

            total_upserted += len(records)
            print(f" → {len(records)} upserted")

        print(f"\nDone. Fetched: {total_fetched}, Upserted: {total_upserted}")
        cur.close()

    except psycopg2.Error as e:
        print(f"\nDatabase Error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"\nError: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Optional: limit to specific exchanges for testing
    # Usage: python3 00_populate_european_entities.py --exchanges WAR,STO
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchanges", type=str, default=None,
                        help="Comma-separated exchange codes to fetch (default: all)")
    args = parser.parse_args()

    exchange_filter = args.exchanges.split(",") if args.exchanges else None
    load_european_data(exchange_filter)
```

- [ ] **Step 2: Test against a single exchange (1 API call)**

Run: `cd src/etl && EODHD_API_TOKEN=your_token SEC_USER_AGENT_EMAIL=your@email.com python3 00_populate_european_entities.py --exchanges WAR`

Expected output:
```
Fetching WAR... 612 tickers → 580 upserted

Done. Fetched: 612, Upserted: 580
```

- [ ] **Step 3: Verify rows in dim_entities**

Run: `psql alphapicks -c "SELECT ticker, company_name FROM dim_entities WHERE ticker LIKE '%.WA' LIMIT 5;"`

Expected: tickers like `PKN.WA`, `CDR.WA` with correct company names.

- [ ] **Step 4: Run full European refresh (15 API calls)**

Run: `cd src/etl && EODHD_API_TOKEN=your_token SEC_USER_AGENT_EMAIL=your@email.com python3 00_populate_european_entities.py`

Expected: All exchanges fetched, tickers inserted.

- [ ] **Step 5: Re-run to verify idempotency**

Run the same command again. Verify no errors and rows updated (dw_loaded_at changes).

- [ ] **Step 6: Verify yfinance can fetch prices for a European ticker**

Run: `python3 -c "import yfinance as yf; d = yf.download('PKN.WA', period='1mo', progress=False); print(d.shape); print(d.head())"`

Expected: OHLCV data returned, not empty.

- [ ] **Step 7: Run 01_fetch_price_data.py for a few European tickers**

Run: `cd src/etl && python3 01_fetch_price_data.py --max 5` — the `--max` limits to first 5 tickers from `dim_entities` (by entity_pk ASC). If those are US tickers, we need to verify that the ETL pipeline picks up European tickers once it runs with full data.

Instead, quick-check the pipeline works: run `cd src/etl && python3 01_fetch_price_data.py` briefly with CTRL+C after a few chunks to confirm no errors on European tickers.

- [ ] **Step 8: Commit**

```bash
git add src/etl/00_populate_european_entities.py
git commit -m "feat: add European ticker population script via EODHD API

New script fetches ticker lists from EODHD per European exchange,
maps exchange codes to yfinance suffixes (WAR -> .WA, LSE -> .L, etc.),
and upserts into dim_entities alongside existing US tickers.
Zero schema changes.
Supports --exchanges flag for testing with limited API calls."
```

---

### Task 2: Add Make targets for ticker population

**Files:**
- Modify: `Makefile` (after the `run:` target)

**Interfaces:**
- Consumes: `EODHD_API_TOKEN` and `SEC_USER_AGENT_EMAIL` env vars
- Produces: `make update-sec-tickers` and `make update-eu-tickers` commands

- [ ] **Step 1: Add Make target for SEC tickers**

Add after the `run:` target in Makefile:

```makefile
update-sec-tickers: start-db
	@echo "Updating SEC tickers..."
	SEC_USER_AGENT_EMAIL=$(SEC_USER_AGENT_EMAIL) \
		cd src/etl && python3 00_populate_entities.py
```

- [ ] **Step 2: Add Make target for European tickers**

```makefile
update-eu-tickers: start-db
	@test -n "$(EODHD_API_TOKEN)" || (echo "[ERROR] EODHD_API_TOKEN not set" && exit 1)
	@echo "Updating European tickers from EODHD..."
	SEC_USER_AGENT_EMAIL=$(SEC_USER_AGENT_EMAIL) \
		EODHD_API_TOKEN=$(EODHD_API_TOKEN) \
		cd src/etl && python3 00_populate_european_entities.py \
		$(if $(EXCHANGES),--exchanges $(EXCHANGES),)
```

Usage examples:
```
# Full European refresh
make update-eu-tickers EODHD_API_TOKEN=xxx

# Test with single exchange (1 API call)
make update-eu-tickers EODHD_API_TOKEN=xxx EXCHANGES=WAR

# Update SEC tickers
make update-sec-tickers
```

- [ ] **Step 3: Test the Make targets**

Run: `make update-eu-tickers EODHD_API_TOKEN=xxx EXCHANGES=WAR`

Expected: Script runs with only Warsaw exchange, 1 API call, tickers inserted.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "chore: add Make targets for SEC and European ticker updates

update-sec-tickers: runs 00_populate_entities.py standalone.
update-eu-tickers: runs 00_populate_european_entities.py with optional
EXCHANGES override for testing."
```