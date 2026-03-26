#!/usr/bin/env python3
"""
scripts/run_training_v4.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
500-cycle V4 training run — full stack:
  - CoinGecko API key (no rate limiting)
  - pgx OTel tracing
  - Regime-aware signal weights (HMM regime detector)
  - Conviction filters (agreement ratio threshold)
  - Honest PnL accounting (randomized exits, real entry prices)
  - 16+ signals: FRED macro, options GEX, liquidation filter, stablecoin flows, etc.
  - Memory + reasoning system
  - Kelly position sizing

Usage:
    python scripts/run_training_v4.py
    python scripts/run_training_v4.py --cycles 500
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── load .env ────────────────────────────────────────────────────────────────
def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env()

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
_handler = logging.StreamHandler(sys.stdout)
_handler.setLevel(logging.INFO)
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
log = logging.getLogger("v4")
log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False

# ── data dirs ────────────────────────────────────────────────────────────────
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = DATA_DIR / "training_progress.json"
TRADES_CSV = DATA_DIR / "v4_trades.csv"


def _init_trades_csv() -> None:
    with open(TRADES_CSV, "w", newline="") as f:
        csv.writer(f).writerow(
            [
                "snapshot_cycle",
                "timestamp",
                "symbol",
                "side",
                "size",
                "entry_price",
                "exit_price",
                "pnl",
                "slippage",
                "hold_cycles",
                "conviction",
                "regime",
            ]
        )


def _win_rate(trades: list[dict]) -> float:
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
    return len(wins) / len(trades) if trades else 0.0


def _total_pnl(trades: list[dict]) -> float:
    return sum(float(t.get("pnl", 0.0)) for t in trades)


def run(n_cycles: int = 500, log_interval: int = 10) -> dict:
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode

    log.info("=" * 65)
    log.info("V4 Training Run — %d cycles", n_cycles)
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""
    log.info("CoinGecko key : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    db_url = os.environ.get("DATABASE_URL", "")
    log.info("Database URL  : %s", db_url[:30] + "..." if db_url else "NOT SET (in-memory only)")
    log.info("=" * 65)

    victoria = VictoriaNode()
    orch = OmegaOrchestrator(name="v4_training")
    orch.register_node(victoria)

    engine = PaperTradingEngine(initial_capital=100_000.0, db_url=db_url or None)
    orch.set_paper_trading(engine)

    _init_trades_csv()
    progress: list[dict] = []
    last_closed_count = 0
    total_start = time.perf_counter()

    # ── Run the full orchestrator in a background thread so we can
    # checkpoint progress every log_interval cycles ─────────────────────────
    import contextlib
    import threading

    run_done = threading.Event()
    run_exc: list[Exception] = []

    def _run_bg() -> None:
        try:
            orch.run(max_cycles=n_cycles, sleep_seconds=0.0)
        except Exception as exc:
            run_exc.append(exc)
        finally:
            run_done.set()

    bg = threading.Thread(target=_run_bg, daemon=True)
    bg.start()

    # ── Progress monitoring loop ──────────────────────────────────────────────
    last_logged_cycle = 0
    while not run_done.is_set() or orch._cycle_number < n_cycles:
        current_cycle = orch._cycle_number
        if run_done.is_set():
            current_cycle = n_cycles  # final flush

        # Log every log_interval new cycles
        if current_cycle > last_logged_cycle and (
            current_cycle % log_interval == 0 or current_cycle == n_cycles or current_cycle == 1
        ):
            closed = engine.closed_trades
            open_pos = engine.open_trades

            pnl = _total_pnl(closed)
            wr = _win_rate(closed)

            regime = "unknown"
            with contextlib.suppress(Exception):
                regime = victoria._regime_detector.current_regime

            signals_active = len(getattr(victoria, "_last_signals", {}))
            signals_active = sum(
                1 for k in getattr(victoria, "_last_signals", {}) if not k.startswith("_")
            )

            mem_count = 0
            with contextlib.suppress(Exception):
                mem_count = len(
                    getattr(getattr(victoria, "_episodic_memory", None), "_episodes", [])
                )

            elapsed = time.perf_counter() - total_start
            avg_cycle_s = elapsed / max(current_cycle, 1)
            eta = avg_cycle_s * (n_cycles - current_cycle)

            checkpoint = {
                "cycle": current_cycle,
                "timestamp": datetime.now(UTC).isoformat(),
                "trades_open": len(open_pos),
                "trades_closed": len(closed),
                "total_pnl": round(pnl, 2),
                "win_rate": round(wr, 4),
                "memories": mem_count,
                "signals_active": signals_active,
                "regime_detected": regime,
                "avg_cycle_time_s": round(avg_cycle_s, 3),
                "elapsed_s": round(elapsed, 1),
            }
            progress.append(checkpoint)
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, indent=2)

            # Append new closed trades to CSV
            new_closed = closed[last_closed_count:]
            if new_closed:
                with open(TRADES_CSV, "a", newline="") as f:
                    w = csv.writer(f)
                    for t in new_closed:
                        w.writerow(
                            [
                                current_cycle,
                                datetime.now(UTC).isoformat(),
                                t.get("sym", t.get("symbol", "")),
                                t.get("side", ""),
                                round(float(t.get("size", 0.0)), 4),
                                round(float(t.get("entry", t.get("entry_price", 0.0))), 4),
                                round(float(t.get("exit_price") or 0.0), 4),
                                round(float(t.get("pnl", 0.0)), 4),
                                round(float(t.get("slippage", 0.0)), 6),
                                t.get("hold_cycles", t.get("age_cycles", 0)),
                                t.get("conviction", ""),
                                regime,
                            ]
                        )
                last_closed_count = len(closed)

            log.info(
                "Cycle %4d/%d | %-8s | sig=%2d mem=%3d | "
                "open=%3d closed=%4d | PnL=$%+.0f wr=%.0f%% | "
                "%.1fs/c ETA %.0fs",
                current_cycle,
                n_cycles,
                regime,
                signals_active,
                mem_count,
                len(open_pos),
                len(closed),
                pnl,
                wr * 100,
                avg_cycle_s,
                eta,
            )
            last_logged_cycle = current_cycle

        if run_done.is_set():
            break
        time.sleep(0.5)

    bg.join(timeout=30)

    if run_exc:
        log.error("Run failed: %s", run_exc[0])

    # ── Final results ─────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start
    closed_final = engine.closed_trades
    open_final = engine.open_trades

    longs = [t for t in closed_final if t.get("side") == "long"]
    shorts = [t for t in closed_final if t.get("side") == "short"]
    wins = [t for t in closed_final if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed_final if float(t.get("pnl", 0.0)) < 0]

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Per-symbol breakdown
    sym_map: dict[str, dict] = {}
    for t in closed_final:
        sym = t.get("sym") or t.get("symbol") or "unknown"
        if sym not in sym_map:
            sym_map[sym] = {"trades": 0, "longs": 0, "shorts": 0, "pnl": 0.0, "wins": 0}
        pnl_t = float(t.get("pnl", 0.0))
        sym_map[sym]["trades"] += 1
        sym_map[sym]["pnl"] += pnl_t
        if t.get("side") == "long":
            sym_map[sym]["longs"] += 1
        else:
            sym_map[sym]["shorts"] += 1
        if pnl_t > 0:
            sym_map[sym]["wins"] += 1

    results = {
        "v4_run": {
            "date": datetime.now(UTC).isoformat(),
            "cycles": n_cycles,
            "elapsed_s": round(total_elapsed, 1),
            "avg_cycle_s": round(total_elapsed / n_cycles, 3),
            "cg_key_used": bool(cg_key),
            "db_url_used": bool(db_url),
        },
        "trades": {
            "total_closed": len(closed_final),
            "long_trades": len(longs),
            "short_trades": len(shorts),
            "open_positions": len(open_final),
            "win_rate": round(_win_rate(closed_final), 4),
            "total_pnl_usd": round(_total_pnl(closed_final), 2),
            "realised_pnl_engine": round(engine.realised_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        },
        "per_symbol": {
            sym: {
                "trades": d["trades"],
                "longs": d["longs"],
                "shorts": d["shorts"],
                "pnl": round(d["pnl"], 2),
                "win_rate": round(d["wins"] / d["trades"], 3) if d["trades"] else 0.0,
            }
            for sym, d in sorted(sym_map.items(), key=lambda x: -abs(x[1]["pnl"]))
        },
    }

    results_file = DATA_DIR / "v4_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    log.info("")
    log.info("=" * 65)
    log.info(
        "V4 COMPLETE — %d cycles in %.0fs (%.2fs/cycle)",
        n_cycles,
        total_elapsed,
        total_elapsed / n_cycles,
    )
    log.info("=" * 65)
    log.info(
        "Closed trades   : %d  (long=%d short=%d)", len(closed_final), len(longs), len(shorts)
    )
    log.info("Open positions  : %d", len(open_final))
    log.info("Total PnL       : $%+.2f", _total_pnl(closed_final))
    log.info(
        "Win rate        : %.1f%%  (%d/%d)",
        _win_rate(closed_final) * 100,
        len(wins),
        len(closed_final),
    )
    log.info("Profit factor   : %.2f", profit_factor)
    log.info("")
    log.info("Per-symbol PnL:")
    per_sym: dict = results["per_symbol"]  # type: ignore[assignment]
    for sym, d in per_sym.items():
        log.info(
            "  %-12s  PnL=$%+8.2f  trades=%3d  win=%.0f%%",
            sym,
            d["pnl"],
            d["trades"],
            d["win_rate"] * 100,
        )
    log.info("")
    log.info("Files saved:")
    log.info("  Progress : %s", PROGRESS_FILE)
    log.info("  Trades   : %s", TRADES_CSV)
    log.info("  Results  : %s", results_file)
    log.info("=" * 65)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V4 500-cycle training run")
    parser.add_argument("--cycles", type=int, default=500)
    parser.add_argument("--log-interval", type=int, default=10)
    args = parser.parse_args()
    run(n_cycles=args.cycles, log_interval=args.log_interval)
