"""Data pipeline orchestrator — polls multiple sources and feeds signal generators."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from omega.data.base import DataBuffer, DataSource, MarketData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (optional — gracefully degraded if not installed)
# ---------------------------------------------------------------------------

_fetch_latency: Any = None
_fetch_errors: Any = None
_data_staleness: Any = None
_PROMETHEUS_AVAILABLE = False

try:
    from prometheus_client import (  # type: ignore[import-untyped,unused-ignore]
        Counter,
        Gauge,
        Histogram,
    )

    _fetch_latency = Histogram(
        "omega_data_fetch_latency_seconds",
        "Latency of data fetch operations",
        ["source", "symbol"],
    )
    _fetch_errors = Counter(
        "omega_data_fetch_errors_total",
        "Total data fetch errors",
        ["source", "symbol"],
    )
    _data_staleness = Gauge(
        "omega_data_staleness_seconds",
        "Seconds since last successful data fetch",
        ["source"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    pass


def _observe_latency(source: str, symbol: str, seconds: float) -> None:
    if _PROMETHEUS_AVAILABLE and _fetch_latency:
        _fetch_latency.labels(source=source, symbol=symbol).observe(seconds)


def _inc_errors(source: str, symbol: str) -> None:
    if _PROMETHEUS_AVAILABLE and _fetch_errors:
        _fetch_errors.labels(source=source, symbol=symbol).inc()


def _set_staleness(source: str, seconds: float) -> None:
    if _PROMETHEUS_AVAILABLE and _data_staleness:
        _data_staleness.labels(source=source).set(seconds)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SourceConfig:
    """Configuration for a single data source in the pipeline."""

    source: DataSource
    symbols: list[str]
    poll_interval_secs: float = 5.0
    max_retries: int = 3
    backoff_base_secs: float = 2.0
    fallback_source: DataSource | None = None
    priority: int = 0  # lower = higher priority


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class DataPipeline:
    """Orchestrates multiple DataSources, polls them, and routes data to consumers.

    Consumers subscribe via callbacks or read from per-symbol DataBuffers.
    """

    def __init__(self, buffer_size: int = 500) -> None:
        self._configs: list[SourceConfig] = []
        self._buffers: dict[str, DataBuffer[MarketData]] = {}
        self._callbacks: list[Callable[[MarketData], None]] = []
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._buffer_size = buffer_size
        self._lock = threading.Lock()
        self._running = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_source(self, config: SourceConfig) -> DataPipeline:
        """Register a data source with the pipeline."""
        with self._lock:
            self._configs.append(config)
            for symbol in config.symbols:
                if symbol not in self._buffers:
                    self._buffers[symbol] = DataBuffer(maxlen=self._buffer_size)
        logger.info(
            "Added source '%s' for symbols %s (poll=%.1fs)",
            config.source.name,
            config.symbols,
            config.poll_interval_secs,
        )
        return self

    def on_data(self, callback: Callable[[MarketData], None]) -> DataPipeline:
        """Register a callback invoked on every new data point."""
        self._callbacks.append(callback)
        return self

    def get_buffer(self, symbol: str) -> DataBuffer[MarketData] | None:
        """Get the ring buffer for a symbol."""
        return self._buffers.get(symbol)

    def latest(self, symbol: str) -> MarketData | None:
        """Get the most recent data point for a symbol."""
        buf = self._buffers.get(symbol)
        if buf is None or len(buf) == 0:
            return None
        items = buf.peek(1)
        return items[0] if items else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background polling threads for all sources."""
        if self._running:
            return
        self._stop_event.clear()
        self._running = True

        # Connect all sources
        for cfg in self._configs:
            try:
                cfg.source.connect()
            except Exception as exc:
                logger.error("Failed to connect source '%s': %s", cfg.source.name, exc)

        # Start a polling thread per source
        for cfg in self._configs:
            t = threading.Thread(
                target=self._poll_loop,
                args=(cfg,),
                daemon=True,
                name=f"pipeline:{cfg.source.name}",
            )
            t.start()
            self._threads.append(t)

        logger.info("DataPipeline started with %d source(s)", len(self._configs))

    def stop(self) -> None:
        """Signal all polling threads to stop and disconnect sources."""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=10)
        self._threads.clear()

        for cfg in self._configs:
            try:
                cfg.source.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting '%s': %s", cfg.source.name, exc)

        self._running = False
        logger.info("DataPipeline stopped")

    def __enter__(self) -> DataPipeline:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal polling
    # ------------------------------------------------------------------

    def _poll_loop(self, cfg: SourceConfig) -> None:
        """Background thread: polls one source for all its symbols."""
        consecutive_errors: dict[str, int] = {s: 0 for s in cfg.symbols}

        while not self._stop_event.is_set():
            loop_start = time.monotonic()

            for symbol in cfg.symbols:
                if self._stop_event.is_set():
                    break
                self._fetch_with_retry(cfg, symbol, consecutive_errors)

            # Sleep the remainder of the poll interval
            elapsed = time.monotonic() - loop_start
            sleep_secs = max(0.0, cfg.poll_interval_secs - elapsed)
            self._stop_event.wait(timeout=sleep_secs)

    def _fetch_with_retry(
        self,
        cfg: SourceConfig,
        symbol: str,
        error_counts: dict[str, int],
    ) -> None:
        source = cfg.source
        for attempt in range(cfg.max_retries):
            t0 = time.monotonic()
            try:
                md = source.get_snapshot(symbol)
                latency = time.monotonic() - t0

                if md is not None:
                    _observe_latency(source.name, symbol, latency)
                    _set_staleness(source.name, 0.0)
                    error_counts[symbol] = 0
                    self._dispatch(md)
                    return
                else:
                    logger.debug("No data from '%s' for %s", source.name, symbol)

            except Exception as exc:
                latency = time.monotonic() - t0
                _inc_errors(source.name, symbol)
                logger.warning(
                    "Fetch error '%s'/%s attempt %d/%d: %s",
                    source.name,
                    symbol,
                    attempt + 1,
                    cfg.max_retries,
                    exc,
                )

            # Exponential backoff before retry
            if attempt < cfg.max_retries - 1:
                backoff = cfg.backoff_base_secs * (2**attempt)
                self._stop_event.wait(timeout=backoff)

        # All retries exhausted — try fallback
        error_counts[symbol] = error_counts.get(symbol, 0) + 1
        _set_staleness(source.name, source.last_fetch_age)

        if cfg.fallback_source is not None:
            self._try_fallback(cfg.fallback_source, symbol)

    def _try_fallback(self, fallback: DataSource, symbol: str) -> None:
        try:
            if not fallback.connected:
                fallback.connect()
            md = fallback.get_snapshot(symbol)
            if md is not None:
                logger.info("Fallback '%s' provided data for %s", fallback.name, symbol)
                self._dispatch(md)
        except Exception as exc:
            logger.warning("Fallback '%s' also failed for %s: %s", fallback.name, symbol, exc)

    def _dispatch(self, md: MarketData) -> None:
        """Push data to buffer and invoke callbacks."""
        buf = self._buffers.get(md.symbol)
        if buf is not None:
            buf.push(md)

        for cb in self._callbacks:
            try:
                cb(md)
            except Exception as exc:
                logger.warning("Callback error for %s: %s", md.symbol, exc)

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def health(self) -> dict[str, object]:
        """Return a summary of pipeline health."""
        return {
            "running": self._running,
            "sources": [
                {
                    "name": cfg.source.name,
                    "connected": cfg.source.connected,
                    "error_count": cfg.source._error_count,
                    "last_fetch_age_secs": round(cfg.source.last_fetch_age, 2),
                    "symbols": cfg.symbols,
                }
                for cfg in self._configs
            ],
            "buffers": {symbol: len(buf) for symbol, buf in self._buffers.items()},
        }
