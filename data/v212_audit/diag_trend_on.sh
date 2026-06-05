#!/bin/bash
set -u
cd "$(dirname "$0")/../.."
PIDFILE="data/v212_off_pids.txt"; : > "$PIDFILE"
SNAP="data/snapshots/snap_trending_2023q4.json"
for run in a b; do
  git checkout data/signal_ic_history.json 2>/dev/null
  ver="v212_diag_trend_on_${run}"
  echo "--- $ver starting $(date -u +%FT%TZ) ---"
  PYTHONHASHSEED=42 python3 scripts/run_training.py --version "$ver" \
    --cycles 200 --sleep 10 --seed 42 --backtest-snapshot "$SNAP" --frozen-cache \
    --features '{"strategy_selector_enabled": true}' \
    > "data/v212_audit/diag_${run}_stdout.log" 2> "data/v212_audit/diag_${run}_stderr.log" &
  pid=$!; echo "$pid" >> "$PIDFILE"; wait "$pid"
  echo "$ver done rc=$? $(date -u +%FT%TZ)"
done
echo "DIAG COMPLETE $(date -u +%FT%TZ)"
