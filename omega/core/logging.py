"""
omega.core.logging
~~~~~~~~~~~~~~~~~~
JSON structured logging for the Omega framework (12-factor style).

All log records are emitted as single-line JSON to stdout. An optional
secondary file handler can also be configured.

Correlation fields
------------------
Four extra fields propagate context through the call chain:

  node_id   — the emitting node's unique ID
  trace_id  — distributed trace ID (from TraceContext.trace_id)
  span_id   — current span ID (from TraceContext.span_id)
  cycle_id  — heartbeat cycle number (int)

Pass them via ``extra={"node_id": ..., "trace_id": ..., ...}`` or by
using the :func:`bound_logger` helper which pre-fills them.

Log-level semantics
-------------------
DEBUG   — every metric, raw API response, span start/end
INFO    — cycle summaries, node improvements, system events
WARNING — alignment rejections, adversarial flags, degraded data
ERROR   — node failures, unrecoverable store errors

Usage::

    from omega.core.logging import configure_logging, get_logger, bound_logger

    configure_logging(level="INFO", json_output=True)

    log = get_logger("omega.nodes.vectora.data_ingestion")
    log.info("Fetched market data", extra={"node_id": "ingestion-01", "cycle_id": 3})

    # Or pre-bind correlation fields for a whole node:
    ctx_log = bound_logger(log, node_id="ingestion-01", trace_id="abc123")
    ctx_log.debug("raw response", extra={"symbol": "BTCUSDT", "latency_ms": 42})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Internal formatter
# ---------------------------------------------------------------------------

_STANDARD_LOG_FIELDS: frozenset = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    # correlation fields — handled explicitly, not duplicated
    "node_id", "trace_id", "span_id", "cycle_id",
    # internal python logging bookkeeping
    "taskName",
})

_CORRELATION_FIELDS = ("node_id", "trace_id", "span_id", "cycle_id")


class _JsonFormatter(logging.Formatter):
    """Formats a :class:`logging.LogRecord` as a single-line JSON string."""

    def format(self, record: logging.LogRecord) -> str:
        # Ensure getMessage() has been called so record.message is set
        record.message = record.getMessage()

        out: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Correlation fields — only include if present and non-None
        for field in _CORRELATION_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                out[field] = value

        # Exception info
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)

        # Any extra fields the caller passed that aren't standard log fields
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_FIELDS and not key.startswith("_"):
                out[key] = value

        return json.dumps(out, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure the root ``omega`` logger.

    Call **once** at application startup (typically from ``main()``).
    Subsequent calls are idempotent — if handlers are already attached
    they won't be duplicated.

    Args:
        level:       Log level name: ``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
                     ``"ERROR"``.
        json_output: If ``True`` (default), emit JSON lines to stdout.
                     If ``False``, use a human-readable format (handy for
                     interactive development).
        log_file:    Optional filesystem path for a secondary JSON log file.
    """
    root = logging.getLogger("omega")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Idempotent — don't add duplicate handlers
    if root.handlers:
        return

    stdout_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        stdout_handler.setFormatter(_JsonFormatter())
    else:
        stdout_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    root.addHandler(stdout_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(_JsonFormatter())
        root.addHandler(file_handler)

    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger in the ``omega.*`` namespace.

    If *name* doesn't start with ``"omega"`` it is automatically prefixed.

    Args:
        name: Logger name, e.g. ``"omega.core.state_store"`` or just
              ``"core.state_store"``.
    """
    if not name.startswith("omega"):
        name = f"omega.{name}"
    return logging.getLogger(name)


class bound_logger:  # noqa: N801 — intentionally lowercase for ergonomics
    """A thin wrapper that pre-fills correlation fields on every log call.

    This avoids repeating ``extra={"node_id": ..., "trace_id": ...}``
    on every log statement inside a node or heartbeat cycle.

    Example::

        log = bound_logger(
            get_logger("omega.nodes.vectora.ingestion"),
            node_id="ingestion-01",
            trace_id="abc123",
            cycle_id=5,
        )
        log.info("Fetched data", extra={"latency_ms": 120})
        log.warning("Stale data", extra={"age_hours": 2.5})
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        node_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        cycle_id: int | None = None,
    ) -> None:
        self._logger = logger
        self._base_extra: dict[str, Any] = {}
        if node_id is not None:
            self._base_extra["node_id"] = node_id
        if trace_id is not None:
            self._base_extra["trace_id"] = trace_id
        if span_id is not None:
            self._base_extra["span_id"] = span_id
        if cycle_id is not None:
            self._base_extra["cycle_id"] = cycle_id

    def _extra(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(self._base_extra)
        if extra:
            merged.update(extra)
        return merged

    def debug(self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._logger.debug(msg, *args, extra=self._extra(extra), **kw)

    def info(self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._logger.info(msg, *args, extra=self._extra(extra), **kw)

    def warning(self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._logger.warning(msg, *args, extra=self._extra(extra), **kw)

    def error(self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._logger.error(msg, *args, extra=self._extra(extra), **kw)

    def exception(self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._logger.exception(msg, *args, extra=self._extra(extra), **kw)
