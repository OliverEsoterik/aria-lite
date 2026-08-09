"""
TSMOM Momentum Ranker

Ranks all portfolio tickers by Time Series Momentum strength
(Moskowitz, Ooi & Pedersen, 2012).

The paper defines the TSMOM signal as sign(r_{t-12,t}).  Position size
is scaled by ex-ante volatility so the effective momentum "score" per
unit of risk is r_{12m} / σ — the annualised past-return Sharpe proxy.
That is the primary sort key here.

Outputs a ranked table of:
  Ticker | Trend | R_252 (%) | Ann.Vol (%) | Score (R/σ) | SMA Ratio

Usage:
    python 05_tsmom_momentum_ranker.py
    python 05_tsmom_momentum_ranker.py --top 10
    python 05_tsmom_momentum_ranker.py --all          # include TSMOM-off tickers
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from typing import List

# --- Configuration ---
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")

# Reuse portfolio and price-fetch logic from existing scripts
sys.path.insert(0, os.path.dirname(__file__))
_mod_03 = __import__("03_generate_production_ratings")
CURRENT_PORTFOLIO = _mod_03.CURRENT_PORTFOLIO

# Mirror the same defaults as script 04
SMA_WINDOW = 210
TSMOM_WINDOW = 252
VOL_WINDOW = 60


def fetch_prices(engine, tickers: List[str]) -> pd.DataFrame:
    """Fetch adjusted close prices — identical logic to script 04."""
    if not tickers:
        return pd.DataFrame()

    query = text("""
        SELECT
            DATE(timestamp) AS date,
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
    return prices


def compute_momentum_scores(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-ticker TSMOM metrics.

    Columns returned:
        Trend      — 1 if P > SMA_210 and R_252 > 0, else 0  (Moskowitz signal gate)
        R_252_pct  — raw 12-month return, %
        Vol_pct    — annualised EWMA volatility, %
        Score      — R_252 / σ  (volatility-scaled momentum, the ex-ante Sharpe proxy)
        SMA_Ratio  — latest price / SMA_210  (trend strength proxy)
    """
    prices = prices.ffill().bfill()

    latest = prices.iloc[-1]
    sma_210 = prices.rolling(window=SMA_WINDOW).mean().iloc[-1]
    r_252 = (latest / prices.iloc[-TSMOM_WINDOW]) - 1.0

    log_returns = np.log(prices / prices.shift(1))
    ewma_std = log_returns.ewm(span=VOL_WINDOW).std().iloc[-1]
    ann_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)

    records = []
    for ticker in prices.columns:
        r = float(r_252[ticker])
        v = float(ann_vol[ticker]) if not np.isnan(ann_vol[ticker]) else np.nan
        trend = int((latest[ticker] > sma_210[ticker]) and (r > 0))
        score = r / v if (v and not np.isnan(v)) else np.nan
        sma_ratio = float(latest[ticker] / sma_210[ticker]) if sma_210[ticker] > 0 else np.nan

        records.append(
            {
                "Ticker": ticker,
                "Trend": trend,
                "R_252_pct": round(r * 100, 2),
                "Vol_pct": round(v * 100, 2) if not np.isnan(v) else np.nan,
                "Score": round(score, 3) if not np.isnan(score) else np.nan,
                "SMA_Ratio": round(sma_ratio, 4) if not np.isnan(sma_ratio) else np.nan,
            }
        )

    df = pd.DataFrame(records).set_index("Ticker")
    df = df.sort_values("Score", ascending=False, na_position="last")
    return df


def print_rankings(df: pd.DataFrame, show_all: bool, top_n: int) -> None:
    subset = df if show_all else df[df["Trend"] == 1]
    if top_n:
        subset = subset.head(top_n)

    n_on  = (df["Trend"] == 1).sum()
    n_off = (df["Trend"] == 0).sum()

    print(f"\n{'=' * 72}")
    print(f"  TSMOM MOMENTUM RANKINGS — {pd.Timestamp.today().date()}")
    print(f"  {len(df)} tickers total  |  {n_on} TSMOM-ON  {n_off} TSMOM-OFF")
    if not show_all:
        print(f"  Showing TSMOM-ON only (pass --all to include off-trend tickers)")
    print("=" * 72)
    print(f"  {'#':<4} {'Ticker':<8} {'Trend':>6} {'R_252%':>8} {'Vol%':>7} {'Score':>7}  {'SMA Ratio':>9}")
    print("  " + "-" * 60)

    for rank, (ticker, row) in enumerate(subset.iterrows(), start=1):
        trend_marker = "✔" if row["Trend"] == 1 else "✖"
        r     = f"{row['R_252_pct']:+.1f}" if not pd.isna(row["R_252_pct"]) else "  n/a"
        v     = f"{row['Vol_pct']:.1f}"    if not pd.isna(row["Vol_pct"])   else "  n/a"
        score = f"{row['Score']:+.3f}"     if not pd.isna(row["Score"])     else "   n/a"
        smar  = f"{row['SMA_Ratio']:.4f}"  if not pd.isna(row["SMA_Ratio"]) else "   n/a"
        print(f"  {rank:<4} {ticker:<8} {trend_marker:>6} {r:>8} {v:>7} {score:>7}  {smar:>9}")

    print()
    if not subset.empty:
        top = subset.index[0]
        print(f"  ★  Strongest momentum: {top}  "
              f"(Score={subset.loc[top,'Score']:+.3f}, "
              f"R_252={subset.loc[top,'R_252_pct']:+.1f}%)\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank portfolio tickers by TSMOM momentum strength"
    )
    parser.add_argument(
        "--top", type=int, default=0, metavar="N",
        help="Show only the top N tickers (default: all)"
    )
    parser.add_argument(
        "--all", dest="show_all", action="store_true",
        help="Include tickers where TSMOM signal is OFF (trend=0)"
    )
    args = parser.parse_args()

    tickers = list(dict.fromkeys(CURRENT_PORTFOLIO))
    print(f"[INFO] Fetching price history for {len(tickers)} tickers...")

    engine = create_engine(DB_URL, pool_size=5, max_overflow=10)
    prices = fetch_prices(engine, tickers)

    if prices.empty:
        sys.exit("[ERROR] No price data returned. Is the database running?")

    valid = [t for t in prices.columns if prices[t].notna().sum() >= TSMOM_WINDOW]
    dropped = [t for t in prices.columns if t not in valid]
    if dropped:
        print(f"[WARN] Dropping {len(dropped)} ticker(s) with < {TSMOM_WINDOW} days: {dropped}",
              file=sys.stderr)
    prices = prices[valid]

    if prices.empty:
        sys.exit("[ERROR] No tickers have sufficient price history.")

    scores = compute_momentum_scores(prices)
    print_rankings(scores, show_all=args.show_all, top_n=args.top)


if __name__ == "__main__":
    main()
