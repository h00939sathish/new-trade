#!/usr/bin/env bash
# run_paper_5d.sh - 5-day paper trading burn-in wrapper (bash / WSL / Git Bash)
#
# Usage:
#   bash scripts/run_paper_5d.sh
#
# Same semantics as run_paper_5d.ps1: paper-only, auto-restart, daily log rotation,
# stops after 5 days, writes run_manifest.json.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
PYTHON="$ROOT/.venv/Scripts/python.exe"
[ -x "$PYTHON" ] || PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || { echo "FATAL: venv python not found"; exit 1; }

BURNIN_DIR="$ROOT/state/burnin"
PID_PATH="$BURNIN_DIR/paper-burnin.pid"
MANIFEST_PATH="$BURNIN_DIR/run_manifest.json"
MAX_RESTARTS_PER_DAY=10

mkdir -p "$BURNIN_DIR"

# Force paper-only env
export TRA_KITE_API_KEY=""
export TRA_KITE_API_SECRET=""
export TRA_KITE_ACCESS_TOKEN=""
export TRA_KITE_USER_ID=""
export TRA_LIVE_TRADING_ENABLED="false"
export TRA_EVENT_STORE_TYPE="sqlite"
export TRA_DASHBOARD="0"
export TRA_DASHBOARD_TYPE="http"
export TRA_METRICS_PORT="8080"
export TRA_BURNIN="1"
export TRA_BURNIN_RECONCILIATION_SECONDS="300"
export TRA_BURNIN_RECONCILIATION_PATH="state/burnin/reconciliation.jsonl"

# Phase 1 invariant env vars
export TRA_CONSENSUS_THRESHOLD="0.65"
export TRA_CONSENSUS_SHORT_THRESHOLD="0.70"
export TRA_SIGNAL_COOLDOWN_SECONDS="120"
export TRA_KILL_SWITCH_DAILY_LOSS_PCT="0.01"
export TRA_KILL_SWITCH_MAX_DRAWDOWN_PCT="0.05"
export TRA_REFLECTION_MUTATION_ENABLED="false"
export TRA_RISK_PER_TRADE_LOSS_CAP_PCT="0.01"

ACTIVE_PID=""
STOP_REASON="completed_5_days"
TOTAL_CRASHES=0
DAY=1

cleanup() {
    local rc=$?
    echo ""
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Caught signal. Stopping burn-in..."
    if [ -n "$ACTIVE_PID" ] && kill -0 "$ACTIVE_PID" 2>/dev/null; then
        kill -TERM "$ACTIVE_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$ACTIVE_PID" 2>/dev/null || true
    fi
    rm -f "$PID_PATH"
    STOP_REASON="stopped_by_operator"
    write_manifest
    exit $rc
}

write_manifest() {
    local now
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "$MANIFEST_PATH" <<EOF
{
  "started_at": "$START_TIME",
  "ended_at": "$now",
  "ended_reason": "$STOP_REASON",
  "days_completed": $((DAY - 1)),
  "total_crashes": $TOTAL_CRASHES,
  "watchlist": "${TRA_WATCHLIST:-}",
  "consensus_threshold": "${TRA_CONSENSUS_THRESHOLD}",
  "kill_switch_daily_loss_pct": "${TRA_KILL_SWITCH_DAILY_LOSS_PCT}"
}
EOF
    echo ""
    echo "[$now] === Burn-in ended ==="
    echo "Manifest: $MANIFEST_PATH"
    echo "Days completed: $((DAY - 1))"
    echo "Total crashes: $TOTAL_CRASHES"
}

trap cleanup INT TERM

START_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
END_EPOCH=$(($(date +%s) + 5 * 86400))

echo "[$START_TIME] Paper 5-day burn-in starting. End epoch: $END_EPOCH"
echo "Logs: $BURNIN_DIR/day{N}.log (stdout) and day{N}_stderr.log (stderr)"

while [ "$(date +%s)" -lt "$END_EPOCH" ]; do
    DAY_LOG="$BURNIN_DIR/day${DAY}.log"
    DAY_ERR="$BURNIN_DIR/day${DAY}_stderr.log"
    DAY_RESTARTS=0
    DAY_EPOCH=$(($(date +%s) + 86400 - 1))

    echo ""
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === Day $DAY starting ==="
    echo "  Log: $DAY_LOG"
    echo "  Day ends at epoch: $DAY_EPOCH"

    while [ "$(date +%s)" -lt "$DAY_EPOCH" ] && [ "$(date +%s)" -lt "$END_EPOCH" ]; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting python -m src.main (attempt $((DAY_RESTARTS + 1)))..."

        "$PYTHON" -m src.main > "$DAY_LOG" 2> "$DAY_ERR" &
        ACTIVE_PID=$!
        echo "$ACTIVE_PID" > "$PID_PATH"

        wait "$ACTIVE_PID"
        EXIT_CODE=$?
        ACTIVE_PID=""
        rm -f "$PID_PATH"

        if [ $EXIT_CODE -eq 0 ]; then
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Process exited cleanly (code=0). Restarting..."
        else
            TOTAL_CRASHES=$((TOTAL_CRASHES + 1))
            DAY_RESTARTS=$((DAY_RESTARTS + 1))
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] CRASH exit=$EXIT_CODE. Total crashes: $TOTAL_CRASHES. Day $DAY restarts: $DAY_RESTARTS."

            if [ $DAY_RESTARTS -ge $MAX_RESTARTS_PER_DAY ]; then
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FATAL: $MAX_RESTARTS_PER_DAY restarts in day $DAY. Aborting."
                STOP_REASON="crash_loop"
                write_manifest
                exit 1
            fi
        fi

        sleep 5
    done

    DAY=$((DAY + 1))
done

write_manifest
