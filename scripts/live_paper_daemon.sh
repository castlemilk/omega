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
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
  echo "FATAL: daemon already running (pid $(cat "$PID_FILE")); one writer per checkpoint dir." >&2
  exit 4
fi

echo "=== V252 live-paper daemon start $(date -u +%FT%TZ) args=$* ===" | tee -a "$RUN_LOG"
nohup "$PYTHON" scripts/live_paper_daemon.py "$@" >> "$RUN_LOG" 2>&1 &
DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"
echo "daemon pid=$DAEMON_PID  log=$RUN_LOG  pidfile=$PID_FILE" | tee -a "$RUN_LOG"
disown "$DAEMON_PID" 2>/dev/null || true
