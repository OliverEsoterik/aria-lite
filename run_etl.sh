#!/bin/bash
# run_etl.sh - Sequentially runs ETL steps with automatic restart on failure

VENV_PYTHON="/home/oliver/sec-etl/venv/bin/python3"
PROJECT_ROOT="/home/oliver/sec-etl"

# Ensure venv is activated
source "$PROJECT_ROOT/venv/bin/activate"

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
        
        # Run the script
        python "$script_file"
        local exit_status=$?
        
        if [ $exit_status -eq 0 ]; then
            echo ">>> SUCCESS: $script_file finished successfully."
            break
        else
            echo ">>> ERROR: $script_file crashed (Exit Code: $exit_status)."
            echo ">>> Restarting in 10 seconds..."
            sleep 10
        fi
    done
}

# Step 1: Price Data Update
run_step "src/etl/09_price_data/01b.py"

# Step 2: Statistics Computations
run_step "src/etl/11_statistics/01b_computations.py"

# Step 3: Production Ratings
run_step "src/etl/11_statistics/03h_prod.py"

echo ">>> ALL ETL STEPS COMPLETED SUCCESSFULLY <<<"
