#!/usr/bin/env python3
"""
Build a top-picks portfolio from the alpha-picks rating system.

Usage:
    nix develop -c python3 skills/top-picks-portfolio/tools/build_top_picks_portfolio.py

Outputs markdown to stdout.
"""

import sys
import os
import json
import importlib.util
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime


# --- Load the rating module ---
def load_rating_module():
    spec = importlib.util.spec_from_file_location(
        "ratings", "src/etl/03_generate_production_ratings.py"
    )
    ratings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratings)
    return ratings


# --- Sector enrichment ---
EXCLUDED_SECTORS = {
    'Healthcare',
    'Pharmaceuticals',
    'Biotechnology',
    'Medical Devices',
    'Medical Diagnostics & Research',
    'Medical Instruments & Supplies',
    'Medical Care Facilities',
    'Drug Manufacturers - General',
    'Drug Manufacturers - Specialty & Generic',
    'Health Information Services',
    'Basic Materials',
    'Metals & Mining',
    'Gold',
    'Silver',
    'Copper',
    'Other Precious Metals & Minerals',
    'Other Industrial Metals & Mining',
    'Industrial Metals & Minerals',
    'Steel',
    'Aluminum',
    'Agricultural Inputs',
}

EXCLUDED_INDUSTRY_KEYWORDS = [
    'pharma', 'biotech', 'biologics', 'therapeutic', 'clinical',
    'drug', 'generic', 'vaccine', 'diagnostic', 'medical',
    'hospital', 'surgical', 'dental', 'laboratory',
    'mining', 'mine', 'mineral', 'metal', 'gold', 'silver',
    'copper', 'uranium', 'lithium', 'rare earth', 'coal',
    'steel', 'aluminum', 'smelting', 'refining', 'exploration',
    'drilling', 'oil & gas exploration', 'oil & gas drilling',
    'oil & gas e&p', 'oil & gas integrated',
]


def get_sector_info(ticker):
    """Fetch sector/industry from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        sector = info.get('sector', 'Unknown')
        industry = info.get('industry', 'Unknown')
        name = info.get('longName') or info.get('shortName', ticker)
        return sector, industry, name
    except Exception:
        return None, None, None


def is_excluded(sector, industry, name):
    """Check if a ticker should be excluded."""
    if sector is None:
        return False
    sector_lower = sector.lower()
    industry_lower = industry.lower() if industry else ''
    name_lower = name.lower() if name else ''

    for ex in EXCLUDED_SECTORS:
        if ex.lower() in sector_lower or ex.lower() in industry_lower:
            return True

    for kw in EXCLUDED_INDUSTRY_KEYWORDS:
        if kw in industry_lower or kw in name_lower:
            return True

    return False


# --- Diversification logic ---
SUBSECTOR_CLUSTERS = {
    'Semiconductors': ['semiconductor', 'memory', 'chip', 'processor', 'gpu', 'asic', 'foundry', 'wafer'],
    'Semiconductor Equipment': ['semiconductor equipment', 'wafer fab', 'chip equipment', 'test equipment'],
    'Storage': ['data storage', 'hard disk', 'ssd', 'flash', 'storage device', 'memory storage'],
    'Networking': ['networking', 'communication equipment', 'fiber optic', 'optical', 'router', 'switch'],
    'Software': ['software', 'saas', 'cloud software', 'enterprise software', 'application'],
    'Internet': ['internet', 'e-commerce', 'online', 'platform', 'digital media'],
    'Financial Services': ['bank', 'insurance', 'asset management', 'brokerage', 'fintech', 'capital markets'],
    'Industrial': ['industrial', 'manufacturing', 'engineering', 'construction', 'machinery'],
    'Consumer Tech': ['consumer electronics', 'hardware', 'peripherals', 'wearable'],
    'Defense': ['defense', 'aerospace', 'military', 'government'],
    'Energy': ['energy', 'oil', 'gas', 'renewable', 'solar', 'wind'],
    'Real Estate': ['reit', 'real estate', 'property'],
    'Consumer Cyclical': ['consumer cyclical', 'retail', 'apparel', 'auto', 'travel', 'leisure'],
    'Consumer Defensive': ['consumer defensive', 'food', 'beverage', 'household', 'personal care'],
    'Communication': ['telecom', 'communication', 'media', 'entertainment'],
    'Technology Services': ['technology services', 'it services', 'consulting', 'outsourcing'],
    'Electronic Components': ['electronic component', 'pcb', 'circuit', 'connector', 'sensor', 'electronic manufacturing'],
}


def classify_subsector(sector, industry):
    """Classify into a broad subsector for diversification."""
    combined = f"{sector} {industry}".lower()
    for cluster, keywords in SUBSECTOR_CLUSTERS.items():
        for kw in keywords:
            if kw in combined:
                return cluster
    return sector


def diversify_candidates(candidates_df, max_per_subsector=2, max_per_sector_frac=0.40, target=14):
    """
    Select a diversified set from candidates.
    Ensures no subsector is overrepresented.
    """
    if candidates_df.empty:
        return pd.DataFrame()

    selected = []
    subsector_counts = {}
    sector_weights = {}

    sorted_df = candidates_df.sort_values('final_score', ascending=False)

    for _, row in sorted_df.iterrows():
        if len(selected) >= target:
            break

        subsector = row.get('_subsector', row.get('sector', 'Unknown'))
        sector = row.get('sector', 'Unknown')

        current_subsector = subsector_counts.get(subsector, 0)
        if current_subsector >= max_per_subsector:
            continue

        estimated_weight = 1.0 / target
        current_sector = sector_weights.get(sector, 0)
        if current_sector + estimated_weight > max_per_sector_frac:
            continue

        selected.append(row)
        subsector_counts[subsector] = current_subsector + 1
        sector_weights[sector] = current_sector + estimated_weight

    return pd.DataFrame(selected)


# --- Final allocation ---
def allocate_portfolio(selected_df, max_single=0.15, min_position=0.05, target=10):
    """Score-weighted allocation with constraints. Iterative normalization."""
    scores = selected_df['final_score'].values.copy()

    min_s = scores.min()
    if min_s < 0:
        scores = scores - min_s + 0.01
    else:
        scores = scores + 0.01

    raw = scores / scores.sum()

    # Iterative: cap at max_single, redistribute remainder
    weights = raw.copy()
    for _ in range(20):
        over = weights > max_single
        if not over.any():
            break
        excess = (weights[over] - max_single).sum()
        weights[over] = max_single
        under = ~over
        if under.sum() > 0:
            weights[under] += excess * (weights[under] / weights[under].sum())

    # Zero out below min_position
    weights[weights < min_position] = 0.0

    total = weights.sum()
    if total > 0:
        weights = weights / total

    # Round to 0.5%
    weights = (weights * 200).round() / 200
    total = weights.sum()
    if total > 0:
        weights = weights / total

    selected_df = selected_df.copy()
    selected_df['weight'] = weights
    selected_df['weight_pct'] = (weights * 100).round(1)
    return selected_df.sort_values('weight', ascending=False)


# --- Risk flags ---
def risk_flags(row):
    flags = []
    try:
        if row.get('beta') and abs(float(row['beta'])) > 1.5:
            flags.append(f"β={float(row['beta']):.1f}")
    except: pass
    try:
        if row.get('debt_to_equity') and float(row['debt_to_equity']) > 100:
            flags.append(f"D/E={float(row['debt_to_equity']):.0f}")
    except: pass
    try:
        if row.get('annual_vol') and float(row['annual_vol']) > 0.5:
            flags.append(f"vol={float(row['annual_vol'])*100:.0f}%")
    except: pass
    try:
        if row.get('current_ratio') and float(row['current_ratio']) < 1.0:
            flags.append("low liq")
    except: pass
    try:
        if row.get('peg') and float(row['peg']) > 2.0:
            flags.append(f"PEG={float(row['peg']):.1f}")
    except: pass
    try:
        if row.get('near_high') and float(row['near_high']) < 0.75:
            flags.append(f"-{((1-float(row['near_high']))*100):.0f}% 52w")
    except: pass
    return "; ".join(flags) if flags else "—"


# --- Main ---
def main():
    print(f"# Top Picks Portfolio — {datetime.now().strftime('%Y-%m-%d')}")
    print()
    print(f"*Based on alpha-picks factor model, STRONG BUY only, ex-pharma/mining*")
    print()

    # Phase 1: Run the rating pipeline
    print("## Phase 1: Running Rating Pipeline", file=sys.stderr)
    ratings = load_rating_module()
    from sqlalchemy import create_engine
    DB_URL = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2:///alphapicks"
    )
    engine = create_engine(DB_URL)

    picks, _ = ratings.get_today_best_buys(
        engine, initial_pool_size=800, final_top_n=500
    )

    if picks is None or picks.empty:
        print("ERROR: Rating pipeline returned no results.", file=sys.stderr)
        sys.exit(1)

    total_screened = len(picks)
    print(f"  Scored {total_screened} tickers.", file=sys.stderr)

    # Phase 2: Filter to STRONG BUY
    print("\n## Phase 2: Filtering to STRONG BUY", file=sys.stderr)
    strong_buys = picks[picks['rating'].str.contains('STRONG BUY')].copy()
    print(f"  STRONG BUY count: {len(strong_buys)}", file=sys.stderr)

    rating_dist = strong_buys['rating'].value_counts()
    for r, c in rating_dist.items():
        print(f"    {r}: {c}", file=sys.stderr)

    # Phase 3: Enrich with sector info
    print("\n## Phase 3: Enriching with Sector Data", file=sys.stderr)
    sectors = {}
    names = {}
    for t in strong_buys['ticker'].tolist():
        sec, ind, name = get_sector_info(t)
        if sec:
            sectors[t] = (sec, ind)
            names[t] = name
        print(f"  {t:6s} -> {str(sec):30s} {str(ind):40s}", file=sys.stderr)

    strong_buys['sector'] = strong_buys['ticker'].map(lambda t: sectors.get(t, (None, None))[0])
    strong_buys['industry'] = strong_buys['ticker'].map(lambda t: sectors.get(t, (None, None))[1])
    strong_buys['name'] = strong_buys['ticker'].map(lambda t: names.get(t, t))

    # Exclude pharma and miners
    excluded_mask = strong_buys.apply(
        lambda r: is_excluded(r['sector'], r['industry'], r['name']), axis=1
    )
    excluded_list = strong_buys[excluded_mask]['ticker'].tolist()
    strong_buys = strong_buys[~excluded_mask].copy()
    print(f"  Excluded {len(excluded_list)}: {', '.join(excluded_list)}", file=sys.stderr)
    print(f"  Remaining after sector filter: {len(strong_buys)}", file=sys.stderr)

    if strong_buys.empty:
        print("ERROR: No STRONG BUY tickers remain after sector exclusions.", file=sys.stderr)
        sys.exit(1)

    # Phase 4: Diversify
    print("\n## Phase 4: Diversification", file=sys.stderr)
    strong_buys['_subsector'] = strong_buys.apply(
        lambda r: classify_subsector(r['sector'], r['industry']), axis=1
    )
    print("  Subsector classification (top by score):", file=sys.stderr)
    for _, r in strong_buys.sort_values('final_score', ascending=False).head(25).iterrows():
        print(f"    {r['ticker']:6s} -> {r['_subsector']:25s} (score={r['final_score']:.3f})", file=sys.stderr)

    diversified = diversify_candidates(strong_buys, target=10)
    print(f"  Selected {len(diversified)} tickers after diversification.", file=sys.stderr)

    if diversified.empty:
        print("ERROR: No tickers selected after diversification.", file=sys.stderr)
        # Fallback: just take top 10 by score
        diversified = strong_buys.sort_values('final_score', ascending=False).head(10)
        print(f"  Fallback: taking top 10 by score.", file=sys.stderr)

    # Phase 5: Allocate
    print("\n## Phase 5: Allocation", file=sys.stderr)
    portfolio_df = allocate_portfolio(diversified, target=len(diversified))

    # Phase 6: Output
    print("## Summary")
    print()
    print(f"| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| Universe screened | {total_screened} |")
    print(f"| STRONG BUY candidates | {len(strong_buys)} |")
    print(f"| Portfolio positions | {(portfolio_df['weight'] > 0).sum()} |")
    wscore = (portfolio_df['weight'] * portfolio_df['final_score']).sum()
    print(f"| Weighted score | {wscore:.3f} |")
    top3 = portfolio_df.head(3)['weight'].sum() * 100
    print(f"| Top 3 concentration | {top3:.0f}% |")
    print(f"| Sectors covered | {portfolio_df['sector'].nunique()} |")

    print()
    print("## Portfolio")
    print()
    print("| # | Ticker | Name | Rating | Score | Wt% | Sector | Subsector | Risk Flags |")
    print("|---|--------|------|--------|-------|-----|--------|-----------|------------|")

    for i, (_, row) in enumerate(portfolio_df.iterrows(), 1):
        if row['weight'] <= 0:
            continue
        name = str(row.get('name', ''))[:35]
        ticker = row['ticker']
        rating = row['rating']
        score = f"{row['final_score']:.3f}"
        wt = f"{row['weight_pct']:.0f}%"
        sector = str(row.get('sector', '?'))[:20]
        subsector = str(row.get('_subsector', '?'))[:20]
        rflags = risk_flags(row)
        print(f"| {i} | {ticker} | {name} | {rating} | {score} | {wt} | {sector} | {subsector} | {rflags} |")

    print()
    print("## Sector Allocation")
    print()
    active = portfolio_df[portfolio_df['weight'] > 0].copy()
    sector_alloc = active.groupby('sector')['weight'].sum().sort_values(ascending=False)
    print("| Sector | Weight |")
    print("|--------|--------|")
    for s, w in sector_alloc.items():
        bar = "█" * max(1, int(w * 100 / 2))
        print(f"| {s} | {w*100:.1f}% {bar} |")

    print()
    print("## Subsector Allocation")
    print()
    subsector_alloc = active.groupby('_subsector')['weight'].sum().sort_values(ascending=False)
    print("| Subsector | Weight |")
    print("|-----------|--------|")
    for s, w in subsector_alloc.items():
        bar = "█" * max(1, int(w * 100 / 2))
        print(f"| {s} | {w*100:.1f}% {bar} |")

    print()
    print("## Risk Notes")
    print()

    if 'beta' in active.columns and active['beta'].notna().any():
        beta_col = active['beta'].fillna(1.0)
        wbeta = (active['weight'] * beta_col).sum()
        print(f"- **Weighted beta:** {wbeta:.2f}")
    else:
        print("- **Weighted beta:** N/A")

    if 'annual_vol' in active.columns and active['annual_vol'].notna().any():
        vol_col = active['annual_vol'].fillna(0.3)
        wvol = (active['weight'] * vol_col).sum()
        print(f"- **Weighted annualized vol:** {wvol*100:.0f}%")

    print(f"- **Top holding:** {active.iloc[0]['ticker']} at {active.iloc[0]['weight_pct']:.0f}%")
    print(f"- **Top 3:** {active.head(3)['weight'].sum()*100:.0f}%")

    # S&P comparison
    print()
    print("## vs S&P 500")
    print()
    print("This portfolio is concentrated in the highest-conviction names from the")
    print("alpha-picks factor model. It differs from the S&P 500 in key ways:")
    print()
    print("- **No passive weight** — every position is a STRONG BUY, not an index constituent")
    print("- **No healthcare/pharma** — excluded by design (binary risk)")
    print("- **No miners/basic materials** — excluded by design (commodity price risk)")
    print("- **Factor-driven** — allocation is proportional to model score, not market cap")
    print("- **Concentrated** — ~10 positions vs 500; higher upside and higher volatility")
    print()
    print("---")
    print(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*")


if __name__ == '__main__':
    main()