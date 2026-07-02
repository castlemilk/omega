#!/bin/bash
# V213 observability delta #2: auto-replicate determinism check.
#
# Runs N replicates of one (gate, features) cell as SEPARATE processes with the
# same seed and frozen cache, then reports the PnL spread + trade-count range and
# emits a single DETERMINISM: PASS|FAIL line. Separate processes are the gold
# standard — they expose id()-ordered / async-completion-ordered non-determinism
# that an in-process re-run would hide.
#
# This is the instrumentation the V207a–V211 arc lacked: those four versions hunted
# noise sources by hand. With this, "is the eval deterministic?" is one command.
#
# It also performs Fix-B per-run state isolation: any run-written disk state read
# at the next run's startup (signal_ic_history.json + the three frozen DBs) is
# snapshotted once and restored before EACH replicate, so a cross-run channel
# cannot leak between replicates.
#
# Usage:
#   scripts/check_determinism.sh GATE [N] [FEATURES_JSON] [VERSION_PREFIX] [FLOOR_USD]
# Examples:
#   scripts/check_determinism.sh trend 2 '{"strategy_selector_enabled": true}' v213_validate 200
#   scripts/check_determinism.sh recent 2 '{}' v213_baseline 200
set -u
cd "$(dirname "$0")/.."   # scripts/ → repo root

GATE="${1:?gate required (recent|trend|crisis)}"
N="${2:-2}"
# NB: do NOT inline a brace-containing default like ${3:-{}} — bash parses that
# as ${3:-{} followed by a literal }, appending a stray brace that corrupts the
# JSON. Assign the default on a separate line.
FEATURES="${3:-}"
[ -z "$FEATURES" ] && FEATURES='{}'
VPREFIX="${4:-v213_check}"
FLOOR="${5:-200}"
SLEEP="${6:-0}"   # seconds between cycles; 0 is fastest. NB prior versions' canonical eval used 10.

ROOT=$(pwd)
# OMEGA_AUDIT_OUTPUT_DIR: redirect determinism-cell outputs + the per-replicate
# run_training write artifacts (results/trades/jsonl) off the host disk onto an
# external mount (e.g. gamma-systems-2) to avoid the ENOSPC class that paused
# V232/V233. Defaults to $ROOT/data. run_training.py honors the SAME env var, so the
# results.json/trades.csv this script copies from AUDIT_DIR land there too. Stable
# frozen-cache INPUTS (signal_ic_history.json, *.db, snapshots) stay under data/.
AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-$ROOT/data}"
mkdir -p "$AUDIT_DIR"
OUT="$AUDIT_DIR/${VPREFIX}_${GATE}_determinism"
mkdir -p "$OUT"
PIDFILE="$AUDIT_DIR/${VPREFIX}_${GATE}_pids.txt"; : > "$PIDFILE"
SUMMARY="$OUT/summary.json"
LOG="$OUT/run.log"

snap_for() {
  case "$1" in
    recent) echo "data/snapshots/snap_20260414.json" ;;
    trend)  echo "data/snapshots/snap_trending_2023q4.json" ;;
    crisis) echo "data/snapshots/snap_crisis_2022h1.json" ;;
    *) echo "" ;;
  esac
}
# V218.E: SNAP_OVERRIDE env lets a caller substitute the snapshot for a gate
# without editing the script (cell E runs its "crisis" gate against
# snap_crisis_2020q1.json with no code diff). Falls back to the gate default.
SNAP="${SNAP_OVERRIDE:-$(snap_for "$GATE")}"
[ -z "$SNAP" ] && { echo "FATAL: unknown gate '$GATE'"; exit 2; }
[ -f "$SNAP" ] || { echo "FATAL: snapshot not found: $SNAP"; exit 2; }

# V216 obs-delta #8: sizing-layer wall-clock tripwire preflight. Any unguarded
# datetime.now()/time.time() in the sizing path leaks non-determinism into trade
# sizing (the V215 channel) — fail before burning replicate runs.
python3 scripts/check_no_wallclock.py || { echo "FATAL: wall-clock tripwire failed (see above)"; exit 3; }

# V227 obs-delta: non-urllib HTTP frozen-fence preflight. yfinance/curl_cffi
# fetches bypass the V215 urllib guard; any HTTP signal module must carry an
# OMEGA_FROZEN_CACHE fence (the V226 spy_signal determinism channel that cost a
# whole determinism FAIL because the urllib leak-log was blind to curl_cffi).
python3 scripts/check_frozen_http_fence.py || { echo "FATAL: frozen-HTTP-fence tripwire failed (see above)"; exit 3; }

# Fix-B state isolation: snapshot run-written disk state once, restore per run.
ISO="$OUT/.state_snapshot"; mkdir -p "$ISO"
for f in data/signal_ic_history.json data/omega_victoria_state.db data/omega_victoria_memory.db data/macro_cache.db; do
  [ -f "$f" ] && cp -f "$f" "$ISO/$(basename "$f")" 2>/dev/null
done
restore_state() {
  for f in signal_ic_history.json omega_victoria_state.db omega_victoria_memory.db macro_cache.db; do
    [ -f "$ISO/$f" ] && cp -f "$ISO/$f" "data/$f" 2>/dev/null
  done
}

echo "=== determinism check: gate=$GATE N=$N sleep=$SLEEP features=$FEATURES floor=\$$FLOOR @ $(date -u +%FT%TZ) ===" | tee "$LOG"

PNLS=(); TRADES=()
for i in $(seq 1 "$N"); do
  restore_state
  ver="${VPREFIX}_${GATE}_r${i}"
  echo "--- $ver starting $(date -u +%FT%TZ) ---" | tee -a "$LOG"
  PYTHONHASHSEED=42 python3 scripts/run_training.py \
    --version "$ver" \
    --cycles 200 --sleep "$SLEEP" --seed 42 \
    --backtest-snapshot "$SNAP" \
    --frozen-cache \
    --features "$FEATURES" \
    > "$OUT/${ver}_stdout.log" 2> "$OUT/${ver}_stderr.log" &
  pid=$!; echo "$pid" >> "$PIDFILE"; wait "$pid"; rc=$?
  cp -f "$AUDIT_DIR/${ver}_results.json" "$OUT/${ver}_results.json" 2>/dev/null || true
  cp -f "$AUDIT_DIR/${ver}_trades.csv"   "$OUT/${ver}_trades.csv"   2>/dev/null || true
  read -r pnl ntr < <(python3 - "$AUDIT_DIR/${ver}_results.json" <<'PY'
import json,sys
try:
    t=json.load(open(sys.argv[1]))["trades"]
    print(t.get("total_pnl_usd",0.0), t.get("total_closed",0))
except Exception:
    print("ERR ERR")
PY
)
  echo "$ver rc=$rc pnl=$pnl trades=$ntr $(date -u +%FT%TZ)" | tee -a "$LOG"
  [ "$pnl" = "ERR" ] && { echo "FATAL: $ver produced no parseable results" | tee -a "$LOG"; exit 1; }
  # V225 obs: control-identity assertion. Opt-in via EXPECT_SKEW/EXPECT_IC env —
  # verifies the run's ACTUAL identity (crisis_skew_enabled / skew_on_cycles /
  # ic_on_cycles) matches what the cell label claims, catching the V224
  # mislabeled-control bug at cell time. No-op when EXPECT_SKEW is unset (legacy
  # IC grids unaffected).
  if [ -n "${EXPECT_SKEW:-}" ]; then
    python3 scripts/assert_cell_identity.py \
      --results "$AUDIT_DIR/${ver}_results.json" \
      --expect-skew "${EXPECT_SKEW}" --expect-ic "${EXPECT_IC:-off}" \
      --expect-gate "${EXPECT_GATE:-off}" --expect-brake "${EXPECT_BRAKE:-off}" \
      --expect-predemean "${EXPECT_PREDEMEAN:-post_demean}" \
      --expect-throttle "${EXPECT_THROTTLE:-off}" --expect-throttle-s "${EXPECT_THROTTLE_S:-}" \
      2>&1 | tee -a "$LOG" \
      || { echo "FATAL: $ver cell-identity assertion FAILED — run does not match label" | tee -a "$LOG"; exit 4; }
  fi
  PNLS+=("$pnl"); TRADES+=("$ntr")
done

# Spread + verdict
# V231: prepend $SNAP + $WINDOW_LABEL provenance (argv[1],[2]) so the distributional
# aggregator can key each cell on its snapshot/window without re-deriving paths.
# Functionally a no-op for legacy single-window callers (WINDOW_LABEL defaults to "default").
python3 - "$SNAP" "${WINDOW_LABEL:-default}" "$FLOOR" "$SUMMARY" "$GATE" "$FEATURES" "${PNLS[@]}" "::" "${TRADES[@]}" <<'PY' | tee -a "$LOG"
import json,sys
snap=sys.argv[1]; window=sys.argv[2]
floor=float(sys.argv[3]); summary=sys.argv[4]; gate=sys.argv[5]; feats=sys.argv[6]
rest=sys.argv[7:]; sep=rest.index("::")
pnls=[float(x) for x in rest[:sep]]; trades=[int(x) for x in rest[sep+1:]]
spread=max(pnls)-min(pnls); trange=max(trades)-min(trades)
verdict="PASS" if spread < floor else "FAIL"
out={"gate":gate,"features":feats,"n":len(pnls),"pnls":pnls,"trades":trades,
     "pnl_spread":round(spread,2),"trade_range":trange,"floor":floor,"verdict":verdict,
     "snapshot":snap,"window":window}
json.dump(out,open(summary,"w"),indent=2)
print(f"DETERMINISM: {verdict} gate={gate} spread=${spread:,.2f} (floor ${floor:,.0f}) "
      f"trade_range={trange} pnls={pnls} trades={trades}")
PY

# V222 obs-delta #14: auto trade-diff on magnitude-FAIL. When the verdict is
# FAIL but the trade COUNT is locked (the V220 signature: same trades, different
# PnL), the channel is in sizing/exit/PnL accounting — the signal-layer
# fingerprint is structurally blind to it (V220 burned its bet on exactly this;
# V221 ran trade_field_diff.py by hand). Auto-name the first divergent
# (trade, field) so the next magnitude channel is self-naming.
VERDICT=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['verdict'], d['trade_range'])" "$SUMMARY" 2>/dev/null || echo "ERR ERR")
read -r _verdict _trange <<< "$VERDICT"
if [ "$_verdict" = "FAIL" ] && [ "$_trange" = "0" ] && [ "$N" -ge 2 ]; then
  echo "--- magnitude-FAIL (trade_range=0): auto trade-level diff (obs #14) ---" | tee -a "$LOG"
  A_CSV="$OUT/${VPREFIX}_${GATE}_r1_trades.csv"
  B_CSV="$OUT/${VPREFIX}_${GATE}_r2_trades.csv"
  if [ -f "$A_CSV" ] && [ -f "$B_CSV" ]; then
    python3 scripts/trade_field_diff.py "$A_CSV" "$B_CSV" \
      --label-a "${GATE}_r1" --label-b "${GATE}_r2" \
      2>&1 | tee "$OUT/trade_field_diff.txt" | tee -a "$LOG" || true
  else
    echo "auto trade-diff skipped: replicate trades.csv missing ($A_CSV / $B_CSV)" | tee -a "$LOG"
  fi
fi

# Cleanup: confirm no replicate PID survived.
for pid in $(cat "$PIDFILE" 2>/dev/null); do
  kill -0 "$pid" 2>/dev/null && { echo "STILL ALIVE: $pid — killing" | tee -a "$LOG"; kill "$pid"; }
done
echo "=== determinism check complete @ $(date -u +%FT%TZ) → $SUMMARY ===" | tee -a "$LOG"
