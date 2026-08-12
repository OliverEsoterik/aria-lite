"""
Train per-ticker 4-state HMMs on multi-horizon returns (21, 63, 252 days).

Features are rolling returns at 1-month, 3-month, and 12-month horizons —
the same windows from the academic trend-following literature (Moskowitz,
Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017).

Usage:
    python src/hmm/train_trend.py NVDA
    python src/hmm/train_trend.py NVDA AMD MU
    python src/hmm/train_trend.py --all
"""

import argparse
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler


CURRENT_PORTFOLIO = [
    "MU", "GOOG", "CLS", "GOOGL", "AGX", "LQDA", "VICR", "SIMO", "AAMI",
    "DELL", "TER", "STRL", "CRDO", "CIEN", "LITE", "AMKR", "KALU", "BE",
    "CLSK", "IREN", "SNDK", "TE", "TSM", "ESLT", "LRCX", "APH", "AVGO",
    "AMD", "STX", "WDC", "FSLR", "MRVL", "NU", "NVDA",
]


def fetch_returns(ticker: str, years: int = 5) -> np.ndarray:
    """Fetch daily close prices and compute multi-horizon rolling returns.

    Returns:
        Array of shape (n_days, 3) with columns [R_21, R_63, R_252].
        Oldest to newest. NaN rows from rolling window computation are dropped.
    """
    end = datetime.now()
    start = end - timedelta(days=years * 365 + 252)  # extra buffer for rolling windows

    data = yf.download(ticker, start=start, end=end, progress=False)
    if data.empty:
        raise ValueError(f"No data for {ticker}")

    prices = data["Close"].iloc[:, 0].dropna()
    # Rolling returns
    r21 = prices.pct_change(21).dropna()
    r63 = prices.pct_change(63).dropna()
    r252 = prices.pct_change(252).dropna()

    # Align on common index
    df = pd.DataFrame({"R_21": r21, "R_63": r63, "R_252": r252}).dropna()
    if len(df) < 252:
        raise ValueError(f"{ticker}: need at least 252 valid observations after computing rolling returns, got {len(df)}")

    return df.values


def _label_trend_states(model: hmm.GaussianHMM) -> list[str]:
    """Label 4 states by their mean 252-day return (long-term trend).

    Sorted by ascending mean of the R_252 feature (index 2).
    """
    means = model.means_
    # Sort by the 252-day return mean (column 2)
    sorted_idx = np.argsort(means[:, 2])

    labels = [""] * len(sorted_idx)
    n = len(sorted_idx)

    if n == 4:
        labels[sorted_idx[0]] = "DOWNTREND"
        labels[sorted_idx[1]] = "SIDEWAYS"
        labels[sorted_idx[2]] = "WEAK_UPTREND"
        labels[sorted_idx[3]] = "STRONG_UPTREND"
    else:
        # Fallback for non-4-state models
        for i, idx in enumerate(sorted_idx):
            labels[idx] = f"STATE_{i}"

    return labels


def train_trend_model(
    ticker: str,
    returns: Optional[np.ndarray] = None,
    save_dir: str = "data/hmm_trend_params",
) -> dict:
    """Train a 4-state HMM on multi-horizon returns for trend quality.

    Args:
        ticker: Stock ticker symbol.
        returns: Array of shape (n_days, 3) with [R_21, R_63, R_252].
            If None, fetches from yfinance.
        save_dir: Directory to save per-ticker model params.

    Returns:
        Dict with 'model', 'scaler', 'state_labels', 'ticker',
        'training_date', 'feature_names'.
    """
    if returns is None:
        returns = fetch_returns(ticker)

    if len(returns) < 252:
        raise ValueError(
            f"{ticker}: need at least 252 valid observations, got {len(returns)}"
        )

    # Standardize features
    scaler = StandardScaler()
    scaled = scaler.fit_transform(returns)

    # Train 4-state HMM with full covariance
    model = hmm.GaussianHMM(
        n_components=4,
        covariance_type="full",
        n_iter=100,
        random_state=42,
    )
    model.fit(scaled)
    best_score = model.score(scaled)

    # Multiple restarts
    for i in range(4):
        trial = hmm.GaussianHMM(
            n_components=4,
            covariance_type="full",
            n_iter=100,
            random_state=42 + i + 1,
        )
        trial.fit(scaled)
        score = trial.score(scaled)
        if score > best_score:
            model = trial
            best_score = score

    state_labels = _label_trend_states(model)

    result = {
        "model": model,
        "scaler": scaler,
        "state_labels": state_labels,
        "ticker": ticker,
        "training_date": datetime.now().isoformat(),
        "feature_names": ["R_21", "R_63", "R_252"],
    }

    # Save
    save_path = Path(save_dir) / f"{ticker}.pkl"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        pickle.dump(result, f)

    print(f"  \u2713 {ticker}: {state_labels}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train per-ticker trend quality HMMs (multi-horizon returns)"
    )
    parser.add_argument("tickers", nargs="*", help="Ticker(s) to train")
    parser.add_argument(
        "--all", action="store_true",
        help="Train on all CURRENT_PORTFOLIO tickers"
    )
    parser.add_argument(
        "--save-dir", default="data/hmm_trend_params",
        help="Directory to save per-ticker models"
    )
    args = parser.parse_args()

    if args.all:
        tickers = CURRENT_PORTFOLIO
    elif args.tickers:
        tickers = args.tickers
    else:
        parser.print_help()
        sys.exit(1)

    tickers = list(dict.fromkeys([t.upper() for t in tickers]))

    print(f"[INFO] Training trend HMMs for {len(tickers)} tickers...")
    success = 0
    failed = 0

    for ticker in tickers:
        try:
            returns = fetch_returns(ticker)
            train_trend_model(ticker, returns=returns, save_dir=args.save_dir)
            success += 1
        except Exception as e:
            print(f"  \u2717 {ticker}: {e}", file=sys.stderr)
            failed += 1

    print(f"[INFO] Done: {success} trained, {failed} failed")


if __name__ == "__main__":
    main()