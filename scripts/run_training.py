#!/usr/bin/env python3
"""
scripts/run_training.py
~~~~~~~~~~~~~~~~~~~~~~~
Canonical Victoria training script — replaces all versioned run_vN.py scripts.

Incorporates all fixes from V14:
  - Meta-model regularization (n_estimators=50, min_samples_leaf=10, max_features='sqrt')
  - Semantic memory SQLite fallback
  - IMPROVEMENT_INTERVAL=10 + auto-register scheduler
  - conviction_distribution included in all _construct_portfolio return paths

Plus four observability/resilience improvements:
  1. Training health watchdog  — escalates after 20/50 zero-trade cycles with
                                 detailed gate-blocking diagnostics
  2. Structured cycle metrics  — one-line JSON per cycle → /tmp/{version}_metrics.jsonl
  3. Startup preflight         — validates DB, exchange, deps before loop starts
  4. Sit-out circuit breaker   — lowers vol_low threshold after 30 consecutive sit-outs

Usage:
    python scripts/run_training.py
    python scripts/run_training.py --version v27 --cycles 500 --sleep 30
    python scripts/run_training.py --cycles 100 --sleep 5 --log-interval 10

Default version is auto-incremented from data/training_version.txt (or "v1").
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


# ---------------------------------------------------------------------------
# .env loader (must run before any omega imports)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_VERSION_FILE = DATA_DIR / "training_version.txt"


def _resolve_version(requested: str | None) -> str:
    """Return the training version to use, auto-incrementing if not specified."""
    if requested:
        _VERSION_FILE.write_text(requested.strip())
        return requested.strip()
    if _VERSION_FILE.exists():
        prev = _VERSION_FILE.read_text().strip()
        if prev.startswith("v") and prev[1:].isdigit():
            next_v = f"v{int(prev[1:]) + 1}"
            _VERSION_FILE.write_text(next_v)
            return next_v
        return prev
    _VERSION_FILE.write_text("v1")
    return "v1"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(version: str) -> logging.Logger:
    log_file = f"/tmp/{version}_training.log"
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    fhandler = logging.FileHandler(log_file, mode="w")
    fhandler.setLevel(logging.INFO)
    fhandler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S")
    )

    log = logging.getLogger(f"training.{version}")
    log.addHandler(handler)
    log.addHandler(fhandler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAX_STALE_MINUTES = 5.0


def _win_rate(trades: list[dict]) -> float:
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
    return len(wins) / len(trades) if trades else 0.0


def _total_pnl(trades: list[dict]) -> float:
    return sum(float(t.get("pnl", 0.0)) for t in trades)


def _init_trades_csv(path: Path) -> None:
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow([
            "cycle", "timestamp", "symbol", "side", "size",
            "entry_price", "exit_price", "pnl", "slippage",
            "hold_cycles", "conviction", "regime", "sit_out_reason",
        ])


def _get_data_freshness(victoria) -> float:
    try:
        return victoria._data_ingestion._data_freshness_minutes()
    except Exception:
        return 0.0


def _get_regime(victoria) -> str:
    try:
        return victoria._regime_detector.current_regime
    except Exception:
        return "unknown"


def _query_semantic_count(data_dir: Path) -> int:
    import sqlite3
    db_path = str(data_dir / "omega_victoria_memory.db")
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM semantic_memories").fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def _count_active_signals(signals: dict) -> int:
    """Count non-metadata signal keys (tickers with a dict value)."""
    return sum(
        1 for k, v in signals.items()
        if not k.startswith("_") and isinstance(v, dict)
    )


def _extract_cycle_conviction(signals: dict) -> str:
    """Return the most common conviction level across all tickers, or 'n/a'."""
    try:
        from omega.nodes.victoria.strategy import score_to_conviction
        levels: list[str] = []
        for k, v in signals.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            composite = v.get("composite")
            if composite is not None:
                levels.append(score_to_conviction(float(composite)).name)
        if not levels:
            return "n/a"
        return max(set(levels), key=levels.count)
    except Exception:
        return "n/a"


def _get_composite_score(signals: dict) -> float | None:
    """Mean composite score across all non-metadata tickers."""
    scores = [
        float(v["composite"])
        for k, v in signals.items()
        if not k.startswith("_") and isinstance(v, dict) and "composite" in v
    ]
    return sum(scores) / len(scores) if scores else None


def _get_proposals_stats(strat) -> tuple[int, int]:
    """(proposals_generated, proposals_filtered) from the strategy node."""
    if strat is None:
        return 0, 0
    try:
        return (
            getattr(strat, "_proposals_generated", 0),
            getattr(strat, "_proposals_filtered", 0),
        )
    except Exception:
        return 0, 0


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

def run(
    version: str,
    n_cycles: int = 100,
    sleep_seconds: float = 30.0,
    log_interval: int = 5,
) -> dict:
    log = logging.getLogger(f"training.{version}")

    # ── File paths ────────────────────────────────────────────────────────
    metrics_jsonl = Path(f"/tmp/{version}_metrics.jsonl")
    trades_csv = DATA_DIR / f"{version}_trades.csv"
    progress_file = DATA_DIR / f"{version}_progress.json"
    results_file = DATA_DIR / f"{version}_results.json"

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    log.info("=" * 70)
    log.info("Training Run %s — %d cycles  sleep=%.0fs", version, n_cycles, sleep_seconds)
    log.info("CoinGecko key  : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    log.info("Database URL   : %s", db_url[:40] + "..." if db_url else "NOT SET — SQLite fallback")
    log.info("Metrics JSONL  : %s", metrics_jsonl)
    log.info("Log file       : /tmp/%s_training.log", version)
    log.info("=" * 70)

    # ── Startup preflight ─────────────────────────────────────────────────
    from omega.core.training_preflight import StartupPreflight
    preflight = StartupPreflight.run()

    # ── Node / engine setup ───────────────────────────────────────────────
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode
    from omega.nodes.shared.semantic_memory import SemanticMemoryNode
    from omega.core.improvement_engine import SyntheticEvaluator

    victoria = VictoriaNode()
    orch = OmegaOrchestrator(name=f"{version}_training")
    orch.register_node(victoria)
    orch._improvement_engine.set_evaluator(SyntheticEvaluator())
    log.info("ImprovementEngine: SyntheticEvaluator injected")

    sem_node = SemanticMemoryNode(review_interval=10)
    orch.register_node(sem_node, activate=False)

    engine = PaperTradingEngine(initial_capital=100_000.0, db_url=db_url or None)
    orch.set_paper_trading(engine)

    _init_trades_csv(trades_csv)

    # ── Watchdog + circuit breaker ────────────────────────────────────────
    from omega.core.training_watchdog import WatchdogState
    from omega.core.sit_out_breaker import SitOutCircuitBreaker

    watchdog = WatchdogState()
    strat = getattr(victoria, "_strategy", None)
    breaker = SitOutCircuitBreaker(strat) if strat is not None else None
    if breaker is None:
        log.warning("Strategy node not found on VictoriaNode — circuit breaker disabled")

    # ── Metrics JSONL file (opened once, flushed each cycle) ──────────────
    metrics_jsonl.parent.mkdir(parents=True, exist_ok=True)
    metrics_fh = open(metrics_jsonl, "w")  # noqa: WPS515

    # ── Loop state ────────────────────────────────────────────────────────
    progress: list[dict] = []
    sit_out_counts: dict[str, int] = {
        "stale_data": 0, "vol_low": 0, "vol_high": 0,
        "regime_uncertain": 0, "normal": 0,
    }
    last_closed_count = 0
    improve_calls = 0
    total_start = time.perf_counter()

    try:
        for i in range(n_cycles):
            cycle_num = i + 1
            cycle_start = time.perf_counter()
            result = orch.run_one_cycle()
            cycle_elapsed = time.perf_counter() - cycle_start

            if result.improvement_proposed:
                improve_calls += 1

            # Semantic memory consolidation every 10 cycles
            if cycle_num % 10 == 0:
                try:
                    from omega.core.node import NodeInput
                    sem_out = sem_node.execute(NodeInput(
                        action="build_semantic",
                        context={"cycle": cycle_num},
                        parameters={"cycle": cycle_num, "force": False},
                    ))
                    if sem_out.success and sem_out.result:
                        stored = sem_out.result.get("patterns_extracted", 0)
                        if stored > 0:
                            log.info("Cycle %d: SemanticMemoryNode stored %d patterns", cycle_num, stored)
                except Exception as exc:
                    log.warning("SemanticMemoryNode error: %s", exc)

            regime = _get_regime(victoria)
            freshness_min = _get_data_freshness(victoria)

            # ── Determine sit_out_reason via strategy counter deltas ───────
            sit_out_reason = "normal"
            if freshness_min > MAX_STALE_MINUTES:
                sit_out_reason = "stale_data"
                sit_out_counts["stale_data"] += 1
            elif strat is not None:
                vol_low_snap = sit_out_counts.get("_vol_low_snap", 0)
                vol_high_snap = sit_out_counts.get("_vol_high_snap", 0)
                regime_snap = sit_out_counts.get("_regime_snap", 0)

                if strat._sit_out_vol_low_count > vol_low_snap:
                    sit_out_reason = "vol_low"
                elif getattr(strat, "_sit_out_vol_high_count", 0) > vol_high_snap:
                    sit_out_reason = "vol_high"
                elif getattr(strat, "_sit_out_regime_count", 0) > regime_snap:
                    sit_out_reason = "regime_uncertain"

                sit_out_counts["_vol_low_snap"] = strat._sit_out_vol_low_count
                sit_out_counts["_vol_high_snap"] = getattr(strat, "_sit_out_vol_high_count", 0)
                sit_out_counts["_regime_snap"] = getattr(strat, "_sit_out_regime_count", 0)
                sit_out_counts[sit_out_reason] = sit_out_counts.get(sit_out_reason, 0) + 1
            else:
                sit_out_counts["normal"] += 1

            # ── Circuit breaker ───────────────────────────────────────────
            if breaker is not None:
                breaker.record(sit_out_reason)

            # ── Closed trade flush ────────────────────────────────────────
            closed = engine.closed_trades
            new_closed = closed[last_closed_count:]
            if new_closed:
                with open(trades_csv, "a", newline="") as f:
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

            # ── Signal metrics ────────────────────────────────────────────
            last_signals: dict = {}
            try:
                last_signals = getattr(result, "signals", {}) or {}
            except Exception:
                pass

            active_signals = _count_active_signals(last_signals)
            composite_score = _get_composite_score(last_signals)
            conviction_str = _extract_cycle_conviction(last_signals)
            proposals_gen, proposals_filt = _get_proposals_stats(strat)

            # ring1_pass: true if any symbol cleared conviction filters
            ring1_pass = proposals_gen > proposals_filt or proposals_gen == 0

            trade_action = (
                "SIT_OUT" if sit_out_reason != "normal"
                else ("TRADE" if new_closed else "HOLD")
            )

            # ── Structured JSONL metric line ──────────────────────────────
            metric_row: dict = {
                "cycle": cycle_num,
                "ts": datetime.now(UTC).isoformat(),
                "version": version,
                "regime": regime,
                "composite_score": round(composite_score, 4) if composite_score is not None else None,
                "trade_action": trade_action,
                "sit_out_reason": sit_out_reason if sit_out_reason != "normal" else None,
                "active_signals": active_signals,
                "ring1_pass": ring1_pass,
                "vol_rank": None,  # transient inside strategy — not exposed yet
                "conviction": conviction_str,
                "new_trades": len(new_closed),
                "total_closed": len(closed),
                "elapsed_s": round(cycle_elapsed, 3),
                "breaker_tripped": breaker.tripped if breaker else False,
                "vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
            }
            metrics_fh.write(json.dumps(metric_row) + "\n")
            metrics_fh.flush()

            # ── Watchdog ──────────────────────────────────────────────────
            watchdog.record_cycle(
                had_trade=bool(new_closed),
                sit_out_reason=sit_out_reason,
                regime=regime,
                conviction_failures=proposals_filt,
                proposals_generated=proposals_gen,
                ring1_pass=ring1_pass,
            )

            # ── Periodic progress log ─────────────────────────────────────
            if cycle_num % log_interval == 0 or cycle_num == 1 or cycle_num == n_cycles:
                pnl = _total_pnl(closed)
                wr = _win_rate(closed)
                open_pos = engine.open_trades
                elapsed = time.perf_counter() - total_start
                avg_cycle_s = elapsed / cycle_num
                eta = avg_cycle_s * (n_cycles - cycle_num)
                sem_db_count = _query_semantic_count(DATA_DIR)

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
                    "watchdog_zero_streak": watchdog.consecutive_zero_trade_cycles,
                    "breaker_tripped": breaker.tripped if breaker else False,
                    "vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
                }
                progress.append(checkpoint)
                with open(progress_file, "w") as f:
                    json.dump(progress, f, indent=2)

                status_tag = {
                    "stale_data": "STALE   ", "vol_low": "SIT-OUT ",
                    "vol_high": "CAUTION ", "regime_uncertain": "CAUTION ",
                    "normal": "OK      ",
                }.get(sit_out_reason, "OK      ")

                breaker_str = (
                    f" [BREAKER thr={strat._vol_low_threshold:.3f}]"
                    if breaker and breaker.tripped else ""
                )

                log.info(
                    "Cycle %3d/%d [%s] %s | fresh=%.1fmin | "
                    "open=%2d closed=%3d | PnL=$%+.0f wr=%.0f%% | "
                    "improve=%d sem_db=%d | %.1fs/c ETA %.0fs"
                    " | zero_streak=%d%s",
                    cycle_num, n_cycles, regime[:4].upper(), status_tag,
                    freshness_min,
                    len(open_pos), len(closed),
                    pnl, wr * 100,
                    improve_calls, sem_db_count,
                    avg_cycle_s, eta,
                    watchdog.consecutive_zero_trade_cycles,
                    breaker_str,
                )

            if i < n_cycles - 1:
                time.sleep(sleep_seconds)

    finally:
        metrics_fh.close()

    # ── Final results ─────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start
    closed_final = engine.closed_trades
    open_final = engine.open_trades
    sem_db_final = _query_semantic_count(DATA_DIR)

    longs = [t for t in closed_final if t.get("side") == "long"]
    shorts = [t for t in closed_final if t.get("side") == "short"]
    wins = [t for t in closed_final if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed_final if float(t.get("pnl", 0.0)) < 0]

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    sit_out_clean = {k: v for k, v in sit_out_counts.items() if not k.startswith("_")}

    results = {
        "version": version,
        "run": {
            "date": datetime.now(UTC).isoformat(),
            "cycles": n_cycles,
            "sleep_seconds": sleep_seconds,
            "elapsed_s": round(total_elapsed, 1),
            "avg_cycle_s": round(total_elapsed / n_cycles, 3),
            "cg_key_used": bool(cg_key),
            "db_url_used": bool(db_url),
        },
        "preflight": {
            "ok": preflight.ok,
            "warnings": preflight.warnings,
        },
        "intelligence": {
            "improve_calls": improve_calls,
            "semantic_patterns_db": sem_db_final,
            "semantic_patterns_node": sem_node._patterns_extracted,
        },
        "observability": {
            "metrics_jsonl": str(metrics_jsonl),
            "total_zero_trade_cycles": watchdog.total_zero_trade_cycles,
            "max_zero_streak": watchdog.consecutive_zero_trade_cycles,
            "ring1_pass_rate_final": watchdog.ring1_pass_rate(),
            "conviction_filter_rate": watchdog.conviction_filter_rate(),
            "circuit_breaker_trips": breaker._trip_count if breaker else 0,
            "final_vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
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

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    log.info("")
    log.info("=" * 70)
    log.info(
        "%s COMPLETE — %d cycles in %.0fs (%.2fs/cycle)",
        version.upper(), n_cycles, total_elapsed, total_elapsed / n_cycles,
    )
    log.info("=" * 70)
    log.info("improve_calls         : %d", improve_calls)
    log.info("semantic_patterns_db  : %d", sem_db_final)
    log.info("Closed trades         : %d  (long=%d  short=%d)", len(closed_final), len(longs), len(shorts))
    log.info(
        "Total PnL             : $%+.2f  (engine realised: $%+.2f)",
        _total_pnl(closed_final), engine.realised_pnl,
    )
    log.info("Win rate              : %.1f%%  (%d/%d)", _win_rate(closed_final) * 100, len(wins), len(closed_final))
    log.info("Profit factor         : %.2f", profit_factor if profit_factor != float("inf") else 0)
    log.info("--- Observability ---")
    log.info(
        "Zero-trade cycles     : %d / %d  (%.0f%%)",
        watchdog.total_zero_trade_cycles, n_cycles,
        watchdog.total_zero_trade_cycles / n_cycles * 100,
    )
    log.info("Circuit breaker trips : %d", breaker._trip_count if breaker else 0)
    log.info("Final vol threshold   : %.3f", getattr(strat, "_vol_low_threshold", 0.20))
    log.info("Metrics JSONL         : %s", metrics_jsonl)
    log.info("Results               : %s", results_file)
    log.info("=" * 70)

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Canonical Victoria training script with watchdog, circuit breaker, and preflight"
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="Training version label (default: auto-increment from data/training_version.txt)"
    )
    parser.add_argument("--cycles", type=int, default=100, help="Number of training cycles")
    parser.add_argument("--sleep", type=float, default=30.0, help="Seconds between cycles")
    parser.add_argument("--log-interval", type=int, default=5, help="Log every N cycles")
    args = parser.parse_args()

    version = _resolve_version(args.version)
    _setup_logging(version)

    run(
        version=version,
        n_cycles=args.cycles,
        sleep_seconds=args.sleep,
        log_interval=args.log_interval,
    )
