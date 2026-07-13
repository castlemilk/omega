#!/usr/bin/env python3
"""
V252 — headless live-paper daemon driver (scheduler + crash-safe checkpoint).

Composes ``omega.live_paper`` scheduler + checkpoint + a cycle function into a
loop that runs one cycle per UTC day and survives kill/restart via the atomic
checkpoint. Pure runner-layer — imports no strategy module and places no orders.

Modes (``--mode``):
  fixture       Deterministic cycle (burn-in / restart proof). Default — the
                7-day burn-in and crash-recovery run here with zero network.
  forward       Real V250 live feeds → PaperTradingEngine mark-to-market. The
                V253 soak path; requires host egress to Binance. Non-deterministic.

Master gate: refuses to loop unless ``SCHEDULER_ENABLED`` is truthy (default OFF).
Pass ``--allow-disabled`` only for the smoke/burn-in harness.

Usage (headless):
  SCHEDULER_ENABLED=1 OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data \
    python3 scripts/live_paper_daemon.py --mode forward
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omega.live_paper.checkpoint import Checkpoint  # noqa: E402
from omega.live_paper.config import LivePaperConfig, SchedulerConfig, checkpoint_dir  # noqa: E402
from omega.live_paper.runner import (  # noqa: E402
    LivePaperRunner,
    make_fixture_cycle,
    make_forward_cycle,
)
from omega.live_paper.scheduler import DailyScheduler  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V252 live-paper daemon")
    ap.add_argument("--mode", choices=("fixture", "forward"), default="fixture")
    ap.add_argument("--max-cycles", type=int, default=None, help="Bound the loop (burn-in/test); default unbounded")
    ap.add_argument("--allow-disabled", action="store_true",
                    help="Run even when SCHEDULER_ENABLED is off (burn-in/smoke only)")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    log = logging.getLogger("live_paper_daemon")

    sched_cfg = SchedulerConfig.from_env()
    if not sched_cfg.enabled and not args.allow_disabled:
        log.error("SCHEDULER_ENABLED is off (default). Refusing to run. "
                  "Set SCHEDULER_ENABLED=1 (V253) or pass --allow-disabled for burn-in.")
        return 3

    lp_cfg = LivePaperConfig()
    ck_dir = checkpoint_dir(lp_cfg)
    checkpoint = Checkpoint(ck_dir, keep_days=sched_cfg.checkpoint_keep_days)
    scheduler = DailyScheduler(sched_cfg)
    pnl_log = lp_cfg.log_dir / "pnl_curve.jsonl"

    if args.mode == "forward":
        cycle_fn = make_forward_cycle(lp_cfg)
    else:
        cycle_fn = make_fixture_cycle()

    log.info("V252 daemon: mode=%s tick=%s UTC checkpoint=%s pnl_log=%s enabled=%s",
             args.mode, sched_cfg.tick_utc, ck_dir, pnl_log, sched_cfg.enabled)

    runner = LivePaperRunner(
        scheduler, checkpoint, cycle_fn,
        initial_capital=lp_cfg.initial_capital,
        pnl_log_path=pnl_log,
    )
    completed = runner.run(max_cycles=args.max_cycles)
    log.info("V252 daemon exit: %d cycles completed", completed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
