"""Tests for DashboardNode."""
import os
import sqlite3
import tempfile
import unittest

from omega.nodes.dashboard_node import DashboardNode


def make_test_state_db(path: str) -> None:
    """Create a minimal state DB with the tables DashboardNode reads."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY, name TEXT, version TEXT,
            capabilities_json TEXT, health REAL, status TEXT,
            registered_at REAL, last_updated REAL
        );
        CREATE TABLE IF NOT EXISTS node_executions (
            exec_id TEXT PRIMARY KEY, node_id TEXT, node_name TEXT,
            action TEXT, started_at REAL, ended_at REAL, duration_ms REAL,
            success INTEGER, error_text TEXT, metrics_json TEXT, cycle INTEGER
        );
    """)
    conn.commit()
    conn.close()


class TestDashboardNode(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_db = os.path.join(self.tmpdir, "state.db")
        make_test_state_db(self.state_db)

    def _make_node(self):
        return DashboardNode(
            state_store=None,  # Not used in pure-sqlite path
            api_url="http://localhost:19999",  # Non-existent port → API check fails gracefully
            state_db_path=self.state_db,
        )

    def test_execute_returns_report(self):
        node = self._make_node()
        result = node.execute()
        self.assertTrue(result["success"])
        report = result["result"]
        self.assertIn("api_ok", report)
        self.assertIn("metric_coverage", report)
        self.assertIn("data_freshness", report)
        self.assertIn("health_score", report)

    def test_api_down_does_not_crash(self):
        """API being unreachable should not raise — returns api_ok=False."""
        node = self._make_node()
        result = node.execute()
        self.assertFalse(result["result"]["api_ok"])
        self.assertTrue(result["success"])

    def test_metric_coverage_no_nodes(self):
        """With no nodes registered, coverage should be 1.0 (nothing to cover)."""
        node = self._make_node()
        coverage = node._compute_metric_coverage()
        self.assertAlmostEqual(coverage, 1.0)

    def test_metric_coverage_with_gap(self):
        """A node with no executions should reduce coverage below 1.0."""
        conn = sqlite3.connect(self.state_db)
        conn.execute("INSERT INTO nodes VALUES ('n1','NodeA','1.0','[]',1.0,'active',1.0,1.0)")
        conn.commit()
        conn.close()

        node = self._make_node()
        coverage = node._compute_metric_coverage()
        self.assertLess(coverage, 1.0)

    def test_evaluate_returns_all_keys(self):
        node = self._make_node()
        metrics = node.evaluate()
        for key in ["api_latency_p95", "data_freshness_score", "metric_coverage",
                    "query_efficiency", "error_rate", "health"]:
            self.assertIn(key, metrics, f"missing key: {key}")

    def test_improve_returns_dict(self):
        node = self._make_node()
        result = node.improve()
        self.assertIn("changed", result)
        self.assertIn("new_version", result)
        self.assertIn("improvements", result)

    def test_get_state(self):
        node = self._make_node()
        state = node.get_state()
        self.assertEqual(state["name"], "DashboardNode")
        self.assertIn("version", state)
        self.assertIn("health", state)

    def test_coverage_gap_report(self):
        """Nodes with no executions appear in gap report."""
        conn = sqlite3.connect(self.state_db)
        conn.execute("INSERT INTO nodes VALUES ('n2','NodeB','1.0','[]',1.0,'active',1.0,1.0)")
        conn.commit()
        conn.close()

        node = self._make_node()
        gaps = node._build_coverage_gap_report()
        self.assertIn("NodeB", gaps)


if __name__ == "__main__":
    unittest.main()
