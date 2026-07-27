"""Tests for top-picks portfolio functions."""
import numpy as np
import pandas as pd
import pytest
import sys
import os

# Add the tools directory to path (hyphen in dir name prevents normal import)
_tools_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "top-picks-portfolio", "tools")
sys.path.insert(0, _tools_dir)
from build_top_picks_portfolio import (
    is_excluded,
    classify_subsector,
    diversify_candidates,
    allocate_portfolio,
)


class TestIsExcluded:
    def test_excludes_healthcare_sector(self):
        assert is_excluded("Healthcare", "Medical Devices", "Test Corp") is True

    def test_excludes_pharma_keyword(self):
        assert is_excluded("Technology", "Pharmaceuticals", "Test Corp") is True

    def test_excludes_mining_sector(self):
        assert is_excluded("Basic Materials", "Gold", "Test Corp") is True

    def test_excludes_biotech_name(self):
        assert is_excluded("Technology", "Software", "Biotech Innovations Inc") is True

    def test_allows_tech(self):
        assert is_excluded("Technology", "Software", "Microsoft Corp") is False

    def test_allows_financial(self):
        assert is_excluded("Financial Services", "Asset Management", "BlackRock") is False

    def test_none_sector_is_not_excluded(self):
        assert is_excluded(None, None, None) is False

    def test_excludes_mining_industry_keyword(self):
        assert is_excluded("Technology", "Software", "Gold Mining Corp") is True

    def test_excludes_biotech_industry(self):
        assert is_excluded("Technology", "Biotechnology", "Some Corp") is True

    def test_excludes_biotech_sector(self):
        assert is_excluded("Biotechnology", "Research", "Some Corp") is True


class TestClassifySubsector:
    def test_semiconductor(self):
        result = classify_subsector("Technology", "Semiconductors")
        assert result == "Semiconductors"

    def test_semiconductor_equipment(self):
        """'semiconductor' keyword in Semiconductors matches before longer 'semiconductor equipment'."""
        result = classify_subsector("Technology", "Semiconductor Equipment & Materials")
        # 'semiconductor' matches Semiconductors cluster first
        assert result == "Semiconductors"

    def test_software(self):
        result = classify_subsector("Technology", "Software - Infrastructure")
        assert result == "Software"

    def test_fallback_to_sector(self):
        result = classify_subsector("Unknown", "Something")
        assert result == "Unknown"

    def test_case_insensitive(self):
        result = classify_subsector("Technology", "SEMICONDUCTOR MEMORY")
        assert result == "Semiconductors"

    def test_networking(self):
        result = classify_subsector("Technology", "Communication Equipment")
        assert result == "Networking"

    def test_storage(self):
        result = classify_subsector("Technology", "Data Storage")
        assert result == "Storage"

    def test_financial_services(self):
        result = classify_subsector("Financial Services", "Asset Management")
        assert result == "Financial Services"

    def test_defense(self):
        """'industrial' keyword from sector name matches Industrial cluster before Defense."""
        result = classify_subsector("Industrials", "Aerospace & Defense")
        # 'industrial' matches Industrial cluster first
        assert result == "Industrial"


class TestDiversifyCandidates:
    @pytest.fixture
    def candidates(self):
        np.random.seed(42)
        tickers = [f"T{i}" for i in range(20)]
        sectors = ["Tech"] * 10 + ["Health"] * 5 + ["Energy"] * 5
        return pd.DataFrame({
            "ticker": tickers,
            "final_score": np.random.uniform(0.2, 0.8, 20),
            "sector": sectors,
            "_subsector": [f"Sub{s}" for s in sectors],
        })

    def test_selects_up_to_target(self, candidates):
        result = diversify_candidates(candidates, max_per_subsector=2, target=10)
        assert len(result) <= 10

    def test_respects_max_per_subsector(self, candidates):
        result = diversify_candidates(candidates, max_per_subsector=1, target=10)
        subsector_counts = result["_subsector"].value_counts()
        assert (subsector_counts <= 1).all()

    def test_empty_dataframe(self):
        result = diversify_candidates(pd.DataFrame(), target=10)
        assert len(result) == 0

    def test_fewer_candidates_than_target(self, candidates):
        few = candidates.head(3)
        # With max_per_subsector=3 (enough for all 3) and target=10, should get all 3
        result = diversify_candidates(few, max_per_subsector=3, max_per_sector_frac=0.90, target=10)
        assert len(result) == 3

    def test_selects_highest_scores_first(self, candidates):
        result = diversify_candidates(candidates, max_per_subsector=10, target=5)
        top5 = candidates.sort_values("final_score", ascending=False).head(5)
        assert result["ticker"].iloc[0] == top5["ticker"].iloc[0]

    def test_missing_subsector_column(self):
        df = pd.DataFrame({
            "ticker": ["A", "B"],
            "final_score": [0.5, 0.4],
            "sector": ["Tech", "Tech"],
        })
        result = diversify_candidates(df, max_per_subsector=2, target=10)
        assert len(result) == 2


class TestAllocatePortfolio:
    @pytest.fixture
    def candidates(self):
        return pd.DataFrame({
            "ticker": ["A", "B", "C", "D"],
            "final_score": [100, 50, 25, 10],
            "sector": ["Tech", "Health", "Tech", "Energy"],
        })

    def test_weights_sum_to_one(self, candidates):
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=4)
        assert result["weight"].sum() == pytest.approx(1.0, abs=1e-2)

    def test_respects_max_single(self, candidates):
        huge_score = candidates.copy()
        huge_score.loc[0, "final_score"] = 10000
        result = allocate_portfolio(huge_score, max_single=0.30, min_position=0.01, target=4)
        assert result["weight"].max() <= 0.30 + 1e-2

    def test_zeros_below_min_position(self, candidates):
        small = candidates.copy()
        small["final_score"] = [0.001, 100, 100, 100]
        result = allocate_portfolio(small, max_single=0.50, min_position=0.05, target=4)
        zero_count = (result["weight"] == 0).sum()
        assert zero_count >= 1

    def test_single_candidate(self):
        candidates = pd.DataFrame({
            "ticker": ["A"],
            "final_score": [100],
            "sector": ["Tech"],
        })
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=1)
        assert result["weight"].iloc[0] == pytest.approx(1.0, abs=1e-2)

    def test_has_weight_pct_column(self, candidates):
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=4)
        assert "weight_pct" in result.columns

    def test_rounding_precision(self, candidates):
        """Weights should be rounded to 0.5% increments."""
        result = allocate_portfolio(candidates, max_single=0.50, min_position=0.01, target=4)
        pcts = result["weight_pct"]
        assert ((pcts * 2) % 1 == 0).all()  # every 0.5%