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
* `make tsmom-positions POSITIONS_FILE=path/to/positions.json [VOLATILITY_TARGET=1]`: Reads your current holdings as **absolute EUR amounts** (`{"NVDA": 10000, "MSFT": 8000}`) and computes target allocations. Set `VOLATILITY_TARGET=1` (default for fully-invested portfolios) to deploy near-full capital. Lower values (e.g. `0.15`) reserve more cash.
* `make tsmom-weights WEIGHTS_FILE=path/to/weights.json`: Same as above, but reads your actual position weights from a JSON file (`{"NVDA": 0.08, "MSFT": 0.05, ...}`) instead of assuming equal weight.
* `make tsmom-rank`: Ranks tickers by multi-window TSMOM composite (Composite > 0, Hurst et al. 2017).
* `make tsmom-rank-all`: Includes off-trend tickers in the ranking (useful for spotting tickers near flipping on).
* `make tsmom-rank-top N=10`: Show only the top N tickers.
* `make status`: Checks the current state of the local PostgreSQL database, including its connection port and host path.
* `make start-db`: Starts the local PostgreSQL database in the background.
* `make stop`: Gracefully shuts down the background PostgreSQL database (alias for `make stop-db`).
* `make migrate`: Manually applies the SQL schema changes. (Already included in `make setup`).
* `make clean`: **(Warning)** Shuts down the database and deletes the local database data folder (`.db_data`). Use this if you want to wipe everything and start from scratch.

**HMM tools** (no database required):
* `make hmm-train-regime`: Train market regime HMM on SPY + VIX.
* `make hmm-predict-regime`: Predict current Bull/Bear/Sideways regime.
* `make hmm-train-trend TICKERS="NVDA AMD"`: Train trend HMMs for specific tickers.
* `make hmm-train-trend-all`: Train trend HMMs for all portfolio tickers.
* `make hmm-predict-trend TICKERS="NVDA" [COMPARE=1]`: Predict trend quality for tickers.
* `make hmm-predict-trend-all [COMPARE=1]`: Predict trend quality for all portfolio tickers.

See [`src/hmm/README.md`](src/hmm/README.md) for full documentation.

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
>
> **EUR positions mode:** Run via `make tsmom-positions POSITIONS_FILE=path/to/positions.json` or directly with `--positions-file`. Supply your current holdings as absolute amounts (e.g. `{"NVDA": 10000, "MSFT": 8000}`). The engine:
> 1. Sums the amounts to get your total portfolio value
> 2. Converts to weights internally (each amount / total)
> 3. Computes target weights from TSMOM
> 4. Prints both EUR amounts and percentages in the output table
>
> This is the recommended way to run the engine — you see exactly how much to buy or sell in cash terms, not just percentage deltas.

**Volatility target:** `VOLATILITY_TARGET` controls how much capital the model wants to deploy. Default is `0.15` (15%), which typically results in a low allocation (mostly cash). Set `VOLATILITY_TARGET=1` (100%) to deploy near-full capital, which is the right setting if you're always fully invested. The target acts as a concentration dial: lower values flatten toward equal-weight, higher values skew more heavily toward lower-volatility stocks.

**Trend signal (price-only):** `T_i = 1` if `Price > SMA_210` AND `12-month return > 0`, else `0`.

**Volatility-targeted weight:** `W_i = (15% target vol / EWMA_60 vol_i) × T_i`, normalised so weights sum to 100%.

**Deadband threshold:** 5% — positions within ±5% of target are left unchanged to cap turnover.

---

### TSMOM Momentum Ranker (`src/etl/05_tsmom_momentum_ranker.py`)

Ranks the same portfolio by multi-window momentum composite per **Hurst, Ooi & Pedersen (2017)**. Run via `make tsmom-rank`.

Instead of a single 252-day window, the ranker averages the volatility-scaled return across three windows (21d, 63d, 252d) — exactly the equal-weighted combination described in the paper. This catches stocks that have recently rolled over (short-term windows go negative) even if the 12-month return is still positive.

| Column | What it means |
|---|---|
| **Trend** | 1 if Composite_Score > 0 |
| **Votes** | How many of the three windows (21d, 63d, 252d) show positive returns (0–3) |
| **R_21% / R_63% / R_252%** | Raw returns over 1-month, 3-month, and 12-month windows |
| **S_21 / S_63 / S_252** | Volatility-scaled score at each horizon (R / σ, the ex-ante Sharpe proxy) |
| **Grade** | Momentum letter grade (A+/A/A-/B+/B/B-/C+/C/C-/F) based on Votes + Composite tiers |
| **Composite** | Average of S_21, S_63, S_252 — **primary sort key** (Hurst et al. 2017 equal-weighted composite) |
| **SMA Rat** | Current price ÷ 210-day SMA — trend steepness proxy |

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

---

## 📚 Research References

This project implements or is directly inspired by the following academic papers. Each reference links to the specific code that implements it.

| Paper | Implemented In | What It Provides |
|-------|---------------|------------------|
| **Moskowitz, Ooi & Pedersen (2012)** — "Time Series Momentum" ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)) | [`04_tsmom_execution_engine.py`](src/etl/04_tsmom_execution_engine.py) | Volatility-scaling of momentum returns, inverse-vol weighting, and the two-step vol-targeting framework. The trend signal (`P > SMA_210` + `R_252 > 0`) and the exh-ante EWMA vol estimator are drawn directly from this paper. |
| **Hurst, Ooi & Pedersen (2017)** — "A Century of Evidence on Trend-Following Investing" ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026)) | [`05_tsmom_momentum_ranker.py`](src/etl/05_tsmom_momentum_ranker.py), [`03_generate_production_ratings.py`](src/etl/03_generate_production_ratings.py) | Multi-window momentum composite: the equal-weighted combination of 21-day, 63-day, and 252-day vol-scaled returns. The hysteresis deadband in the execution engine also follows this paper's turnover-control recommendations. The production scoring function now uses a 3/6/12-month composite (P1). |
| **Yang & Zhang (2000)** — "Drift-Independent Volatility Estimation" ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=225882)) | [`03_generate_production_ratings.py`](src/etl/03_generate_production_ratings.py) | Range-based volatility estimator combining overnight variance, open-close variance, and the Rogers-Satchell high-low range. Replaces close-to-close std dev in the momentum score denominator for 7-8x more efficient estimation (P0). |
| **Tan, Roberts & Zohren (2023)** — "Spatio-Temporal Momentum" ([arxiv](https://arxiv.org/abs/2302.10175)) | [`03_generate_production_ratings.py`](src/etl/03_generate_production_ratings.py) | Multi-lookback momentum composite: combining 3-month, 6-month, and 12-month returns (0.3/0.3/0.4) significantly outperforms single-lookback approaches (P1). |
| **Lee (2025)** — "Not All Factors Crowd Equally" ([arxiv](https://arxiv.org/abs/2512.11913)) | [`03_generate_production_ratings.py`](src/etl/03_generate_production_ratings.py) | Momentum alpha decays hyperbolically. The quality metric now uses exponentially weighted counts (63-day half-life) so recent days contribute more than old ones (P3). |
| **Liu, Shu & Chiu (2023)** — "NoxTrader: LSTM-Based Stock Return Momentum Prediction" ([arxiv](https://arxiv.org/abs/2310.00747)) | [`03_generate_production_ratings.py`](src/etl/03_generate_production_ratings.py) | When short-term acceleration and long-term momentum are both positive, the combined signal is stronger than the sum of parts. The final score applies a non-linear boost (1.0-1.3x) to the momentum weight block when both align (P4). |
| **Rabiner (1989)** — "A Tutorial on Hidden Markov Models and Selected Applications in Speech Recognition" ([IEEE](https://ieeexplore.ieee.org/document/18626)) | [`src/hmm/`](src/hmm/) (all four modules) | Gaussian HMM training via Baum-Welch (expectation-maximisation) and state prediction via the Viterbi algorithm. The 3-state regime detector and 4-state trend quality models are standard Rabiner-style HMMs applied to financial returns. |

---

## HMM Regime Detector & Trend Quality

Standalone advisory tools using Hidden Markov Models — no changes to the existing trading system.

See the **[dedicated HMM documentation](src/hmm/README.md)** for full usage, workflow, and reference.

### Quick Start (inside `nix develop`)

```bash
# Train market regime model
make hmm-train-regime

# Predict current regime
make hmm-predict-regime
```

```bash
# Train trend models for all portfolio tickers
make hmm-train-trend-all

# Predict all trends
make hmm-predict-trend-all
```

### Commands

| Target | Description |
|--------|-------------|
| `make hmm-train-regime` | Train regime HMM (SPY + VIX) |
| `make hmm-predict-regime` | Predict current market regime |
| `make hmm-train-trend TICKERS="NVDA AMD"` | Train trend HMMs for specific tickers |
| `make hmm-train-trend-all` | Train trend HMMs for all portfolio tickers |
| `make hmm-predict-trend TICKERS="NVDA" [COMPARE=1]` | Predict trend quality |
| `make hmm-predict-trend-all [COMPARE=1]` | Predict trends for all portfolio tickers |

These targets do **not** require the database — they use yfinance directly.

