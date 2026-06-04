#!/bin/bash
# V211 — 2-pair × 3-gate audit (12 runs) at V211 noise floor.
# Sequential, seed=42, PYTHONHASHSEED=42, frozen funding cache.
set -u
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
AUDIT="$ROOT/data/v211_audit"
LOG="$AUDIT/run.log"
PIDFILE="$ROOT/data/v211_pids.txt"
: > "$PIDFILE"

snap_for() {
  case "$1" in
    recent) echo "data/snapshots/snap_20260414.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json" ;;
    crisis) echo "data/snapshots/snap_crisis_2022h1.json" ;;
  esac
}

echo "=== V211 2-pair 3-gate audit starting at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
echo "PYTHONHASHSEED env at driver: ${PYTHONHASHSEED:-unset}" | tee -a "$LOG"

pre_fp=$(sha256sum data/macro_cache.db data/omega_victoria_state.db data/omega_victoria_memory.db 2>/dev/null)
echo "Pre-audit fingerprints:" | tee -a "$LOG"
echo "$pre_fp" | tee -a "$LOG"

for gate in recent trend crisis; do
  snap=$(snap_for "$gate")
  for pair in p1 p2; do
    for run in r1 r2; do
      ver="v211_${gate}_${pair}_${run}"
      outdir="$AUDIT/${gate}_${pair}_${run}"
      mkdir -p "$outdir"
      echo "--- $ver starting $(date -u +%FT%TZ) ---" | tee -a "$LOG"
      PYTHONHASHSEED=42 python3 scripts/run_training.py \
        --version "$ver" \
        --cycles 200 --sleep 10 --seed 42 \
        --backtest-snapshot "$snap" \
        --frozen-cache \
        > "$outdir/stdout.log" 2> "$outdir/stderr.log" &
      pid=$!
      echo "$pid" >> "$PIDFILE"
      wait "$pid"
      rc=$?
      echo "$ver exit=$rc at $(date -u +%FT%TZ)" | tee -a "$LOG"
      cp -f "data/${ver}_results.json" "$outdir/results.json" 2>/dev/null || echo "MISSING ${ver}_results.json" | tee -a "$LOG"
      cp -f "data/${ver}_trades.csv" "$outdir/trades.csv" 2>/dev/null || echo "MISSING ${ver}_trades.csv" | tee -a "$LOG"
      cp -f "/tmp/${ver}_metrics.jsonl" "$outdir/metrics.jsonl" 2>/dev/null || echo "MISSING ${ver}_metrics.jsonl" | tee -a "$LOG"
      cp -f "data/${ver}_signal_contribs.jsonl" "$outdir/signal_contribs.jsonl" 2>/dev/null || true
      sha256sum "$outdir/results.json" "$outdir/trades.csv" "$outdir/metrics.jsonl" 2>&1 | tee -a "$LOG"
    done
  done
done

post_fp=$(sha256sum data/macro_cache.db data/omega_victoria_state.db data/omega_victoria_memory.db 2>/dev/null)
echo "Post-audit fingerprints:" | tee -a "$LOG"
echo "$post_fp" | tee -a "$LOG"
if [ "$pre_fp" = "$post_fp" ]; then
  echo "FROZEN-CACHE VERIFIED: pre/post fingerprints identical" | tee -a "$LOG"
else
  echo "WARNING: cache files mutated during audit" | tee -a "$LOG"
fi

echo "=== V211 audit finished at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
