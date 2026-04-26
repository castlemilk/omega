#!/usr/bin/env python3
"""Append a one-line health snapshot of v163_live to data/v163_live_monitor.jsonl.

Reads /tmp/v163_live_metrics.jsonl and emits:
  - cycles completed, wall-clock elapsed
  - PnL, trade count, win rate
  - regime distribution
  - signal-freeze check: stdev of TDA/W2 signals (the bug we fixed should keep these >0)
"""
from __future__ import annotations
import json, os, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

_VERSION = os.environ.get("V_LIVE_VERSION", "v163_live")
_METRICS_DIR = os.environ.get("OMEGA_METRICS_DIR", "/tmp")
METRICS = Path(f"{_METRICS_DIR}/{_VERSION}_metrics.jsonl")
OUT = Path(f"data/{_VERSION}_monitor.jsonl")
_TRADES_CSV = Path(f"data/{_VERSION}_trades.csv")


def _stdev(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    return statistics.pstdev(xs)


def main() -> int:
    if not METRICS.exists():
        snap = {"ts": datetime.now(timezone.utc).isoformat(), "status": "no_metrics_yet"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "a") as f:
            f.write(json.dumps(snap) + "\n")
        print(json.dumps(snap))
        return 0

    rows = []
    with open(METRICS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    if not rows:
        return 0

    first_ts = rows[0].get("timestamp") or rows[0].get("ts")
    last_ts = rows[-1].get("timestamp") or rows[-1].get("ts")

    closed_trades = int(rows[-1].get("total_closed") or 0)
    # PnL not in metrics — read from trades CSV if present
    closed_pnl = 0.0
    win_rate = 0.0
    trades_csv = _TRADES_CSV
    if trades_csv.exists():
        import csv
        with open(trades_csv) as f:
            reader = csv.DictReader(f)
            pnls = [float(r.get("pnl") or 0) for r in reader]
        if pnls:
            closed_pnl = sum(pnls)
            win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

    regimes: dict[str, int] = {}
    for r in rows:
        rg = r.get("regime") or r.get("_regime") or "unknown"
        regimes[rg] = regimes.get(rg, 0) + 1
    regime_transitions = sum(1 for r in rows if r.get("regime_transition"))

    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cycles": len(rows),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "closed_pnl": round(float(closed_pnl), 2),
        "closed_trades": int(closed_trades),
        "win_rate": round(float(win_rate), 4),
        "regimes": regimes,
        "regime_transitions": regime_transitions,
        "signal_stdev": {
            "w2_trend": round(_stdev([r.get("w2_trend") for r in rows]), 6),
            "w2_crisis": round(_stdev([r.get("w2_crisis") for r in rows]), 6),
            "w2_normal": round(_stdev([r.get("w2_normal") for r in rows]), 6),
            "tda_betti0": round(_stdev([r.get("tda_betti0") for r in rows]), 6),
            "tda_fragmentation": round(_stdev([r.get("tda_fragmentation") for r in rows]), 6),
            "tda_pers_entropy": round(_stdev([r.get("tda_pers_entropy") for r in rows]), 6),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(snap) + "\n")
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
