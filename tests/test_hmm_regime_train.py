"""Tests for market regime HMM training."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from src.hmm.train_regime import train_regime_model


def test_train_regime_synthetic_data():
    """Should train on synthetic 3-regime data and produce expected output."""
    # Generate synthetic data: 3 regimes with distinct means
    np.random.seed(42)
    n = 300
    # Regime 0 (bull): mean +0.001, low vol
    # Regime 1 (bear): mean -0.002, high vol
    # Regime 2 (sideways): mean 0.0, moderate vol
    states = np.random.choice([0, 1, 2], size=n, p=[0.4, 0.3, 0.3])
    returns = np.where(
        states == 0, np.random.normal(0.001, 0.008, n),
        np.where(states == 1, np.random.normal(-0.002, 0.020, n),
                 np.random.normal(0.0, 0.012, n))
    )
    vix = np.where(
        states == 0, np.random.normal(15, 3, n),
        np.where(states == 1, np.random.normal(30, 8, n),
                 np.random.normal(20, 5, n))
    )
    features = np.column_stack([returns, vix])

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "regime_params.pkl"
        result = train_regime_model(
            features=features,
            save_path=str(save_path),
            n_states=3,
            n_iter=50,
            n_restarts=3,
        )

    # Verify output structure
    assert "model" in result
    assert "scaler" in result
    assert "state_labels" in result
    assert "training_date" in result
    assert len(result["state_labels"]) == 3
    assert result["model"].n_components == 3


def test_train_regime_saves_file():
    """Should write a pickle file at the specified path."""
    np.random.seed(42)
    features = np.random.randn(200, 2)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "regime_params.pkl"
        train_regime_model(features=features, save_path=str(save_path))

        assert save_path.exists()
        with open(save_path, "rb") as f:
            loaded = pickle.load(f)
        assert "model" in loaded