"""Tests for European ticker suffix mapping."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "etl"))

from european_ticker_config import get_suffix


class TestGetSuffix:
    """Verify each EODHD exchange code maps to the correct yfinance suffix."""

    def test_lse(self):
        assert get_suffix("LSE", "UK") == ".L"

    def test_xetra(self):
        assert get_suffix("XETRA", "Germany") == ".DE"

    def test_swiss(self):
        assert get_suffix("SW", "Switzerland") == ".SW"

    def test_stockholm(self):
        assert get_suffix("ST", "Sweden") == ".ST"

    def test_helsinki(self):
        assert get_suffix("HE", "Finland") == ".HE"

    def test_copenhagen(self):
        assert get_suffix("CO", "Denmark") == ".CO"

    def test_oslo(self):
        assert get_suffix("OL", "Norway") == ".OL"

    def test_warsaw(self):
        assert get_suffix("WAR", "Poland") == ".WA"

    def test_madrid(self):
        assert get_suffix("MC", "Spain") == ".MC"

    def test_ireland(self):
        assert get_suffix("IR", "Ireland") == ".IR"

    def test_paris(self):
        assert get_suffix("PA", "France") == ".PA"

    def test_amsterdam(self):
        assert get_suffix("AS", "Netherlands") == ".AS"

    def test_brussels(self):
        assert get_suffix("BR", "Belgium") == ".BR"

    def test_lisbon(self):
        assert get_suffix("LS", "Portugal") == ".LS"

    def test_unknown_exchange_returns_empty(self):
        assert get_suffix("UNKNOWN", "Somewhere") == ""