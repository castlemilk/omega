#!/bin/bash
# V233 — crisis-term application-SITE experiment, measured on the V231/V232 crisis
# distribution. Clone of v232_dist_grid.sh; the arms become single-arm CONFIGS and the
# baseline (post_demean_w0.2 = V227 skew standing-main) is REUSED from data/v232_dist
# (NOT re-run). Each config tests the EXISTING V227 skew as a probe under a different
# application site / gated weight — isolating the SITE variable (no new signal).
#
# CONFIGS (crisis-only by default — the binding V230/V231/V232 falsifier window):
#   pre_demean_w0.2             — term added pre-demean (itself demeaned), W=0.2
#   pre_demean_w0.4             — pre-demean, W=0.4 (weight escalation)
#   pre_demean_w0.6             — pre-demean, W=0.6
#   pre_demean_common_mode_w0.2 — pre-demean + basket-mean add-back, W=0.2
# Baseline post_demean_w0.2 (= V227 default) is data/v232_dist/distribution.json pnl_off.
#
# Each config carries V227 skew ON + gated + X=0.12, brake OFF, IC OFF; the SITE flags
# layer on top. The flags default-inert ⇒ a post_demean cell == standing-main byte-for-
# byte. assert_cell_identity --expect-predemean verifies the site/weight per cell.
#
# EXECUTION: SEQUENTIAL (MAXP=1) — DATA_DIR=ROOT/data is a hardcoded global; concurrent
# in-checkout cells corrupt shared data/*.db + signal_ic_history.json.
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED.
#
# Usage:
#   # Phase-1 smoke (1 new cell at N=2 to certify the new pre-demean path is hermetic):
#   N=2 CONFIGS="pre_demean_w0.2" GATES=crisis WINDOWS="snap_crisis_2020q1" \
#       nohup bash scripts/v233_dist_grid.sh > /tmp/v233_smoke.log 2>&1 &
#   # Full crisis block at N=1 (smoke cell skipped on resume):
#   N=1 nohup bash scripts/v233_dist_grid.sh > /tmp/v233_grid.log 2>&1 &
#   # Conditional trend/recent for the winning config ONLY (after a crisis winner):
#   N=1 CONFIGS="<winner>" GATES="trend recent" \
#       nohup bash scripts/v233_dist_grid.sh > /tmp/v233_tr.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

N="${N:-1}"; SLEEP="${SLEEP:-10}"; FLOOR="${FLOOR:-200}"
OUT=data/v233_dist; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json
BASELINE="${BASELINE:-data/v232_dist/distribution.json}"

# Shared base for every config: V227 skew ON + gated + X=0.12, brake OFF, IC OFF.
BASE='"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false'

# config token -> feature JSON. The site flags layer on top of BASE.
feats_for() {
  case "$1" in
    pre_demean_w0.2)
      echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean\", \"crisis_term_gated_weight\": 0.2}" ;;
    pre_demean_w0.4)
      echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean\", \"crisis_term_gated_weight\": 0.4}" ;;
    pre_demean_w0.6)
      echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean\", \"crisis_term_gated_weight\": 0.6}" ;;
    pre_demean_common_mode_w0.2)
      echo "{$BASE, \"crisis_term_predemean_enabled\": true, \"crisis_term_predemean_mode\": \"pre_demean_common_mode\", \"crisis_term_gated_weight\": 0.2}" ;;
    *) echo "" ;;
  esac
}
# config token -> the --expect-predemean claim (mode[:weight]) for cell-identity.
expect_for() {
  case "$1" in
    pre_demean_w0.2)             echo "pre_demean:0.2" ;;
    pre_demean_w0.4)             echo "pre_demean:0.4" ;;
    pre_demean_w0.6)             echo "pre_demean:0.6" ;;
    pre_demean_common_mode_w0.2) echo "pre_demean_common_mode:0.2" ;;
    *) echo "post_demean" ;;
  esac
}

CONFIGS="${CONFIGS:-pre_demean_w0.2 pre_demean_w0.4 pre_demean_w0.6 pre_demean_common_mode_w0.2}"

# Per-gate window snapshot lists. Crisis is the binding distribution for V233.
windows_for() {
  case "$1" in
    crisis) echo "data/snapshots/snap_crisis_2020q1.json data/snapshots/snap_crisis_2022h1.json data/snapshots/snap_crisis_2024aug.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json data/snapshots/snap_trending_2024q1.json" ;;
    recent) echo "data/snapshots/snap_20260414.json" ;;
  esac
}

log() { echo "$@" | tee -a "$SUM"; }

GATES="${GATES:-crisis}"
CELLS=()        # "gate|snap|config"
for gate in $GATES; do
  for snap in $(windows_for "$gate"); do
    # Optional WINDOWS filter (basename without .json) for the smoke run.
    if [ -n "${WINDOWS:-}" ]; then
      case " $WINDOWS " in *" $(basename "$snap" .json) "*) : ;; *) continue ;; esac
    fi
    for cfg in $CONFIGS; do
      CELLS+=("$gate|$snap|$cfg")
    done
  done
done
TOTAL=${#CELLS[@]}

cell_summary() { # gate wlabel config -> path
  echo "data/v233_${1}_${2}_${3}_${1}_determinism/summary.json"
}
cell_done() {   # gate wlabel config -> 0 if PASS summary exists
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$N" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, n, slp = sys.argv[1:7]
json.dump({"version":"v233","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"n_replicates":int(n),"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v233_dist_grid.sh to continue"},
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
d["v233_dist"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                  "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap cfg <<< "$c"
  wlabel="$(basename "$snap" .json)"
  cell_done "$gate" "$wlabel" "$cfg" && DONE0=$((DONE0+1))
done

log "=== V233 site grid start $(date -u +%FT%TZ) — $TOTAL cells (N=$N sleep=$SLEEP), $DONE0 already done (resume) ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap cfg <<< "$c"
  wlabel="$(basename "$snap" .json)"
  vprefix="v233_${gate}_${wlabel}_${cfg}"

  if [ ! -f "$snap" ]; then
    log "--- SKIP $vprefix — snapshot missing: $snap (build it, then re-run to resume) ---"
    continue
  fi
  if cell_done "$gate" "$wlabel" "$cfg"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  feats="$(feats_for "$cfg")"
  if [ -z "$feats" ]; then
    log "--- SKIP $vprefix — unknown config token: $cfg ---"
    continue
  fi
  epredemean="$(expect_for "$cfg")"
  log "--- CELL $vprefix gate=$gate window=$wlabel config=$cfg start $(date -u +%FT%TZ) ---"
  SNAP_OVERRIDE="$snap" WINDOW_LABEL="$wlabel" \
  EXPECT_SKEW=on EXPECT_IC=off EXPECT_GATE=on EXPECT_BRAKE=off EXPECT_PREDEMEAN="$epredemean" \
    bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "data/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$gate" "$wlabel" "$cfg" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V233 site grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v233_dist_aggregate.py --root data --prefix v233 \
        --baseline "$BASELINE" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V233_dist_results.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V233 aggregation rc=$AGG_RC (0=det PASS, 5=det FAIL blocks verdict) ==="
