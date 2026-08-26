#!/bin/bash
# V223 — determinism gate + regime-gated-IC re-baseline grid (NOT committed; run harness).
# 4 cells at sleep=10 N=2, regime_conditional_ic_weighting ON in every cell (that
# IS V223). These determinism cells double as the re-baseline PnL measurement; the
# V222-IC-on comparison column comes from V222.md (full-on IC, no re-run needed).
#   1. trend  selOFF  — thesis gate (does the trend gain survive 48% bypass?)
#   2. trend  selON   — selector + regime-gate interaction
#   3. crisis selOFF  — does crisis recover (79/200 cycles bypass)?
#   4. recent selOFF  — does recent recover (113/200 cycles bypass)?
# Falsifier is "all 4 cells PASS <$200", per the layered-channel rule.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
SUM=data/v223_grid_progress.log
: > "$SUM"
echo "=== V223 grid start $(date -u +%FT%TZ) ===" | tee -a "$SUM"

run_cell() {
  local gate="$1" n="$2" features="$3" vprefix="$4"
  echo "--- cell $vprefix gate=$gate N=$n features=$features start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  bash scripts/check_determinism.sh "$gate" "$n" "$features" "$vprefix" 200 10 >> "$SUM" 2>&1
  echo "--- cell $vprefix done rc=$? $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  grep -h "V223. IC-gate summary" "data/${vprefix}_${gate}_determinism/"*_stdout.log 2>/dev/null | tail -1 | tee -a "$SUM"
}

# regime-gated IC ON in all cells; thesis gate (trend selOFF) first.
run_cell trend  2 '{"regime_conditional_ic_weighting": true}' v223_rg
run_cell crisis 2 '{"regime_conditional_ic_weighting": true}' v223_rg
run_cell recent 2 '{"regime_conditional_ic_weighting": true}' v223_rg
run_cell trend  2 '{"regime_conditional_ic_weighting": true, "strategy_selector_enabled": true}' v223_rgsel

echo "=== V223 grid complete $(date -u +%FT%TZ) ===" | tee -a "$SUM"