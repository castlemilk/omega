#!/bin/bash
# V241 — reasoning-layer frozen-LLM-cache fill (phase 0 + phase 1).
#
# Runs each walk-forward window ONCE with the reasoning layer ON under the
# EXACT grid conditions (check_determinism.sh N=1: PYTHONHASHSEED=42, seed 42,
# --frozen-cache, sleep=0, selective-universe features) plus:
#
#   OMEGA_LLM_CACHE_FILL=1     — LLM path only: cache miss -> live agy call,
#                                stored to data/frozen_llm_cache/. All other
#                                inputs stay frozen, so fill-time prompts are
#                                byte-identical to grid replay-time prompts.
#   OMEGA_REASONING_TRACE=...  — per-call JSONL for the phase-0 inertness
#                                report (scripts/v241_intervention_report.py).
#
# RESUMABLE: a window with $OUT/<wid>.done is skipped. agy calls already
# cached are hits on re-run, so a mid-window crash resumes cheaply.
#
# Phase 0 (one recent window):
#   WINDOWS="snap_wf_20250305" bash scripts/v241_cache_fill.sh
# Phase 1 (all 32 windows, ~8h wall-clock):
#   nohup bash scripts/v241_cache_fill.sh > $OMEGA_AUDIT_OUTPUT_DIR/v241_cache_fill/fill.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL="${DATABASE_URL:-postgres://omega:omega@localhost:5432/omega?sslmode=disable}"

MANIFEST="${MANIFEST:-data/walk_forward_manifest.json}"
AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"; mkdir -p "$AUDIT_DIR"
if [ "$AUDIT_DIR" != "data" ]; then
  export TMPDIR="${TMPDIR:-$AUDIT_DIR/tmp}"; mkdir -p "$TMPDIR"
fi
OUT="$AUDIT_DIR/v241_cache_fill"; mkdir -p "$OUT"
SUM="$OUT/fill_progress.log"

REASONING_ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": false, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true, "reasoning_layer_enabled": true}'

log() { echo "$@" | tee -a "$SUM"; }

CELL_SRC="$(python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for w in m["windows"]:
    cycles = max(1, min(200, w["min_bars"] - 31))
    print(f"{w['id']}|{w['path']}|{w['regime']}|{cycles}")
PY
)"

total=0; done_n=0
while IFS='|' read -r wid path regime cycles; do
  [ -z "$wid" ] && continue
  if [ -n "${WINDOWS:-}" ]; then
    case " $WINDOWS " in *" $wid "*) : ;; *) continue ;; esac
  fi
  total=$((total+1))
  if [ -f "$OUT/${wid}.done" ]; then
    log "--- SKIP $wid — already filled (resume) ---"; done_n=$((done_n+1)); continue
  fi
  vprefix="v241fill_${wid}"
  ncache_before=$(ls data/frozen_llm_cache/gemini-3.1-pro-low/*.json 2>/dev/null | grep -cv MANIFEST)
  log "--- FILL $wid regime=$regime cycles=$cycles cache_before=$ncache_before start $(date -u +%FT%TZ) ---"
  # Committed run-state restore (V240 protocol; prompt-hash identity depends
  # on it — see SESSION_STATE "grid restored committed state before running").
  git checkout -q data/macro_cache.db data/signal_ic_history.json data/training_version.txt data/.cache_manifest.json 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true
  t0=$(date +%s)
  OMEGA_LLM_CACHE_FILL=1 \
  OMEGA_REASONING_TRACE="$OUT/${wid}_reasoning_trace.jsonl" \
  CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=off EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$regime" 1 "$REASONING_ON" "$vprefix" 200 0 \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  t1=$(date +%s)
  ncache_after=$(ls data/frozen_llm_cache/gemini-3.1-pro-low/*.json 2>/dev/null | grep -cv MANIFEST)
  calls=$((ncache_after - ncache_before))
  if [ $rc -eq 0 ]; then
    touch "$OUT/${wid}.done"; done_n=$((done_n+1))
    log "--- FILL $wid OK rc=$rc new_cache_entries=$calls wall=$((t1-t0))s $(date -u +%FT%TZ) ---"
  else
    log "--- FILL $wid FAILED rc=$rc new_cache_entries=$calls wall=$((t1-t0))s — resumable, see $OUT/${vprefix}.log ---"
  fi
done <<< "$CELL_SRC"

log "=== V241 cache-fill pass complete: $done_n/$total windows filled $(date -u +%FT%TZ) ==="
python3 scripts/v241_intervention_report.py --glob "$OUT/*_reasoning_trace.jsonl" \
  --json-out "$OUT/intervention_report.json" | tee -a "$SUM"
