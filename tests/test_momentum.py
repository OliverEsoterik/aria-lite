"""Tests for momentum scoring helpers."""
import numpy as np
import pandas as pd
import pytest
from src.etl.common import z_score, ANNUALIZATION_FACTOR


class TestZScore:
    def test_mean_zero_std_one(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = z_score(s)
        assert result.mean() == pytest.approx(0, abs=1e-10)
        # pandas uses ddof=1 so std won't be exactly 1
        assert result.std() == pytest.approx(1, rel=1e-3)

    def test_constant_series(self):
        """Constant series should produce zeros (std=0, but epsilon prevents div by 0)."""
        s = pd.Series([5, 5, 5, 5, 5])
        result = z_score(s)
        assert (result == 0).all()

    def test_single_value(self):
        s = pd.Series([42])
        result = z_score(s)
        # Single value: std is NaN, so result is NaN due to epsilon
        assert pd.isna(result.iloc[0])

    def test_with_nan(self):
        s = pd.Series([1, 2, np.nan, 4, 5])
        result = z_score(s)
        assert result.isna().sum() == 1
        assert result.dropna().mean() == pytest.approx(0, abs=1e-10)

    def test_negative_values(self):
        s = pd.Series([-10, -5, 0, 5, 10])
        result = z_score(s)
        assert result.mean() == pytest.approx(0, abs=1e-10)
        assert result.std() == pytest.approx(1, rel=1e-3)

    def test_two_values(self):
        s = pd.Series([10, 20])
        result = z_score(s)
        assert result.mean() == pytest.approx(0, abs=1e-10)
        assert result.std() == pytest.approx(1, rel=1e-3)

    def test_anualization_factor(self):
        assert ANNUALIZATION_FACTOR == pytest.approx(np.sqrt(252), rel=1e-10)