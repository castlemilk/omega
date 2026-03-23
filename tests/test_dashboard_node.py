"""Tests for DashboardNode."""

import os
import unittest

import pytest

from omega.nodes.dashboard_node import DashboardNode

_NEEDS_DB = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)


class TestDashboardNode(unittest.TestCase):
    def _make_node(self):
        return DashboardNode(
            state_store=None,
            api_url="http://localhost:19999",  # Non-existent port → API check fails gracefully
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

    def test_metric_coverage_no_db(self):
        """Without a DB, coverage returns the optimistic default (1.0)."""
        node = self._make_node()
        coverage = node._compute_metric_coverage()
        self.assertAlmostEqual(coverage, 1.0)

    def test_evaluate_returns_all_keys(self):
        node = self._make_node()
        metrics = node.evaluate()
        for key in [
            "api_latency_p95",
            "data_freshness_score",
            "metric_coverage",
            "query_efficiency",
            "error_rate",
            "health",
        ]:
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


if __name__ == "__main__":
    unittest.main()
