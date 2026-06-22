#!/bin/bash
# V231 — distributional eval grid (instrument-only; run harness, not committed as data).
#
# Atomic cell = check_determinism.sh (gate, window, arm) -> N=2 replicates -> own $0.00
# verdict + cell-identity assertion. The new layers (window, arm, per-gate aggregation)
# live HERE + in v231_dist_aggregate.py; check_determinism.sh is unchanged except a
# cosmetic snapshot/window provenance field in summary.json.
#
# ARMS:
#   ON  = standing main = V227 crisis-skew, gated, X=0.12 (crisis_skew_enabled:true,
#         crisis_skew_regime_gate_enabled:true). Defaults, stated explicitly.
#   OFF = all-OFF equal-weight (crisis_skew_enabled:false) — the within-grid control.
#
# EXECUTION: SEQUENTIAL (MAXP=1). DATA_DIR=ROOT/data is a hardcoded global in
# run_training.py:167, so concurrent in-checkout cells corrupt shared data/*.db +
# signal_ic_history.json. Safe MAXP>1 requires git worktrees (matrix mode) — not used
# here for unattended-overnight robustness. Crisis-ordered-FIRST so the binding crisis
# distribution (the V230 falsifier) completes before any interruption.
#
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED. Re-running
# this script resumes from where it stopped. Manifest: data/v231_dist/grid_state.json.
#
# Usage:  nohup bash scripts/v231_dist_grid.sh > /tmp/v231_grid.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

N="${N:-2}"; SLEEP="${SLEEP:-10}"; FLOOR="${FLOOR:-200}"
OUT=data/v231_dist; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json
MANIFEST_PY=scripts/v231_dist_aggregate.py   # referenced for the final aggregation

ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# Per-gate window snapshot lists. Crisis FIRST (binding). Trend/recent = bonus.
windows_for() {
  case "$1" in
    crisis) echo "data/snapshots/snap_crisis_2020q1.json data/snapshots/snap_crisis_2022h1.json data/snapshots/snap_crisis_2024aug.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json data/snapshots/snap_trending_2024q1.json" ;;
    recent) echo "data/snapshots/snap_20260414.json" ;;
  esac
}

log() { echo "$@" | tee -a "$SUM"; }

# Build the ordered cell list: crisis (binding) -> trend -> recent; ON then OFF per window.
CELLS=()        # "gate|snap|arm"
for gate in crisis trend recent; do
  for snap in $(windows_for "$gate"); do
    CELLS+=("$gate|$snap|on")
    CELLS+=("$gate|$snap|off")
  done
done
TOTAL=${#CELLS[@]}

# Count already-done cells (resumability) for the manifest header.
cell_summary() { # gate wlabel arm -> path
  echo "data/v231_${1}_${2}_${3}_${1}_determinism/summary.json"
}
cell_done() {   # gate wlabel arm -> 0 if PASS summary exists
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$N" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, n, slp = sys.argv[1:7]
json.dump({"version":"v231","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"n_replicates":int(n),"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v231_dist_grid.sh to continue"},
          open(state,"w"), indent=2)
PY
}
update_session_state() { # phase done total
  [ -f "$SESSION_STATE" ] || return 0
  python3 - "$SESSION_STATE" "$1" "$2" "$3" "$STATE" <<'PY'
import json, sys
p, phase, done, total, manifest = sys.argv[1:6]
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["v231_dist"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                  "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap arm <<< "$c"
  wlabel="$(basename "$snap" .json)"
  cell_done "$gate" "$wlabel" "$arm" && DONE0=$((DONE0+1))
done

log "=== V231 dist grid start $(date -u +%FT%TZ) — $TOTAL cells (N=$N sleep=$SLEEP), $DONE0 already done (resume) ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap arm <<< "$c"
  wlabel="$(basename "$snap" .json)"
  vprefix="v231_${gate}_${wlabel}_${arm}"

  if [ ! -f "$snap" ]; then
    log "--- SKIP $vprefix — snapshot missing: $snap (build it, then re-run to resume) ---"
    continue
  fi
  if cell_done "$gate" "$wlabel" "$arm"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  if [ "$arm" = "on" ]; then feats="$ON"; eskew=on; egate=on; else feats="$OFF"; eskew=off; egate=off; fi
  log "--- CELL $vprefix gate=$gate window=$wlabel arm=$arm start $(date -u +%FT%TZ) ---"
  SNAP_OVERRIDE="$snap" WINDOW_LABEL="$wlabel" \
  EXPECT_SKEW="$eskew" EXPECT_IC=off EXPECT_GATE="$egate" \
    bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$gate" "$wlabel" "$arm" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V231 dist grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v231_dist_aggregate.py --root data \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V231_dist_results.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V231 aggregation rc=$AGG_RC (0=det PASS, 5=det FAIL blocks verdict) ==="
