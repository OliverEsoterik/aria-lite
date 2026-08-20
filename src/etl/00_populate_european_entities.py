import requests
import psycopg2
import os
import sys
import time

# --- CONFIGURATION ---
EODHD_TOKEN = os.environ.get("EODHD_API_TOKEN")
if not EODHD_TOKEN:
    print("Error: EODHD_API_TOKEN environment variable not set.")
    sys.exit(1)

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT_EMAIL")
if not SEC_USER_AGENT:
    print("Error: SEC_USER_AGENT_EMAIL environment variable not set.")
    sys.exit(1)
HEADERS = {"User-Agent": SEC_USER_AGENT}
DB_URL = os.environ.get("DATABASE_URL", "postgresql:///alphapicks")

from european_ticker_config import EXCHANGE_CONFIG, get_suffix


def fetch_exchange_symbols(exchange_code: str) -> list:
    """Fetch active common stock symbols from EODHD for one exchange."""
    url = f"https://eodhd.com/api/exchange-symbol-list/{exchange_code}"
    params = {
        "api_token": EODHD_TOKEN,
        "fmt": "json",
        "type": "common_stock",
    }
    response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def load_european_data(exchange_filter: list = None):
    """
    Fetch and load European tickers into dim_entities.

    If exchange_filter is provided, only fetch those exchanges (for testing).
    """
    conn = None
    try:
        exchanges_to_fetch = EXCHANGE_CONFIG
        if exchange_filter:
            exchanges_to_fetch = [
                ec for ec in EXCHANGE_CONFIG if ec[0] in exchange_filter
            ]
            if not exchanges_to_fetch:
                print(f"Warning: no matching exchanges for filter {exchange_filter}")
                return

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        total_upserted = 0
        total_fetched = 0

        for exchange_code, country_map, default_suffix in exchanges_to_fetch:
            print(f"Fetching {exchange_code}...", end=" ", flush=True)
            symbols = None
            for attempt in range(2):
                try:
                    symbols = fetch_exchange_symbols(exchange_code)
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == 0:
                        print(f"retrying...", end=" ", flush=True)
                        time.sleep(1)
                        continue
                    print(f"FAILED: {e}")
                    break
            if symbols is None:
                continue

            # Filter to Common Stock / Preferred Stock only
            symbols = [s for s in symbols if s.get("Type", "").lower()
                       in ("common stock", "preferred stock")]

            print(f"{len(symbols)} tickers", end="", flush=True)
            total_fetched += len(symbols)

            skipped = 0
            records = []
            for sym in symbols:
                code = sym.get("Code", "")
                isin = sym.get("Isin", "")
                name = sym.get("Name", "")
                country = sym.get("Country", "")

                if not code or not isin:
                    skipped += 1
                    continue

                suffix = get_suffix(exchange_code, country)
                ticker = f"{code}{suffix}"

                records.append((isin, ticker, name))

            if skipped > 0:
                print(f" ({skipped} skipped, no ISIN)")

            if not records:
                print(" → 0 upserted")
                continue

            sql = """
                INSERT INTO dim_entities (entity_identifier, ticker, company_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (entity_identifier, ticker)
                DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    dw_loaded_at = CURRENT_TIMESTAMP;
            """

            cur.executemany(sql, records)
            conn.commit()

            total_upserted += len(records)
            print(f" → {len(records)} upserted")

        print(f"\nDone. Fetched: {total_fetched}, Upserted: {total_upserted}")
        cur.close()

    except psycopg2.Error as e:
        print(f"\nDatabase Error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"\nError: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Optional: limit to specific exchanges for testing
    # Usage: python3 00_populate_european_entities.py --exchanges WAR,STO
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchanges", type=str, default=None,
                        help="Comma-separated exchange codes to fetch (default: all)")
    args = parser.parse_args()

    exchange_filter = args.exchanges.split(",") if args.exchanges else None
    load_european_data(exchange_filter)
