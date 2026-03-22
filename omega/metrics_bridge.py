"""
omega.metrics_bridge
~~~~~~~~~~~~~~~~~~~~~
OpenTelemetry metrics bridge for Python signal generation layer.

Exposes three key signal-quality metrics to the OTLP collector:
  - omega.signal.ic_per_bar       — Information Coefficient per bar processed
  - omega.signal.generation.latency — Time to generate signals (seconds)
  - omega.signal.tpe.trial_score  — Scores from TPE optimization trials

If the ``opentelemetry-sdk`` package is not installed the bridge falls back to
a lightweight SQLite-backed file store at ``/tmp/omega_metrics_bridge.db`` that
the Go side can poll via a periodic scrape job.

Usage::

    from omega.metrics_bridge import MetricsBridge

    bridge = MetricsBridge()
    bridge.record_signal_generation(latency_s=0.042, ticker_count=5)
    bridge.record_ic_per_bar(signal_name="sma_crossover", ic=0.12)
    bridge.record_tpe_trial(trial_number=7, score=0.89, is_best=True)
    bridge.shutdown()  # flush on exit
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import TYPE_CHECKING

logger = logging.getLogger("omega.metrics_bridge")

# ---------------------------------------------------------------------------
# Try to import the OTel SDK — fall back gracefully if not installed
# ---------------------------------------------------------------------------

_OTEL_AVAILABLE = False
try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    _OTEL_AVAILABLE = True
except ImportError:
    logger.info("opentelemetry-sdk not installed — metrics bridge will use SQLite fallback")

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram, Meter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://localhost:4318")
_BRIDGE_DB_PATH = os.environ.get(
    "OMEGA_BRIDGE_DB",
    os.path.join(os.environ.get("OMEGA_DATA_DIR", "./data"), "omega_metrics_bridge.db"),
)
_EXPORT_INTERVAL_MS = 15_000  # 15 s — matches Go side


# ---------------------------------------------------------------------------
# MetricsBridge
# ---------------------------------------------------------------------------


class MetricsBridge:
    """
    OTel-backed (or SQLite-backed) metrics bridge for the Python signal layer.

    Instantiate once per process, then call the record_* methods from signal
    generation code. Call shutdown() before process exit to flush pending data.
    """

    def __init__(
        self,
        otlp_endpoint: str = _DEFAULT_OTLP_ENDPOINT,
        service_name: str = "omega-python",
        service_version: str = "0.1.0",
    ) -> None:
        self._otlp_endpoint = otlp_endpoint
        self._service_name = service_name
        self._provider: MeterProvider | None = None
        self._meter: Meter | None = None

        # OTel instruments (populated in _init_otel)
        self._ic_histogram: Histogram | None = None
        self._generation_latency: Histogram | None = None
        self._tpe_score_histogram: Histogram | None = None
        self._signal_error_counter: Counter | None = None

        if _OTEL_AVAILABLE:
            self._init_otel(service_name, service_version, otlp_endpoint)
        else:
            self._init_sqlite()

    # ------------------------------------------------------------------
    # Public recording API
    # ------------------------------------------------------------------

    def record_signal_generation(
        self,
        latency_s: float,
        ticker_count: int = 0,
        signal_version: str = "unknown",
        success: bool = True,
    ) -> None:
        """Record a completed signal generation pass."""
        attrs = {
            "omega.signal.version": signal_version,
            "omega.signal.ticker_count": str(ticker_count),
            "outcome": "success" if success else "error",
        }

        if self._generation_latency is not None:
            self._generation_latency.record(latency_s, attributes=attrs)
        else:
            self._sqlite_record(
                "signal_generation_latency",
                latency_s,
                {"version": signal_version, "success": str(success)},
            )

        if not success and self._signal_error_counter is not None:
            self._signal_error_counter.add(1, attributes=attrs)

    def record_ic_per_bar(
        self,
        ic: float,
        signal_name: str = "composite",
        ticker: str = "",
    ) -> None:
        """Record an Information Coefficient observation for a signal."""
        attrs = {
            "omega.signal.indicator": signal_name,
            "omega.signal.ticker": ticker,
        }

        if self._ic_histogram is not None:
            self._ic_histogram.record(ic, attributes=attrs)
        else:
            self._sqlite_record(
                "ic_per_bar",
                ic,
                {"signal": signal_name, "ticker": ticker},
            )

    def record_tpe_trial(
        self,
        score: float,
        trial_number: int = 0,
        is_best: bool = False,
        signal_name: str = "composite",
    ) -> None:
        """Record a TPE optimization trial score."""
        attrs = {
            "omega.signal.indicator": signal_name,
            "is_best": str(is_best),
            "trial": str(trial_number),
        }

        if self._tpe_score_histogram is not None:
            self._tpe_score_histogram.record(score, attributes=attrs)
        else:
            self._sqlite_record(
                "tpe_trial_score",
                score,
                {"trial": str(trial_number), "is_best": str(is_best)},
            )

    def shutdown(self) -> None:
        """Flush pending metrics and release resources."""
        if self._provider is not None:
            try:
                self._provider.shutdown()
            except Exception:
                logger.exception("MetricsBridge: error during OTel shutdown")

    # ------------------------------------------------------------------
    # OTel initialisation
    # ------------------------------------------------------------------

    def _init_otel(
        self,
        service_name: str,
        service_version: str,
        otlp_endpoint: str,
    ) -> None:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "telemetry.sdk.language": "python",
            }
        )

        exporter = OTLPMetricExporter(
            endpoint=otlp_endpoint + "/v1/metrics",
            headers={},
        )
        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=_EXPORT_INTERVAL_MS,
        )
        self._provider = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(self._provider)
        self._meter = self._provider.get_meter("omega.python", version=service_version)

        self._ic_histogram = self._meter.create_histogram(
            name="omega.signal.ic_per_bar",
            unit="1",
            description="Information Coefficient per bar for each signal",
        )
        self._generation_latency = self._meter.create_histogram(
            name="omega.signal.generation.latency",
            unit="s",
            description="Time to run a full signal generation pass",
        )
        self._tpe_score_histogram = self._meter.create_histogram(
            name="omega.signal.tpe.trial_score",
            unit="1",
            description="TPE hyperparameter optimization trial scores",
        )
        self._signal_error_counter = self._meter.create_counter(
            name="omega.signal.errors",
            description="Count of signal generation errors",
        )
        logger.info(
            "MetricsBridge: OTel initialised (endpoint=%s, service=%s)",
            otlp_endpoint,
            service_name,
        )

    # ------------------------------------------------------------------
    # SQLite fallback — Go polls this DB when OTel SDK is unavailable
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        self._db = sqlite3.connect(_BRIDGE_DB_PATH, check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS omega_metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                metric_name TEXT    NOT NULL,
                value       REAL    NOT NULL,
                attrs_json  TEXT    NOT NULL DEFAULT '{}'
            )
        """)
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_metrics_name_ts ON omega_metrics(metric_name, ts)"
        )
        self._db.commit()
        logger.info("MetricsBridge: using SQLite fallback at %s", _BRIDGE_DB_PATH)

    def _sqlite_record(self, metric_name: str, value: float, attrs: dict[str, str]) -> None:
        import json

        try:
            self._db.execute(
                "INSERT INTO omega_metrics(ts, metric_name, value, attrs_json) VALUES(?,?,?,?)",
                (time.time(), metric_name, value, json.dumps(attrs)),
            )
            self._db.commit()
        except Exception:
            logger.exception("MetricsBridge: SQLite write failed for %s", metric_name)


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly
# ---------------------------------------------------------------------------

_bridge: MetricsBridge | None = None


def get_bridge() -> MetricsBridge:
    """Return (or lazily create) the module-level MetricsBridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = MetricsBridge()
    return _bridge
