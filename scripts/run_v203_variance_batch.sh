#!/usr/bin/env bash
# V203 variance batch — 12 runs, ~6 hours total.
# Pins strategy.py at V199 and V201 commits via `git checkout -- file`,
# restores HEAD on exit (success or failure).

set -u
set -o pipefail

LOG=data/.v203_batch.log
STRAT=omega/nodes/victoria/strategy.py
HEAD_SHA=$(git rev-parse HEAD)
V199_SHA=cbbfb07
V201_SHA=1f53e77

cleanup() {
  echo "[$(date -Iseconds)] restoring $STRAT to HEAD ($HEAD_SHA)" >>"$LOG"
  git checkout "$HEAD_SHA" -- "$STRAT" 2>>"$LOG" || true
}
trap cleanup EXIT INT TERM

mkdir -p data
: >"$LOG"

run_one() {
  local tag=$1 snap=$2 seed=$3
  echo "[$(date -Iseconds)] START $tag seed=$seed snapshot=$snap" >>"$LOG"
  python3 scripts/run_training.py \
    --version "$tag" \
    --cycles 200 \
    --sleep 10 \
    --backtest-snapshot "$snap" \
    --seed "$seed" \
    >>"$LOG" 2>&1
  local rc=$?
  echo "[$(date -Iseconds)] END   $tag seed=$seed rc=$rc" >>"$LOG"
}

# --- V199 code state (cbbfb07): recent + crisis ---
echo "[$(date -Iseconds)] pinning strategy.py at $V199_SHA" >>"$LOG"
git checkout "$V199_SHA" -- "$STRAT" 2>>"$LOG"

for seed in 1 2 3 42; do
  run_one "v203_v199_recent_s${seed}" "data/snapshots/snap_20260414.json" "$seed"
done
for seed in 1 2 3 42; do
  run_one "v203_v199_crisis_s${seed}" "data/snapshots/snap_crisis_2022h1.json" "$seed"
done

# --- V201 code state (1f53e77): trend ---
echo "[$(date -Iseconds)] pinning strategy.py at $V201_SHA" >>"$LOG"
git checkout "$V201_SHA" -- "$STRAT" 2>>"$LOG"

for seed in 1 2 3 42; do
  run_one "v203_v201_trend_s${seed}" "data/snapshots/snap_trending_2023q4.json" "$seed"
done

echo "[$(date -Iseconds)] BATCH COMPLETE" >>"$LOG"
# cleanup() restores HEAD on EXIT.
