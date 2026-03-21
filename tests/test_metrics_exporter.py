"""
tests.test_metrics_exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for omega.core.metrics_exporter.

All tests run without any external dependencies (stdlib only).
A real in-memory StateStore is used to verify DB-backed metric rendering.
"""

import threading
import time
import urllib.request

import pytest

from omega.core.metrics_exporter import MetricsExporter, _Histogram, _labels, _sanitize
from omega.core.state_store import StateStore

# ---------------------------------------------------------------------------
# _Histogram unit tests
# ---------------------------------------------------------------------------

class TestHistogram:
    def test_observe_single_value(self):
        h = _Histogram()
        h.observe(0.05)
        lines = h.render("test_histo", {})
        assert "test_histo_count 1" in lines
        assert "test_histo_sum" in "\n".join(lines)

    def test_observe_multiple_values(self):
        h = _Histogram()
        h.observe(0.1)
        h.observe(0.2)
        h.observe(5.0)
        lines = h.render("test_histo", {})
        count_line = next(l for l in lines if l.startswith("test_histo_count"))
        assert count_line == "test_histo_count 3"

    def test_bucket_cumulative_counts(self):
        h = _Histogram()
        h.observe(0.002)   # fits in 0.005 bucket and above
        h.observe(0.1)     # fits in 0.1 bucket and above
        lines = "\n".join(h.render("h", {}))
        # le="0.001" should have 0 observations
        assert 'le="0.001"} 0' in lines
        # le="0.005" should have 1 (the 0.002 observation)
        assert 'le="0.005"} 1' in lines
        # le="+Inf" should have 2
        assert 'le="+Inf"} 2' in lines

    def test_render_with_labels(self):
        h = _Histogram()
        h.observe(0.5)
        lines = "\n".join(h.render("h", {"node_id": "abc", "node_type": "TestNode"}))
        assert 'node_id="abc"' in lines
        assert 'node_type="TestNode"' in lines

    def test_sum_accuracy(self):
        h = _Histogram()
        h.observe(1.0)
        h.observe(2.0)
        h.observe(3.0)
        lines = h.render("h", {})
        sum_line = next(l for l in lines if l.startswith("h_sum"))
        assert "6.0" in sum_line

    def test_thread_safety(self):
        h = _Histogram()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    h.observe(0.1)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        lines = h.render("h", {})
        count_line = next(l for l in lines if l.startswith("h_count"))
        assert count_line == "h_count 1000"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_labels_empty(self):
        assert _labels({}) == ""

    def test_labels_single(self):
        result = _labels({"key": "val"})
        assert result == 'key="val"'

    def test_labels_multiple(self):
        result = _labels({"a": "1", "b": "2"})
        assert 'a="1"' in result
        assert 'b="2"' in result

    def test_sanitize_quotes(self):
        assert '"' not in _sanitize('say "hello"')

    def test_sanitize_newlines(self):
        assert '\n' not in _sanitize("line1\nline2")


# ---------------------------------------------------------------------------
# MetricsExporter with real StateStore
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    return StateStore(db_path=":memory:")


@pytest.fixture
def exporter(store):
    return MetricsExporter(state_store=store)


class TestMetricsExporterRender:
    def test_render_returns_string(self, exporter):
        output = exporter.render()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_render_contains_required_metric_names(self, exporter):
        output = exporter.render()
        expected = [
            "omega_up",
            "omega_process_start_time_seconds",
            "omega_node_execution_duration_seconds",
            "omega_node_execution_total",
            "omega_improvement_cycle_total",
            "omega_alignment_decision_total",
            "omega_adversarial_flags_total",
            "omega_brain_request_total",
            "omega_brain_latency_seconds",
            "omega_memory_entries_total",
            "omega_challenge_registry_total",
            "omega_signal_value",
            "omega_portfolio_exposure",
            "omega_heartbeat_duration_seconds",
        ]
        for name in expected:
            assert name in output, f"Missing metric: {name}"

    def test_render_has_help_and_type_lines(self, exporter):
        output = exporter.render()
        assert "# HELP" in output
        assert "# TYPE" in output

    def test_omega_up_is_one(self, exporter):
        output = exporter.render()
        assert "omega_up 1" in output

    def test_node_execution_total_from_db(self, store, exporter):
        # Seed some executions into the StateStore
        node_id = "node-abc"
        store._conn.execute(
            "INSERT INTO nodes (node_id, name, version, capabilities_json, health, registered_at, last_updated) "
            "VALUES (?, ?, '1.0', '[]', 1.0, ?, ?)",
            (node_id, "TestNode", time.time(), time.time()),
        )
        store._conn.execute(
            "INSERT INTO node_executions "
            "(exec_id, node_id, node_name, action, started_at, ended_at, duration_ms, success, cycle) "
            "VALUES ('e1', ?, 'TestNode', 'run', ?, ?, 50.0, 1, 0)",
            (node_id, time.time(), time.time()),
        )
        store._conn.execute(
            "INSERT INTO node_executions "
            "(exec_id, node_id, node_name, action, started_at, ended_at, duration_ms, success, cycle) "
            "VALUES ('e2', ?, 'TestNode', 'run', ?, ?, 30.0, 0, 0)",
            (node_id, time.time(), time.time()),
        )
        store._conn.commit()

        output = exporter.render()
        assert 'status="success"} 1' in output
        assert 'status="failure"} 1' in output

    def test_improvement_cycle_total_from_db(self, store, exporter):
        store._conn.execute(
            "INSERT INTO improvement_log "
            "(improve_id, node_id, node_name, from_version, to_version, triggered_by, recorded_at, cycle) "
            "VALUES ('imp1', 'nid', 'TestNode', '1.0', '1.1', 'metrics', ?, 0)",
            (time.time(),),
        )
        store._conn.commit()

        output = exporter.render()
        assert 'result="improved"} 1' in output

    def test_memory_entries_no_memory_kernel(self, exporter):
        output = exporter.render()
        assert 'memory_type="episodic"} 0' in output
        assert 'memory_type="semantic"} 0' in output
        assert 'memory_type="working"} 0' in output


class TestMetricsExporterRecordMethods:
    def test_record_heartbeat(self, exporter):
        exporter.record_heartbeat(4.5)
        output = exporter.render()
        assert "omega_heartbeat_duration_seconds_count 1" in output

    def test_record_node_execution(self, exporter):
        exporter.record_node_execution("node-1", "DataNode", 0.15, success=True)
        output = exporter.render()
        assert "omega_node_execution_duration_seconds" in output
        assert "DataNode" in output

    def test_record_brain_request(self, exporter):
        exporter.record_brain_request("node-1", "anthropic", 0.8)
        output = exporter.render()
        assert "omega_brain_latency_seconds" in output
        assert "anthropic" in output

    def test_record_improvement(self, exporter):
        exporter.record_improvement("rejected")
        output = exporter.render()
        assert 'result="rejected"} 1' in output

    def test_record_alignment_decision(self, exporter):
        exporter.record_alignment_decision("approved")
        exporter.record_alignment_decision("rejected")
        output = exporter.render()
        assert 'decision="approved"} 1' in output
        assert 'decision="rejected"} 1' in output

    def test_record_adversarial_flag(self, exporter):
        exporter.record_adversarial_flag("ring1", "critical")
        output = exporter.render()
        assert 'ring="ring1"' in output
        assert 'severity="critical"' in output

    def test_update_signals_dict(self, exporter):
        exporter.update_signals({
            "BTCUSDT": {"composite": 0.75},
            "ETHUSDT": {"composite": -0.3},
        })
        output = exporter.render()
        assert 'symbol="BTC"' in output
        assert 'symbol="ETH"' in output
        assert "0.750000" in output

    def test_update_portfolio_exposure(self, exporter):
        exporter.update_portfolio_exposure(0.65)
        output = exporter.render()
        assert "omega_portfolio_exposure 0.650000" in output

    def test_multiple_records_accumulate(self, exporter):
        exporter.record_heartbeat(3.0)
        exporter.record_heartbeat(4.0)
        exporter.record_heartbeat(5.0)
        output = exporter.render()
        assert "omega_heartbeat_duration_seconds_count 3" in output

    def test_multiple_nodes_separate_histograms(self, exporter):
        exporter.record_node_execution("node-1", "NodeA", 0.1, success=True)
        exporter.record_node_execution("node-2", "NodeB", 0.2, success=True)
        output = exporter.render()
        assert "NodeA" in output
        assert "NodeB" in output


# ---------------------------------------------------------------------------
# HTTP server integration test
# ---------------------------------------------------------------------------

class TestMetricsHTTPServer:
    def test_metrics_endpoint_returns_200(self, store):
        exporter = MetricsExporter(state_store=store, port=19090)
        exporter.start(daemon=True)
        time.sleep(0.1)  # brief wait for server to bind

        url = "http://localhost:19090/metrics"
        with urllib.request.urlopen(url, timeout=3) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "omega_up 1" in body
        assert "# HELP" in body

    def test_unknown_path_returns_404(self, store):
        exporter = MetricsExporter(state_store=store, port=19091)
        exporter.start(daemon=True)
        time.sleep(0.1)

        url = "http://localhost:19091/unknown"
        try:
            urllib.request.urlopen(url, timeout=3)
            assert False, "Expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

    def test_content_type_header(self, store):
        exporter = MetricsExporter(state_store=store, port=19092)
        exporter.start(daemon=True)
        time.sleep(0.1)

        url = "http://localhost:19092/metrics"
        with urllib.request.urlopen(url, timeout=3) as resp:
            ct = resp.headers.get("Content-Type", "")
        assert "text/plain" in ct
        assert "0.0.4" in ct
