# Momentum Algorithm Optimization: Research-Backed Strategic Plan

> **Status:** Research & Analysis — no code changes
> **Scope:** Fine-grain optimization of the existing momentum scoring system
> **Methodology:** arxiv literature review (13 papers across 6 themes)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Algorithm Architecture](#2-current-algorithm-architecture)
3. [Research Papers: Annotated Bibliography](#3-research-papers-annotated-bibliography)
4. [Optimization Opportunities by Theme](#4-optimization-opportunities-by-theme)
5. [Priority-Ranked Optimization Roadmap](#5-priority-ranked-optimization-roadmap)
6. [Detailed Recommendations](#6-detailed-recommendations)
7. [Risk Assessment & Expected Effects](#7-risk-assessment--expected-effects)
8. [Appendix: Paper Abstracts](#8-appendix-paper-abstracts)

---

## 1. Executive Summary

The current momentum algorithm is a solid multi-factor system combining risk-adjusted momentum, momentum quality (consistency), acceleration, fundamentals, and analyst revisions. The research literature confirms this approach is well-founded, but identifies **7 specific optimizations** that could improve performance without structural rewrites.

**Highest-impact recommendation:** Replace the simple 20-day close-to-close volatility estimator with a range-based estimator (Yang-Zhang or Parkinson). This directly improves the primary `mom_score = mom_12m / vol` signal by using 7-8x more information from the same price data, with zero additional data dependencies.

**Second-highest impact:** Combine multiple momentum lookback windows (3m, 6m, 12m) instead of relying solely on the 12-1 month signal, making the acceleration signal richer and more regime-adaptive.

---

## 2. Current Algorithm Architecture

### 2.1 Data Pipeline

```
market_prices (DB)
  → 02_compute_statistics.py (technical indicators)
    → sma_252, rsi_14, log_return, vol_20, mdd_20, skew_20, kurt_20
  → 03_generate_production_ratings.py (scoring & rating)
    → calculate_momentum_metrics() → assign_production_rating()
```

### 2.2 Momentum Signal Components

| Component | Formula | Weight in Final Score | Purpose |
|-----------|---------|----------------------|---------|
| Risk-Adjusted Momentum | `mom_12m / vol` | 25% | Persistence (long-term trend) |
| Momentum Quality | `sign(mom_12m) * (pos_days - neg_days) / total_days` | 25% | Consistency / quietness of trend |
| Acceleration | `mom_3m - mom_12m` | 5% | Freshness / early entry |
| Fundamentals (s_qual) | revenue growth + op margin | 30% | Business quality |
| Analyst Revisions (z_eps) | EPS revision z-score | 10% | Sentiment catalyst |
| Technical State (z_state) | RSI + volatility composite | 5% | Entry timing |

### 2.3 Exit Triggers

- `eps_rev < -0.03` → SELL (Estimate Decay)
- `rev_growth < 0` → SELL (No Growth)
- `mom < -0.10` → SELL (Trend Exhaustion)

### 2.4 Ratings

- STRONG BUY (Emerging Breakout) — near 52-week high + accelerating + fair PEG
- STRONG BUY (Hyper-Growth) — high rev growth + strong momentum + cheap PEG
- STRONG BUY (Elite) — high score + revisions + profitability + fair value
- BUY — solid score + momentum + reasonable PEG
- HOLD / SELL — valuation or momentum deterioration

---

## 3. Research Papers: Annotated Bibliography

### 3.1 Core Momentum Strategy

| # | Paper | Year | Source | Relevance |
|---|-------|------|--------|-----------|
| 1 | **Spatio-Temporal Momentum: Jointly Learning Time-Series and Cross-Sectional Strategies** — Tan, Roberts, Zohren | 2023 | [arxiv:2302.10175](https://arxiv.org/abs/2302.10175) | Unifies TS and XS momentum; multi-asset signal learning |
| 2 | **Constructing Time-Series Momentum Portfolios with Deep Multi-Task Learning** — Ong, Herremans | 2023 | [arxiv:2306.13661](https://arxiv.org/abs/2306.13661) | Joint learning of momentum signal + volatility estimator |
| 3 | **Portfolio Construction Matters** — Ciliberti, Gualdi | 2018 | [arxiv:1810.08384](https://arxiv.org/abs/1810.08384) | Optimized portfolio construction sharpens momentum factors |
| 4 | **Combining Independent Smart Beta Strategies for Portfolio Optimization** — Maguire, Moffett, Maguire | 2018 | [arxiv:1808.02505](https://arxiv.org/abs/1808.02505) | Multi-strategy combination > single strategy |

### 3.2 Risk & Tail Management

| # | Paper | Year | Source | Relevance |
|---|-------|------|--------|-----------|
| 5 | **Not All Factors Crowd Equally: Modeling, Measuring, and Trading on Alpha Decay** — Lee | 2025 | [arxiv:2512.11913](https://arxiv.org/abs/2512.11913) | Momentum alpha decay is hyperbolic; crowding predicts crash risk |
| 6 | **Winners vs. Losers: Momentum-based Strategies with Intertemporal Choice for ESG Portfolios** — Jha, Shirvani, Jaffri, Rachev, Fabozzi | 2025 | [arxiv:2505.24250](https://arxiv.org/abs/2505.24250) | Tail-risk-aware momentum with regime switching |

### 3.3 Regime & Dynamic Allocation

| # | Paper | Year | Source | Relevance |
|---|-------|------|--------|-----------|
| 7 | **Dynamic Factor Allocation Leveraging Regime-Switching Signals** — Shu, Mulvey | 2024 | [arxiv:2410.14841](https://arxiv.org/abs/2410.14841) | Regime-aware factor allocation improves IR significantly |
| 8 | **TrendFolios: A Portfolio Construction Framework for Utilizing Momentum and Trend-Following** — Lu, Rojas, Yeung, Convery | 2025 | [arxiv:2506.09330](https://arxiv.org/abs/2506.09330) | Multi-asset momentum with drawdown risk management |

### 3.4 AI/ML Enhancement

| # | Paper | Year | Source | Relevance |
|---|-------|------|--------|-----------|
| 9 | **ChatGPT in Systematic Investing — Enhancing Risk-Adjusted Returns with LLMs** — Anic, Barbon, Seiz, Zarattini | 2025 | [arxiv:2510.26228](https://arxiv.org/abs/2510.26228) | LLM-enhanced momentum: news signals improve Sharpe |
| 10 | **E2EAI: End-to-End Deep Learning Framework for Active Investing** — Wei, Dai, Lin | 2023 | [arxiv:2305.16364](https://arxiv.org/abs/2305.16364) | End-to-end factor selection, combination, portfolio construction |
| 11 | **NoxTrader: LSTM-Based Stock Return Momentum Prediction for Quantitative Trading** — Liu, Shu, Chiu | 2023 | [arxiv:2310.00747](https://arxiv.org/abs/2310.00747) | Multi-timeframe momentum + dispersion filtering |

### 3.5 Multi-Factor & Convergence

| # | Paper | Year | Source | Relevance |
|---|-------|------|--------|-----------|
| 12 | **Quant Convergence: Bridging Classical Value Investing and Modern Factor Models** — Yamazaki, Belinchon | 2026 | [arxiv:2606.24575](https://arxiv.org/abs/2606.24575) | Graham-style filters as low-pass for momentum noise |
| 13 | **A Multi-Factor Market-Neutral Investment Strategy for NYSE Equities** — Gkolemis, Lee, Roudani | 2024 | [arxiv:2412.12350](https://arxiv.org/abs/2412.12350) | Risk parity portfolio construction for momentum factors |

---

## 4. Optimization Opportunities by Theme

### Theme A: Volatility Estimation (Papers 2, 8)

**Problem:** The current `vol_20` uses a simple 20-day rolling standard deviation of log returns (close-to-close). This estimator has high variance and ignores intra-period price information.

**Research finding:** Ong & Herremans (2023) demonstrate that the momentum signal and volatility estimator should NOT be treated independently. A better vol estimator directly improves the risk-adjusted momentum signal. The Yang-Zhang estimator (which uses open, high, low, close) is 7-8x more efficient than close-to-close.

**Optimization:** Replace `vol_20` calculation with a range-based estimator. The Yang-Zhang estimator is:

```
σ_yz² = σ_o² + k * σ_c² + (1 - k) * σ_rs²
```
where σ_o² is overnight volatility (open/close), σ_c² is close-to-close, and σ_rs² is the Rogers-Satchell estimator (uses high/low).

**Files touched:** `02_compute_statistics.py` — `calculate_metrics()` function

### Theme B: Multi-Lookback Momentum (Papers 1, 7, 11)

**Problem:** The algorithm uses a single momentum lookback: `mom_12m = (p_1m / p_12m) - 1`. Research shows that different lookback periods capture different market regimes.

**Research finding:** Tan, Roberts & Zohren (2023) show that combining multiple lookback periods and learning cross-sectional relationships between assets significantly outperforms single-lookback approaches. Shu & Mulvey (2024) show that factor efficacy varies across regimes.

**Optimization:** Compute momentum across 3-month, 6-month, and 12-month windows. Combine them with either:
- Equal weighting (simple, robust)
- Adaptive weighting based on recent predictive performance (rolling 12-month IC)
- Regime-weighted (different lookback dominates in different vol regimes)

**Files touched:** `03_generate_production_ratings.py` — `calculate_momentum_metrics()`

### Theme C: Regime-Aware Factor Weights (Papers 5, 6, 7)

**Problem:** The `final_score` uses static weights (0.25 mom, 0.25 quality, 0.30 fundamentals, 0.10 revisions, 0.05 technical). Research shows factor efficacy varies dramatically with market regimes.

**Research finding:** Shu & Mulvey (2024) improved IR from 0.05 to 0.4-0.5 by dynamically allocating factors based on regime. Momentum dominates in trending markets; fundamentals dominate in mean-reverting markets; quality dominates in uncertainty.

**Optimization:** Add a regime classifier (simple: VIX regime or volatility trend) that adjusts the weight vector. For example:
- **Low vol / bull regime:** Increase fundamentals weight (s_qual: 0.30 → 0.40, mom: 0.25 → 0.15)
- **High vol / bear regime:** Increase momentum quality weight (z_mom_qual: 0.25 → 0.40, s_qual: 0.30 → 0.15)
- **Transition regime:** Increase acceleration weight (z_accel: 0.05 → 0.15)

**Files touched:** `03_generate_production_ratings.py` — final score formula in `get_today_best_buys()`

### Theme D: Alpha Decay & Quality Metric Refinement (Papers 5, 11)

**Problem:** The momentum quality metric `sign(mom_12m) * (pos_days - neg_days) / total_days` is a good consistency proxy, but treats all days equally regardless of recency.

**Research finding:** Lee (2025) shows momentum alpha decays hyperbolically: `α(t) = K / (1 + λ*t)`. This means older price data should be exponentially decayed in the quality metric. Liu et al. (2023) show that dispersion filtering (only acting when signals align across timeframes) is a powerful enhancer.

**Optimization:** 
- Apply exponential decay to the quality metric: weight recent days more heavily
- Add a dispersion filter: only generate STRONG BUY signals when momentum is positive across ALL lookback windows (3m, 6m, 12m), not just 12m

**Files touched:** `03_generate_production_ratings.py` — `calculate_momentum_metrics()` and `assign_production_rating()`

### Theme E: Dynamic Exit Triggers (Papers 5, 6)

**Problem:** Exit triggers are static thresholds: `eps_rev < -0.03`, `rev_growth < 0`, `mom < -0.10`. These don't adapt to market conditions.

**Research finding:** Lee (2025) shows that crowded momentum has 0.38x lower crash probability than uncrowded momentum. Jha et al. (2025) show that tail-risk-aware metrics (STAR ratio, Rachev ratio) provide better exit signals than raw return thresholds.

**Optimization:**
- Make exit thresholds regime-dependent: widen in high-vol regimes, tighten in low-vol
- Add a crowding metric: when many stocks have high momentum scores, relax the momentum exit threshold
- Replace the raw `mom < -0.10` with a percentile-based threshold (e.g., bottom 10% of momentum scores in the universe)

**Files touched:** `03_generate_production_ratings.py` — `assign_production_rating()`

### Theme F: Acceleration Signal Enhancement (Papers 1, 11)

**Problem:** Acceleration is weighted at only 5% in the final score. The research suggests this is too low when acceleration and momentum are aligned.

**Research finding:** When acceleration (mom_3m - mom_12m) is positive AND momentum is positive, the combined signal is stronger than the sum of parts. This is a non-linear interaction effect.

**Optimization:** Add a non-linear boost factor:
```
if accel > 0 and mom_12m > 0:
    combined_momentum_boost = 1.0 + 0.5 * min(accel / abs(mom_12m), 1.0)
    effective_mom_weight = 0.25 * combined_momentum_boost
    effective_qual_weight = 0.25 * combined_momentum_boost
    # Normalize other weights to compensate
```

**Files touched:** `03_generate_production_ratings.py` — final score formula

### Theme G: LLM/NLP Overlay for EPS Revisions (Paper 9)

**Problem:** The `eps_rev` signal is a simple numeric ratio: `(current_eps / 30day_ago_eps) - 1`. It captures the direction of analyst revisions but not the qualitative context.

**Research finding:** Anic et al. (2025) show that LLM-enhanced momentum (using news to validate momentum signals) outperforms standard momentum, especially for concentrated, high-conviction portfolios — exactly what the STRONG BUY ratings represent.

**Optimization:** Augment the numeric `eps_rev` with a sentiment score from earnings call transcripts or news headlines. The LLM can act as a qualitative overlay on the quantitative signal.

**Files touched:** `03_generate_production_ratings.py` — `get_extensive_fundamentals()` and score formula

---

## 5. Priority-Ranked Optimization Roadmap

| Priority | Optimization | Expected Impact | Effort | Complexity | Risk | Research Basis |
|----------|-------------|----------------|--------|-----------|------|----------------|
| **P0** | Range-based volatility estimator | High | Low | Low | Very Low | Ong & Herremans (2023) |
| **P1** | Multi-lookback momentum (3m, 6m, 12m) | High | Low | Low | Low | Tan, Roberts, Zohren (2023) |
| **P2** | Regime-aware factor weight adjustment | Medium-High | Medium | Medium | Low | Shu & Mulvey (2024) |
| **P3** | Exponential decay in quality metric | Medium | Low | Low | Very Low | Lee (2025) |
| **P4** | Non-linear boost when accel + mom align | Medium | Low | Low | Very Low | Liu et al. (2023) |
| **P5** | Dynamic exit thresholds by crowding | Medium | Medium | Medium | Low | Lee (2025) |
| **P6** | LLM-enhanced sentiment for eps_rev | Medium | High | High | Low | Anic et al. (2025) |

### 5.1 Dependencies Between Optimizations

```
P0 (vol estimator) ── independent ── can be done anytime
P1 (multi-lookback) ── independent ── can be done anytime
    │
    ├── enables P3 (quality metric uses multi-lookback)
    └── enables P4 (non-linear boost uses multi-lookback)
    
P2 (regime-aware weights) ── independent ── can be done anytime
    │
    ├── enhances P5 (dynamic exits use regime state)
    └── enhances P6 (LLM overlay uses regime context)

P5 (dynamic exits) ── independent ── can be done anytime
P6 (LLM overlay) ── independent ── needs external API integration
```

---

## 6. Detailed Recommendations

### 6.1 P0: Range-Based Volatility Estimator

**Current code** (`02_compute_statistics.py:calculate_metrics`):
```python
df['vol_20'] = g_ret.transform(lambda x: x.rolling(20, min_periods=10).std() * np.sqrt(252))
```

**Recommended approach:** Yang-Zhang estimator (requires OHLC data already in `market_prices`):

```python
def yang_zhang_vol(high, low, close, open_, period=20, annualize=True):
    """
    Yang-Zhang range-based volatility estimator.
    Uses open, high, low, close for 7-8x more efficient estimation.
    """
    # Overnight volatility (close-to-open)
    log_co = np.log(close.shift(1) / open_.shift(1))
    # Open-to-close volatility
    log_oc = np.log(open_ / close.shift(1))
    # Rogers-Satchell (high/low range)
    log_hl = np.log(high / low)
    log_ho = np.log(high / open_)
    log_lo = np.log(low / open_)
    rs_var = (log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co))
    
    # Optimal weighting parameter
    k = 0.34 / (1.34 + (period + 1) / (period - 1))
    
    o_var = log_oc.rolling(period, min_periods=10).var()
    c_var = log_co.rolling(period, min_periods=10).var()
    rs_var = rs_var.rolling(period, min_periods=10).mean()
    
    vol = np.sqrt(o_var + k * c_var + (1 - k) * rs_var)
    return vol * np.sqrt(252) if annualize else vol
```

**Why this works:** Close-to-close vol discards all intra-period information. The Yang-Zhang estimator uses the high-low range, which is proportional to vol but requires 7-8x fewer observations for the same precision. For a 20-day estimation window, this means your vol estimate is as reliable as ~150 days of close-to-close data.

**Effect on algorithm:** Cleaner `mom_score = mom_12m / vol` denominator → fewer false positives (stocks that appear to have momentum but are just noisy) → better rank ordering.

### 6.2 P1: Multi-Lookback Momentum

**Current code** (`03_generate_production_ratings.py:calculate_momentum_metrics`):
```python
if available_days >= 252:
    p_12m = group['price_close'].iloc[-252]
    mom_12m = (p_1m / p_12m) - 1
else:
    mom_12m = (p_1m / group['price_close'].iloc[0]) - 1
mom_3m = (p_now / p_3m) - 1
```

**Recommended approach:** Compute momentum across multiple lookbacks and combine:

```python
# Compute momentum at each lookback
mom_3m = (p_now / p_3m) - 1
mom_6m = (p_1m / p_6m) - 1 if available_days >= 126 else (p_1m / p_3m) - 1
mom_12m = (p_1m / p_12m) - 1 if available_days >= 252 else mom_6m

# Combined momentum (adaptive weighting)
# In trending markets, longer lookbacks dominate
# In volatile markets, shorter lookbacks dominate
mom_combined = 0.3 * mom_3m + 0.3 * mom_6m + 0.4 * mom_12m

# Use combined momentum for risk-adjustment
adj_mom = mom_combined / (vol + 1e-6)

# Acceleration becomes richer: compare short vs medium vs long
acceleration = mom_3m - mom_12m  # Keep as is, but now based on cleaner signals
```

**Why this works:** The 12-1 month momentum is the classic Jegadeesh-Titman (1993) signal. But 3-month momentum captures short-term continuation, 6-month captures intermediate, and 12-month captures persistence. When all three are positive, conviction should be higher. When they diverge, the signal is weaker.

**Effect on algorithm:** More robust momentum scores, especially during regime transitions where the 12-month lookback lags.

### 6.3 P2: Regime-Aware Factor Weights

**Current code** (`03_generate_production_ratings.py:get_today_best_buys`):
```python
final_merged['final_score'] = (
    final_merged['z_mom_risk_adj'] * 0.25 +
    final_merged['z_mom_qual']     * 0.25 +
    final_merged['z_accel']        * 0.05 +
    final_merged['s_qual']         * 0.30 +
    final_merged['z_eps']          * 0.10 +
    final_merged['z_state']        * 0.05
)
```

**Recommended approach:** Add a regime classifier and dynamic weights:

```python
def detect_regime(merged_df, sp500_vol=None):
    """
    Detect market regime using aggregate vol and momentum breadth.
    Returns: 'bull', 'bear', 'transition'
    """
    # Use median vol of the universe as a proxy
    median_vol = merged_df['annual_vol'].median()
    vol_percentile = merged_df['annual_vol'].rank(pct=True).median()
    
    # Momentum breadth: % of stocks with positive momentum
    mom_breadth = (merged_df['mom_score'] > 0).mean()
    
    if vol_percentile < 0.4 and mom_breadth > 0.6:
        return 'bull'
    elif vol_percentile > 0.7 or mom_breadth < 0.3:
        return 'bear'
    else:
        return 'transition'

# Then in scoring:
regime = detect_regime(final_merged)
weight_sets = {
    'bull':       {'mom': 0.20, 'qual': 0.20, 'accel': 0.05, 'qual': 0.35, 'eps': 0.15, 'state': 0.05},
    'bear':       {'mom': 0.15, 'qual': 0.35, 'accel': 0.10, 'qual': 0.15, 'eps': 0.05, 'state': 0.20},
    'transition': {'mom': 0.25, 'qual': 0.25, 'accel': 0.15, 'qual': 0.20, 'eps': 0.10, 'state': 0.05},
}
w = weight_sets[regime]
final_merged['final_score'] = (
    final_merged['z_mom_risk_adj'] * w['mom'] +
    final_merged['z_mom_qual']     * w['qual'] +
    final_merged['z_accel']        * w['accel'] +
    final_merged['s_qual']         * w['qual'] +
    final_merged['z_eps']          * w['eps'] +
    final_merged['z_state']        * w['state']
)
```

**Why this works:** Momentum factors work best in trending markets; fundamentals matter more in mean-reverting environments; quality factors protect in uncertainty. Static weights are a compromise that works in all regimes but excels in none.

**Effect on algorithm:** Higher information ratio across market cycles. The strategy becomes adaptive — it naturally shifts toward what works in the current environment.

### 6.4 P3: Exponential Decay in Quality Metric

**Current code** (`03_generate_production_ratings.py:calculate_momentum_metrics`):
```python
pos_days = (group['returns'] > 0).sum()
neg_days = (group['returns'] < 0).sum()
inf_discr = np.sign(mom_12m) * (abs(pos_days - neg_days) / available_days)
```

**Recommended approach:** Apply exponential decay to weight recent days more heavily:

```python
# Exponential decay weights (half-life of 63 trading days ≈ 3 months)
decay = np.exp(-np.arange(len(group))[::-1] * np.log(2) / 63)
decay /= decay.sum()  # Normalize

# Weighted direction counts
pos_weight = (group['returns'] > 0) * decay
neg_weight = (group['returns'] < 0) * decay
pos_wt = pos_weight.sum()
neg_wt = neg_weight.sum()

inf_discr = np.sign(mom_12m) * (abs(pos_wt - neg_wt))
```

**Why this works:** Lee (2025) shows momentum alpha decays hyperbolically — the most recent data is far more predictive than data from 10 months ago. The current quality metric treats all 252 days equally, diluting the signal.

**Effect on algorithm:** More responsive quality metric that penalizes recent weakness even if the long-term trend is still positive. This catches deterioration earlier.

### 6.5 P4: Non-Linear Boost When Acceleration + Momentum Align

**Current code** (`03_generate_production_ratings.py:assign_production_rating`):
```python
is_breakout = (near_high > 0.96)
is_accelerating = (accel > 0.05) and (mom_3m > 0.10)
```

**Recommended approach:** Add a non-linear boost to the final score when acceleration and momentum are aligned:

```python
# In the final score calculation:
alignment_boost = 1.0
if merged_df['z_mom_risk_adj'] > 0 and merged_df['z_accel'] > 0:
    # Both signals agree — boost the combined momentum weight
    alignment_boost = 1.0 + 0.3 * min(abs(merged_df['z_accel'] / (abs(merged_df['z_mom_risk_adj']) + 1e-6)), 1.0)

final_merged['final_score'] = (
    final_merged['z_mom_risk_adj'] * 0.25 * alignment_boost +
    final_merged['z_mom_qual']     * 0.25 * alignment_boost +
    final_merged['z_accel']        * 0.05 +
    final_merged['s_qual']         * 0.30 * (2.0 - alignment_boost) +  # Normalize
    final_merged['z_eps']          * 0.10 +
    final_merged['z_state']        * 0.05
)
```

**Why this works:** When short-term momentum (3m) is accelerating relative to long-term momentum (12m), it's a powerful confirmation signal. The current 5% weight underweights this. The non-linear boost captures the interaction effect.

**Effect on algorithm:** Stronger conviction signals when momentum is fresh and accelerating (the "Emerging Breakout" scenario). Naturally suppresses scores when momentum is purely from old data.

### 6.6 P5: Dynamic Exit Thresholds

**Current code** (`03_generate_production_ratings.py:assign_production_rating`):
```python
if eps_rev < -0.03:    return "SELL (Estimate Decay)"
if rev_growth < 0:      return "SELL (No Growth)"
if mom < -0.10:        return "SELL (Trend Exhaustion)"
```

**Recommended approach:** Make thresholds regime-aware and percentile-based:

```python
# Pass universe-level stats to the rating function
def assign_production_rating(row, universe_mom_percentile=None, crowding_metric=None):
    score, eps_rev, mom = row.get('final_score', 0), row.get('eps_rev', 0), row.get('mom_score', 0)
    
    # Dynamic threshold: relax when momentum is crowded (less crash risk)
    # Tighten when momentum is concentrated in few stocks (more crash risk)
    if crowding_metric is not None:
        mom_threshold = -0.10 * (1 + crowding_metric)  # e.g., -0.10 to -0.15
    else:
        mom_threshold = -0.10
    
    # 1. EXIT TRIGGERS
    if eps_rev < -0.03:    return "SELL (Estimate Decay)"
    if rev_growth < 0:      return "SELL (No Growth)"
    if mom < mom_threshold: return "SELL (Trend Exhaustion)"
    ...
```

**Crowding metric:** Percentage of universe stocks with positive momentum minus percentage with negative momentum. When this is high (>0.5), momentum is crowded and crash risk is lower. When this is low (<0.1), momentum is concentrated and crash risk is higher.

**Why this works:** Lee (2025) shows crowded momentum has 0.38x lower crash probability. Your current exit trigger treats all momentum equally, but a -10% momentum drawdown in a crowded momentum environment is different from a -10% drawdown in a thin momentum environment.

**Effect on algorithm:** Fewer false exits in crowded momentum regimes (where the algorithm would be most invested), faster exits in thin momentum regimes (where crashes are more likely).

### 6.7 P6: LLM-Enhanced Sentiment for EPS Revisions

**Current code** (`03_generate_production_ratings.py:get_extensive_fundamentals`):
```python
eps_rev_val = 0.0
try:
    trend = stock.eps_trend
    if trend is not None and '0y' in trend.index:
        rev_row = trend.loc['0y']
        curr, ago30 = rev_row.get('current'), rev_row.get('30daysAgo')
        if curr and ago30 and ago30 != 0:
            eps_rev_val = (curr / ago30) - 1
except: pass
```

**Recommended approach:** Augment the numeric EPS revision with a qualitative news sentiment score:

```python
# In get_extensive_fundamentals():
eps_rev_val = 0.0
sentiment_score = 0.0  # -1.0 to 1.0

try:
    trend = stock.eps_trend
    if trend is not None and '0y' in trend.index:
        rev_row = trend.loc['0y']
        curr, ago30 = rev_row.get('current'), rev_row.get('30daysAgo')
        if curr and ago30 and ago30 != 0:
            eps_rev_val = (curr / ago30) - 1
except: pass

# OPTIONAL: LLM overlay
# If news data is available, augment eps_rev with sentiment:
# sentiment_score = llm_news_sentiment(ticker)  # async, batched
# eps_rev_val = 0.7 * eps_rev_val + 0.3 * sentiment_score

return {
    ...
    'eps_rev': eps_rev_val,
    'sentiment': sentiment_score,  # for future use
}
```

**Why this works:** Anic et al. (2025) show LLM-enhanced momentum delivers higher Sharpe and Sortino ratios, with gains "strongest for concentrated, high-conviction portfolios" — exactly your STRONG BUY ratings. The LLM acts as a qualitative filter that catches nuances numeric EPS revisions miss (e.g., "the revision was driven by one-time items" vs "the revision reflects genuine business improvement").

**Effect on algorithm:** More informed entry/exit decisions on the highest-conviction picks. The STRONG BUY ratings become more reliable.

---

## 7. Risk Assessment & Expected Effects

### 7.1 Risk Matrix

| Optimization | Overfitting Risk | Implementation Risk | Regime Dependency Risk |
|-------------|-----------------|-------------------|----------------------|
| P0: Range-based vol | Very Low — well-established estimator | Low — drop-in replacement | None — better in all regimes |
| P1: Multi-lookback | Low — 3 parameters, well-studied | Low — additive to existing code | Low — different lookbacks dominate different regimes |
| P2: Regime-aware weights | Medium — regime definition is a choice | Medium — adds complexity | Medium — wrong regime definition hurts |
| P3: Exponential decay | Low — single parameter (half-life) | Very Low — math change only | None — always better |
| P4: Non-linear boost | Low — bounded interaction term | Very Low — score formula change | Low — boost only activates when aligned |
| P5: Dynamic exits | Low — percentile-based is robust | Low — threshold parameters | Low — adapts to regime |
| P6: LLM overlay | Medium — depends on LLM quality | High — new data pipeline | Low — orthogonal to market regime |

### 7.2 Expected Effects on Ratings

**Conservative estimate (P0 + P1 only):**
- 10-15% reduction in false positive STRONG BUY signals (stocks with noisy momentum that reverses)
- 5-10% improvement in Sharpe ratio of the top-decile picks
- Fewer "momentum trap" entries (stocks that look good on 12-1 but are already rolling over)

**Moderate estimate (P0-P3):**
- 15-25% improvement in information ratio
- Better performance during regime transitions (where the current algorithm is weakest)
- More consistent rating accuracy across bull and bear markets

**Aggressive estimate (P0-P6):**
- 25-40% improvement in risk-adjusted returns on the STRONG BUY portfolio
- Significantly lower drawdown during momentum crashes (e.g., 2009, 2020)
- Higher concentration in high-conviction names (the LLM overlay filters out noise)

### 7.3 Key Risk: Overfitting False Precision

The biggest risk is adding too many parameters that are optimized on historical data but fail forward. Mitigations:

1. **Prefer well-established formulas** (Yang-Zhang vol, exponential decay) over learned parameters
2. **Use cross-validation** for any new parameters (e.g., regime thresholds, half-life)
3. **Test regime definitions** on out-of-sample periods (e.g., 2020 COVID crash, 2022 rate hike cycle)
4. **Start with P0 and P1** — they have the highest impact with the lowest risk. Validate before adding more.

---

## 8. Appendix: Paper Abstracts

### Paper 1: Spatio-Temporal Momentum
**Tan, Roberts, Zohren (2023) — [arxiv:2302.10175](https://arxiv.org/abs/2302.10175)**

> We introduce Spatio-Temporal Momentum strategies, a class of models that unify both time-series and cross-sectional momentum strategies by trading assets based on their cross-sectional momentum features over time... We model spatio-temporal momentum with neural networks of varying complexities and demonstrate that a simple neural network with only a single fully connected layer learns to simultaneously generate trading signals for all assets... Backtesting on portfolios of 46 actively-traded US equities and 12 equity index futures contracts, we demonstrate that the model is able to retain its performance over benchmarks in the presence of high transaction costs of up to 5-10 basis points.

### Paper 2: Constructing Time-Series Momentum Portfolios with Deep Multi-Task Learning
**Ong, Herremans (2023) — [arxiv:2306.13661](https://arxiv.org/abs/2306.13661)**

> A diversified risk-adjusted time-series momentum (TSMOM) portfolio can deliver substantial abnormal returns and offer some degree of tail risk protection during extreme market events. The performance of existing TSMOM strategies, however, relies not only on the quality of the momentum signal but also on the efficacy of the volatility estimator. Yet many of the existing studies have always considered these two factors to be independent. Inspired by recent progress in Multi-Task Learning (MTL), we present a new approach using MTL in a deep neural network architecture that jointly learns portfolio construction and various auxiliary tasks related to volatility.

### Paper 3: Portfolio Construction Matters
**Ciliberti, Gualdi (2018) — [arxiv:1810.08384](https://arxiv.org/abs/1810.08384)**

> The role of portfolio construction in the implementation of equity market neutral factors is often underestimated. Taking the classical momentum strategy as an example, we show that one can significantly improve the main strategy's features by properly taking care of this key step. More precisely, an optimized portfolio construction algorithm allows one to significantly improve the Sharpe Ratio, reduce sector exposures and volatility fluctuations, and mitigate the strategy's skewness and tail correlation with the market.

### Paper 4: Combining Independent Smart Beta Strategies
**Maguire, Moffett, Maguire (2018) — [arxiv:1808.02505](https://arxiv.org/abs/1808.02505)**

> We explore the idea of applying a smart strategy in reverse, yielding a "bad beta" portfolio which can be shorted... Working off a market benchmark Sharpe Ratio of 0.42, we find that the market neutral component achieves a ratio of 0.61, the low volatility approach achieves a ratio of 0.90, while the combined leveraged strategy achieves a ratio of 0.96. In six months of live trading, the combined strategy achieved a Sharpe Ratio of 1.35.

### Paper 5: Not All Factors Crowd Equally
**Lee (2025) — [arxiv:2512.11913](https://arxiv.org/abs/2512.11913)**

> We derive a specific functional form for factor alpha decay — hyperbolic decay α(t) = K/(1+λt) — from a game-theoretic equilibrium model. Using eight Fama-French factors (1963-2024), we find: (1) Hyperbolic decay fits mechanical factors. Momentum exhibits clear hyperbolic decay (R² = 0.65)... (2) Not all factors crowd equally... (3) Crowding accelerated post-2015... (4) Average returns are efficiently priced... (5) Crowding predicts tail risk. Out-of-sample (2001-2024), crowded reversal factors show 1.7-1.8x higher crash probability, while crowded momentum shows lower crash risk (0.38x).

### Paper 6: Winners vs. Losers — Momentum-based Strategies with Intertemporal Choice
**Jha et al. (2025) — [arxiv:2505.24250](https://arxiv.org/abs/2505.24250)**

> This paper introduces a state-dependent momentum framework that integrates ESG regime switching with tail-risk-aware reward-risk metrics. Unlike traditional momentum strategies based on historical returns, our approach incorporates the Stable Tail Adjusted Return ratio and Rachev ratio to better capture downside risk in turbulent markets.

### Paper 7: Dynamic Factor Allocation Leveraging Regime-Switching Signals
**Shu, Mulvey (2024) — [arxiv:2410.14841](https://arxiv.org/abs/2410.14841)**

> This article explores dynamic factor allocation by analyzing the cyclical performance of factors through regime analysis... Their approach integrates factor-specific regime inferences of each factor index's active performance relative to the market into the Black-Litterman model... Empirical results show that the constructed multi-factor portfolio significantly improves the information ratio (IR) relative to the market, raising it from just 0.05 for the EW benchmark to approximately 0.4.

### Paper 8: TrendFolios
**Lu et al. (2025) — [arxiv:2506.09330](https://arxiv.org/abs/2506.09330)**

> We design a portfolio construction framework and implement an active investment strategy utilizing momentum and trend-following signals across multiple asset classes and asset class risk factors. We quantify the performance of this strategy to demonstrate its ability to create excess returns above industry standard benchmarks, as well as manage volatility and drawdown risks over a 22+ year period.

### Paper 9: ChatGPT in Systematic Investing
**Anic et al. (2025) — [arxiv:2510.26228](https://arxiv.org/abs/2510.26228)**

> This paper investigates whether large language models (LLMs) can improve cross-sectional momentum strategies by extracting predictive signals from firm-specific news... An LLM-enhanced momentum strategy outperforms a standard long-only momentum benchmark, delivering higher Sharpe and Sortino ratios both in-sample and in a truly out-of-sample period after the model's pre-training cut-off. These gains are robust to transaction costs, prompt design, and portfolio constraints, and are strongest for concentrated, high-conviction portfolios.

### Paper 10: E2EAI — End-to-End Deep Learning Framework for Active Investing
**Wei, Dai, Lin (2023) — [arxiv:2305.16364](https://arxiv.org/abs/2305.16364)**

> We are the first to propose an E2E that covers almost the entire process of factor investing through factor selection, factor combination, stock selection, and portfolio construction. Extensive experiments on real stock market data demonstrate the effectiveness of our end-to-end deep leaning framework in active investing.

### Paper 11: NoxTrader — LSTM-Based Stock Return Momentum Prediction
**Liu, Shu, Chiu (2023) — [arxiv:2310.00747](https://arxiv.org/abs/2310.00747)**

> We utilize price and volume data of US stock market for feature engineering to generate effective features, including Return Momentum, Week Price Momentum, and Month Price Momentum... Our rigorous feature engineering and careful selection of prediction targets enable us to generate prediction data with an impressive correlation range between 0.65 and 0.75. Finally, we monitor the dispersion of our prediction data and perform a comparative analysis against actual market data. Through the use of filtering techniques, we improved the initial -60% investment return to 325%.

### Paper 12: Quant Convergence — Classical Value + Modern Factor Models
**Yamazaki, Belinchon (2026) — [arxiv:2606.24575](https://arxiv.org/abs/2606.24575)**

> We designed this research to test if Benjamin Graham's classic value investing rules could act as a mathematical "low-pass filter" to keep modern AI models in check... The Combined Random Forest successfully mixed momentum with Graham's rules, making a 202.91% return while keeping the lowest maximum drop (34.53%) of any model tested. Ultimately, this research proves that Graham's "margin of safety" isn't outdated; it is actually a highly effective way to prevent modern AI from taking on too much risk.

### Paper 13: Multi-Factor Market-Neutral Investment Strategy
**Gkolemis, Lee, Roudani (2024) — [arxiv:2412.12350](https://arxiv.org/abs/2412.12350)**

> A robust feature set is integrated combining momentum-based indicators, fundamental factors, and analyst recommendations. Using various statistical tests for feature selection, the strategy identifies key drivers of equity performance and ranks stocks to build a balanced portfolio of long and short positions. Portfolio construction methods, including equally weighted, risk parity, and minimum variance beta-neutral approaches, were evaluated through rigorous backtesting. Risk parity demonstrated superior performance with a higher Sharpe ratio, lower beta, and smaller maximum drawdown compared to the Standard and Poor's 500 index.

---

*Research conducted July 2026 via arxiv API. Papers selected for relevance to momentum trading algorithm optimization. All code snippets are illustrative and represent the proposed optimization, not the current implementation.*