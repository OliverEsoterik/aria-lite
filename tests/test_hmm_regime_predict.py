"""Tests for market regime HMM prediction."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler
from src.hmm.predict_regime import predict_regime


def _make_dummy_params(path: str, n_states: int = 3):
    """Create a minimal HMM param file for testing."""
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        random_state=42,
    )
    # Pre-fit by training on synthetic data
    np.random.seed(42)
    X = np.random.randn(200, 2)
    model.fit(X)

    scaler = StandardScaler()
    scaler.fit(X)

    result = {
        "model": model,
        "scaler": scaler,
        "state_labels": ["BEAR", "SIDEWAYS", "BULL"] if n_states >= 3
                        else [f"STATE_{i}" for i in range(n_states)],
        "feature_names": ["spy_log_return", "vix_close"],
        "training_date": "2026-01-01",
    }
    with open(path, "wb") as f:
        pickle.dump(result, f)


def test_predict_regime_returns_correct_structure():
    """Should return dict with state, probabilities, persistence, guidance."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "params.pkl"
        _make_dummy_params(str(params_path))

        # Generate synthetic recent observations
        recent = np.random.randn(60, 2)

        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
        )

    assert "state" in result
    assert "confidence" in result
    assert "probabilities" in result
    assert "persistence" in result
    assert "state_labels" in result
    assert "guidance" in result
    assert len(result["probabilities"]) == 3
    assert abs(sum(result["probabilities"]) - 1.0) < 1e-6


def test_predict_regime_raises_on_missing_params():
    """Should raise FileNotFoundError when params file doesn't exist."""
    try:
        predict_regime(params_path="/nonexistent/params.pkl")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


def test_predict_regime_guidance_maps_correctly():
    """Guidance should match the predicted state."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "params.pkl"
        _make_dummy_params(str(params_path))

        recent = np.random.randn(60, 2)
        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
        )

    assert result["state"] in ["BEAR", "SIDEWAYS", "BULL"]
    assert result["state"] == result["guidance"]["state"]