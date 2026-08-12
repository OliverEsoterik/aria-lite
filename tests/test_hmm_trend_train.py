"""Tests for per-ticker trend HMM training (multi-horizon features)."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from src.hmm.train_trend import train_trend_model


def _make_synthetic_features(n: int = 500) -> np.ndarray:
    """Generate synthetic 3-feature data (R_21, R_63, R_252)."""
    np.random.seed(42)
    # Strong uptrend: all 3 windows positive with positive drift
    base = np.random.randn(n) * 0.01 + 0.002
    # R_21: short-term noise
    r21 = base + np.random.randn(n) * 0.005
    # R_63: medium-term smoother
    r63 = np.convolve(base, np.ones(3)/3, mode='same') + np.random.randn(n) * 0.003
    # R_252: long-term very smooth
    r252 = np.convolve(base, np.ones(5)/5, mode='same') + np.random.randn(n) * 0.001
    return np.column_stack([r21, r63, r252])


def test_train_trend_synthetic_data():
    """Should train on synthetic 3-feature data and produce expected output."""
    features = _make_synthetic_features()

    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        result = train_trend_model(
            ticker="TEST",
            returns=features,
            save_dir=str(save_dir),
        )

    assert "model" in result
    assert "scaler" in result
    assert "state_labels" in result
    assert len(result["state_labels"]) == 4
    assert result["ticker"] == "TEST"
    assert result["feature_names"] == ["R_21", "R_63", "R_252"]
    assert result["model"].n_components == 4
    assert result["model"].means_.shape[1] == 3


def test_train_trend_saves_file():
    """Should write a pickle file per ticker."""
    features = _make_synthetic_features(400)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        train_trend_model(ticker="TEST", returns=features, save_dir=str(save_dir))

        expected_path = save_dir / "TEST.pkl"
        assert expected_path.exists()
        with open(expected_path, "rb") as f:
            loaded = pickle.load(f)
        assert loaded["ticker"] == "TEST"
        assert "scaler" in loaded


def test_train_trend_minimum_data():
    """Should raise ValueError if fewer than 252 data points."""
    features = np.random.randn(50, 3)
    try:
        train_trend_model(ticker="TEST", returns=features)
        assert False, "Should have raised"
    except ValueError as e:
        assert "252" in str(e)


def test_train_trend_state_labels():
    """State labels should be 4 distinct trend states."""
    features = _make_synthetic_features()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = train_trend_model(
            ticker="TEST", returns=features, save_dir=str(tmpdir)
        )
    labels = result["state_labels"]
    assert len(set(labels)) == 4  # All distinct
    for label in ["DOWNTREND", "SIDEWAYS", "WEAK_UPTREND", "STRONG_UPTREND"]:
        assert label in labels