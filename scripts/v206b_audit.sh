#!/usr/bin/env bash
# V206b state-leak audit launcher.
# Runs 3 gates × 2 no-op pairs sequentially. Snapshots the persistent
# sqlite DBs and all per-run artifacts into data/v206b_audit/<gate>_<run>/.
#
# Total runtime: ~4 hours (recent ~5min/run, crisis ~40min/run, trend
# likely ~30min/run; recent is much shorter due to 60-step snapshot).

set -uo pipefail

cd /Users/benebsworth/projects/omega

AUDIT_DIR="data/v206b_audit"
LOG="$AUDIT_DIR/run.log"
mkdir -p "$AUDIT_DIR"

# Snapshot fingerprints of pre-existing persistent state so we can see
# whether the DBs already differed before V206b began.
{
  echo "[$(date -Iseconds)] V206b audit starting"
  echo "--- pre-audit fingerprints ---"
  shasum -a 256 data/omega_victoria_state.db data/omega_victoria_memory.db data/victoria_state.db 2>/dev/null
  echo "------------------------------"
} >> "$LOG"

snap_for() {
  case "$1" in
    recent) echo "data/snapshots/snap_20260414.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json" ;;
    crisis) echo "data/snapshots/snap_crisis_2022h1.json" ;;
  esac
}

snapshot_artifacts() {
  local gate=$1
  local run=$2
  local version=$3
  local dest="$AUDIT_DIR/${gate}_${run}"
  mkdir -p "$dest"

  # Per-run outputs from run_training.py
  cp -f "data/${version}_results.json"        "$dest/" 2>/dev/null
  cp -f "data/${version}_trades.csv"          "$dest/" 2>/dev/null
  cp -f "data/${version}_progress.json"       "$dest/" 2>/dev/null
  cp -f "data/${version}_gate_result.json"    "$dest/" 2>/dev/null
  cp -f "/tmp/${version}_metrics.jsonl"       "$dest/" 2>/dev/null
  cp -f "/tmp/${version}_decisions.jsonl"     "$dest/" 2>/dev/null
  cp -f "/tmp/${version}_training.log"        "$dest/" 2>/dev/null

  # Persistent sqlite DBs — the prime suspects for state leak
  cp -f data/omega_victoria_state.db          "$dest/omega_victoria_state.db" 2>/dev/null
  cp -f data/omega_victoria_memory.db         "$dest/omega_victoria_memory.db" 2>/dev/null
  cp -f data/victoria_state.db                "$dest/victoria_state.db" 2>/dev/null

  {
    echo "--- post-run fingerprints: ${gate}_${run} (version=${version}) ---"
    shasum -a 256 "$dest"/*.db "$dest"/*.json "$dest"/*.csv "$dest"/*.jsonl 2>/dev/null
  } >> "$LOG"
}

for gate in recent trend crisis; do
  snap="$(snap_for "$gate")"
  for run in r1 r2; do
    version="v206b_${gate}_${run}"
    {
      echo "[$(date -Iseconds)] START $version snapshot=$snap"
    } >> "$LOG"

    python3 scripts/run_training.py \
      --version "$version" \
      --cycles 200 \
      --sleep 10 \
      --seed 42 \
      --backtest-snapshot "$snap" \
      >>"$AUDIT_DIR/${version}.stdout" 2>>"$AUDIT_DIR/${version}.stderr"

    rc=$?
    {
      echo "[$(date -Iseconds)] END   $version rc=$rc"
    } >> "$LOG"

    snapshot_artifacts "$gate" "$run" "$version"
  done
done

{
  echo "[$(date -Iseconds)] V206b audit complete"
} >> "$LOG"
