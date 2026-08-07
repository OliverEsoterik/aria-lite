# Algorithmic DCF Valuation for Stock Screening

## Research Report

---

## 1. Overview

This report covers practical, implementable approaches for building a standalone Python script that computes DCF fair values for stocks automatically using yfinance data. The focus is on production-quality methods used by existing stock screeners (Finviz, TradingView, SimplyWallStreet, Portfolio123), not academic perfection.

---

## 2. Discount Rate Determination

### Recommended Approach: CAPM with Sector Adjustments

The standard used by virtually all automated screeners:

```
Discount Rate = Risk-Free Rate + Beta × Equity Risk Premium + Size Premium
```

**Risk-Free Rate:**
- Use the 10-year US Treasury yield (^TNX or ^TYX from yfinance, or a hardcoded recent value)
- Can be updated daily/weekly via a configurable constant or fetched from FRED API
- Current (2024-2025) range: ~4.0-5.0%

**Beta:**
- Use yfinance's `info['beta']` (5-year monthly by default)
- For stocks with market cap < $500M or no beta available: use industry-average beta
- Industry-average beta can be computed from all stocks in the same sector (yfinance `info['sector']`)
- Avoid using raw beta for micro-cap stocks (too volatile)

**Equity Risk Premium (ERP):**
- Damodaran's recommended ERP: 4.5-5.5% for US equities
- Use a fixed 5% as a reasonable default. This is what most screeners do.
- For emerging markets, consider adding 1-3% country risk premium

**Size Premium:**
- Large-cap (>$10B): 0%
- Mid-cap ($2B-$10B): +0.5%
- Small-cap ($300M-$2B): +1.0%
- Micro-cap (<$300M): +1.5% (or skip DCF for these)

### Simplified Alternative (What Most Screeners Actually Use)

Many screeners (Finviz, TradingView defaults) use a fixed discount rate:
- Stable/defensive: 8%
- Average: 9%
- Growth/volatile: 10%
- This is less accurate but avoids beta instability issues

### What We Don't Recommend

- **Fama-French 3-factor/5-factor:** Too complex for a screening tool. Requires loading factor data from Ken French's website, adds maintenance burden, and doesn't materially improve screening accuracy.
- **Company-specific WACC with cost of debt:** Too many moving parts for automated computation. Interest coverage ratio → synthetic rating → credit spread is fragile.

---

## 3. Growth Rate Estimation

### Three-Tier Strategy

**Tier 1: Analyst Consensus (Best)**
- yfinance provides: `nextYearEarningsGrowth`, `nextYearRevenueGrowth`
- Use these for the first 1-2 years of the projection
- For EPS model: use earnings growth estimates
- For FCF model: use revenue growth estimates (FCF growth tends to track revenue growth over time)

**Tier 2: Historical Growth (Fallback)**
- 3-year or 5-year CAGR of the relevant metric (FCF, revenue, or EPS)
- For FCF: use `freeCashflow` from yfinance
- For revenue: use `totalRevenue`
- Minimum 3 years of data required; if not available, use Tier 3

**Tier 3: Sector Median (Last Resort)**
- Compute median growth rate across all stocks in the same sector
- Also used for very new companies (< 3 years of data)

### Growth Decay Model

Instead of a single growth rate, use a decay function:
```
Year 1: g_1 = analyst estimate or historical growth
Year 2: g_2 = (g_1 + g_terminal) / 2-ish
Year 3: g_3 = blend toward terminal
Year 4: g_4 = closer to terminal
Year 5: g_5 = terminal
```

Simpler approach used by most screeners:
```
Years 1-3: g_high (from analyst estimates or historical)
Years 4-5: linear fade from g_high to g_terminal
Terminal: g_terminal (2-3%)
```

### Constraints
- **Cap growth at 25%** — even if historical shows 50%, 25% is the practical ceiling
- **Floor at 0%** — negative growth projections are valid, but don't project negative growth forever (use 0% as terminal minimum)
- **If historical growth is negative:** Use as-is (the DCF will produce a lower valuation, which is correct)

---

## 4. Model Selection: FCF vs EPS vs Revenue

### Decision Tree

```
Is FCF positive for 3+ of last 5 years?
  YES → Use FCF model (default)
  NO  → Is company profitable (net income positive for 3+ of last 5)?
          YES → Use EPS model
          NO  → Use revenue model with industry margin assumption
```

### Additional Rules

- **High-growth companies (revenue growth > 20%):** Even if FCF is negative, prefer FCF model. The negative FCF is an investment phase, not a structural problem.
- **Cyclical companies (sector in Basic Materials, Energy, Industrials):** Use normalized FCF = 5-year average FCF/revenue ratio × trailing revenue
- **Financial sector (Banks, Insurance, Financial Services):** Skip DCF entirely. FCF doesn't work for financials (they borrow money as a core business function). Flag as "DCF not applicable."

### Revenue Model Details

When using revenue-based DCF:
1. Project revenue 5 years forward using growth rate
2. Apply industry-average net margin to get projected net income
3. Apply industry-average FCF conversion ratio (FCF/net income) to get projected FCF
4. Discount and compute terminal value as usual

Industry-average net margins can be computed from yfinance for all stocks in the sector.

---

## 5. DCF Computation

### Two-Stage Model

```
Stage 1 (Years 1-5):
  FCF_t = FCF_0 × (1 + g_t)^t
  PV(FCF_t) = FCF_t / (1 + r)^t

Stage 2 (Terminal Value):
  Method A (Recommended): Exit Multiple
    TV = projected_net_income_year_5 × sector_median_PE
    PV(TV) = TV / (1 + r)^5

  Method B (Fallback): Gordon Growth Model
    TV = FCF_5 × (1 + g_terminal) / (r - g_terminal)
    PV(TV) = TV / (1 + r)^5

Enterprise Value = Sum(PV(FCF_t)) + PV(TV)

Equity Value = Enterprise Value + Cash - Total Debt

Fair Value Per Share = Equity Value / Diluted Shares Outstanding
```

### Adding Net Cash

- `net_cash = totalCash - totalDebt` (from yfinance)
- If net cash is negative (more debt than cash), subtract it
- This is non-negotiable — skipping this step produces wrong valuations

### Shares Outstanding

- Use `dilutedSharesOutstanding` from yfinance (or `sharesOutstanding` as fallback)
- For companies with significant options/warrants, diluted shares is essential

---

## 6. Common Pitfalls and Mitigations

| Pitfall | Mitigation |
|---------|-----------|
| **FCF-negative companies** | Switch to EPS or revenue model |
| **Cyclical companies** | Use normalized FCF (5-year average) |
| **Growth rate extrapolation** | Cap at 25%, decay to terminal |
| **Beta instability (small caps)** | Use industry-average beta |
| **Terminal value dominance** | Cap TV at 80% of total value; flag if exceeded |
| **Financial sector** | Skip DCF entirely |
| **Negative equity** | Still compute (DCF is forward-looking, book value is backward) |
| **Extreme fair values** | Flag if fair value > 10x current price or < 0.1x current price |
| **Cash-rich companies (Apple, MSFT)** | DCF works fine — net cash adjustment handles it |
| **Highly leveraged companies** | WACC should reflect higher risk — beta captures this partially |

---

## 7. Implementation Architecture

### Proposed Module Structure

```
dcf/
  ├── __init__.py
  ├── model.py          # DCF computation (two-stage, TV, terminal)
  ├── discount_rate.py  # CAPM, beta, industry beta, size premium
  ├── growth_rate.py    # Analyst estimates, historical CAGR, decay
  ├── model_selector.py # FCF vs EPS vs Revenue decision tree
  ├── normalization.py  # Normalized FCF, cyclical adjustment
  └── config.py         # Constants: ERP, size premiums, caps, defaults
```

### Key Constants (config.py)

```python
# Discount rate
ERP = 0.05  # Equity risk premium
RISK_FREE_RATE = 0.045  # 10-year Treasury (configurable)

# Size premiums
SIZE_PREMIUM = {
    'large': 0.0,    # > $10B
    'mid': 0.005,    # $2B-$10B
    'small': 0.01,   # $300M-$2B
    'micro': 0.015,  # < $300M
}

# Growth
MAX_GROWTH_RATE = 0.25
TERMINAL_GROWTH_RATE = 0.02
PROJECTION_YEARS = 5
FADE_START_YEAR = 3  # Start fading to terminal growth

# Model selection
FCF_POSITIVE_THRESHOLD = 3  # Years out of last 5
HIGH_GROWTH_THRESHOLD = 0.20

# Validation
MAX_TV_RATIO = 0.80  # Max terminal value as % of total
FAIR_VALUE_CAP_RATIO = 10.0  # Max fair value / current price ratio
```

### Flow

```
get_ticker(ticker) → yfinance data
    ↓
model_selector.select(data) → which model (FCF/EPS/revenue)
    ↓
discount_rate.compute(data) → discount rate
    ↓
growth_rate.compute(data) → growth rates (years 1-5)
    ↓
model.compute(data, discount_rate, growth_rates, model_type) → FV per share
    ↓
validate(fv_per_share, current_price) → flags, warnings
    ↓
return {fair_value, model_used, discount_rate, flags}
```

---

## 8. Validation and Sanity Checks

### Output Validation

Always run these checks on the output:

1. **Fair value should be positive** — If negative, the model is wrong (likely FCF-negative with no adjustment)
2. **Fair value should be within reasonable range** — Not 100x or 0.01x current price
3. **Terminal value should not dominate** — If TV > 80% of total value, the model is TV-driven (high uncertainty)
4. **Discount rate should be in range** — 6-15% is normal; outside this range suggests bad beta or data issues

### What to Log

- Model selected (FCF/EPS/revenue) and why
- Discount rate and components (beta, ERP, size premium)
- Growth rate for each year
- Terminal value as % of total value
- Flags for any edge cases hit

---

## 9. Recommendations

### For the First Implementation

1. **Start with FCF model only** — handle the 80% case first
2. **Use fixed discount rate** (9%) — simplest, most robust, defers beta complexity
3. **Use analyst estimates for growth** — yfinance has them, use them
4. **Add model switching (EPS, revenue) in V2** — get the core working first
5. **Add beta-based CAPM in V2** — once the basic framework is validated

### What to Build First

The simplest working version:

```python
def compute_dcf(fcf, revenue_growth, risk_free_rate, beta, market_cap, 
                cash, debt, shares, sector_pe):
    # 1. Discount rate
    r = 0.09  # fixed 9% for V1
    
    # 2. Growth rates
    growth_rates = [min(g, 0.25) for g in generate_growth_rates(revenue_growth)]
    
    # 3. Project FCFs
    pv_fcfs = sum(fcf * (1 + g)**i / (1 + r)**(i+1) for i, g in enumerate(growth_rates))
    
    # 4. Terminal value (exit multiple)
    net_income_y5 = ...  # project net income
    tv = net_income_y5 * sector_pe
    pv_tv = tv / (1 + r)**5
    
    # 5. Enterprise value → equity value
    ev = pv_fcfs + pv_tv
    equity = ev + cash - debt
    fv_per_share = equity / shares
    
    return fv_per_share
```

### Sources
- Damodaran, A. "The Dark Side of Valuation" — valuing young, distressed, and complex companies
- Damodaran, A. "Valuation: Approaches and Metrics" — practical valuation framework
- Finviz, TradingView, SimplyWallStreet — observations of their DCF behavior
- GitHub discussions on dcfpy, openbb, and other Python DCF implementations
- Various blog posts by quantitative analysts on automated DCF screening