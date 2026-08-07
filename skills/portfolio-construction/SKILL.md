---
name: portfolio-construction
description: >
  Build a diversified portfolio from a list of tickers. Runs the existing
  alpha-picks rating system against your picks, performs deep per-ticker
  research (moat, sector, macro exposure, competitive risk), analyzes
  cross-stock correlations and concentration, and produces a recommended
  allocation with % weights, rationale, and risk flags.
---

# Portfolio Construction

## Overview

This skill takes a list of stock tickers and produces a complete portfolio
allocation. It follows a 4-phase pipeline:

1. **Score** — Run each ticker through the alpha-picks factor model
   (momentum, quality, analyst revisions, valuation) to get a risk-adjusted
   score and rating.
2. **Research** — For each ticker, fetch financial data and produce a
   qualitative assessment (moat, sector, macro exposure, key risks).
3. **Analyze** — Build correlation matrix, check sector concentration,
   identify overlapping risk factors, compute portfolio-level metrics.
4. **Allocate** — Score-weighted allocation with diversification constraints;
   produce final weight table with rationale.

---

## How to use

Invoke with your ticker list:

```
/skill:portfolio-construction SNDK, LITE, MU, TER, VICR, WDC, STX, AGX, CLS, STRL, CRDO
```

Or via the orchestrator:

```
/skill:orchestrator build a portfolio from these tickers: SNDK, LITE, MU, TER, VICR, WDC, STX, AGX, CLS, STRL, CRDO
```

---

## Pipeline

### Phase 1: Score

For each ticker, fetch fundamental data via yfinance and compute the
alpha-picks factor scores:

- **Risk-adjusted momentum** (12-1 month persistence, vol-adjusted)
- **Momentum quality** (consistency of positive vs negative days)
- **Acceleration** (3m vs 12m momentum delta)
- **Quality composite** (revenue growth + operating margins)
- **Analyst revisions** (EPS estimate trend)
- **Technical state** (RSI + volume)

Pass through the **Risk Gate** (price > $10, op margin > 5%, current ratio >
0.8, ROE > -10%, forward P/E exists).

Assign a rating: STRONG BUY / BUY / HOLD / SELL.

Output: `work/phase1_scores.csv` with ticker, score, rating, and all
sub-components.

### Phase 2: Research

For each ticker that passes the Risk Gate, produce a research brief covering:

- **Sector & Industry** — GICS classification
- **Business Model** — What does the company do? Who are its customers?
- **Competitive Moat** — Pricing power, switching costs, network effects, IP
- **Macro Exposure** — Interest rate sensitivity, commodity exposure,
  regulatory risk, FX risk
- **Key Risks** — Concentration risk, technology disruption, cyclicality
- **Growth Drivers** — Near-term catalysts, secular tailwinds

This phase is parallelized per ticker via sub-agents.

Output: `work/research/<ticker>.md` for each ticker.

### Phase 3: Analyze

Compute portfolio-level statistics:

- **Correlation matrix** — price return correlations over 1y and 3y windows
- **Sector concentration** — % allocation per sector, Herfindahl index
- **Factor overlap** — How many stocks share the same macro drivers
  (semiconductor cycle, rates, AI capex, etc.)
- **Portfolio risk metrics** — Weighted-average beta, volatility, drawdown
  risk (from historical simulation)
- **Concentration risk** — Top-3 holdings weight, single-stock max

Output: `work/phase3_analysis.md`

### Phase 4: Allocate

Generate the final allocation:

1. **Base weight** = proportional to `final_score` from Phase 1
2. **Apply constraints**:
   - Single stock max: 15% (hard cap)
   - Single sector max: 30% (soft cap, warn if exceeded)
   - Minimum position: 2% (or exclude)
   - Round to 0.5% increments
3. **Adjust for correlation** — if two stocks have >0.8 correlation,
   cap combined weight at 20%
4. **Normalize** to 100%

Output: `work/phase4_allocation.md` with a table:

| Ticker | Rating | Score | Weight % | Sector | Rationale | Risk Flags |
|--------|--------|-------|----------|--------|-----------|------------|

Plus a one-paragraph portfolio summary covering diversification, risk
profile, and macro stance.

---

## Tools

### `tools/score_tickers.py`

Fetches yfinance data for the given tickers and computes alpha-picks factor
scores. Outputs CSV to stdout.

Usage:
```bash
python3 skills/portfolio-construction/tools/score_tickers.py SNDK LITE MU TER VICR WDC STX AGX CLS STRL CRDO
```

### `tools/research_ticker.py`

Fetches comprehensive financial data for a single ticker and prints a
structured research brief as markdown.

Usage:
```bash
python3 skills/portfolio-construction/tools/research_ticker.py SNDK
```

### `tools/portfolio_optimize.py`

Reads the scores CSV and research files, computes correlations from yfinance
price history, applies allocation constraints, and outputs the final
portfolio table as markdown.

Usage:
```bash
python3 skills/portfolio-construction/tools/portfolio_optimize.py work/phase1_scores.csv
```

---

## Dependencies

- **Python 3** with `yfinance`, `numpy`, `pandas` (available in the Nix env)
- **Database** (optional) — if the alpha-picks DB is available, the tools
  will use it for price history; otherwise they fall back to yfinance