"""
Predict current market regime from a trained HMM.

Usage:
    python src/hmm/predict_regime.py
    python src/hmm/predict_regime.py --params-path data/hmm_regime_params.pkl
"""

import argparse
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import hmmlearn.hmm as hmm
import numpy as np
import pandas as pd
import yfinance as yf


# Ticker mapping: short name -> yfinance symbol
TICKER_MAP = {
    "SPY": "SPY",
    "SOX": "^SOX",
    "NDX": "^NDX",
}

ALL_TICKERS = ["SPY", "SOX", "NDX"]


# Portfolio guidance templates per regime
_GUIDANCE: dict[str, dict[str, str]] = {
    "Low-Vol Bull": {
        "state": "Low-Vol Bull",
        "deployment": "Full capital deployment",
        "strategy": "Momentum ideal — low vol confirms conviction",
        "hold_period": "Normal hold periods",
        "caution": "",
    },
    "High-Vol Bull": {
        "state": "High-Vol Bull",
        "deployment": "Full deployment, tighter stops",
        "strategy": "Momentum works but reversion risk elevated",
        "hold_period": "Shorten holds, tighten stops",
        "caution": "Elevated vol suggests late-cycle dynamics",
    },
    "Low-Vol Sideways": {
        "state": "Low-Vol Sideways",
        "deployment": "Selective, reduced exposure",
        "strategy": "Mean-reversion / range trading",
        "hold_period": "Short holds, take profits",
        "caution": "Range likely persists",
    },
    "High-Vol Sideways": {
        "state": "High-Vol Sideways",
        "deployment": "Reduce aggressively, raise cash",
        "strategy": "Wait for breakout",
        "hold_period": "Minimal — avoid chop",
        "caution": "High vol in range precedes breakout or panic",
    },
    "Low-Vol Bear": {
        "state": "Low-Vol Bear",
        "deployment": "Raise cash, reduce positions",
        "strategy": "Defensive / quality factors",
        "hold_period": "Short holds, tight stops",
        "caution": "Don't catch falling knives",
    },
    "High-Vol Bear": {
        "state": "High-Vol Bear",
        "deployment": "Near-minimal deployment",
        "strategy": "Cash is the winning position",
        "hold_period": "No new positions",
        "caution": "Capitulation risk — wait for vol to subside",
    },
}



def _directional(label: str) -> str:
    """Extract the directional component from a 6-state label.

    'Low-Vol Bull' -> 'BULL', 'High-Vol Bear' -> 'BEAR', etc.
    Falls back to the label as-is if no direction is found.
    """
    for direction in ["Bull", "Bear", "Sideways"]:
        if direction in label:
            return direction.upper()
    return label.upper()



def fetch_recent_data(ticker: str = "SPY", lookback_days: int = 60) -> np.ndarray:
    """Fetch recent index + VIX data including vol metrics for prediction.

    Args:
        ticker: Index ticker (SPY, SOX, or NDX).
        lookback_days: Number of recent trading days to use.

    Returns:
        Array of shape (lookback_days, 4) with:
        [log_return, vix_close, vix_log_return, realized_vol].
    """
    yf_ticker = TICKER_MAP[ticker]
    name_lower = ticker.lower()

    end = datetime.now()
    start = end - timedelta(days=max(1, lookback_days * 2))

    index_data = yf.download(yf_ticker, start=start, end=end, progress=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False)

    if index_data.empty or vix.empty:
        raise ValueError(f"Failed to fetch recent {ticker} or VIX data")

    df = pd.DataFrame(index=index_data.index)
    df[f"{name_lower}_close"] = index_data["Close"]
    df["vix_close"] = vix["Close"]
    df = df.dropna()
    df[f"{name_lower}_return"] = np.log(
        df[f"{name_lower}_close"] / df[f"{name_lower}_close"].shift(1)
    )
    df["vix_log_return"] = np.log(
        df["vix_close"] / df["vix_close"].shift(1)
    )
    df["realized_vol"] = (
        df[f"{name_lower}_return"].rolling(window=20).std()
    )
    df = df.dropna()

    recent = df.tail(lookback_days)
    return recent[
        [f"{name_lower}_return", "vix_close", "vix_log_return", "realized_vol"]
    ].values


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
            off_idx = [j for j in range(len(t)) if j != i]
            off_sum = sum(t[i, j] for j in off_idx)
            if off_sum > 0:
                for j in off_idx:
                    t[i, j] += excess * t[i, j] / off_sum
            else:
                for j in off_idx:
                    t[i, j] = excess / (len(t) - 1)
    return t


def compute_forecast(
    model: hmm.GaussianHMM,
    current_probs: np.ndarray,
    horizons: list[int] = None,
) -> dict[int, list[float]]:
    """Compute N-step-ahead state distribution using the transition matrix.

    P(state at t+N) = P(state at t) x A^N

    Args:
        model: Trained GaussianHMM.
        current_probs: Current state probabilities from Forward algorithm.
        horizons: List of trading-day horizons (default: [30, 60, 90]).

    Returns:
        Dict mapping horizon -> list of state probabilities.
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


def predict_regime(
    params_path: str = "data/hmm_regime_params.pkl",
    lookback_days: int = 60,
    recent_observations: Optional[np.ndarray] = None,
    forecast_horizons: list[int] = None,
    ticker: str = "SPY",
) -> dict:
    """Predict current market regime using a trained HMM.

    Args:
        params_path: Path to saved HMM parameters pickle.
        lookback_days: Number of recent trading days to use.
        recent_observations: Optional pre-computed features (n_days, 4).
            If None, fetches from yfinance.
        forecast_horizons: List of forecast horizons in trading days.
        ticker: Index ticker (SPY, SOX, or NDX).

    Returns:
        Dict with:
            ticker: str
            state: str (BULL/BEAR/SIDEWAYS)
            confidence: float
            probabilities: list[float] (one per state)
            persistence: float (self-transition prob)
            state_labels: list[str]
            guidance: dict (regime-specific guidance)
            forecast: dict[int, list[float]]
    """
    params_path_obj = Path(params_path)
    if not params_path_obj.exists():
        raise FileNotFoundError(f"Model parameters not found: {params_path}")

    with open(params_path_obj, "rb") as f:
        params = pickle.load(f)

    model = params["model"]
    scaler = params["scaler"]
    state_labels = params["state_labels"]

    if recent_observations is None:
        recent_observations = fetch_recent_data(ticker=ticker, lookback_days=lookback_days)

    # Ensure we have enough data
    if len(recent_observations) < 10:
        raise ValueError(f"Need at least 10 observations, got {len(recent_observations)}")

    # Standardize using training scaler
    scaled = scaler.transform(recent_observations)

    # Forward algorithm: P(state | observations)
    state_probs = model.predict_proba(scaled)
    # Use the last timestep's probabilities as current state estimate
    current_probs = state_probs[-1]

    # Use the marginal posterior (forward-backward) for the current state.
    # Viterbi (model.predict) finds the most likely global path, which can
    # disagree with the marginal at a single timestep — especially during
    # regime transitions where high self-transition probabilities make
    # the global path slow to react. For point-in-time regime classification
    # the marginal posterior is the correct answer.
    current_state_idx = int(np.argmax(current_probs))

    # State label and confidence
    state_label = state_labels[current_state_idx]
    confidence = float(current_probs[current_state_idx])

    # Persistence (self-transition probability)
    persistence = float(model.transmat_[current_state_idx, current_state_idx])

    # Guidance
    guidance = _GUIDANCE.get(state_label, _GUIDANCE["Low-Vol Sideways"])

    # Forecast
    forecast = compute_forecast(model, current_probs, forecast_horizons)

    return {
        "ticker": ticker,
        "state": state_label,
        "confidence": round(confidence, 4),
        "probabilities": [round(float(p), 4) for p in current_probs],
        "persistence": round(persistence, 4),
        "state_labels": state_labels,
        "guidance": guidance,
        "forecast": forecast,
    }


def print_report(result: dict) -> None:
    """Print the regime report to stdout."""
    ticker = result.get("ticker", "SPY")
    state = result["state"]
    conf = result["confidence"] * 100
    probs = result["probabilities"]
    labels = result["state_labels"]
    persist = result["persistence"]
    guidance = result["guidance"]
    forecast = result["forecast"]

    prob_str = "  |  ".join(
        f"{labels[i]:20s} {probs[i]*100:.0f}%"
        for i in range(len(labels))
    )

    # Expected duration = 1 / (1 - a_ii)
    state_idx = labels.index(state)
    expected_duration = 1.0 / (1.0 - persist) if persist < 1.0 else float("inf")

    print()
    print(f"{'=' * 55}")
    print(f"  HMM Regime Report ({ticker})  —  {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'=' * 55}")
    print()
    print(f"  Regime:  {state} ({conf:.0f}% confidence)")
    print(f"  Probabilities:  {prob_str}")
    print()
    print(f"  Forecast:")
    for horizon in sorted(forecast.keys()):
        fprobs = forecast[horizon]
        fstr = "  |  ".join(
            f"{labels[i]}: {fprobs[i]*100:.0f}%"
            for i in range(len(labels))
        )
        label = f"{horizon}d" if horizon < 365 else f"{horizon/365:.0f}y"
        print(f"    {label:>6}:  {fstr}")
    print()
    print(f"  Persistence:  {persist*100:.0f}% chance same state tomorrow")
    print(f"  Expected duration in current regime:  {expected_duration:.0f} trading days")
    print()
    print(f"  Portfolio guidance:")
    print(f"    → {guidance['deployment']}")
    print(f"    → {guidance['strategy']}")
    print(f"    → {guidance['hold_period']}")
    if guidance['caution']:
        print(f"    ⚠  {guidance['caution']}")
    print()


def _default_params_path(ticker: str) -> str:
    """Default save path for a given ticker."""
    return f"data/hmm_regime_params_{ticker.lower()}.pkl"


def print_comparison_report(results: list[dict]) -> None:
    """Print a side-by-side comparison of all regime results."""
    print()
    print(f"{'=' * 60}")
    print(f"  HMM Regime Comparison  —  {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'=' * 60}")
    print()
    print(f"  {'Index':<8} {'Regime':<12} {'Conf':<8} {'30d Fcast':<24} {'Persist':<8}")
    print(f"  {'─' * 8} {'─' * 12} {'─' * 8} {'─' * 24} {'─' * 8}")

    divergence = []
    for r in results:
        ticker = r["ticker"]
        state = r["state"]
        conf = f"{r['confidence']*100:.0f}%"
        labels = r["state_labels"]
        f30 = r["forecast"].get(30, [])
        f30_state_probs = sorted(
            zip(labels, f30), key=lambda x: x[1], reverse=True
        )[:3]
        f30_str = " ".join(
            f"{l}{p*100:.0f}%"
            for l, p in f30_state_probs
        )
        persist = f"{r['persistence']*100:.0f}%"
        print(f"  {ticker:<8} {state:<12} {conf:<8} {f30_str:<24} {persist:<8}")
        divergence.append(state)

    print()

    # Heuristic: flag if SPY and SOX disagree
    if len(results) >= 2:
        spy_state = _directional(next((r["state"] for r in results if r["ticker"] == "SPY"), ""))
        sox_state = _directional(next((r["state"] for r in results if r["ticker"] == "SOX"), ""))
        ndx_state = _directional(next((r["state"] for r in results if r["ticker"] == "NDX"), ""))

        if spy_state and sox_state:
            if spy_state == sox_state:
                print(f"  ✓ SPY and SOX agree — {spy_state}. Full conviction.")
            else:
                print(f"  ⚠ SPY={spy_state} vs SOX={sox_state} — semi cycle diverging from broad market.")
        if spy_state and ndx_state and spy_state != ndx_state:
            print(f"  ⚠ SPY={spy_state} vs NDX={ndx_state} — tech/growth telling a different story.")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Predict current market regime from trained HMM"
    )
    parser.add_argument(
        "--ticker", default=None, choices=list(TICKER_MAP.keys()),
        help="Index ticker to predict (default: show all)"
    )
    parser.add_argument(
        "--params-path", default=None,
        help="Path to trained model parameters"
    )
    parser.add_argument(
        "--lookback", type=int, default=60,
        help="Number of recent trading days to use (default: 60)"
    )
    args = parser.parse_args()

    try:
        if args.ticker:
            # Single ticker mode
            params_path = args.params_path or _default_params_path(args.ticker)
            result = predict_regime(
                params_path=params_path,
                lookback_days=args.lookback,
                ticker=args.ticker,
            )
            print_report(result)
        else:
            # All tickers mode
            results = []
            for ticker in ALL_TICKERS:
                params_path = _default_params_path(ticker)
                if not Path(params_path).exists():
                    print(f"[SKIP] {ticker} — no model at {params_path}. Run 'make hmm-train-regime' first.")
                    continue
                result = predict_regime(
                    params_path=params_path,
                    lookback_days=args.lookback,
                    ticker=ticker,
                )
                results.append(result)
            if not results:
                print("[ERROR] No trained models found. Run 'make hmm-train-regime' first.", file=sys.stderr)
                sys.exit(1)
            print_comparison_report(results)
            # Also print detailed report for each
            for r in results:
                print_report(r)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()