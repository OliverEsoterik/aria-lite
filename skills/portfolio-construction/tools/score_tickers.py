#!/usr/bin/env python3
"""
Score a list of tickers using the alpha-picks factor model.
Replicates the logic from 03_generate_production_ratings.py without
requiring a database connection (falls back to yfinance for price history).

Usage:
    python3 skills/portfolio-construction/tools/score_tickers.py SNDK LITE MU TER VICR WDC STX AGX CLS STRL CRDO
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src/etl"))
from common import yang_zhang_vol, RiskGate, assign_rating, z_score, ANNUALIZATION_FACTOR
import math
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta



# --- Risk Gate ---
# --- Fundamentals ---
def get_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or info.get('regularMarketPrice') is None and info.get('currentPrice') is None:
            return None

        fwd_pe = info.get('forwardPE', 0) or 0
        peg = info.get('pegRatio')

        # Institutional PEG proxy
        if peg is None or peg == 0:
            f_eps = info.get('forwardEps', 0) or 0
            t_eps = info.get('trailingEps', 0) or 0
            if f_eps > 0 and t_eps > 0:
                eps_growth = ((f_eps / t_eps) - 1) * 100
                peg = fwd_pe / eps_growth if eps_growth > 2.0 else 99.0
            else:
                peg = 99.0

        fcf = info.get('freeCashflow')
        mcap = info.get('marketCap')
        fcf_yield = 0.0
        if fcf and mcap and mcap > 0:
            fcf_yield = fcf / mcap

        # Analyst revisions
        eps_rev_val = 0.0
        try:
            trend = stock.eps_trend
            if trend is not None and '0y' in trend.index:
                rev_row = trend.loc['0y']
                curr = rev_row.get('current') if isinstance(rev_row, dict) else getattr(rev_row, 'current', None)
                ago30 = rev_row.get('30daysAgo') if isinstance(rev_row, dict) else getattr(rev_row, '30daysAgo', None)
                if curr and ago30 and ago30 != 0:
                    eps_rev_val = (curr / ago30) - 1
        except Exception:
            pass

        current_price = info.get('currentPrice') or info.get('regularMarketPrice', 0)
        sector = info.get('sector', 'Unknown')
        industry = info.get('industry', 'Unknown')
        long_name = info.get('longName') or info.get('shortName', ticker)

        return {
            'ticker': ticker,
            'name': long_name,
            'sector': sector,
            'industry': industry,
            'current_price': current_price,
            'peg': round(peg, 3) if peg else 99.0,
            'fcf_yield': round(fcf_yield, 4),
            'fwd_pe': fwd_pe,
            'trl_eps': info.get('trailingEps', 0),
            'op_margin': info.get('operatingMargins', 0),
            'profit_margin': info.get('profitMargins', 0),
            'rev_growth': info.get('revenueGrowth', 0),
            'roe': info.get('returnOnEquity', 0),
            'debt_to_equity': info.get('debtToEquity', 0),
            'current_ratio': info.get('currentRatio', 0),
            'eps_rev': eps_rev_val,
            'beta': info.get('beta'),
            'market_cap': mcap,
        }
    except Exception as e:
        print(f"  [WARN] Failed to fetch {ticker}: {e}", file=sys.stderr)
        return None


# --- Momentum from yfinance price history ---
def get_momentum(ticker):
    try:
        end = datetime.now()
        start = end - timedelta(days=400)
        hist = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                           end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
        if hist.empty or len(hist) < 63:
            return None

        close = hist['Close'].values.flatten()
        n = len(close)

        # Build OHLC DataFrame for Yang-Zhang volatility estimator
        yz_df = pd.DataFrame({
            'price_open': hist['Open'].values.flatten(),
            'price_high': hist['High'].values.flatten(),
            'price_low': hist['Low'].values.flatten(),
            'price_close': close,
        })
        vol = yang_zhang_vol(yz_df, period=n, min_periods=10).iloc[-1]

        # Keep returns for quality metric and momentum
        returns = np.diff(close) / close[:-1]

        p_now = close[-1]
        p_1m = close[-22] if n >= 22 else close[0]
        p_3m = close[-63] if n >= 63 else close[0]
        p_6m = close[-126] if n >= 126 else close[0]
        p_12m = close[-252] if n >= 252 else close[0]

        # Multi-lookback momentum (skip last month to avoid reversal)
        mom_3m = (p_1m / p_3m) - 1
        mom_6m = (p_1m / p_6m) - 1
        mom_12m = (p_1m / p_12m) - 1

        # Combined momentum (weighted across lookbacks)
        mom_combined = 0.3 * mom_3m + 0.3 * mom_6m + 0.4 * mom_12m

        adj_mom = mom_combined / (vol + 1e-6)

        # Acceleration (now includes last month to capture freshness)
        acceleration = (p_now / p_3m) - 1 - mom_12m

        pos_days = np.sum(returns > 0)
        neg_days = np.sum(returns < 0)
        inf_discr = np.sign(mom_12m) * (abs(pos_days - neg_days) / n)

        # RSI-14
        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # Average volume (20-day)
        vol_20 = np.mean(hist['Volume'].values[-20:].flatten()) if n >= 20 else np.mean(hist['Volume'].values.flatten())

        return {
            'ticker': ticker,
            'mom_score': adj_mom,
            'mom_quality': inf_discr,
            'acceleration': acceleration,
            'annual_vol': vol,
            'near_high': p_now / np.max(close),
            'mom_3m': mom_3m,
            'mom_6m': mom_6m,
            'rsi_14': rsi,
            'vol_20': vol_20,
        }
    except Exception as e:
        print(f"  [WARN] Momentum failed for {ticker}: {e}", file=sys.stderr)
        return None


# --- Rating ---
# --- Main ---
def main():
    tickers = [t.upper().strip() for t in sys.argv[1:] if t.strip()]
    if not tickers:
        print("Usage: score_tickers.py TICKER [TICKER ...]", file=sys.stderr)
        sys.exit(1)

    print(f"Scoring {len(tickers)} tickers...", file=sys.stderr)

    # Phase 1: Fundamentals
    print("Fetching fundamentals...", file=sys.stderr)
    fund_rows = []
    for t in tickers:
        print(f"  {t}...", file=sys.stderr)
        row = get_fundamentals(t)
        if row:
            fund_rows.append(row)

    if not fund_rows:
        print("No data fetched for any ticker.", file=sys.stderr)
        sys.exit(1)

    fund_df = pd.DataFrame(fund_rows)

    # Phase 2: Momentum
    print("Fetching momentum data...", file=sys.stderr)
    mom_rows = []
    for t in tickers:
        print(f"  {t}...", file=sys.stderr)
        m = get_momentum(t)
        if m:
            mom_rows.append(m)

    mom_df = pd.DataFrame(mom_rows) if mom_rows else pd.DataFrame()

    # Merge
    merged = fund_df
    if not mom_df.empty:
        merged = fund_df.merge(mom_df, on='ticker', how='left')

    # Fill missing momentum
    for col in ['mom_score', 'mom_quality', 'acceleration', 'annual_vol', 'near_high', 'mom_3m', 'rsi_14', 'vol_20']:
        if col not in merged.columns:
            merged[col] = 0

    # Z-score normalization
    # z_score is imported from common
        return (s - s.mean()) / (s.std() + 1e-6)

    merged['z_mom_risk_adj'] = z_score(merged['mom_score'].fillna(0))
    merged['z_mom_qual'] = z_score(merged['mom_quality'].fillna(0))
    merged['z_accel'] = z_score(merged['acceleration'].fillna(0))
    merged['z_eps'] = z_score(merged['eps_rev'].fillna(0))

    merged['z_state'] = (
        z_score(merged['rsi_14'].fillna(50)) * -0.5
        + z_score(merged['vol_20'].fillna(0)) * 0.5
    )

    merged['s_qual'] = (
        merged['rev_growth'].fillna(0).clip(0, 0.4) / 0.4 * 0.5
        + merged['op_margin'].fillna(0).clip(0, 0.3) / 0.3 * 0.5
    )

    # Final score
    merged['final_score'] = (
        merged['z_mom_risk_adj'] * 0.25
        + merged['z_mom_qual'] * 0.25
        + merged['z_accel'] * 0.05
        + merged['s_qual'] * 0.30
        + merged['z_eps'] * 0.10
        + merged['z_state'] * 0.05
    )

    # Risk Gate
    gate = RiskGate()
    merged['pass_gate'] = merged.apply(gate.is_pass, axis=1)

    # Rating
    merged['rating'] = merged.apply(assign_rating, axis=1)

    # Sort by score descending
    merged = merged.sort_values('final_score', ascending=False)

    # Output CSV
    cols = [
        'ticker', 'name', 'sector', 'industry', 'rating', 'final_score',
        'pass_gate', 'current_price', 'fwd_pe', 'peg', 'eps_rev',
        'mom_score', 'mom_quality', 'acceleration', 'rev_growth',
        'op_margin', 'profit_margin', 'roe', 'debt_to_equity',
        'current_ratio', 'fcf_yield', 'beta', 'market_cap',
        'annual_vol', 'near_high', 'rsi_14',
    ]
    available_cols = [c for c in cols if c in merged.columns]
    merged[available_cols].to_csv(sys.stdout, index=False)

    # Also print summary to stderr
    print(f"\n--- Summary ---", file=sys.stderr)
    for _, row in merged.iterrows():
        gate_status = "PASS" if row['pass_gate'] else "FAIL"
        print(f"  {row['ticker']:6s} | {row['rating']:30s} | score={row['final_score']:.3f} | gate={gate_status}",
              file=sys.stderr)


if __name__ == '__main__':
    main()