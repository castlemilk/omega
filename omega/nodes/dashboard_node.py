"""
omega.nodes.dashboard_node
~~~~~~~~~~~~~~~~~~~~~~~~~~
DashboardNode — the observability dashboard as a self-improving Omega node.

The dashboard is not a passive viewer. It's an active participant in the
orchestration graph that the system can evaluate and improve. This creates
a fully self-referential architecture:

    Capability nodes do work
    → Dashboard node observes all nodes
    → Orchestrator evaluates everything including the dashboard
    → System improves everything including how it sees itself

Self-evaluation metrics:
    api_latency_p95    — p95 response time for the Go API server (ms)
    data_freshness     — 0-1 score (1 = data < 30s old, 0 = data > 5min old)
    metric_coverage    — fraction of registered nodes with execution records
    query_efficiency   — 1 - (slow_queries / total_queries), estimated
    error_rate         — fraction of API health checks that failed

Self-improvement actions:
    low metric_coverage → log gap report identifying unrepresented nodes
    high api_latency    → recommend query optimization / caching
    low data_freshness  → flag that orchestrator heartbeat may be stalled
"""

import logging
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any, ClassVar

logger = logging.getLogger("omega.nodes.dashboard")


class DashboardNode:
    """Observability dashboard as a self-improving Omega node."""

    node_name = "DashboardNode"
    capabilities: ClassVar[list[str]] = [
        "api_health_check",
        "metric_coverage_analysis",
        "data_freshness_monitoring",
        "query_efficiency_tracking",
        "self_improvement",
    ]

    # Thresholds
    FRESHNESS_STALE_SECS = 300  # 5 min — data older than this is stale
    FRESHNESS_FRESH_SECS = 30  # <30s — fully fresh
    API_LATENCY_HIGH_MS = 500  # >500ms p95 → flag for optimization
    COVERAGE_WARN_THRESHOLD = 0.8  # <80% coverage → improvement needed

    def __init__(
        self,
        state_store: Any,
        api_url: str = "http://localhost:8080",
        state_db_path: str | None = None,
    ) -> None:
        import os

        self._store = state_store
        self._api_url = api_url.rstrip("/")
        self._state_db_path = state_db_path or os.environ.get(
            "OMEGA_STATE_DB_PATH",
            os.path.join(os.environ.get("OMEGA_DATA_DIR", "./data"), "omega_victoria_state.db"),
        )

        # Metrics tracking
        self._api_latencies_ms: list[float] = []
        self._api_errors: int = 0
        self._api_checks: int = 0
        self._last_coverage_report: dict | None = None
        self._version: str = "1.0"
        self._health: float = 1.0
        self._improvement_count: int = 0

    # ── Node interface ──────────────────────────────────────────────────────

    def execute(self, context: dict | None = None, input_data: Any | None = None) -> dict:
        """
        Run one dashboard health check cycle.

        Returns a health report dict that gets stored as an execution record.
        """
        context = context or {}
        start = time.time()

        # 1. Check API health
        api_ok, latency_ms = self._check_api_health()
        self._api_checks += 1
        if not api_ok:
            self._api_errors += 1
        else:
            self._api_latencies_ms.append(latency_ms)
            # Keep rolling window of last 100
            if len(self._api_latencies_ms) > 100:
                self._api_latencies_ms = self._api_latencies_ms[-100:]

        # 2. Measure metric coverage
        coverage = self._compute_metric_coverage()

        # 3. Measure data freshness
        freshness = self._compute_data_freshness()

        # 4. Update node health score
        error_rate = self._api_errors / max(1, self._api_checks)
        self._health = max(0.0, (coverage * 0.4 + freshness * 0.4 + (1 - error_rate) * 0.2))

        elapsed_ms = (time.time() - start) * 1000

        report = {
            "api_ok": api_ok,
            "api_latency_ms": round(latency_ms, 1),
            "metric_coverage": round(coverage, 3),
            "data_freshness": round(freshness, 3),
            "error_rate": round(error_rate, 3),
            "health_score": round(self._health, 3),
            "elapsed_ms": round(elapsed_ms, 1),
        }

        logger.info(
            "DashboardNode: api=%s latency=%.0fms coverage=%.0f%% freshness=%.2f health=%.2f",
            "ok" if api_ok else "down",
            latency_ms,
            coverage * 100,
            freshness,
            self._health,
        )

        return {"success": True, "result": report, "metrics": report}

    def evaluate(self) -> dict[str, float]:
        """Return current performance metrics for the orchestrator's improvement loop."""
        error_rate = self._api_errors / max(1, self._api_checks)
        p95 = self._percentile(self._api_latencies_ms, 95)

        return {
            "api_latency_p95": round(p95, 1),
            "data_freshness_score": round(self._compute_data_freshness(), 3),
            "metric_coverage": round(self._compute_metric_coverage(), 3),
            "query_efficiency": self._estimate_query_efficiency(),
            "error_rate": round(error_rate, 3),
            "health": round(self._health, 3),
        }

    def improve(self, feedback: dict | None = None) -> dict:
        """
        Apply self-improvement based on current metrics.

        Returns a dict describing what changed (or what was flagged).
        """
        feedback = feedback or {}
        metrics = self.evaluate()
        improvements = []

        # Coverage gap: identify nodes with no execution records
        if metrics["metric_coverage"] < self.COVERAGE_WARN_THRESHOLD:
            gap_report = self._build_coverage_gap_report()
            if gap_report:
                improvements.append(
                    {
                        "type": "coverage_gap",
                        "action": "flag_unrepresented_nodes",
                        "nodes": gap_report,
                        "message": f"Nodes with no execution records: {', '.join(gap_report)}",
                    }
                )
                logger.warning(
                    "DashboardNode improvement: %d nodes have no execution records: %s",
                    len(gap_report),
                    gap_report,
                )

        # High API latency: recommend caching
        if metrics["api_latency_p95"] > self.API_LATENCY_HIGH_MS:
            improvements.append(
                {
                    "type": "latency_optimization",
                    "action": "recommend_query_caching",
                    "p95_ms": metrics["api_latency_p95"],  # type: ignore[dict-item]
                    "message": f"API p95 latency {metrics['api_latency_p95']:.0f}ms exceeds {self.API_LATENCY_HIGH_MS}ms - consider caching AllNodes() result",
                }
            )
            logger.warning(
                "DashboardNode improvement: high API latency p95=%.0fms",
                metrics["api_latency_p95"],
            )

        # Stale data: flag orchestrator may be stalled
        if metrics["data_freshness_score"] < 0.3:
            improvements.append(
                {
                    "type": "data_freshness",
                    "action": "flag_stalled_orchestrator",
                    "freshness": metrics["data_freshness_score"],  # type: ignore[dict-item]
                    "message": "Data is stale - orchestrator heartbeat may be stalled",
                }
            )
            logger.warning(
                "DashboardNode improvement: data is stale (freshness=%.2f)",
                metrics["data_freshness_score"],
            )

        if improvements:
            self._improvement_count += 1
            new_version = f"{float(self._version) + 0.1:.1f}"
            self._version = new_version
            logger.info(
                "DashboardNode improved to v%s with %d improvement(s)",
                self._version,
                len(improvements),
            )

        return {
            "changed": bool(improvements),
            "new_version": self._version,
            "improvements": improvements,
        }

    def get_state(self) -> dict:
        """Return current node state for registration/heartbeat."""
        return {
            "name": self.node_name,
            "version": self._version,
            "health": round(self._health, 3),
            "status": "active",
            "capabilities": self.capabilities,
        }

    def get_capabilities(self) -> list[str]:
        return self.capabilities

    # ── Internal helpers ────────────────────────────────────────────────────

    def _check_api_health(self) -> tuple:
        """
        Ping the Go API server's GetHealth endpoint.
        Returns (ok, latency_ms).
        """
        url = f"{self._api_url}/omega.v1.OrchestratorService/GetHealth"
        start = time.time()
        try:
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Connect-Protocol-Version": "1",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            latency_ms = (time.time() - start) * 1000
            return True, latency_ms
        except Exception as e:
            logger.debug("DashboardNode API health check failed: %s", e)
            latency_ms = (time.time() - start) * 1000
            return False, latency_ms

    def _compute_metric_coverage(self) -> float:
        """
        Fraction of registered nodes that have at least one execution record.
        """
        try:
            conn = sqlite3.connect(self._state_db_path, timeout=3)
            try:
                cur = conn.execute("SELECT COUNT(*) FROM nodes")
                total_nodes = cur.fetchone()[0]
                if total_nodes == 0:
                    return 1.0  # No nodes = nothing to cover

                cur = conn.execute("SELECT COUNT(DISTINCT node_id) FROM node_executions")
                covered = cur.fetchone()[0]
                return float(covered) / float(total_nodes)
            finally:
                conn.close()
        except Exception as e:
            logger.debug("DashboardNode coverage check failed: %s", e)
            return 1.0  # Optimistic default if DB unavailable

    def _compute_data_freshness(self) -> float:
        """
        Freshness score 0-1:
          1.0 = most recent execution < FRESHNESS_FRESH_SECS ago
          0.0 = most recent execution > FRESHNESS_STALE_SECS ago
        """
        try:
            conn = sqlite3.connect(self._state_db_path, timeout=3)
            try:
                cur = conn.execute("SELECT MAX(started_at) FROM node_executions")
                row = cur.fetchone()
                if not row or row[0] is None:
                    return 0.5  # No data yet — neutral
                last_ts = float(row[0])
                age_secs = time.time() - last_ts
                if age_secs <= self.FRESHNESS_FRESH_SECS:
                    return 1.0
                if age_secs >= self.FRESHNESS_STALE_SECS:
                    return 0.0
                # Linear interpolation
                return 1.0 - (age_secs - self.FRESHNESS_FRESH_SECS) / (
                    self.FRESHNESS_STALE_SECS - self.FRESHNESS_FRESH_SECS
                )
            finally:
                conn.close()
        except Exception as e:
            logger.debug("DashboardNode freshness check failed: %s", e)
            return 0.5

    def _estimate_query_efficiency(self) -> float:
        """
        Estimate query efficiency from API latency data.
        1.0 = fast queries, 0.0 = very slow.
        """
        if not self._api_latencies_ms:
            return 1.0
        p95 = self._percentile(self._api_latencies_ms, 95)
        # 100ms = 1.0, 1000ms = 0.0
        return max(0.0, 1.0 - (p95 - 100) / 900)

    def _build_coverage_gap_report(self) -> list[str]:
        """Return names of nodes with zero execution records."""
        try:
            conn = sqlite3.connect(self._state_db_path, timeout=3)
            try:
                cur = conn.execute(
                    """
                    SELECT n.name FROM nodes n
                    WHERE n.node_id NOT IN (
                        SELECT DISTINCT node_id FROM node_executions
                    )
                    """
                )
                return [row[0] for row in cur.fetchall()]
            finally:
                conn.close()
        except Exception:
            return []

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sv = sorted(values)
        k = (len(sv) - 1) * pct / 100.0
        lo, hi = int(k), min(int(k) + 1, len(sv) - 1)
        return sv[lo] + (sv[hi] - sv[lo]) * (k - lo)
