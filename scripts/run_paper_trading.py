"""
scripts/run_paper_trading.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs N paper trading cycles with the enhanced signal suite (v2) and prints
a JSON summary.  Designed to be run from the repo root:

    python scripts/run_paper_trading.py --cycles 200

The script deliberately uses 0-second sleep between cycles so that all cycles
complete quickly — the DataIngestionNode and signal providers have internal
5-minute TTL caches, so only the first few cycles hit external APIs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ── Ensure repo root is on the import path ───────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.WARNING,  # suppress per-cycle INFO noise; errors still visible
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("paper_trading_run")


def run(num_cycles: int = 200) -> dict:
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode

    orch = OmegaOrchestrator(name="paper_trading_v2")

    node = VictoriaNode()
    orch.register_node(node)

    engine = PaperTradingEngine(initial_capital=100_000.0)
    orch.set_paper_trading(engine)

    logger.warning("Starting %d paper trading cycles (v2 signal suite)...", num_cycles)

    history = orch.run(max_cycles=num_cycles, sleep_seconds=0.0)

    # ── Collect results ───────────────────────────────────────────────────────
    closed = engine.closed_trades
    positions = engine.positions

    longs = [t for t in closed if t.get("side") == "long"]
    shorts = [t for t in closed if t.get("side") == "short"]

    def _pnl(trade: dict) -> float:
        return float(trade.get("pnl", 0.0) or trade.get("realized_pnl", 0.0))

    total_pnl = sum(_pnl(t) for t in closed)
    long_pnl = sum(_pnl(t) for t in longs)
    short_pnl = sum(_pnl(t) for t in shorts)

    wins = [t for t in closed if _pnl(t) > 0]
    losses = [t for t in closed if _pnl(t) < 0]
    win_rate = len(wins) / len(closed) if closed else 0.0

    # Per-symbol breakdown
    sym_map: dict[str, dict] = {}
    for t in closed:
        sym = t.get("sym") or t.get("symbol") or "unknown"
        if sym not in sym_map:
            sym_map[sym] = {"trades": 0, "longs": 0, "shorts": 0, "pnl": 0.0, "wins": 0}
        sym_map[sym]["trades"] += 1
        sym_map[sym]["pnl"] += _pnl(t)
        if t.get("side") == "long":
            sym_map[sym]["longs"] += 1
        else:
            sym_map[sym]["shorts"] += 1
        if _pnl(t) > 0:
            sym_map[sym]["wins"] += 1

    # Cycle stats
    errors = sum(r.error_count for r in history._window)
    total_cycles = len(history._window)

    summary = {
        "cycles_run": total_cycles,
        "total_trades": len(closed),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "win_rate": round(win_rate, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "long_pnl_usd": round(long_pnl, 2),
        "short_pnl_usd": round(short_pnl, 2),
        "realised_pnl_engine": round(engine.realised_pnl, 2),
        "open_positions": len(positions),
        "cycle_errors": errors,
        "per_symbol": {
            sym: {
                "trades": d["trades"],
                "longs": d["longs"],
                "shorts": d["shorts"],
                "pnl": round(d["pnl"], 2),
                "win_rate": round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0,
            }
            for sym, d in sorted(sym_map.items(), key=lambda x: -abs(x[1]["pnl"]))
        },
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paper trading cycles (v2)")
    parser.add_argument("--cycles", type=int, default=200, help="Number of cycles to run")
    parser.add_argument("--output", default=None, help="JSON output path (optional)")
    args = parser.parse_args()

    result = run(args.cycles)

    print(json.dumps(result, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"\nResults saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
