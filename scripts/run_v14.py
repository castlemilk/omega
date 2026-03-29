#!/usr/bin/env python3
"""
scripts/run_v14.py
~~~~~~~~~~~~~~~~~~
V14 training run — all V13 fixes + V14 conviction patch:
  - Fix 1: Meta-model regularization (n_estimators=50, min_samples_leaf=10,
            max_features='sqrt') + IC weight decay to prevent OOS Sharpe blowout
  - Fix 2: Semantic memory SQLite fallback so patterns flush to DB
  - Fix 3: IMPROVEMENT_INTERVAL=10 + auto-register scheduler so improve() fires
  - Fix 4: conviction_distribution included in all _construct_portfolio return paths

Usage:
    python scripts/run_v14.py
    python scripts/run_v14.py --cycles 100 --sleep 30
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

LOG_FILE = "/tmp/v14_training.log"
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
log = logging.getLogger("v14")
log.addHandler(_handler)
log.addHandler(_fhandler)
log.setLevel(logging.INFO)
log.propagate = False

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = DATA_DIR / "v14_progress.json"
TRADES_CSV = DATA_DIR / "v14_trades.csv"
RESULTS_FILE = DATA_DIR / "v14_results.json"

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


# ANSI colour helpers (no external deps)
_R = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOX_W = 54


def _diag_line(label: str, value: str) -> str:
    return f"  {_BOLD}{label:<14}{_R} {value}"


def print_training_diagnostics(victoria, strategy, cycle: int, engine) -> None:
    """Print a colorized diagnostics block — shows regime, data, signals, blockers."""
    sep = "═" * _BOX_W

    print(f"\n{_CYAN}{sep}{_R}")
    print(f"{_CYAN}══ TRAINING DIAGNOSTICS (cycle {cycle}) {'═' * max(0, _BOX_W - 30 - len(str(cycle)))}{_R}")
    print(f"{_CYAN}{sep}{_R}")

    # ── Regime ────────────────────────────────────────────────────────────
    signals_cache: dict = {}
    try:
        signals_cache = getattr(victoria, "_last_signals", {}) or {}
    except Exception:
        pass

    regime_raw = signals_cache.get("_regime") or _get_regime(victoria)
    regime_upper = str(regime_raw).upper()
    if regime_upper in ("UNKNOWN", "UNKN", ""):
        regime_str = f"{_RED}UNKN ⚠️{_R}"
    else:
        conf = 0.0
        try:
            probs = victoria._wasserstein_regime._regime_probs
            conf = max(probs) if probs else 0.0
        except Exception:
            pass
        label_colour = _GREEN if regime_upper == "BULL" else (_RED if regime_upper == "BEAR" else _YELLOW)
        regime_str = f"{label_colour}{regime_upper}{_R} (conf: {conf:.2f})"
    print(_diag_line("REGIME:", regime_str))

    # ── Data freshness ────────────────────────────────────────────────────
    freshness = _get_data_freshness(victoria)
    if freshness > MAX_STALE_MINUTES:
        fresh_str = f"{_RED}❌ STALE ({freshness:.1f}min >5min){_R}"
    else:
        fresh_str = f"{_GREEN}✅ {freshness:.1f}min ago{_R}"
    print(_diag_line("DATA FRESH:", fresh_str))

    # ── Active signals ────────────────────────────────────────────────────
    ticker_signals = {
        k: v for k, v in signals_cache.items()
        if not k.startswith("_") and isinstance(v, dict)
    }
    active = sum(1 for v in ticker_signals.values() if v.get("composite") is not None)
    total = len(ticker_signals)
    sig_str = f"{active}/{total} active" if total > 0 else f"{_YELLOW}none yet{_R}"
    print(_diag_line("SIGNALS:", sig_str))

    # ── Sit-out status ────────────────────────────────────────────────────
    if strategy is not None:
        vol_low = getattr(strategy, "_sit_out_vol_low_count", 0)
        vol_high = getattr(strategy, "_sit_out_vol_high_count", 0)
        regime_out = getattr(strategy, "_sit_out_regime_count", 0)
        if vol_low > 0:
            sit_str = f"{_YELLOW}YES: vol_low (streak: {vol_low}){_R}"
        elif vol_high > 0:
            sit_str = f"{_YELLOW}YES: vol_high (streak: {vol_high}){_R}"
        elif regime_out > 0:
            sit_str = f"{_YELLOW}YES: regime_uncertain (count: {regime_out}){_R}"
        else:
            sit_str = f"{_GREEN}NO{_R}"
    else:
        sit_str = "strategy n/a"
    print(_diag_line("SIT-OUT:", sit_str))

    # ── Per-ticker conviction ─────────────────────────────────────────────
    conv_parts: list[str] = []
    for sym, data in ticker_signals.items():
        composite = data.get("composite")
        if composite is None:
            continue
        composite = float(composite)
        ticker = sym.replace("USDT", "").replace("/USDT", "")
        if composite > 0.05:
            direction = f"{_GREEN}BUY{_R}"
        elif composite < -0.05:
            direction = f"{_RED}SELL{_R}"
        else:
            direction = "HOLD"
        conv_parts.append(f"{ticker}: {composite:+.2f} ({direction})")
    conv_str = " | ".join(conv_parts) if conv_parts else f"{_YELLOW}n/a{_R}"
    print(_diag_line("CONVICTION:", conv_str))

    # ── Trade stats ───────────────────────────────────────────────────────
    closed = engine.closed_trades
    open_pos = engine.open_trades
    pnl = _total_pnl(closed)
    wr = _win_rate(closed)
    trade_str = (
        f"open={len(open_pos)} closed={len(closed)} | "
        f"PnL=${pnl:+.2f} | WR={wr * 100:.0f}%"
    )
    print(_diag_line("TRADES:", trade_str))

    # ── Long/short breakdown ──────────────────────────────────────────────
    all_trades = list(closed) + list(open_pos)
    n_longs = sum(1 for t in all_trades if t.get("side") == "long")
    n_shorts = sum(1 for t in all_trades if t.get("side") == "short")
    ls_str = f"longs={n_longs} shorts={n_shorts}"
    if n_longs == 0 and n_shorts >= 3:
        ls_str += f"  {_RED}⚠️  short-only bias{_R}"
    elif n_shorts == 0 and n_longs >= 3:
        ls_str += f"  {_YELLOW}⚠️  long-only — short side suppressed?{_R}"
    print(_diag_line("LONG/SHORT:", ls_str))

    # ── Blockers ──────────────────────────────────────────────────────────
    blockers: list[str] = []
    if regime_upper in ("UNKNOWN", "UNKN", ""):
        blockers.append("Regime detector not firing")
    if strategy is not None and getattr(strategy, "_sit_out_vol_low_count", 0) > 0:
        blockers.append(f"vol_low sit-out (streak {strategy._sit_out_vol_low_count})")
    if freshness > MAX_STALE_MINUTES:
        blockers.append(f"Data freshness >{freshness:.1f}min")
    composites = [
        float(v.get("composite", 0.0))
        for v in ticker_signals.values()
        if v.get("composite") is not None
    ]
    if composites and all(abs(c) < 0.05 for c in composites):
        blockers.append("No conviction above threshold (all HOLD)")
    if n_longs == 0 and n_shorts >= 3:
        blockers.append("Short-only bias detected — check short_bias fix")
    if total == 0:
        blockers.append("No signal data yet (first cycle?)")

    if blockers:
        blocker_str = f"{_RED}" + " | ".join(blockers) + _R
    else:
        blocker_str = f"{_GREEN}NONE{_R}"
    print(_diag_line("BLOCKERS:", blocker_str))

    print(f"{_CYAN}{sep}{_R}\n")
    sys.stdout.flush()


def run(n_cycles: int = 100, sleep_seconds: float = 30.0, log_interval: int = 5) -> dict:
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode
    from omega.nodes.shared.semantic_memory import SemanticMemoryNode

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    log.info("=" * 70)
    log.info("V14 Training Run — %d cycles  sleep=%.0fs", n_cycles, sleep_seconds)
    log.info("FIXES: meta-model regularization | semantic SQLite flush | "
             "IMPROVEMENT_INTERVAL=10 | conviction_distribution patch")
    log.info("CoinGecko key  : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    log.info("Database URL   : %s", db_url[:40] + "..." if db_url else "NOT SET — SQLite fallback")
    log.info("Log file       : %s", LOG_FILE)
    log.info("=" * 70)

    from omega.core.improvement_engine import SyntheticEvaluator

    victoria = VictoriaNode()
    orch = OmegaOrchestrator(name="v14_training")
    orch.register_node(victoria)

    orch._improvement_engine.set_evaluator(SyntheticEvaluator())
    log.info("ImprovementEngine: SyntheticEvaluator injected")

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

    # Pre-loop diagnostic (cycle 0 — before any trades)
    print_training_diagnostics(victoria, strat, 0, engine)

    for i in range(n_cycles):
        cycle_start = time.perf_counter()
        result = orch.run_one_cycle()
        cycle_elapsed = time.perf_counter() - cycle_start

        if result.improvement_proposed:
            improve_calls += 1

        # Diagnostics every 10 cycles
        if (i + 1) % 10 == 0:
            print_training_diagnostics(victoria, strat, i + 1, engine)

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
        "version": "v14",
        "fixes_applied": [
            "meta_model: n_estimators=50, min_samples_leaf=10, max_features=sqrt",
            "dynamic_weights: IC weight decay 0.95*w + 0.05*(1/N)",
            "semantic_memory: SQLite fallback store, store_semantic logging upgraded",
            "orchestrator: IMPROVEMENT_INTERVAL=10, scheduler auto-register",
            "conviction_distribution: included in all _construct_portfolio return paths",
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
    log.info("V14 COMPLETE — %d cycles in %.0fs (%.2fs/cycle)", n_cycles, total_elapsed, total_elapsed / n_cycles)
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
    parser = argparse.ArgumentParser(description="V14 training run — all fixes")
    parser.add_argument("--cycles", type=int, default=100, help="Number of training cycles")
    parser.add_argument("--sleep", type=float, default=30.0, help="Seconds between cycles")
    parser.add_argument("--log-interval", type=int, default=5, help="Log every N cycles")
    args = parser.parse_args()
    run(n_cycles=args.cycles, sleep_seconds=args.sleep, log_interval=args.log_interval)
