#!/bin/bash
# V234 — crisis SIZING-LAYER intervention, measured on the V231/V232/V233 crisis
# distribution. Clone of v233_dist_grid.sh. After 7 composite-additive interventions
# (V227..V233) left snap_crisis_2024aug byte-identical at Δ==$0.00, V234 acts DOWNSTREAM
# of the composite — on position SIZE when the EXISTING V227 drawdown-AND-gate fires.
# Goal: change the 2024aug ledger (Δtrades≠0 OR Δsize≠0), which no composite change did.
#
# CONFIGS (crisis-only by default — the binding V230..V233 falsifier window):
#   baseline        — throttle OFF (== V227 skew standing-main; the in-grid OFF identity
#                     / determinism anchor — re-RUN here, NOT reused, so the OFF arm proves
#                     the new code path is default-inert byte-for-byte)
#   throttle_s0.5   — crisis_size_throttle_enabled, S=0.5 (halve gated size)
#   throttle_s0.25  — crisis_size_throttle_enabled, S=0.25 (quarter gated size)
#   (S=0.0 deliberately SKIPPED to save cost; the two factors bracket directionality.)
#
# Each config carries V227 skew ON + gated + X=0.12, brake OFF, IC OFF, predemean OFF
# (post_demean standing-main site). The throttle flags layer on top; default-inert ⇒ the
# baseline cell == standing-main byte-for-byte. assert_cell_identity --expect-throttle
# verifies the throttle flag + factor per cell.
#
# EXECUTION: SEQUENTIAL (MAXP=1) — DATA_DIR=ROOT/data is a hardcoded global; concurrent
# in-checkout cells corrupt shared data/*.db + signal_ic_history.json.
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED.
#
# TMPDIR FIX (closes the V233 cell-11 ENOSPC class): check_determinism.sh's bash heredocs
# (`python3 - <<'PY'`) materialise their temp files under $TMPDIR. On macOS bash 3.2 the
# host $TMPDIR is on the host disk, NOT the gamma redirect — V233 cell-11 ran the host out
# of space there. Pin $TMPDIR onto the gamma mount so every heredoc temp file lands there
# too. No code change to check_determinism.sh — it inherits the exported $TMPDIR.
#
# Usage:
#   # Phase-1 smoke (1 throttle cell at N=2, certify the new size-throttle path is hermetic):
#   N=2 CONFIGS="throttle_s0.5" GATES=crisis WINDOWS="snap_crisis_2024aug" \
#       nohup bash scripts/v234_dist_grid.sh > /tmp/v234_smoke.log 2>&1 &
#   # Full crisis block at N=2 (smoke cell skipped on resume):
#   nohup bash scripts/v234_dist_grid.sh > /tmp/v234_grid.log 2>&1 &
#   # Conditional trend/recent leak spot-check for a winning config ONLY (after a crisis win):
#   CONFIGS="<winner>" GATES="trend recent" \
#       nohup bash scripts/v234_dist_grid.sh > /tmp/v234_tr.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

N="${N:-2}"; SLEEP="${SLEEP:-10}"; FLOOR="${FLOOR:-200}"
# OMEGA_AUDIT_OUTPUT_DIR: redirect grid + determinism-cell outputs off the host disk onto
# an external mount (gamma-systems-2) to avoid the ENOSPC class. Defaults to data/.
# check_determinism.sh + run_training.py honor the SAME env var.
AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"; mkdir -p "$AUDIT_DIR"

# --- TMPDIR FIX (V234): heredoc temp files onto the audit mount, NOT the host disk.
# Default the tmp dir under the audit mount when OMEGA_AUDIT_OUTPUT_DIR redirects off-host;
# fall back to the host default only when running fully local (AUDIT_DIR == data).
if [ "$AUDIT_DIR" != "data" ]; then
  export TMPDIR="${TMPDIR:-$AUDIT_DIR/tmp}"
  mkdir -p "$TMPDIR"
fi

OUT="$AUDIT_DIR/v234_dist"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json
BASELINE="${BASELINE:-$AUDIT_DIR/v232_dist/distribution.json}"

# Shared base for every config: V227 skew ON + gated + X=0.12, brake OFF, IC OFF,
# predemean OFF (post_demean standing-main site). The throttle flags layer on top.
BASE='"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false'

# config token -> feature JSON. The throttle flags layer on top of BASE.
feats_for() {
  case "$1" in
    baseline)
      echo "{$BASE, \"crisis_size_throttle_enabled\": false}" ;;
    throttle_s0.5)
      echo "{$BASE, \"crisis_size_throttle_enabled\": true, \"crisis_size_throttle\": 0.5}" ;;
    throttle_s0.25)
      echo "{$BASE, \"crisis_size_throttle_enabled\": true, \"crisis_size_throttle\": 0.25}" ;;
    *) echo "" ;;
  esac
}
# config token -> the --expect-throttle claim (on|off) for cell-identity.
expect_throttle_for() { case "$1" in baseline) echo "off" ;; throttle_*) echo "on" ;; *) echo "off" ;; esac; }
# config token -> the --expect-throttle-s factor claim for cell-identity.
expect_throttle_s_for() {
  case "$1" in
    throttle_s0.5)  echo "0.5"  ;;
    throttle_s0.25) echo "0.25" ;;
    *) echo "" ;;
  esac
}

CONFIGS="${CONFIGS:-baseline throttle_s0.5 throttle_s0.25}"

# Per-gate window snapshot lists. Crisis is the binding distribution for V234.
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
  echo "$AUDIT_DIR/v234_${1}_${2}_${3}_${1}_determinism/summary.json"
}
cell_done() {   # gate wlabel config -> 0 if PASS summary exists
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$N" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, n, slp = sys.argv[1:7]
json.dump({"version":"v234","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"n_replicates":int(n),"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v234_dist_grid.sh to continue"},
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
d["v234_dist"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
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

log "=== V234 sizing grid start $(date -u +%FT%TZ) — $TOTAL cells (N=$N sleep=$SLEEP), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r gate snap cfg <<< "$c"
  wlabel="$(basename "$snap" .json)"
  vprefix="v234_${gate}_${wlabel}_${cfg}"

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
  ethrottle="$(expect_throttle_for "$cfg")"
  ethrottle_s="$(expect_throttle_s_for "$cfg")"
  log "--- CELL $vprefix gate=$gate window=$wlabel config=$cfg start $(date -u +%FT%TZ) ---"
  SNAP_OVERRIDE="$snap" WINDOW_LABEL="$wlabel" \
  EXPECT_SKEW=on EXPECT_IC=off EXPECT_GATE=on EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean \
  EXPECT_THROTTLE="$ethrottle" EXPECT_THROTTLE_S="$ethrottle_s" \
    bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "$AUDIT_DIR/${vprefix}_${gate}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$gate" "$wlabel" "$cfg" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V234 sizing grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v234_dist_aggregate.py --root "$AUDIT_DIR" --prefix v234 \
        --baseline "$BASELINE" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V234_dist_results.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V234 aggregation rc=$AGG_RC (0=det PASS, 5=det FAIL blocks verdict) ==="
