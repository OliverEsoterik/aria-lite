---
name: top-picks-portfolio
description: >
  Build a concentrated, high-conviction portfolio of ~10 stocks from the
  alpha-picks rating system. Filters to STRONG BUY only, excludes pharma
  and miners, enforces sector diversification, and produces a risk-aware
  allocation designed to outperform the S&P 500.
---

# Top Picks Portfolio

## Overview

This skill runs the full alpha-picks production rating pipeline against the
entire ticker universe, then filters aggressively to produce a high-conviction
portfolio of ~10 stocks.

### Philosophy

- **STRONG BUY only** — the alpha-picks factor model already does the
  filtering. We only take the highest conviction ratings.
- **No pharma, no miners** — biotech/pharma is binary (trial outcomes, FDA
  decisions) and miners are commodity price takers. Both add uncompensated
  tail risk.
- **Sector-capped** — no single sector dominates. The portfolio must be
  diversified enough that a single sector drawdown doesn't crush the thesis.
- **Score-weighted** — allocation proportional to the `final_score` from the
  factor model, with constraints.
- **Outperform S&P** — the factor model is designed to beat the market. This
  skill selects the best of what passes the model.

---

## Pipeline

### Phase 1: Run the Rating Pipeline

Runs `get_today_best_buys()` from `03_generate_production_ratings.py` to
score the entire universe. This produces a dataframe with `final_score`,
`rating`, and all sub-components for ~500 top candidates.

### Phase 2: Filter

Apply filters in order:

1. **Rating** — must contain "STRONG BUY"
2. **Sector exclusion** — remove tickers in:
   - Healthcare / Pharmaceuticals / Biotech / Medical
   - Basic Materials / Metals & Mining / Minerals
   - Energy (if it's a miner/extractor, not a service)
3. **Risk gate** — already applied by the pipeline, but double-check
4. **Score** — take top 20 by `final_score` for further analysis

### Phase 3: Enrich

For each candidate, fetch sector/industry from yfinance (since the rating
output doesn't include sector). Also fetch a short business description.

### Phase 4: Diversify

From the top 20 candidates, select ~10 with these constraints:

- **Sector max:** 30% of portfolio
- **No duplicate subsectors** — e.g. don't take 3 semiconductor companies
  if they'd crowd the same cycle exposure
- **Correlation check:** skip second pick in same subsector if score is
  significantly lower
- **Minimum score threshold:** `final_score > 0.3`

### Phase 5: Allocate

- **Base weight:** proportional to `final_score` among selected tickers
- **Single stock max:** 15%
- **Single stock min:** 5% (if below, exclude and reallocate)
- **Round:** to 0.5% increments
- **Normalize:** to 100%

### Phase 6: Output

Portfolio table with:

| Ticker | Rating | Score | Weight | Sector | Industry | Risk Flags | Rationale |
|--------|--------|-------|--------|--------|----------|------------|-----------|

Plus:
- Portfolio summary (sector breakdown, concentration, weighted score)
- Comparison to S&P sectors (where is the portfolio overweight/underweight?)
- Risk notes (beta, volatility, concentration risk)

---

## Tools

### `tools/build_top_picks_portfolio.py`

Standalone script that runs the full pipeline. Connects to the alpha-picks
DB, runs the rating pipeline, applies filters, enriches with yfinance, and
outputs the final portfolio as markdown.

Usage:
```bash
nix develop -c python3 skills/top-picks-portfolio/tools/build_top_picks_portfolio.py
```

### `tools/score_candidates.py`

Reusable module that runs the factor model against a specific ticker list
(used when you don't want the full universe scan). Same logic as
`skills/portfolio-construction/tools/score_tickers.py`.

---

## Dependencies

- **alpha-picks DB** — must be running with populated `statistics` table
  (run `make run` or `make setup` first)
- **Python 3** with `yfinance`, `numpy`, `pandas`, `sqlalchemy` (available
  in the Nix environment)
- **Nix environment** — `nix develop` to get all dependencies