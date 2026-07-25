#!/bin/bash
# V252 — headless live-paper daemon entrypoint (nohup/PID-tracked).
#
# Wraps scripts/live_paper_daemon.py so the scheduler + crash-safe checkpoint
# can run unattended for 90+ days. Pure runner-layer: no broker, no orders, no
# funds. On a SIGKILL the daemon dies mid-cycle; on restart it reloads the last
# atomic checkpoint and resumes idempotently (see V252.md).
#
# Usage:
#   # 7-day burn-in (deterministic fixture cycle, no network):
#   SCHEDULER_ENABLED=1 bash scripts/live_paper_daemon.sh --mode fixture
#
#   # V253 production soak (real live feeds):
#   SCHEDULER_ENABLED=1 OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data \
#     bash scripts/live_paper_daemon.sh --mode forward
#
# Env:
#   SCHEDULER_ENABLED          master gate (default OFF; must be 1 to run)
#   SCHEDULER_TICK_UTC         daily fire time, default 04:05:00
#   OMEGA_AUDIT_OUTPUT_DIR     checkpoint/pnl output root (gamma volume in prod)
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH

PYTHON="${PYTHON:-python3}"
AUDIT_DIR="${OMEGA_AUDIT_OUTPUT_DIR:-data}"
LOG_DIR="$AUDIT_DIR/live_paper/logs"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/daemon.pid"
RUN_LOG="$LOG_DIR/daemon.out"

# Refuse to start a second daemon against the same checkpoint dir (one writer).
# Two pid files are consulted: the on-gamma one written here, and the local one
# written by scripts/live_paper_launchd.sh — a launchd-spawned bash cannot write
# to /Volumes (TCC EPERM), so the launchd job's claim only lands locally. Check
# both or a hand-run here would happily become a second writer alongside launchd.
LOCAL_PID_FILE="${LIVE_PAPER_LOCAL_PID_FILE:-$HOME/Library/Logs/omega/daemon.pid}"
for _pf in "$PID_FILE" "$LOCAL_PID_FILE"; do
  _other="$(cat "$_pf" 2>/dev/null)" || continue
  [ -n "$_other" ] || continue
  if kill -0 "$_other" 2>/dev/null; then
    echo "FATAL: daemon already running (pid $_other, via $_pf); one writer per checkpoint dir." >&2
    echo "       If that is the launchd agent: launchctl unload -w ~/Library/LaunchAgents/com.omega.live_paper.plist" >&2
    exit 4
  fi
done

echo "=== V252 live-paper daemon start $(date -u +%FT%TZ) args=$* ===" | tee -a "$RUN_LOG"
nohup "$PYTHON" scripts/live_paper_daemon.py "$@" >> "$RUN_LOG" 2>&1 &
DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"
echo "daemon pid=$DAEMON_PID  log=$RUN_LOG  pidfile=$PID_FILE" | tee -a "$RUN_LOG"
disown "$DAEMON_PID" 2>/dev/null || true
