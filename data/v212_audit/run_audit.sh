#!/bin/bash
# V212 — 2-pair × 3-gate audit (12 runs) with strategy_selector_enabled=true.
# Sequential, seed=42, PYTHONHASHSEED=42, frozen funding cache.
# Tests whether the restored V156 strategy_selector module moves any gate
# > 2σ vs V211 noise floors (recent $1, trend $166, crisis $12).
#
# HARDENED RELAUNCH (2026-06-05): the original run (run.log.dead1) died at
# run 3 from ENOSPC and the un-guarded loop marched on stamping runs 4-12
# exit=1 at the same second. This version adds a pre-run free-space gate and
# a hard abort if any run fails to produce results.json, so a transient disk
# blip can never again fake-fail the remaining audit.
set -u
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
AUDIT="$ROOT/data/v212_audit"
LOG="$AUDIT/run.log"
PIDFILE="$ROOT/data/v212_pids.txt"
: > "$PIDFILE"

FEATURES='{"strategy_selector_enabled": true}'
MIN_FREE_KB=$((5 * 1024 * 1024))   # 5 GB floor

snap_for() {
  case "$1" in
    recent) echo "data/snapshots/snap_20260414.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json" ;;
    crisis) echo "data/snapshots/snap_crisis_2022h1.json" ;;
  esac
}

abort() { echo "FATAL: $1" | tee -a "$LOG"; exit 1; }

echo "=== V212 2-pair 3-gate audit (hardened relaunch) starting at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
echo "PYTHONHASHSEED env at driver: ${PYTHONHASHSEED:-unset}" | tee -a "$LOG"
echo "VICTORIA_FEATURES: $FEATURES" | tee -a "$LOG"

pre_fp=$(sha256sum data/macro_cache.db data/omega_victoria_state.db data/omega_victoria_memory.db 2>/dev/null)
echo "Pre-audit fingerprints:" | tee -a "$LOG"
echo "$pre_fp" | tee -a "$LOG"

for gate in recent trend crisis; do
  snap=$(snap_for "$gate")
  for pair in p1 p2; do
    for run in r1 r2; do
      ver="v212_${gate}_${pair}_${run}"
      outdir="$AUDIT/${gate}_${pair}_${run}"

      # Disk precheck — abort cleanly rather than cascade-fail.
      avail=$(df -k "$ROOT" | awk 'NR==2{print $4}')
      if [ "$avail" -lt "$MIN_FREE_KB" ]; then
        abort "$ver: only ${avail}KB free (< ${MIN_FREE_KB}KB floor) — aborting before run to avoid ENOSPC cascade"
      fi

      mkdir -p "$outdir" || abort "$ver: mkdir failed (disk?)"
      echo "--- $ver starting $(date -u +%FT%TZ) (free=${avail}KB) ---" | tee -a "$LOG"
      PYTHONHASHSEED=42 python3 scripts/run_training.py \
        --version "$ver" \
        --cycles 200 --sleep 10 --seed 42 \
        --backtest-snapshot "$snap" \
        --frozen-cache \
        --features "$FEATURES" \
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

      # Hard gate: a run that produced no results.json means something is wrong
      # (disk, crash). Stop the whole audit instead of marching on.
      if [ ! -s "$outdir/results.json" ]; then
        abort "$ver produced no results.json (rc=$rc) — stopping audit to avoid faking the remaining cells on a broken environment"
      fi
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

echo "=== V212 audit finished at $(date -u +%FT%TZ) ===" | tee -a "$LOG"
