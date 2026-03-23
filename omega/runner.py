"""
omega.runner
~~~~~~~~~~~~
Runtime orchestration — wires all subsystems together and drives the
heartbeat loop.

Usage::

    runner = OmegaRunner(config_path="omega.yml", mode="pico")
    sys.exit(runner.run())
"""

from __future__ import annotations

import contextlib
import logging
import signal
import time
from typing import Any

logger = logging.getLogger("omega.runner")


class OmegaRunner:
    """
    Initialises all Omega subsystems from a YAML config and runs the
    heartbeat loop until stopped.

    Parameters
    ----------
    config_path:
        Path to ``omega.yml`` (or ``omega.example.yml``).  When *None* the
        loader searches the working directory automatically.
    mode:
        ``"pico"`` — no LLM calls, rules-only signals.
        ``"supervised"`` — LLM generates suggestions; human approves.
        ``"autonomous"`` — full self-improvement enabled.
    symbols:
        Override the symbol list from config.
    dry_run:
        When *True* the loop runs but no trades / state mutations are
        committed to storage.
    heartbeat_override:
        Override heartbeat interval (seconds) from config.
    max_iterations:
        Stop after this many heartbeat cycles (``None`` = run forever).
    """

    def __init__(
        self,
        config_path: str | None = None,
        mode: str = "pico",
        symbols: list[str] | None = None,
        dry_run: bool = False,
        heartbeat_override: int | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.config_path = config_path
        self.mode = mode
        self.symbols = symbols
        self.dry_run = dry_run
        self.heartbeat_override = heartbeat_override
        self.max_iterations = max_iterations

        self._running = False
        self._cfg: Any = None
        self._store: Any = None
        self._exporter: Any = None
        self._orchestrator: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Blocking entry point.  Returns an exit code."""
        self._setup()
        self._install_signal_handlers()
        self._running = True

        heartbeat: int = self.heartbeat_override or int(
            getattr(self._cfg, "heartbeat_interval_sec", 60) or 60
        )

        logger.info(
            "Omega runner started  mode=%s  dry_run=%s  heartbeat=%ds",
            self.mode,
            self.dry_run,
            heartbeat,
        )

        iteration = 0
        while self._running:
            if self.max_iterations is not None and iteration >= self.max_iterations:
                logger.info("Reached max_iterations=%d, stopping.", self.max_iterations)
                break

            t0 = time.monotonic()
            try:
                self._heartbeat(iteration)
            except Exception as exc:
                logger.error("Heartbeat %d failed: %s", iteration, exc, exc_info=True)

            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, heartbeat - elapsed)
            iteration += 1

            if self._running and sleep_time > 0:
                self._interruptible_sleep(sleep_time)

        self._teardown()
        logger.info("Omega runner stopped after %d iterations.", iteration)
        return 0

    def stop(self) -> None:
        """Request a graceful shutdown from another thread."""
        logger.info("Stop requested.")
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        """Load config and initialise all subsystems."""
        from omega.core.config import OmegaConfig
        from omega.core.logging import configure_logging
        from omega.core.metrics_exporter import MetricsExporter
        from omega.core.orchestrator_v2 import OmegaOrchestrator
        from omega.core.state_store import make_state_backend

        self._cfg = OmegaConfig.load(self.config_path)

        configure_logging(
            level=self._cfg.monitoring.log_level,
            json_output=self._cfg.monitoring.json_logs,
            log_file=self._cfg.monitoring.log_file,
        )

        # Override symbols if provided on CLI
        if self.symbols:
            self._cfg.data.symbols = self.symbols

        logger.info("Config loaded  symbols=%s", self._cfg.data.symbols)

        self._store = make_state_backend()

        self._exporter = MetricsExporter(state_store=self._store)
        self._exporter.start()
        logger.info(
            "Metrics exporter started on port %d",
            self._cfg.monitoring.metrics_port,
        )

        self._orchestrator = OmegaOrchestrator(name="omega", metrics_exporter=self._exporter)

        self._setup_nodes()

    def _setup_nodes(self) -> None:
        """Register VictoriaNode with the orchestrator."""
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        self._orchestrator.register_node(node)

        logger.info("Registered VictoriaNode.")

    def _teardown(self) -> None:
        if self._exporter:
            with contextlib.suppress(Exception):
                self._exporter.stop()

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat(self, iteration: int) -> None:
        logger.debug("Heartbeat %d start", iteration)

        result = self._orchestrator.run_one_cycle()

        duration = 0.0
        if result and isinstance(result, dict):
            duration = float(result.get("duration_seconds", 0.0))

        if self._exporter:
            self._exporter.record_heartbeat(duration_seconds=duration)

        logger.debug("Heartbeat %d complete", iteration)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            logger.info("Signal %d received, shutting down…", signum)
            self._running = False

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in small chunks so SIGINT is handled promptly."""
        end = time.monotonic() + seconds
        while self._running:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.25))
