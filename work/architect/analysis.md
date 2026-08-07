# Architectural Analysis: DCF Column in Ratings Output

## User Request

Add a DCF (Discounted Cash Flow) fair value column to the `make ratings` output — each stock row should show a DCF-based fair value estimate alongside the existing rating, score, and fundamental metrics. The DCF computation must be a separate Python script (no LLM involvement), and must handle the fact that different companies need different discount rates, growth assumptions, and model types.

## Codebase Context

### Project Structure
```
aria-lite/
├── Makefile                    # Targets: setup, run, statistics, ratings
├── sql/01_init_schema.sql      # Schema: dim_entities, market_prices, statistics
├── src/etl/
│   ├── 00_populate_entities.py  # SEC entity import
│   ├── 01_fetch_price_data.py   # yfinance OHLCV download
│   ├── 02_compute_statistics.py # Technical indicators
│   └── 03_generate_production_ratings.py  # ← TARGET: ratings engine
├── data/tickers_to_trade.json   # Master ticker list
└── scripts/run_etl.sh           # ETL orchestration
```

### Key File: `03_generate_production_ratings.py`

This is the file that produces the ratings table. Key flow:

1. **`get_today_best_buys(engine)`** — main function
   - Fetches 1500 candidates by dollar volume from `statistics` table
   - Computes momentum scores from `market_prices` (via `calculate_momentum_metrics`)
   - Fetches fundamental data via `get_extensive_fundamentals(ticker)` — calls `yf.Ticker(ticker).info`
   - Normalizes into z-scores, computes `final_score`
   - Applies `RiskGate` and `assign_production_rating()`
   - Returns `top_picks` and `portfolio_status` DataFrames

2. **`get_extensive_fundamentals(ticker)`** — fetches yfinance info dict
   - Returns: peg, fcf_yield, fwd_pe, trl_eps, op_margin, profit_margin, rev_growth, roe, debt_to_equity, current_ratio, eps_rev
   - **Already has access to the full yfinance info dict** — all the data needed for DCF is available here

3. **Display columns** (printed at end):
   ```
   ticker, rating, final_score, eps_rev, mom_score, peg, fwd_pe, rev_growth, 
   op_margin, near_high, current_ratio, debt_to_equity, roe, profit_margin, fcf_yield
   ```

### What yfinance info provides (relevant to DCF)
- `freeCashflow`, `operatingCashflow`, `capitalExpenditure` — FCF computation
- `totalRevenue`, `revenueGrowth` — growth estimation
- `forwardEps`, `trailingEps`, `earningsGrowth` — EPS-based valuation
- `beta` — risk measure for discount rate (CAPM)
- `debtToEquity`, `totalDebt`, `totalCash` — net debt adjustment
- `marketCap`, `enterpriseValue` — comparison
- `sector`, `industry` — for sector-based adjustments
- `sharesOutstanding` — per-share calculations
- `numberOfAnalystOpinions` — consensus quality signal

### Makefile Targets
```
ratings: start-db
    cd src/etl && python3 03_generate_production_ratings.py
```

## Constraints

1. **No LLM involvement** in the DCF computation — purely algorithmic
2. **Must be a separate Python script** — not inline in the ratings script
3. **Must handle diverse company profiles** — cyclical vs stable, FCF-positive vs negative, high-growth vs mature
4. **Must output a column that integrates into the existing ratings table**
5. **Must not duplicate yfinance API calls** — data already fetched in `get_extensive_fundamentals()`
6. **Performance matters** — the ratings script processes ~800 companies in batches; DCF should not be a bottleneck
7. **No database schema changes** — DCF value should be computed on-the-fly or stored in a simple way

## Open Questions

1. How to choose between FCF-based DCF and EPS-based DCF algorithmically? (Negative FCF → EPS model)
2. How to determine discount rate per company? (CAPM with beta, but what risk-free rate and ERP?)
3. How to estimate growth rates without manual input? Options:
   - Historical revenue growth trend
   - Analyst consensus (from yfinance earnings trend)
   - Sector averages
   - A blend of the above
4. How to handle terminal growth rate? (Fixed 3% for all? Sector-adjusted?)
5. Should the DCF be a single value or a range (sensitivity analysis)?
6. Should the DCF value be persisted in the database or computed on-the-fly each run?
7. How to handle extreme outliers (e.g., 85%+ overvaluation for TER)?
8. What to display when DCF cannot be computed (negative FCF, no earnings, missing data)?