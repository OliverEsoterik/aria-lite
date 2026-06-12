.PHONY: setup start-db stop-db migrate run clean

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

stop-db:
	@if [ -d "$(DB_PATH)" ] && pg_isready -h $(PGHOST) -p $(PGPORT) > /dev/null 2>&1; then \
		pg_ctl -D $(DB_PATH) stop; \
	fi

migrate: start-db
	@echo "Applying database migrations..."
	psql -h $(PGHOST) -p $(PGPORT) -d alphapicks -f sql/01_init_schema.sql

run: start-db
	@echo "Running daily services..."
	./scripts/run_etl.sh

clean: stop-db
	rm -rf $(DB_PATH)