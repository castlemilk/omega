#!/bin/bash
# V228: stack the drawdown-gated crisis-skew (V227, default ON) with the trend-IC
# overlay (R3 empirical ICs, V224, banked +$2,206). 6 cells = 3 gates x
# {stack-ON, both-OFF}, N=2 @ sleep=10 (canonical eval condition). Decisive
# comparison = stack-ON vs within-grid both-OFF equal-weight control, same commit
# + frozen caches.
#
# stack-ON = crisis_skew defaults ON (V227) + the IC overlay turned on via the two
#   seed/gate flags + the OMEGA_R3_ICS=1 env (R3 empirical IC table).
# both-OFF = crisis_skew OFF AND equal-weight. ic_seed_weighting:false is MANDATORY
#   ({} would silently run seed-IC — the V224 control bug).
set -u
cd "$(dirname "$0")/.."

ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "ic_seed_weighting": true, "regime_conditional_ic_weighting": true}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# cell GATE ARM FEATS ESKEW EGATE EIC R3
cell() {
  local gate="$1" arm="$2" feats="$3" eskew="$4" egate="$5" eic="$6" r3="$7"
  echo "######## CELL $gate $arm $(date -u +%FT%TZ) ########"
  if [ "$r3" = "1" ]; then
    EXPECT_SKEW="$eskew" EXPECT_GATE="$egate" EXPECT_IC="$eic" OMEGA_R3_ICS=1 \
      bash scripts/check_determinism.sh "$gate" 2 "$feats" "v228_grid_${arm}" 200 10
  else
    EXPECT_SKEW="$eskew" EXPECT_GATE="$egate" EXPECT_IC="$eic" \
      bash scripts/check_determinism.sh "$gate" 2 "$feats" "v228_grid_${arm}" 200 10
  fi
}

for g in trend crisis recent; do
  cell "$g" off "$OFF" off off off 0
  cell "$g" on  "$ON"  on  on  on  1
done
echo "ALL GRID DONE $(date -u +%FT%TZ)"
