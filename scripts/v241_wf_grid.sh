#!/bin/bash
# V241 — reasoning-layer frozen-replay walk-forward grid (phase 2).
#
# 32 windows x ONE config (`reasoning_on`) = 32 cells. The OFF arm is NOT
# re-run — the V240 confirm cells (v240wf_*_universe_selective_*, certified
# deterministic, standing baseline) are the baseline, joined by
# scripts/v241_wf_aggregate.py. The 4-window OFF reproducibility spot-check
# (scripts/v241_baseline_spotcheck.sh) certifies those cells still reproduce
# from current state.
#
#   reasoning_on — V240 selective standing config + reasoning_layer_enabled.
#     Runs under --frozen-cache (OMEGA_FROZEN_CACHE=1): every reasoning call
#     MUST be a frozen_llm_cache hit; a miss raises LLMCacheMiss and kills the
#     cell (never a stub). Cache is pre-filled by scripts/v241_cache_fill.sh.
#
# Sentinels run N=2 — the byte-identical no-op re-run per regime demanded by
# the V241 plan (LLM-in-loop determinism re-certified from cache).
#
# Acceptance (training_log/V241.md): ADOPT iff recent mean-D > +$400 AND
# recent p25-D > +$500 AND trend mean-D > -$300 AND crisis mean-D > -$300.
#
# EXECUTION: SEQUENTIAL. RESUMABLE (summary.json verdict==PASS skips).
# Usage:
#   export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
#   nohup bash scripts/v241_wf_grid.sh > $OMEGA_AUDIT_OUTPUT_DIR/v241/grid.log 2>&1 &
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

OUT="$AUDIT_DIR/v241"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"
SESSION_STATE=data/SESSION_STATE.json

REASONING_ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true, "reasoning_layer_enabled": true}'

CONFIGS="${CONFIGS:-reasoning_on}"

feats_for() { case "$1" in reasoning_on) echo "$REASONING_ON" ;; *) echo "" ;; esac; }
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

cell_summary() { echo "$AUDIT_DIR/v241wf_${1}_${2}_${3}_determinism/summary.json"; }
cell_done() {
  local p; p="$(cell_summary "$1" "$2" "$3")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() {
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v241_wf","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v241_wf_grid.sh to continue"},
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
d["v241_walkforward"] = {"phase": phase, "cells_done": int(done), "cells_total": int(total),
                         "max_parallel": 1, "manifest": manifest}
json.dump(d, open(p, "w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  cell_done "$wid" "$cfg" "$regime" && DONE0=$((DONE0+1))
done

log "=== V241 reasoning-layer grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2: $SENTINELS), $DONE0 already done (resume); TMPDIR=${TMPDIR:-<host>} AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"
update_session_state "running" "$DONE0" "$TOTAL"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles cfg <<< "$c"
  vprefix="v241wf_${wid}_${cfg}"

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
  OMEGA_REASONING_TRACE="$OUT/${wid}_grid_reasoning_trace.jsonl" \
  CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=off EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$regime" "$n" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "$AUDIT_DIR/${vprefix}_${regime}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  if grep -q "LLMCacheMiss" "$OUT/${vprefix}.log" 2>/dev/null; then
    log "!!! $vprefix hit LLMCacheMiss — cache-fill coverage incomplete; re-run scripts/v241_cache_fill.sh for $wid then resume"
  fi
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$wid" "$cfg" "$regime" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
  update_session_state "running" "$done" "$TOTAL"
done

log "=== V241 grid complete $(date -u +%FT%TZ) — aggregating ==="
write_manifest "$done" "$TOTAL" "aggregating"
python3 scripts/v241_wf_aggregate.py --root "$AUDIT_DIR" --manifest "$MANIFEST" \
        --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V241_WALKFORWARD_RESULTS.md" | tee -a "$SUM"
AGG_RC=$?
write_manifest "$done" "$TOTAL" "complete"
update_session_state "complete" "$done" "$TOTAL"
log "=== V241 aggregation rc=$AGG_RC (0=ok, 5=determinism FAIL blocks verdict) ==="
