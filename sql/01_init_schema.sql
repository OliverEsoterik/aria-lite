CREATE TABLE IF NOT EXISTS dim_entities (
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

CREATE TABLE IF NOT EXISTS market_prices (
    timestamp       TIMESTAMPTZ     NOT NULL,
    ticker_fk       INTEGER         NOT NULL,
    ticker          TEXT            NOT NULL, 
    price_open      NUMERIC(24, 8),
    price_high      NUMERIC(24, 8),
    price_low       NUMERIC(24, 8),
    price_close     NUMERIC(24, 8)  NOT NULL,
    price_adjusted  NUMERIC(24, 8),
    volume          NUMERIC(24, 8),
    source          TEXT,
    inserted_at     TIMESTAMPTZ     DEFAULT NOW(),

    CONSTRAINT market_prices_pkey PRIMARY KEY (timestamp, ticker_fk),
    CONSTRAINT fk_entity FOREIGN KEY (ticker_fk) REFERENCES dim_entities(entity_pk)
);

-- Convert to Hypertable safely
SELECT create_hypertable('market_prices', 'timestamp', if_not_exists => TRUE);

-- Configure Compression safely
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables 
        WHERE hypertable_name = 'market_prices' AND compression_enabled = true
    ) THEN
        ALTER TABLE market_prices SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'ticker_fk',
            timescaledb.compress_orderby = 'timestamp DESC'
        );
        PERFORM add_compression_policy('market_prices', INTERVAL '30 days');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS statistics (
    timestamp       TIMESTAMP WITH TIME ZONE NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    
    rsi_14          DOUBLE PRECISION,
    sma_252         DOUBLE PRECISION,
    
    log_return      DOUBLE PRECISION,
    vol_20          DOUBLE PRECISION,
    mdd_20          DOUBLE PRECISION,
    
    skew_20         DOUBLE PRECISION,
    kurt_20         DOUBLE PRECISION,

    PRIMARY KEY (timestamp, ticker)
);

SELECT create_hypertable('statistics', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_stats_ticker_ts ON statistics (ticker, timestamp DESC);
