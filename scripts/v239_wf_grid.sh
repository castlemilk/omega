#!/bin/bash
# V239 — walk-forward universe-flip grid: _TRADING_BLACKLIST legacy vs full.
#
# Clone of scripts/v238_wf_grid.sh with two configs per window, both on the
# V238 STANDING baseline (frozen_series OFF — V238 kept series flag-gated, so
# the V239 baseline is the V235/V238 `main` config):
#   universe_legacy — the standing main (V227 skew ON + regime-gated + X=0.12;
#                     IC OFF; brake OFF; predemean OFF; throttle OFF;
#                     frozen_series OFF). blacklist ON ⇒ 4-name universe
#                     (ETH/ADA/NEAR/ARB). MUST be byte-identical to the V238
#                     `main` cells (which are byte-identical to V235).
#   universe_full   — universe_legacy + universe_full_enabled ⇒ _TRADING_BLACKLIST
#                     treated as empty (open to the full 13-name snapshot
#                     universe: + BTC/DOT/MATIC/XRP/SOL/AVAX/LINK/BNB/SUI, per
#                     V235_UNIVERSE_REVIEW.md new-blacklist=∅). Names with
#                     missing bars in a window are skipped automatically.
#
# N=1 per cell except the three SENTINEL windows (one per regime) at N=2 —
# same certification pattern as V235/V238. sleep=0. Acceptance (V239.md):
# ship infra on determinism PASS + legacy identity vs V238 main; adopt the full
# universe as standing baseline only if pooled mean-Δ(full−legacy) > −$300 and
# no regime regresses > $500.
#
# EXECUTION: SEQUENTIAL (MAXP=1) — DATA_DIR=ROOT/data is a hardcoded global.
# RESUMABLE: a cell whose summary.json exists AND verdict==PASS is SKIPPED.
#
# Usage (gamma-redirected, overnight):
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   nohup bash scripts/v239_wf_grid.sh > $OMEGA_AUDIT_OUTPUT_DIR/v239_wf_grid.log 2>&1 &
# Smoke (one window, both configs):
#   WINDOWS="snap_wf_20250305" bash scripts/v239_wf_grid.sh
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

OUT="$AUDIT_DIR/v239_wf"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

LEGACY='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false}'
FULL='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_full_enabled": true}'

CONFIGS="${CONFIGS:-universe_legacy universe_full}"

feats_for() { case "$1" in universe_legacy) echo "$LEGACY" ;; universe_full) echo "$FULL" ;; *) echo "" ;; esac; }
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

cell_summary() { echo "$AUDIT_DIR/v239wf_${1}_${2}_${3}_determinism/summary.json"; }  # wid cfg gate
cell_done() {
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v239_wf","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v239_wf_grid.sh to continue"},
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
d["v239_walkforward"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                         "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  cell_done "$wid" "$cfg" "$regime" && DONE0=$((DONE0+1))
done

log "=== V239 walk-forward grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2: $SENTINELS), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  vprefix="v239wf_${wid}_${cfg}"

  if [ ! -f "$path" ]; then
    log "--- SKIP $vprefix — snapshot missing: $path ---"
    continue
  fi
  if cell_done "$wid" "$cfg" "$regime"; then
    log "--- SKIP $vprefix — already PASS (resume) ---"
    continue
  fi

  # macro_cache.db is a WAL-mode SQLite file: the app's init (CREATE TABLE IF
  # NOT EXISTS + commit) writes the -wal sidecar, and an autocheckpoint can fold
  # it back into the main file → the tracked bytes drift from committed even
  # though frozen mode blocks all data INSERTs. Restore the committed bytes
  # before each cell so the V219 preflight always sees the certified substrate
  # (the 10ccb64 fix, carried forward from V238).
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

log "=== V239 walk-forward grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v239_wf_aggregate.py --root "$AUDIT_DIR" --manifest "$MANIFEST" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V239_WALKFORWARD_RESULTS.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V239 aggregation rc=$AGG_RC (0=ok, 5=determinism FAIL blocks verdict) ==="
