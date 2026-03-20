"""
omega.core.metrics
~~~~~~~~~~~~~~~~~~~
Metrics collection and aggregation for the Omega framework.

MetricsCollector wraps StateStore to provide:
  - Rolling time-window aggregates (p50, p95, p99 latency)
  - Per-node health summaries
  - System-wide convergence trends
  - Dashboard-ready JSON output

Design: MetricsCollector is read-heavy. All writes go through StateStore
(via node executions, cost events). MetricsCollector just queries and
aggregates.

Usage::
    collector = MetricsCollector(state_store)

    # After a heartbeat cycle:
    summary = collector.node_summary("DataIngestionNode")
    dashboard = collector.dashboard(since_cycle=0)
    health = collector.system_health()
"""

import logging
import math
import time
from typing import Any, Dict, List, Optional

from omega.core.state_store import StateStore

logger = logging.getLogger("omega.core.metrics")


def _percentile(values: List[float], pct: float) -> float:
    """Compute percentile (0-100) of a sorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _trend(values: List[float]) -> str:
    """Return 'improving', 'degrading', or 'stable' from a series of values."""
    if len(values) < 2:
        return "stable"
    delta = values[-1] - values[0]
    pct = abs(delta) / max(abs(values[0]), 1e-9) * 100
    if pct < 5:
        return "stable"
    return "improving" if delta > 0 else "degrading"


class MetricsCollector:
    """
    Aggregates and presents metrics from the StateStore.

    Provides rolling-window aggregates, per-node summaries, and
    dashboard-ready JSON output.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._system_start = time.time()
        self._cycle_scores: List[float] = []    # convergence tracking
        self._cycle_count: int = 0

    def record_cycle_score(self, score: float) -> None:
        """Record the composite score after each heartbeat. Used for convergence."""
        self._cycle_scores.append(score)
        self._cycle_count += 1

    # ------------------------------------------------------------------ per-node

    def node_summary(self, node_name: str, since_cycle: int = 0) -> Dict[str, Any]:
        """Return aggregated metrics for a single node."""
        # Get all executions for this node
        all_nodes = self._store.all_nodes()
        node_info = next((n for n in all_nodes if n["name"] == node_name), None)

        if node_info is None:
            return {"name": node_name, "status": "not_registered"}

        execs = self._store.get_recent_executions(
            node_id=node_info["node_id"], limit=500, since_cycle=since_cycle
        )

        latencies = [e["duration_ms"] for e in execs if e.get("duration_ms") is not None]
        successes = sum(1 for e in execs if e.get("success"))
        total = len(execs)

        improvements = self._store.get_improvement_history(node_id=node_info["node_id"])

        return {
            "name": node_name,
            "node_id": node_info["node_id"],
            "version": node_info["version"],
            "health": node_info["health"],
            "status": node_info["status"],
            "executions_total": total,
            "error_rate": (total - successes) / max(1, total),
            "latency_p50_ms": round(_percentile(latencies, 50), 1),
            "latency_p95_ms": round(_percentile(latencies, 95), 1),
            "latency_p99_ms": round(_percentile(latencies, 99), 1),
            "avg_latency_ms": round(sum(latencies) / max(1, len(latencies)), 1),
            "improvement_count": len(improvements),
            "improvements": [
                {
                    "from": imp["from_version"],
                    "to": imp["to_version"],
                    "cycle": imp["cycle"],
                    "triggered_by": imp["triggered_by"],
                }
                for imp in improvements[:5]
            ],
        }

    def all_node_summaries(self, since_cycle: int = 0) -> List[Dict[str, Any]]:
        """Return summaries for all registered nodes."""
        all_nodes = self._store.all_nodes()
        return [self.node_summary(n["name"], since_cycle=since_cycle) for n in all_nodes]

    # ------------------------------------------------------------------ system

    def system_health(self) -> Dict[str, Any]:
        """Compute overall system health from node health scores."""
        nodes = self._store.all_nodes()
        if not nodes:
            return {"score": 0.0, "status": "no_nodes"}

        health_scores = [n["health"] for n in nodes]
        avg_health = sum(health_scores) / len(health_scores)
        min_health = min(health_scores)

        # Convergence trend from cycle scores
        convergence_trend = _trend(self._cycle_scores[-10:]) if self._cycle_scores else "stable"
        convergence_score = self._cycle_scores[-1] if self._cycle_scores else 0.0

        # Open issues affect health
        open_issues = self._store.get_open_issues()
        error_issues = sum(1 for i in open_issues if i.get("severity") == "error")

        # Composite system health score (0-1)
        # Penalise for open error issues
        issue_penalty = min(0.3, error_issues * 0.1)
        composite = max(0.0, avg_health - issue_penalty)

        if composite >= 0.8:
            status = "healthy"
        elif composite >= 0.6:
            status = "degraded"
        else:
            status = "critical"

        return {
            "status": status,
            "composite_score": round(composite, 3),
            "avg_node_health": round(avg_health, 3),
            "min_node_health": round(min_health, 3),
            "node_count": len(nodes),
            "open_issues": len(open_issues),
            "error_issues": error_issues,
            "convergence_score": round(convergence_score, 4),
            "convergence_trend": convergence_trend,
            "uptime_seconds": round(time.time() - self._system_start, 0),
            "total_cycles": self._cycle_count,
        }

    # ------------------------------------------------------------------ cost

    def cost_summary(self, since_cycle: int = 0) -> Dict[str, Any]:
        """Return aggregated cost data by provider."""
        raw = self._store.get_cost_summary(since_cycle=since_cycle)

        total_calls = sum(v.get("calls", 0) for v in raw.values())
        total_ms = sum(v.get("total_ms", 0) for v in raw.values())
        total_cost = sum(v.get("total_cost", 0) for v in raw.values())

        return {
            "by_provider": raw,
            "total_api_calls": total_calls,
            "total_api_time_ms": round(total_ms, 1),
            "total_estimated_cost_usd": round(total_cost, 6),
        }

    # ------------------------------------------------------------------ dashboard

    def dashboard(self, since_cycle: int = 0) -> Dict[str, Any]:
        """
        Return structured dashboard data combining all metric sources.

        Suitable for rendering in a web dashboard or logging.
        """
        node_summaries = self.all_node_summaries(since_cycle=since_cycle)
        system = self.system_health()
        costs = self.cost_summary(since_cycle=since_cycle)
        open_issues = self._store.get_open_issues()
        recent_traces = self._store.get_recent_traces(limit=5)
        improvements = self._store.get_improvement_history(limit=10)

        return {
            "timestamp": time.time(),
            "system": system,
            "nodes": node_summaries,
            "costs": costs,
            "issues": open_issues[:10],
            "recent_traces": recent_traces,
            "recent_improvements": [
                {
                    "node": imp["node_name"],
                    "from": imp["from_version"],
                    "to": imp["to_version"],
                    "cycle": imp["cycle"],
                }
                for imp in improvements
            ],
        }

    def format_dashboard(self, since_cycle: int = 0) -> str:
        """Return a human-readable ASCII dashboard summary."""
        data = self.dashboard(since_cycle=since_cycle)
        sys = data["system"]

        lines = [
            "┌─────────────────────────────────────────────────────────────┐",
            f"│  OMEGA SYSTEM DASHBOARD                                      │",
            f"│  Status: {sys['status']:<10} Health: {sys['composite_score']:.2f}  Cycles: {sys['total_cycles']:<6} │",
            f"│  Convergence: {sys['convergence_score']:.4f} ({sys['convergence_trend']:<10})  Issues: {sys['open_issues']:<4}     │",
            "├───────────────────────┬──────────┬───────────┬────────────────┤",
            "│  Node                 │  Version │  p95 (ms) │  Errors        │",
            "├───────────────────────┼──────────┼───────────┼────────────────┤",
        ]

        for n in data["nodes"]:
            name = n["name"][:21]
            ver = n["version"][:8]
            p95 = f"{n['latency_p95_ms']:.0f}"
            err = f"{n['error_rate']:.0%}"
            status_icon = "●" if n.get("health", 0) >= 0.7 else "○"
            lines.append(f"│  {status_icon} {name:<19} │  {ver:<8} │  {p95:>9} │  {err:<14} │")

        lines.append("└───────────────────────┴──────────┴───────────┴────────────────┘")

        if data["issues"]:
            lines.append(f"\n  Open Issues ({len(data['issues'])}):")
            for issue in data["issues"][:3]:
                lines.append(f"  [{issue['severity'].upper()[:4]}] {issue['detector']}: {issue['description'][:50]}")

        if data["costs"]["total_api_calls"] > 0:
            lines.append(f"\n  API Calls: {data['costs']['total_api_calls']}  │  Time: {data['costs']['total_api_time_ms']:.0f}ms")

        return "\n".join(lines)
