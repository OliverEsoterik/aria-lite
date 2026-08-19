#!/usr/bin/env bash
# run_etl.sh - Sequentially runs ETL steps with automatic restart on failure
# Usage: ./scripts/run_etl.sh [--skip-entities] [--max N]
#   --skip-entities   Skip the 00_populate_entities.py step (useful for daily runs)
#   --max N           Limit to the first N tickers (forwarded to 01_fetch_price_data.py)

set -euo pipefail

PROJECT_ROOT=${PROJECT_ROOT:-$PWD}
SKIP_ENTITY_POPULATION=false
MAX_TICKERS=""

# --- Parse CLI arguments ---
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --skip-entities)
            SKIP_ENTITY_POPULATION=true
            shift
            ;;
        --max)
            MAX_TICKERS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--skip-entities] [--max N]" >&2
            exit 1
            ;;
    esac
done

# --- Step runner ---
run_step() {
    local script_rel_path=$1
    shift
    local script_abs_path="$PROJECT_ROOT/$script_rel_path"
    local script_dir=$(dirname "$script_abs_path")
    local script_file=$(basename "$script_abs_path")

    while true; do
        echo "=========================================================="
        echo ">>> STARTING STEP: $script_file"
        echo ">>> Directory: $script_dir"
        echo "=========================================================="

        # Navigate to the script's directory so relative data paths work
        cd "$script_dir" || exit 1

        # Run the script using Python from the Nix environment
        python3 "$script_file" "$@"
        local exit_status=$?

        if [ $exit_status -eq 0 ]; then
            echo ">>> SUCCESS: $script_file finished successfully."
            break
        else
            echo ">>> ERROR: $script_file crashed (Exit Code: $exit_status)."
            echo ">>> Aborting to avoid infinite loop during development."
            exit $exit_status
        fi
    done
}

# --- Run the pipeline ---
if [ "$SKIP_ENTITY_POPULATION" = false ]; then
    # Step 0: Populate Entities from SEC (only on initial setup)
    SEC_USER_AGENT_EMAIL="$SEC_USER_AGENT_EMAIL" \
        run_step "src/etl/00_populate_entities.py"
fi

# Step 1: Price Data Update
if [ -n "$MAX_TICKERS" ]; then
    run_step "src/etl/01_fetch_price_data.py" "--max" "$MAX_TICKERS"
else
    run_step "src/etl/01_fetch_price_data.py"
fi

# Step 2: Statistics Computations
run_step "src/etl/02_compute_statistics.py"

# Step 3: Production Ratings
run_step "src/etl/03_generate_production_ratings.py"

echo ">>> ALL ETL STEPS COMPLETED SUCCESSFULLY <<<"
