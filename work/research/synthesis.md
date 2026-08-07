# Research Synthesis: Algorithmic DCF Valuation

## Unified Summary

The research (web sources) covers practical approaches for automated DCF valuation of publicly traded stocks using yfinance data. The key finding is that automated DCF at scale is a solved problem that screening tools like Finviz, TradingView, and SimplyWallStreet handle daily. The approaches are not academically perfect but work well enough for screening purposes.

## Key Findings (Ranked by Relevance)

### 1. Discount Rate: CAPM with Sector Adjustments is the Standard
- All major screeners use CAPM-based discount rates, not Fama-French models
- Simpler is better: r_f + β * ERP, optionally adjusted for size and sector
- 10-year Treasury yield as risk-free rate; 5% ERP as standard; beta from market data
- For small/micro-cap stocks, use industry-average beta to avoid instability

### 2. Growth Rate: Analyst Consensus + Historical Blend
- Analyst estimates (from yfinance) are the preferred source for years 1-2
- Historical 3-5 year CAGR as fallback when analyst estimates are missing
- Cap growth at 25%, decay toward terminal rate over 5 years
- Terminal growth at 2-3% (long-term GDP/nominal growth proxy)

### 3. Model Selection: FCF Default, EPS Fallback, Revenue for Unprofitable
- Default to FCF for FCF-positive companies (3+ of last 5 years positive)
- Switch to EPS for profitable but FCF-negative companies
- Use revenue-based model with industry net margin assumption for unprofitable
- Normalize FCF over 5-7 years for cyclical companies

### 4. Terminal Value: Exit Multiple Over Gordon Growth
- P/E exit multiple (sector median P/E × projected net income) is more robust
- Gordon Growth Model is sensitive to terminal growth assumptions
- Cap terminal value at 80% of total DCF — flag results exceeding this

### 5. Common Pitfalls to Handle
- FCF-negative companies need model switching, not exclusion
- Cyclical companies need normalized FCF (5-year average)
- Growth rate extrapolation must be capped and decayed
- Beta instability needs industry-average fallback
- Net cash adjustment is mandatory (cash - debt)
- Terminal value dominance must be flagged

### 6. Open-Source Libraries
- No well-maintained, focused DCF library exists
- dcfpy is too simple, openbb is too complex
- Best approach: Build a ~50-100 line DCF module using yfinance directly
- Decision logic (model selection, growth rate estimation) is the real complexity

## Gaps
- No detailed comparison of how different screeners handle financial sector stocks (banks, insurance) — most just exclude them from DCF
- Limited information on how to handle companies with negative equity (book value)
- No data on backtesting results comparing DCF-based screening to actual returns

## Source-by-Source Notes
- **Web search:** Good coverage of practical approaches. Sources included blog posts, documentation from screening tools, Damodaran's valuation resources, and GitHub discussions. Missing detailed academic validation of the approaches.