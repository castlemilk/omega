#!/bin/bash
# V233 smoke: 5-cycle frozen-cache run per (config × crisis snapshot). Confirms
# (a) the new V233 site flags parse + fire (skew_on_cycles>0 via the pre-demean path,
# predemean_enabled=true, mode/weight as claimed), (b) the per-cycle
# `crisis_skew[V233 site=...]` log line fires, (c) the wallclock + frozen-HTTP fences
# PASS (the site change is pure arithmetic — must not introduce any leak), and (d)
# post_demean default is byte-reachable. Fast (5 cycles) — NOT a determinism gate
# (that's the grid). Per the V233 brief's smoke step.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
OUT=data/v233_smoke; mkdir -p "$OUT"

BASE='"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false'
feats_for() {
  case "$1" in
    post_demean_w0.2)            echo "{$BASE}" ;;
    pre_demean_w0.2)             echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean\", \"crisis_term_gated_weight\": 0.2}" ;;
    pre_demean_w0.6)             echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean\", \"crisis_term_gated_weight\": 0.6}" ;;
    pre_demean_common_mode_w0.2) echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean_common_mode\", \"crisis_term_gated_weight\": 0.2}" ;;
  esac
}
expect_for() {
  case "$1" in
    post_demean_w0.2)            echo "post_demean" ;;
    pre_demean_w0.2)             echo "pre_demean:0.2" ;;
    pre_demean_w0.6)             echo "pre_demean:0.6" ;;
    pre_demean_common_mode_w0.2) echo "pre_demean_common_mode:0.2" ;;
  esac
}

CONFIGS="${CONFIGS:-post_demean_w0.2 pre_demean_w0.2 pre_demean_w0.6 pre_demean_common_mode_w0.2}"
# Crisis snapshots only — the binding distribution. 2024aug is the key window.
SNAPS="${SNAPS:-data/snapshots/snap_crisis_2020q1.json data/snapshots/snap_crisis_2022h1.json data/snapshots/snap_crisis_2024aug.json}"

echo "=== V233 smoke start $(date -u +%FT%TZ) ==="
echo "--- source tripwires (wallclock + frozen-HTTP fence) ---"
python3 scripts/check_no_wallclock.py && echo "WALLCLOCK: PASS" || echo "WALLCLOCK: FAIL"
python3 scripts/check_frozen_http_fence.py && echo "FENCE: PASS" || echo "FENCE: FAIL"

for cfg in $CONFIGS; do
  feats="$(feats_for "$cfg")"; epd="$(expect_for "$cfg")"
  for snap in $SNAPS; do
    wlabel="$(basename "$snap" .json)"
    ver="v233_smoke_${cfg}_${wlabel}"
    echo "=== smoke $cfg @ $wlabel ($epd) $(date -u +%FT%TZ) ==="
    PYTHONHASHSEED=42 OMEGA_FROZEN_CACHE=1 python3 scripts/run_training.py \
      --version "$ver" --cycles 5 --sleep 10 --seed 42 \
      --backtest-snapshot "$snap" --frozen-cache --features "$feats" \
      > "$OUT/${ver}_stdout.log" 2> "$OUT/${ver}_stderr.log"
    rc=$?
    echo "--- $ver rc=$rc ---"
    grep -h "crisis_skew\[V233 site=" "$OUT/${ver}_stdout.log" "$OUT/${ver}_stderr.log" 2>/dev/null | tail -2 || echo "(no V233 site log — expected for post_demean)"
    python3 -c "import json;d=json.load(open('data/${ver}_results.json'))['observability'];print('  predemean_enabled=',d.get('crisis_term_predemean_enabled'),'mode=',d.get('crisis_term_predemean_mode'),'w=',d.get('crisis_term_gated_weight'),'skew_on_cycles=',d.get('skew_on_cycles'),'gate_accept=',d.get('skew_gate_accept_cycles'))" 2>/dev/null || echo "  (no results)"
    echo "--- $ver cell-identity ---"
    python3 scripts/assert_cell_identity.py --results "data/${ver}_results.json" \
      --expect-skew on --expect-ic off --expect-gate on --expect-predemean "$epd" 2>&1 | tail -1 || echo "  (identity FAIL)"
  done
done
echo "=== V233 smoke complete $(date -u +%FT%TZ) ==="
