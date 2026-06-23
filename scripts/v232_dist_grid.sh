#!/bin/bash
# V232 — RV-term-structure inversion brake, measured on the V231 crisis distribution.
#
# Clone of v231_dist_grid.sh (the standing distributional instrument is left intact).
# ONLY the arms, the output dir, the version prefix, and the aggregator differ.
#
# ARMS (both carry the V227 crisis-skew, gated, X=0.12 — so the brake's Δ is measured
# ON TOP OF the existing skew, NOT vs equal-weight):
#   ON  = V227 skew (gated) + rv_term_brake_enabled:true  (+ brake regime/dd gate, X=1.5)
#   OFF = V227 skew (gated) + rv_term_brake_enabled:false  (= standing main — the control)
#
# Because BOTH arms run skew+gate, the cell-identity skew/gate assertions now run on
# BOTH arms (a stronger control than V231, where OFF was equal-weight). The sole
# difference between arms is the brake flag; assert_cell_identity --expect-brake verifies it.
#
# EXECUTION: SEQUENTIAL (MAXP=1) — DATA_DIR=ROOT/data is a hardcoded global; concurrent
# in-checkout cells corrupt shared data/*.db + signal_ic_history.json. Crisis-only by
# default (the V230/V231 binding falsifier). ETA ~5-6h (12 cells, N=2).
#
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED.
# Manifest: data/v232_dist/grid_state.json.
#
# Usage:  nohup bash scripts/v232_dist_grid.sh > /tmp/v232_grid.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

N="${N:-2}"; SLEEP="${SLEEP:-10}"; FLOOR="${FLOOR:-200}"
OUT=data/v232_dist; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

# Both arms hold V227 skew ON + gated + X=0.12. The sole difference is the brake flag.
ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": true, "rv_term_brake_regime_gate_enabled": true, "rv_term_brake_drawdown_threshold": 0.12, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false}'

# Per-gate window snapshot lists. Crisis is the binding distribution for V232.
windows_for() {
  case "$1" in
    crisis) echo "data/snapshots/snap_crisis_2020q1.json data/snapshots/snap_crisis_2022h1.json data/snapshots/snap_crisis_2024aug.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json data/snapshots/snap_trending_2024q1.json" ;;
    recent) echo "data/snapshots/snap_20260414.json" ;;
  esac
}

log() { echo "$@" | tee -a "$SUM"; }

# GATES defaults to crisis-only (the V232 binding falsifier; ~5-6h). Do NOT add
# trend/recent here — that's V233 (the SHIP branch). Crisis is always FIRST.
GATES="${GATES:-crisis}"
CELLS=()        # "gate|snap|arm"
for gate in $GATES; do
  for snap in $(windows_for "$gate"); do
    CELLS+=("$gate|$snap|on")
    CELLS+=("$gate|$snap|off")
  done
done
TOTAL=${#CELLS[@]}

cell_summary() { # gate wlabel arm -> path
  echo "data/v232_${1}_${2}_${3}_${1}_determinism/summary.json"
}
cell_done() {   # gate wlabel arm -> 0 if PASS summary exists
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$N" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, n, slp = sys.argv[1:7]
json.dump({"version":"v232","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"n_replicates":int(n),"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v232_dist_grid.sh to continue"},
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
d["v232_dist"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
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

log "=== V232 dist grid start $(date -u +%FT%TZ) — $TOTAL cells (N=$N sleep=$SLEEP), $DONE0 already done (resume) ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap arm <<< "$c"
  wlabel="$(basename "$snap" .json)"
  vprefix="v232_${gate}_${wlabel}_${arm}"

  if [ ! -f "$snap" ]; then
    log "--- SKIP $vprefix — snapshot missing: $snap (build it, then re-run to resume) ---"
    continue
  fi
  if cell_done "$gate" "$wlabel" "$arm"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  # V232: BOTH arms carry skew ON + gate ON (V231's OFF arm was equal-weight). The
  # arm differs ONLY in the brake. EXPECT_BRAKE threads the new identity claim.
  if [ "$arm" = "on" ]; then feats="$ON"; ebrake=on; else feats="$OFF"; ebrake=off; fi
  log "--- CELL $vprefix gate=$gate window=$wlabel arm=$arm start $(date -u +%FT%TZ) ---"
  SNAP_OVERRIDE="$snap" WINDOW_LABEL="$wlabel" \
  EXPECT_SKEW=on EXPECT_IC=off EXPECT_GATE=on EXPECT_BRAKE="$ebrake" \
    bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$gate" "$wlabel" "$arm" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V232 dist grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v232_dist_aggregate.py --root data --prefix v232 \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V232_dist_results.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V232 aggregation rc=$AGG_RC (0=det PASS, 5=det FAIL blocks verdict) ==="
