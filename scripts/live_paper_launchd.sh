#!/bin/bash
# V253 — launchd exec wrapper for the live-paper soak daemon.
#
# Why a wrapper instead of pointing the plist straight at python3:
#   1. launchd does NOT source shell rc files, and it does not read `.env`. The
#      daemon needs FRED_API_KEY + DATABASE_URL, which live in the gitignored
#      `harness/.env`. Baking them into ~/Library/LaunchAgents/*.plist would put
#      a live API key and a DB password in a world-readable plist — so we source
#      `harness/.env` here instead and keep the plist secret-free.
#   2. The output root has to EXIST before python starts, or launchd crash-loops
#      against a missing checkpoint dir. This was written for the gamma volume,
#      an external mount that could appear after login; the soak now writes to
#      local disk, where the wait passes on the first iteration. The guard is
#      kept because its real job is "refuse to start against the wrong root",
#      which matters more now, not less: a missing local dir would otherwise be
#      silently created somewhere unintended.
#   3. It execs the REPO VENV, not `python3`. On this host `python3` resolves to
#      Homebrew 3.14 with none of numpy/psycopg/yaml installed, so the daemon
#      died on import. The venv is the interpreter every other entrypoint uses.
#
# NOT scripts/live_paper_daemon.sh: that one nohup+disowns, which makes launchd
# think the job exited and immediately restart it. Here launchd IS the supervisor,
# so we `exec` the python process directly into launchd's slot.
#
# Manual use is fine too:  bash scripts/live_paper_launchd.sh
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:/usr/bin:/bin

# ── secrets (FRED_API_KEY, DATABASE_URL) — gitignored, never in the plist ──────
#
# `.env` first, because that is where this repo's keys actually live and
# `harness/` has never existed — the original `[ -f harness/.env ]` guard meant
# the source was a silent no-op, so a key added to the obvious place was read by
# nothing. The only symptom would have been FRED 400 warnings buried in
# daemon.err, and a key that is present but unsourced looks exactly like a key
# that was never added.
#
# harness/.env is still honoured, second, so it can override for a host that
# keeps soak secrets separate from the repo's.
for _envf in .env harness/.env; do
  if [ -f "$_envf" ]; then
    set -a
    # shellcheck disable=SC1090
    . "./$_envf"
    set +a
  fi
done

if [ -z "${FRED_API_KEY:-}" ]; then
  # Not fatal: VIXCLS and DTWEXBGS fail over to Yahoo. DGS2/DGS10 have no
  # fallback, so the yield-curve input is simply absent — worth one loud line
  # rather than 90 days of silent degradation.
  echo "$(date -u +%FT%TZ) WARNING: FRED_API_KEY unset — DGS2/DGS10 unavailable (no fallback); VIX/DXY will use Yahoo." >&2
fi

# ── V253 soak configuration (matches the manual launch env, see V253 kickoff) ──
# gamma-systems-2 is gone; the soak writes to local disk. Sizing is not the
# reason the external volume was chosen — the runbook's own math is ~0.5-2 GB
# over the full 90 days, and the 100 GB floor was ENOSPC insurance. This host
# has ~638 GB free, so the insurance still holds.
export OMEGA_AUDIT_OUTPUT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-$HOME/omega-victoria-data}"
export LIVE_PAPER_ENABLED="${LIVE_PAPER_ENABLED:-1}"

# ── keep the soak OFF the committed frozen substrate (load-bearing) ───────────
# data/macro_cache.db, omega_victoria_state.db and omega_victoria_memory.db are
# COMMITTED files whose md5s data/.cache_manifest.json asserts. Every backtest
# and the standing baseline read them.
#
# Without these three overrides the daemon resolves each path from __file__ and
# writes the repo copy on EVERY cycle. Measured, not theorised: one forward
# cycle moved macro_cache.db from 397b9438… to a0bed83b…, and a 90-day soak
# would have rewritten it ~90 times while the V251 reconciliation was still
# claiming live/frozen bit-identity against it. The tests' own guard
# (tests/conftest.py) sets exactly these three, but it only covers pytest — a
# daemon started by launchd is outside it entirely.
#
# Pointed INTO the soak's own output root so its cache is real and warm (an
# empty macro cache makes every lookup miss and fall through to a live fetch),
# while the repo copy stays byte-identical.
export OMEGA_SUBSTRATE_DIR="${OMEGA_SUBSTRATE_DIR:-$OMEGA_AUDIT_OUTPUT_DIR/live_paper/substrate}"
mkdir -p "$OMEGA_SUBSTRATE_DIR"
for _db in macro_cache.db omega_victoria_memory.db omega_victoria_state.db; do
  [ -f "$OMEGA_SUBSTRATE_DIR/$_db" ] || cp -p "data/$_db" "$OMEGA_SUBSTRATE_DIR/$_db" 2>/dev/null || true
done
export OMEGA_MACRO_CACHE_PATH="${OMEGA_MACRO_CACHE_PATH:-$OMEGA_SUBSTRATE_DIR/macro_cache.db}"
export OMEGA_MEMORY_DB_PATH="${OMEGA_MEMORY_DB_PATH:-$OMEGA_SUBSTRATE_DIR/omega_victoria_memory.db}"
export OMEGA_STATE_DB_PATH="${OMEGA_STATE_DB_PATH:-$OMEGA_SUBSTRATE_DIR/omega_victoria_state.db}"
export SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-1}"
export SCHEDULER_TICK_UTC="${SCHEDULER_TICK_UTC:-02:55:00}"

# Standing V240-selective baseline — identical to scripts/v252_reconcile_smoke.py
# (SELECTIVE) and to every manual daemon launch in this soak.
export VICTORIA_FEATURES="${VICTORIA_FEATURES:-{\"crisis_skew_enabled\": true, \"crisis_skew_regime_gate_enabled\": true, \"crisis_skew_drawdown_threshold\": 0.12, \"rv_term_brake_enabled\": false, \"ic_seed_weighting\": false, \"crisis_term_predemean_enabled\": false, \"crisis_size_throttle_enabled\": false, \"universe_selective_enabled\": true}}"

# ── wait for the checkpoint root to exist (bounded: 10 min) ───────────────────
# Local now, so this normally passes immediately. Still bounded rather than
# instant: if the root is ever moved back onto a removable volume, this is what
# stops launchd spinning against a path that has not appeared yet.
CKPT_ROOT="$OMEGA_AUDIT_OUTPUT_DIR"
for _ in $(seq 1 120); do
  [ -d "$CKPT_ROOT" ] && break
  echo "$(date -u +%FT%TZ) waiting for $CKPT_ROOT to appear..." >&2
  sleep 5
done
if [ ! -d "$CKPT_ROOT" ]; then
  echo "$(date -u +%FT%TZ) FATAL: $CKPT_ROOT never appeared — refusing to start (would write to the wrong root)." >&2
  exit 69   # EX_UNAVAILABLE
fi

# ── one writer per checkpoint dir ─────────────────────────────────────────────
# Guards against launchd racing a hand-started (nohup) daemon. Exit 0 so KeepAlive
# treats it as a clean stop rather than a crash-loop; launchd retries after
# ThrottleInterval and takes over once the manual one goes away.
#
# TCC NOTE (macOS, load-bearing): a launchd-spawned **/bin/bash** has NO
# read/write access to `/Volumes` — every open() there returns EPERM (stat/`-d`
# still works). Homebrew python3 DOES hold the removable-volume grant, so the
# daemon's own checkpoint + pnl writes are fine; it is only this shell that is
# blocked. That makes the on-gamma pid file unreadable AND unwritable here, so
# the guard would be silently inert. Hence a second, always-accessible pid file
# under ~/Library/Logs/omega — that one is the authoritative cross-check between
# the launchd job and a hand-run scripts/live_paper_daemon.sh.
PID_FILE="$CKPT_ROOT/live_paper/logs/daemon.pid"
LOCAL_PID_FILE="${LIVE_PAPER_LOCAL_PID_FILE:-$HOME/Library/Logs/omega/daemon.pid}"
mkdir -p "$(dirname "$LOCAL_PID_FILE")"

for _pf in "$LOCAL_PID_FILE" "$PID_FILE"; do
  _other="$(cat "$_pf" 2>/dev/null)" || continue
  [ -n "$_other" ] || continue
  # Don't stand down for our own stale entry from a previous exec of this job.
  [ "$_other" = "$$" ] && continue
  if kill -0 "$_other" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) another live-paper daemon is running (pid $_other, via $_pf); standing down." >&2
    exit 0
  fi
done

# Claim the pid files with OUR pid — `exec` below replaces this shell in place, so
# $$ IS the python process's pid. This keeps scripts/live_paper_daemon.sh's guard
# honest in the other direction too: a hand-run daemon refuses to start while the
# launchd-supervised one holds the file. The gamma write is best-effort (EPERM
# under launchd, see the TCC note above); the local one is the reliable claim.
echo $$ > "$LOCAL_PID_FILE"
mkdir -p "$(dirname "$PID_FILE")" 2>/dev/null || true
echo $$ > "$PID_FILE" 2>/dev/null || \
  echo "$(date -u +%FT%TZ) note: cannot write $PID_FILE (TCC/launchd); authoritative pid file is $LOCAL_PID_FILE" >&2

# ── interpreter ───────────────────────────────────────────────────────────────
# The repo venv, NOT `python3`. Measured on this host: the PATH above resolves
# python3 to Homebrew 3.14, which has numpy, psycopg and yaml all MISSING — the
# daemon would exit on import and launchd would crash-loop it forever. Falling
# back to python3 only if the venv is absent keeps a bare checkout working.
PYBIN="./.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN="python3"

echo "=== V253 launchd live-paper daemon exec $(date -u +%FT%TZ) tick=$SCHEDULER_TICK_UTC root=$CKPT_ROOT py=$PYBIN pid=$$ ===" >&2
exec "$PYBIN" scripts/live_paper_daemon.py --mode forward
