#!/bin/bash
# V235 — walk-forward distributional grid (manifest-driven; clone of the
# v231→v234 dist-grid pattern generalized over data/walk_forward_manifest.json).
#
# Per window (26 windows, regime-labeled by scripts/walk_forward_freeze.py):
#   main    — standing main: V227 skew ON + regime-gated + X=0.12; IC OFF; brake OFF;
#             predemean OFF (post_demean site); throttle OFF.
#   trendic — the V229 banked stack: main flags + seed-IC overlay
#             (ic_seed_weighting + regime_conditional_ic_weighting) + per-ticker
#             IC drawdown-gate (0.12) + OMEGA_R3_ICS=1.
#
# N=1 per cell (the determinism arc proved the eval is byte-identical from
# committed state; V231 harness re-proved it distributionally), EXCEPT the three
# SENTINEL windows (one per regime, full coverage) which run N=2 at the SAME
# sleep=0 condition to certify determinism holds across the new window set.
# sleep=0 (wall-clock channels fenced V215/V216; V229 grid confirmed honest).
#
# Every cell still runs the full preflight stack: check_no_wallclock,
# check_frozen_http_fence, assert_cell_identity (skew/gate/IC/brake/predemean/
# throttle claims) — via check_determinism.sh.
#
# EXECUTION: SEQUENTIAL (MAXP=1) — DATA_DIR=ROOT/data is a hardcoded global.
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED.
#
# Usage (gamma-redirected, overnight):
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   nohup bash scripts/walk_forward_grid.sh > /tmp/v235_wf_grid.log 2>&1 &
# Smoke (one window, both configs):
#   WINDOWS="snap_wf_20230912" bash scripts/walk_forward_grid.sh
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

SLEEP="${SLEEP:-0}"; FLOOR="${FLOOR:-200}"
MANIFEST="${MANIFEST:-data/walk_forward_manifest.json}"
SENTINELS="${SENTINELS:-snap_wf_20230912 snap_wf_20240310 snap_wf_20250305}"

AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"; mkdir -p "$AUDIT_DIR"
if [ "$AUDIT_DIR" != "data" ]; then
  export TMPDIR="${TMPDIR:-$AUDIT_DIR/tmp}"
  mkdir -p "$TMPDIR"
fi

OUT="$AUDIT_DIR/v235_wf"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

MAIN='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false}'
TRENDIC='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "ic_seed_weighting": true, "per_regime_ic_weighting": true, "regime_conditional_ic_weighting": true, "ic_drawdown_gate_enabled": true, "ic_drawdown_threshold": 0.12}'

CONFIGS="${CONFIGS:-main trendic}"

feats_for()     { case "$1" in main) echo "$MAIN" ;; trendic) echo "$TRENDIC" ;; *) echo "" ;; esac; }
expect_ic_for() { case "$1" in trendic) echo "on" ;; *) echo "off" ;; esac; }
r3_for()        { case "$1" in trendic) echo "1" ;; *) echo "0" ;; esac; }
n_for()         { case " $SENTINELS " in *" $1 "*) echo 2 ;; *) echo 1 ;; esac; }

log() { echo "$@" | tee -a "$SUM"; }

# Cells from the manifest: "wid|path|regime|cycles". cycles = min_bars - 31 —
# ReplayIngestionNode yields series_len-30 honest steps then WRAPS (replays the
# series across a fictitious price seam — the V235 wrap forensic). Never exceed it.
CELL_SRC="$(python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for w in m["windows"]:
    cycles = max(1, min(200, w["min_bars"] - 31))
    print(f"{w['id']}|{w['path']}|{w['regime']}|{cycles}")
PY
)"

CELLS=()   # "wid|path|regime|cycles|cfg"
while IFS= read -r line; do
  [ -z "$line" ] && continue
  wid="${line%%|*}"
  if [ -n "${WINDOWS:-}" ]; then
    case " $WINDOWS " in *" $wid "*) : ;; *) continue ;; esac
  fi
  for cfg in $CONFIGS; do
    CELLS+=("$line|$cfg")
  done
done <<< "$CELL_SRC"
TOTAL=${#CELLS[@]}

cell_summary() { echo "$AUDIT_DIR/v235wf_${1}_${2}_${3}_determinism/summary.json"; }  # wid cfg gate
cell_done() {
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v235_wf","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/walk_forward_grid.sh to continue"},
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
d["v235_walkforward"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                         "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  cell_done "$wid" "$cfg" "$regime" && DONE0=$((DONE0+1))
done

log "=== V235 walk-forward grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2: $SENTINELS), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  vprefix="v235wf_${wid}_${cfg}"

  if [ ! -f "$path" ]; then
    log "--- SKIP $vprefix — snapshot missing: $path ---"
    continue
  fi
  if cell_done "$wid" "$cfg" "$regime"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  feats="$(feats_for "$cfg")"
  [ -z "$feats" ] && { log "--- SKIP $vprefix — unknown config: $cfg ---"; continue; }
  eic="$(expect_ic_for "$cfg")"
  n="$(n_for "$wid")"
  log "--- CELL $vprefix regime=$regime N=$n cycles=$cycles start $(date -u +%FT%TZ) ---"
  if [ "$(r3_for "$cfg")" = "1" ]; then
    CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" OMEGA_R3_ICS=1 \
    EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC="$eic" EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
      bash scripts/check_determinism.sh "$regime" "$n" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
      > "$OUT/${vprefix}.log" 2>&1
  else
    CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
    EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC="$eic" EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
      bash scripts/check_determinism.sh "$regime" "$n" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
      > "$OUT/${vprefix}.log" 2>&1
  fi
  rc=$?
  grep -h "DETERMINISM:" "$AUDIT_DIR/${vprefix}_${regime}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$wid" "$cfg" "$regime" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V235 walk-forward grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/walk_forward_aggregate.py --root "$AUDIT_DIR" --manifest "$MANIFEST" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V235_WALKFORWARD_RESULTS.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V235 aggregation rc=$AGG_RC (0=ok, 5=determinism FAIL blocks verdict) ==="
