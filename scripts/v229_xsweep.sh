#!/bin/bash
# V229 X-calibration sweep (pre-registered Step 2). At X=0.12 the IC drawdown gate
# fired 42x/run on crisis with ~$0 effect → test whether a LOWER X recovers crisis,
# and whether trend's IC edge survives the lower X (the joint-feasibility question).
# N=1 per cell — the gate mechanism's determinism is already certified at X=0.12 N=2
# ($0.00); a different threshold constant is the same code path, so this is a PnL read.
set -u
cd "$(dirname "$0")/.."
sweep() {
  local gate="$1" x="$2"
  local feats="{\"crisis_skew_enabled\": true, \"crisis_skew_regime_gate_enabled\": true, \"crisis_skew_drawdown_threshold\": 0.12, \"ic_seed_weighting\": true, \"per_regime_ic_weighting\": true, \"regime_conditional_ic_weighting\": true, \"ic_drawdown_gate_enabled\": true, \"ic_drawdown_threshold\": ${x}}"
  local tag="v229_sweep_x${x/./}"
  local icdd="data/${tag}_${gate}_ic_dd.jsonl"; : > "$icdd"
  echo "######## SWEEP $gate X=$x $(date -u +%FT%TZ) ########"
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=on OMEGA_R3_ICS=1 OMEGA_IC_DD_LOG="$icdd" \
    bash scripts/check_determinism.sh "$gate" 1 "$feats" "$tag" 200 10
}
for x in 0.08 0.05; do
  for g in trend crisis; do
    sweep "$g" "$x"
  done
done
echo "ALL SWEEP DONE $(date -u +%FT%TZ)"
