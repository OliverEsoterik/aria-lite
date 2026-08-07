# Technical Specification: Time Series Momentum (TSMOM) Execution Overlay Engine

## 1. Context & Objective

I would like to add a new feature.

In the file 03_generate_production_ratings.py i specify tickers inside "CURRENT_PORTFOLIO"

I now want to integrate a **Time Series Momentum (TSMOM)** and **Volatility-Targeting** execution overlay module for these tickers.

It would be good to have a complete separate script maybe whch is not destroying or making large adjustments to my current scripts.

This script acts as the **Execution Management System (EMS)** layer: it determines exact entry/exit timing and portfolio position sizing using time-series trend rules and risk-parity volatility adjustments, adhering to execution thresholds to cap monthly turnover at $\le 5$ trades.

You can fetch all data through yfinance.

**Academic Foundation:**
1. **Moskowitz, Ooi, and Pedersen (2012):** *Time Series Momentum* (12-month excess return signal and ex-ante volatility scaling).
2. **Hurst, Ooi, and Pedersen (2017):** *A Century of Trend Following Investing* (Moving average trend filtering and trade execution deadbands/hysteresis).

## 2. Mathematical Specification

### A. Trend Signal Calculation ($T_i(t)$)
For a ticker $i$ on day $t$, given price history $P_i$:

1. **10-Month Simple Moving Average ($SMA_{210}$):**
$$SMA_{210, i}(t) = \frac{1}{210} \sum_{k=0}^{209} P_i(t-k)$$

2. **12-Month Momentum Return ($R_{252}$):**
$$R_{252, i}(t) = \frac{P_i(t)}{P_i(t-252)} - 1$$

3. **Composite Trend State ($T_i(t) \in \{0, 1\}$):**
$$T_i(t) = \begin{cases} 1 & \text{if } P_i(t) > SMA_{210, i}(t) \text{ AND } R_{252, i}(t) > 0 \text{ AND Fundamental Signal} \in \{\text{'BUY'}, \text{'STRONG BUY'}\} \\ 0 & \text{otherwise} \end{cases}$$

### B. Volatility Sizing (Inverse Risk Weighting)
1. **Ex-Ante Annualized Volatility ($\sigma_i(t)$):**
Calculated using a 60-day exponentially weighted moving average (EWMA) of daily log returns $r_i(t) = \ln(P_i(t) / P_i(t-1))$:
$$\sigma_i(t) = \text{EWMA}_{\text{span}=60}\left(r_i(t)\right) \cdot \sqrt{252}$$

2. **Raw Weight Allocation ($W_{\text{raw}, i}(t)$):**
Given target annual portfolio volatility $\sigma_{\text{target}} = 0.15$ (15%):
$$W_{\text{raw}, i}(t) = \left( \frac{\sigma_{\text{target}}}{\sigma_i(t)} \right) \cdot T_i(t)$$

3. **Normalized Portfolio Weight ($W_{\text{target}, i}(t)$):**
$$W_{\text{target}, i}(t) = \begin{cases} \frac{W_{\text{raw}, i}(t)}{\sum_{j} W_{\text{raw}, j}(t)} & \text{if } \sum_{j} W_{\text{raw}, j}(t) > 0 \\ 0 & \text{otherwise} \end{cases}$$

### C. Execution Deadband & Action Decision Rules
To suppress unnecessary turnover on high-beta equities, compare $W_{\text{target}, i}(t)$ against the current weight $W_{\text{current}, i}(t)$ using rebalance threshold parameter $\theta_{\text{rebalance}} = 0.05$ (5%):

$$\text{Action}_i(t) = \begin{cases}  \text{\textbf{SELL}} & \text{if } W_{\text{target}, i}(t) = 0 \text{ AND } W_{\text{current}, i}(t) > 0 \\ \text{\textbf{BUY}} & \text{if } W_{\text{current}, i}(t) = 0 \text{ AND } W_{\text{target}, i}(t) > 0 \\ \text{\textbf{REBALANCE}} & \text{if } \vert{}W_{\text{target}, i}(t) - W_{\text{current}, i}(t)\vert{} \ge \theta_{\text{rebalance}} \\ \text{\textbf{HOLD}} & \text{otherwise} \end{cases}$$

## 3. Implementation Requirements

### Input Interface Contract
* **daily_prices:** `pd.DataFrame` containing at least **252 trading days** of historical adjusted close prices. Index: `DatetimeIndex`, Columns: `Ticker` strings.
* **fundamental_signals:** `Dict[str, str]` or `pd.Series` mapping tickers to fundamental classifications (`'STRONG BUY'`, `'BUY'`, `'HOLD'`, `'SELL'`).
* **current_portfolio_weights:** `Dict[str, float]` mapping currently held tickers to their decimal portfolio allocation.

### Output Dataframe Schema
Returned DataFrame must contain only actionable trades (`Action != 'HOLD'`), structured as:
* `Ticker` (Index / String)
* `Current_Weight` (Float, 4 decimals)
* `Target_Weight` (Float, 4 decimals)
* `Weight_Delta` (Float, 4 decimals)
* `Action` (Enum / String: `'BUY'`, `'SELL'`, `'REBALANCE'`)

## 4. Production-Ready Python Module

```python
import numpy as np
import pandas as pd
from typing import Dict, Literal

class TSMOMExecutionEngine:
    \"\"\"
    Production-Grade Execution Management System (EMS) implementing Time Series Momentum
    (Moskowitz et al., 2012) with Hysteresis Turnover Controls (Hurst et al., 2017).
    \"\"\"

    def __init__(self, 
                 target_annual_volatility: float = 0.15,
                 min_rebalance_threshold: float = 0.05,
                 sma_window_days: int = 210,
                 tsmom_window_days: int = 252,
                 volatility_window_days: int = 60):
        self.target_annual_volatility = target_annual_volatility
        self.min_rebalance_threshold = min_rebalance_threshold
        self.sma_window_days = sma_window_days
        self.tsmom_window_days = tsmom_window_days
        self.volatility_window_days = volatility_window_days

    def calculate_orders(
        self, 
        daily_prices: pd.DataFrame, 
        fundamental_signals: Dict[str, str],
        current_weights: Dict[str, float]
    ) -> pd.DataFrame:
        if len(daily_prices) < self.tsmom_window_days:
            raise ValueError(
                f"Insufficient price history. Required: {self.tsmom_window_days} days, "
                f"Provided: {len(daily_prices)} days."
            )

        # Ensure price data has no NaN gaps
        prices = daily_prices.ffill().bfill()
        
        # 1. Latest Metrics
        latest_prices = prices.iloc[-1]
        sma_210 = prices.rolling(window=self.sma_window_days).mean().iloc[-1]
        tsmom_returns = (latest_prices / prices.iloc[-self.tsmom_window_days]) - 1.0

        # 2. Ex-Ante Annualized EWMA Volatility
        daily_returns = np.log(prices / prices.shift(1))
        ewma_std = daily_returns.ewm(span=self.volatility_window_days).std().iloc[-1]
        annualized_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)

        # 3. Composite Trend Evaluation
        trend_signals = {}
        for ticker in prices.columns:
            f_sig = str(fundamental_signals.get(ticker, "SELL")).upper()
            is_fund_valid = f_sig in ["BUY", "STRONG BUY"]
            is_tech_valid = (latest_prices[ticker] > sma_210[ticker]) and (tsmom_returns[ticker] > 0)
            
            trend_signals[ticker] = 1 if (is_fund_valid and is_tech_valid) else 0

        trend_series = pd.Series(trend_signals)

        # 4. Volatility Sizing & Portfolio Normalization
        raw_weights = (self.target_annual_volatility / annualized_vol) * trend_series
        raw_weights = raw_weights.fillna(0.0)

        total_weight = raw_weights.sum()
        if total_weight > 0:
            target_weights = raw_weights / total_weight
        else:
            target_weights = pd.Series(0.0, index=prices.columns)

        # 5. Order Generation Logic
        order_records = []
        for ticker in prices.columns:
            c_weight = float(current_weights.get(ticker, 0.0))
            t_weight = float(target_weights[ticker])
            delta = t_weight - c_weight

            action = self._resolve_action(c_weight, t_weight, delta)

            order_records.append({
                'Ticker': ticker,
                'Current_Weight': round(c_weight, 4),
                'Target_Weight': round(t_weight, 4),
                'Weight_Delta': round(delta, 4),
                'Action': action
            })

        orders_df = pd.DataFrame(order_records).set_index('Ticker')
        
        # Filter for actionable trade instructions
        actionable_df = orders_df[orders_df['Action'] != 'HOLD'].copy()
        
        # Custom sort order: Liquidations (SELL) first, then BUYs, then REBALANCEs
        action_priority = {'SELL': 0, 'BUY': 1, 'REBALANCE': 2}
        actionable_df['Priority'] = actionable_df['Action'].map(action_priority)
        actionable_df = actionable_df.sort_values(by=['Priority', 'Weight_Delta']).drop(columns=['Priority'])

        return actionable_df

    def _resolve_action(
        self, 
        current_w: float, 
        target_w: float, 
        delta: float
    ) -> Literal["SELL", "BUY", "REBALANCE", "HOLD"]:
        if target_w == 0.0 and current_w > 0.0:
            return "SELL"
        elif current_w == 0.0 and target_w > 0.0:
            return "BUY"
        elif abs(delta) >= self.min_rebalance_threshold:
            return "REBALANCE"
        else:
            return "HOLD"