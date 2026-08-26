#!/bin/bash
# V225 — additive crisis-skew decisive grid (run harness; not committed as data).
# 6 cells at sleep=10 N=2 = the full re-baseline AND the determinism gate AND the
# cell-identity assertion, in one pass:
#   skew-ON cells  (crisis_skew_enabled:true,  ic_seed_weighting:false):
#     1. trend  ON   — does the crisis brake HARM trend? (no-harm falsifier)
#     2. crisis ON   — does it improve the chronically-negative crisis gate?
#     3. recent ON   — does it HARM recent? (no-harm falsifier)
#   skew-OFF control cells (crisis_skew_enabled:false, ic_seed_weighting:false) —
#   the DECISIVE within-grid equal-weight baseline (same commit + caches, avoids
#   cross-version FP-recanon drift):
#     4. trend  OFF
#     5. crisis OFF
#     6. recent OFF
# Every cell: N=2 determinism (PASS <$200, ideally $0.00) + assert_cell_identity
# (EXPECT_SKEW/EXPECT_IC) — a cell whose run does not match its label aborts the
# cell (exit 4). Pre-committed fork: skew-ON beats within-grid skew-OFF on crisis
# by >$200 WITHOUT regressing trend OR recent by >$200.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
SUM=data/v225_grid_progress.log
: > "$SUM"
echo "=== V225 grid start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

# run_cell GATE N FEATURES VPREFIX EXPECT_SKEW
run_cell() {
  local gate="$1" n="$2" features="$3" vprefix="$4" expect_skew="$5"
  echo "--- cell $vprefix gate=$gate N=$n skew=$expect_skew features=$features start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  EXPECT_SKEW="$expect_skew" EXPECT_IC=off \
    bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "CELL-IDENTITY:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -2 | tee -a "$SUM"
}

ON='{"crisis_skew_enabled": true, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# skew-ON cells (the thesis).
run_cell trend  2 "$ON" v225_skew_on  on
run_cell crisis 2 "$ON" v225_skew_on  on
run_cell recent 2 "$ON" v225_skew_on  on
# skew-OFF within-grid equal-weight controls (decisive baseline).
run_cell trend  2 "$OFF" v225_skew_off off
run_cell crisis 2 "$OFF" v225_skew_off off
run_cell recent 2 "$OFF" v225_skew_off off

echo "=== V225 grid complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"
