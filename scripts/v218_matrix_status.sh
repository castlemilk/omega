#!/bin/bash
# V218 matrix health monitor — single-pane status for the 3 concurrent cells.
#
# The matrix runs 3 worktrees in parallel (A=carry plumbing, B=V170 IC [BLOCKED
# no-op], E=2020q1 crisis snapshot), each driving a determinism gate + a
# 3-gate × N audit via check_determinism.sh. This script gives one-line-per-cell
# visibility: orchestrator liveness, last log line, and gate-completion progress.
#
# Usage:  scripts/v218_matrix_status.sh
# Re-run any time; read-only. Exit 0 if any cell still alive, else 0 (informational).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WT="$ROOT/.claude/worktrees"

# cell-letter  worktree-dir  orchestrator-log
CELLS=(
  "a  $WT/v218-a-carry-plumbing       /tmp/v218a_orch.log"
  "b  $WT/v218-b-v170-ic              /tmp/v218b_orch.log"
  "e  $WT/v218-e-snap-crisis-2020q1   /tmp/v218e_orch.log"
)

now="$(date -u +%FT%TZ)"
echo "=== V218 matrix status @ $now ==="
any_alive=0
for row in "${CELLS[@]}"; do
  read -r letter wt log <<<"$row"
  pidfile="$wt/data/v218${letter}_pids.txt"

  # liveness: any PID in the cell's pidfile still running?
  alive="done"
  live_pids=""
  if [ -f "$pidfile" ]; then
    while read -r pid; do
      [ -n "$pid" ] || continue
      if kill -0 "$pid" 2>/dev/null; then alive="ALIVE"; live_pids="$live_pids $pid"; fi
    done < "$pidfile"
  else
    alive="nopid"
  fi
  [ "$alive" = "ALIVE" ] && any_alive=1

  # progress: count completed determinism summaries (one per gate call).
  done_gates=0
  if [ -d "$wt/data" ]; then
    done_gates=$(find "$wt/data" -maxdepth 2 -name summary.json -path '*v218'"$letter"'*' 2>/dev/null | wc -l | tr -d ' ')
  fi

  # last verdict line + last log line
  last_det=""
  if [ -d "$wt/data" ]; then
    last_det=$(grep -rh "DETERMINISM:" "$wt"/data/v218"$letter"*/run.log 2>/dev/null | tail -1)
  fi
  last_log=""
  [ -f "$log" ] && last_log=$(tail -1 "$log" 2>/dev/null | cut -c1-100)

  printf "[%s] %-6s pids:%-14s gates_done=%s\n" "$letter" "$alive" "${live_pids:- -}" "$done_gates"
  [ -n "$last_det" ] && printf "      last verdict: %s\n" "$(echo "$last_det" | cut -c1-110)"
  [ -n "$last_log" ] && printf "      last log:     %s\n" "$last_log"
done

echo "---"
if [ "$any_alive" = "1" ]; then
  echo "STATUS: at least one cell still running."
else
  echo "STATUS: no live cell PIDs — all cells finished or not yet launched."
fi
