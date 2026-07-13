#!/usr/bin/env python3
"""
V252 smoke Test C — reconciliation preservation through the daemon path.

Replays V251's three sentinel windows (one per regime) through the SAME runner
loop the daemon uses (scheduler tick → retrospective cycle → checkpoint → PnL
log), and asserts each window reproduces V251's recorded per-window PnL EXACTLY:

    snap_wf_20240310  crisis  $1,149.76
    snap_wf_20230912  trend   $4,679.67
    snap_wf_20250305  recent  $  771.98

The retrospective cycle shells out to the unchanged ``run_training.py
--backtest-snapshot`` eval (PYTHONHASHSEED=42, --seed 42, --frozen-cache,
committed frozen state restored first — byte-for-byte V251's invocation), so a
match proves that wrapping the eval in the V252 scheduler+checkpoint runner does
not perturb a single trade. Any mismatch = REFUTED (backtest byte-identity
broken), do NOT merge.

Usage:
  export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
  python3 scripts/v252_reconcile_smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omega.live_paper.checkpoint import Checkpoint  # noqa: E402
from omega.live_paper.config import SchedulerConfig  # noqa: E402
from omega.live_paper.runner import LivePaperRunner, make_retrospective_cycle  # noqa: E402
from omega.live_paper.scheduler import DailyScheduler  # noqa: E402

# The standing V240-selective baseline config (identical to scripts/v251_layer2.sh).
SELECTIVE = json.dumps({
    "crisis_skew_enabled": True,
    "crisis_skew_regime_gate_enabled": True,
    "crisis_skew_drawdown_threshold": 0.12,
    "rv_term_brake_enabled": False,
    "ic_seed_weighting": False,
    "crisis_term_predemean_enabled": False,
    "crisis_size_throttle_enabled": False,
    "universe_selective_enabled": True,
})

# (window id, regime, cycles, V251-recorded PnL)
SENTINELS = [
    ("snap_wf_20240310", "crisis", 60, 1149.76),
    ("snap_wf_20230912", "trend", 60, 4679.67),
    ("snap_wf_20250305", "recent", 60, 771.98),
]
TOL = 0.01  # V251 recorded arm-Δ of $0.00; require an exact (to the cent) match.


class _ImmediateClock:
    """Fires the scheduler's first tick right away; fake sleep = zero wall-clock."""

    def __init__(self, target: datetime) -> None:
        # Start one second before the tick so sleep_until returns almost at once.
        self._now = target - timedelta(seconds=1)

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def replay_window(wid: str, cycles: int, cycle_date: date, tmp: Path) -> dict:
    """Drive ONE sentinel through the full daemon runner path; return its PnL line."""
    snapshot = ROOT / "data" / "snapshots" / "walk_forward" / f"{wid}.json"
    cfg = SchedulerConfig(tick_utc="04:05:00", max_sleep_chunk_seconds=1.0)
    target = datetime.combine(cycle_date, datetime.min.time(), tzinfo=UTC).replace(hour=4, minute=5)
    clock = _ImmediateClock(target)
    sched = DailyScheduler(cfg, now_fn=clock.now, sleep_fn=clock.sleep, log_sink=lambda r: None)
    ckpt = Checkpoint(tmp / wid / "checkpoint", keep_days=14)
    cycle_fn = make_retrospective_cycle(
        window_snapshot=snapshot, cycles=cycles, features_json=SELECTIVE, repo_root=ROOT,
    )
    runner = LivePaperRunner(
        sched, ckpt, cycle_fn, pnl_log_path=tmp / wid / "logs" / "pnl_curve.jsonl",
        install_signals=False,
    )
    runner.run(max_cycles=1)
    pnl_lines = [json.loads(ln) for ln in (tmp / wid / "logs" / "pnl_curve.jsonl").read_text().splitlines() if ln.strip()]
    assert len(pnl_lines) == 1, pnl_lines
    return pnl_lines[0]


def main() -> int:
    print("=== V252 Test C — reconciliation preservation through the daemon path ===")
    rows = []
    all_pass = True
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for wid, regime, cycles, expected in SENTINELS:
            # Use the window's own frozen date as the cycle date (cosmetic; the eval
            # is driven by the snapshot, not the tick date).
            d = date.fromisoformat(f"{wid[-8:-4]}-{wid[-4:-2]}-{wid[-2:]}")
            line = replay_window(wid, cycles, d, tmp)
            got = float(line["window_pnl"])
            ok = abs(got - expected) <= TOL
            all_pass = all_pass and ok
            rows.append({
                "window": wid, "regime": regime,
                "v251_pnl": expected, "daemon_path_pnl": got,
                "delta": round(got - expected, 4), "n_closed": line.get("n_closed"),
                "match": ok,
            })
            print(f"  {wid} [{regime:6s}] V251={expected:>9.2f}  daemon={got:>9.2f}  "
                  f"Δ={got - expected:+.4f}  {'MATCH' if ok else 'MISMATCH'}")
    print()
    print(json.dumps({"verdict": "PASS" if all_pass else "REFUTED", "rows": rows}, indent=1))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
