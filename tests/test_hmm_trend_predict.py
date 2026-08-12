"""Tests for per-ticker trend quality prediction (multi-horizon features)."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler
from src.hmm.predict_trend import (
    predict_trend,
    compute_quality_grade,
    format_trend_report,
)


def _make_dummy_trend_params(path: str, ticker: str = "TEST"):
    """Create a dummy 4-state, 3-feature HMM param file for testing."""
    model = hmm.GaussianHMM(n_components=4, covariance_type="full", random_state=42)
    X = np.random.randn(500, 3)
    model.fit(X)

    scaler = StandardScaler()
    scaler.fit(X)

    result = {
        "model": model,
        "scaler": scaler,
        "state_labels": ["DOWNTREND", "SIDEWAYS", "WEAK_UPTREND", "STRONG_UPTREND"],
        "ticker": ticker,
        "training_date": "2026-01-01",
        "feature_names": ["R_21", "R_63", "R_252"],
    }
    with open(path, "wb") as f:
        pickle.dump(result, f)


def test_predict_trend_returns_correct_structure():
    """Should return dict with state, confidence, forecast, grade."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "TEST.pkl"
        _make_dummy_trend_params(str(params_path))

        # 3-feature recent data
        recent = np.random.randn(252, 3)

        result = predict_trend(
            ticker="TEST",
            params_dir=str(tmpdir),
            recent_returns=recent,
        )

    assert "ticker" in result
    assert "state" in result
    assert "confidence" in result
    assert "forecast" in result
    assert "grade" in result
    assert "grade_score" in result
    assert 0 <= result["confidence"] <= 1.0
    assert result["ticker"] == "TEST"
    assert result["state"] in ["DOWNTREND", "SIDEWAYS", "WEAK_UPTREND", "STRONG_UPTREND"]


def test_predict_trend_forecast():
    """Forecast should have valid horizons and probabilities."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "TEST.pkl"
        _make_dummy_trend_params(str(params_path))
        recent = np.random.randn(252, 3)
        result = predict_trend(
            ticker="TEST",
            params_dir=str(tmpdir),
            recent_returns=recent,
        )

    forecast = result["forecast"]
    assert 60 in forecast  # Default horizon
    for horizon, probs in forecast.items():
        assert abs(sum(probs) - 1.0) < 1e-6


def test_compute_quality_grade():
    """Grade should map state + confidence + forecast to letter."""
    # STRONG_UPTREND (1.0) * 0.4 + 0.95 * 0.3 + 0.90 * 0.3 = 0.4 + 0.285 + 0.27 = 0.955
    assert compute_quality_grade(0.955) == "A"
    # STRONG_UPTREND (1.0) * 0.4 + 0.5 * 0.3 + 0.3 * 0.3 = 0.4 + 0.15 + 0.09 = 0.64
    assert compute_quality_grade(0.64) == "B"
    # WEAK_UPTREND (0.66) * 0.4 + 0.5 * 0.3 + 0.3 * 0.3 = 0.264 + 0.15 + 0.09 = 0.504
    assert compute_quality_grade(0.504) == "C"
    # SIDEWAYS (0.33) * 0.4 + 0.3 * 0.3 + 0.2 * 0.3 = 0.132 + 0.09 + 0.06 = 0.282
    assert compute_quality_grade(0.282) == "D"
    # DOWNTREND (0.0) * 0.4 + 0.2 * 0.3 + 0.1 * 0.3 = 0.0 + 0.06 + 0.03 = 0.09
    assert compute_quality_grade(0.09) == "F"


def test_format_trend_report_single():
    """Should produce a multi-line string for a single ticker."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "TEST.pkl"
        _make_dummy_trend_params(str(params_path))
        recent = np.random.randn(252, 3)
        result = predict_trend(
            ticker="TEST",
            params_dir=str(tmpdir),
            recent_returns=recent,
        )
        report = format_trend_report([result])

    assert "TEST" in report
    assert result["state"] in report
    assert result["grade"] in report


def test_format_trend_report_compare():
    """Compare mode should show a table with multiple tickers."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        results = []
        for ticker in ["AAA", "BBB"]:
            params_path = Path(tmpdir) / f"{ticker}.pkl"
            _make_dummy_trend_params(str(params_path), ticker=ticker)
            recent = np.random.randn(252, 3)
            r = predict_trend(ticker, params_dir=str(tmpdir), recent_returns=recent)
            results.append(r)

        report = format_trend_report(results)
        assert "AAA" in report
        assert "BBB" in report
        assert "Ticker" in report  # table header