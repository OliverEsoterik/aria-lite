#!/usr/bin/env python3
"""
Deep research on a single ticker: financial data, business summary, key ratios,
insider transactions, institutional holders, earnings history.

Outputs structured markdown to stdout.

Usage:
    python3 skills/portfolio-construction/tools/research_ticker.py SNDK
"""

import sys
import json
import yfinance as yf
from datetime import datetime


def fmt(n, suffix=''):
    if n is None:
        return 'N/A'
    if isinstance(n, str):
        return n
    if suffix == '$':
        if abs(n) >= 1_000_000_000_000:
            return f'${n/1_000_000_000_000:.1f}T'
        if abs(n) >= 1_000_000_000:
            return f'${n/1_000_000_000:.1f}B'
        if abs(n) >= 1_000_000:
            return f'${n/1_000_000:.1f}M'
        if abs(n) >= 1_000:
            return f'${n/1_000:.1f}K'
        return f'${n:.2f}'
    if abs(n) >= 1_000_000_000_000:
        return f'{n/1_000_000_000_000:.1f}T'
    if abs(n) >= 1_000_000_000:
        return f'{n/1_000_000_000:.1f}B'
    if abs(n) >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if abs(n) >= 1_000:
        return f'{n/1_000:.1f}K'
    return f'{n:.2f}'


def pct(n):
    if n is None:
        return 'N/A'
    return f'{n*100:.1f}%'


def main():
    if len(sys.argv) < 2:
        print("Usage: research_ticker.py TICKER", file=sys.stderr)
        sys.exit(1)

    ticker = sys.argv[1].upper().strip()
    stock = yf.Ticker(ticker)
    info = stock.info

    if not info or info.get('regularMarketPrice') is None and info.get('currentPrice') is None:
        print(f"# {ticker} — Research Brief")
        print(f"\n**No data available.** The ticker may be invalid or delisted.")
        sys.exit(0)

    price = info.get('currentPrice') or info.get('regularMarketPrice', 'N/A')
    name = info.get('longName') or info.get('shortName', ticker)
    sector = info.get('sector', 'N/A')
    industry = info.get('industry', 'N/A')
    summary = info.get('longBusinessSummary', 'No summary available.')

    print(f"# {ticker} — Research Brief")
    print(f"**{name}** | Sector: {sector} | Industry: {industry}")
    print(f"\n## Business Summary")
    print(f"\n{summary}")

    # Key Metrics
    print(f"\n## Key Financial Metrics")
    print(f"\n| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| Current Price | {fmt(price, '$')} |")
    print(f"| Market Cap | {fmt(info.get('marketCap'), '$')} |")
    print(f"| Enterprise Value | {fmt(info.get('enterpriseValue'), '$')} |")
    print(f"| Trailing P/E | {fmt(info.get('trailingPE'))} |")
    print(f"| Forward P/E | {fmt(info.get('forwardPE'))} |")
    print(f"| PEG Ratio | {fmt(info.get('pegRatio'))} |")
    print(f"| Price/Book | {fmt(info.get('priceToBook'))} |")
    print(f"| EPS (TTM) | {fmt(info.get('trailingEps'), '$')} |")
    print(f"| Revenue Growth | {pct(info.get('revenueGrowth'))} |")
    print(f"| Gross Margin | {pct(info.get('grossMargins'))} |")
    print(f"| Operating Margin | {pct(info.get('operatingMargins'))} |")
    print(f"| Profit Margin | {pct(info.get('profitMargins'))} |")
    print(f"| ROE | {pct(info.get('returnOnEquity'))} |")
    print(f"| ROA | {pct(info.get('returnOnAssets'))} |")
    print(f"| FCF Yield | {pct(info.get('freeCashflow') / info.get('marketCap', 1) if info.get('freeCashflow') and info.get('marketCap') else 0)} |")
    print(f"| Dividend Yield | {pct(info.get('dividendYield'))} |")
    print(f"| Beta (5Y) | {fmt(info.get('beta'))} |")

    # Balance Sheet
    print(f"\n## Balance Sheet Health")
    print(f"\n| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| Debt/Equity | {fmt(info.get('debtToEquity'))} |")
    print(f"| Current Ratio | {fmt(info.get('currentRatio'))} |")
    print(f"| Quick Ratio | {fmt(info.get('quickRatio'))} |")
    print(f"| Cash & Equivalents | {fmt(info.get('totalCash'), '$')} |")
    print(f"| Total Debt | {fmt(info.get('totalDebt'), '$')} |")
    print(f"| Net Debt | {fmt(info.get('netDebt'), '$')} |")
    print(f"| Book Value/Share | {fmt(info.get('bookValue'), '$')} |")

    # 52-week range
    print(f"\n## Technical")
    print(f"\n| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| 52-Week High | {fmt(info.get('fiftyTwoWeekHigh'), '$')} |")
    print(f"| 52-Week Low | {fmt(info.get('fiftyTwoWeekLow'), '$')} |")
    print(f"| Avg Volume (3M) | {fmt(info.get('averageVolume'))} |")
    print(f"| Short Ratio | {fmt(info.get('shortRatio'))} |")
    print(f"| Short % of Float | {pct(info.get('shortPercentOfFloat'))} |")

    # Institutional & Insider
    print(f"\n## Ownership")
    print(f"\n| Metric | Value |")
    print(f"|--------|-------|")
    print(f"| Institutional Ownership | {pct(info.get('heldPercentInstitutions'))} |")
    print(f"| Insider Ownership | {pct(info.get('heldPercentInsiders'))} |")

    # Insider Transactions
    try:
        insider_txns = stock.insider_transactions
        if insider_txns is not None and not insider_txns.empty:
            print(f"\n## Recent Insider Transactions")
            print(f"\n| Date | Insider | Transaction | Shares | Value |")
            print(f"|------|---------|-------------|--------|-------|")
            for _, txn in insider_txns.head(10).iterrows():
                txn_date = txn.get('startDate', '') or txn.get('date', '') or ''
                if hasattr(txn_date, 'strftime'):
                    txn_date = txn_date.strftime('%Y-%m-%d')
                insider = txn.get('insider', {}).get('name', '') if isinstance(txn.get('insider'), dict) else str(txn.get('insider', ''))
                transaction = txn.get('transaction', '') or txn.get('type', '') or ''
                shares = txn.get('shares', '') or ''
                value = txn.get('value', '') or ''
                if shares:
                    shares = f'{int(shares):,}' if shares else ''
                if value:
                    value = f'${float(value):,.0f}' if value else ''
                print(f"| {txn_date} | {insider} | {transaction} | {shares} | {value} |")
    except Exception:
        pass

    # Earnings History
    try:
        earnings = stock.earnings_dates
        if earnings is not None and not earnings.empty:
            print(f"\n## Recent Earnings Reports")
            print(f"\n| Date | Actual EPS | Estimated EPS | Surprise |")
            print(f"|------|-----------|---------------|----------|")
            for _, e in earnings.head(8).iterrows():
                e_date = e.name
                if hasattr(e_date, 'strftime'):
                    e_date = e_date.strftime('%Y-%m-%d')
                actual = fmt(e.get('eps_actual', 'N/A'), '$')
                estimate = fmt(e.get('eps_estimate', 'N/A'), '$')
                surprise = e.get('eps_surprise', '') or e.get('surprisePercent', '')
                if isinstance(surprise, (int, float)):
                    surprise = f'{float(surprise)*100:.1f}%' if abs(float(surprise)) < 1 else f'{float(surprise):.1f}%'
                print(f"| {e_date} | {actual} | {estimate} | {surprise} |")
    except Exception:
        pass

    # Institutional Holders
    try:
        holders = stock.institutional_holders
        if holders is not None and not holders.empty:
            print(f"\n## Top Institutional Holders")
            print(f"\n| Holder | Shares | Value |")
            print(f"|--------|--------|-------|")
            for _, h in holders.head(10).iterrows():
                holder = h.get('holder', '') or ''
                shares = h.get('shares', 0) or 0
                value = h.get('value', 0) or 0
                print(f"| {holder} | {int(shares):,} | ${float(value):,.0f} |")
    except Exception:
        pass

    print(f"\n---")
    print(f"*Report generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*")


if __name__ == '__main__':
    main()