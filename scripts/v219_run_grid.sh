#!/bin/bash
# V219 — sequential determinism + re-baseline grid (NOT committed; run harness).
# Cells run sequentially (shared state.db/memory.db => no concurrency). Each cell
# is check_determinism.sh N=2 sleep=10, which restores frozen state before each
# replicate. Emits a final aggregate to data/v219_grid_summary.txt.
set -u
cd "$(dirname "$0")/.."
LOG=data/v219_grid.log
SUM=data/v219_grid_summary.txt
: > "$LOG"; : > "$SUM"
echo "V219 GRID START $(date -u +%FT%TZ)" | tee -a "$LOG" "$SUM"

run_cell() {  # label gate features prefix
  local label="$1" gate="$2" feats="$3" prefix="$4"
  echo "=== CELL $label ($gate, $feats) START $(date -u +%FT%TZ) ===" | tee -a "$LOG"
  scripts/check_determinism.sh "$gate" 2 "$feats" "$prefix" 200 10 >> "$LOG" 2>&1
  local verdict_line
  verdict_line=$(grep -h "DETERMINISM:" "$LOG" | tail -1)
  echo "$label: $verdict_line" | tee -a "$SUM"
}

# Phase 1: trend determinism (required) — OFF then ON.
run_cell "trend_OFF" trend '{}' v219_det_off
run_cell "trend_ON"  trend '{"strategy_selector_enabled": true}' v219_det_on
# Phase 2: re-baseline + determinism on the other two gates (selector OFF).
run_cell "crisis_OFF" crisis '{}' v219_base_crisis
run_cell "recent_OFF" recent '{}' v219_base_recent

echo "V219 GRID DONE $(date -u +%FT%TZ)" | tee -a "$LOG" "$SUM"
echo "--- per-cell results.json PnL ---" | tee -a "$SUM"
for p in v219_det_off_trend v219_det_on_trend v219_base_crisis_crisis v219_base_recent_recent; do
  d="data/${p}_determinism"
  for r in r1 r2; do
    f="$d/${p}_${r}_results.json"
    [ -f "$f" ] && python3 - "$f" "${p}_${r}" <<'PY' | tee -a "$SUM"
import json,sys
t=json.load(open(sys.argv[1]))["trades"]
print(f"  {sys.argv[2]}: pnl=${t.get('total_pnl_usd',0):,.2f} trades={t.get('total_closed',0)} "
      f"wr={t.get('win_rate',0):.4f} pf={t.get('profit_factor',0):.3f}")
PY
  done
done
echo "V219 GRID COMPLETE" | tee -a "$SUM"
