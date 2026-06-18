#!/bin/bash
# V226 — regime-gated crisis-skew decisive grid (run harness; not committed as data).
# 6 cells at sleep=10 N=2 = full re-baseline AND determinism gate AND cell-identity
# assertion, in one pass:
#   skew-ON+gated cells (crisis_skew_enabled:true, crisis_skew_regime_gate_enabled:
#   true, ic_seed_weighting:false) — the V226 thesis (W=0.2, term gated to
#   {crisis,high_vol} only):
#     1. trend  ON   — does the gate keep the brake OFF trend? (no-harm falsifier)
#     2. crisis ON   — does the gated brake improve the crisis gate?
#     3. recent ON   — does the gate keep the brake OFF recent? (no-harm falsifier)
#   skew-OFF control cells (crisis_skew_enabled:false, ic_seed_weighting:false) —
#   the DECISIVE within-grid equal-weight baseline (same commit + caches):
#     4. trend  OFF
#     5. crisis OFF
#     6. recent OFF
# Every cell: N=2 determinism (PASS <$200) + assert_cell_identity. The skew-ON
# cells pass EXPECT_GATE=on so a gated-to-zero cell (skew_on_cycles==0 on
# trend/recent) is NOT mis-flagged as silently inert — the gate-aware assertion
# instead requires the gate was EVALUATED. Pre-committed fork: gated skew-ON beats
# within-grid skew-OFF on crisis by >$200 WITHOUT regressing trend OR recent >$200.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
SUM=data/v226_grid_progress.log
: > "$SUM"
echo "=== V226 grid start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

# run_cell GATE N FEATURES VPREFIX EXPECT_SKEW EXPECT_GATE
run_cell() {
  local gate="$1" n="$2" features="$3" vprefix="$4" expect_skew="$5" expect_gate="$6"
  echo "--- cell $vprefix gate=$gate N=$n skew=$expect_skew gate_flag=$expect_gate features=$features start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  EXPECT_SKEW="$expect_skew" EXPECT_IC=off EXPECT_GATE="$expect_gate" \
    bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "CELL-IDENTITY:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -2 | tee -a "$SUM"
}

ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# skew-ON+gated cells (the thesis).
run_cell trend  2 "$ON" v226_skew_on  on  on
run_cell crisis 2 "$ON" v226_skew_on  on  on
run_cell recent 2 "$ON" v226_skew_on  on  on
# skew-OFF within-grid equal-weight controls (decisive baseline).
run_cell trend  2 "$OFF" v226_skew_off off off
run_cell crisis 2 "$OFF" v226_skew_off off off
run_cell recent 2 "$OFF" v226_skew_off off off

echo "=== V226 grid complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"
