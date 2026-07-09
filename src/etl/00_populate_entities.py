import requests
import psycopg2
import sys
import os

# --- CONFIGURATION ---
URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_EMAIL = os.environ.get("SEC_EMAIL", "oliver.esoterik@gmail.com")
HEADERS = {"User-Agent": SEC_EMAIL}

# Dynamically connect to the local Unix socket DB
DB_URL = os.environ.get("DATABASE_URL", "postgresql:///alphapicks")

def load_sec_data():
    conn = None
    try:
        # 1. Fetch Data from SEC
        print(f"Fetching data from {URL}...")
        response = requests.get(URL, headers=HEADERS)
        response.raise_for_status() # Raise error for bad status codes
        
        json_payload = response.json()
        
        # Verify structure matches expectations based on the prompt
        # fields: ["cik", "name", "ticker", "exchange"]
        # indices:   0       1       2         3
        data_rows = json_payload.get('data', [])
        
        print(f"Successfully fetched {len(data_rows)} rows. preparing data...")

        # 2. Transform Data
        records_to_insert = []
        for row in data_rows:
            # Map CIK to entity_identifier and fill with zeros to 10 digits
            raw_cik = row[0]
            entity_identifier = str(raw_cik).zfill(10)
            
            company_name = row[1]
            ticker = row[2]
            
            # Create a tuple for the SQL query
            records_to_insert.append((entity_identifier, ticker, company_name))

        # 3. Connect to Database
        print("Connecting to database...")
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # 4. Insert/Update Data
        sql = """
            INSERT INTO dim_entities (entity_identifier, ticker, company_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (entity_identifier) 
            DO UPDATE SET 
                ticker = EXCLUDED.ticker,
                company_name = EXCLUDED.company_name,
                dw_loaded_at = CURRENT_TIMESTAMP;
        """

        print(f"Inserting/Updating {len(records_to_insert)} records...")
        cur.executemany(sql, records_to_insert)
        
        conn.commit()
        print("Success! Data loaded committed.")
        
        cur.close()

    except requests.exceptions.RequestException as e:
        print(f"Network Error: {e}")
    except psycopg2.Error as e:
        print(f"Database Error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"General Error: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    load_sec_data()
