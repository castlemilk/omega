#!/bin/bash
# V221 — determinism grid with the signal_generation.py:1160 fsum demean fence.
# 4 cells, sequential (shared state.db/memory.db => no concurrency), each
# check_determinism.sh N=2 sleep=10 floor=$200. Prefixes mirror V220 so the
# r1/r2 artifacts line up cell-for-cell with the V220 baseline.
# Acceptance = 4/4 PASS (all spreads < $200, ideally < $50).
set -u
cd "$(dirname "$0")/.."
LOG=data/v221_grid.log
SUM=data/v221_grid_summary.txt
: > "$LOG"; : > "$SUM"
echo "V221 GRID START $(date -u +%FT%TZ)" | tee -a "$LOG" "$SUM"

run_cell() {  # label gate features prefix
  local label="$1" gate="$2" feats="$3" prefix="$4"
  echo "=== CELL $label ($gate, $feats) START $(date -u +%FT%TZ) ===" | tee -a "$LOG"
  scripts/check_determinism.sh "$gate" 2 "$feats" "$prefix" 200 10 >> "$LOG" 2>&1
  local verdict_line
  verdict_line=$(grep -h "DETERMINISM:" "$LOG" | tail -1)
  echo "$label: $verdict_line" | tee -a "$SUM"
}

run_cell "trend_OFF"  trend  '{}'                                  v221_det_off
run_cell "trend_ON"   trend  '{"strategy_selector_enabled": true}' v221_det_on
run_cell "crisis_OFF" crisis '{}'                                  v221_base_crisis
run_cell "recent_OFF" recent '{}'                                  v221_base_recent

echo "V221 GRID DONE $(date -u +%FT%TZ)" | tee -a "$LOG" "$SUM"
echo "--- per-cell results.json PnL ---" | tee -a "$SUM"
for p in v221_det_off_trend v221_det_on_trend v221_base_crisis_crisis v221_base_recent_recent; do
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
echo "V221 GRID COMPLETE" | tee -a "$SUM"
