"""
omega.__main__
~~~~~~~~~~~~~~
CLI entry point.  Run with:  python -m omega [command] [options]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omega",
        description="Omega — Autonomous Multi-Node Intelligence Framework",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to YAML config file (default: omega.yml or omega.example.yml)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Start the Omega orchestrator")
    run_p.add_argument(
        "--mode",
        choices=["pico", "supervised", "autonomous"],
        default="pico",
        help="Autonomy mode (default: pico)",
    )
    run_p.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated list of symbols, e.g. BTCUSDT,ETHUSDT",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Initialise subsystems but do not trade / modify state",
    )
    run_p.add_argument(
        "--heartbeat",
        type=int,
        default=None,
        help="Heartbeat interval in seconds (overrides config)",
    )
    run_p.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Max heartbeat iterations (default: run forever)",
    )

    # ── backtest ─────────────────────────────────────────────────────────────
    bt_p = sub.add_parser("backtest", help="Run strategy on historical data")
    bt_p.add_argument("--start-date", required=True, metavar="YYYY-MM-DD")
    bt_p.add_argument("--end-date", required=True, metavar="YYYY-MM-DD")
    bt_p.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols (default: from config)",
    )
    bt_p.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Save JSON report to this path",
    )
    bt_p.add_argument(
        "--compare",
        action="store_true",
        help="Compare PICO baseline vs full Omega strategy",
    )

    # ── status ───────────────────────────────────────────────────────────────
    st_p = sub.add_parser("status", help="Show system state from StateStore")
    st_p.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Path to state DB (default: from config)",
    )
    st_p.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print status as JSON",
    )

    # ── run-project ──────────────────────────────────────────────────────────
    rp_p = sub.add_parser(
        "run-project",
        help="Load a YAML project config and orchestrate its nodes",
    )
    rp_p.add_argument(
        "project",
        metavar="NAME_OR_PATH",
        help=(
            "Project name (e.g. 'victoria') or path to a YAML file (e.g. 'projects/victoria.yaml')"
        ),
    )
    rp_p.add_argument(
        "--heartbeat",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Seconds between cycles (default: 60)",
    )
    rp_p.add_argument(
        "--cycles",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N cycles (default: run forever)",
    )
    rp_p.add_argument(
        "--reload-interval",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Seconds between YAML hot-reload checks (0 = disable, default: 10)",
    )
    rp_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the project config without executing any nodes",
    )

    # ── baseline ─────────────────────────────────────────────────────────────
    bl_p = sub.add_parser("baseline", help="Run PICO baseline tests")
    bl_p.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols for baseline evaluation",
    )
    bl_p.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Save baseline JSON report to this path",
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_run_project(args: argparse.Namespace) -> int:
    from omega.core.project_runner import ProjectRunner

    runner = ProjectRunner(
        path_or_name=args.project,
        heartbeat=args.heartbeat,
        max_cycles=args.cycles,
        reload_interval=args.reload_interval,
        dry_run=args.dry_run,
    )
    return runner.run()


def _cmd_run(args: argparse.Namespace) -> int:
    from omega.runner import OmegaRunner

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    runner = OmegaRunner(
        config_path=args.config,
        mode=args.mode,
        symbols=symbols,
        dry_run=args.dry_run,
        heartbeat_override=args.heartbeat,
        max_iterations=args.iterations,
    )
    return runner.run()


def _cmd_backtest(args: argparse.Namespace) -> int:
    from omega.backtest import BacktestEngine
    from omega.core.config import OmegaConfig

    cfg = OmegaConfig.load(args.config)
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else cfg.data.symbols

    engine = BacktestEngine(config=cfg, symbols=symbols)
    report = engine.run(
        start_date=args.start_date,
        end_date=args.end_date,
        compare_pico=args.compare,
    )

    _print_backtest_report(report)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"\nReport saved → {out}")

    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from omega.core.state_store import make_state_backend

    store = make_state_backend()
    status = _collect_status(store)

    if args.output_json:
        print(json.dumps(status, indent=2))
    else:
        _print_status(status)

    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    import datetime

    from omega.backtest import BacktestEngine
    from omega.core.config import OmegaConfig

    cfg = OmegaConfig.load(args.config)
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else cfg.data.symbols

    end = datetime.date.today()
    start = end - datetime.timedelta(days=90)

    engine = BacktestEngine(config=cfg, symbols=symbols)
    report = engine.run(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        compare_pico=True,
        pico_only=True,
    )

    _print_backtest_report(report)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"\nBaseline report saved → {out}")

    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_status(store: Any) -> dict:
    """Pull node states and recent performance from StateStore."""
    try:
        nodes = store.list_nodes()
    except Exception:
        nodes = []

    node_data = []
    for n in nodes:
        node_data.append(
            {
                "node_id": n.get("node_id", "?"),
                "name": n.get("name", "?"),
                "health": n.get("health", 0.0),
                "status": n.get("status", "unknown"),
                "last_updated": n.get("last_updated", 0),
            }
        )

    try:
        recent_execs = store.list_executions(limit=20)
    except Exception:
        recent_execs = []

    successes = sum(1 for e in recent_execs if e.get("success", 0))
    total = len(recent_execs)

    return {
        "nodes": node_data,
        "recent_executions": total,
        "recent_success_rate": round(successes / total, 3) if total else None,
    }


def _print_status(status: dict) -> None:
    nodes = status.get("nodes", [])
    print(f"\n{'─' * 60}")
    print(f"  Omega System Status  ({len(nodes)} nodes)")
    print(f"{'─' * 60}")
    for n in nodes:
        health_bar = "█" * int(n["health"] * 10) + "░" * (10 - int(n["health"] * 10))
        print(f"  {n['name']:<30} [{health_bar}] {n['health']:.2f}  {n['status']}")
    if not nodes:
        print("  (no nodes registered)")
    execs = status.get("recent_executions", 0)
    sr = status.get("recent_success_rate")
    print(f"\n  Recent executions: {execs}  success rate: {sr if sr is not None else 'N/A'}")
    print(f"{'─' * 60}\n")


def _print_backtest_report(report: dict) -> None:
    print(f"\n{'═' * 60}")
    print("  Backtest Report")
    print(f"{'═' * 60}")
    for key, val in report.items():
        if isinstance(val, dict):
            print(f"\n  [{key}]")
            for k2, v2 in val.items():
                print(f"    {k2:<28} {v2}")
        else:
            print(f"  {key:<30} {val}")
    print(f"{'═' * 60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure basic logging early; runner/config may override.
    level = args.log_level or "INFO"
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    dispatch = {
        "run": _cmd_run,
        "run-project": _cmd_run_project,
        "backtest": _cmd_backtest,
        "status": _cmd_status,
        "baseline": _cmd_baseline,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        logging.getLogger("omega").error("Fatal error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
