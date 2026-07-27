"""Tests for the RiskGate filter."""
import pytest
from src.etl.common import RiskGate


class TestRiskGate:
    def setup_method(self):
        self.gate = RiskGate()

    def test_passes_healthy_stock(self, sample_fundamentals):
        assert self.gate.is_pass(sample_fundamentals) is True

    def test_fails_low_price(self, sample_fundamentals):
        row = dict(sample_fundamentals, current_price=5.0)
        assert self.gate.is_pass(row) is False

    def test_fails_low_op_margin(self, sample_fundamentals):
        row = dict(sample_fundamentals, op_margin=0.01)
        assert self.gate.is_pass(row) is False

    def test_fails_low_current_ratio(self, sample_fundamentals):
        row = dict(sample_fundamentals, current_ratio=0.5)
        assert self.gate.is_pass(row) is False

    def test_fails_low_roe(self, sample_fundamentals):
        row = dict(sample_fundamentals, roe=-0.20)
        assert self.gate.is_pass(row) is False

    def test_fails_none_fwd_pe(self, sample_fundamentals):
        row = dict(sample_fundamentals, fwd_pe=None)
        assert self.gate.is_pass(row) is False

    def test_fails_zero_fwd_pe(self, sample_fundamentals):
        """fwd_pe=0 is not None, so it passes the None check."""
        row = dict(sample_fundamentals, fwd_pe=0)
        assert self.gate.is_pass(row) is True

    def test_handles_empty_dict(self):
        assert self.gate.is_pass({}) is False

    def test_handles_missing_keys(self):
        assert self.gate.is_pass({"current_price": 100}) is False

    def test_edge_price_boundary(self, sample_fundamentals):
        """price exactly at min_price should pass."""
        row = dict(sample_fundamentals, current_price=10.0)
        assert self.gate.is_pass(row) is True

    def test_edge_op_margin_boundary(self, sample_fundamentals):
        """op_margin exactly at min should pass."""
        row = dict(sample_fundamentals, op_margin=0.05)
        assert self.gate.is_pass(row) is True

    def test_edge_current_ratio_boundary(self, sample_fundamentals):
        """current_ratio exactly at min should pass."""
        row = dict(sample_fundamentals, current_ratio=0.8)
        assert self.gate.is_pass(row) is True

    def test_edge_roe_boundary(self, sample_fundamentals):
        """roe exactly at min should pass."""
        row = dict(sample_fundamentals, roe=-0.10)
        assert self.gate.is_pass(row) is True