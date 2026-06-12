#!/bin/bash
# run_etl.sh - Sequentially runs ETL steps with automatic restart on failure

PROJECT_ROOT=${PROJECT_ROOT:-$PWD}

run_step() {
    local script_rel_path=$1
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
        python3 "$script_file"
        local exit_status=$?
        
        if [ $exit_status -eq 0 ]; then
            echo ">>> SUCCESS: $script_file finished successfully."
            break
        else
            echo ">>> ERROR: $script_file crashed (Exit Code: $exit_status)."
            # For demonstration purposes, if it crashes we break instead of infinite looping, 
            # so the developer doesn't get stuck in tests. Change 'break' to 'sleep 10' for infinite retry if desired.
            echo ">>> Aborting to avoid infinite loop during development."
            exit $exit_status
        fi
    done
}

# The scripts are located in the src/etl/ directory
# Step 1: Price Data Update
run_step "src/etl/01_fetch_price_data.py"

# Step 2: Statistics Computations
run_step "src/etl/02_compute_statistics.py"

# Step 3: Production Ratings
run_step "src/etl/03_generate_production_ratings.py"

echo ">>> ALL ETL STEPS COMPLETED SUCCESSFULLY <<<"
