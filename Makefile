.PHONY: setup start-db stop-db stop status migrate run ratings tsmom tsmom-weights tsmom-positions clean \
	hmm-train-regime hmm-predict-regime hmm-train-trend hmm-train-trend-all \
	hmm-predict-trend hmm-predict-trend-all

SEC_USER_AGENT_EMAIL ?= your.email@address.com

setup: start-db migrate
	SEC_USER_AGENT_EMAIL=$(SEC_USER_AGENT_EMAIL) ./scripts/run_etl.sh

start-db:
	@if [ ! -d "$(DB_PATH)" ]; then \
		echo "Initializing database cluster..."; \
		initdb -D $(DB_PATH) --auth=trust --no-locale --encoding=UTF8; \
		echo "shared_preload_libraries = 'timescaledb'" >> $(DB_PATH)/postgresql.conf; \
	fi
	@if ! pg_isready -h $(PGHOST) -p $(PGPORT) > /dev/null 2>&1; then \
		echo "Starting PostgreSQL..."; \
		pg_ctl -D $(DB_PATH) -l $(DB_PATH)/logfile -o "-F -p $(PGPORT) -k $(PGHOST)" start; \
		sleep 2; \
	else \
		echo "PostgreSQL is already running."; \
	fi
	@psql -h $(PGHOST) -p $(PGPORT) -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'alphapicks'" | grep -q 1 || createdb -h $(PGHOST) -p $(PGPORT) alphapicks
	@psql -h $(PGHOST) -p $(PGPORT) -d alphapicks -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

stop: stop-db

stop-db:
	@if [ -d "$(DB_PATH)" ] && pg_isready -h $(PGHOST) -p $(PGPORT) > /dev/null 2>&1; then \
		echo ">>> Stopping PostgreSQL..."; \
		pg_ctl -D $(DB_PATH) stop; \
	else \
		echo ">>> PostgreSQL is not running."; \
	fi

status:
	@echo "========================================"
	@echo "Database Status Check"
	@echo "========================================"
	@if [ -d "$(DB_PATH)" ] && pg_isready -h $(PGHOST) -p $(PGPORT) > /dev/null 2>&1; then \
		printf "Status:   [\033[32mRUNNING\033[0m]\n"; \
		echo "Port:     $(PGPORT)"; \
		echo "Host:     $(PGHOST)"; \
		echo "Database: alphapicks"; \
	else \
		printf "Status:   [\033[31mOFFLINE\033[0m]\n"; \
	fi
	@echo "========================================"

migrate: start-db
	@echo "Applying database migrations..."
	psql -h $(PGHOST) -p $(PGPORT) -d alphapicks -f sql/01_init_schema.sql

run: start-db
	@echo "Running daily services..."
	./scripts/run_etl.sh --skip-entities

statistics: start-db
	@echo "Computing statistics..."
	cd src/etl && python3 02_compute_statistics.py

ratings: start-db
	@echo "Generating production ratings..."
	cd src/etl && python3 03_generate_production_ratings.py

tsmom: start-db
	@echo "Running TSMOM Execution Engine..."
	cd src/etl && python3 04_tsmom_execution_engine.py

tsmom-weights: start-db
	@test -n "$(WEIGHTS_FILE)" || (echo "[ERROR] Usage: make tsmom-weights WEIGHTS_FILE=path/to/weights.json" && exit 1)
	@echo "Running TSMOM Execution Engine with weights file..."
	cd src/etl && python3 04_tsmom_execution_engine.py --weights-file ../../$(WEIGHTS_FILE)

tsmom-positions: start-db
	@test -n "$(POSITIONS_FILE)" || (echo "[ERROR] Usage: make tsmom-positions POSITIONS_FILE=path/to/positions.json [VOLATILITY_TARGET=1]" && exit 1)
	@echo "Running TSMOM Execution Engine with positions file..."
	cd src/etl && python3 04_tsmom_execution_engine.py --positions-file ../../$(POSITIONS_FILE) $(if $(VOLATILITY_TARGET),--volatility-target $(VOLATILITY_TARGET),)

tsmom-rank: start-db
	@echo "Ranking portfolio by TSMOM momentum strength..."
	cd src/etl && python3 05_tsmom_momentum_ranker.py $(ARGS)

tsmom-rank-all: start-db
	@echo "Ranking ALL portfolio tickers by TSMOM momentum (including off-trend)..."
	cd src/etl && python3 05_tsmom_momentum_ranker.py --all $(ARGS)

tsmom-rank-top: start-db
	@test -n "$(N)" || (echo "[ERROR] Usage: make tsmom-rank-top N=10" && exit 1)
	@echo "Showing top $(N) by TSMOM momentum..."
	cd src/etl && python3 05_tsmom_momentum_ranker.py --top $(N) $(ARGS)

# ──────────────────────────────────────────────
# HMM — Regime Detector & Trend Quality
# ──────────────────────────────────────────────
# These do NOT depend on a database — they use yfinance directly.
# Run from the project root inside `nix develop`.

HMM_DATA_DIR     ?= data
HMM_REGIME_PARAMS ?= $(HMM_DATA_DIR)/hmm_regime_params.pkl
HMM_TREND_DIR    ?= $(HMM_DATA_DIR)/hmm_trend_params

hmm-train-regime:
	@mkdir -p $(HMM_DATA_DIR)
	python3 src/hmm/train_regime.py --save-path $(HMM_REGIME_PARAMS)

hmm-predict-regime:
	@test -f $(HMM_REGIME_PARAMS) || (echo "[ERROR] No trained model at $(HMM_REGIME_PARAMS). Run 'make hmm-train-regime' first." && exit 1)
	python3 src/hmm/predict_regime.py --params-path $(HMM_REGIME_PARAMS)

hmm-train-trend:
	@test -n "$(TICKERS)" || (echo "[ERROR] Usage: make hmm-train-trend TICKERS=\"NVDA AMD\"" && exit 1)
	@mkdir -p $(HMM_TREND_DIR)
	python3 src/hmm/train_trend.py --save-dir $(HMM_TREND_DIR) $(TICKERS)

hmm-train-trend-all:
	@mkdir -p $(HMM_TREND_DIR)
	python3 src/hmm/train_trend.py --all --save-dir $(HMM_TREND_DIR)

hmm-predict-trend:
	@test -n "$(TICKERS)" || (echo "[ERROR] Usage: make hmm-predict-trend TICKERS=\"NVDA AMD\" [COMPARE=1]" && exit 1)
	python3 src/hmm/predict_trend.py --params-dir $(HMM_TREND_DIR) $(if $(COMPARE),--compare,) $(TICKERS)

hmm-predict-trend-all:
	python3 src/hmm/predict_trend.py --all --params-dir $(HMM_TREND_DIR) $(if $(COMPARE),--compare,)

clean: stop-db
	rm -rf $(DB_PATH)