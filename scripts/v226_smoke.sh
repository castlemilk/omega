#!/bin/bash
# V226 smoke: 5-cycle frozen-cache run per snapshot with crisis_skew ON + the
# regime gate ON. Confirms (a) the banner reads `crisis_skew: ON (regime_gated=1,
# W=0.2)`, (b) the per-cycle gate-decision log fires, and (c) skew_on_cycles /
# gate accept-skip VARIES per snapshot (crisis → mostly accept/fire; trend/recent
# → mostly skip). This is the instrument V225 lacked — it learned only post-grid
# that the term fired every cycle.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
OUT=data/v226_smoke; mkdir -p "$OUT"
FEAT='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}'
snap_for(){ case "$1" in
  recent) echo data/snapshots/snap_20260414.json;;
  trend)  echo data/snapshots/snap_trending_2023q4.json;;
  crisis) echo data/snapshots/snap_crisis_2022h1.json;; esac; }

for gate in trend crisis recent; do
  snap=$(snap_for "$gate")
  echo "=== smoke $gate ($snap) $(date -u +%FT%TZ) ==="
  PYTHONHASHSEED=42 OMEGA_FROZEN_CACHE=1 python3 scripts/run_training.py \
    --version "v226_smoke_${gate}" --cycles 5 --sleep 10 --seed 42 \
    --backtest-snapshot "$snap" --frozen-cache --features "$FEAT" \
    > "$OUT/${gate}_stdout.log" 2> "$OUT/${gate}_stderr.log"
  echo "--- $gate banner ---"
  grep -h "crisis_skew:" "$OUT/${gate}_stdout.log" "$OUT/${gate}_stderr.log" 2>/dev/null | tail -1 || echo "(no banner)"
  echo "--- $gate gate_decision lines ---"
  grep -h "crisis_skew gate_decision" "$OUT/${gate}_stdout.log" "$OUT/${gate}_stderr.log" 2>/dev/null || echo "(none)"
  echo "--- $gate observability (skew_on / accept / skip) ---"
  python3 -c "import json;d=json.load(open('data/v226_smoke_${gate}_results.json'))['observability'];print('skew_on_cycles=',d.get('skew_on_cycles'),'gate_accept=',d.get('skew_gate_accept_cycles'),'gate_skip=',d.get('skew_gate_skip_cycles'))" 2>/dev/null || echo "(no results)"
done
echo "=== v226 smoke complete $(date -u +%FT%TZ) ==="
