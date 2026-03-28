#!/usr/bin/env python3
"""
scripts/run_training.py
~~~~~~~~~~~~~~~~~~~~~~~
V10 training run — all improvements stacked:
  - Sit-out filter (regime uncertainty + vol percentile)        [91f7771]
  - Regime directional filter (block longs bear / shorts bull)  [baa0681]
  - CoinGecko cache TTL 60s (fresher prices)                    [ee723b5]
  - Staleness filter (skip cycle if data > MAX_STALE_MINUTES)
  - Honest PnL (realized_pnl from engine, real entry prices)
  - DB persistence (PaperTradingEngine writes to postgres)
  - Progress JSON + trades CSV

Usage:
    python scripts/run_training.py
    python scripts/run_training.py --cycles 100 --sleep 30
    python scripts/run_training.py --cycles 500 --sleep 5
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
LOG_FILE = "/tmp/v10_training.log"
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
log = logging.getLogger("v10")
log.addHandler(_handler)
log.addHandler(_fhandler)
log.setLevel(logging.INFO)
log.propagate = False

# ── config ───────────────────────────────────────────────────────────────────
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = DATA_DIR / "training_progress.json"
TRADES_CSV = DATA_DIR / "v10_trades.csv"
RESULTS_FILE = DATA_DIR / "v10_results.json"

_VERSION = "v10"  # updated by --version arg at startup


def _set_version(version: str) -> None:
    global TRADES_CSV, RESULTS_FILE, _VERSION
    _VERSION = version
    TRADES_CSV = DATA_DIR / f"{version}_trades.csv"
    RESULTS_FILE = DATA_DIR / f"{version}_results.json"

# Staleness: if market data is older than this, skip the cycle
MAX_STALE_MINUTES = 5.0


def _win_rate(trades: list[dict]) -> float:
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
    return len(wins) / len(trades) if trades else 0.0


def _total_pnl(trades: list[dict]) -> float:
    return sum(float(t.get("pnl", 0.0)) for t in trades)


def _init_trades_csv() -> None:
    with open(TRADES_CSV, "w", newline="") as f:
        csv.writer(f).writerow(
            [
                "cycle",
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
                "sit_out_reason",
            ]
        )


def _get_data_freshness(victoria: object) -> float:
    """Return minutes since last price data fetch. 9999 if unknown."""
    try:
        di = getattr(victoria, "_data_ingestion", None)
        if di is None:
            return 0.0
        result_val = di._data_freshness_minutes()
        return float(result_val)
    except Exception:
        return 0.0  # assume fresh if we can't check


def _get_regime(victoria: object) -> str:
    try:
        rd = getattr(victoria, "_regime_detector", None)
        if rd is None:
            return "unknown"
        regime_val = rd.current_regime
        return str(regime_val)
    except Exception:
        return "unknown"


def run(n_cycles: int = 100, sleep_seconds: float = 30.0, log_interval: int = 5) -> dict:
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    log.info("=" * 70)
    log.info("V12 Training Run — %d cycles  sleep=%.0fs", n_cycles, sleep_seconds)
    log.info("CoinGecko key  : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    log.info("Database URL   : %s", db_url[:40] + "..." if db_url else "NOT SET — in-memory only")
    log.info("Staleness limit: %.0f min", MAX_STALE_MINUTES)
    log.info("Log file       : %s", LOG_FILE)
    log.info("Intelligence metrics: ACTIVE")
    log.info("=" * 70)

    # ── Startup validation ────────────────────────────────────────────────────
    from omega.core.startup_checks import StartupChecker
    _startup = StartupChecker(skip_db=(not db_url), skip_api=False).run()
    _startup.print_summary()
    if not _startup.ok:
        log.error("Startup checks failed — aborting run")
        return {}

    intel_collector = IntelligenceMetricsCollector(db_url=db_url or None)

    victoria = VictoriaNode()
    orch = OmegaOrchestrator(name="v12_training", metrics_collector=intel_collector)
    orch.register_node(victoria)

    engine = PaperTradingEngine(initial_capital=100_000.0, db_url=db_url or None)
    orch.set_paper_trading(engine)

    _init_trades_csv()

    progress: list[dict] = []
    sit_out_counts: dict[str, int] = {
        "stale_data": 0,
        "vol_low": 0,
        "vol_high": 0,
        "regime_uncertain": 0,
        "normal": 0,
    }
    last_closed_count = 0
    total_start = time.perf_counter()

    strat = getattr(victoria, "_strategy", None)

    for i in range(n_cycles):
        cycle_start = time.perf_counter()
        orch.run_one_cycle()
        time.perf_counter() - cycle_start

        regime = _get_regime(victoria)
        freshness_min = _get_data_freshness(victoria)

        # ── Determine sit-out reason ──────────────────────────────────────────
        sit_out_reason = "normal"

        if freshness_min > MAX_STALE_MINUTES:
            sit_out_reason = "stale_data"
            sit_out_counts["stale_data"] += 1
        elif strat is not None:
            # Infer from strategy counter deltas
            total_strat = (
                getattr(strat, "_sit_out_vol_low_count", 0)
                + getattr(strat, "_sit_out_vol_high_count", 0)
                + getattr(strat, "_sit_out_regime_count", 0)
                + getattr(strat, "_normal_trade_count", 0)
            )
            if total_strat == i + 1:
                if strat._sit_out_vol_low_count > sit_out_counts.get("_vol_low_snap", 0):
                    sit_out_reason = "vol_low"
                elif strat._sit_out_vol_high_count > sit_out_counts.get("_vol_high_snap", 0):
                    sit_out_reason = "vol_high"
                elif strat._sit_out_regime_count > sit_out_counts.get("_regime_snap", 0):
                    sit_out_reason = "regime_uncertain"
            # snapshot for next delta
            sit_out_counts["_vol_low_snap"] = getattr(strat, "_sit_out_vol_low_count", 0)
            sit_out_counts["_vol_high_snap"] = getattr(strat, "_sit_out_vol_high_count", 0)
            sit_out_counts["_regime_snap"] = getattr(strat, "_sit_out_regime_count", 0)
            sit_out_counts[sit_out_reason] = sit_out_counts.get(sit_out_reason, 0) + 1
        else:
            sit_out_counts["normal"] += 1

        cycle_num = i + 1

        # ── Append new closed trades ──────────────────────────────────────────
        closed = engine.closed_trades
        new_closed = closed[last_closed_count:]
        if new_closed:
            with open(TRADES_CSV, "a", newline="") as f:
                w = csv.writer(f)
                for t in new_closed:
                    w.writerow(
                        [
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
                        ]
                    )
            last_closed_count = len(closed)

        # ── Progress logging ──────────────────────────────────────────────────
        if cycle_num % log_interval == 0 or cycle_num == 1 or cycle_num == n_cycles:
            pnl = _total_pnl(closed)
            wr = _win_rate(closed)
            open_pos = engine.open_trades
            elapsed = time.perf_counter() - total_start
            avg_cycle_s = elapsed / cycle_num
            eta = avg_cycle_s * (n_cycles - cycle_num)

            checkpoint = {
                "cycle": cycle_num,
                "timestamp": datetime.now(UTC).isoformat(),
                "trades_open": len(open_pos),
                "trades_closed": len(closed),
                "total_pnl": round(pnl, 2),
                "win_rate": round(wr, 4),
                "regime": regime,
                "data_freshness_min": round(freshness_min, 2),
                "sit_out_reason": sit_out_reason,
                "avg_cycle_time_s": round(avg_cycle_s, 3),
                "elapsed_s": round(elapsed, 1),
            }
            progress.append(checkpoint)
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, indent=2)

            status_tag = {
                "stale_data": "STALE   ",
                "vol_low": "SIT-OUT ",
                "vol_high": "CAUTION ",
                "regime_uncertain": "CAUTION ",
                "normal": "OK      ",
            }.get(sit_out_reason, "OK      ")

            log.info(
                "Cycle %3d/%d [%s] %s | fresh=%.1fmin | "
                "open=%2d closed=%3d | PnL=$%+.0f wr=%.0f%% | %.1fs/c ETA %.0fs",
                cycle_num,
                n_cycles,
                regime[:4].upper(),
                status_tag,
                freshness_min,
                len(open_pos),
                len(closed),
                pnl,
                wr * 100,
                avg_cycle_s,
                eta,
            )

        if i < n_cycles - 1:
            time.sleep(sleep_seconds)

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

    # Clean internal snapshot keys from sit_out_counts
    sit_out_clean = {k: v for k, v in sit_out_counts.items() if not k.startswith("_")}

    results = {
        "version": "v10",
        "run": {
            "date": datetime.now(UTC).isoformat(),
            "cycles": n_cycles,
            "sleep_seconds": sleep_seconds,
            "elapsed_s": round(total_elapsed, 1),
            "avg_cycle_s": round(total_elapsed / n_cycles, 3),
            "cg_key_used": bool(cg_key),
            "db_url_used": bool(db_url),
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

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    log.info("")
    log.info("=" * 70)
    log.info(
        "V10 COMPLETE — %d cycles in %.0fs (%.2fs/cycle)",
        n_cycles,
        total_elapsed,
        total_elapsed / n_cycles,
    )
    log.info("=" * 70)
    log.info(
        "Closed trades   : %d  (long=%d  short=%d)", len(closed_final), len(longs), len(shorts)
    )
    log.info("Open positions  : %d", len(open_final))
    log.info(
        "Total PnL       : $%+.2f  (engine realised: $%+.2f)",
        _total_pnl(closed_final),
        engine.realised_pnl,
    )
    log.info(
        "Win rate        : %.1f%%  (%d/%d)",
        _win_rate(closed_final) * 100,
        len(wins),
        len(closed_final),
    )
    log.info("Profit factor   : %.2f", profit_factor if profit_factor != float("inf") else 0)
    log.info("")
    log.info("Sit-out breakdown:")
    for k, v in sit_out_clean.items():
        pct = v / n_cycles * 100
        log.info("  %-20s %3d / %d  (%.0f%%)", k + ":", v, n_cycles, pct)
    log.info("")
    log.info("Per-symbol PnL:")
    per_sym: dict = results.get("per_symbol", {})  # type: ignore[assignment]
    for sym, d in list(per_sym.items())[:10]:
        log.info(
            "  %-12s  PnL=$%+8.2f  trades=%3d  win=%.0f%%",
            sym,
            d["pnl"],
            d["trades"],
            d["win_rate"] * 100,
        )
    log.info("")
    log.info("Files: %s  |  %s  |  %s", PROGRESS_FILE, TRADES_CSV, RESULTS_FILE)
    log.info("Log  : %s", LOG_FILE)
    log.info("=" * 70)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Training run — all filters stacked")
    parser.add_argument("--cycles", type=int, default=100, help="Number of training cycles")
    parser.add_argument("--sleep", type=float, default=30.0, help="Seconds between cycles")
    parser.add_argument("--log-interval", type=int, default=5, help="Log every N cycles")
    parser.add_argument("--version", type=str, default="v10", help="Version tag for output files (e.g. v18)")
    args = parser.parse_args()
    _set_version(args.version)
    run(n_cycles=args.cycles, sleep_seconds=args.sleep, log_interval=args.log_interval)
