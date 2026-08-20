#!/bin/bash
# V274 Phase 1 — the IC-ON arm across all 32 walk-forward manifest windows.
# Pre-registration: omega/nodes/victoria/training_log/V274.md §2/§3.
#
# G0 established that the standing baseline (crisis +$599 / trend +$2,997 /
# recent +$30) was produced with ic_seed_weighting EXPLICITLY FALSE in all 32
# cells, so the informative arm is IC-ON: how far would the baseline have moved
# had V273's H3 defect actually been present in its entry gate?
#
# Structure mirrors scripts/v240_wf_grid.sh (same manifest, same N policy, same
# SLEEP=0 condition, same resume-by-PASS logic) so the two arms are paired
# per-window. Cell prefixes match scripts/v274_smoke.sh, so the three sentinel
# cells the Phase-0 smoke already ran are picked up by the resume check.
#
# No code is changed by this version. The only lever is the --features JSON.
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

OUT="$AUDIT_DIR/v274"; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"
SUM="$OUT/grid_progress.log"

# ARM_ON = the V240 universe_selective string with ic_seed_weighting flipped
# false -> true. per_regime_ic_weighting is left at its features.py default
# (True) — under IC-ON it becomes live, which is exactly the H3 configuration.
ARM_ON='{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "crisis_skew_drawdown_threshold": 0.12, "rv_term_brake_enabled": false, "ic_seed_weighting": true, "crisis_term_predemean_enabled": false, "crisis_size_throttle_enabled": false, "universe_selective_enabled": true}'

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

CELLS=()
while IFS= read -r line; do
  [ -z "$line" ] && continue
  wid="${line%%|*}"
  if [ -n "${WINDOWS:-}" ]; then
    case " $WINDOWS " in *" $wid "*) : ;; *) continue ;; esac
  fi
  CELLS+=("$line")
done <<< "$CELL_SRC"
TOTAL=${#CELLS[@]}

cell_summary() { echo "$AUDIT_DIR/v274_on_${1}_${2}_determinism/summary.json"; }  # wid gate
cell_done() {
  local p; p="$(cell_summary "$1" "$2")"
  [ -f "$p" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('verdict')=='PASS' else 1)" "$p" 2>/dev/null
}

write_manifest() { # done total phase
  python3 - "$STATE" "$1" "$2" "$3" "$SLEEP" <<'PY'
import json, sys
state, done, total, phase, slp = sys.argv[1:6]
json.dump({"version":"v274_ic_on","phase":phase,"cells_done":int(done),"cells_total":int(total),
           "max_parallel":1,"sleep":int(slp),
           "manifest_note":"resumable: re-run scripts/v274_ic_on_grid.sh to continue"},
          open(state,"w"), indent=2)
PY
}

DONE0=0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles <<< "$c"
  cell_done "$wid" "$regime" && DONE0=$((DONE0+1))
done

log "=== V274 IC-ON grid start $(date -u +%FT%TZ) — $TOTAL cells (sleep=$SLEEP, sentinels N=2), $DONE0 already done (resume); AUDIT=$AUDIT_DIR ==="
write_manifest "$DONE0" "$TOTAL" "running"

done=$DONE0
for c in "${CELLS[@]}"; do
  IFS='|' read -r wid path regime cycles <<< "$c"
  vprefix="v274_on_${wid}"

  if [ ! -f "$path" ]; then log "--- SKIP $vprefix — snapshot missing: $path ---"; continue; fi
  if cell_done "$wid" "$regime"; then log "--- SKIP $vprefix — already PASS (resume) ---"; continue; fi

  # Restore committed macro_cache.db bytes before each cell (WAL sidecar drift
  # fix, carried from V238/V239/V240 — see 10ccb64). Safe here: this grid runs
  # from an isolated worktree whose data/ is not shared with any daemon.
  git checkout -q data/macro_cache.db 2>/dev/null || true
  rm -f data/macro_cache.db-wal data/macro_cache.db-shm 2>/dev/null || true

  n="$(n_for "$wid")"
  log "--- CELL $vprefix regime=$regime N=$n cycles=$cycles start $(date -u +%FT%TZ) ---"
  CYCLES="$cycles" SNAP_OVERRIDE="$path" WINDOW_LABEL="$wid" \
  EXPECT_SKEW=on EXPECT_GATE=on EXPECT_IC=on EXPECT_BRAKE=off EXPECT_PREDEMEAN=post_demean EXPECT_THROTTLE=off \
    bash scripts/check_determinism.sh "$regime" "$n" "$ARM_ON" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  rc=$?
  grep -h "DETERMINISM:" "$AUDIT_DIR/${vprefix}_${regime}_determinism/run.log" 2>/dev/null | tail -1 | tee -a "$SUM"
  log "--- CELL $vprefix done rc=$rc $(date -u +%FT%TZ) ---"
  cell_done "$wid" "$regime" && done=$((done+1))
  write_manifest "$done" "$TOTAL" "running"
done

log "=== V274 IC-ON grid complete $(date -u +%FT%TZ) — $done/$TOTAL cells PASS ==="
write_manifest "$done" "$TOTAL" "complete"
