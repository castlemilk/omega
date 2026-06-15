#!/bin/bash
# V224 — empirical-IC (R3) decisive grid (NOT committed as data; run harness).
# 6 cells at sleep=10 N=2:
#   R3 cells (gate ON + OMEGA_R3_ICS=1, empirical OOS-holdout ICs):
#     1. trend  R3    — does the empirical IC beat equal-weight on trend?
#     2. crisis R3    — does empirical fix the 121 normal-labeled crisis cycles?
#     3. recent R3    — does empirical preserve recent?
#   IC-off control cells (ic_seed_weighting:false → equal-weight) at THIS commit,
#   the DECISIVE within-grid baseline (avoids cross-version FP-recanon drift):
#     4. trend  OFF
#     5. crisis OFF
#     6. recent OFF
# Determinism falsifier: all cells PASS <$200 (ideally $0.00). Pre-committed fork:
# R3 beats within-grid IC-off by >$200 on >=2 of {trend,crisis,recent} -> IC rehab.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
SUM=data/v224_grid_progress.log
: > "$SUM"
echo "=== V224 grid start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

run_cell() {
  local gate="$1" n="$2" features="$3" vprefix="$4" r3="$5"
  echo "--- cell $vprefix gate=$gate N=$n R3=$r3 features=$features start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  if [ "$r3" = "1" ]; then
    OMEGA_R3_ICS=1 bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  else
    bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  fi
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "IC-gate summary" "data/${vprefix}_${gate}_determinism/"*_stdout.log 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "total_pnl_usd" "data/${vprefix}_${gate}_determinism/${vprefix}_${gate}_r1_results.json" 2>/dev/null | tail -1 | tee -a "$SUM"
}

R3F='{"ic_seed_weighting": true, "regime_conditional_ic_weighting": true}'

# R3 cells first (the thesis).
run_cell trend  2 "$R3F" v224_r3 1
run_cell crisis 2 "$R3F" v224_r3 1
run_cell recent 2 "$R3F" v224_r3 1
# IC-off controls (decisive within-grid baseline).
run_cell trend  2 '{}' v224_off 0
run_cell crisis 2 '{}' v224_off 0
run_cell recent 2 '{}' v224_off 0

echo "=== V224 grid complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"
