#!/bin/bash
# V222 — sequential determinism + IC re-baseline grid (NOT committed; run harness).
# 4 determinism cells (IC ON) at sleep=10 N=2, then 3 IC-off controls (N=1)
# that must reproduce the V221 hermetic baseline exactly.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
SUM=data/v222_grid_progress.log
: > "$SUM"
echo "=== V222 grid start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

run_cell() {
  local gate="$1" n="$2" features="$3" vprefix="$4"
  echo "--- cell $vprefix gate=$gate N=$n features=$features start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
}

# Determinism cells, IC ON (committed defaults), thesis gate first.
run_cell recent 2 '{}' v222_ic
run_cell trend  2 '{}' v222_ic
run_cell crisis 2 '{}' v222_ic
run_cell trend  2 '{"strategy_selector_enabled": true}' v222_icsel

# IC-off controls (must equal V221: recent 4901.01/22t, trend 631.85/23t, crisis -3599.74/31t).
run_cell recent 1 '{"ic_seed_weighting": false}' v222_ctl
run_cell trend  1 '{"ic_seed_weighting": false}' v222_ctl
run_cell crisis 1 '{"ic_seed_weighting": false}' v222_ctl

echo "=== V222 grid complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"
