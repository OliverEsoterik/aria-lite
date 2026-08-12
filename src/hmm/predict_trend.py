"""
Predict per-ticker trend quality from trained HMMs (multi-horizon features).

Features: rolling returns at 21, 63, and 252 trading days.
States:   DOWNTREND, SIDEWAYS, WEAK_UPTREND, STRONG_UPTREND.

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
import pandas as pd
import yfinance as yf


CURRENT_PORTFOLIO = [
    "MU", "GOOG", "CLS", "GOOGL", "AGX", "LQDA", "VICR", "SIMO", "AAMI",
    "DELL", "TER", "STRL", "CRDO", "CIEN", "LITE", "AMKR", "KALU", "BE",
    "CLSK", "IREN", "SNDK", "TE", "TSM", "ESLT", "LRCX", "APH", "AVGO",
    "AMD", "STX", "WDC", "FSLR", "MRVL", "NU", "NVDA",
]

# State score mapping for grade calculation
_STATE_SCORES = {
    "STRONG_UPTREND": 1.0,
    "WEAK_UPTREND": 0.66,
    "SIDEWAYS": 0.33,
    "DOWNTREND": 0.0,
}


def fetch_recent_returns(ticker: str, lookback_days: int = 252) -> np.ndarray:
    """Fetch recent prices and compute multi-horizon rolling returns.

    Returns:
        Array of shape (n_days, 3) with [R_21, R_63, R_252].
        Oldest to newest. At least 252 days needed for the 252-day window.
    """
    end = datetime.now()
    start = end - timedelta(days=lookback_days * 2)

    data = yf.download(ticker, start=start, end=end, progress=False)
    if data.empty:
        raise ValueError(f"No recent data for {ticker}")

    prices = data["Close"].iloc[:, 0].dropna()
    r21 = prices.pct_change(21)
    r63 = prices.pct_change(63)
    r252 = prices.pct_change(252)

    df = pd.DataFrame({"R_21": r21, "R_63": r63, "R_252": r252}).dropna()
    # Take the most recent `lookback_days` (or as many as available)
    recent = df.tail(min(lookback_days, len(df)))
    return recent.values


def _regularize_transmat(transmat: np.ndarray, max_self: float = 0.99) -> np.ndarray:
    """Regularize transition matrix so no state is perfectly absorbing.

    Baum-Welch can converge to boundary solutions where a state's
    self-transition probability is exactly 1.0 (absorbing state).
    This makes matrix_power produce degenerate forecasts. Clip
    diagonals to a maximum and redistribute excess to off-diagonals.
    """
    t = transmat.copy()
    for i in range(len(t)):
        if t[i, i] > max_self:
            excess = t[i, i] - max_self
            t[i, i] = max_self
            # Distribute excess proportionally to off-diagonals
            off_idx = [j for j in range(len(t)) if j != i]
            off_sum = sum(t[i, j] for j in off_idx)
            if off_sum > 0:
                for j in off_idx:
                    t[i, j] += excess * t[i, j] / off_sum
            else:
                # Uniform spread if no off-diagonals exist
                for j in off_idx:
                    t[i, j] = excess / (len(t) - 1)
    return t


def compute_forecast(
    model: "hmm.GaussianHMM",
    current_probs: np.ndarray,
    horizons: list[int] = None,
) -> dict[int, list[float]]:
    """Compute N-step-ahead state distribution using the transition matrix.

    The transition matrix is regularized before forecasting to prevent
    degenerate results from absorbing states.
    """
    if horizons is None:
        horizons = [30, 60, 90]
    transmat = _regularize_transmat(model.transmat_)
    forecast = {}
    for step in horizons:
        power = np.linalg.matrix_power(transmat, step)
        future = current_probs @ power
        forecast[step] = [round(float(p), 4) for p in future]
    return forecast


def compute_quality_grade(score: float) -> str:
    """Map composite score (0-1) to letter grade."""
    if score >= 0.75:
        return "A"
    elif score >= 0.55:
        return "B"
    elif score >= 0.35:
        return "C"
    elif score >= 0.15:
        return "D"
    else:
        return "F"


def predict_trend(
    ticker: str,
    params_dir: str = "data/hmm_trend_params",
    lookback_days: int = 252,
    recent_returns: Optional[np.ndarray] = None,
) -> dict:
    """Predict trend quality for a single ticker.

    Args:
        ticker: Stock ticker symbol.
        params_dir: Directory containing per-ticker HMM params.
        lookback_days: Number of recent trading days for features.
        recent_returns: Optional pre-computed (n, 3) array [R_21, R_63, R_252].
            If None, fetches from yfinance.

    Returns:
        Dict with ticker, state, confidence, probabilities, state_labels,
        forecast, grade, grade_score, returns dict.
    """
    params_path = Path(params_dir) / f"{ticker}.pkl"
    if not params_path.exists():
        raise FileNotFoundError(f"No trained model for {ticker} at {params_path}")

    with open(params_path, "rb") as f:
        params = pickle.load(f)

    model = params["model"]
    scaler = params["scaler"]
    state_labels = params["state_labels"]

    if recent_returns is None:
        recent_returns = fetch_recent_returns(ticker, lookback_days=lookback_days)

    if len(recent_returns) < 10:
        raise ValueError(f"{ticker}: need at least 10 observations, got {len(recent_returns)}")

    # Standardize using training scaler
    scaled = scaler.transform(recent_returns)

    # Forward algorithm
    state_probs = model.predict_proba(scaled)
    current_probs = state_probs[-1]

    # Viterbi
    hidden_states = model.predict(scaled)
    current_state_idx = int(hidden_states[-1])

    state_label = state_labels[current_state_idx]
    confidence = float(current_probs[current_state_idx])

    # Forecast
    forecast = compute_forecast(model, current_probs, [30, 60, 90])

    # Quality grade: state strength + confidence
    # Forecast is excluded because transition matrices can have
    # near-1.0 self-transitions, producing degenerate forecasts.
    state_score = _STATE_SCORES.get(state_label, 0.33)
    grade_score = state_score * 0.50 + confidence * 0.50
    grade = compute_quality_grade(grade_score)

    # Current return values (last row)
    last_returns = recent_returns[-1]

    return {
        "ticker": ticker,
        "state": state_label,
        "confidence": round(confidence, 4),
        "probabilities": [round(float(p), 4) for p in current_probs],
        "state_labels": state_labels,
        "forecast": forecast,
        "grade": grade,
        "grade_score": round(grade_score, 4),
        "returns": {
            "R_21": round(float(last_returns[0] * 100), 2),
            "R_63": round(float(last_returns[1] * 100), 2),
            "R_252": round(float(last_returns[2] * 100), 2),
        },
    }


def format_trend_report(results: List[dict]) -> str:
    """Format trend prediction results as a human-readable report."""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  Trend Quality Report  —  {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("=" * 70)

    if len(results) == 1:
        r = results[0]
        lines.append("")
        lines.append(f"  Ticker:  {r['ticker']}")
        lines.append(f"  State:   {r['state']} ({r['confidence']*100:.0f}% confidence)")
        lines.append("")
        lines.append("  Returns:")
        lines.append(f"    1-month:  {r['returns']['R_21']:+.2f}%")
        lines.append(f"    3-month:  {r['returns']['R_63']:+.2f}%")
        lines.append(f"    12-month: {r['returns']['R_252']:+.2f}%")
        lines.append("")
        lines.append("  Forecast:")
        for horizon in sorted(r["forecast"].keys()):
            fprobs = r["forecast"][horizon]
            flabels = r["state_labels"]
            fstr = "  |  ".join(
                f"{flabels[i]}: {fprobs[i]*100:.0f}%"
                for i in range(len(flabels))
            )
            label = f"{horizon}d"
            lines.append(f"    {label:>6}:  {fstr}")
        lines.append("")
        lines.append(f"  Quality grade:  {r['grade']} (score: {r['grade_score']:.2f})")
        lines.append("")
    else:
        # Table format for comparison
        lines.append("")
        header = (
            f"  {'Ticker':<8} {'State':<18} {'Conf':>6} {'R_21':>7} "
            f"{'R_63':>7} {'R_252':>8} {'Grade':>6}"
        )
        lines.append(header)
        lines.append("  " + "-" * 62)
        for r in results:
            lines.append(
                f"  {r['ticker']:<8} {r['state']:<18} "
                f"{r['confidence']*100:>5.0f}% "
                f"{r['returns']['R_21']:>+6.1f}% "
                f"{r['returns']['R_63']:>+6.1f}% "
                f"{r['returns']['R_252']:>+7.1f}% "
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
        help="Directory with per-ticker model params"
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

    if len(results) == 1 or not args.compare:
        for r in results:
            print(format_trend_report([r]))
    else:
        print(format_trend_report(results))


if __name__ == "__main__":
    main()