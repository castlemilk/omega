#!/usr/bin/env bash
# Wait for all Phase A benchmark runs to complete, then compute scorecards + leaderboard.
# Usage: bash scripts/wait_and_score.sh
set -euo pipefail

VERSIONS=(
  bt_v93_recent bt_v93_trend bt_v93_crisis
  bt_v112_recent bt_v112_trend bt_v112_crisis
  bt_v115_recent bt_v115_trend bt_v115_crisis
)

SNAPSHOTS=(
  "bt_v93_recent:snap_20260414.json"
  "bt_v93_trend:snap_trending_2023q4.json"
  "bt_v93_crisis:snap_crisis_2022h1.json"
  "bt_v112_recent:snap_20260414.json"
  "bt_v112_trend:snap_trending_2023q4.json"
  "bt_v112_crisis:snap_crisis_2022h1.json"
  "bt_v115_recent:snap_20260414.json"
  "bt_v115_trend:snap_trending_2023q4.json"
  "bt_v115_crisis:snap_crisis_2022h1.json"
)

echo "Waiting for all 9 backtest runs to complete..."

while true; do
  all_done=true
  for v in "${VERSIONS[@]}"; do
    results_file="data/${v}_results.json"
    if [ ! -f "$results_file" ]; then
      all_done=false
      echo "  still running: $v"
      break
    fi
  done
  if $all_done; then
    break
  fi
  sleep 10
done

echo ""
echo "All runs complete. Computing scorecards..."
echo ""

for entry in "${SNAPSHOTS[@]}"; do
  version="${entry%%:*}"
  snap="${entry##*:}"
  snap_id="${snap%.json}"
  echo "  Scoring $version against $snap_id..."
  python3 scripts/compute_scorecard.py \
    --version "$version" \
    --snapshot "$snap_id" \
    --snapshot-path "data/snapshots/$snap" \
    --seed 42 \
    --cycles 150
done

echo ""
echo "Computing leaderboard..."
python3 scripts/run_leaderboard.py \
  --prefix bt_ \
  --out data/benchmarks/leaderboard.json

echo ""
echo "Done. Leaderboard saved to data/benchmarks/leaderboard.json"
