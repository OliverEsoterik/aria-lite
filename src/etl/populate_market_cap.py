#!/usr/bin/env python3
"""
populate_market_cap.py - Fetch market cap from yfinance for all tickers in dim_entities
and store it in the market_cap column.

Usage: python3 populate_market_cap.py [--batch N] [--refresh-all]
  --batch N        Process N tickers per batch (default: 50)
  --refresh-all    Re-fetch market cap for ALL tickers (default: only missing ones)
"""

import time
import os
import argparse
import yfinance as yf
from sqlalchemy import create_engine, text
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
engine = create_engine(DB_URL, pool_pre_ping=True)


# Proactive request counter to stay under yfinance crumb expiry (~1800-2000 requests).
REQUEST_COUNTER = 0
REQUEST_LIMIT = 1900
COOLDOWN_SECONDS = 180


def refresh_yfinance_session():
    """Force yfinance to get a fresh crumb/session."""
    try:
        if hasattr(yf, 'shared') and hasattr(yf.shared, '_session'):
            yf.shared._session = None
    except Exception:
        pass


def fetch_market_cap(ticker):
    """Fetch market cap for a single ticker. Returns (ticker, market_cap) or (ticker, None)."""
    global REQUEST_COUNTER
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        REQUEST_COUNTER += 1
        mcap = info.get("marketCap")
        return (ticker, mcap)
    except Exception:
        return (ticker, None)


def main():
    parser = argparse.ArgumentParser(description="Populate market_cap in dim_entities")
    parser.add_argument("--batch", type=int, default=50, help="Tickers per batch (default: 50)")
    parser.add_argument("--refresh-all", action="store_true",
                        help="Re-fetch market cap for all tickers (default: only missing)")
    args = parser.parse_args()

    # Default: skip tickers that already have market_cap, and only process tickers
    # that exist in market_prices (tickers with no price data can't pass the pipeline anyway).
    # Use --refresh-all to re-process everything that has price data.
    if args.refresh_all:
        query = """
            SELECT ticker FROM dim_entities
            WHERE ticker IN (SELECT DISTINCT ticker FROM market_prices)
            ORDER BY entity_pk ASC
        """
        print("Refresh-all mode: processing ALL tickers with price data...")
    else:
        query = """
            SELECT ticker FROM dim_entities
            WHERE market_cap IS NULL
              AND ticker IN (SELECT DISTINCT ticker FROM market_prices)
            ORDER BY entity_pk ASC
        """
        print("Default mode: processing only tickers with price data and missing market_cap.")

    with engine.connect() as conn:
        result = conn.execute(text(query))
        tickers = [row[0] for row in result]

    total = len(tickers)
    print(f"Found {total} tickers to process.")

    global REQUEST_COUNTER
    updated = 0
    skipped = 0

    i = 0
    while i < total:
        batch = tickers[i: i + args.batch]

        # Proactive cooldown: before this batch would push us over the limit,
        # pause and refresh the session. This prevents 401s entirely.
        if REQUEST_COUNTER >= REQUEST_LIMIT:
            print(f"  Proactive cooldown: {REQUEST_COUNTER} requests made, "
                  f"pausing {COOLDOWN_SECONDS}s to refresh yfinance session...")
            refresh_yfinance_session()
            time.sleep(COOLDOWN_SECONDS)
            REQUEST_COUNTER = 0

        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_map = {executor.submit(fetch_market_cap, t): t for t in batch}
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as e:
                    print(f"  ! Error: {e}")
                    results.append((future_map[future], None))

        # Commit batch results
        with engine.begin() as conn:
            for ticker, mcap in results:
                if mcap is not None and mcap > 0:
                    conn.execute(
                        text("UPDATE dim_entities SET market_cap = :mcap WHERE ticker = :ticker"),
                        {"mcap": mcap, "ticker": ticker}
                    )
                    updated += 1
                else:
                    skipped += 1

        batch_num = i // args.batch + 1
        total_batches = (total + args.batch - 1) // args.batch
        print(f"  Batch {batch_num}/{total_batches}: "
              f"{updated} updated, {skipped} skipped so far")

        time.sleep(3.0)
        i += args.batch

    print(f"\nDone. Updated: {updated}, Skipped (no data): {skipped}")


if __name__ == "__main__":
    main()