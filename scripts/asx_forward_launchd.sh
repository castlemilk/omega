#!/bin/bash
# V309 — launchd exec wrapper for the forward ASX lane.
#
# Same shape as scripts/live_paper_launchd.sh, for the same reasons: launchd
# sources no rc files and reads no .env; the daemon must run under the repo venv
# (Homebrew python3 lacks numpy/yfinance); and launchd IS the supervisor, so the
# python process is exec'd into this slot rather than nohup'd.
#
# No broker, no orders, no capital: this lane appends what the market published
# and writes one spread observation a week. See training_log/V309_ASX_FORWARD.md.
#
# Manual use:  SCHEDULER_ENABLED=1 bash scripts/asx_forward_launchd.sh
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:/usr/bin:/bin

for _envf in .env harness/.env; do
  if [ -f "$_envf" ]; then
    set -a
    # shellcheck disable=SC1090
    . "./$_envf"
    set +a
  fi
done

export OMEGA_ASX_FORWARD_DIR="${OMEGA_ASX_FORWARD_DIR:-$HOME/omega-asx-forward}"
export SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-1}"
export SCHEDULER_TICK_UTC="${SCHEDULER_TICK_UTC:-09:00:00}"
# The soak's frozen-substrate overrides, kept for the same reason: nothing a
# daemon does may touch a committed cache file.
export OMEGA_MACRO_CACHE_PATH="${OMEGA_MACRO_CACHE_PATH:-$OMEGA_ASX_FORWARD_DIR/scratch/macro_cache.db}"
mkdir -p "$OMEGA_ASX_FORWARD_DIR/scratch" "$HOME/Library/Logs/omega"

PYTHON="$(pwd)/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "$(date -u +%FT%TZ) FATAL: repo venv interpreter missing at $PYTHON" >&2
  exit 78
fi

# One writer per store. launchd restarts us if we exit, so a stale pid file from
# a crash is harmless (kill -0 fails and we proceed).
PID_FILE="$HOME/Library/Logs/omega/asx_forward.pid"
_other="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -n "$_other" ] && kill -0 "$_other" 2>/dev/null && [ "$_other" != "$$" ]; then
  echo "$(date -u +%FT%TZ) FATAL: asx_forward already running (pid $_other)" >&2
  exit 4
fi
echo "$$" > "$PID_FILE"

echo "$(date -u +%FT%TZ) asx_forward start root=$OMEGA_ASX_FORWARD_DIR tick=$SCHEDULER_TICK_UTC" >&2
exec "$PYTHON" scripts/asx_forward_daemon.py "$@"
