#!/usr/bin/env python3
"""scripts/session_state.py — V228 resiliency #3: session-continuity manifest.

A single `data/SESSION_STATE.json` that records where the current training
iteration stands, so a NEW task (after a laptop restart killed the orchestrating
session) can read one file and know "V### is at step N, next action is X, last
commit is Y, grid is alive/dead" — instead of re-deriving it from scratch by
grepping logs, PID files, and the training log. The V222/V224/V226/V227 sessions
all hit mid-run restarts; each recovery cost 1-3h of re-discovery this replaces.

This file is metadata only — it is NEVER read by the eval/compute path, so it
has zero determinism impact. It is surfaced automatically at the top of every
session by `scripts/prepare_session.sh` (which calls `session_state.py show`).

Usage:
    python3 scripts/session_state.py show
    python3 scripts/session_state.py update --version v228 \
        --step "grid running (6 cells, N=2, sleep=10)" \
        --next "finalize V228.md + V229 brief when summaries land" \
        --note "stack drawdown-gated crisis-skew + trend-IC overlay" \
        --pidfile data/v228_pids.txt --grid-log data/v228_grid.log
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "SESSION_STATE.json"


def _git_short_sha() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def _pids_alive(pidfile: str | None) -> dict:
    """Report liveness of every PID in a pidfile (data/v###_pids.txt)."""
    if not pidfile:
        return {}
    p = ROOT / pidfile if not os.path.isabs(pidfile) else Path(pidfile)
    if not p.exists():
        return {"pidfile": pidfile, "exists": False}
    alive, dead = [], []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        try:
            os.kill(pid, 0)
            alive.append(pid)
        except OSError:
            dead.append(pid)
    return {"pidfile": pidfile, "exists": True, "alive": alive, "dead": dead}


def _grid_tail(grid_log: str | None, n: int = 3) -> list[str]:
    if not grid_log:
        return []
    p = ROOT / grid_log if not os.path.isabs(grid_log) else Path(grid_log)
    if not p.exists():
        return []
    try:
        return p.read_text(errors="replace").splitlines()[-n:]
    except Exception:
        return []


def cmd_update(a: argparse.Namespace) -> None:
    state: dict = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}
    if a.version is not None:
        state["version"] = a.version
    if a.step is not None:
        state["step"] = a.step
    if a.next is not None:
        state["next_action"] = a.next
    if a.note is not None:
        state.setdefault("notes", [])
        if a.note not in state["notes"]:
            state["notes"].append(a.note)
    state["last_commit"] = _git_short_sha()
    state["updated_at"] = datetime.now(UTC).isoformat()
    if a.pidfile is not None:
        state["grid"] = _pids_alive(a.pidfile)
    if a.grid_log is not None:
        state["grid_log"] = a.grid_log
        state["grid_log_tail"] = _grid_tail(a.grid_log)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"[session_state] updated {STATE.relative_to(ROOT)} → "
          f"{state.get('version')} @ {state.get('last_commit')}")


def cmd_show(a: argparse.Namespace) -> None:
    if not STATE.exists():
        print("[session_state] no data/SESSION_STATE.json — no recorded iteration state.")
        return
    try:
        state = json.loads(STATE.read_text())
    except Exception as e:
        print(f"[session_state] unreadable: {e}")
        return
    # Refresh grid liveness on read (PIDs may have died since last update).
    g = state.get("grid") or {}
    if g.get("pidfile"):
        state["grid"] = _pids_alive(g["pidfile"])
    print("─── SESSION STATE ───────────────────────────────────────")
    print(f"  version     : {state.get('version')}")
    print(f"  step        : {state.get('step')}")
    print(f"  next_action : {state.get('next_action')}")
    print(f"  last_commit : {state.get('last_commit')}")
    print(f"  updated_at  : {state.get('updated_at')}")
    grid = state.get("grid") or {}
    if grid.get("exists"):
        alive = grid.get("alive") or []
        print(f"  grid        : {'ALIVE ' + str(alive) if alive else 'DONE/DEAD (no live PIDs)'}")
    for note in state.get("notes", []):
        print(f"  note        : {note}")
    for line in state.get("grid_log_tail", []):
        print(f"  log         : {line}")
    print("─────────────────────────────────────────────────────────")


def main() -> None:
    ap = argparse.ArgumentParser(description="Session-continuity manifest (resiliency #3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update", help="merge fields into data/SESSION_STATE.json")
    u.add_argument("--version")
    u.add_argument("--step")
    u.add_argument("--next")
    u.add_argument("--note")
    u.add_argument("--pidfile", help="e.g. data/v228_pids.txt — records liveness")
    u.add_argument("--grid-log", dest="grid_log", help="e.g. data/v228_grid.log")
    u.set_defaults(func=cmd_update)
    s = sub.add_parser("show", help="print the current session state")
    s.set_defaults(func=cmd_show)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
