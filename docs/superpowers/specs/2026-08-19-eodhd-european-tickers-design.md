# EODHD European Tickers — Design Document

> **Status:** Draft
> **Date:** 2026-08-19
> **Research basis:** EODHD API docs (eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours); SEC company_tickers_exchange.json (sec.gov); yfinance ticker suffix conventions
> **Practical basis:** Existing `00_populate_entities.py` fetches US tickers from SEC into `dim_entities`; `01_fetch_price_data.py` reads `dim_entities` and fetches prices from yfinance by ticker

## 1. Context and Motivation

The pipeline currently loads only US-registered tickers from the SEC's `company_tickers_exchange.json` endpoint. The SEC only covers US companies — European exchanges (LSE, XETRA, Euronext, SIX, Borsa Italiana, Nasdaq Nordic, WSE, BME, Oslo) are not represented.

This leaves out a substantial portion of the global investable universe. The downstream `01_fetch_price_data.py` already fetches price data via yfinance, which supports European tickers natively when given the correct exchange suffix (e.g. `CDR.WA` for Warsaw, `SIE.DE` for Xetra). What's missing is the ticker list itself — a source of which European securities exist and what their symbols are.

EODHD provides an API that mirrors the SEC endpoint's simplicity: one authenticated call per exchange returns every listed ticker with its ISIN, name, and currency. The free tier (20 calls/day) is sufficient for a weekly or monthly refresh of the ~15 European exchanges we'd cover.

The design is constrained by a hard requirement: **zero schema changes to `dim_entities`** and **zero changes to existing scripts**. The European ticker pipeline must slot in as a parallel process that writes to the same table without touching anything else.

## 2. Goals and Non-Goals

### Goals

- **Fetch European tickers from EODHD:** Pull listed securities from major European exchanges via EODHD's `exchange-symbol-list` endpoint.
- **Store in `dim_entities` alongside US tickers:** European tickers are additional rows in the existing table. No schema changes.
- **Construct yfinance-compatible ticker symbols:** Map EODHD exchange codes to yfinance suffixes (e.g. `WAR` → `.WA`) so that `01_fetch_price_data.py` can download prices for these tickers without modification.
- **Refresh on a sustainable cadence:** 15 exchanges × 1 call = 15 API calls per refresh, fitting within EODHD's free tier (20/day). Refresh weekly or monthly.
- **Preserve idempotency:** Re-running the script is safe — existing rows are updated on conflict, new rows inserted.

### Non-Goals

- **No fundamental data from EODHD:** EODHD also offers fundamentals, but the pipeline uses yfinance for fundamental data. We only fetch the ticker list.
- **No intraday or real-time data:** This is about listing tickers, not fetching prices. Price data remains yfinance's job.
- **No delisted ticker tracking:** EODHD can return delisted tickers via `?delisted=1`. Excluding delistings is intentional — we only want currently tradeable securities.
- **No US tickers via EODHD:** The existing SEC pipeline continues to handle US tickers. EODHD would duplicate this (with less reliable ISIN coverage for US stocks).
- **No exchange-venue breakdown within countries:** EODHD's `EURONEXT` exchange code aggregates Paris, Amsterdam, Brussels, and Lisbon. We use the exchange code as-is and derive the yfinance suffix from a static mapping.
  _Why not:_ The yfinance suffix is per-country (`.PA`, `.AS`, `.BR`, `.LS`). EODHD's response does not include the specific venue — only the aggregated exchange code. We'd need to resolve the venue from the ISIN or country field, which adds complexity for marginal gain. A static mapping from `EURONEXT` → the most common suffix (`.PA`) would miss some listings, so instead we map the EODHD exchange code to the correct suffix by checking the `Country` field in the response.

## 3. Proposed Design

### 3.1. Architecture Overview

Two parallel, independent pipelines writing to the same table:

```
┌──────────────────────────────┐     ┌──────────────────────────────┐
│  00_populate_entities.py     │     │  00_populate_european.py     │
│  (unchanged)                 │     │  (new)                       │
│                              │     │                              │
│  SEC → US tickers            │     │  EODHD → European tickers    │
│  CIK as entity_identifier    │     │  ISIN as entity_identifier   │
│  No suffix on ticker         │     │  Suffix on ticker (BP.L)     │
└──────────┬───────────────────┘     └──────────┬───────────────────┘
           │                                    │
           ▼                                    ▼
      ┌─────────────────────────────────────────────┐
      │            dim_entities                      │
      │  (entity_pk, entity_identifier, ticker,     │
      │   company_name, dw_loaded_at)               │
      │                                             │
      │  US rows: CIK zfilled, "AAPL", "Apple"     │
      │  EU rows: ISIN, "CDR.WA", "CD PROJEKT SA"  │
      └─────────────────────┬───────────────────────┘
                            │
                            ▼
      ┌─────────────────────────────────────────────┐
      │  01_fetch_price_data.py  (unchanged)         │
      │                                              │
      │  Reads all tickers → yf.download() → market_prices │
      └─────────────────────────────────────────────┘
```

No new tables, no new columns, no new indexes. The new script is the only addition.

### 3.2. Detailed Design

#### 3.2.1. EODHD Exchange → yfinance suffix mapping

EODHD returns a `Code` (base ticker) and an `Exchange` code. The full yfinance ticker is constructed as `{Code}.{suffix}`. The suffix is derived from the exchange code and country:

| EODHD Exchange Code | Country (in response) | yfinance Suffix | Example |
|---|---|---|---|
| `LSE` | UK | `.L` | `BP.L` |
| `XETRA` | Germany | `.DE` | `SIE.DE` |
| `EURONEXT` | France | `.PA` | `MC.PA` |
| `EURONEXT` | Netherlands | `.AS` | `ABN.AS` |
| `EURONEXT` | Belgium | `.BR` | `ABO.BR` |
| `EURONEXT` | Portugal | `.LS` | `EDP.LS` |
| `SW` | Switzerland | `.SW` | `NOVN.SW` |
| `BIT` | Italy | `.MI` | `ENI.MI` |
| `STO` | Sweden | `.ST` | `ERIC-B.ST` |
| `HEL` | Finland | `.HE` | `NOKIA.HE` |
| `CPH` | Denmark | `.CO` | `MAERSK-B.CO` |
| `OSL` | Norway | `.OL` | `EQNR.OL` |
| `WAR` | Poland | `.WA` | `PKN.WA` |
| `BME` | Spain | `.MC` | `SAN.MC` |
| `IR` | Ireland | `.IR` | `KR1.IR` |

This mapping is a static dict in the script — it doesn't need to be in the database.

#### 3.2.2. EODHD API calls

For each exchange code above, call:

```
GET https://eodhd.com/api/exchange-symbol-list/{EXCHANGE}?api_token={TOKEN}&fmt=json&type=common_stock
```

The `type=common_stock` filter limits results to Common Stock rows, excluding ETFs, funds, warrants, and notes (though some European instruments may still be classified differently — we rely on EODHD's Type field post-filter).

Response per exchange (typically 100–2000 rows):

```json
[
    {
        "Code": "PKN",
        "Name": "PKN Orlen SA",
        "Country": "Poland",
        "Exchange": "WAR",
        "Currency": "PLN",
        "Type": "Common Stock",
        "Isin": "PLPKN0000018"
    }
]
```

Filter: `Type` in `("Common Stock", "Preferred Stock")` — includes common and preferred equity, excludes ETFs, Funds, Warrants, Notes.

#### 3.2.3. Insert logic

Same pattern as the SEC script — `INSERT ... ON CONFLICT (entity_identifier, ticker) DO UPDATE`:

```python
sql = """
    INSERT INTO dim_entities (entity_identifier, ticker, company_name)
    VALUES (%s, %s, %s)
    ON CONFLICT (entity_identifier, ticker) 
    DO UPDATE SET 
        company_name = EXCLUDED.company_name,
        dw_loaded_at = CURRENT_TIMESTAMP;
"""
```

- `entity_identifier` = ISIN from the EODHD response
- `ticker` = `{Code}.{suffix}` (full yfinance symbol)
- `company_name` = `Name` from the EODHD response

If a row already exists with the same ISIN + ticker (e.g. from a previous run), it's updated. No duplicates. No conflicts with US rows (CIK vs ISIN never match).

#### 3.2.4. Script structure

New file: `src/etl/00_populate_european_entities.py`

```
src/etl/
├── 00_populate_entities.py          ← unchanged (SEC US tickers)
├── 00_populate_european_entities.py ← new (EODHD European tickers)
├── 01_fetch_price_data.py           ← unchanged (yfinance prices)
├── ...
```

Same conventions as the SEC script:
- Reads `EODHD_API_TOKEN` and `SEC_USER_AGENT_EMAIL` from environment (SEC_UA is a requirement of EODHD's terms too)
- Writes to the same `DATABASE_URL`
- Prints progress to stdout
- Returns non-zero on failure (for cron/CI to pick up)

### 3.3. User-Facing Changes

**None.** Ticketers appear automatically in `dim_entities` after the script runs. The next run of `01_fetch_price_data.py` will pick them up and start downloading prices. No configuration change, no restart, no migration.

The only change is operational: the user must sign up for an EODHD API key and set `EODHD_API_TOKEN` in their environment.

## 4. Alternatives Considered

### Alternative 1: Euronext CSV download (free, no API key)

The Euronext website has a download button that POSTs to a CSV endpoint. Proven to work (used by the `quantr` R package). Covers Euronext exchanges (Paris, Amsterdam, Brussels, Lisbon, Oslo).

- **Pros:** Free, no auth, no API key, includes ISIN.
- **Cons:** Scraping — subject to break if the endpoint changes. Only Euronext exchanges — no LSE, XETRA, Swiss, Nordic, Warsaw, Spanish, or Italian exchanges. Would need multiple sources to cover all of Europe.
- **Why rejected:** Incomplete coverage and maintenance risk from scraping. EODHD covers everything in one provider contract.

### Alternative 2: Xetra CSV download (free, no API key)

Xetra publishes a weekly CSV of all tradable instruments. No auth.

- **Pros:** Free, official, no API key.
- **Cons:** Xetra only (German stocks). No LSE, Euronext, or other major European exchanges. Weekly update cadence is inflexible. CSV format requires different parsing logic.
- **Why rejected:** Single-exchange coverage doesn't solve the problem. Would need to combine multiple disparate sources, each with a different format and update schedule.

### Alternative 3: Polygon.io

Polygon's `/v3/reference/tickers` endpoint supports MIC-based exchange filtering and returns tickers with FIGI identifiers.

- **Pros:** Well-documented, paginated, rich identifier support. Also usable for price data if we ever wanted to move off yfinance.
- **Cons:** Free tier is very restrictive. Paid tiers ($29+/month) are more expensive than EODHD for this use case (we only need ticker listings, not prices). Overkill for a ticker-list-only job.
- **Why rejected:** EODHD provides the same functionality at lower cost with a simpler API (no pagination — whole exchange in one response).

### Alternative 4: Community-maintained CSV lists (GitHub)

Repos like `Global-Stock-Symbols` provide scraped CSV lists for various exchanges, updated periodically.

- **Pros:** Free, no API key, no auth.
- **Cons:** Second-hand data — no guarantee of accuracy or timeliness. No SLA. May lag behind actual listings by weeks or months. Maintenance burden if the repo goes stale.
- **Why rejected:** Not production-grade. A paid API with an SLA is worth the cost for a data pipeline.

## 5. Cross-Cutting Concerns

### 5.1. Security

- **API token:** `EODHD_API_TOKEN` is read from environment variables, same pattern as `SEC_USER_AGENT_EMAIL`. Never committed to git.
- **Data sensitivity:** Ticker symbols and company names are public information. No PII.
- **No new secrets:** The existing `.env` / environment setup handles the new token.

### 5.2. Performance

- **API calls:** ~15 calls per full refresh (one per exchange). Each returns 100–5000 rows.
- **Free tier:** 20 calls/day limit. A full European refresh uses 15 calls — well within limits. Even with SEC (1 call) and debugging, headroom is comfortable.
- **Insert volume:** ~10,000–20,000 rows across all European exchanges. The `executemany` pattern already used in the SEC script handles this efficiently.

### 5.3. Observability

- **Logging:** The script prints progress per exchange (exchange name, row count, insert count). Same verbosity convention as the SEC script.
- **Error handling:** API failures (HTTP 4xx/5xx) are caught per-exchange — one exchange failing does not abort the others. Network errors retry once with backoff.
- **Idempotency check:** The `ON CONFLICT` upsert means re-running is safe. Verify by checking `dw_loaded_at` timestamps.

### 5.4. Testability

- **Unit tests:** The exchange-to-suffix mapping can be unit-tested in isolation.
- **Integration tests:** Run the script against a test database and verify that:
  - Rows are inserted with correct ticker format (suffix appended)
  - Rerunning updates `dw_loaded_at` without creating duplicates
  - `entity_identifier` (ISIN) is stored correctly
- **Mock tests:** The EODHD API call can be mocked to test error handling without network access.

### 5.5. Operational Impact

- **Deployment:** Add `EODHD_API_TOKEN` to environment. Deploy the new script file. Run once manually to seed the table, then add to cron/scheduler.
- **Rollback:** Delete the script file. European rows in `dim_entities` are harmless — `01_fetch_price_data.py` will skip them if yfinance returns no data for those tickers. To fully remove, run a DELETE query.
- **Migration:** No data migration needed. The script inserts into an existing table with no schema changes.

## 6. Trade-offs and Consequences

| Decision | Upside | Downside |
|---|---|---|
| EODHD over free CSV sources | One provider, one contract, stable API | Requires API key and free tier has 20 calls/day limit |
| `ON CONFLICT` upsert into `dim_entities` | Idempotent, no duplicates, safe to re-run | No way to detect delisted tickers (they remain in the table) |
| Static suffix mapping over dynamic resolution | Simple, testable, no external dependency | Must manually maintain the mapping if yfinance changes suffixes |
| `type=common_stock` filter | Reduces noise from ETFs and funds | May miss instruments EODHD classifies differently (e.g., some European preferred stocks) |
| Same `entity_identifier` column for CIK and ISIN | Zero schema changes | Column semantics are mixed (CIK vs ISIN) — must know the source to interpret correctly |

The mixed-semantics `entity_identifier` column is the most notable trade-off. A future reader who sees `"PLPKN0000018"` in the same column as `"0000320193"` must know that one is an ISIN and the other is a CIK. This is acceptable because:
1. The column is not used as a foreign key anywhere
2. The unique constraint is `(entity_identifier, ticker)` — the pair is always unique regardless of identifier type
3. Adding an `identifier_type` column would be a schema change that provides no functional benefit today

## 7. Implementation Plan

### Phase 1 — Script + Mapping (1 session)

1. Create `src/etl/00_populate_european_entities.py` with:
   - Exchange-to-suffix mapping dict
   - Per-exchange EODHD API call with error handling
   - ISIN → `entity_identifier`, `Code.suffix` → `ticker`, `Name` → `company_name`
   - `INSERT ... ON CONFLICT` upsert into `dim_entities`
2. Run against production DB to seed European tickers
3. Verify rows exist in `dim_entities` and tickers have correct suffixes

### Phase 2 — Verification (1 session)

4. Run `01_fetch_price_data.py --max 5` to confirm yfinance accepts the new tickers
5. Check `market_prices` table for European price rows
6. Re-run the European script to verify idempotency

### Phase 3 — Scheduling (0.5 session)

7. Add `EODHD_API_TOKEN` to environment configuration
8. Add weekly cron entry for `00_populate_european_entities.py`
9. Update README or docs with setup instructions for the new token

## 8. Self-Review Checklist

1. ✅ Doc has status, date, research/practical basis in the header
2. ✅ Non-goals explicitly stated with explanation for each
3. ✅ 4 alternatives considered and rejected with reasoning
4. ✅ Each section explains "why" before "what"
5. ✅ Trade-offs of chosen design discussed in Section 6
6. ✅ Implementation plan is phased with concrete deliverables
7. ✅ Doc avoids placeholder text (TBD, TODO, FIXME)
8. ✅ Prose narrative used for main argumentation
9. ✅ Obvious objections addressed directly