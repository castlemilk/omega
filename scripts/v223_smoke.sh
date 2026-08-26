#!/bin/bash
# V223 smoke: 5-cycle run per snapshot with the regime gate ON, confirm the
# per-cycle IC-gate log fires as designed (trend→ACTIVE, crisis→BYPASS, recent→mix).
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
OUT=data/v223_smoke; mkdir -p "$OUT"
FEAT='{"regime_conditional_ic_weighting": true}'
snap_for(){ case "$1" in
  recent) echo data/snapshots/snap_20260414.json;;
  trend)  echo data/snapshots/snap_trending_2023q4.json;;
  crisis) echo data/snapshots/snap_crisis_2022h1.json;; esac; }

for gate in trend crisis recent; do
  snap=$(snap_for "$gate")
  echo "=== smoke $gate ($snap) $(date -u +%FT%TZ) ==="
  PYTHONHASHSEED=42 python3 scripts/run_training.py \
    --version "v223_smoke_${gate}" --cycles 5 --sleep 10 --seed 42 \
    --backtest-snapshot "$snap" --frozen-cache --features "$FEAT" \
    > "$OUT/${gate}_stdout.log" 2> "$OUT/${gate}_stderr.log"
  echo "--- $gate IC-gate lines ---"
  grep -h "V223 IC-gate" "$OUT/${gate}_stdout.log" "$OUT/${gate}_stderr.log" 2>/dev/null || echo "(none found)"
  echo "--- $gate results ic_on/off cycles ---"
  python3 -c "import json;d=json.load(open('data/v223_smoke_${gate}_results.json'))['observability'];print('ic_on_cycles=',d.get('ic_on_cycles'),'ic_off_cycles=',d.get('ic_off_cycles'))" 2>/dev/null || echo "(no results)"
done
echo "=== v223 smoke complete $(date -u +%FT%TZ) ==="
