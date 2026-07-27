"""Tests for the production rating engine."""
import pytest
from src.etl.common import assign_production_rating


class TestAssignProductionRating:
    def test_strong_buy_elite(self, sample_rating_row):
        """score > 0.42, eps_rev > 0.01, mom > 0.1, op_margin > 0, peg < 1.8, pe < 60"""
        rating = assign_production_rating(sample_rating_row)
        assert "STRONG BUY" in rating

    def test_buy(self, sample_rating_row):
        """score > 0.35, mom > 0.1, peg < 2.0"""
        row = dict(sample_rating_row, final_score=0.38, eps_rev=0.005, op_margin=0.05,
                   near_high=0.90, acceleration=0.02, mom_3m=0.05)
        rating = assign_production_rating(row)
        assert rating == "BUY"

    def test_sell_estimate_decay(self, sample_rating_row):
        """eps_rev < -0.03 → SELL"""
        row = dict(sample_rating_row, eps_rev=-0.05)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "Estimate Decay" in rating

    def test_sell_no_growth(self, sample_rating_row):
        """rev_growth < 0 → SELL"""
        row = dict(sample_rating_row, rev_growth=-0.05)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "No Growth" in rating

    def test_sell_trend_exhaustion(self, sample_rating_row):
        """mom_score < -0.10 → SELL"""
        row = dict(sample_rating_row, mom_score=-0.15)
        rating = assign_production_rating(row)
        assert "SELL" in rating
        assert "Trend Exhaustion" in rating

    def test_strong_buy_emerging_breakout(self, sample_rating_row):
        """near_high > 0.96, accel > 0.05, mom_3m > 0.10, peg < 1.5"""
        row = dict(sample_rating_row,
                   final_score=0.30,
                   near_high=0.98,
                   acceleration=0.08,
                   mom_3m=0.15,
                   peg=1.3)
        rating = assign_production_rating(row)
        assert "STRONG BUY" in rating
        assert "Emerging Breakout" in rating

    def test_strong_buy_hyper_growth(self, sample_rating_row):
        """rev_growth > 0.50, mom > 0.25, peg < 1.2"""
        row = dict(sample_rating_row,
                   rev_growth=0.60,
                   mom_score=0.30,
                   peg=1.1,
                   near_high=0.90, acceleration=0.02,  # avoid Emerging Breakout
                   eps_rev=0.0,  # avoid SELL
                   fwd_pe=30)
        rating = assign_production_rating(row)
        assert "STRONG BUY" in rating
        assert "Hyper-Growth" in rating

    def test_hold_overvalued_high_pe(self, sample_rating_row):
        """pe > 65 with low score should trigger HOLD (Overvalued)."""
        row = dict(sample_rating_row,
                   final_score=0.30,  # below BUY threshold of 0.35
                   fwd_pe=70,         # above 65 threshold
                   near_high=0.90, acceleration=0.02, mom_3m=0.05,  # avoid Emerging Breakout
                   mom_score=0.05)    # avoid SELL (Trend Exhaustion)
        rating = assign_production_rating(row)
        assert "HOLD" in rating
        assert "Overvalued" in rating

    def test_hold_overvalued_high_peg(self, sample_rating_row):
        """peg > 3.0 → HOLD"""
        row = dict(sample_rating_row, peg=4.0)
        rating = assign_production_rating(row)
        assert "HOLD" in rating
        assert "Overvalued" in rating

    def test_hold_consolidation(self, sample_rating_row):
        """mom < 0 → HOLD"""
        row = dict(sample_rating_row, mom_score=-0.05, near_high=0.90, acceleration=0.02, mom_3m=0.05)
        rating = assign_production_rating(row)
        assert "HOLD" in rating
        assert "Consolidation" in rating

    def test_fallback_hold(self, sample_rating_row):
        """No conditions met → HOLD"""
        row = dict(sample_rating_row,
                   final_score=0.20,
                   eps_rev=0.0,
                   mom_score=0.05,
                   rev_growth=0.05,
                   fwd_pe=30,
                   peg=2.0,
                   op_margin=0.05,
                   acceleration=0.01,
                   near_high=0.80,
                   mom_3m=0.02)
        rating = assign_production_rating(row)
        assert rating == "HOLD"

    def test_handles_missing_fields(self):
        """Should not crash on missing optional fields."""
        row = {"final_score": 0.5, "eps_rev": 0.05}
        rating = assign_production_rating(row)
        assert isinstance(rating, str)

    def test_assign_rating_alias(self, sample_rating_row):
        """assign_rating should be an alias for assign_production_rating."""
        from src.etl.common import assign_rating
        assert assign_rating(sample_rating_row) == assign_production_rating(sample_rating_row)

    def test_sell_decay_takes_priority(self, sample_rating_row):
        """SELL triggers should fire before STRONG BUY even if score is high."""
        row = dict(sample_rating_row, eps_rev=-0.05, final_score=0.60)
        rating = assign_production_rating(row)
        assert "SELL" in rating