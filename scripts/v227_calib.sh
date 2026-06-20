#!/bin/bash
# V227 Track B calibration: run each gate with the regime gate ON and
# drawdown_threshold=0, harvest the per-cycle dd_max distribution among
# regime-accepted cycles so X can be chosen to keep skew_on_cycles < 40.
set -u
cd "$(dirname "$0")/.."

FEAT='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.0, "ic_seed_weighting": false}'

run_one() {
  local g="$1" snap="$2"
  echo "=== calib $g start $(date -u +%FT%TZ) ==="
  rm -f "data/v227_calib_${g}_dd.jsonl"
  PYTHONHASHSEED=42 OMEGA_FROZEN_CACHE=1 OMEGA_SKEW_DD_LOG="data/v227_calib_${g}_dd.jsonl" \
    python3 scripts/run_training.py \
    --version "v227_calib_$g" --cycles 200 --sleep 0 --seed 42 \
    --backtest-snapshot "$snap" --frozen-cache \
    --features "$FEAT" > "data/v227_calib_${g}.stdout" 2> "data/v227_calib_${g}.stderr"
  echo "=== calib $g done rc=$? $(date -u +%FT%TZ) ==="
}

run_one trend  data/snapshots/snap_trending_2023q4.json
run_one recent data/snapshots/snap_20260414.json
run_one crisis data/snapshots/snap_crisis_2022h1.json
echo "ALL CALIB DONE"
