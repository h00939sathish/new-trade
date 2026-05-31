#!/usr/bin/env bash
set -euo pipefail

cd "/d/projects/new trade"

# Activate venv
source .venv/Scripts/activate

# Force paper trading by clearing broker creds
export TRA_KITE_API_KEY=""
export TRA_KITE_API_SECRET=""
export TRA_KITE_ACCESS_TOKEN=""
export TRA_KITE_USER_ID=""

# Disable CLI dashboard to keep stdout clean
export TRA_DASHBOARD="0"
export TRA_DASHBOARD_TYPE="http"
export TRA_METRICS_PORT="8080"

# Auto-restart loop for 24/7 operation
while true; do
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting paper trading system..."
  python -m src.main
  rc=$?
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Process exited (code=$rc). Restarting in 5s..."
  sleep 5
  
done
