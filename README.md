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

# 2. Start the database (if offline) and run daily scripts (skips entity population)
make run
```

---

## 🛠 Makefile Commands Reference

We use a `Makefile` to orchestrate local development tasks cleanly. Once inside `nix develop`, you have access to the following commands:

* `make setup`: **(First-time only)** Initializes the database cluster, installs the TimescaleDB extension, applies SQL schema (`sql/01_init_schema.sql`), and executes the full ETL pipeline including entity population (`scripts/run_etl.sh`).
* `make run`: The standard command to run your daily scripts. It ensures the database is running in the background and executes the ETL pipeline.
* `make ratings`: A convenience command to skip the ETL steps and *only* run the final production ratings generation (`03_generate_production_ratings.py`).
* `make tsmom`: Runs the TSMOM Execution Engine against your current portfolio, printing a full position table with recommended actions.
* `make tsmom-weights WEIGHTS_FILE=path/to/weights.json`: Same as above, but reads your actual position weights from a JSON file (`{"NVDA": 0.08, "MSFT": 0.05, ...}`) instead of assuming equal weight.
* `make tsmom-rank`: Ranks all TSMOM-ON tickers by momentum strength (volatility-scaled 12-month return).
* `make tsmom-rank-all`: Includes off-trend tickers in the ranking (useful for spotting tickers near flipping on).
* `make tsmom-rank-top N=10`: Show only the top N tickers.
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

### TSMOM Execution Engine (`src/etl/04_tsmom_execution_engine.py`)

A standalone portfolio execution overlay based on **Time Series Momentum** (Moskowitz, Ooi & Pedersen 2012) and **volatility targeting** (Hurst, Ooi & Pedersen 2017). Run via `make tsmom`.

For each ticker in `CURRENT_PORTFOLIO` it computes a price-only trend signal and a volatility-adjusted target weight, then compares against your current holdings to produce one of four actions:

| Action | When it fires |
|---|---|
| **HOLD** | Ticker is in trend, your position is within 5% of the volatility-targeted weight — no action needed |
| **REBALANCE** | Ticker is in trend, but your current weight drifts more than 5% from target — trim or add |
| **BUY** | Ticker enters trend and you have **no position** (weight = 0) — initiate |
| **SELL** | Trend breaks and you currently hold the position — exit |

> **Note:** `BUY` only fires when you pass real position weights via `--weights-file` and a ticker has weight `0`. With the default equal-weight mode every ticker is treated as held, so only `SELL`, `REBALANCE`, and `HOLD` appear.

**Trend signal (price-only):** `T_i = 1` if `Price > SMA_210` AND `12-month return > 0`, else `0`.

**Volatility-targeted weight:** `W_i = (15% target vol / EWMA_60 vol_i) × T_i`, normalised so weights sum to 100%.

**Deadband threshold:** 5% — positions within ±5% of target are left unchanged to cap turnover.

---

### TSMOM Momentum Ranker (`src/etl/05_tsmom_momentum_ranker.py`)

Ranks the same portfolio by continuous momentum strength — the natural extension of the binary TSMOM signal. Run via `make tsmom-rank`.

For each ticker it computes the full suite of TSMOM metrics and sorts by **Score** = R_252 / σ (the ex-ante Sharpe proxy from Moskowitz et al. 2012 — return per unit of risk, the same quantity used for position sizing in script 04).

| Column | What it means |
|---|---|
| **Trend** | 1 = the TSMOM gate is open (P > SMA_210 AND R_252 > 0), 0 = closed |
| **R_252%** | Raw 12-month return |
| **Vol%** | Annualised EWMA volatility (60-day span) |
| **Score** | R_252 / σ — momentum strength per unit of risk (primary sort key) |
| **SMA Ratio** | Current price ÷ 210-day SMA — trend steepness proxy |

```bash
# Rank tickers with active TSMOM signal (default)
make tsmom-rank

# Include off-trend tickers
make tsmom-rank-all

# Top 5 only (respects --all flag when running tsmom-rank-all)
make tsmom-rank-top N=5
make tsmom-rank-top N=5 ARGS="--all"

# Pass any extra args: --top, --all, or both
make tsmom-rank ARGS="--top 10"
make tsmom-rank ARGS="--all --top 10"
```

---

### ❄️ NixOS System Integration

Alpha Picks can be integrated directly into your NixOS system configuration as a scheduled background task without modifying the source code.

#### 1. Add to your Flake Inputs
Add this repository to your system's `flake.nix`:

```nix
inputs.alphapicks.url = "git+https://github.com/OliverEsoterik/aria-lite.git";
```

#### 2. Define a Systemd Service
In your NixOS configuration, you can create a service that runs the ETL pipeline daily. This example assumes you want to run it at 3:00 AM using your system's existing PostgreSQL service.

```nix
{ config, pkgs, inputs, ... }: 
let
  # Create a package from the flake input
  alphapicks-pkg = inputs.alphapicks.packages.${pkgs.system}.default;
  
  # Configuration
  dataDir = "/var/lib/alphapicks";
  dbUrl = "postgresql+psycopg2:///alphapicks";
in {
  # 1. Ensure the data directory exists
  systemd.tmpfiles.rules = [
    "d ${dataDir} 0750 alphapicks alphapicks -"
  ];

  # 2. Define the ETL Service
  systemd.services.alphapicks-etl = {
    description = "Alpha Picks Daily ETL Pipeline";
    serviceConfig = {
      Type = "oneshot";
      User = "alphapicks";
      StateDirectory = "alphapicks";
      WorkingDirectory = "${alphapicks-pkg}";
      ExecStart = "${alphapicks-pkg}/scripts/run_etl.sh --skip-entities";
    };
    environment = {
      PROJECT_ROOT = "${alphapicks-pkg}";
      DATABASE_URL = dbUrl;
      # Point to your system's Postgres socket if needed
      PGHOST = "/run/postgresql"; 
    };
  };

  # 3. Schedule the run (Daily at 3 AM)
  systemd.timers.alphapicks-etl = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 03:00:00";
      Persistent = true;
    };
  };
}
```

**Note:** This setup requires that your system's PostgreSQL has the `timescaledb` extension enabled and a database named `alphapicks` created.

