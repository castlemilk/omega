"""
omega.nodes.vectora.dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DashboardNode — the observability dashboard as a self-improving Omega node.

The system recursively optimizes its own observability: the dashboard isn't a
passive viewer but an active node that gets evaluated and improved alongside
everything else in the pipeline.

Capabilities (grow with self-improvement arcs):
  v1.0: api_health_check, metric_coverage_audit
  v1.1: + query_caching         (when API p95 > 300ms)
  v1.2: + auto_discovery        (when metric coverage < 80%)
  v1.3: + adaptive_polling      (when data freshness < 50%)

When the Go API server isn't running, connection errors are captured as issues
and reported through the standard issue/triage system — they don't crash the
pipeline.
"""

import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from omega.core.brain import BrainConfig
from omega.core.node import Node, NodeInput, NodeOutput, NodeState


class DashboardNode(Node):
    """
    Observability dashboard as a self-improving Omega node.

    Monitors the health of the backend API server, audits metric coverage
    (are all nodes reporting?), and tracks data freshness. Participates in
    the same heartbeat, evaluation, and self-improvement loop as every other
    node in the graph.

    The self-improvement arc adds capabilities as issues are observed:
      v1.0 → v1.1 : high API latency  → adds query_caching capability
      v1.1 → v1.2 : low coverage      → adds auto_discovery capability
      v1.2 → v1.3 : stale data        → adds adaptive_polling capability
    """

    # Endpoints expected on the backend API server
    _ENDPOINTS = [
        "/api/health",
        "/api/nodes",
        "/api/metrics",
        "/api/traces",
        "/api/convergence",
    ]

    # Latency threshold that triggers the query_caching improvement (ms)
    _LATENCY_IMPROVEMENT_THRESHOLD = 300.0

    def __init__(
        self,
        state_store=None,
        api_base_url: str = "http://localhost:8080",
        brain_config: Optional[BrainConfig] = None,
    ) -> None:
        super().__init__(brain_config=brain_config)
        self._node_id = str(uuid.uuid4())
        self._state_store = state_store
        self._api_base_url = api_base_url.rstrip("/")
        self._version = "1.0"

        # Capability set grows with improvement arcs
        self._capabilities: List[str] = ["api_health_check", "metric_coverage_audit"]

        # Rolling latency samples (most recent 50)
        self._api_latencies: List[float] = []

        # Coverage and freshness scores (0.0–1.0)
        self._coverage_score: float = 0.0
        self._freshness_score: float = 0.0

        # Issue tracking
        self._issues: Dict[str, Dict[str, Any]] = {}

        # Execution counters
        self._execution_count: int = 0
        self._error_count: int = 0
        self._total_checks: int = 0
        self._total_latency_ms: float = 0.0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        health = self._calculate_health()
        recent = self._api_latencies[-20:]
        avg_latency = sum(recent) / len(recent) if recent else 0.0
        return NodeState(
            node_id=self._node_id,
            name="DashboardNode",
            version=self._version,
            health=health,
            capabilities=list(self._capabilities),
            metrics=self.evaluate(),
            metadata={
                "api_base_url": self._api_base_url,
                "capability_count": len(self._capabilities),
                "avg_latency_ms": round(avg_latency, 1),
                "coverage_score": self._coverage_score,
                "freshness_score": self._freshness_score,
                "open_issues": len(self._active_issues()),
            },
        )

    def get_capabilities(self) -> List[str]:
        return list(self._capabilities)

    def describe(self) -> str:
        return (
            "Observability dashboard node — monitors backend API health, "
            "audits metric coverage across all registered nodes, tracks data "
            "freshness, and self-improves its own observability capabilities. "
            f"Currently v{self._version} with {len(self._capabilities)} capabilities."
        )

    def execute(self, input: NodeInput) -> NodeOutput:  # noqa: A002
        t0 = time.perf_counter()
        self._execution_count += 1
        action = input.action

        if action not in self.get_capabilities():
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"DashboardNode: unknown action '{action}'"],
                metrics={"latency_ms": 0.0},
            )

        results: Dict[str, Any] = {"checks": [], "issues": [], "coverage": {}, "freshness": {}}

        # ── 1. API health check ───────────────────────────────────────────────
        if "api_health_check" in self._capabilities:
            for endpoint in self._ENDPOINTS:
                url = f"{self._api_base_url}{endpoint}"
                try:
                    start = time.monotonic()
                    req = urllib.request.Request(
                        url,
                        headers={"Accept": "application/json"},
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        latency_ms = (time.monotonic() - start) * 1000
                        self._api_latencies.append(latency_ms)
                        if len(self._api_latencies) > 100:
                            self._api_latencies = self._api_latencies[-100:]
                        self._total_latency_ms += latency_ms
                        self._total_checks += 1

                        results["checks"].append({
                            "endpoint": endpoint,
                            "status": resp.status,
                            "latency_ms": round(latency_ms, 1),
                            "ok": resp.status < 400,
                        })
                        # Resolve any prior error issue for this endpoint
                        self._resolve_issue(f"api_error_{endpoint.replace('/', '_')}")

                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    self._error_count += 1
                    self._total_checks += 1
                    severity = "high" if endpoint == "/api/health" else "medium"
                    issue_id = f"api_error_{endpoint.replace('/', '_')}"
                    self._open_issue(
                        issue_id,
                        severity,
                        f"API endpoint unreachable: {endpoint} — {type(exc).__name__}",
                        {"endpoint": endpoint, "error": str(exc), "url": url},
                    )
                    results["issues"].append({
                        "endpoint": endpoint,
                        "error": str(exc),
                        "severity": severity,
                    })

        # ── 2. Metric coverage audit ─────────────────────────────────────────
        if "metric_coverage_audit" in self._capabilities and self._state_store is not None:
            try:
                all_nodes = self._state_store.all_nodes()
                active_nodes = [n for n in all_nodes if n.get("status") == "active"]
                recent_node_ids = {
                    row["node_id"]
                    for row in self._state_store.get_nodes_with_recent_metrics(minutes=10)
                }

                if active_nodes:
                    covered = sum(1 for n in active_nodes if n["node_id"] in recent_node_ids)
                    self._coverage_score = covered / len(active_nodes)
                    if self._coverage_score < 0.8:
                        self._open_issue(
                            "low_metric_coverage",
                            "warning",
                            f"Only {self._coverage_score:.0%} of active nodes have recent metrics",
                            {"covered": covered, "total": len(active_nodes)},
                        )
                    else:
                        self._resolve_issue("low_metric_coverage")
                else:
                    self._coverage_score = 1.0

                results["coverage"] = {
                    "active_nodes": len(active_nodes),
                    "nodes_with_recent_metrics": len(recent_node_ids),
                    "coverage_score": round(self._coverage_score, 3),
                }

                # ── Freshness audit ───────────────────────────────────────────
                latest_ts = self._state_store.get_latest_execution_time()
                if latest_ts is not None:
                    age_s = time.time() - latest_ts
                    self._freshness_score = max(0.0, 1.0 - age_s / 300.0)  # decays to 0 at 5 min
                    if self._freshness_score < 0.5:
                        self._open_issue(
                            "stale_metrics",
                            "warning",
                            f"Latest execution is {age_s:.0f}s old (freshness={self._freshness_score:.2f})",
                            {"age_seconds": age_s, "freshness": self._freshness_score},
                        )
                    else:
                        self._resolve_issue("stale_metrics")
                else:
                    self._freshness_score = 0.0

                results["freshness"] = {
                    "freshness_score": round(self._freshness_score, 3),
                    "latest_execution_ts": latest_ts,
                }

            except Exception as exc:
                # Coverage audit failure is non-fatal
                results["issues"].append({
                    "source": "coverage_audit",
                    "error": str(exc),
                    "severity": "low",
                })

        latency_ms = (time.perf_counter() - t0) * 1000
        api_endpoints_ok = len(results["checks"])
        api_endpoints_err = len([i for i in results["issues"] if "endpoint" in i])

        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=results,
            metrics={
                "latency_ms": round(latency_ms, 1),
                "api_endpoints_ok": float(api_endpoints_ok),
                "api_endpoints_err": float(api_endpoints_err),
                "coverage_score": self._coverage_score,
                "freshness_score": self._freshness_score,
                "health_score": self._calculate_health(),
            },
        )

    def evaluate(self) -> Dict[str, float]:
        recent = self._api_latencies[-50:] if self._api_latencies else [0.0]
        error_rate = self._error_count / max(self._total_checks, 1)

        avg_latency = sum(recent) / len(recent)
        p95_idx = max(0, int(len(recent) * 0.95) - 1)
        p95_latency = sorted(recent)[p95_idx] if len(recent) >= 5 else avg_latency

        return {
            "api_latency_avg_ms": round(avg_latency, 1),
            "api_latency_p95_ms": round(p95_latency, 1),
            "error_rate": round(error_rate, 4),
            "metric_coverage": round(self._coverage_score, 3),
            "data_freshness": round(self._freshness_score, 3),
            "health_score": round(self._calculate_health(), 4),
            "avg_latency_ms": round(avg_latency, 1),  # standard key for MetricsCollector
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """Self-improve observability capabilities based on observed issues."""
        metrics = self.evaluate()
        changed = False

        # v1.0 → v1.1: high latency → add query_caching
        if (
            self._version == "1.0"
            and metrics.get("api_latency_p95_ms", 0) > self._LATENCY_IMPROVEMENT_THRESHOLD
            and "query_caching" not in self._capabilities
        ):
            self._capabilities.append("query_caching")
            self._version = "1.1"
            changed = True

        # v1.1 → v1.2: low metric coverage → add auto_discovery
        elif (
            self._version == "1.1"
            and metrics.get("metric_coverage", 1.0) < 0.8
            and "auto_discovery" not in self._capabilities
        ):
            self._capabilities.append("auto_discovery")
            self._version = "1.2"
            changed = True

        # v1.2 → v1.3: stale data → add adaptive_polling
        elif (
            self._version == "1.2"
            and metrics.get("data_freshness", 1.0) < 0.5
            and "adaptive_polling" not in self._capabilities
        ):
            self._capabilities.append("adaptive_polling")
            self._version = "1.3"
            changed = True

        return changed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calculate_health(self) -> float:
        scores: List[float] = []

        # Latency score — target p95 < 200ms, 0 at 500ms+
        if self._api_latencies:
            recent = self._api_latencies[-20:]
            p95_idx = max(0, int(len(recent) * 0.95) - 1)
            p95 = sorted(recent)[p95_idx] if len(recent) >= 5 else sum(recent) / len(recent)
            scores.append(max(0.0, 1.0 - p95 / 500.0))

        # Error rate score — 0 at 10%+ error rate
        error_rate = self._error_count / max(self._total_checks, 1)
        scores.append(1.0 - min(error_rate * 10.0, 1.0))

        # Coverage and freshness (only count if we've actually audited)
        if self._coverage_score > 0 or self._total_checks > 0:
            scores.append(self._coverage_score)
        if self._freshness_score > 0 or self._total_checks > 0:
            scores.append(self._freshness_score)

        return sum(scores) / max(len(scores), 1)

    def _open_issue(self, issue_id: str, severity: str, description: str, context: Dict) -> None:
        if issue_id not in self._issues:
            self._issues[issue_id] = {
                "issue_id": issue_id,
                "severity": severity,
                "description": description,
                "context": context,
                "state": "pending",
                "opened_at": time.time(),
            }
        else:
            if self._issues[issue_id]["state"] == "pending":
                self._issues[issue_id]["state"] = "active"

    def _resolve_issue(self, issue_id: str) -> None:
        if issue_id in self._issues and self._issues[issue_id]["state"] != "resolved":
            self._issues[issue_id]["state"] = "resolved"
            self._issues[issue_id]["resolved_at"] = time.time()

    def _active_issues(self) -> List[Dict[str, Any]]:
        return [i for i in self._issues.values() if i["state"] in ("pending", "active")]
