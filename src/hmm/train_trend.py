"""
Train per-ticker 3-state HMMs for trend quality assessment.

Usage:
    python src/hmm/train_trend.py NVDA
    python src/hmm/train_trend.py --tickers NVDA AMD MU
    python src/hmm/train_trend.py --all
"""

import argparse
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn import hmm


# When --all is used, which tickers to train on
CURRENT_PORTFOLIO = [
    "MU", "GOOG", "CLS", "GOOGL", "AGX", "LQDA", "VICR", "SIMO", "AAMI",
    "DELL", "TER", "STRL", "CRDO", "CIEN", "LITE", "AMKR", "KALU", "BE",
    "CLSK", "IREN", "SNDK", "TE", "TSM", "ESLT", "LRCX", "APH", "AVGO",
    "AMD", "STX", "WDC", "FSLR", "MRVL", "NU", "NVDA",
]


def fetch_returns(ticker: str, years: int = 5) -> np.ndarray:
    """Fetch daily log returns for a ticker from yfinance.

    Args:
        ticker: Stock ticker symbol.
        years: Years of historical data.

    Returns:
        Array of daily log returns, oldest to newest.
    """
    end = datetime.now()
    start = end.replace(year=end.year - years)

    data = yf.download(ticker, start=start, end=end, progress=False)
    if data.empty:
        raise ValueError(f"No data for {ticker}")

    prices = data["Close"].dropna()
    returns = np.log(prices / prices.shift(1)).dropna().values
    return returns


def _label_trend_states(model: hmm.GaussianHMM) -> list[str]:
    """Label states as STRONG_UPTREND, WEAK_UPTREND, SIDEWAYS, etc.

    Sorts states by their mean return (ascending).
    For 3 states: lowest = DOWNTREND/SIDEWAYS, highest = STRONG_UPTREND, middle = WEAK_UPTREND.
    """
    means = model.means_[:, 0]
    sorted_idx = np.argsort(means)
    labels = [""] * len(sorted_idx)

    if len(sorted_idx) >= 3:
        labels[sorted_idx[0]] = "DOWNTREND"
        labels[sorted_idx[-1]] = "STRONG_UPTREND"
        for i in sorted_idx[1:-1]:
            labels[i] = "WEAK_UPTREND"
    else:
        for i, idx in enumerate(sorted_idx):
            labels[idx] = f"STATE_{i}"

    return labels


def train_trend_model(
    ticker: str,
    returns: Optional[np.ndarray] = None,
    save_dir: str = "data/hmm_trend_params",
) -> dict:
    """Train a 3-state HMM on a ticker's returns for trend quality.

    Args:
        ticker: Stock ticker symbol.
        returns: Array of daily log returns. If None, fetches from yfinance.
        save_dir: Directory to save per-ticker model params.

    Returns:
        Dict with 'model', 'state_labels', 'ticker', 'training_date', 'mean_return', 'volatility'.
    """
    if returns is None:
        returns = fetch_returns(ticker)

    if len(returns) < 252:
        raise ValueError(
            f"{ticker}: need at least 252 trading days of data, got {len(returns)}"
        )

    # Standardize returns
    mean = np.mean(returns)
    std = np.std(returns)
    scaled = (returns.reshape(-1, 1) - mean) / (std + 1e-8)

    # Train HMM with diagonal covariance (simpler for single-feature)
    model = hmm.GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=50,
        random_state=42,
    )
    model.fit(scaled)

    state_labels = _label_trend_states(model)

    result = {
        "model": model,
        "state_labels": state_labels,
        "ticker": ticker,
        "training_date": datetime.now().isoformat(),
        "mean_return": float(mean),
        "volatility": float(std),
    }

    # Save per-ticker
    save_path = Path(save_dir) / f"{ticker}.pkl"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        pickle.dump(result, f)

    print(f"  ✓ {ticker}: {state_labels}  (μ={mean:.4f}, σ={std:.4f})")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train per-ticker trend quality HMMs"
    )
    parser.add_argument("tickers", nargs="*", help="Ticker(s) to train")
    parser.add_argument(
        "--all", action="store_true",
        help="Train on all CURRENT_PORTFOLIO tickers"
    )
    parser.add_argument(
        "--save-dir", default="data/hmm_trend_params",
        help="Directory to save per-ticker models (default: data/hmm_trend_params)"
    )
    parser.add_argument(
        "--years", type=int, default=5,
        help="Years of historical data (default: 5)"
    )
    args = parser.parse_args()

    if args.all:
        tickers = CURRENT_PORTFOLIO
    elif args.tickers:
        tickers = args.tickers
    else:
        parser.print_help()
        sys.exit(1)

    # Deduplicate
    tickers = list(dict.fromkeys([t.upper() for t in tickers]))

    print(f"[INFO] Training trend HMMs for {len(tickers)} tickers ({args.years} years)...")
    success = 0
    failed = 0

    for ticker in tickers:
        try:
            returns = fetch_returns(ticker, years=args.years)
            train_trend_model(ticker, returns=returns, save_dir=args.save_dir)
            success += 1
        except Exception as e:
            print(f"  ✗ {ticker}: {e}", file=sys.stderr)
            failed += 1

    print(f"[INFO] Done: {success} trained, {failed} failed")


if __name__ == "__main__":
    main()