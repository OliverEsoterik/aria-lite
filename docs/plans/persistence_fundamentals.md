# Concrete Implementation Plan: Persisting Fundamental Data

## 1. Database Schema
- **File:** `sql/02_create_fact_fundamentals.sql`
- **Definition:**
  ```sql
  CREATE TABLE IF NOT EXISTS fact_fundamentals (
      timestamp       TIMESTAMPTZ     NOT NULL,
      ticker_fk       INTEGER         NOT NULL,
      ticker          TEXT            NOT NULL, 
      forward_pe      NUMERIC,
      peg_ratio       NUMERIC,
      op_margin       NUMERIC,
      fcf_yield       NUMERIC,
      rev_growth      NUMERIC,
      roe             NUMERIC,
      debt_to_equity  NUMERIC,
      current_ratio   NUMERIC,
      eps_rev         NUMERIC,

      PRIMARY KEY (timestamp, ticker_fk),
      CONSTRAINT fk_entity FOREIGN KEY (ticker_fk) REFERENCES dim_entities(entity_pk)
  );
  SELECT create_hypertable('fact_fundamentals', 'timestamp', if_not_exists => TRUE);
  ```

## 2. Ingestion Script (`src/etl/02_fetch_fundamentals.py`)
- **Responsibility:**
  1. Retrieve the list of active tickers.
  2. Resolve the `ticker_fk` (referencing `dim_entities.entity_pk`) for each ticker symbol. 
     - *Design Guard:* Any ticker to be fetched must already exist in `dim_entities` to prevent `ForeignKeyViolation` errors.
  3. Batch iterate tickers and fetch statistics/fundamentals via `yfinance`.
  4. Write daily snapshots to `fact_fundamentals` with normalized daily `TIMESTAMPTZ` markers (matching the daily interval patterns used in `market_prices` and `statistics`).
  5. Bulk insert/upsert data using `pandas.to_sql` or direct SQLAlchemy expressions.
- **Dependency:** Only `pandas`, `yfinance`, and `sqlalchemy`.

## 3. Pipeline Adjustment & Renaming
To maintain the `00`-`04` sequence and ensure reference integrity:
- **Prerequisite:** `00_populate_entities.py` must support the new environment-driven dynamic `WATCHLIST` configuration so new tickers are seeded in `dim_entities` before the other scripts execute.
- **Renumbering:**
  - `src/etl/02_compute_statistics.py` -> `src/etl/03_compute_statistics.py`
  - `src/etl/03_generate_production_ratings.py` -> `src/etl/04_generate_production_ratings.py`

## 4. Consumption Logic (`src/etl/04_generate_production_ratings.py`)
- **Modification:**
  - Remove all direct `yfinance` API fetching logic.
  - Implement `pd.read_sql` to join `fact_fundamentals` (querying the latest daily timestamp snapshot for each `ticker_fk`) with `statistics` and `market_prices`.
  - Supply the unified dataset directly into the existing `assign_production_rating` scoring model in-memory.

## 5. Deployment & Orchestration
- `run_etl.sh` must execute the pipeline steps in this exact, dependent order:
  1. `00_populate_entities.py` (Seeds `dim_entities` using the `WATCHLIST`)
  2. `01_fetch_price_data.py` (Populates `market_prices`)
  3. `02_fetch_fundamentals.py` (Populates `fact_fundamentals` with resolved FKs)
  4. `03_compute_statistics.py` (Populates `statistics`)
  5. `04_generate_production_ratings.py` (Loads, evaluates, and ranks)
