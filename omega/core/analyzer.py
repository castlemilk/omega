"""
omega.core.analyzer
~~~~~~~~~~~~~~~~~~~~
SystemAnalyzer — translates observability data into improvement recommendations.

The key insight: traces + metrics ARE input to the improvement loop.
SystemAnalyzer reads StateStore data and produces Recommendation objects
that feed into the orchestrator's improve() cycle.

Usage::
    analyzer = SystemAnalyzer(state_store, metrics_collector)

    # Run after each heartbeat cycle
    recommendations = analyzer.analyze(cycle=5)

    # Feed into improvement loop
    for rec in recommendations:
        print(f"[{rec.priority}] {rec.target_node}: {rec.message}")
        feedback[rec.target_node] = rec.as_feedback_dict()
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from omega.core.state_store import StateStore
from omega.core.metrics import MetricsCollector

logger = logging.getLogger("omega.core.analyzer")


@dataclass
class Recommendation:
    """
    A recommendation produced by SystemAnalyzer for the improvement loop.

    Attributes
    ----------
    target_node  : name of the node this recommendation is for, or "system"
    rec_type     : category — "latency", "error_rate", "improvement", "rollback", "bottleneck"
    priority     : "high", "medium", "low"
    message      : human-readable description
    context      : structured data for the improvement loop
    cycle        : cycle number when this was generated
    """
    target_node: str
    rec_type: str
    priority: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    cycle: int = 0

    def as_feedback_dict(self) -> Dict[str, Any]:
        """Convert to feedback dict for Node.improve()."""
        return {
            "recommendation": self.rec_type,
            "priority": self.priority,
            "message": self.message,
            **self.context,
        }


class SystemAnalyzer:
    """
    Analyzes observability data to generate improvement recommendations.

    Three analysis passes per call:
      1. Trace analysis  — bottleneck detection, error cascades
      2. Metrics analysis — degradation, rising error rates, memory bloat
      3. Improvement history — diminishing returns, regression detection

    Results feed into the orchestrator's improvement cycle.
    """

    # Thresholds
    BOTTLENECK_PCT = 0.7          # node uses >70% of total cycle time → bottleneck
    HIGH_ERROR_RATE = 0.1         # >10% error rate → high priority
    MEDIUM_ERROR_RATE = 0.05      # >5% error rate → medium priority
    HIGH_LATENCY_MS = 5000        # >5s per node → high priority
    MEDIUM_LATENCY_MS = 2000      # >2s per node → medium priority
    REGRESSION_MIN_CYCLES = 2     # need N improvements to check for regression

    def __init__(self, store: StateStore, collector: MetricsCollector) -> None:
        self._store = store
        self._collector = collector
        self._last_analysis_cycle: int = -1
        self._recommendation_history: List[Recommendation] = []

    # ------------------------------------------------------------------ main entry

    def analyze(self, cycle: int) -> List[Recommendation]:
        """
        Run all analysis passes and return a merged, de-duplicated list of
        Recommendations ordered by priority.
        """
        recs: List[Recommendation] = []

        recs.extend(self._analyze_traces(cycle))
        recs.extend(self._analyze_metrics(cycle))
        recs.extend(self._analyze_improvement_history(cycle))

        # De-duplicate by (target_node, rec_type)
        seen = set()
        unique_recs = []
        for r in recs:
            key = (r.target_node, r.rec_type)
            if key not in seen:
                seen.add(key)
                unique_recs.append(r)

        # Sort: high first, then medium, then low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        unique_recs.sort(key=lambda r: priority_order.get(r.priority, 9))

        self._recommendation_history.extend(unique_recs)
        self._last_analysis_cycle = cycle

        if unique_recs:
            logger.info(
                "Cycle %d analysis: %d recommendations (%d high, %d medium, %d low)",
                cycle,
                len(unique_recs),
                sum(1 for r in unique_recs if r.priority == "high"),
                sum(1 for r in unique_recs if r.priority == "medium"),
                sum(1 for r in unique_recs if r.priority == "low"),
            )

        return unique_recs

    # ------------------------------------------------------------------ trace analysis

    def _analyze_traces(self, cycle: int) -> List[Recommendation]:
        """
        Detect: bottleneck nodes, error-heavy spans, redundant calls.
        """
        recs: List[Recommendation] = []
        recent_traces = self._store.get_recent_traces(limit=10)

        if not recent_traces:
            return recs

        # Per-trace: find which node takes the most time
        for trace_meta in recent_traces:
            trace_id = trace_meta.get("trace_id")
            if not trace_id:
                continue

            spans = self._store.get_trace(trace_id)
            if not spans:
                continue

            # Exclude the root span from bottleneck analysis
            child_spans = [s for s in spans if s.get("parent_span_id") is not None]

            if not child_spans:
                continue

            total_duration = sum(s.get("duration_ms") or 0 for s in child_spans)
            if total_duration <= 0:
                continue

            # Find the slowest span
            slowest = max(child_spans, key=lambda s: s.get("duration_ms") or 0)
            slowest_ms = slowest.get("duration_ms") or 0
            node_name = slowest.get("node_name", "Unknown")

            if total_duration > 0 and slowest_ms / total_duration >= self.BOTTLENECK_PCT:
                priority = "high" if slowest_ms > self.HIGH_LATENCY_MS else "medium"
                recs.append(Recommendation(
                    target_node=node_name,
                    rec_type="bottleneck",
                    priority=priority,
                    message=(
                        f"{node_name} used {slowest_ms / total_duration:.0%} of cycle time "
                        f"({slowest_ms:.0f}ms of {total_duration:.0f}ms total). "
                        f"Optimize latency: target <{self.MEDIUM_LATENCY_MS}ms."
                    ),
                    context={
                        "node_duration_ms": slowest_ms,
                        "total_duration_ms": total_duration,
                        "pct_of_cycle": slowest_ms / total_duration,
                        "target_latency_ms": self.MEDIUM_LATENCY_MS,
                        "improve_latency": True,
                    },
                    cycle=cycle,
                ))

            # Error spans
            error_spans = [s for s in spans if s.get("status") == "error"]
            for span in error_spans:
                recs.append(Recommendation(
                    target_node=span.get("node_name", "Unknown"),
                    rec_type="error_cascade",
                    priority="high",
                    message=(
                        f"Error span detected in trace {trace_id[:8]}: "
                        f"{span.get('operation', '?')} failed."
                    ),
                    context={
                        "trace_id": trace_id,
                        "span_id": span.get("span_id"),
                        "operation": span.get("operation"),
                        "improve_accuracy": True,
                    },
                    cycle=cycle,
                ))

        return recs

    # ------------------------------------------------------------------ metrics analysis

    def _analyze_metrics(self, cycle: int) -> List[Recommendation]:
        """
        Detect: rising error rates, high latency, degraded health scores.
        """
        recs: List[Recommendation] = []
        node_summaries = self._collector.all_node_summaries(since_cycle=0)

        for ns in node_summaries:
            name = ns["name"]
            error_rate = ns.get("error_rate", 0.0)
            p95_ms = ns.get("latency_p95_ms", 0.0)
            health = ns.get("health", 1.0)

            # High error rate
            if error_rate >= self.HIGH_ERROR_RATE:
                recs.append(Recommendation(
                    target_node=name,
                    rec_type="error_rate",
                    priority="high",
                    message=(
                        f"{name} has {error_rate:.0%} error rate (threshold: {self.HIGH_ERROR_RATE:.0%}). "
                        f"Review recent failures and add retry logic."
                    ),
                    context={
                        "error_rate": error_rate,
                        "threshold": self.HIGH_ERROR_RATE,
                        "improve_accuracy": True,
                        "improve_error_handling": True,
                    },
                    cycle=cycle,
                ))
            elif error_rate >= self.MEDIUM_ERROR_RATE:
                recs.append(Recommendation(
                    target_node=name,
                    rec_type="error_rate",
                    priority="medium",
                    message=(
                        f"{name} has elevated error rate: {error_rate:.0%}. Monitor closely."
                    ),
                    context={"error_rate": error_rate, "improve_accuracy": True},
                    cycle=cycle,
                ))

            # High latency
            if p95_ms >= self.HIGH_LATENCY_MS:
                recs.append(Recommendation(
                    target_node=name,
                    rec_type="latency",
                    priority="high",
                    message=(
                        f"{name} p95 latency is {p95_ms:.0f}ms (threshold: {self.HIGH_LATENCY_MS}ms). "
                        f"Add caching or reduce data volume."
                    ),
                    context={
                        "latency_p95_ms": p95_ms,
                        "threshold_ms": self.HIGH_LATENCY_MS,
                        "improve_latency": True,
                    },
                    cycle=cycle,
                ))
            elif p95_ms >= self.MEDIUM_LATENCY_MS:
                recs.append(Recommendation(
                    target_node=name,
                    rec_type="latency",
                    priority="medium",
                    message=(
                        f"{name} p95 latency is {p95_ms:.0f}ms — consider caching."
                    ),
                    context={"latency_p95_ms": p95_ms, "improve_latency": True},
                    cycle=cycle,
                ))

            # Degraded health
            if health < 0.5:
                recs.append(Recommendation(
                    target_node=name,
                    rec_type="health_degraded",
                    priority="high",
                    message=(
                        f"{name} health score is {health:.2f} (below 0.5). "
                        f"Node may be failing — investigate errors."
                    ),
                    context={"health": health, "improve_accuracy": True},
                    cycle=cycle,
                ))

        return recs

    # ------------------------------------------------------------------ improvement history analysis

    def _analyze_improvement_history(self, cycle: int) -> List[Recommendation]:
        """
        Detect: regressions (improvement made things worse), stale nodes,
        diminishing returns.
        """
        recs: List[Recommendation] = []
        improvements = self._store.get_improvement_history(limit=50)

        if len(improvements) < self.REGRESSION_MIN_CYCLES:
            return recs

        # Group improvements by node
        by_node: Dict[str, List[Dict]] = {}
        for imp in improvements:
            name = imp.get("node_name", "?")
            by_node.setdefault(name, []).append(imp)

        for node_name, node_imps in by_node.items():
            # Sort by cycle
            node_imps.sort(key=lambda x: x.get("cycle", 0))

            # Detect regression: last improvement made things worse
            # (Compare before/after metrics if available)
            if len(node_imps) >= 2:
                last = node_imps[-1]
                before = last.get("before_metrics", {})
                after = last.get("after_metrics", {})

                # Check error_rate specifically (if tracked)
                b_err = before.get("error_rate", 0)
                a_err = after.get("error_rate", 0)
                if a_err > b_err * 1.5 and b_err > 0:
                    recs.append(Recommendation(
                        target_node=node_name,
                        rec_type="regression",
                        priority="high",
                        message=(
                            f"{node_name} v{last['from_version']}→v{last['to_version']} "
                            f"increased error rate: {b_err:.0%} → {a_err:.0%}. "
                            f"Consider rollback to v{last['from_version']}."
                        ),
                        context={
                            "from_version": last["from_version"],
                            "to_version": last["to_version"],
                            "before_error_rate": b_err,
                            "after_error_rate": a_err,
                        },
                        cycle=cycle,
                    ))

            # Detect stale node: not improved in N cycles but still at v1.0
            if node_imps:
                last_cycle = node_imps[-1].get("cycle", 0)
                if (cycle - last_cycle) > 10 and node_imps[-1].get("to_version", "") == "1.0":
                    recs.append(Recommendation(
                        target_node=node_name,
                        rec_type="stale",
                        priority="low",
                        message=(
                            f"{node_name} hasn't improved since cycle {last_cycle}. "
                            f"Still at v{node_imps[-1].get('to_version', '?')}."
                        ),
                        context={"last_improvement_cycle": last_cycle},
                        cycle=cycle,
                    ))

        return recs

    # ------------------------------------------------------------------ reporting

    def get_recommendations_for_node(self, node_name: str) -> List[Recommendation]:
        """Return all pending recommendations for a specific node."""
        return [r for r in self._recommendation_history if r.target_node == node_name]

    def summary(self, cycle: int) -> str:
        """Return a concise text summary of current recommendations."""
        recs = self.analyze(cycle)
        if not recs:
            return "  SystemAnalyzer: No recommendations this cycle."

        lines = [f"  SystemAnalyzer: {len(recs)} recommendation(s):"]
        for r in recs[:5]:  # Show top 5
            icon = "▲" if r.priority == "high" else ("►" if r.priority == "medium" else "▼")
            lines.append(f"    {icon} [{r.priority.upper()[:3]}] {r.target_node}: {r.message[:60]}")
        if len(recs) > 5:
            lines.append(f"    … and {len(recs) - 5} more")
        return "\n".join(lines)
