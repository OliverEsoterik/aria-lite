CREATE TABLE dim_entities (
    entity_pk BIGSERIAL PRIMARY KEY,

    entity_identifier TEXT NOT NULL UNIQUE, 
    ticker TEXT NOT NULL,
    company_name TEXT NOT NULL,
    state_of_incorporation TEXT, 
    sic_code TEXT, 
    sector TEXT, 
    industry TEXT, 

    first_filing_id TEXT,

    dw_loaded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE market_prices (
    timestamp       TIMESTAMPTZ     NOT NULL,
    ticker_fk       INTEGER         NOT NULL, -- FK definition moved to bottom for clarity
    ticker          TEXT            NOT NULL, 
    price_open      NUMERIC(24, 8),
    price_high      NUMERIC(24, 8),
    price_low       NUMERIC(24, 8),
    price_close     NUMERIC(24, 8)  NOT NULL,
    price_adjusted  NUMERIC(24, 8),
    volume          NUMERIC(24, 8),
    source          TEXT,
    inserted_at     TIMESTAMPTZ     DEFAULT NOW(),

    -- Constraints
    CONSTRAINT market_prices_pkey PRIMARY KEY (time, ticker_fk),
    CONSTRAINT fk_entity FOREIGN KEY (ticker_fk) REFERENCES dim_entities(entity_pk)
);


-- Convert the standard table into a TimescaleDB Hypertable
-- This partitions the data by 'time' (the first argument)
SELECT create_hypertable('market_prices', 'time');
-- 2. Enable Compression
-- This is critical. It turns rows into columns (columnar storage) 
-- and typically reduces your disk usage by 90%+.
ALTER TABLE market_prices SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'ticker_fk',
  timescaledb.compress_orderby = 'time DESC'
);

-- 3. Add a Compression Policy
-- Automatically compress data older than 30 days
SELECT add_compression_policy('market_prices', INTERVAL '30 days');

CREATE TABLE statistics (
    timestamp       TIMESTAMP WITH TIME ZONE NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    
    -- Technical Indicators
    rsi_14          DOUBLE PRECISION,
    sma_252         DOUBLE PRECISION,
    
    -- Return & Risk Metrics
    log_return      DOUBLE PRECISION,
    vol_20          DOUBLE PRECISION,
    mdd_20          DOUBLE PRECISION,
    
    -- Shape/Distribution Metrics
    skew_20         DOUBLE PRECISION,
    kurt_20         DOUBLE PRECISION,

    PRIMARY KEY (timestamp, ticker)
);

-- Convert to Hypertable for performance on time-series queries
SELECT create_hypertable('statistics', 'timestamp', if_not_exists => TRUE);

-- Create an index on ticker for faster per-stock lookups
CREATE INDEX IF NOT EXISTS idx_stats_ticker_ts ON statistics (ticker, timestamp DESC);
