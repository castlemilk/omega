#!/bin/bash
# V224 corrective — the MISSING equal-weight (true IC-off) control cells.
#
# WHY: v224_run_grid.sh ran its "IC-off" control cells with features='{}', but
# `ic_seed_weighting` DEFAULTS TO True (features.py:680), so those cells ran
# SEED-IC weighting on all 200 cycles (ic_source=seed, ic_on=200) — NOT the
# equal-weight baseline V224.md pre-registered as the decisive within-grid
# control (V224.md:144 "an OMEGA_R3_ICS unset / ic_seed_weighting:false control
# cell"). Seed-IC was already refuted twice (V222, V223); the decisive fork is
# R3-empirical vs EQUAL-WEIGHT, which the grid never measured.
#
# This runs the 3 equal-weight controls at the SAME commit (053d3d0) + caches so
# the R3 vs equal-weight comparison is within-grid (no cross-version FP drift).
# Equal-weight = ic_seed_weighting:false → _signal_ics empty → conviction path
# early-returns the raw composite on all cycles.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
SUM=data/v224_eqw_progress.log
: > "$SUM"
echo "=== V224 equal-weight controls start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

run_cell() {
  local gate="$1" vprefix="$2"
  echo "--- cell $vprefix gate=$gate equal-weight (ic_seed_weighting:false) start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  bash scripts/check_determinism.sh "$gate" 2 '{"ic_seed_weighting": false}' "$vprefix" 200 10 >> "$SUM" 2>&1
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "total_pnl_usd" "data/${vprefix}_${gate}_determinism/${vprefix}_${gate}_r1_results.json" 2>/dev/null | tail -1 | tee -a "$SUM"
}

run_cell trend  v224_eqw
run_cell crisis v224_eqw
run_cell recent v224_eqw

echo "=== V224 equal-weight controls complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"
