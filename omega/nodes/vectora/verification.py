"""
omega.nodes.vectora.verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verification and convergence monitoring nodes for the Vectora self-improvement loop.

Classes:
  - VerificationNode        : verifies self-improvements don't break invariants
  - PropertyTestNode        : tests mathematical/logical properties on pipeline outputs
  - InvariantDiscoveryNode  : observes pipeline state and discovers statistical invariants
  - ConvergenceMonitorNode  : tracks long-term convergence using EMA, regression, plateau detection
"""

import time
import uuid
from abc import abstractmethod
from typing import Any, Dict, List

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.nodes.vectora.cleaners import CleanerNode


# ---------------------------------------------------------------------------
# VerificationNode
# ---------------------------------------------------------------------------

class VerificationNode(CleanerNode):
    """
    Verifies that self-improvements don't break invariants.
    Called from the improvement loop in vectora_main.py.

    Compares before/after metrics for each improvement cycle and rolls back
    state if a regression beyond the threshold is detected.
    """

    REGRESSION_THRESHOLD = 0.3  # 30% degradation triggers rollback
    MAXIMIZE_METRICS = {"coverage_rate", "signal_coverage", "sharpe_ratio", "completeness_score"}
    MINIMIZE_METRICS = {"error_rate", "avg_latency_ms"}

    def __init__(self) -> None:
        super().__init__()
        self._verification_history: List[Dict] = []  # last 20 verification results
        self._rollback_count = 0
        self._pass_count = 0
        self._fail_count = 0

    # -- CleanerNode interface

    def get_capabilities(self) -> List[str]:
        return ["verify_improvement"]

    def describe(self) -> str:
        return (
            "Guards the self-improvement loop by comparing before/after metrics for each "
            "improvement cycle. Rolls back node state if a metric regresses beyond the "
            "configured threshold. Tracks pass/fail history and rollback events."
        )

    def get_state(self) -> NodeState:
        pass_rate = self._pass_count / max(1, self._pass_count + self._fail_count)
        health = pass_rate
        return NodeState(
            node_id=self._node_id,
            name="VerificationNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "pass_count": self._pass_count,
                "fail_count": self._fail_count,
                "rollback_count": self._rollback_count,
            },
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        self._cycle_count += 1

        if input.action not in self.get_capabilities():
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action: {input.action}"],
                metrics={"latency_ms": 0.0},
            )

        try:
            params = input.parameters
            node_name = params.get("node_name", "unknown")
            before_metrics = params.get("before_metrics", {})
            after_metrics = params.get("after_metrics", {})

            result = self.verify_improvement(
                node=params.get("node"),
                node_name=node_name,
                before_metrics=before_metrics,
                after_metrics=after_metrics,
                snapshot=params.get("snapshot", {}),
                cycle=params.get("cycle", 0),
            )

            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": latency_ms},
            )

        except Exception as exc:
            self._error_count += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": latency_ms},
            )

    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        recent = self._verification_history[-20:]
        passed = sum(1 for r in recent if r.get("passed"))
        return {
            "recent_verifications": len(recent),
            "recent_passed": passed,
            "recent_failed": len(recent) - passed,
            "rollback_count": self._rollback_count,
            "pass_rate": passed / max(1, len(recent)),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """v1.0 -> v1.1: tighten regression threshold after sufficient iterations."""
        if self._version == "1.0":
            iteration = feedback.get("iteration", 0)
            if iteration >= 3:
                self.REGRESSION_THRESHOLD = 0.2
                self._version = "1.1"
                return True
        return False

    # -- Verification helpers

    def snapshot_node(self, node: Node) -> Dict[str, Any]:
        """Capture rollback-able state snapshot of a node before improvement."""
        state_dict = {}
        for attr in vars(node):
            val = getattr(node, attr)
            if isinstance(val, (bool, str, int, float, list)):
                state_dict[attr] = val if not isinstance(val, list) else list(val)
        return state_dict

    def restore_node(self, node: Node, snapshot: Dict[str, Any]) -> None:
        """Restore a node to its pre-improvement state."""
        for attr, value in snapshot.items():
            if hasattr(node, attr):
                setattr(node, attr, value if not isinstance(value, list) else list(value))

    def verify_improvement(
        self,
        node: Any,
        node_name: str,
        before_metrics: Dict[str, float],
        after_metrics: Dict[str, float],
        snapshot: Dict[str, Any],
        cycle: int = 0,
    ) -> Dict[str, Any]:
        """
        Compare before/after metrics. If regression detected, rollback.
        Returns result dict with: passed, regression_detected, rolled_back, details.
        """
        regressions = []

        for metric, before_val in before_metrics.items():
            if metric not in after_metrics:
                continue
            after_val = after_metrics[metric]

            if metric in self.MAXIMIZE_METRICS:
                if after_val < before_val * (1 - self.REGRESSION_THRESHOLD):
                    regressions.append({
                        "metric": metric,
                        "before": before_val,
                        "after": after_val,
                        "type": "maximize_regression",
                    })
            elif metric in self.MINIMIZE_METRICS:
                if after_val > before_val * (1 + self.REGRESSION_THRESHOLD):
                    regressions.append({
                        "metric": metric,
                        "before": before_val,
                        "after": after_val,
                        "type": "minimize_regression",
                    })

        regression_detected = len(regressions) > 0
        rolled_back = False

        if regression_detected and node is not None and snapshot:
            self.restore_node(node, snapshot)
            rolled_back = True
            self._rollback_count += 1

        passed = not regression_detected
        if passed:
            self._pass_count += 1
        else:
            self._fail_count += 1

        result = {
            "passed": passed,
            "regression_detected": regression_detected,
            "rolled_back": rolled_back,
            "node_name": node_name,
            "cycle": cycle,
            "regressions": regressions,
            "details": {
                "before_metrics": before_metrics,
                "after_metrics": after_metrics,
            },
        }

        self._verification_history.append(result)
        if len(self._verification_history) > 20:
            self._verification_history = self._verification_history[-20:]

        return result


# ---------------------------------------------------------------------------
# PropertyTestNode
# ---------------------------------------------------------------------------

class PropertyTestNode(CleanerNode):
    """
    Tests mathematical/logical properties on pipeline outputs each cycle.

    Fast checks (every cycle):
      - Signal bounds [-1, 1]
      - Portfolio weights sum <= 1.0
      - Risk metrics non-negative
      - No null composite signals

    Deep checks (every DEEP_INTERVAL cycles, v1.1+):
      - Signal stability (no large single-cycle direction flips)
    """

    def __init__(self) -> None:
        super().__init__()
        self._last_signals: Dict = {}
        self._properties_discovered: int = 0
        self._deep_stability_enabled: bool = False

    # -- CleanerNode interface

    def get_capabilities(self) -> List[str]:
        return ["run_property_tests"]

    def describe(self) -> str:
        return (
            "Tests mathematical and logical properties on pipeline outputs every cycle. "
            "Checks signal bounds, portfolio weight sums, risk metric non-negativity, "
            "and null signal detection. Deep checks validate signal stability across cycles."
        )

    def get_state(self) -> NodeState:
        active = self._active_issues()
        health = max(0.0, 1.0 - len(active) * 0.25)
        return NodeState(
            node_id=self._node_id,
            name="PropertyTestNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={"active_issues": len(active)},
        )

    def evaluate(self) -> Dict[str, float]:
        active = self._active_issues()
        return {
            "property_violations": float(len(active)),
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "coverage": float(len(active) == 0),
        }

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        self._cycle_count += 1

        if input.action not in self.get_capabilities():
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action: {input.action}"],
                metrics={"latency_ms": 0.0},
            )

        try:
            data = {
                "signals": input.parameters.get("signals", {}),
                "portfolio": input.parameters.get("portfolio", {}),
                "risk": input.parameters.get("risk", {}),
            }

            fast_issues = self._fast_check(data)
            for iss in fast_issues:
                self._open_issue(
                    iss["issue_id"],
                    iss["severity"],
                    iss["description"],
                    iss.get("context", {}),
                )

            deep_issues = []
            if self._cycle_count % self.DEEP_INTERVAL == 0:
                deep_issues = self._deep_check(data)
                for iss in deep_issues:
                    self._open_issue(
                        iss["issue_id"],
                        iss["severity"],
                        iss["description"],
                        iss.get("context", {}),
                    )

            raised_ids = {i["issue_id"] for i in fast_issues + deep_issues}
            for issue_id in list(self._issues.keys()):
                if issue_id not in raised_ids:
                    self._resolve_issue(issue_id)

            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms
            result = self._build_result(data, fast_issues + deep_issues)

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": latency_ms,
                    "violations": float(len(fast_issues + deep_issues)),
                },
            )

        except Exception as exc:
            self._error_count += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": latency_ms},
            )

    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        signals = data.get("signals", {})
        portfolio = data.get("portfolio", {})
        risk = data.get("risk", {})

        # 1. Signal bounds [-1, 1]
        for ticker, sig_data in signals.items():
            if not isinstance(sig_data, dict):
                continue
            composite = sig_data.get("composite")
            if composite is None:
                issues.append({
                    "issue_id": "property_null_signals",
                    "severity": "warning",
                    "description": f"Ticker {ticker} has null composite signal",
                    "context": {"ticker": ticker},
                })
            elif isinstance(composite, (int, float)):
                if not (-2 <= composite <= 2):
                    issues.append({
                        "issue_id": f"property_signal_bounds_{ticker}",
                        "severity": "error",
                        "description": f"Signal for {ticker} out of bounds: {composite:.4f} (expected [-2, 2])",
                        "context": {"ticker": ticker, "composite": composite},
                    })
                elif not (-1 <= composite <= 1):
                    issues.append({
                        "issue_id": f"property_signal_bounds_{ticker}",
                        "severity": "warning",
                        "description": f"Signal for {ticker} outside [-1, 1]: {composite:.4f}",
                        "context": {"ticker": ticker, "composite": composite},
                    })

        # 2. Portfolio weights sum <= 1.0
        weights = portfolio.get("weights", {})
        if weights:
            weight_sum = sum(w for w in weights.values() if isinstance(w, (int, float)))
            if weight_sum > 1.05:
                issues.append({
                    "issue_id": "property_weight_sum",
                    "severity": "error",
                    "description": f"Portfolio weights sum to {weight_sum:.4f} (exceeds 1.05)",
                    "context": {"weight_sum": weight_sum},
                })

        # 3. Risk metrics non-negative
        var_95 = risk.get("portfolio_var_95")
        cvar_95 = risk.get("portfolio_cvar_95")
        if var_95 is not None and isinstance(var_95, (int, float)) and var_95 < 0:
            issues.append({
                "issue_id": "property_risk_nonnegative",
                "severity": "error",
                "description": f"portfolio_var_95 is negative: {var_95}",
                "context": {"portfolio_var_95": var_95},
            })
        if cvar_95 is not None and isinstance(cvar_95, (int, float)) and cvar_95 < 0:
            issues.append({
                "issue_id": "property_risk_nonnegative",
                "severity": "error",
                "description": f"portfolio_cvar_95 is negative: {cvar_95}",
                "context": {"portfolio_cvar_95": cvar_95},
            })

        # 4. No null composite signals (catch signals dict where composite is None)
        for ticker, sig_data in signals.items():
            if isinstance(sig_data, dict) and sig_data.get("composite") is None:
                # Already handled above in signal bounds loop
                pass

        return issues

    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Signal stability check (v1.1+): detect large single-cycle direction flips."""
        issues: List[Dict[str, Any]] = []

        if not self._deep_stability_enabled:
            # Save current signals for next deep check
            signals = data.get("signals", {})
            self._last_signals = {
                t: sd.get("composite") for t, sd in signals.items()
                if isinstance(sd, dict) and sd.get("composite") is not None
            }
            return issues

        signals = data.get("signals", {})
        for ticker, sig_data in signals.items():
            if not isinstance(sig_data, dict):
                continue
            current = sig_data.get("composite")
            if current is None:
                continue
            last = self._last_signals.get(ticker)
            if last is not None and isinstance(last, (int, float)):
                delta = abs(current - last)
                if delta > 1.5:
                    issues.append({
                        "issue_id": f"property_signal_stability_{ticker}",
                        "severity": "warning",
                        "description": (
                            f"Signal for {ticker} flipped by {delta:.4f} in one cycle "
                            f"(from {last:.4f} to {current:.4f}) — possible instability"
                        ),
                        "context": {"ticker": ticker, "last": last, "current": current, "delta": delta},
                    })

        # Update last signals
        self._last_signals = {
            t: sd.get("composite") for t, sd in signals.items()
            if isinstance(sd, dict) and sd.get("composite") is not None
        }

        return issues

    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        signals = data.get("signals", {})
        properties_tested = len(signals) + 2  # bounds per ticker + weight sum + risk checks
        violations = len(issues)
        active = self._active_issues()
        coverage = 1.0 - (violations / max(1, properties_tested))
        return {
            "properties_tested": properties_tested,
            "violations": violations,
            "active_issues": active,
            "coverage": coverage,
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """v1.0 -> v1.1: enable deep signal consistency checking when iteration >= 2."""
        if self._version == "1.0":
            iteration = feedback.get("iteration", 0)
            if iteration >= 2:
                self._deep_stability_enabled = True
                self._version = "1.1"
                return True
        return False


# ---------------------------------------------------------------------------
# InvariantDiscoveryNode
# ---------------------------------------------------------------------------

class InvariantDiscoveryNode(Node):
    """
    Observes pipeline state over time and discovers statistical invariants.

    Not a CleanerNode — it's a pure observer that accumulates metrics from
    multiple cycles and proposes/confirms invariants based on statistical patterns.
    """

    OBSERVATION_WINDOW = 5  # start discovering after N observations

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._observations: List[Dict[str, float]] = []
        self._proposed_invariants: List[Dict[str, Any]] = []
        self._confirmed_invariants: List[Dict[str, Any]] = []
        self._violation_count: int = 0
        self._execution_count: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0

    # -- Node interface

    def get_capabilities(self) -> List[str]:
        return ["observe", "discover_invariants"]

    def describe(self) -> str:
        return (
            "Observes pipeline metrics over time and discovers statistical invariants. "
            "Proposes and confirms invariants based on observed bounds, normalized-value "
            "properties, and stability patterns. Gets more accurate as observations accumulate."
        )

    def get_state(self) -> NodeState:
        total_obs = len(self._observations)
        violation_rate = self._violation_count / max(1, total_obs)
        health = max(0.0, 1.0 - violation_rate)
        return NodeState(
            node_id=self._node_id,
            name="InvariantDiscoveryNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "observations": total_obs,
                "confirmed_invariants": len(self._confirmed_invariants),
                "proposed_invariants": len(self._proposed_invariants),
            },
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1

        if input.action not in self.get_capabilities():
            latency_ms = (time.perf_counter() - t0) * 1000
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action: {input.action}"],
                metrics={"latency_ms": latency_ms},
            )

        try:
            if input.action == "observe":
                metrics = input.parameters.get("metrics", {})
                self._record_observation(metrics)
                latency_ms = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += latency_ms
                return NodeOutput(
                    request_id=input.request_id,
                    success=True,
                    result={"observations": len(self._observations), "violation_count": self._violation_count},
                    metrics={"latency_ms": latency_ms},
                )

            elif input.action == "discover_invariants":
                candidates = self._discover_from_observations()

                # Add new candidates to proposed, skip if already confirmed
                confirmed_keys = {(inv["metric"], inv["type"]) for inv in self._confirmed_invariants}
                for candidate in candidates:
                    key = (candidate["metric"], candidate["type"])
                    if key not in confirmed_keys:
                        # Check if already proposed
                        proposed_keys = {(inv["metric"], inv["type"]) for inv in self._proposed_invariants}
                        if key not in proposed_keys:
                            self._proposed_invariants.append(candidate)
                        # Promote high-confidence proposed to confirmed immediately (MVP)
                        if candidate.get("confidence", 0) >= 1.0 and key not in confirmed_keys:
                            self._confirmed_invariants.append(candidate)
                            confirmed_keys.add(key)

                latency_ms = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += latency_ms
                return NodeOutput(
                    request_id=input.request_id,
                    success=True,
                    result={
                        "confirmed_invariants": self._confirmed_invariants,
                        "proposed_invariants": self._proposed_invariants,
                        "total_confirmed": len(self._confirmed_invariants),
                    },
                    metrics={"latency_ms": latency_ms},
                )

        except Exception as exc:
            self._error_count += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": latency_ms},
            )

    def evaluate(self) -> Dict[str, float]:
        total_obs = len(self._observations)
        violation_rate = self._violation_count / max(1, total_obs)
        return {
            "confirmed_invariants": float(len(self._confirmed_invariants)),
            "violation_rate": violation_rate,
            "proposed_invariants": float(len(self._proposed_invariants)),
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """Improves naturally as observations accumulate. No explicit improvement arc."""
        return False

    # -- Internal helpers

    def _record_observation(self, metrics: Dict[str, float]) -> None:
        """Record a new observation and check confirmed invariants for violations."""
        clean_metrics = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
        self._observations.append(clean_metrics)
        # Keep last 50
        if len(self._observations) > 50:
            self._observations = self._observations[-50:]

        # Check confirmed invariants against new observation
        for inv in self._confirmed_invariants:
            metric = inv["metric"]
            if metric not in clean_metrics:
                continue
            val = clean_metrics[metric]
            inv_type = inv["type"]
            if inv_type == "lower_bound" and val < inv["bound"]:
                self._violation_count += 1
            elif inv_type == "upper_bound" and val > inv["bound"]:
                self._violation_count += 1

    def _discover_from_observations(self) -> List[Dict]:
        if len(self._observations) < self.OBSERVATION_WINDOW:
            return []

        # Collect per-metric values
        metric_values: Dict[str, List[float]] = {}
        for obs in self._observations:
            for k, v in obs.items():
                metric_values.setdefault(k, []).append(v)

        candidates = []
        for metric, values in metric_values.items():
            if len(values) < self.OBSERVATION_WINDOW:
                continue
            min_v = min(values)
            max_v = max(values)
            mean_v = sum(values) / len(values)

            # Invariant: always non-negative
            if min_v >= 0:
                candidates.append({
                    "metric": metric,
                    "type": "lower_bound",
                    "bound": 0.0,
                    "description": f"{metric} >= 0 (observed min={min_v:.4f} over {len(values)} cycles)",
                    "confidence": 1.0,
                })

            # Invariant: always <= 1.0 (rates/normalized values)
            if max_v <= 1.0 and metric.endswith(("_rate", "_score", "_coverage")):
                candidates.append({
                    "metric": metric,
                    "type": "upper_bound",
                    "bound": 1.0,
                    "description": f"{metric} <= 1.0 (observed max={max_v:.4f} over {len(values)} cycles)",
                    "confidence": 1.0,
                })

            # Invariant: metric has stabilized (std < 5% of mean)
            if len(values) >= 5 and mean_v > 0:
                std_v = (sum((v - mean_v) ** 2 for v in values) / len(values)) ** 0.5
                if std_v / mean_v < 0.05:
                    candidates.append({
                        "metric": metric,
                        "type": "stable",
                        "value": mean_v,
                        "std": std_v,
                        "description": f"{metric} is stable at {mean_v:.4f} ± {std_v:.4f}",
                        "confidence": 0.8,
                    })

        return candidates


# ---------------------------------------------------------------------------
# ConvergenceMonitorNode
# ---------------------------------------------------------------------------

class ConvergenceMonitorNode(CleanerNode):
    """
    Tracks long-term convergence of the self-improvement loop.

    Uses EMA smoothing, linear regression for trend detection, plateau detection,
    and oscillation detection (sign-flip counting). Renders an ASCII sparkline of
    the score history for human-readable terminal output.
    """

    EMA_ALPHA = 0.3
    PLATEAU_SLOPE_THRESHOLD = 0.001
    OSCILLATION_FLIP_THRESHOLD = 3  # N sign flips in last 10 deltas = oscillating

    def __init__(self) -> None:
        super().__init__()
        self._scores: List[float] = []
        self._score_emas: List[float] = []
        self._metric_history: Dict[str, List[float]] = {}
        self._oscillation_count: int = 0

    # -- CleanerNode interface

    def get_capabilities(self) -> List[str]:
        return ["monitor_convergence"]

    def describe(self) -> str:
        return (
            "Tracks long-term convergence of the self-improvement loop using EMA smoothing, "
            "linear regression slope, plateau detection, and oscillation counting. "
            "Generates ASCII sparklines for terminal output and flags degrading or oscillating trends."
        )

    def get_state(self) -> NodeState:
        slope = self._linear_regression_slope(self._scores[-10:]) if len(self._scores) >= 2 else 0.0
        last_ema = self._score_emas[-1] if self._score_emas else 0.0
        plateau = abs(slope) < self.PLATEAU_SLOPE_THRESHOLD and len(self._scores) >= 5

        # Determine trend for health
        if len(self._scores) >= 3:
            deltas = [
                self._scores[i] - self._scores[i - 1]
                for i in range(max(1, len(self._scores) - 10), len(self._scores))
            ]
            flips = sum(1 for i in range(1, len(deltas)) if deltas[i] * deltas[i - 1] < 0)
            oscillating = flips >= self.OSCILLATION_FLIP_THRESHOLD
        else:
            oscillating = False

        if oscillating:
            health = 0.5
        elif slope > self.PLATEAU_SLOPE_THRESHOLD:
            health = 1.0
        elif slope < -self.PLATEAU_SLOPE_THRESHOLD:
            health = 0.4
        elif plateau:
            health = 0.7
        else:
            health = 0.7

        return NodeState(
            node_id=self._node_id,
            name="ConvergenceMonitorNode",
            version=self._version,
            health=health,
            capabilities=self.get_capabilities(),
            metrics=self.evaluate(),
            metadata={
                "cycles_tracked": len(self._scores),
                "oscillation_count": self._oscillation_count,
            },
        )

    def evaluate(self) -> Dict[str, float]:
        slope = self._linear_regression_slope(self._scores[-10:]) if len(self._scores) >= 2 else 0.0
        last_ema = self._score_emas[-1] if self._score_emas else 0.0
        return {
            "ema_score": last_ema,
            "slope": slope,
            "oscillation_count": float(self._oscillation_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
        }

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        self._cycle_count += 1

        if input.action != "monitor_convergence":
            latency_ms = (time.perf_counter() - t0) * 1000
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action: {input.action}"],
                metrics={"latency_ms": latency_ms},
            )

        try:
            score = float(input.parameters.get("score", 0.0))
            system_metrics = input.parameters.get("system_metrics", {})

            # Track score history
            self._scores.append(score)
            ema = self._compute_ema(self._scores)
            self._score_emas.append(ema)

            # Track metric history
            for k, v in system_metrics.items():
                if isinstance(v, (int, float)):
                    self._metric_history.setdefault(k, []).append(float(v))

            # Compute trend
            recent = self._scores[-10:]
            slope = self._linear_regression_slope(recent)

            # Plateau detection
            plateau = abs(slope) < self.PLATEAU_SLOPE_THRESHOLD and len(self._scores) >= 5

            # Oscillation detection: count sign flips in score deltas
            if len(self._scores) >= 3:
                deltas = [
                    self._scores[i] - self._scores[i - 1]
                    for i in range(max(1, len(self._scores) - 10), len(self._scores))
                ]
                flips = sum(1 for i in range(1, len(deltas)) if deltas[i] * deltas[i - 1] < 0)
                oscillating = flips >= self.OSCILLATION_FLIP_THRESHOLD
                if oscillating:
                    self._oscillation_count += 1
            else:
                oscillating = False
                flips = 0

            # Trend classification
            if slope > self.PLATEAU_SLOPE_THRESHOLD:
                trend = "improving"
            elif slope < -self.PLATEAU_SLOPE_THRESHOLD:
                trend = "degrading"
            else:
                trend = "plateau"

            # Generate issues
            issues = []
            if plateau and len(self._scores) >= 8:
                issues.append({
                    "issue_id": "convergence_plateau",
                    "severity": "info",
                    "description": f"System score plateaued at {ema:.4f} (slope={slope:.6f})",
                    "context": {},
                })
            if oscillating:
                issues.append({
                    "issue_id": "convergence_oscillation",
                    "severity": "warning",
                    "description": f"Score oscillating ({flips} sign flips in last 10 cycles)",
                    "context": {},
                })
            if slope < -0.01 and len(self._scores) >= 5:
                issues.append({
                    "issue_id": "convergence_degrading",
                    "severity": "error",
                    "description": f"System score degrading: slope={slope:.4f}",
                    "context": {},
                })

            # Open/resolve issues
            raised_ids = {i["issue_id"] for i in issues}
            for iss in issues:
                self._open_issue(iss["issue_id"], iss["severity"], iss["description"], iss.get("context", {}))
            for issue_id in list(self._issues.keys()):
                if issue_id not in raised_ids:
                    self._resolve_issue(issue_id)

            # Find best improvement opportunity (which metric is degrading most)
            focus_metric = None
            focus_score = 0.0
            for metric, history in self._metric_history.items():
                if len(history) >= 3:
                    m_slope = self._linear_regression_slope(history[-5:])
                    if m_slope < 0 and abs(m_slope) > focus_score:
                        focus_score = abs(m_slope)
                        focus_metric = metric

            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms

            result = {
                "current_score": score,
                "ema_score": round(ema, 4),
                "trend": trend,
                "slope": round(slope, 6),
                "plateau": plateau,
                "oscillating": oscillating,
                "oscillation_count": self._oscillation_count,
                "sparkline": self._ascii_sparkline(self._scores),
                "focus_metric": focus_metric,
                "cycles_tracked": len(self._scores),
                "active_issues": self._active_issues(),
            }

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": latency_ms,
                    "convergence_slope": slope,
                    "ema_score": ema,
                },
            )

        except Exception as exc:
            self._error_count += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += latency_ms
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": latency_ms},
            )

    def _fast_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _deep_check(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _build_result(self, data: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "cycles_tracked": len(self._scores),
            "active_issues": self._active_issues(),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """Convergence monitor doesn't self-improve its algorithms."""
        return False

    # -- Computation helpers

    def _compute_ema(self, values: List[float]) -> float:
        """Compute EMA of values."""
        if not values:
            return 0.0
        ema = values[0]
        for v in values[1:]:
            ema = self.EMA_ALPHA * v + (1 - self.EMA_ALPHA) * ema
        return ema

    def _linear_regression_slope(self, values: List[float]) -> float:
        """Compute slope of least-squares line through values."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator != 0 else 0.0

    def _ascii_sparkline(self, values: List[float], width: int = 20) -> str:
        """Render values as ASCII sparkline using block characters."""
        if not values:
            return "─" * width
        blocks = "▁▂▃▄▅▆▇█"
        min_v = min(values)
        max_v = max(values)
        rng = max_v - min_v
        if rng == 0:
            return "▄" * min(len(values), width)
        # Sample to width
        step = max(1, len(values) // width)
        sampled = values[::step][:width]
        result = ""
        for v in sampled:
            idx = int((v - min_v) / rng * (len(blocks) - 1))
            result += blocks[idx]
        return result.ljust(width, "▁")
