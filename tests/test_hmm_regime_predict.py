"""Tests for market regime HMM prediction."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler
from src.hmm.predict_regime import predict_regime


def _make_dummy_params(path: str, n_states: int = 6):
    """Create a minimal HMM param file for testing.

    Args:
        path: Where to write the pickle.
        n_states: Number of states (default: 6).
    """
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        random_state=42,
    )
    np.random.seed(42)
    X = np.random.randn(200, 4)
    model.fit(X)

    scaler = StandardScaler()
    scaler.fit(X)

    result = {
        "model": model,
        "scaler": scaler,
        "state_labels": [
            "Low-Vol Bull", "High-Vol Bull", "Low-Vol Sideways",
            "High-Vol Sideways", "Low-Vol Bear", "High-Vol Bear",
        ][:n_states],
        "feature_names": [
            "spy_log_return", "vix_close", "vix_log_return", "realized_vol",
        ],
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
        recent = np.random.randn(60, 4)

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
    assert len(result["probabilities"]) == 6
    assert abs(sum(result["probabilities"]) - 1.0) < 1e-3


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
        recent = np.random.randn(60, 4)
        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
        )

    valid_states = [
        "Low-Vol Bull", "High-Vol Bull", "Low-Vol Sideways",
        "High-Vol Sideways", "Low-Vol Bear", "High-Vol Bear",
    ]
    assert result["state"] in valid_states
    assert result["state"] == result["guidance"]["state"]


def test_regime_forecast_returns_probabilities():
    """Forecast should return valid probability distributions for each horizon."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "params.pkl"
        _make_dummy_params(str(params_path))
        recent = np.random.randn(60, 4)
        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
        )

    assert "forecast" in result
    for horizon, probs in result["forecast"].items():
        assert isinstance(horizon, int)
        assert len(probs) == 6
        assert abs(sum(probs) - 1.0) < 1e-3


def test_regime_forecast_returns_dict():
    """Forecast should return a dict keyed by horizon."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "params.pkl"
        _make_dummy_params(str(params_path))
        recent = np.random.randn(60, 4)
        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
        )

    # Exact values depend on random init; verify structure only
    assert isinstance(result["forecast"], dict)
    for horizon, probs in result["forecast"].items():
        assert isinstance(horizon, int)
        # Probabilities should be a list of 6 floats
        assert isinstance(probs, list)
        assert len(probs) == 6


def test_regime_forecast_long_term():
    """Long-term forecast should approach stationary distribution."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "params.pkl"
        _make_dummy_params(str(params_path))
        recent = np.random.randn(60, 4)
        result = predict_regime(
            params_path=str(params_path),
            recent_observations=recent,
            forecast_horizons=[30, 60, 90, 180],
        )

    diff = sum(abs(a - b) for a, b in zip(result["forecast"][90], result["forecast"][180]))
    assert diff < 0.15