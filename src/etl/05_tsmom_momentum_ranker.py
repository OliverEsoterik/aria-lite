"""
TSMOM Momentum Ranker — Multi-Window Composite (Hurst, Ooi & Pedersen, 2017)

Ranks portfolio tickers by the equal-weighted combination of 1-month,
3-month, and 12-month volatility-scaled momentum signals.

Hurst et al. (2017) extend Moskowitz et al. (2012) across 137 years of
data and show that combining signals across multiple horizons produces
more robust trend detection.  The composite catches stocks that have
recently rolled over (short-term windows negative) even if the 12-month
return remains positive.

Output columns:
  Ticker | Trend | Votes | Grade | R_21% | R_63% | R_252% | Score_21 | Score_63 | Score_252 | Composite | SMA_Ratio

  Composite = (Score_21 + Score_63 + Score_252) / 3  (the primary sort key)
  Votes     = how many of the three windows show positive returns (0-3)

Usage:
    python 05_tsmom_momentum_ranker.py
    python 05_tsmom_momentum_ranker.py --top 10
    python 05_tsmom_momentum_ranker.py --all          # include tickers with no positive windows
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

# Multi-window lookbacks per Hurst et al. (2017)
WINDOWS = {
    "R_21": 21,    # 1-month
    "R_63": 63,    # 3-month
    "R_252": 252,  # 12-month
}


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


def _grade(votes: int, composite: float) -> str:
    """Momentum letter grade based on votes and composite score."""
    if pd.isna(composite):
        return "F"
    if votes == 3:
        if composite > 3.0:
            return "A+"
        elif composite > 1.0:
            return "A"
        else:
            return "A-"
    elif votes == 2:
        if composite > 2.0:
            return "B+"
        elif composite > 0.5:
            return "B"
        else:
            return "B-"
    elif votes == 1:
        if composite > 1.0:
            return "C+"
        elif composite > 0.0:
            return "C"
        else:
            return "D"
    else:
        return "F"


def compute_momentum_scores(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-ticker TSMOM metrics across three windows (Hurst et al. 2017).

    Returns:
        DataFrame indexed by Ticker with columns:
            Trend          — 1 if Composite_Score > 0, else 0 (for backward compat)
            Votes          — count of windows with positive returns (0-3)
            Grade          — momentum letter grade (A+ to F)
            R_21_pct       — raw 21-day return, %
            R_63_pct       — raw 63-day return, %
            R_252_pct      — raw 252-day return, %
            Score_21       — R_21 / σ (vol-scaled 1-month momentum, σ = EWMA-60 ann. vol)
            Score_63       — R_63 / σ (vol-scaled 3-month momentum, shared σ)
            Score_252      — R_252 / σ (vol-scaled 12-month momentum, shared σ)
            Composite_Score— average of all three scores (primary sort key)
            SMA_Ratio      — latest price / SMA_210 (trend steepness proxy)
    """
    prices = prices.ffill().bfill()

    log_returns = np.log(prices / prices.shift(1))
    ewma_std = log_returns.ewm(span=60).std().iloc[-1]
    ann_vol = (ewma_std * np.sqrt(252)).replace(0, np.nan)

    sma_210 = prices.rolling(window=210).mean().iloc[-1]
    latest = prices.iloc[-1]

    # Pre-compute prices at each lookback (replace zero to prevent inf returns)
    price_at = {name: prices.iloc[-window].replace(0, np.nan) for name, window in WINDOWS.items()}

    records = []
    for ticker in prices.columns:
        v = float(ann_vol[ticker]) if not np.isnan(ann_vol[ticker]) else np.nan

        scores = {}
        raw_returns = {}
        votes = 0

        for name, window in WINDOWS.items():
            # Raw return for this window
            r = float((latest[ticker] / price_at[name][ticker]) - 1.0)
            raw_returns[name] = r

            # Vol-scaled score
            score = r / v if (v and not np.isnan(v) and v > 0) else np.nan
            scores[name] = score

            if not np.isnan(r) and r > 0:
                votes += 1

        # Composite: average of available vol-scaled scores
        valid_scores = [s for s in scores.values() if not np.isnan(s)]
        composite = np.mean(valid_scores) if valid_scores else np.nan

        trend = int(not np.isnan(composite) and composite > 0)
        sma_ratio = float(latest[ticker] / sma_210[ticker]) if sma_210[ticker] > 0 else np.nan

        records.append({
            "Ticker": ticker,
            "Trend": trend,
            "Votes": votes,
            "Grade": _grade(votes, composite),
            "R_21_pct": round(raw_returns["R_21"] * 100, 2),
            "R_63_pct": round(raw_returns["R_63"] * 100, 2),
            "R_252_pct": round(raw_returns["R_252"] * 100, 2),
            "Score_21": round(scores["R_21"], 3) if not np.isnan(scores["R_21"]) else np.nan,
            "Score_63": round(scores["R_63"], 3) if not np.isnan(scores["R_63"]) else np.nan,
            "Score_252": round(scores["R_252"], 3) if not np.isnan(scores["R_252"]) else np.nan,
            "Composite_Score": round(composite, 3) if not np.isnan(composite) else np.nan,
            "SMA_Ratio": round(sma_ratio, 4) if not np.isnan(sma_ratio) else np.nan,
        })

    df = pd.DataFrame(records).set_index("Ticker")
    df = df.sort_values("Composite_Score", ascending=False, na_position="last")
    return df


def print_rankings(df: pd.DataFrame, show_all: bool, top_n: int) -> None:
    """Print ranked table sorted by Composite_Score."""
    # Default filter: show tickers with Composite_Score > 0
    subset = df if show_all else df[df["Composite_Score"] > 0]
    if top_n:
        subset = subset.head(top_n)

    n_pos = (df["Composite_Score"] > 0).sum()
    n_neg = (df["Composite_Score"] <= 0).sum()

    print(f"\n{'=' * 128}")
    print(f"  TSMOM MULTI-WINDOW RANKINGS — {pd.Timestamp.today().date()}  "
          f"(Hurst, Ooi & Pedersen 2017)")
    print(f"  {len(df)} tickers total  |  {n_pos} Composite>0  {n_neg} Composite<=0")
    if not show_all:
        print(f"  Showing Composite>0 only (pass --all to include all tickers)")
    print("=" * 128)
    header = (f"  {'#':<4} {'Ticker':<8} {'Trend':>6} {'Votes':>6} {'Grade':>6}"
              f" {'R_21%':>8} {'R_63%':>8} {'R_252%':>8}"
              f" {'S_21':>7} {'S_63':>7} {'S_252':>7}"
              f" {'Composite':>10} {'SMA Rat':>8}")
    print(header)
    print("  " + "-" * 112)

    for rank, (ticker, row) in enumerate(subset.iterrows(), start=1):
        trend_marker = "✔" if row["Trend"] == 1 else "✖"
        votes = int(row["Votes"])
        grade = str(row["Grade"])
        r21  = f"{row['R_21_pct']:+.1f}"   if not pd.isna(row["R_21_pct"]) else "   n/a"
        r63  = f"{row['R_63_pct']:+.1f}"   if not pd.isna(row["R_63_pct"]) else "   n/a"
        r252 = f"{row['R_252_pct']:+.1f}"  if not pd.isna(row["R_252_pct"]) else "   n/a"
        s21  = f"{row['Score_21']:+.3f}"   if not pd.isna(row["Score_21"]) else "   n/a"
        s63  = f"{row['Score_63']:+.3f}"   if not pd.isna(row["Score_63"]) else "   n/a"
        s252 = f"{row['Score_252']:+.3f}"  if not pd.isna(row["Score_252"]) else "   n/a"
        comp = f"{row['Composite_Score']:+.3f}" if not pd.isna(row["Composite_Score"]) else "   n/a"
        smar = f"{row['SMA_Ratio']:.4f}"   if not pd.isna(row["SMA_Ratio"]) else "   n/a"

        print(f"  {rank:<4} {ticker:<8} {trend_marker:>6} {votes:>6} {grade:>6}"
              f" {r21:>8} {r63:>8} {r252:>8}"
              f" {s21:>7} {s63:>7} {s252:>7}"
              f" {comp:>10} {smar:>8}")

    print()
    if not subset.empty:
        top = subset.index[0]
        print(f"  ★  Strongest: {top}  "
              f"Composite={subset.loc[top,'Composite_Score']:+.3f}, "
              f"Votes={int(subset.loc[top,'Votes'])}, "
              f"R_252={subset.loc[top,'R_252_pct']:+.1f}%\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank portfolio tickers by multi-window TSMOM composite (Hurst et al. 2017)"
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
