"""
TSMOM Execution Engine — standalone EMS script.

Implements Time Series Momentum (Moskowitz et al. 2012) with
Volatility-Targeting and Hysteresis Deadband (Hurst et al. 2017).

Usage:
    python 04_tsmom_execution_engine.py
    python 04_tsmom_execution_engine.py --weights-file data/my_weights.json

Weights file format (JSON):
    {"NVDA": 0.05, "MSFT": 0.04, ...}
    Missing tickers default to 0.0 (not currently held).
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from typing import Dict, Literal


# --- Configuration (matches existing ETL scripts) ---
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")

# Import portfolio definition from script 03 — single source of truth
sys.path.insert(0, os.path.dirname(__file__))
_mod_03 = __import__('03_generate_production_ratings')
CURRENT_PORTFOLIO = _mod_03.CURRENT_PORTFOLIO


class TSMOMExecutionEngine:
    """
    Production-Grade Execution Management System (EMS) implementing Time Series Momentum
    (Moskowitz et al., 2012) with Hysteresis Turnover Controls (Hurst et al., 2017).

    Fundamental signal gate is disabled: T_i(t) = 1 iff P > SMA_210 AND R_252 > 0.
    """

    def __init__(
        self,
        target_annual_volatility: float = 0.15,
        min_rebalance_threshold: float = 0.05,
        sma_window_days: int = 210,
        tsmom_window_days: int = 252,
        volatility_window_days: int = 60,
    ):
        self.target_annual_volatility = target_annual_volatility
        self.min_rebalance_threshold = min_rebalance_threshold
        self.sma_window_days = sma_window_days
        self.tsmom_window_days = tsmom_window_days
        self.volatility_window_days = volatility_window_days

    def calculate_orders(
        self,
        daily_prices: pd.DataFrame,
        current_weights: Dict[str, float],
    ) -> pd.DataFrame:
        """
        Compute TSMOM execution orders.

        Args:
            daily_prices: DatetimeIndex × ticker DataFrame of adjusted close prices.
                          Must contain at least `tsmom_window_days` rows.
            current_weights: {ticker: decimal_weight} for currently held positions.
                             Tickers absent from this dict are treated as weight 0.

        Returns:
            DataFrame indexed by Ticker with columns:
                Current_Weight, Target_Weight, Weight_Delta, Action
            Filtered to non-HOLD rows only, sorted SELL → BUY → REBALANCE.

        Raises:
            ValueError: if fewer than `tsmom_window_days` rows are provided.
        """
        if len(daily_prices) < self.tsmom_window_days:
            raise ValueError(
                f"Insufficient price history. Required: {self.tsmom_window_days} days, "
                f"Provided: {len(daily_prices)} days."
            )

        prices = daily_prices.ffill().bfill()

        latest = prices.iloc[-1]
        sma_210 = prices.rolling(window=self.sma_window_days).mean().iloc[-1]
        r_252 = (latest / prices.iloc[-self.tsmom_window_days]) - 1.0

        # Ex-ante annualised EWMA volatility
        log_returns = np.log(prices / prices.shift(1))
        ewma_std = log_returns.ewm(span=self.volatility_window_days).std().iloc[-1]
        annualised_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)

        # Composite trend state T_i ∈ {0, 1} — price-only, no fundamental gate
        trend = pd.Series(
            {
                ticker: int(
                    (latest[ticker] > sma_210[ticker]) and (r_252[ticker] > 0)
                )
                for ticker in prices.columns
            }
        )

        # Volatility-targeted raw weights
        raw_weights = (self.target_annual_volatility / annualised_vol) * trend
        raw_weights = raw_weights.fillna(0.0)

        total = raw_weights.sum()
        target_weights = raw_weights / total if total > 0 else pd.Series(0.0, index=prices.columns)

        # Order generation
        records = []
        for ticker in prices.columns:
            c = float(current_weights.get(ticker, 0.0))
            t = float(target_weights[ticker])
            delta = t - c
            action = self._resolve_action(c, t, delta)
            records.append(
                {
                    "Ticker": ticker,
                    "Current_Weight": round(c, 4),
                    "Target_Weight": round(t, 4),
                    "Weight_Delta": round(delta, 4),
                    "Action": action,
                }
            )

        df = pd.DataFrame(records).set_index("Ticker")
        actionable = df[df["Action"] != "HOLD"].copy()

        _priority = {"SELL": 0, "BUY": 1, "REBALANCE": 2}
        actionable["_p"] = actionable["Action"].map(_priority)
        actionable = actionable.sort_values(["_p", "Weight_Delta"]).drop(columns=["_p"])
        return actionable

    def _resolve_action(
        self, current_w: float, target_w: float, delta: float
    ) -> Literal["SELL", "BUY", "REBALANCE", "HOLD"]:
        if target_w == 0.0 and current_w > 0.0:
            return "SELL"
        elif current_w == 0.0 and target_w > 0.0:
            return "BUY"
        elif abs(delta) >= self.min_rebalance_threshold:
            return "REBALANCE"
        else:
            return "HOLD"
