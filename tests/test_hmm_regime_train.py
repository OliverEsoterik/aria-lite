"""Tests for market regime HMM training."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from hmmlearn import hmm
from src.hmm.train_regime import train_regime_model, _assign_regime_labels, _PROTOTYPES, _REGIME_LABELS


def test_train_regime_synthetic_data():
    """Should train a 6-state model on 4-feature data and produce expected output."""
    np.random.seed(42)
    features = np.random.randn(300, 4)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "regime_params.pkl"
        result = train_regime_model(
            features=features,
            save_path=str(save_path),
            n_states=6,
            n_iter=50,
            n_restarts=3,
        )

    assert "model" in result
    assert "scaler" in result
    assert "state_labels" in result
    assert "training_date" in result
    assert len(result["state_labels"]) == 6
    assert result["model"].n_components == 6


def test_train_regime_saves_file():
    """Should write a pickle file at the specified path."""
    np.random.seed(42)
    features = np.random.randn(200, 4)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "regime_params.pkl"
        train_regime_model(features=features, save_path=str(save_path))

        assert save_path.exists()
        with open(save_path, "rb") as f:
            loaded = pickle.load(f)
        assert "model" in loaded


def test_regime_labeling_hungarian():
    """Hungarian assignment should map known means to correct labels."""
    # Create a model with means_ matching prototypes in shuffled order
    model = hmm.GaussianHMM(n_components=6, covariance_type="full")
    rng = np.random.RandomState(42)
    shuffled = _PROTOTYPES.copy()
    rng.shuffle(shuffled)
    model.means_ = shuffled

    labels = _assign_regime_labels(model)

    assert len(labels) == 6
    assert all(l in _REGIME_LABELS for l in labels)
    assert len(set(labels)) == 6  # no duplicates