.PHONY: setup start-db stop-db stop status migrate run ratings tsmom tsmom-weights clean

setup: start-db migrate
	./scripts/run_etl.sh

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
	@echo "Running TSMOM Execution Engine with weights file..."
	cd src/etl && python3 04_tsmom_execution_engine.py --weights-file ../../$(WEIGHTS_FILE)

clean: stop-db
	rm -rf $(DB_PATH)