#!/usr/bin/env bash
# V269 Phase B — idempotent installer for the forward L2 depth collector.
#
# Installs launchd agent  com.omega.depth_collector  — DISTINCT from the
# live-paper strategy daemon's  com.omega.live_paper.  Different label,
# different program, different log paths, zero shared state (V269 §6).
#
# This script NEVER touches com.omega.live_paper or its plist.
#
# Usage:
#   scripts/install_depth_collector.sh            # install + load + start
#   scripts/install_depth_collector.sh --status   # report only
#   scripts/install_depth_collector.sh --uninstall
set -euo pipefail

LABEL="com.omega.depth_collector"
PROTECTED_LABEL="com.omega.live_paper"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$REPO/data/v269_depth_logs"
SCRIPT="$REPO/scripts/v269_depth_collector.py"

# Hard guard: refuse to run if the label was ever mistyped toward the daemon's.
if [[ "$LABEL" == "$PROTECTED_LABEL" ]]; then
  echo "FATAL: label collides with the live-paper daemon. Aborting." >&2
  exit 1
fi

status() {
  echo "== $LABEL =="
  if launchctl list "$LABEL" >/dev/null 2>&1; then
    launchctl list "$LABEL" | grep -E '"(PID|LastExitStatus)"' || true
  else
    echo "  not loaded"
  fi
  echo "== $PROTECTED_LABEL (untouched, read-only check) =="
  launchctl list "$PROTECTED_LABEL" 2>/dev/null | grep -E '"(PID|LastExitStatus)"' \
    || echo "  not loaded"
  echo "== landed depth partitions =="
  find "$REPO/data/frozen_series/binance_depth_forward" -name '*.json.gz' 2>/dev/null \
    | wc -l | xargs echo "  files:"
}

case "${1:-install}" in
  --status) status; exit 0 ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
      || launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "uninstalled $LABEL (spools and landed data left in place)"
    exit 0 ;;
  install) ;;
  *) echo "unknown arg: $1" >&2; exit 2 ;;
esac

PY="$(command -v python3)"
[[ -x "$PY" ]] || { echo "FATAL: python3 not found" >&2; exit 1; }
[[ -f "$SCRIPT" ]] || { echo "FATAL: missing $SCRIPT" >&2; exit 1; }

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

# Idempotent: unload an existing instance before rewriting the plist.
if launchctl list "$LABEL" >/dev/null 2>&1; then
  echo "unloading existing $LABEL"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
    || launchctl unload "$PLIST" 2>/dev/null || true
fi

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>StandardOutPath</key><string>${LOG_DIR}/depth_collector.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/depth_collector.err.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
</dict>
</plist>
PLIST_EOF

plutil -lint "$PLIST" >/dev/null

launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST"
launchctl kickstart "gui/$(id -u)/$LABEL" 2>/dev/null || true

echo "installed $LABEL -> $PLIST"
sleep 3
status
