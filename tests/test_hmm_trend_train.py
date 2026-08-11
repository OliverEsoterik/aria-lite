"""Tests for per-ticker trend HMM training."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from src.hmm.train_trend import train_trend_model


def test_train_trend_synthetic_data():
    """Should train on synthetic trend data and produce expected output."""
    np.random.seed(42)
    n = 500
    # Uptrend: positive drift
    returns = np.random.normal(0.002, 0.015, n)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        result = train_trend_model(
            ticker="TEST",
            returns=returns,
            save_dir=str(save_dir),
        )

    assert "model" in result
    assert "state_labels" in result
    assert len(result["state_labels"]) == 3
    assert result["ticker"] == "TEST"


def test_train_trend_saves_file():
    """Should write a pickle file per ticker."""
    np.random.seed(42)
    returns = np.random.randn(300)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        train_trend_model(ticker="TEST", returns=returns, save_dir=str(save_dir))

        expected_path = save_dir / "TEST.pkl"
        assert expected_path.exists()
        with open(expected_path, "rb") as f:
            loaded = pickle.load(f)
        assert loaded["ticker"] == "TEST"


def test_train_trend_minimum_data():
    """Should raise ValueError if fewer than 252 data points."""
    try:
        train_trend_model(ticker="TEST", returns=np.random.randn(50))
        assert False, "Should have raised"
    except ValueError as e:
        assert "252" in str(e)