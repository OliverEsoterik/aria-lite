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


def refresh_yfinance_session():
    """Force yfinance to get a fresh crumb/session."""
    try:
        # Clear the cached session so yfinance creates a new one
        if hasattr(yf, 'shared') and hasattr(yf.shared, '_session'):
            yf.shared._session = None
    except Exception:
        pass


def fetch_market_cap(ticker, max_retries=3):
    """Fetch market cap for a single ticker. Retries on 401 with backoff."""
    import requests
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            mcap = info.get("marketCap")
            return (ticker, mcap)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 2)  # 4s, 8s, 16s
                print(f"  ! 401 on {ticker}, retrying in {wait}s (attempt {attempt + 2}/{max_retries})...")
                # Force a fresh session before retry
                refresh_yfinance_session()
                time.sleep(wait)
                continue
            return (ticker, None)
        except Exception:
            return (ticker, None)
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

    i = 0
    while i < total:
        batch = tickers[i: i + args.batch]

        # Batch-level retry loop: when yfinance session expires (all 401s),
        # wait and retry the same batch instead of skipping those tickers.
        batch_retries = 0
        max_batch_retries = 5
        final_results = None

        while batch_retries <= max_batch_retries:
            results = []

            with ThreadPoolExecutor(max_workers=5) as executor:
                future_map = {executor.submit(fetch_market_cap, t): t for t in batch}
                for future in as_completed(future_map):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        print(f"  ! Error: {e}")
                        results.append((future_map[future], None))

            batch_failures = sum(1 for _, mcap in results if mcap is None)
            fail_rate = batch_failures / len(batch) if batch else 0

            batch_num = i // args.batch + 1
            total_batches = (total + args.batch - 1) // args.batch

            # If nearly all failed, retry the batch after a long cooldown
            if fail_rate >= 0.9 and batch_retries < max_batch_retries:
                batch_retries += 1
                cooldown = 15 * (2 ** (batch_retries - 1))  # 15s, 30s, 60s, 120s, 240s
                print(f"  Batch {batch_num}/{total_batches}: {batch_failures}/{len(batch)} failed, "
                      f"retry {batch_retries}/{max_batch_retries} after {cooldown}s cooldown...")
                refresh_yfinance_session()
                time.sleep(cooldown)
            else:
                # Accept this result — good enough or gave up after max retries
                final_results = results
                time.sleep(3.0)
                break

        # If we exhausted retries without ever accepting, use the last result
        if final_results is None:
            final_results = results

        # Commit whatever we got for this batch (only once)
        with engine.begin() as conn:
            for ticker, mcap in final_results:
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

        i += args.batch

    print(f"\nDone. Updated: {updated}, Skipped (no data): {skipped}")


if __name__ == "__main__":
    main()