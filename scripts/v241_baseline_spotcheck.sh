#!/bin/bash
# V241 preflight — standing-baseline reproducibility spot-check.
#
# Re-runs 4 of the 32 V240 confirm cells (one per regime + one N=2 sentinel)
# under the identical selective-universe config and byte-compares trades.csv
# against the archived v240wf_* cells on gamma. PASS = all 4 byte-identical.
#
# Usage:
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   bash scripts/v241_baseline_spotcheck.sh
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"
if [ "$AUDIT_DIR" != "data" ]; then
  export TMPDIR="${TMPDIR:-$AUDIT_DIR/tmp}"; mkdir -p "$TMPDIR"
fi
OUT="$AUDIT_DIR/v241/baseline_spotcheck"; mkdir -p "$OUT"

SELECTIVE='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'

# wid|regime|path|cycles
CELLS="snap_wf_20200101|crisis|data/snapshots/walk_forward/snap_wf_20200101.json|60
snap_wf_20200331|trend|data/snapshots/walk_forward/snap_wf_20200331.json|60
snap_wf_20200813|recent|data/snapshots/walk_forward/snap_wf_20200813.json|55
snap_wf_20250305|recent|data/snapshots/walk_forward/snap_wf_20250305.json|60"

overall=PASS
while IFS='|' read -r wid regime path cycles; do
  [ -z "$wid" ] && continue
  vprefix="v241base_${wid}"
  echo "--- SPOTCHECK $wid ($regime, $cycles cycles) $(date -u +%FT%TZ) ---"
  git checkout -q data/macro_cache.db 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true
  CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=off EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$regime" 1 "$SELECTIVE" "$vprefix" 200 0 \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  new="$AUDIT_DIR/${vprefix}_${regime}_determinism/${vprefix}_${regime}_r1_trades.csv"
  ref="$AUDIT_DIR/v240wf_${wid}_universe_selective_${regime}_determinism/v240wf_${wid}_universe_selective_${regime}_r1_trades.csv"
  if [ ! -f "$new" ] || [ ! -f "$ref" ]; then
    echo "SPOTCHECK $wid: MISSING FILE (rc=$rc new=$new ref=$ref)"; overall=FAIL
  # trades.csv column 2 is the run wall-clock timestamp (pure metadata) —
  # identity is asserted on every OTHER field, the same contract the
  # determinism arc certifies (trade_field_diff excludes run timestamps).
  elif cmp -s <(cut -d, -f1,3- "$new") <(cut -d, -f1,3- "$ref"); then
    echo "SPOTCHECK $wid: IDENTICAL to V240 confirm cell (all fields except run timestamp) (rc=$rc)"
  else
    echo "SPOTCHECK $wid: DIFFERS from V240 confirm cell (rc=$rc)"; overall=FAIL
    diff <(cut -d, -f1,3- "$new") <(cut -d, -f1,3- "$ref") | head -10
  fi
done <<< "$CELLS"

echo "SPOTCHECK OVERALL: $overall"
[ "$overall" = "PASS" ]
