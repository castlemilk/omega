"""
omega.core.overnight_runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Overnight training scheduler — runs continuous training in batches of cycles.

Features
--------
- Batches of BATCH_SIZE cycles (default 200), up to --batches total batches
- After each batch: saves results JSON, runs trade analyzer, checks PnL alerts
- Continues to next batch if PnL > 0 and profit_factor > 1.2
- Pauses with CRITICAL alert after 2 consecutive batches with negative PnL
- Graceful shutdown via SIGTERM or /tmp/omega_stop sentinel file
- System health snapshot logged between every batch

CLI usage (direct)::

    python -m omega.core.overnight_runner --batches 10 --batch-size 200

Go wrapper::

    omega run-overnight --batches 10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.overnight")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOP_FILE = Path("/tmp/omega_stop")
RESULTS_PATH = Path("data/overnight_results.json")
PROFIT_FACTOR_THRESHOLD = 1.2
MAX_CONSECUTIVE_LOSSES = 2


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BatchResult:
    batch_num: int
    cycles_run: int
    started_at: str
    finished_at: str
    total_pnl: float
    profit_factor: float
    win_rate: float
    n_closed: int
    n_open: int
    health_score: float
    error_rate: float
    alert_level: str = "ok"  # "ok" | "warn" | "critical"
    alert_message: str = ""


@dataclass
class OvernightProgress:
    started_at: str
    batch_size: int
    total_batches: int
    completed_batches: int = 0
    batches: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"  # "running" | "paused" | "completed" | "interrupted"
    stop_reason: str = ""
    finished_at: str = ""


# ---------------------------------------------------------------------------
# OvernightRunner
# ---------------------------------------------------------------------------


class OvernightRunner:
    """
    Runs training in batches of *batch_size* cycles.

    Parameters
    ----------
    total_batches:
        How many batches to run before stopping (0 = run forever).
    batch_size:
        Number of orchestrator cycles per batch.
    config_path:
        Path to omega.yml config file.
    mode:
        Orchestrator mode: "pico" | "supervised" | "autonomous".
    """

    def __init__(
        self,
        total_batches: int = 10,
        batch_size: int = 200,
        config_path: str | None = None,
        mode: str = "pico",
    ) -> None:
        self.total_batches = total_batches
        self.batch_size = batch_size
        self.config_path = config_path
        self.mode = mode

        self._running = False
        self._orchestrator: Any = None
        self._paper_trading: Any = None
        self._analyzer: Any = None
        self._store: Any = None
        self._metrics: Any = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Blocking entry point. Returns exit code (0 = ok, 1 = paused/error)."""
        self._setup()
        self._install_signal_handlers()
        self._running = True

        progress = OvernightProgress(
            started_at=_now(),
            batch_size=self.batch_size,
            total_batches=self.total_batches,
        )

        logger.info(
            "Overnight runner started  batches=%d  batch_size=%d  mode=%s",
            self.total_batches,
            self.batch_size,
            self.mode,
        )
        print(
            f"[overnight] Starting: {self.total_batches} batch(es) × "
            f"{self.batch_size} cycles = {self.total_batches * self.batch_size} total cycles"
        )

        consecutive_losses = 0
        exit_code = 0
        batch_num = 0

        while self._running:
            # Honour stop file
            if STOP_FILE.exists():
                logger.warning("Stop file detected at %s — shutting down", STOP_FILE)
                print(f"\n[overnight] Stop file found at {STOP_FILE} — halting.")
                progress.status = "interrupted"
                progress.stop_reason = "stop_file"
                break

            # Honour total_batches limit
            if self.total_batches > 0 and batch_num >= self.total_batches:
                logger.info("Reached total_batches=%d — done.", self.total_batches)
                print(f"\n[overnight] All {self.total_batches} batch(es) complete.")
                progress.status = "completed"
                break

            batch_num += 1
            print(f"\n{'═' * 60}")
            print(f"[overnight] Batch {batch_num}/{self.total_batches}  ({self.batch_size} cycles)")
            print(f"{'═' * 60}")

            result = self._run_batch(batch_num)
            progress.completed_batches = batch_num
            progress.batches.append(asdict(result))
            _save_progress(progress)

            # ── Alert / continuation logic ────────────────────────────
            if result.total_pnl < 0:
                consecutive_losses += 1
                logger.warning(
                    "Batch %d: negative PnL=%.2f  consecutive_losses=%d",
                    batch_num,
                    result.total_pnl,
                    consecutive_losses,
                )
            else:
                consecutive_losses = 0

            if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                msg = (
                    f"CRITICAL: {consecutive_losses} consecutive batches with negative PnL "
                    f"(last PnL={result.total_pnl:.2f}, profit_factor={result.profit_factor:.3f}). "
                    "Pausing overnight run."
                )
                logger.critical(msg)
                print(f"\n{'!' * 60}")
                print(f"[overnight] {msg}")
                print(f"{'!' * 60}\n")
                result.alert_level = "critical"
                result.alert_message = msg
                progress.batches[-1] = asdict(result)
                progress.status = "paused"
                progress.stop_reason = "consecutive_losses"
                _save_progress(progress)
                exit_code = 1
                break

            if result.total_pnl > 0 and result.profit_factor > PROFIT_FACTOR_THRESHOLD:
                logger.info(
                    "Batch %d: PnL=%.2f  profit_factor=%.3f ✓ — continuing",
                    batch_num,
                    result.total_pnl,
                    result.profit_factor,
                )
                print(
                    f"[overnight] ✓ Batch {batch_num} ok: "
                    f"PnL={result.total_pnl:.2f}  profit_factor={result.profit_factor:.3f}"
                )
            elif result.total_pnl > 0:
                logger.info(
                    "Batch %d: PnL=%.2f but profit_factor=%.3f < %.1f — warn, continuing",
                    batch_num,
                    result.total_pnl,
                    result.profit_factor,
                    PROFIT_FACTOR_THRESHOLD,
                )
                result.alert_level = "warn"
                result.alert_message = (
                    f"profit_factor={result.profit_factor:.3f} below threshold {PROFIT_FACTOR_THRESHOLD}"
                )
                progress.batches[-1] = asdict(result)
                print(
                    f"[overnight] ⚠ Batch {batch_num}: PnL positive but "
                    f"profit_factor={result.profit_factor:.3f} < {PROFIT_FACTOR_THRESHOLD}"
                )
            else:
                logger.warning(
                    "Batch %d: PnL=%.2f (negative) — consecutive_losses=%d",
                    batch_num,
                    result.total_pnl,
                    consecutive_losses,
                )
                result.alert_level = "warn"
                result.alert_message = f"Negative PnL: {result.total_pnl:.2f}"
                progress.batches[-1] = asdict(result)
                print(
                    f"[overnight] ⚠ Batch {batch_num}: negative PnL={result.total_pnl:.2f} "
                    f"(consecutive_losses={consecutive_losses})"
                )

            _save_progress(progress)

            # Health snapshot between batches
            self._log_system_health(batch_num)

        # ── Teardown ──────────────────────────────────────────────────
        if progress.status == "running":
            progress.status = "interrupted"
            progress.stop_reason = "sigterm"
        progress.finished_at = _now()
        _save_progress(progress)
        self._teardown()

        self._print_summary(progress)
        return exit_code

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def _run_batch(self, batch_num: int) -> BatchResult:
        """Run batch_size cycles and return aggregate metrics."""
        started_at = _now()
        t0 = time.monotonic()
        errors = 0

        for i in range(self.batch_size):
            if not self._running:
                break
            if STOP_FILE.exists():
                break

            try:
                self._orchestrator.run_one_cycle()
            except Exception as exc:
                errors += 1
                logger.error("Cycle %d in batch %d failed: %s", i + 1, batch_num, exc)

            if (i + 1) % 50 == 0:
                elapsed = time.monotonic() - t0
                print(
                    f"  [{i + 1:>3}/{self.batch_size}] "
                    f"elapsed={elapsed:.0f}s  errors={errors}"
                )

        finished_at = _now()
        elapsed_total = time.monotonic() - t0

        # ── Gather trade metrics ──────────────────────────────────────
        trade_metrics = self._get_trade_metrics()

        # ── Run trade analyzer ───────────────────────────────────────
        recommendations = self._run_analyzer(batch_num)
        if recommendations:
            logger.info(
                "Batch %d analyzer produced %d recommendation(s)", batch_num, len(recommendations)
            )
            for rec in recommendations[:3]:  # log top 3
                logger.info("  [%s] %s: %s", rec.priority, rec.target_node, rec.message)

        # ── Gather system health ──────────────────────────────────────
        health_score, error_rate = self._get_health_metrics()

        result = BatchResult(
            batch_num=batch_num,
            cycles_run=self.batch_size,
            started_at=started_at,
            finished_at=finished_at,
            total_pnl=trade_metrics.get("total_pnl", 0.0),
            profit_factor=trade_metrics.get("profit_factor", 0.0),
            win_rate=trade_metrics.get("win_rate", 0.0),
            n_closed=trade_metrics.get("n_closed", 0),
            n_open=trade_metrics.get("n_open", 0),
            health_score=health_score,
            error_rate=error_rate,
        )

        print(
            f"  Batch {batch_num} done in {elapsed_total:.0f}s: "
            f"trades(closed={result.n_closed} open={result.n_open})  "
            f"PnL={result.total_pnl:.2f}  pf={result.profit_factor:.3f}  "
            f"win={result.win_rate:.1%}  health={result.health_score:.3f}"
        )

        return result

    # ------------------------------------------------------------------
    # Subsystem helpers
    # ------------------------------------------------------------------

    def _get_trade_metrics(self) -> dict[str, Any]:
        """Pull metrics from the paper trading engine."""
        if self._paper_trading is None:
            return {}
        try:
            return self._paper_trading.compute_metrics()
        except Exception as exc:
            logger.warning("compute_metrics failed: %s", exc)
            return {}

    def _run_analyzer(self, batch_num: int) -> list[Any]:
        """Run the system analyzer and return recommendations."""
        if self._analyzer is None:
            return []
        try:
            return self._analyzer.analyze(cycle=batch_num * self.batch_size)
        except Exception as exc:
            logger.warning("analyzer.analyze failed: %s", exc)
            return []

    def _get_health_metrics(self) -> tuple[float, float]:
        """Return (health_score, error_rate) from metrics collector."""
        if self._metrics is None:
            return 0.0, 0.0
        try:
            health = self._metrics.system_health()
            score = health.get("composite_score", 0.0)
            err_rate = health.get("error_rate", 0.0)
            return float(score), float(err_rate)
        except Exception as exc:
            logger.warning("system_health failed: %s", exc)
            return 0.0, 0.0

    def _log_system_health(self, after_batch: int) -> None:
        """Log a system health snapshot between batches."""
        score, err_rate = self._get_health_metrics()
        logger.info(
            "System health after batch %d: score=%.3f  error_rate=%.3f",
            after_batch,
            score,
            err_rate,
        )
        print(
            f"[overnight] Health after batch {after_batch}: "
            f"score={score:.3f}  error_rate={err_rate:.3f}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        from omega.core.analyzer import SystemAnalyzer
        from omega.core.config import OmegaConfig
        from omega.core.logging import configure_logging
        from omega.core.metrics import MetricsCollector
        from omega.core.orchestrator_v2 import OmegaOrchestrator
        from omega.core.paper_trading import PaperTradingEngine
        from omega.core.state_store import make_state_backend
        from omega.nodes.victoria.victoria_node import VictoriaNode

        cfg = OmegaConfig.load(self.config_path)
        configure_logging(
            level=cfg.monitoring.log_level,
            json_output=cfg.monitoring.json_logs,
            log_file=cfg.monitoring.log_file,
        )

        self._store = make_state_backend()
        self._metrics = MetricsCollector(self._store)
        self._analyzer = SystemAnalyzer(self._store, self._metrics)

        self._orchestrator = OmegaOrchestrator(name="omega-overnight")
        self._orchestrator.register_node(VictoriaNode())

        self._paper_trading = PaperTradingEngine()
        self._orchestrator.set_paper_trading(self._paper_trading)

        logger.info("OvernightRunner setup complete")

    def _teardown(self) -> None:
        logger.info("OvernightRunner teardown")

    def _install_signal_handlers(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            logger.info("Signal %d received — stopping after current cycle", signum)
            print(f"\n[overnight] Signal {signum} received — finishing current cycle then stopping...")
            self._running = False

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self, progress: OvernightProgress) -> None:
        batches = progress.batches
        print(f"\n{'═' * 60}")
        print(f"[overnight] Run complete — status={progress.status}")
        if progress.stop_reason:
            print(f"  Stop reason: {progress.stop_reason}")
        print(f"  Batches completed: {progress.completed_batches}/{progress.total_batches}")
        if batches:
            pnls = [b.get("total_pnl", 0.0) for b in batches]
            print(f"  PnL per batch:  min={min(pnls):.2f}  max={max(pnls):.2f}  final={pnls[-1]:.2f}")
            alerts = [b for b in batches if b.get("alert_level") in ("warn", "critical")]
            if alerts:
                print(f"  Alerts raised:  {len(alerts)} batch(es)")
        print(f"  Results saved to: {RESULTS_PATH}")
        print(f"{'═' * 60}\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_progress(progress: OvernightProgress) -> None:
    try:
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(
            json.dumps(asdict(progress), indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Could not save overnight results: %s", exc)


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m omega.core.overnight_runner",
        description="Omega overnight training scheduler",
    )
    parser.add_argument(
        "--batches",
        type=int,
        default=10,
        help="Number of batches to run (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Cycles per batch (default: 200)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to omega.yml config file",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="pico",
        choices=["pico", "supervised", "autonomous"],
        help="Orchestrator mode (default: pico)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stderr,
    )
    args = _parse_args(argv)

    # Clean up any stale stop file from a previous run
    if STOP_FILE.exists():
        logger.info("Removing stale stop file %s", STOP_FILE)
        STOP_FILE.unlink(missing_ok=True)

    runner = OvernightRunner(
        total_batches=args.batches,
        batch_size=args.batch_size,
        config_path=args.config,
        mode=args.mode,
    )
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
