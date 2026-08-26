#!/bin/bash
# V229: drawdown-gate the trend-IC overlay (the V227 fix, applied to IC). 6 cells =
# 3 gates x {stack-ON, both-OFF}, N=2 @ sleep=10 (canonical eval condition).
# Decisive comparison = V229-stack-ON vs within-grid both-OFF equal-weight control,
# same commit + frozen caches.
#
# V229-stack-ON = the V228 stack (crisis_skew default ON + the IC overlay via the two
#   seed/gate flags + OMEGA_R3_ICS=1) PLUS the NEW per-ticker IC drawdown-gate
#   (ic_drawdown_gate_enabled + ic_drawdown_threshold=0.12). The gate bypasses IC to
#   equal-weight on genuine-drawdown cycles even when labeled normal — the V228 fix.
# both-OFF = crisis_skew OFF AND equal-weight. ic_seed_weighting:false is MANDATORY
#   ({} would silently run seed-IC — the V224 control bug).
#
# Per-decision IC gate log: OMEGA_IC_DD_LOG sink written per ON cell (skip/accept).
set -u
cd "$(dirname "$0")/.."

ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "ic_seed_weighting": true, "per_regime_ic_weighting": true, "regime_conditional_ic_weighting": true, "ic_drawdown_gate_enabled": true, "ic_drawdown_threshold": 0.12}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# cell GATE ARM FEATS ESKEW EGATE EIC R3
cell() {
  local gate="$1" arm="$2" feats="$3" eskew="$4" egate="$5" eic="$6" r3="$7"
  echo "######## CELL $gate $arm $(date -u +%FT%TZ) ########"
  local icdd="data/v229_grid_${arm}_${gate}_ic_dd.jsonl"; : > "$icdd"
  if [ "$r3" = "1" ]; then
    EXPECT_SKEW="$eskew" EXPECT_GATE="$egate" EXPECT_IC="$eic" OMEGA_R3_ICS=1 OMEGA_IC_DD_LOG="$icdd" \
      bash scripts/check_determinism.sh "$gate" 2 "$feats" "v229_grid_${arm}" 200 10
  else
    EXPECT_SKEW="$eskew" EXPECT_GATE="$egate" EXPECT_IC="$eic" \
      bash scripts/check_determinism.sh "$gate" 2 "$feats" "v229_grid_${arm}" 200 10
  fi
}

for g in trend crisis recent; do
  cell "$g" off "$OFF" off off off 0
  cell "$g" on  "$ON"  on  on  on  1
done
echo "ALL GRID DONE $(date -u +%FT%TZ)"
