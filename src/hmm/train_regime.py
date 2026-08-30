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
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist
from sklearn.preprocessing import StandardScaler


TICKER_MAP = {
    "SPY": "SPY",
    "SOX": "^SOX",
    "NDX": "^NDX",
}


def fetch_training_data(ticker: str = "SPY", years: int = 10) -> np.ndarray:
    """Fetch daily returns, VIX levels, VIX log-returns, and realized vol.

    Args:
        ticker: Index ticker (SPY, SOX, or NDX).
        years: Years of historical data.

    Returns:
        Array of shape (n_days, 4) with columns:
        [<ticker>_log_return, vix_close, vix_log_return, realized_vol].
    """
    yf_ticker = TICKER_MAP[ticker]
    name_lower = ticker.lower()

    end = datetime.now()
    start = end.replace(year=end.year - years)

    index_data = yf.download(yf_ticker, start=start, end=end, progress=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False)

    if index_data.empty or vix.empty:
        raise ValueError(f"Failed to fetch {ticker} or VIX data from yfinance")

    # Align on date index
    df = pd.DataFrame(index=index_data.index)
    df[f"{name_lower}_close"] = index_data["Close"]
    df["vix_close"] = vix["Close"]
    df = df.dropna()

    # Log returns
    df[f"{name_lower}_return"] = np.log(
        df[f"{name_lower}_close"] / df[f"{name_lower}_close"].shift(1)
    )
    df["vix_log_return"] = np.log(
        df["vix_close"] / df["vix_close"].shift(1)
    )
    # 20-day rolling realized volatility of daily log returns
    df["realized_vol"] = (
        df[f"{name_lower}_return"].rolling(window=20).std()
    )
    df = df.dropna()

    return df[
        [f"{name_lower}_return", "vix_close", "vix_log_return", "realized_vol"]
    ].values


# Prototype mean vectors in standardized feature space.
# Order: [log_return, vix_close, vix_log_return, realized_vol]
# Each row describes the expected signature of one regime.
_PROTOTYPES = np.array([
    [ 0.8, -0.5, -0.5, -0.7],   # Low-Vol Bull: high return, low VIX, low vol
    [ 0.5,  0.0,  0.0,  0.7],   # High-Vol Bull: positive return, elevated vol
    [ 0.0, -0.3,  0.0, -0.3],   # Low-Vol Sideways: flat return, quiet
    [ 0.0,  0.5,  0.0,  0.5],   # High-Vol Sideways: flat return, choppy
    [-0.5,  0.3,  0.5,  0.3],   # Low-Vol Bear: negative return, moderate vol
    [-0.8,  0.8,  0.7,  0.7],   # High-Vol Bear: strongly negative, high vol
])

_REGIME_LABELS = [
    "Low-Vol Bull",
    "High-Vol Bull",
    "Low-Vol Sideways",
    "High-Vol Sideways",
    "Low-Vol Bear",
    "High-Vol Bear",
]


def _assign_regime_labels(model: hmm.GaussianHMM) -> list[str]:
    """Assign interpretable regime labels via Hungarian prototype matching.

    Computes pairwise Euclidean distances between the 6 learned emission
    means and 6 prototype vectors, then runs linear sum assignment to find
    the optimal 1-to-1 mapping. This is deterministic across retraining
    runs — same means_ always produces same labels.

    Args:
        model: Fitted GaussianHMM with means_ attribute of shape (6, n_features).

    Returns:
        List of 6 label strings, index-aligned with model.means_.

    Raises:
        ValueError: If model has != 6 components.
    """
    if model.n_components != 6:
        raise ValueError(
            f"Expected 6 components for regime labeling, got {model.n_components}"
        )

    cost = cdist(model.means_, _PROTOTYPES, metric="euclidean")
    row_idx, col_idx = linear_sum_assignment(cost)

    labels = [""] * len(model.means_)
    for learned_idx, proto_idx in zip(row_idx, col_idx):
        labels[learned_idx] = _REGIME_LABELS[proto_idx]

    return labels


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
    ticker: str = "SPY",
) -> dict:
    """Train a Gaussian HMM on market data and save parameters.

    Args:
        features: Array of shape (n_days, n_features). If None, fetches from yfinance.
        save_path: Where to save the trained model pickle.
        n_states: Number of hidden states (default: 3).
        n_iter: EM iterations per restart.
        n_restarts: Random restarts to avoid local optima.
        ticker: Index ticker (SPY, SOX, or NDX).

    Returns:
        Dict with 'model', 'scaler', 'state_labels', 'feature_names', 'training_date'.
    """
    name_lower = ticker.lower()

    if features is None:
        print(f"[INFO] Fetching {ticker} training data from yfinance...")
        features = fetch_training_data(ticker=ticker, years=10)

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
        "feature_names": [f"{name_lower}_log_return", "vix_close", "vix_log_return", "realized_vol"],
        "training_date": datetime.now().isoformat(),
        "ticker": ticker,
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
        description="Train a 3-state HMM on an index + VIX for market regime detection"
    )
    parser.add_argument(
        "--ticker", default="SPY", choices=list(TICKER_MAP.keys()),
        help="Index ticker to train on (default: SPY)"
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

    print(f"[INFO] Fetching {args.years} years of {args.ticker} + VIX data...")
    features = fetch_training_data(ticker=args.ticker, years=args.years)

    train_regime_model(
        features=features,
        save_path=args.save_path,
        n_states=args.states,
        ticker=args.ticker,
    )


if __name__ == "__main__":
    main()