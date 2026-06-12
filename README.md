# Alpha Picks

A data engineering and ETL pipeline project powered by Python, TimescaleDB, and a fully reproducible Nix environment. 

## 🚀 Getting Started

This project uses [Nix](https://nixos.org/) (specifically Nix Flakes) to provide a 100% reproducible development environment. You do **not** need to install Python, PostgreSQL, TimescaleDB, or any Python packages (like `pandas` or `yfinance`) globally on your machine. Nix handles it all.

### Prerequisites

* Ensure you have the Nix package manager installed.
* Ensure you have Nix Flakes enabled.

### 1. Initial Setup (Run Once)

When you clone the repository for the first time, you need to spin up the Nix environment, initialize the local TimescaleDB instance, apply the database schema, and run the initial ETL data load.

```bash
# 1. Enter the Nix environment (downloads Python, DB, and all packages)
nix develop

# 2. Run the automated setup
make setup
```

### 2. Daily Development Workflow

For day-to-day development, you simply need to enter the Nix environment and start the daily ETL/services.

```bash
# 1. Enter the Nix environment
nix develop

# 2. Start the database (if offline) and run daily scripts
make run
```

---

## 🛠 Makefile Commands Reference

We use a `Makefile` to orchestrate local development tasks cleanly. Once inside `nix develop`, you have access to the following commands:

* `make setup`: **(First-time only)** Initializes the database cluster, installs the TimescaleDB extension, applies SQL schema (`sql/01_init_schema.sql`), and executes the ETL pipeline (`scripts/run_etl.sh`).
* `make run`: The standard command to run your daily scripts. It ensures the database is running in the background and executes the ETL pipeline.
* `make status`: Checks the current state of the local PostgreSQL database, including its connection port and host path.
* `make start-db`: Starts the local PostgreSQL database in the background.
* `make stop`: Gracefully shuts down the background PostgreSQL database (alias for `make stop-db`).
* `make migrate`: Manually applies the SQL schema changes. (Already included in `make setup`).
* `make clean`: **(Warning)** Shuts down the database and deletes the local database data folder (`.db_data`). Use this if you want to wipe everything and start from scratch.

---

## 📂 Architecture & Details

### Database 
* The database data is stored locally in the `.db_data` directory within the project root. This directory is ignored by Git.
* The database listens locally via Unix sockets. You do not need to configure usernames or passwords.
* The database name created by default is `alphapicks`.
* If you want to connect to the database via an external tool (like DBeaver or TablePlus) while it's running, you can connect using:
  * **Host:** `localhost`
  * **Port:** `5432`
  * **Database:** `alphapicks`
  * **User:** Your current Unix username (no password needed)

### Environment Variables
Upon running `nix develop`, the environment automatically sets up the following variables for your scripts:
* `DATABASE_URL`: `postgresql+psycopg2:///alphapicks`
* `PGHOST`: Path to your local `.db_data` socket directory
* `PGPORT`: `5432`
* `PROJECT_ROOT`: Absolute path to this repository

### ETL Scripts
Python scripts (`src/etl/01_fetch_price_data.py`, `src/etl/02_compute_statistics.py`, `src/etl/03_generate_production_ratings.py`) execute using the dependencies pinned in the Nix environment. Database connections intelligently read from the environment variables, meaning no hardcoded credentials are used.
