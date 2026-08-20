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

    def test_bit(self):
        assert get_suffix("BIT", "Italy") == ".MI"

    def test_sto(self):
        assert get_suffix("STO", "Sweden") == ".ST"

    def test_hel(self):
        assert get_suffix("HEL", "Finland") == ".HE"

    def test_cph(self):
        assert get_suffix("CPH", "Denmark") == ".CO"

    def test_osl(self):
        assert get_suffix("OSL", "Norway") == ".OL"

    def test_war(self):
        assert get_suffix("WAR", "Poland") == ".WA"

    def test_bme(self):
        assert get_suffix("BME", "Spain") == ".MC"

    def test_ir(self):
        assert get_suffix("IR", "Ireland") == ".IR"

    def test_euronext_france(self):
        assert get_suffix("EURONEXT", "France") == ".PA"

    def test_euronext_netherlands(self):
        assert get_suffix("EURONEXT", "Netherlands") == ".AS"

    def test_euronext_belgium(self):
        assert get_suffix("EURONEXT", "Belgium") == ".BR"

    def test_euronext_portugal(self):
        assert get_suffix("EURONEXT", "Portugal") == ".LS"

    def test_euronext_unknown_country_defaults(self):
        assert get_suffix("EURONEXT", "Unknown") == ".PA"

    def test_unknown_exchange_returns_empty(self):
        assert get_suffix("UNKNOWN", "Somewhere") == ""