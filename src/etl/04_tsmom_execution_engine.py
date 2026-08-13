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
from typing import Dict, List, Literal, Optional


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
        actionable_only: bool = True,
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

        df = df.sort_values("Target_Weight", ascending=False)

        if actionable_only:
            return df[df["Action"] != "HOLD"].copy()
        return df

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


def fetch_portfolio_prices(engine, tickers: List[str]) -> pd.DataFrame:
    """
    Fetch adjusted close prices for a list of tickers from the DB.

    Uses price_adjusted where available, falls back to price_close.
    Returns a DatetimeIndex x ticker DataFrame sorted oldest-first.
    Tickers with no rows are dropped from the result.
    """
    if not tickers:
        return pd.DataFrame()

    query = text("""
        SELECT
            DATE(timestamp)                                    AS date,
            ticker,
            CASE
                WHEN price_adjusted IS NOT NULL AND price_adjusted > 0
                    THEN price_adjusted::double precision
                ELSE price_close::double precision
            END AS adj_close
        FROM market_prices
        WHERE ticker IN :tickers
          AND timestamp >= NOW() - INTERVAL '400 days'
        ORDER BY ticker, date ASC
    """)

    with engine.connect() as conn:
        raw = pd.read_sql(query, conn, params={"tickers": tuple(tickers)})

    if raw.empty:
        return pd.DataFrame()

    prices = (
        raw.groupby(["date", "ticker"])["adj_close"]
        .last()
        .unstack("ticker")
        .sort_index()
    )
    prices.index = pd.to_datetime(prices.index)

    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"[WARN] No price data found for: {missing}", file=sys.stderr)

    return prices


def load_weights(tickers: List[str], weights_file: Optional[str] = None) -> Dict[str, float]:
    """
    Build current_weights dict.

    If weights_file is None: equal-weight across all tickers (1/N).
    If weights_file is given: parse JSON {"TICKER": float, ...}.
        Tickers in the file but not in tickers list are ignored.
        Tickers in tickers list but not in the file default to 0.0.

    Raises SystemExit on file not found or invalid JSON.
    """
    if weights_file is None:
        n = len(tickers)
        if n == 0:
            return {}
        w = 1.0 / n
        return {t: w for t in tickers}

    if not os.path.exists(weights_file):
        sys.exit(f"[ERROR] Weights file not found: {weights_file}")

    try:
        with open(weights_file) as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"[ERROR] Invalid JSON in weights file: {exc}")

    return {t: float(raw.get(t, 0.0)) for t in tickers}


def load_positions(positions_file: str) -> Dict[str, float]:
    """
    Load current portfolio positions from a JSON file.

    Format: {"TICKER": euro_amount, ...}
        - euro_amount must be >= 0.0 (zero means "not held")
        - Negative values raise SystemExit

    Returns {ticker: absolute_amount}.
    """
    if not os.path.exists(positions_file):
        sys.exit(f"[ERROR] Positions file not found: {positions_file}")

    try:
        with open(positions_file) as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"[ERROR] Invalid JSON in positions file: {exc}")

    if not isinstance(raw, dict):
        sys.exit("[ERROR] Positions file must contain a JSON object (dict).")

    for ticker, amount in raw.items():
        if not isinstance(amount, (int, float)):
            sys.exit(f"[ERROR] Invalid position for {ticker}: expected a number, got {type(amount).__name__}")
        if amount < 0:
            sys.exit(f"[ERROR] Negative position for {ticker}: {amount}")

    return {str(ticker).upper(): float(amount) for ticker, amount in raw.items()}


def print_orders(orders: pd.DataFrame, total_value: Optional[float] = None) -> None:
    """
    Print the full portfolio position table.

    If total_value is provided, EUR amounts are shown alongside percentages.
    """
    n_sell      = (orders["Action"] == "SELL").sum()
    n_buy       = (orders["Action"] == "BUY").sum()
    n_rebalance = (orders["Action"] == "REBALANCE").sum()
    n_hold      = (orders["Action"] == "HOLD").sum()

    has_eur = total_value is not None and total_value > 0

    print(f"\n{'=' * 80}")
    print(f"  TSMOM EXECUTION ENGINE — {pd.Timestamp.today().date()}")
    print(f"  {len(orders)} tickers  |  "
          f"{n_sell} SELL  {n_buy} BUY  {n_rebalance} REBALANCE  {n_hold} HOLD")
    if has_eur:
        print(f"  Portfolio value: €{total_value:,.0f}")
    print("=" * 80)

    if has_eur:
        print(f"  {'Ticker':<8} {'Curr €':>12} {'Curr%':>7} {'Tgt €':>12} {'Tgt%':>7} {'Delta €':>12} {'Delta%':>8}  Action")
        print("  " + "-" * 76)
    else:
        print(f"  {'Ticker':<8} {'Curr%':>7} {'Tgt%':>7} {'Delta%':>8}  Action")
        print("  " + "-" * 52)

    for ticker, row in orders.iterrows():
        action = row["Action"]
        marker = "  "
        if action == "SELL":      marker = "✖ "
        elif action == "BUY":     marker = "✚ "
        elif action == "REBALANCE": marker = "↕ "

        if has_eur:
            curr_eur  = row["Current_Weight"] * total_value
            tgt_eur   = row["Target_Weight"] * total_value
            delta_eur = row["Weight_Delta"] * total_value
            curr_pct  = row["Current_Weight"] * 100
            tgt_pct   = row["Target_Weight"] * 100
            delta_pct = row["Weight_Delta"] * 100
            print(f"{marker}{ticker:<8} €{curr_eur:>9,.0f} {curr_pct:>6.2f} "
                  f"€{tgt_eur:>9,.0f} {tgt_pct:>6.2f} "
                  f"€{delta_eur:>+9,.0f} {delta_pct:>+7.2f}  {action}")
        else:
            curr  = f"{row['Current_Weight']*100:.2f}"
            tgt   = f"{row['Target_Weight']*100:.2f}"
            delta = f"{row['Weight_Delta']*100:+.2f}"
            print(f"{marker}{ticker:<8} {curr:>7} {tgt:>7} {delta:>8}  {action}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TSMOM Execution Engine — print daily execution orders for CURRENT_PORTFOLIO"
    )
    parser.add_argument(
        "--weights-file",
        metavar="PATH",
        default=None,
        help="JSON file mapping ticker→current decimal weight. "
             "Omit to use equal-weight across all portfolio tickers.",
    )
    parser.add_argument(
        "--positions-file",
        metavar="PATH",
        default=None,
        help="JSON file mapping ticker→current EUR amount (e.g. {\"NVDA\": 10000}). "
             "Overrides --weights-file if both are given.",
    )
    args = parser.parse_args()

    # Deduplicate portfolio tickers (CURRENT_PORTFOLIO has duplicates)
    tickers = list(dict.fromkeys(CURRENT_PORTFOLIO))

    print(f"[INFO] Fetching price history for {len(tickers)} tickers...")
    db_engine = create_engine(DB_URL, pool_size=5, max_overflow=10)
    prices = fetch_portfolio_prices(db_engine, tickers)

    if prices.empty:
        sys.exit("[ERROR] No price data returned from DB. Is the database running?")

    # ------------------------------------------------------------
    # Load current holdings: positions file, weights file, or equal-weight
    # ------------------------------------------------------------
    total_portfolio_value: Optional[float] = None

    if args.positions_file is not None:
        # Load positions BEFORE filtering so we can detect held-but-dropped tickers
        raw_positions = load_positions(args.positions_file)
        total_portfolio_value = sum(raw_positions.values())

        if total_portfolio_value <= 0:
            sys.exit("[ERROR] Total portfolio value must be > 0 in positions file.")

        # Build weight dict for ALL price-available tickers (before filtering)
        all_tickers_weights = {
            t: raw_positions.get(t, 0.0) / total_portfolio_value
            for t in prices.columns
        }
        print(f"[INFO] Loaded positions for {len(raw_positions)} ticker(s), "
              f"total portfolio value = \u20ac{total_portfolio_value:,.0f}")

        if args.weights_file is not None:
            print("[INFO] --positions-file takes precedence; ignoring --weights-file.")
    else:
        # Fall back to existing weights-file or equal-weight
        all_tickers_weights = load_weights(list(prices.columns), args.weights_file)

    # Drop tickers with insufficient data (< 252 rows after pivot)
    valid_tickers = [t for t in prices.columns if prices[t].notna().sum() >= 252]
    dropped = [t for t in prices.columns if t not in valid_tickers]
    if dropped:
        print(f"[WARN] Dropping {len(dropped)} ticker(s) with < 252 days: {dropped}", file=sys.stderr)
    prices = prices[valid_tickers]

    if prices.empty:
        sys.exit("[ERROR] No tickers have sufficient price history (252 days required).")

    # Warn about held-but-dropped tickers
    for ticker in dropped:
        w = all_tickers_weights.get(ticker, 0.0)
        if w > 0.0:
            print(f"[WARN] {ticker}: held (weight={w:.4f}) but insufficient price history — no SELL generated", file=sys.stderr)

    if args.positions_file is not None:
        current_weights = {t: raw_positions.get(t, 0.0) / total_portfolio_value for t in valid_tickers}
    else:
        current_weights = load_weights(valid_tickers, args.weights_file)

    eng = TSMOMExecutionEngine()
    try:
        orders = eng.calculate_orders(prices, current_weights, actionable_only=False)
    except ValueError as exc:
        sys.exit(f"[ERROR] {exc}")

    print_orders(orders, total_value=total_portfolio_value)


if __name__ == "__main__":
    main()
