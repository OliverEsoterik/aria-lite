"""
Predict per-ticker trend quality from trained HMMs.

Usage:
    python src/hmm/predict_trend.py NVDA
    python src/hmm/predict_trend.py NVDA AMD MU --compare
    python src/hmm/predict_trend.py --all
"""

import argparse
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np
import yfinance as yf


CURRENT_PORTFOLIO = [
    "MU", "GOOG", "CLS", "GOOGL", "AGX", "LQDA", "VICR", "SIMO", "AAMI",
    "DELL", "TER", "STRL", "CRDO", "CIEN", "LITE", "AMKR", "KALU", "BE",
    "CLSK", "IREN", "SNDK", "TE", "TSM", "ESLT", "LRCX", "APH", "AVGO",
    "AMD", "STX", "WDC", "FSLR", "MRVL", "NU", "NVDA",
]


def fetch_recent_returns(ticker: str, lookback_days: int = 60) -> np.ndarray:
    """Fetch recent daily returns for a ticker from yfinance.

    Returns:
        Array of daily log returns, oldest to newest.
    """
    end = datetime.now()
    start = end - timedelta(days=lookback_days * 2)  # buffer

    data = yf.download(ticker, start=start, end=end, progress=False)
    if data.empty:
        raise ValueError(f"No recent data for {ticker}")

    prices = data["Close"].dropna().tail(lookback_days)
    returns = np.log(prices / prices.shift(1)).dropna().values
    return returns


def compute_quality_grade(score: float) -> str:
    """Map composite quality score (0-4) to letter grade."""
    if score >= 3.5:
        return "A"
    elif score >= 2.5:
        return "B"
    elif score >= 1.5:
        return "C"
    elif score >= 0.5:
        return "D"
    else:
        return "F"


def predict_trend(
    ticker: str,
    params_dir: str = "data/hmm_trend_params",
    lookback_days: int = 60,
    recent_returns: Optional[np.ndarray] = None,
) -> dict:
    """Predict trend quality for a single ticker.

    Args:
        ticker: Stock ticker symbol.
        params_dir: Directory containing per-ticker HMM params.
        lookback_days: Number of recent trading days to use.
        recent_returns: Optional pre-computed returns. If None, fetches from yfinance.

    Returns:
        Dict with ticker, state, confidence, persistence, trend_age, grade,
        state_labels, probabilities, mean_return, volatility.
    """
    params_path = Path(params_dir) / f"{ticker}.pkl"
    if not params_path.exists():
        raise FileNotFoundError(f"No trained model for {ticker} at {params_path}")

    with open(params_path, "rb") as f:
        params = pickle.load(f)

    model = params["model"]
    state_labels = params["state_labels"]
    train_mean = params["mean_return"]
    train_std = params["volatility"]

    if recent_returns is None:
        recent_returns = fetch_recent_returns(ticker, lookback_days=lookback_days)

    if len(recent_returns) < 10:
        raise ValueError(f"{ticker}: need at least 10 recent observations, got {len(recent_returns)}")

    # Standardize using training statistics
    scaled = (recent_returns.reshape(-1, 1) - train_mean) / (train_std + 1e-8)

    # Forward algorithm
    state_probs = model.predict_proba(scaled)
    current_probs = state_probs[-1]

    # Viterbi
    hidden_states = model.predict(scaled)
    current_state_idx = int(hidden_states[-1])

    state_label = state_labels[current_state_idx]
    confidence = float(current_probs[current_state_idx])

    # Persistence
    persistence = float(model.transmat_[current_state_idx, current_state_idx])

    # Trend age: count consecutive days in current state at end of sequence
    trend_age = 0
    for s in reversed(hidden_states):
        if s == current_state_idx:
            trend_age += 1
        else:
            break

    # Quality grade
    grade_score = (
        confidence * 0.30
        + persistence * 0.30
        + (1.0 / (float(model.covars_[current_state_idx].flatten()[0]) + 1e-6) * 0.20)
        + min(trend_age / 252.0, 1.0) * 0.20
    )
    # Normalize grade_score to roughly 0-4 range
    grade_score = min(grade_score * 2.0, 4.0)
    grade = compute_quality_grade(grade_score)

    return {
        "ticker": ticker,
        "state": state_label,
        "confidence": round(confidence, 4),
        "probabilities": [round(float(p), 4) for p in current_probs],
        "persistence": round(persistence, 4),
        "trend_age": trend_age,
        "grade": grade,
        "grade_score": round(grade_score, 2),
        "state_labels": state_labels,
        "mean_return": round(float(recent_returns.mean()), 6),
        "volatility": round(float(recent_returns.std()), 6),
    }


def format_trend_report(results: List[dict]) -> str:
    """Format trend prediction results as a human-readable report.

    Args:
        results: List of result dicts from predict_trend().

    Returns:
        Multi-line string report.
    """
    lines = []
    lines.append("")
    lines.append("=" * 66)
    lines.append(f"  Trend Quality Report  —  {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("=" * 66)

    if len(results) == 1:
        r = results[0]
        lines.append("")
        lines.append(f"  Ticker:  {r['ticker']}")
        lines.append(f"  State:   {r['state']} ({r['confidence']*100:.0f}% confidence)")
        lines.append(f"  Mean daily return: {r['mean_return']:+.4f}")
        lines.append(f"  Volatility:        {r['volatility']:.4f}")
        lines.append(f"  Trend age:         {r['trend_age']} trading days")
        lines.append(f"  Persistence:       {r['persistence']*100:.0f}% chance same state tomorrow")
        lines.append(f"  Quality grade:     {r['grade']} (score: {r['grade_score']})")
        lines.append("")
    else:
        # Table format for comparison
        lines.append("")
        header = f"  {'Ticker':<8} {'State':<18} {'Conf':>6} {'Age':>5} {'Persist':>7} {'Grade':>6}"
        lines.append(header)
        lines.append("  " + "-" * 58)
        for r in results:
            lines.append(
                f"  {r['ticker']:<8} {r['state']:<18} "
                f"{r['confidence']*100:>5.0f}% "
                f"{r['trend_age']:>4d}d "
                f"{r['persistence']*100:>5.0f}% "
                f"{r['grade']:>6}"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Predict per-ticker trend quality from trained HMMs"
    )
    parser.add_argument("tickers", nargs="*", help="Ticker(s) to analyze")
    parser.add_argument(
        "--all", action="store_true",
        help="Analyze all CURRENT_PORTFOLIO tickers"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Show comparison table when multiple tickers"
    )
    parser.add_argument(
        "--params-dir", default="data/hmm_trend_params",
        help="Directory with per-ticker model params (default: data/hmm_trend_params)"
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

    results = []
    for ticker in tickers:
        try:
            result = predict_trend(ticker, params_dir=args.params_dir)
            results.append(result)
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            continue

    if not results:
        print("[ERROR] No predictions could be made", file=sys.stderr)
        sys.exit(1)

    # Single ticker: always full report. Multiple: compare table only with --compare
    if len(results) == 1 or not args.compare:
        for r in results:
            print(format_trend_report([r]))
    else:
        print(format_trend_report(results))


if __name__ == "__main__":
    main()