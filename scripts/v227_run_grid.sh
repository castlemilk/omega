#!/bin/bash
# V227 Track B falsifier grid: drawdown-gated crisis-skew (X=0.12) vs within-grid
# skew-OFF equal-weight control, per gate. Same fenced commit + frozen caches,
# both IC-off. N=2 for determinism + cell-identity. recent-OFF is reused from the
# Track C run (v227_fence_off_recent = +$4,901.01, byte-identical OFF path).
set -u
cd "$(dirname "$0")/.."

ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

cell() {
  local gate="$1" arm="$2" feats="$3" eskew="$4" egate="$5"
  echo "######## CELL $gate $arm $(date -u +%FT%TZ) ########"
  EXPECT_SKEW="$eskew" EXPECT_IC=off EXPECT_GATE="$egate" \
    bash scripts/check_determinism.sh "$gate" 1 "$feats" "v227_grid_${arm}" 200 0
}

# trend
cell trend  off "$OFF" off off
cell trend  on  "$ON"  on  on
# crisis (the target gate)
cell crisis off "$OFF" off off
cell crisis on  "$ON"  on  on
# recent (OFF reused from Track C; run ON only)
cell recent on  "$ON"  on  on
echo "ALL GRID DONE $(date -u +%FT%TZ)"
