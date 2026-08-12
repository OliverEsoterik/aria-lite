"""
Train a 3-state Gaussian HMM on SPY returns + VIX to detect market regimes.

Usage:
    python src/hmm/train_regime.py
    python src/hmm/train_regime.py --save-path data/hmm_regime_params.pkl
    python src/hmm/train_regime.py --years 15 --states 4
"""

import argparse
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler


def fetch_training_data(years: int = 10) -> np.ndarray:
    """Fetch SPY daily returns and VIX levels from yfinance.

    Returns:
        Array of shape (n_days, 2) with columns [SPY_log_return, VIX_close].
    """
    end = datetime.now()
    start = end.replace(year=end.year - years)

    spy = yf.download("SPY", start=start, end=end, progress=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False)

    if spy.empty or vix.empty:
        raise ValueError("Failed to fetch SPY or VIX data from yfinance")

    # Align on date index
    df = pd.DataFrame(index=spy.index)
    df["spy_close"] = spy["Close"]
    df["vix_close"] = vix["Close"]
    df = df.dropna()

    # Log returns
    df["spy_return"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
    df = df.dropna()

    features = df[["spy_return", "vix_close"]].values
    return features


def _label_states(model: hmm.GaussianHMM) -> list[str]:
    """Label HMM states as Bull, Bear, or Sideways based on mean return and VIX.

    Uses the emission means: lower return + higher VIX = Bear,
    higher return + lower VIX = Bull, middle = Sideways.
    """
    means = model.means_
    # Sort states by mean return (ascending)
    return_means = means[:, 0]
    sorted_idx = np.argsort(return_means)

    labels = [""] * len(sorted_idx)
    # Lowest return state = Bear, highest = Bull, rest = Sideways
    if len(sorted_idx) >= 3:
        labels[sorted_idx[0]] = "BEAR"
        labels[sorted_idx[-1]] = "BULL"
        for i in sorted_idx[1:-1]:
            labels[i] = "SIDEWAYS"
    else:
        for i, idx in enumerate(sorted_idx):
            labels[idx] = f"STATE_{i}"

    return labels


def train_regime_model(
    features: Optional[np.ndarray] = None,
    save_path: str = "data/hmm_regime_params.pkl",
    n_states: int = 3,
    n_iter: int = 100,
    n_restarts: int = 5,
) -> dict:
    """Train a Gaussian HMM on market data and save parameters.

    Args:
        features: Array of shape (n_days, n_features). If None, fetches from yfinance.
        save_path: Where to save the trained model pickle.
        n_states: Number of hidden states (default: 3).
        n_iter: EM iterations per restart.
        n_restarts: Random restarts to avoid local optima.

    Returns:
        Dict with 'model', 'scaler', 'state_labels', 'feature_names', 'training_date'.
    """
    if features is None:
        print("[INFO] Fetching training data from yfinance...")
        features = fetch_training_data(years=10)

    # Standardize features
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    # Train HMM
    print(f"[INFO] Training {n_states}-state HMM ({n_restarts} restarts, {n_iter} iterations)...")
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=n_iter,
        random_state=42,
        init_params="stmc",
        params="stmc",
    )
    model.fit(scaled)
    best_score = model.score(scaled)

    # Multiple restarts: keep the best model
    for i in range(n_restarts - 1):
        trial = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=n_iter,
            random_state=42 + i + 1,
            init_params="stmc",
            params="stmc",
        )
        trial.fit(scaled)
        score = trial.score(scaled)
        if score > best_score:
            model = trial
            best_score = score

    # Label states post-hoc
    state_labels = _label_states(model)

    result = {
        "model": model,
        "scaler": scaler,
        "state_labels": state_labels,
        "feature_names": ["spy_log_return", "vix_close"],
        "training_date": datetime.now().isoformat(),
    }

    # Save
    save_path_obj = Path(save_path)
    save_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path_obj, "wb") as f:
        pickle.dump(result, f)

    print(f"[INFO] Model saved to {save_path}")
    print(f"[INFO] State labels: {state_labels}")
    print(f"[INFO] Transition matrix:\n{model.transmat_.round(3)}")
    print(f"[INFO] Means:\n{model.means_.round(4)}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a 3-state HMM on SPY+VIX for market regime detection"
    )
    parser.add_argument(
        "--save-path", default="data/hmm_regime_params.pkl",
        help="Path to save trained model parameters (default: data/hmm_regime_params.pkl)"
    )
    parser.add_argument(
        "--years", type=int, default=10,
        help="Years of historical data for training (default: 10)"
    )
    parser.add_argument(
        "--states", type=int, default=3,
        help="Number of hidden states (default: 3)"
    )
    args = parser.parse_args()

    print(f"[INFO] Fetching {args.years} years of SPY + VIX data...")
    features = fetch_training_data(years=args.years)

    train_regime_model(
        features=features,
        save_path=args.save_path,
        n_states=args.states,
    )


if __name__ == "__main__":
    main()