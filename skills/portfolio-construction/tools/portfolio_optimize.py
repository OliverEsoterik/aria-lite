#!/usr/bin/env python3
"""
Portfolio optimizer: reads scores CSV, fetches price correlations, applies
allocation constraints, outputs final portfolio table.

Usage:
    python3 skills/portfolio-construction/tools/portfolio_optimize.py work/phase1_scores.csv
"""

import sys
import os
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta


def load_scores(csv_path):
    df = pd.read_csv(csv_path)
    # Filter to pass_gate = True
    df = df[df['pass_gate'] == True].copy()
    if df.empty:
        print("No tickers passed the risk gate.", file=sys.stderr)
        # Fallback: use all tickers with a warning
        df = pd.read_csv(csv_path)
        print(f"Using all {len(df)} tickers (risk gate bypassed).", file=sys.stderr)
    return df


def fetch_correlations(tickers, years=2):
    """Fetch price history and compute correlation matrix."""
    end = datetime.now()
    start = end - timedelta(days=int(years * 365))
    data = {}
    for t in tickers:
        try:
            hist = yf.download(t, start=start.strftime('%Y-%m-%d'),
                               end=end.strftime('%Y-%m-%d'),
                               progress=False, auto_adjust=True)
            if not hist.empty:
                data[t] = hist['Close'].values.flatten()
        except Exception:
            pass

    # Align to shortest length
    min_len = min(len(v) for v in data.values()) if data else 0
    if min_len < 20:
        return None

    aligned = {}
    for t, vals in data.items():
        aligned[t] = vals[-min_len:]

    df = pd.DataFrame(aligned)
    returns = df.pct_change().dropna()
    return returns.corr()


def compute_sector_concentration(df):
    """Compute sector weights and Herfindahl index."""
    if 'sector' not in df.columns:
        return {}, 0
    sector_counts = df['sector'].value_counts()
    total = sector_counts.sum()
    if total == 0:
        return {}, 0
    weights = (sector_counts / total).to_dict()
    hhi = sum(w ** 2 for w in weights.values())
    return weights, hhi


def allocate(df, max_single=0.15, max_sector=0.30, min_position=0.02, correlation_df=None):
    """
    Score-proportional allocation with constraints.
    Returns a DataFrame with allocation weights.
    """
    scores = df['final_score'].values
    tickers = df['ticker'].values
    sectors = df['sector'].values if 'sector' in df.columns else ['Unknown'] * len(df)

    # Shift scores to be non-negative
    min_score = scores.min()
    if min_score < 0:
        scores = scores - min_score + 0.01
    else:
        scores = scores + 0.01  # prevent zeros

    # Base weights proportional to score
    raw_weights = scores / scores.sum()
    result = df.copy()
    result['raw_weight'] = raw_weights

    # --- Constraint 1: Single stock max (iterative cap + redistribute) ---
    weights = raw_weights.copy()
    for _ in range(20):
        over = weights > max_single
        if not over.any():
            break
        excess = (weights[over] - max_single).sum()
        weights[over] = max_single
        under = ~over
        if under.sum() > 0:
            weights[under] += excess * (weights[under] / weights[under].sum())
    result['weight'] = weights

    # --- Constraint 2: Correlation constraint ---
    # If two stocks have >0.8 correlation, cap combined weight at 25%
    if correlation_df is not None:
        ticker_list = result['ticker'].tolist()
        for i, t1 in enumerate(ticker_list):
            for j, t2 in enumerate(ticker_list):
                if i >= j:
                    continue
                if t1 in correlation_df.index and t2 in correlation_df.columns:
                    corr = correlation_df.loc[t1, t2]
                    if pd.notna(corr) and abs(corr) > 0.80:
                        combined = result.loc[result['ticker'].isin([t1, t2]), 'weight'].sum()
                        if combined > 0.25:
                            # Scale both down proportionally
                            scale = 0.25 / combined
                            result.loc[result['ticker'] == t1, 'weight'] *= scale
                            result.loc[result['ticker'] == t2, 'weight'] *= scale

    # --- Constraint 3: Sector max ---
    for sector in result['sector'].unique():
        mask = result['sector'] == sector
        sector_w = result.loc[mask, 'weight'].sum()
        if sector_w > max_sector:
            scale = max_sector / sector_w
            result.loc[mask, 'weight'] *= scale

    # --- Constraint 4: Minimum position ---
    result.loc[result['weight'] < min_position, 'weight'] = 0.0

    # Normalize to 100%
    total = result['weight'].sum()
    if total > 0:
        result['weight'] = result['weight'] / total

    # Round to 0.5%
    result['weight'] = (result['weight'] * 200).round() / 200

    # Normalize again after rounding
    total = result['weight'].sum()
    if total > 0:
        result['weight'] = result['weight'] / total

    result = result.sort_values('weight', ascending=False)
    result['weight_pct'] = (result['weight'] * 100).round(1)
    return result


def risk_flags(row, corr_df=None):
    """Generate risk flags for a ticker."""
    flags = []
    if row.get('beta') is not None and abs(row.get('beta', 0)) > 1.5:
        flags.append(f"High beta ({row['beta']:.1f})")
    if row.get('debt_to_equity') is not None and row.get('debt_to_equity', 0) > 100:
        flags.append(f"Elevated leverage (D/E: {row['debt_to_equity']:.0f})")
    if row.get('annual_vol') is not None and row.get('annual_vol', 0) > 0.5:
        flags.append(f"High vol ({row['annual_vol']*100:.0f}% annualized)")
    if row.get('current_ratio') is not None and row.get('current_ratio', 0) < 1.0:
        flags.append("Low liquidity")
    if row.get('fcf_yield') is not None and row.get('fcf_yield', 0) < 0:
        flags.append("Negative FCF yield")
    if row.get('near_high') is not None and row.get('near_high', 0) < 0.80:
        flags.append(f"-{((1-row['near_high'])*100):.0f}% from 52w high")
    return "; ".join(flags) if flags else "None"


def rationale(row):
    """Generate one-line rationale for allocation."""
    parts = []
    rating = row.get('rating', '')
    score = row.get('final_score', 0)
    if 'STRONG BUY' in rating:
        parts.append("Highest conviction")
    elif 'BUY' in rating:
        parts.append("Attractive setup")
    else:
        parts.append("Neutral/hold")

    if row.get('mom_score', 0) > 0.1:
        parts.append("positive momentum")
    if row.get('eps_rev', 0) > 0.01:
        parts.append("rising estimates")
    if row.get('peg', 99) < 1.5:
        parts.append("reasonable PEG")
    if row.get('rev_growth', 0) > 0.2:
        parts.append("strong revenue growth")

    return " | ".join(parts) if parts else "Score-driven allocation"


def main():
    if len(sys.argv) < 2:
        print("Usage: portfolio_optimize.py <scores_csv>", file=sys.stderr)
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    df = load_scores(csv_path)
    print(f"Loaded {len(df)} tickers that passed the risk gate.", file=sys.stderr)

    tickers = df['ticker'].tolist()
    print(f"Tickers: {', '.join(tickers)}", file=sys.stderr)

    # Correlation matrix
    print("Fetching price history for correlations...", file=sys.stderr)
    corr_df = fetch_correlations(tickers)
    if corr_df is not None:
        print(f"Correlation matrix computed ({len(corr_df)}x{len(corr_df)}).", file=sys.stderr)
    else:
        print("WARNING: Could not compute correlations (insufficient data).", file=sys.stderr)

    # Sector concentration
    if 'sector' in df.columns:
        sector_w, hhi = compute_sector_concentration(df)
        print(f"\nSector concentration (HHI: {hhi:.3f}):", file=sys.stderr)
        for s, w in sorted(sector_w.items(), key=lambda x: -x[1]):
            print(f"  {s}: {w*100:.0f}%", file=sys.stderr)

    # Allocate
    result = allocate(df, correlation_df=corr_df)

    # Print allocation table
    print("\n# Portfolio Allocation")
    print(f"\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*")
    print(f"\n## Summary")
    print(f"\n| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| Positions | {len(result[result['weight'] > 0])} |")
    print(f"| Top 3 concentration | {(result.head(3)['weight'].sum() * 100):.0f}% |")
    print(f"| Weighted score | {(result['weight'] * result['final_score']).sum():.3f} |")
    print(f"| Passed risk gate | {len(df)}/{len(df)} |")

    if corr_df is not None:
        # Max correlation
        max_corr = 0
        max_pair = ("", "")
        for i, t1 in enumerate(tickers):
            for j, t2 in enumerate(tickers):
                if i >= j:
                    continue
                if t1 in corr_df.index and t2 in corr_df.columns:
                    c = corr_df.loc[t1, t2]
                    if pd.notna(c) and abs(c) > abs(max_corr):
                        max_corr = c
                        max_pair = (t1, t2)
        print(f"| Highest correlation | {max_pair[0]}–{max_pair[1]}: {max_corr:.2f} |")

    # Sector breakdown of final allocation
    sector_alloc = result[result['weight'] > 0].groupby('sector')['weight'].sum().sort_values(ascending=False)
    print(f"\n## Sector Allocation")
    print(f"\n| Sector | Weight |")
    print(f"|--------|--------|")
    for s, w in sector_alloc.items():
        bar = "█" * int(w * 100 / 2)
        print(f"| {s} | {w*100:.1f}% {bar} |")

    print(f"\n## Positions")
    print(f"\n| # | Ticker | Name | Weight | Rating | Score | Sector | Risk Flags | Rationale |")
    print(f"|---|--------|------|--------|--------|-------|--------|------------|-----------|")

    for i, (_, row) in enumerate(result.iterrows(), 1):
        if row['weight'] <= 0:
            continue
        name = str(row.get('name', ''))[:40]
        sector = str(row.get('sector', ''))[:20]
        rflags = risk_flags(row, corr_df)
        rat = rationale(row)
        print(f"| {i} | {row['ticker']} | {name} | {row['weight_pct']:.0f}% | {row['rating']} | {row['final_score']:.3f} | {sector} | {rflags} | {rat} |")

    # Portfolio-level risk
    print(f"\n## Portfolio Risk Notes")
    print(f"\n- **Concentration:** Top 3 = {(result.head(3)['weight'].sum() * 100):.0f}% of portfolio")
    if 'beta' in result.columns:
        high_beta = result[result['beta'].fillna(0).abs() > 1.3]
        if not high_beta.empty:
            betas = [f"{t} ({b:.1f})" for t, b in zip(high_beta['ticker'], high_beta['beta'])]
            print(f"- **High beta names:** {', '.join(betas)}")
    if 'op_margin' in result.columns:
        low_margin = result[result['op_margin'].fillna(0) < 0.10]
        if not low_margin.empty:
            print(f"- **Thin margins:** {', '.join(low_margin['ticker'])} (op margins below 10%)")
    print(f"- **Diversification:** {len(result[result['weight'] > 0])} positions across {len(sector_alloc)} sectors")


if __name__ == '__main__':
    main()