#!/bin/bash
# V215 determinism driver: runs the two pre-registered gates SEQUENTIALLY at the
# canonical sleep=10 (concurrent runs would clobber the shared data/*.db state
# that check_determinism.sh restores per replicate).
#   1. trend, selector ON,  N=4  — headline acceptance (was $1,510 FAIL at V214)
#   2. trend, selector OFF, N=2  — amplifier-reframe control
set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
MARK="$ROOT/data/v215_determinism_DONE.txt"
: > "$MARK.running"

echo "=== V215 determinism driver start $(date -u +%FT%TZ) ===" | tee "$ROOT/data/v215_determinism_driver.log"

echo ">>> GATE 1: trend ON N=4 sleep=10" | tee -a "$ROOT/data/v215_determinism_driver.log"
scripts/check_determinism.sh trend 4 '{"strategy_selector_enabled": true}' v215_on 200 10 \
  >> "$ROOT/data/v215_determinism_driver.log" 2>&1

echo ">>> GATE 2: trend OFF N=2 sleep=10" | tee -a "$ROOT/data/v215_determinism_driver.log"
scripts/check_determinism.sh trend 2 '{}' v215_off 200 10 \
  >> "$ROOT/data/v215_determinism_driver.log" 2>&1

echo "=== V215 determinism driver complete $(date -u +%FT%TZ) ===" | tee -a "$ROOT/data/v215_determinism_driver.log"
echo "ON  summary:" >> "$ROOT/data/v215_determinism_driver.log"
cat "$ROOT/data/v215_on_trend_determinism/summary.json" 2>/dev/null >> "$ROOT/data/v215_determinism_driver.log"
echo "OFF summary:" >> "$ROOT/data/v215_determinism_driver.log"
cat "$ROOT/data/v215_off_trend_determinism/summary.json" 2>/dev/null >> "$ROOT/data/v215_determinism_driver.log"
mv "$MARK.running" "$MARK"
