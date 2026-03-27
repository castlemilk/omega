#!/usr/bin/env python3
"""
scripts/run_v13.py
~~~~~~~~~~~~~~~~~~
V13 training run — 3 critical fixes applied:
  - Fix 1: Meta-model regularization (n_estimators=50, min_samples_leaf=10,
            max_features='sqrt') + IC weight decay to prevent OOS Sharpe blowout
  - Fix 2: Semantic memory SQLite fallback so patterns flush to DB
  - Fix 3: IMPROVEMENT_INTERVAL=10 + auto-register scheduler so improve() fires

Usage:
    python scripts/run_v13.py
    python scripts/run_v13.py --cycles 50 --sleep 30
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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

LOG_FILE = "/tmp/v13_training.log"
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
_handler = logging.StreamHandler(sys.stdout)
_handler.setLevel(logging.INFO)
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
_fhandler = logging.FileHandler(LOG_FILE, mode="w")
_fhandler.setLevel(logging.INFO)
_fhandler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S"))
log = logging.getLogger("v13")
log.addHandler(_handler)
log.addHandler(_fhandler)
log.setLevel(logging.INFO)
log.propagate = False

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = DATA_DIR / "v13_progress.json"
TRADES_CSV = DATA_DIR / "v13_trades.csv"
RESULTS_FILE = DATA_DIR / "v13_results.json"

MAX_STALE_MINUTES = 5.0


def _win_rate(trades: list[dict]) -> float:
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
    return len(wins) / len(trades) if trades else 0.0


def _total_pnl(trades: list[dict]) -> float:
    return sum(float(t.get("pnl", 0.0)) for t in trades)


def _init_trades_csv() -> None:
    with open(TRADES_CSV, "w", newline="") as f:
        csv.writer(f).writerow([
            "cycle", "timestamp", "symbol", "side", "size",
            "entry_price", "exit_price", "pnl", "slippage",
            "hold_cycles", "conviction", "regime", "sit_out_reason",
        ])


def _get_data_freshness(victoria) -> float:
    try:
        di = victoria._data_ingestion
        return di._data_freshness_minutes()
    except Exception:
        return 0.0


def _get_regime(victoria) -> str:
    try:
        return victoria._regime_detector.current_regime
    except Exception:
        return "unknown"


def _query_semantic_count() -> int:
    """Count rows in semantic_memories SQLite table."""
    import sqlite3
    db_path = str(DATA_DIR / "omega_victoria_memory.db")
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM semantic_memories").fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def run(n_cycles: int = 50, sleep_seconds: float = 30.0, log_interval: int = 5) -> dict:
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode
    from omega.nodes.shared.semantic_memory import SemanticMemoryNode

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    log.info("=" * 70)
    log.info("V13 Training Run — %d cycles  sleep=%.0fs", n_cycles, sleep_seconds)
    log.info("FIXES: meta-model regularization | semantic SQLite flush | IMPROVEMENT_INTERVAL=10")
    log.info("CoinGecko key  : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    log.info("Database URL   : %s", db_url[:40] + "..." if db_url else "NOT SET — SQLite fallback")
    log.info("Log file       : %s", LOG_FILE)
    log.info("=" * 70)

    from omega.core.improvement_engine import SyntheticEvaluator

    victoria = VictoriaNode()
    orch = OmegaOrchestrator(name="v13_training")
    orch.register_node(victoria)

    # Inject SyntheticEvaluator so improvement engine fires (default is NullEvaluator)
    orch._improvement_engine.set_evaluator(SyntheticEvaluator())
    log.info("ImprovementEngine: SyntheticEvaluator injected")

    # Register SemanticMemoryNode so it runs during consolidation
    sem_node = SemanticMemoryNode(review_interval=10)
    orch.register_node(sem_node, activate=False)

    engine = PaperTradingEngine(initial_capital=100_000.0, db_url=db_url or None)
    orch.set_paper_trading(engine)

    _init_trades_csv()

    progress: list[dict] = []
    sit_out_counts: dict[str, int] = {
        "stale_data": 0, "vol_low": 0, "vol_high": 0,
        "regime_uncertain": 0, "normal": 0,
    }
    last_closed_count = 0
    improve_calls = 0
    total_start = time.perf_counter()
    strat = getattr(victoria, "_strategy", None)

    for i in range(n_cycles):
        cycle_start = time.perf_counter()
        result = orch.run_one_cycle()
        cycle_elapsed = time.perf_counter() - cycle_start

        if result.improvement_proposed:
            improve_calls += 1

        # Run semantic memory consolidation every 10 cycles
        if (i + 1) % 10 == 0:
            try:
                from omega.core.node import NodeInput
                sem_inp = NodeInput(
                    action="build_semantic",
                    context={"cycle": i + 1},
                    parameters={"cycle": i + 1, "force": False},
                )
                sem_out = sem_node.execute(sem_inp)
                if sem_out.success and sem_out.result:
                    stored = sem_out.result.get("patterns_extracted", 0)
                    if stored > 0:
                        log.info("Cycle %d: SemanticMemoryNode stored %d patterns", i + 1, stored)
            except Exception as exc:
                log.warning("SemanticMemoryNode error: %s", exc)

        regime = _get_regime(victoria)
        freshness_min = _get_data_freshness(victoria)

        sit_out_reason = "normal"
        if freshness_min > MAX_STALE_MINUTES:
            sit_out_reason = "stale_data"
            sit_out_counts["stale_data"] += 1
        elif strat is not None:
            if strat._sit_out_vol_low_count > sit_out_counts.get("_vol_low_snap", 0):
                sit_out_reason = "vol_low"
            elif getattr(strat, "_sit_out_vol_high_count", 0) > sit_out_counts.get("_vol_high_snap", 0):
                sit_out_reason = "vol_high"
            elif getattr(strat, "_sit_out_regime_count", 0) > sit_out_counts.get("_regime_snap", 0):
                sit_out_reason = "regime_uncertain"
            sit_out_counts["_vol_low_snap"] = getattr(strat, "_sit_out_vol_low_count", 0)
            sit_out_counts["_vol_high_snap"] = getattr(strat, "_sit_out_vol_high_count", 0)
            sit_out_counts["_regime_snap"] = getattr(strat, "_sit_out_regime_count", 0)
            sit_out_counts[sit_out_reason] = sit_out_counts.get(sit_out_reason, 0) + 1
        else:
            sit_out_counts["normal"] += 1

        cycle_num = i + 1

        closed = engine.closed_trades
        new_closed = closed[last_closed_count:]
        if new_closed:
            with open(TRADES_CSV, "a", newline="") as f:
                w = csv.writer(f)
                for t in new_closed:
                    w.writerow([
                        cycle_num,
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
                        sit_out_reason,
                    ])
            last_closed_count = len(closed)

        if cycle_num % log_interval == 0 or cycle_num == 1 or cycle_num == n_cycles:
            pnl = _total_pnl(closed)
            wr = _win_rate(closed)
            open_pos = engine.open_trades
            elapsed = time.perf_counter() - total_start
            avg_cycle_s = elapsed / cycle_num
            eta = avg_cycle_s * (n_cycles - cycle_num)
            sem_db_count = _query_semantic_count()

            checkpoint = {
                "cycle": cycle_num,
                "timestamp": datetime.now(UTC).isoformat(),
                "trades_open": len(open_pos),
                "trades_closed": len(closed),
                "total_pnl": round(pnl, 2),
                "win_rate": round(wr, 4),
                "regime": regime,
                "improve_calls": improve_calls,
                "semantic_patterns_db": sem_db_count,
                "data_freshness_min": round(freshness_min, 2),
                "sit_out_reason": sit_out_reason,
                "avg_cycle_time_s": round(avg_cycle_s, 3),
                "elapsed_s": round(elapsed, 1),
            }
            progress.append(checkpoint)
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, indent=2)

            status_tag = {
                "stale_data": "STALE   ", "vol_low": "SIT-OUT ",
                "vol_high": "CAUTION ", "regime_uncertain": "CAUTION ", "normal": "OK      ",
            }.get(sit_out_reason, "OK      ")

            log.info(
                "Cycle %3d/%d [%s] %s | fresh=%.1fmin | "
                "open=%2d closed=%3d | PnL=$%+.0f wr=%.0f%% | "
                "improve=%d sem_db=%d | %.1fs/c ETA %.0fs",
                cycle_num, n_cycles, regime[:4].upper(), status_tag,
                freshness_min,
                len(open_pos), len(closed),
                pnl, wr * 100,
                improve_calls, sem_db_count,
                avg_cycle_s, eta,
            )

        if i < n_cycles - 1:
            time.sleep(sleep_seconds)

    # Final results
    total_elapsed = time.perf_counter() - total_start
    closed_final = engine.closed_trades
    open_final = engine.open_trades
    sem_db_final = _query_semantic_count()

    longs = [t for t in closed_final if t.get("side") == "long"]
    shorts = [t for t in closed_final if t.get("side") == "short"]
    wins = [t for t in closed_final if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed_final if float(t.get("pnl", 0.0)) < 0]

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    sit_out_clean = {k: v for k, v in sit_out_counts.items() if not k.startswith("_")}

    results = {
        "version": "v13",
        "fixes_applied": [
            "meta_model: n_estimators=50, min_samples_leaf=10, max_features=sqrt",
            "dynamic_weights: IC weight decay 0.95*w + 0.05*(1/N)",
            "semantic_memory: SQLite fallback store, store_semantic logging upgraded",
            "orchestrator: IMPROVEMENT_INTERVAL=10, scheduler auto-register",
        ],
        "run": {
            "date": datetime.now(UTC).isoformat(),
            "cycles": n_cycles,
            "sleep_seconds": sleep_seconds,
            "elapsed_s": round(total_elapsed, 1),
            "avg_cycle_s": round(total_elapsed / n_cycles, 3),
            "cg_key_used": bool(cg_key),
            "db_url_used": bool(db_url),
        },
        "intelligence": {
            "improve_calls": improve_calls,
            "semantic_patterns_db": sem_db_final,
            "semantic_patterns_node": sem_node._patterns_extracted,
        },
        "filters": sit_out_clean,
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
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    log.info("")
    log.info("=" * 70)
    log.info("V13 COMPLETE — %d cycles in %.0fs (%.2fs/cycle)", n_cycles, total_elapsed, total_elapsed / n_cycles)
    log.info("=" * 70)
    log.info("improve_calls         : %d", improve_calls)
    log.info("semantic_patterns_db  : %d", sem_db_final)
    log.info("Closed trades         : %d  (long=%d  short=%d)", len(closed_final), len(longs), len(shorts))
    log.info("Total PnL             : $%+.2f  (engine realised: $%+.2f)", _total_pnl(closed_final), engine.realised_pnl)
    log.info("Win rate              : %.1f%%  (%d/%d)", _win_rate(closed_final) * 100, len(wins), len(closed_final))
    log.info("Profit factor         : %.2f", profit_factor if profit_factor != float("inf") else 0)
    log.info("Results               : %s", RESULTS_FILE)
    log.info("=" * 70)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V13 training run — 3 critical fixes")
    parser.add_argument("--cycles", type=int, default=50, help="Number of training cycles")
    parser.add_argument("--sleep", type=float, default=30.0, help="Seconds between cycles")
    parser.add_argument("--log-interval", type=int, default=5, help="Log every N cycles")
    args = parser.parse_args()
    run(n_cycles=args.cycles, sleep_seconds=args.sleep, log_interval=args.log_interval)
