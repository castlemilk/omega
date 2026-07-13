#!/bin/bash
# V251 Layer 2 — empirical output-equivalence (frozen arm vs live-rebuilt arm).
#
# For each sentinel window (one per regime) run the IDENTICAL eval (SELECTIVE
# config, the standing V240 baseline; all V241-V248 flags OFF, V243_A blacklist
# ext OFF) twice per arm (N=2 for determinism):
#   Arm A (backtest) : SNAP_OVERRIDE = committed frozen snapshot.
#   Arm B (live-repl): SNAP_OVERRIDE = v251/live_snapshots/<wid>.json (live OHLCV,
#                      macro held frozen per §6).
# Since Layer-1 proved OHLCV is bit-identical, the hermetic eval MUST yield
# identical trades+PnL: Arm A PnL == Arm B PnL. This run CONFIRMS that chain
# empirically on this code+config and certifies determinism (N=2 spread).
#
# Usage:
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   bash scripts/v251_layer2.sh
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"
LIVE_DIR="$AUDIT_DIR/v251/live_snapshots"
SLEEP=0; FLOOR=200; N=2
SELECTIVE='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'

# wid|regime|cycles|frozen_path
SENTINELS=(
  "snap_wf_20240310|crisis|60|data/snapshots/walk_forward/snap_wf_20240310.json"
  "snap_wf_20230912|trend|60|data/snapshots/walk_forward/snap_wf_20230912.json"
  "snap_wf_20250305|recent|60|data/snapshots/walk_forward/snap_wf_20250305.json"
)

run_arm() { # gate cycles snap vprefix
  local gate="$1" cycles="$2" snap="$3" vprefix="$4"
  CYCLES="$cycles" SNAP_OVERRIDE="$snap" WINDOW_LABEL="$vprefix" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=off EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$gate" "$N" "$SELECTIVE" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$AUDIT_DIR/${vprefix}.log" 2>&1
  echo "rc=$? $vprefix"
}

echo "=== V251 Layer 2 start $(date -u +%FT%TZ) — SELECTIVE config, N=$N/arm ==="
for c in "${SENTINELS[@]}"; do
  IFS='|' read -r wid regime cycles fpath <<< "$c"
  lpath="$LIVE_DIR/${wid}.json"
  [ -f "$lpath" ] || { echo "FATAL: live snapshot missing: $lpath (run v251_reconcile.py build first)"; exit 2; }
  # restore committed macro_cache before each window (grid discipline)
  git checkout -q data/macro_cache.db 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true
  echo "--- $wid [$regime] Arm A (frozen) ---"
  run_arm "$regime" "$cycles" "$fpath" "v251_${wid}_frozen"
  git checkout -q data/macro_cache.db 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true
  echo "--- $wid [$regime] Arm B (live) ---"
  run_arm "$regime" "$cycles" "$lpath" "v251_${wid}_live"
done
echo "=== V251 Layer 2 complete $(date -u +%FT%TZ) ==="
