#!/bin/bash
# V246 — exit-adaptivity walk-forward grid (trail_keep=0.25, hold_win=8).
#
# 32 windows x ONE config (`exit_adapt`) = 32 cells. The OFF arm is NOT
# re-run — the V240 confirm cells (v240wf_*_universe_selective_*, certified
# deterministic, standing baseline) are the baseline, joined by
# scripts/v246_wf_aggregate.py. The 4-window OFF reproducibility spot-check
# (scripts/v241_baseline_spotcheck.sh, re-run 2026-07-13) certifies those
# cells still reproduce from current state.
#
#   exit_adapt — V240 selective standing config + exit_adaptivity_enabled
#     (trail_keep_frac=0.25, max_hold_win=8; winning v246_exit_scorer_v2 cell).
#
# Sentinels run N=2 (byte-identical no-op re-run per regime).
#
# Falsifier (training_log/V246.md): FAILS if ANY of
#   recent mean-D < +$100 AND recent p25-D < +$400; pooled p25-D < $0;
#   trend mean-D < -$300; crisis mean-D < -$300; exit-rule fire rate <3% (inert).
# ADOPT only if no clause fires AND pooled mean-D > $0.
#
# EXECUTION: SEQUENTIAL. RESUMABLE (summary.json verdict==PASS skips).
# Usage:
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   nohup bash scripts/v246_gdelt_grid.sh > $OMEGA_AUDIT_OUTPUT_DIR/v246/grid.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

SLEEP="${SLEEP:-0}"; FLOOR="${FLOOR:-200}"
MANIFEST="${MANIFEST:-data/walk_forward_manifest.json}"
SENTINELS="${SENTINELS:-snap_wf_20230912 snap_wf_20240310 snap_wf_20250305}"

AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"; mkdir -p "$AUDIT_DIR"
if [ "$AUDIT_DIR" != "data" ]; then
  export TMPDIR="${TMPDIR:-$AUDIT_DIR/tmp}"; mkdir -p "$TMPDIR"
fi

OUT="$AUDIT_DIR/v246"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

EXIT_ADAPT='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true, "exit_adaptivity_enabled": true, "exit_trail_keep_frac": 0.25, "exit_max_hold_win": 8}'

CONFIGS="${CONFIGS:-exit_adapt}"

feats_for() { case "$1" in exit_adapt) echo "$EXIT_ADAPT" ;; *) echo "" ;; esac; }
n_for()     { case " $SENTINELS " in *" $1 "*) echo 2 ;; *) echo 1 ;; esac; }

log() { echo "$@" | tee -a "$SUM"; }

CELL_SRC="$(python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for w in m["windows"]:
    cycles = max(1, min(200, w["min_bars"] - 31))
    print(f"{w['id']}|{w['path']}|{w['regime']}|{cycles}")
PY
)"

CELLS=()
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

cell_summary() { echo "$AUDIT_DIR/v246wf_${1}_${2}_${3}_determinism/summary.json"; }
cell_done() {
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() {
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v246_wf","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v246_wf_grid.sh to continue"},
          open(state,"w"), indent=2)
PY
}
update_session_state() {
  [ -f "$SESSION_STATE" ] || return 0
  python3 - "$SESSION_STATE" "$1" "$2" "$3" "$STATE" <<'PY'
import json, sys
p, phase, done, total, manifest = sys.argv[1:6]
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["v246_walkforward"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                         "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  cell_done "$wid" "$cfg" "$regime" && DONE0=$((DONE0+1))
done

log "=== V246 exit-adapt grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2: $SENTINELS), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  vprefix="v246wf_${wid}_${cfg}"

  if [ ! -f "$path" ]; then
    log "--- SKIP $vprefix — snapshot missing: $path ---"; continue
  fi
  if cell_done "$wid" "$cfg" "$regime"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"; continue
  fi

  # Committed run-state restore (V240 protocol; prompt-hash identity with the
  # cache-fill pass depends on it).
  git checkout -q data/macro_cache.db data/signal_ic_history.json data/training_version.txt data/.cache_manifest.json 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true

  feats="$(feats_for "$cfg")"
  [ -z "$feats" ] && { log "--- SKIP $vprefix — unknown config: $cfg ---"; continue; }
  n="$(n_for "$wid")"
  log "--- CELL $vprefix regime=$regime N=$n cycles=$cycles start $(date -u +%FT%TZ) ---"
  CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=off EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$regime" "$n" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "$AUDIT_DIR/${vprefix}_${regime}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$wid" "$cfg" "$regime" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V246 grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v246_wf_aggregate.py --root "$AUDIT_DIR" --manifest "$MANIFEST" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V246_WALKFORWARD_RESULTS.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V246 aggregation rc=$AGG_RC (0=ok, 5=determinism FAIL blocks verdict) ==="
