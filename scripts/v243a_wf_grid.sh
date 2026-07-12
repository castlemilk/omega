#!/bin/bash
# V243 Candidate A — walk-forward universe-blacklist-extension confirm grid.
#
# Both arms are run FRESH on this branch so the A/B is same-code, flag-only:
#   universe_selective     — baseline (V240 standing baseline: crisis_skew ON +
#                            regime-gate + X=0.12; IC/brake/predemean/throttle
#                            OFF; universe_selective_enabled => blacklist
#                            {BTC,DOT,LINK}, 10-name universe).
#   universe_selective_ext — baseline + universe_blacklist_extended => the
#                            blacklist additionally drops {ADA,NEAR,ARB}
#                            (7-name universe).
#
# 32 windows x 2 arms = 64 cells. We run BOTH arms fresh (rather than reusing the
# V240 selective cells as baseline) so there is NO cross-version reuse assumption:
# baseline and treatment differ ONLY by universe_blacklist_extended, on identical
# code at this branch head. The verdict is a per-regime distribution of
# Δ(ext − selective), same acceptance shape as V240.
#
# Acceptance (V243_A_VERDICT.md, three-tier):
#   ADOPT           — recent mean-Δ ≥ +$300 AND pooled mean-Δ ≥ +$400 AND no
#                     regime mean-Δ worse than −$100.
#   KEEP FLAG-GATED — recent mean-Δ in [+$100,+$300) AND positive in every regime.
#   REVERT          — any regime mean-Δ worse than −$300.
#
# EXECUTION: SEQUENTIAL (MAXP=1). RESUMABLE (summary.json verdict==PASS skips).
# Usage:
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   export TMPDIR=$OMEGA_AUDIT_OUTPUT_DIR/tmp
#   nohup bash scripts/v243a_wf_grid.sh > $OMEGA_AUDIT_OUTPUT_DIR/v243a_wf_grid.log 2>&1 &
# Smoke (one window, both arms):
#   WINDOWS="snap_wf_20250305" bash scripts/v243a_wf_grid.sh
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

OUT="$AUDIT_DIR/v243a_wf"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

SELECTIVE='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'
SELECTIVE_EXT='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true, "universe_blacklist_extended": true}'

CONFIGS="${CONFIGS:-universe_selective universe_selective_ext}"

feats_for() {
  case "$1" in
    universe_selective)     echo "$SELECTIVE" ;;
    universe_selective_ext) echo "$SELECTIVE_EXT" ;;
    *) echo "" ;;
  esac
}
n_for() { case " $SENTINELS " in *" $1 "*) echo 2 ;; *) echo 1 ;; esac; }

log() { echo "$@" | tee -a "$SUM"; }

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

cell_summary() { echo "$AUDIT_DIR/v243awf_${1}_${2}_${3}_determinism/summary.json"; }  # wid cfg gate
cell_done() {
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v243a_wf","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v243a_wf_grid.sh to continue"},
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
d["v243a_walkforward"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                          "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  cell_done "$wid" "$cfg" "$regime" && DONE0=$((DONE0+1))
done

log "=== V243.A universe-blacklist-extension grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2: $SENTINELS), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  vprefix="v243awf_${wid}_${cfg}"

  if [ ! -f "$path" ]; then
    log "--- SKIP $vprefix — snapshot missing: $path ---"
    continue
  fi
  if cell_done "$wid" "$cfg" "$regime"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  # Restore committed macro_cache.db bytes before each cell (WAL sidecar drift
  # fix, carried from V238/V239/V240 — see 10ccb64).
  git checkout -q data/macro_cache.db 2>/dev/null || true
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

log "=== V243.A grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v243a_wf_aggregate.py --root "$AUDIT_DIR" --manifest "$MANIFEST" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V243_A_CONFIRM_RESULTS.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V243.A aggregation rc=$AGG_RC (0=ok, 5=determinism FAIL blocks verdict) ==="
