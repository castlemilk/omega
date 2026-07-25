#!/bin/bash
# V253 — launchd exec wrapper for the live-paper soak daemon.
#
# Why a wrapper instead of pointing the plist straight at python3:
#   1. launchd does NOT source shell rc files, and it does not read `.env`. The
#      daemon needs FRED_API_KEY + DATABASE_URL, which live in the gitignored
#      `harness/.env`. Baking them into ~/Library/LaunchAgents/*.plist would put
#      a live API key and a DB password in a world-readable plist — so we source
#      `harness/.env` here instead and keep the plist secret-free.
#   2. The gamma volume is an EXTERNAL mount that can appear AFTER login. Exec'ing
#      python before it mounts makes launchd crash-loop against a missing
#      checkpoint dir, so we wait (bounded) for the mount first.
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
if [ -f harness/.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./harness/.env
  set +a
fi

# ── V253 soak configuration (matches the manual launch env, see V253 kickoff) ──
export OMEGA_AUDIT_OUTPUT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-/Volumes/gamma-systems-2/omega-victoria-data/live_paper_v253_smoke_v2}"
export LIVE_PAPER_ENABLED="${LIVE_PAPER_ENABLED:-1}"
export SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-1}"
export SCHEDULER_TICK_UTC="${SCHEDULER_TICK_UTC:-02:55:00}"

# Standing V240-selective baseline — identical to scripts/v252_reconcile_smoke.py
# (SELECTIVE) and to every manual daemon launch in this soak.
export VICTORIA_FEATURES="${VICTORIA_FEATURES:-{\"crisis_skew_enabled\": true, \"crisis_skew_regime_gate_enabled\": true, \"crisis_skew_drawdown_threshold\": 0.12, \"rv_term_brake_enabled\": false, \"ic_seed_weighting\": false, \"crisis_term_predemean_enabled\": false, \"crisis_size_throttle_enabled\": false, \"universe_selective_enabled\": true}}"

# ── wait for the external checkpoint volume (bounded: 10 min) ─────────────────
CKPT_ROOT="$OMEGA_AUDIT_OUTPUT_DIR"
for _ in $(seq 1 120); do
  [ -d "$CKPT_ROOT" ] && break
  echo "$(date -u +%FT%TZ) waiting for $CKPT_ROOT to mount..." >&2
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

echo "=== V253 launchd live-paper daemon exec $(date -u +%FT%TZ) tick=$SCHEDULER_TICK_UTC root=$CKPT_ROOT pid=$$ ===" >&2
exec python3 scripts/live_paper_daemon.py --mode forward
