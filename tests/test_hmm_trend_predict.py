"""Tests for per-ticker trend quality prediction."""
import pickle
import numpy as np
import tempfile
from pathlib import Path
from hmmlearn import hmm
from src.hmm.predict_trend import (
    predict_trend,
    compute_quality_grade,
    format_trend_report,
)


def _make_dummy_trend_params(path: str, ticker: str = "TEST"):
    """Create a dummy trend HMM param file for testing."""
    model = hmm.GaussianHMM(n_components=3, covariance_type="diag", random_state=42)
    X = np.random.randn(300, 1)
    model.fit(X)

    result = {
        "model": model,
        "state_labels": ["DOWNTREND", "WEAK_UPTREND", "STRONG_UPTREND"],
        "ticker": ticker,
        "training_date": "2026-01-01",
        "mean_return": 0.001,
        "volatility": 0.02,
    }
    with open(path, "wb") as f:
        pickle.dump(result, f)


def test_predict_trend_returns_correct_structure():
    """Should return dict with state, confidence, persistence, grade."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "TEST.pkl"
        _make_dummy_trend_params(str(params_path))

        recent = np.random.randn(60)
        result = predict_trend(
            ticker="TEST",
            params_dir=str(tmpdir),
            recent_returns=recent,
        )

    assert "ticker" in result
    assert "state" in result
    assert "confidence" in result
    assert "persistence" in result
    assert "grade" in result
    assert "trend_age" in result
    assert 0 <= result["confidence"] <= 1.0
    assert result["ticker"] == "TEST"


def test_quality_grade_thresholds():
    """Quality grade should map scores to letters correctly."""
    assert compute_quality_grade(4.0) == "A"
    assert compute_quality_grade(3.5) == "A"
    assert compute_quality_grade(3.0) == "B"
    assert compute_quality_grade(2.5) == "B"
    assert compute_quality_grade(2.0) == "C"
    assert compute_quality_grade(1.5) == "C"
    assert compute_quality_grade(1.0) == "D"
    assert compute_quality_grade(0.5) == "D"
    assert compute_quality_grade(0.0) == "F"


def test_format_trend_report_single():
    """Should produce a multi-line string for a single ticker."""
    np.random.seed(42)
    with tempfile.TemporaryDirectory() as tmpdir:
        params_path = Path(tmpdir) / "TEST.pkl"
        _make_dummy_trend_params(str(params_path))

        recent = np.random.randn(60)
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
            recent = np.random.randn(60)
            r = predict_trend(ticker, params_dir=str(tmpdir), recent_returns=recent)
            results.append(r)

        report = format_trend_report(results)
        assert "AAA" in report
        assert "BBB" in report
        assert "Ticker" in report  # table header