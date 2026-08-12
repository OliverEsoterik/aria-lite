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


# Portfolio guidance templates per regime
_GUIDANCE = {
    "BULL": {
        "state": "BULL",
        "deployment": "Full capital deployment",
        "strategy": "Momentum strategies favored",
        "hold_period": "Normal hold periods",
        "caution": "Monitor for signs of exhaustion",
    },
    "BEAR": {
        "state": "BEAR",
        "deployment": "Raise cash, reduce position sizes",
        "strategy": "Quality/defensive factors over raw momentum",
        "hold_period": "Shorten hold periods, tighten stops",
        "caution": "Avoid catching falling knives",
    },
    "SIDEWAYS": {
        "state": "SIDEWAYS",
        "deployment": "Moderate deployment, selective positions",
        "strategy": "Fundamentals over momentum",
        "hold_period": "Reduce hold periods, take profits faster",
        "caution": "Range-bound — mean reversion risk elevated",
    },
}


def fetch_recent_data(lookback_days: int = 60) -> np.ndarray:
    """Fetch recent SPY + VIX data for prediction.

    Returns:
        Array of shape (lookback_days, 2) with [log_return, vix_close].
    """
    end = datetime.now()
    start = end - timedelta(days=max(1, lookback_days * 2))

    spy = yf.download("SPY", start=start, end=end, progress=False)
    vix = yf.download("VIX", start=start, end=end, progress=False)

    if spy.empty or vix.empty:
        raise ValueError("Failed to fetch recent SPY or VIX data")

    df = pd.DataFrame(index=spy.index)
    df["spy_close"] = spy["Close"]
    df["vix_close"] = vix["Close"]
    df = df.dropna()
    df["spy_return"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
    df = df.dropna()

    # Take the most recent `lookback_days` days
    recent = df.tail(lookback_days)
    return recent[["spy_return", "vix_close"]].values


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

    transmat = model.transmat_
    forecast = {}
    for step in horizons:
        # A^step
        power = np.linalg.matrix_power(transmat, step)
        # P(t+N) = P(t) @ A^N
        future = current_probs @ power
        forecast[step] = [round(float(p), 4) for p in future]

    return forecast


def predict_regime(
    params_path: str = "data/hmm_regime_params.pkl",
    lookback_days: int = 60,
    recent_observations: Optional[np.ndarray] = None,
    forecast_horizons: list[int] = None,
) -> dict:
    """Predict current market regime using a trained HMM.

    Args:
        params_path: Path to saved HMM parameters pickle.
        lookback_days: Number of recent trading days to use.
        recent_observations: Optional pre-computed features (n_days, 2).
            If None, fetches from yfinance.

    Returns:
        Dict with:
            state: str (BULL/BEAR/SIDEWAYS)
            confidence: float
            probabilities: list[float] (one per state)
            persistence: float (self-transition prob)
            state_labels: list[str]
            guidance: dict (regime-specific guidance)
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
        recent_observations = fetch_recent_data(lookback_days=lookback_days)

    # Ensure we have enough data
    if len(recent_observations) < 10:
        raise ValueError(f"Need at least 10 observations, got {len(recent_observations)}")

    # Standardize using training scaler
    scaled = scaler.transform(recent_observations)

    # Forward algorithm: P(state | observations)
    state_probs = model.predict_proba(scaled)
    # Use the last timestep's probabilities as current state estimate
    current_probs = state_probs[-1]

    # Viterbi: most likely state sequence
    hidden_states = model.predict(scaled)
    current_state_idx = hidden_states[-1]

    # State label and confidence
    state_label = state_labels[current_state_idx]
    confidence = float(current_probs[current_state_idx])

    # Persistence (self-transition probability)
    persistence = float(model.transmat_[current_state_idx, current_state_idx])

    # Guidance
    guidance = _GUIDANCE.get(state_label, _GUIDANCE["SIDEWAYS"])

    # Forecast
    forecast = compute_forecast(model, current_probs, forecast_horizons)

    return {
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
    state = result["state"]
    conf = result["confidence"] * 100
    probs = result["probabilities"]
    labels = result["state_labels"]
    persist = result["persistence"]
    guidance = result["guidance"]
    forecast = result["forecast"]

    prob_str = "  |  ".join(
        f"{labels[i]}: {probs[i]*100:.0f}%"
        for i in range(len(labels))
    )

    # Expected duration = 1 / (1 - a_ii)
    state_idx = labels.index(state)
    expected_duration = 1.0 / (1.0 - persist) if persist < 1.0 else float("inf")

    print()
    print(f"{'=' * 55}")
    print(f"  HMM Regime Report  —  {datetime.now().strftime('%Y-%m-%d')}")
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Predict current market regime from trained HMM"
    )
    parser.add_argument(
        "--params-path", default="data/hmm_regime_params.pkl",
        help="Path to trained model parameters"
    )
    parser.add_argument(
        "--lookback", type=int, default=60,
        help="Number of recent trading days to use (default: 60)"
    )
    args = parser.parse_args()

    try:
        result = predict_regime(
            params_path=args.params_path,
            lookback_days=args.lookback,
        )
        print_report(result)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()