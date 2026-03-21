"""Tests for omega.core.logging — JSON structured logger."""

import json
import logging
from io import StringIO

import pytest

from omega.core.logging import _JsonFormatter, bound_logger, configure_logging, get_logger


def _capture_log(level: str = "DEBUG") -> tuple[logging.Logger, StringIO]:
    """Return a logger with a StringIO handler for test inspection."""
    log = logging.getLogger(f"omega.test.{__name__}.{level}")
    log.setLevel(getattr(logging, level))
    log.handlers.clear()
    log.propagate = False
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JsonFormatter())
    log.addHandler(handler)
    return log, buf


class TestJsonFormatter:
    def test_output_is_valid_json(self):
        log, buf = _capture_log()
        log.info("hello world")
        line = buf.getvalue().strip()
        record = json.loads(line)
        assert record["message"] == "hello world"

    def test_standard_fields_present(self):
        log, buf = _capture_log()
        log.warning("test warning")
        record = json.loads(buf.getvalue())
        assert "timestamp" in record
        assert "level" in record
        assert "logger" in record
        assert record["level"] == "WARNING"

    def test_correlation_fields_included_when_present(self):
        log, buf = _capture_log()
        log.info("ctx msg", extra={"node_id": "n-01", "trace_id": "abc", "cycle_id": 3})
        record = json.loads(buf.getvalue())
        assert record["node_id"] == "n-01"
        assert record["trace_id"] == "abc"
        assert record["cycle_id"] == 3

    def test_correlation_fields_absent_when_not_set(self):
        log, buf = _capture_log()
        log.info("plain msg")
        record = json.loads(buf.getvalue())
        assert "node_id" not in record
        assert "trace_id" not in record

    def test_extra_fields_included(self):
        log, buf = _capture_log()
        log.info("with extra", extra={"latency_ms": 42.5, "symbol": "BTCUSDT"})
        record = json.loads(buf.getvalue())
        assert record["latency_ms"] == 42.5
        assert record["symbol"] == "BTCUSDT"

    def test_exception_info_included(self):
        log, buf = _capture_log()
        try:
            raise ValueError("test error")
        except ValueError:
            log.exception("caught exception")
        record = json.loads(buf.getvalue())
        assert "exception" in record
        assert "ValueError" in record["exception"]

    def test_timestamp_is_iso8601(self):
        log, buf = _capture_log()
        log.info("ts test")
        record = json.loads(buf.getvalue())
        ts = record["timestamp"]
        # Should contain T and +00:00 (UTC)
        assert "T" in ts
        assert "+" in ts or "Z" in ts or ts.endswith("+00:00")


class TestGetLogger:
    def test_omega_prefix_added(self):
        log = get_logger("core.mymodule")
        assert log.name.startswith("omega.")

    def test_omega_prefix_not_doubled(self):
        log = get_logger("omega.core.mymodule")
        assert log.name == "omega.core.mymodule"

    def test_returns_logger_instance(self):
        log = get_logger("omega.test")
        assert isinstance(log, logging.Logger)


class TestConfigureLogging:
    def test_idempotent(self):
        """Calling configure_logging twice does not duplicate handlers."""
        root = logging.getLogger("omega")
        root.handlers.clear()
        configure_logging(level="INFO")
        configure_logging(level="DEBUG")  # second call — should be a no-op
        assert len(root.handlers) == 1
        root.handlers.clear()

    def test_sets_correct_level(self):
        root = logging.getLogger("omega")
        root.handlers.clear()
        configure_logging(level="DEBUG")
        assert root.level == logging.DEBUG
        root.handlers.clear()


class TestBoundLogger:
    def test_pre_fills_correlation_fields(self):
        log, buf = _capture_log()
        ctx = bound_logger(log, node_id="n-99", trace_id="trace-abc", cycle_id=7)
        ctx.info("bound message")
        record = json.loads(buf.getvalue())
        assert record["node_id"] == "n-99"
        assert record["trace_id"] == "trace-abc"
        assert record["cycle_id"] == 7

    def test_extra_merged_with_base(self):
        log, buf = _capture_log()
        ctx = bound_logger(log, node_id="n-01")
        ctx.info("with extra", extra={"latency_ms": 100})
        record = json.loads(buf.getvalue())
        assert record["node_id"] == "n-01"
        assert record["latency_ms"] == 100

    def test_extra_overrides_base(self):
        """Caller-supplied extra should win over bound fields if keys clash."""
        log, buf = _capture_log()
        ctx = bound_logger(log, node_id="base-node")
        ctx.info("override", extra={"node_id": "override-node"})
        record = json.loads(buf.getvalue())
        assert record["node_id"] == "override-node"

    def test_all_log_levels(self):
        log, buf = _capture_log("DEBUG")
        ctx = bound_logger(log, node_id="test")
        ctx.debug("d")
        ctx.info("i")
        ctx.warning("w")
        ctx.error("e")
        lines = [l for l in buf.getvalue().strip().split("\n") if l]
        levels = [json.loads(l)["level"] for l in lines]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR"]
