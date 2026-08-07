# Solution Research: DCF Column in Ratings Output

## Architectural Options

### Option A: Standalone DCF Script + Integration Hook

**Description:**
Create a `dcf/` module (separate from the ETL pipeline) with a `compute_dcf(ticker, yfinance_info_dict) → dict` function. The ratings script imports and calls it for each row, adding the result as a column. The DCF module is independently testable and callable.

**Fit with codebase:** Tight — the ratings script already loops over tickers and has the yfinance info dict. A single import + function call per row adds minimal complexity.

**Pros:**
- Single responsibility: DCF logic is isolated, testable, reusable
- Ratings script only needs 3-4 lines added to the `display_cols` and output section
- Can be run standalone: `python3 -m dcf.runner AAPL`
- No database changes needed
- Follows the existing pattern (each ETL step is a separate script)

**Cons:**
- Adds ~5-10 seconds to the ratings run (DCF math is fast, but yfinance data is already fetched)
- Must handle missing data gracefully (stock not in yfinance, missing fields)
- The DCF function needs the full yfinance info dict, which the ratings script already has

### Option B: Pure Postgres SQL Function

**Description:**
Write a PL/pgSQL function or a PostgreSQL extension that computes DCF values directly in the database using data stored in `market_prices` and `statistics`.

**Fit with codebase:** Poor — the fundamental data needed for DCF (FCF, debt, cash, beta, etc.) is not stored in the database. It's fetched fresh from yfinance each run.

**Cons:**
- Would need to store fundamental data in the DB first → massive schema changes
- yfinance data is ephemeral; storing it introduces stale data problems
- SQL is terrible for the conditional logic needed (model selection, growth decay)
- **Rejected**

### Option C: Fully Separate Script, CSV Merge

**Description:**
A standalone script that reads the tickers from the ratings output CSV, computes DCF values independently (fetching its own yfinance data), and merges the column back.

**Fit with codebase:** Looser — avoids modifying the ratings script at all, but duplicates yfinance API calls.

**Pros:**
- Zero risk of breaking the ratings engine
- Fully independent, can be run on a different schedule
- Easy to test in isolation

**Cons:**
- **Duplicates yfinance API calls** — doubles the API load (yfinance is rate-limited)
- Requires a merge step (file I/O, temp files)
- The ratings script already has the data in memory; throwing it away and re-fetching is wasteful
- Slower overall

### Option D: DCF as a Pre-computed Table (Separate ETL Step)

**Description:**
A new ETL script `04_compute_dcf.py` that runs after ratings, computes DCF for all tracked tickers, stores results in a `dcf_values` table, and the ratings output reads from it.

**Fit with codebase:** Follows the existing ETL pattern (numbered steps). But adds DB complexity for a single column.

**Pros:**
- Follows the ETL pipeline pattern
- DCF values are persisted and can be queried, charted, or used in other reports
- DCF computation is decoupled from ratings

**Cons:**
- Requires a new DB table + migration
- DCF values depend on config (discount rate, growth assumptions) that can change — leads to stale data questions
- Adds complexity to the simple output format
- **Over-engineered for a single column**

---

## Detailed Design: Option A (Recommended)

### Module Structure

```
src/dcf/
├── __init__.py
├── config.py              # Constants: ERP, risk-free rate, caps, thresholds
├── discount_rate.py       # CAPM computation + size premium
├── growth.py              # Growth rate estimation + decay model
├── model_selector.py      # FCF vs EPS vs revenue decision tree
├── compute.py             # Core DCF math (two-stage model)
├── runner.py              # Standalone CLI: dcf AAPL MSFT GOOG
└── validators.py          # Sanity checks, flags, edge case handling
```

### Integration Point

In `03_generate_production_ratings.py`, the `get_extensive_fundamentals()` function already returns a dict with all the yfinance data. The integration is:

```python
from dcf.compute import compute_dcf

# Inside get_extensive_fundamentals, after fetching info:
result = get_extensive_fundamentals(ticker)
# Add DCF computation
dcf_result = compute_dcf(info)  # uses the full yfinance info dict
result['dcf_fair_value'] = dcf_result['fair_value']
result['dcf_model'] = dcf_result['model_used']
result['dcf_discount_rate'] = dcf_result['discount_rate']
```

### Algorithmic Decision Tree

```
For each stock:
1. Get yfinance info dict
2. Select model:
   - FCF > 0 AND FCF margin > 5% → FCF model
   - EPS > 0 AND profitable last 3 years → EPS model  
   - Revenue > 0 → Revenue model (apply sector margin)
   - None of the above → DCF = N/A
3. Compute discount rate:
   - Beta available? → CAPM: r = RF + β × ERP + size premium
   - No beta? → Sector average discount rate
4. Estimate growth:
   - Use analyst consensus (forwardEps/forwardRevenue growth)
   - Cap at 25%, fade to 3% terminal over 5 years
5. Compute DCF (two-stage: 5 years + terminal)
6. Adjust for net debt → fair value per share
7. Validate: positive, within 10x price, TV < 80% of total
```

### Implementation Plan

1. Create `src/dcf/` module with config, discount_rate, growth, model_selector, compute
2. Add DCF computation to `get_extensive_fundamentals()` in the ratings script
3. Add `dcf_fair_value` to the display columns
4. Create standalone runner `runner.py` for CLI usage
5. Handle edge cases: missing data, financial sector, negative FCF, extreme values