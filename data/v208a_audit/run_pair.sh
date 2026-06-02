#!/bin/bash
# V208 sub-experiment A — recent gate, 2 runs, seed=42, frozen cache.
set -u
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
AUDIT="$ROOT/data/v208a_audit"
LOG="$AUDIT/run.log"
snap="data/snapshots/snap_20260414.json"

echo "=== V208a recent-pair starting at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
echo "PYTHONHASHSEED env at driver: ${PYTHONHASHSEED:-unset}" | tee -a "$LOG"

pre_fp=$(sha256sum data/macro_cache.db data/omega_victoria_state.db data/omega_victoria_memory.db 2>/dev/null)
echo "Pre-run fingerprints:" | tee -a "$LOG"
echo "$pre_fp" | tee -a "$LOG"

for run in r1 r2; do
  ver="v208a_recent_${run}"
  outdir="$AUDIT/recent_${run}"
  mkdir -p "$outdir"
  echo "--- $ver starting $(date -u +%FT%TZ) ---" | tee -a "$LOG"
  PYTHONHASHSEED=42 python3 scripts/run_training.py \
    --version "$ver" \
    --cycles 200 --sleep 10 --seed 42 \
    --backtest-snapshot "$snap" \
    --frozen-cache \
    > "$outdir/stdout.log" 2> "$outdir/stderr.log"
  rc=$?
  echo "$ver exit=$rc at $(date -u +%FT%TZ)" | tee -a "$LOG"
  cp -f "data/${ver}_results.json" "$outdir/results.json" 2>/dev/null || echo "MISSING ${ver}_results.json" | tee -a "$LOG"
  cp -f "data/${ver}_trades.csv" "$outdir/trades.csv" 2>/dev/null || echo "MISSING ${ver}_trades.csv" | tee -a "$LOG"
  cp -f "/tmp/${ver}_metrics.jsonl" "$outdir/metrics.jsonl" 2>/dev/null || echo "MISSING ${ver}_metrics.jsonl" | tee -a "$LOG"
  sha256sum "$outdir/results.json" "$outdir/trades.csv" "$outdir/metrics.jsonl" 2>&1 | tee -a "$LOG"
done

post_fp=$(sha256sum data/macro_cache.db data/omega_victoria_state.db data/omega_victoria_memory.db 2>/dev/null)
echo "Post-run fingerprints:" | tee -a "$LOG"
echo "$post_fp" | tee -a "$LOG"
if [ "$pre_fp" = "$post_fp" ]; then
  echo "FROZEN-CACHE VERIFIED: pre/post fingerprints identical" | tee -a "$LOG"
else
  echo "WARNING: cache files mutated during audit" | tee -a "$LOG"
fi

echo "=== V208a recent-pair finished at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
