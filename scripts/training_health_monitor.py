#!/usr/bin/env python3
"""Health monitor for live training runs.

Watches a training process's output files and process state. Detects four
failure modes and optionally auto-recovers:

  - FROZEN:          log file not updated in 2x sleep_interval
  - STUCK:           0 new trades for 50+ cycles AND non-zero earlier trades
  - IDLE:            0 new trades for 20-50 cycles (informational, no action)
  - EMPTY_COMPOSITE: composite_score = 0 / null for 10+ consecutive cycles
                     (the v167b failure mode — strategy alive, market data
                     fine, but composite always 0 → strategy_selector vetoing
                     every cycle, or basket signals failing silently)

On STUCK / FROZEN / EMPTY_COMPOSITE the monitor:
  1. Kills the training process (SIGTERM, then SIGKILL after 5s)
  2. Logs the event with last-known state to data/health_events.jsonl
  3. Re-launches via the original command (recorded at monitor start)
  4. Increments a restart counter; halts if 3 restarts in 24h

Status snapshot written to data/training_health.json every check.

Usage:
  python3 scripts/training_health_monitor.py \
    --pid 87037 \
    --version v167c_15min \
    --sleep-interval 900 \
    --check-interval 1800

To enable auto-relaunch, also pass:
    --relaunch-cmd "OMEGA_METRICS_DIR=data/runs FRED_API_KEY=... python3 scripts/run_training.py --version v167c_15min --cycles 192 --sleep 900 --features v161_live"
    --max-restarts-24h 3
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEALTH_PATH = ROOT / "data" / "training_health.json"
EVENTS_PATH = ROOT / "data" / "health_events.jsonl"

# Detection thresholds
IDLE_TRADES_CYCLES = 20
STUCK_TRADES_CYCLES = 50
EMPTY_COMPOSITE_CYCLES = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill(pid: int, log) -> None:
    if not _is_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        log(f"sent SIGTERM to {pid}")
        for _ in range(10):
            time.sleep(0.5)
            if not _is_alive(pid):
                return
        os.kill(pid, signal.SIGKILL)
        log(f"sent SIGKILL to {pid}")
    except OSError as exc:
        log(f"kill failed: {exc}")


def _read_metrics_tail(version: str, n: int) -> list[dict]:
    paths = [
        ROOT / "data" / "runs" / f"{version}_metrics.jsonl",
        Path(f"/tmp/{version}_metrics.jsonl"),
    ]
    for p in paths:
        if p.exists():
            try:
                with open(p) as f:
                    rows = [json.loads(l) for l in f if l.strip()]
                return rows[-n:] if n else rows
            except Exception:
                pass
    return []


def _trades_count(version: str) -> int:
    p = ROOT / "data" / f"{version}_trades.csv"
    if not p.exists():
        return 0
    with open(p) as f:
        return max(0, sum(1 for _ in f) - 1)  # minus header


def _trades_pnl(version: str) -> float:
    p = ROOT / "data" / f"{version}_trades.csv"
    if not p.exists():
        return 0.0
    import csv
    total = 0.0
    with open(p) as f:
        for r in csv.DictReader(f):
            try:
                total += float(r.get("pnl", 0) or 0)
            except (TypeError, ValueError):
                pass
    return total


def _log_mtime(version: str) -> float | None:
    candidates = [
        ROOT / "data" / f"{version}.log",
        ROOT / f"data/{version}_15min.log",
        ROOT / "data" / "runs" / f"{version}_training.log",
    ]
    for p in candidates:
        if p.exists():
            return p.stat().st_mtime
    return None


def _classify(state: dict, sleep_interval: float) -> tuple[str, str]:
    """Returns (status, reason). status one of:
    HEALTHY | IDLE | STUCK | FROZEN | EMPTY_COMPOSITE | DEAD
    """
    if not state["alive"]:
        return "DEAD", "process not alive"
    log_mt = state["log_mtime"]
    if log_mt is None:
        return "DEAD", "no log file"
    age = time.time() - log_mt
    if age > 2 * sleep_interval:
        return "FROZEN", f"log stale {int(age)}s vs sleep {int(sleep_interval)}s"

    cyc = state["cycle"]
    last_trade_cyc = state["last_trade_cycle"]
    cycles_since_trade = (cyc - last_trade_cyc) if last_trade_cyc is not None else cyc
    n_zero = state["zero_composite_streak"]

    if n_zero >= EMPTY_COMPOSITE_CYCLES:
        return "EMPTY_COMPOSITE", f"{n_zero} consecutive zero composites"
    if state["trades"] > 0 and cycles_since_trade >= STUCK_TRADES_CYCLES:
        return "STUCK", f"{cycles_since_trade} cycles since last trade"
    if cycles_since_trade >= IDLE_TRADES_CYCLES:
        return "IDLE", f"{cycles_since_trade} cycles since last trade (informational)"
    return "HEALTHY", ""


def _gather_state(pid: int, version: str) -> dict:
    rows = _read_metrics_tail(version, 0)
    cycle = rows[-1]["cycle"] if rows else 0
    trades = _trades_count(version)
    pnl = _trades_pnl(version)

    # last_trade_cycle: scan trades.csv for the highest cycle column
    last_trade_cycle = None
    p = ROOT / "data" / f"{version}_trades.csv"
    if p.exists():
        import csv
        with open(p) as f:
            for r in csv.DictReader(f):
                try:
                    c = int(r.get("cycle", 0) or 0)
                    if last_trade_cycle is None or c > last_trade_cycle:
                        last_trade_cycle = c
                except (TypeError, ValueError):
                    pass

    # zero-composite streak from the tail of metrics
    zero_streak = 0
    for r in reversed(rows):
        comp = r.get("composite_score")
        if comp is None or comp == 0 or comp == 0.0:
            zero_streak += 1
        else:
            break

    log_mt = _log_mtime(version)
    return {
        "pid": pid,
        "version": version,
        "alive": _is_alive(pid),
        "cycle": cycle,
        "trades": trades,
        "pnl": round(pnl, 2),
        "last_trade_cycle": last_trade_cycle,
        "zero_composite_streak": zero_streak,
        "log_mtime": log_mt,
        "last_log_update": (
            datetime.fromtimestamp(log_mt, timezone.utc).isoformat() if log_mt else None
        ),
    }


def _emit_event(kind: str, state: dict, extra: dict | None = None) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now_iso(), "kind": kind, "state": state}
    if extra:
        rec.update(extra)
    with open(EVENTS_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _write_health(state: dict, status: str, reason: str, restarts: int, started_at: float) -> None:
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["status"] = status
    payload["reason"] = reason
    payload["restarts"] = restarts
    payload["uptime_hours"] = round((time.time() - started_at) / 3600.0, 2)
    payload["checked_at"] = _now_iso()
    with open(HEALTH_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def _relaunch(cmd: str, log) -> int | None:
    """Relaunch via shell so env-var prefixes work. Returns new PID or None."""
    log(f"relaunch: {cmd}")
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            executable="/bin/zsh",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid
    except Exception as exc:
        log(f"relaunch failed: {exc}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--sleep-interval", type=float, default=900.0,
                    help="training cycle sleep in seconds (default 900)")
    ap.add_argument("--check-interval", type=float, default=1800.0,
                    help="how often to check (seconds, default 1800)")
    ap.add_argument("--relaunch-cmd", default="",
                    help="shell command to relaunch on STUCK/FROZEN/EMPTY_COMPOSITE")
    ap.add_argument("--max-restarts-24h", type=int, default=3)
    args = ap.parse_args()

    def log(msg: str) -> None:
        print(f"[{_now_iso()}] {msg}", flush=True)

    pid = args.pid
    started_at = time.time()
    restart_history: list[float] = []

    log(f"monitor start: pid={pid} version={args.version} "
        f"sleep_interval={args.sleep_interval}s check_interval={args.check_interval}s "
        f"relaunch_enabled={bool(args.relaunch_cmd)}")

    while True:
        state = _gather_state(pid, args.version)
        status, reason = _classify(state, args.sleep_interval)
        # prune restart history to last 24h
        cutoff = time.time() - 86400
        restart_history = [t for t in restart_history if t >= cutoff]
        _write_health(state, status, reason, len(restart_history), started_at)
        log(f"check: status={status} cycle={state['cycle']} trades={state['trades']} "
            f"pnl={state['pnl']:+.0f} zero_streak={state['zero_composite_streak']} "
            f"reason='{reason}'")

        if status in ("STUCK", "FROZEN", "EMPTY_COMPOSITE", "DEAD"):
            _emit_event(status, state, {"reason": reason})
            if not args.relaunch_cmd:
                log(f"failure detected ({status}) but no --relaunch-cmd; halting")
                return 0
            if len(restart_history) >= args.max_restarts_24h:
                _emit_event("RESTART_BUDGET_EXHAUSTED", state,
                            {"restarts_in_24h": len(restart_history)})
                log(f"halt: {len(restart_history)} restarts in 24h >= max {args.max_restarts_24h}")
                return 1
            _kill(pid, log)
            new_pid = _relaunch(args.relaunch_cmd, log)
            if new_pid is None:
                log("relaunch failed — halting")
                return 1
            restart_history.append(time.time())
            pid = new_pid
            _emit_event("RELAUNCHED", state, {"new_pid": new_pid})
            log(f"new pid={new_pid}")
        time.sleep(args.check_interval)


if __name__ == "__main__":
    sys.exit(main())
