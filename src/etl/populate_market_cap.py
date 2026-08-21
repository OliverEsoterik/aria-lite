#!/usr/bin/env python3
"""
populate_market_cap.py - Fetch market cap from yfinance for all tickers in dim_entities
and store it in the market_cap column.

Usage: python3 populate_market_cap.py [--batch N] [--skip-existing]
  --batch N        Process N tickers per batch (default: 50)
  --skip-existing  Skip tickers that already have market_cap set
"""

import time
import os
import argparse
import yfinance as yf
from sqlalchemy import create_engine, text
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2:///alphapicks")
engine = create_engine(DB_URL, pool_pre_ping=True)


def fetch_market_cap(ticker):
    """Fetch market cap for a single ticker. Returns (ticker, market_cap) or (ticker, None)."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        mcap = info.get("marketCap")
        return (ticker, mcap)
    except Exception:
        return (ticker, None)


def main():
    parser = argparse.ArgumentParser(description="Populate market_cap in dim_entities")
    parser.add_argument("--batch", type=int, default=50, help="Tickers per batch (default: 50)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip tickers that already have market_cap")
    args = parser.parse_args()

    # Load tickers from dim_entities
    if args.skip_existing:
        query = "SELECT ticker FROM dim_entities WHERE market_cap IS NULL ORDER BY entity_pk ASC"
    else:
        query = "SELECT ticker FROM dim_entities ORDER BY entity_pk ASC"

    with engine.connect() as conn:
        result = conn.execute(text(query))
        tickers = [row[0] for row in result]

    total = len(tickers)
    print(f"Found {total} tickers to process.")

    updated = 0
    skipped = 0

    for i in range(0, total, args.batch):
        batch = tickers[i: i + args.batch]
        results = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_map = {executor.submit(fetch_market_cap, t): t for t in batch}
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as e:
                    print(f"  ! Error: {e}")
                    results.append((future_map[future], None))

        # Batch update
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

        print(f"  Batch {i // args.batch + 1}/{(total + args.batch - 1) // args.batch}: "
              f"{updated} updated, {skipped} skipped so far")

        time.sleep(1.5)  # Anti-throttling

    print(f"\nDone. Updated: {updated}, Skipped (no data): {skipped}")


if __name__ == "__main__":
    main()