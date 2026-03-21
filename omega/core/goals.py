"""
omega.core.goals — 3-layer goal architecture for the Omega autonomous AI framework.

Layers:
  1. ConstitutionalConstraints — hard/soft safety rules (blocking gate)
  2. BalancedScorecard        — multi-dimensional goal tracking
  3. HTNDecomposer            — Hierarchical Task Network decomposition

AdaptiveReferenceTracker replaces the former MPCReferenceTracker.  Unlike MPC,
it does not assume fixed reference dynamics — instead it maintains a rolling EMA
target that adapts each cycle.  This avoids the fundamental tension between MPC's
fixed-trajectory assumption and self-improvement (system dynamics change every
improvement cycle).

NashWelfareAggregator and MPCReferenceTracker are retained in the module for
advanced/experimental use but are NOT wired into GoalArchitecture by default.

GoalArchitecture.step() returns a GoalDecision each cycle.
"""

from __future__ import annotations

import copy
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.core.goals")


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass
class ConstraintViolation:
    constraint_name: str
    metric_name: str
    current_value: float
    limit: float
    severity: str  # "hard" | "soft"


@dataclass
class Task:
    task_id: str
    name: str
    parameters: dict[str, Any]
    assigned_to: str
    priority: float
    preconditions: dict[str, Any]


@dataclass
class GoalDecision:
    approved: bool
    constraint_violations: list[ConstraintViolation]
    scorecard: dict[str, float]
    composite_score: float
    subtasks: list[Task]
    tracking_error: float
    control_action: dict[str, float]
    cycle: int


# ---------------------------------------------------------------------------
# Layer 1: ConstitutionalConstraints
# ---------------------------------------------------------------------------


class ConstitutionalConstraints:
    """Hard safety rules that override everything else."""

    def __init__(self) -> None:
        self._constraints: list[dict[str, Any]] = []

    def register(
        self,
        name: str,
        metric_key: str,
        limit: float,
        direction: str = "max",
        severity: str = "hard",
    ) -> None:
        """Register a constraint.

        Args:
            name: Human-readable constraint name.
            metric_key: Key in the metrics dict to check.
            limit: Threshold value.
            direction: "max" means metric must be <= limit; "min" means >= limit.
            severity: "hard" blocks the decision; "soft" warns only.
        """
        self._constraints.append(
            {
                "name": name,
                "metric_key": metric_key,
                "limit": limit,
                "direction": direction,
                "severity": severity,
            }
        )
        logger.debug(
            "Registered constraint %s: %s %s %s (%s)",
            name,
            metric_key,
            "<=" if direction == "max" else ">=",
            limit,
            severity,
        )

    def check(
        self, metrics: dict[str, float]
    ) -> tuple[bool, list[ConstraintViolation]]:
        """Evaluate all constraints against current metrics.

        Returns:
            (passed, violations) where passed=False if any hard constraint is violated.
        """
        violations: list[ConstraintViolation] = []
        for c in self._constraints:
            key = c["metric_key"]
            if key not in metrics:
                continue
            value = metrics[key]
            limit = c["limit"]
            direction = c["direction"]
            violated = False
            if (direction == "max" and value > limit) or (direction == "min" and value < limit):
                violated = True
            if violated:
                v = ConstraintViolation(
                    constraint_name=c["name"],
                    metric_name=key,
                    current_value=value,
                    limit=limit,
                    severity=c["severity"],
                )
                violations.append(v)
                logger.warning(
                    "Constraint violated: %s | %s=%.4f (limit=%.4f, %s)",
                    c["name"],
                    key,
                    value,
                    limit,
                    c["severity"],
                )
        hard_violated = any(v.severity == "hard" for v in violations)
        passed = not hard_violated
        return passed, violations

    def register_defaults(self) -> None:
        """Register sensible defaults for the Vectora pipeline."""
        self.register(
            "max_drawdown_limit",
            "max_drawdown_pct",
            15.0,
            direction="max",
            severity="hard",
        )
        self.register(
            "max_position_limit",
            "max_position_pct",
            25.0,
            direction="max",
            severity="hard",
        )
        self.register(
            "min_sharpe_ratio",
            "sharpe_ratio",
            -2.0,
            direction="min",
            severity="soft",
        )
        self.register(
            "max_error_rate",
            "error_rate",
            0.5,
            direction="max",
            severity="soft",
        )


# ---------------------------------------------------------------------------
# Layer 2: BalancedScorecard
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    """Sigmoid function clamped to [0, 1]."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


class BalancedScorecard:
    """Multi-dimensional goal tracking across four dimensions."""

    DIMENSIONS = ["returns", "risk", "diversification", "information_ratio"]

    def __init__(self, dimension_weights: dict[str, float] | None = None) -> None:
        if dimension_weights is None:
            equal = 1.0 / len(self.DIMENSIONS)
            self._weights: dict[str, float] = {d: equal for d in self.DIMENSIONS}
        else:
            self._weights = {d: dimension_weights.get(d, 0.0) for d in self.DIMENSIONS}
            self._normalise_weights()

        self._scores: dict[str, float] = {d: 0.0 for d in self.DIMENSIONS}
        self._history: list[dict[str, float]] = []

    def _normalise_weights(self) -> None:
        total = sum(self._weights.values())
        if total > 0:
            for k in self._weights:
                self._weights[k] /= total

    def _map_returns(self, metrics: dict[str, float]) -> float:
        parts: list[float] = []
        if "sharpe_ratio" in metrics:
            parts.append(_sigmoid(metrics["sharpe_ratio"]))
        if "pnl" in metrics:
            parts.append(_sigmoid(metrics["pnl"]))
        if not parts:
            return 0.5
        return sum(parts) / len(parts)

    def _map_risk(self, metrics: dict[str, float]) -> float:
        parts: list[float] = []
        if "max_drawdown_pct" in metrics:
            parts.append(max(0.0, 1.0 - metrics["max_drawdown_pct"] / 100.0))
        if "error_rate" in metrics:
            parts.append(max(0.0, 1.0 - metrics["error_rate"]))
        if not parts:
            return 0.5
        return sum(parts) / len(parts)

    def _map_diversification(self, metrics: dict[str, float]) -> float:
        if "max_correlation" in metrics:
            return max(0.0, 1.0 - abs(metrics["max_correlation"]))
        if "coverage_rate" in metrics:
            return max(0.0, min(1.0, metrics["coverage_rate"]))
        return 0.5

    def _map_information_ratio(self, metrics: dict[str, float]) -> float:
        if "information_ratio" in metrics:
            return _sigmoid(metrics["information_ratio"])
        if "accuracy" in metrics:
            return max(0.0, min(1.0, metrics["accuracy"]))
        return 0.5

    def update(self, metrics: dict[str, float]) -> None:
        """Map incoming metrics to scorecard dimensions and record history."""
        self._scores["returns"] = self._map_returns(metrics)
        self._scores["risk"] = self._map_risk(metrics)
        self._scores["diversification"] = self._map_diversification(metrics)
        self._scores["information_ratio"] = self._map_information_ratio(metrics)
        self._history.append(copy.copy(self._scores))
        logger.debug("Scorecard updated: %s", self._scores)

    def score(self) -> dict[str, float]:
        """Return current dimension scores."""
        return copy.copy(self._scores)

    def composite_score(self) -> float:
        """Weighted average of dimension scores."""
        return sum(self._scores[d] * self._weights[d] for d in self.DIMENSIONS)

    def trend(self, window: int = 5) -> dict[str, float]:
        """Return {dimension: delta} over the last `window` updates."""
        if len(self._history) < 2:
            return {d: 0.0 for d in self.DIMENSIONS}
        recent = self._history[-window:]
        if len(recent) < 2:
            return {d: 0.0 for d in self.DIMENSIONS}
        first = recent[0]
        last = recent[-1]
        return {d: last[d] - first[d] for d in self.DIMENSIONS}


# ---------------------------------------------------------------------------
# AdaptiveReferenceTracker  (replaces MPCReferenceTracker)
# ---------------------------------------------------------------------------


class AdaptiveReferenceTracker:
    """Rolling EMA reference tracker with uncertainty-aware horizon.

    Unlike MPC, this tracker does not assume fixed reference dynamics.  The
    reference adapts each cycle via an exponential moving average, making it
    compatible with self-improving systems where the underlying dynamics change
    every improvement cycle.

    Uncertainty grows proportionally to the rolling variance of each objective,
    widening the acceptable tracking band when the system is in a high-volatility
    regime.
    """

    def __init__(
        self,
        objectives: list[str],
        ema_alpha: float = 0.2,
        uncertainty_factor: float = 1.5,
    ) -> None:
        self._objectives = list(objectives)
        self._alpha = ema_alpha          # EMA smoothing factor (higher = faster adaptation)
        self._uncertainty_factor = uncertainty_factor

        # EMA reference values per objective
        self._ema: dict[str, float] = {}
        # Running variance (Welford online) per objective
        self._mean: dict[str, float] = {}
        self._m2: dict[str, float] = {}
        self._n: dict[str, int] = {}
        # Last observed values
        self._last: dict[str, float] = {}
        # Optional manual reference override
        self._manual_reference: dict[str, float] = {}

    def set_reference(self, trajectory: dict[str, list[float]]) -> None:
        """Override with a manual reference (first value of each trajectory used)."""
        self._manual_reference = {
            obj: vals[0] for obj, vals in trajectory.items() if vals
        }
        logger.debug("AdaptiveReferenceTracker: manual reference set %s", self._manual_reference)

    def update(self, current: dict[str, float]) -> None:
        """Update EMA reference and running variance with new observations."""
        for obj in self._objectives:
            val = current.get(obj)
            if val is None:
                continue
            self._last[obj] = val

            # EMA update
            if obj not in self._ema:
                self._ema[obj] = val
            else:
                self._ema[obj] = self._alpha * val + (1.0 - self._alpha) * self._ema[obj]

            # Welford online variance
            n = self._n.get(obj, 0) + 1
            self._n[obj] = n
            delta = val - self._mean.get(obj, val)
            self._mean[obj] = self._mean.get(obj, val) + delta / n
            delta2 = val - self._mean[obj]
            self._m2[obj] = self._m2.get(obj, 0.0) + delta * delta2

    def _variance(self, obj: str) -> float:
        n = self._n.get(obj, 0)
        if n < 2:
            return 0.0
        return self._m2.get(obj, 0.0) / n

    def tracking_error(self) -> float:
        """MSE between current observations and adaptive reference, uncertainty-scaled."""
        if not self._last:
            return 0.0
        total = 0.0
        count = 0
        for obj in self._objectives:
            if obj not in self._last:
                continue
            ref = self._manual_reference.get(obj, self._ema.get(obj))
            if ref is None:
                continue
            # Uncertainty band: widen tolerance proportional to volatility
            uncertainty = self._uncertainty_factor * math.sqrt(self._variance(obj))
            diff = abs(self._last[obj] - ref) - uncertainty
            diff = max(0.0, diff)  # only penalise outside the uncertainty band
            total += diff * diff
            count += 1
        return total / count if count > 0 else 0.0

    def control_action(self) -> dict[str, float]:
        """Proportional correction: K_p * (reference - current), scaled by uncertainty."""
        K_P = 0.1
        actions: dict[str, float] = {}
        for obj in self._objectives:
            ref = self._manual_reference.get(obj, self._ema.get(obj))
            cur = self._last.get(obj)
            if ref is None or cur is None:
                actions[obj] = 0.0
                continue
            # Scale down correction when uncertainty is high
            uncertainty = 1.0 + self._uncertainty_factor * math.sqrt(self._variance(obj))
            actions[obj] = K_P * (ref - cur) / uncertainty
        return actions


# ---------------------------------------------------------------------------
# Layer 3: HTNDecomposer
# ---------------------------------------------------------------------------


class HTNDecomposer:
    """Hierarchical Task Network that decomposes high-level goals into subtasks."""

    def __init__(self) -> None:
        self._methods: dict[str, list[dict[str, Any]]] = {}

    def register_method(
        self,
        goal: str,
        method_name: str,
        preconditions: dict[str, Any],
        subtasks: list[dict[str, Any]],
    ) -> None:
        """Register a decomposition method for a goal."""
        if goal not in self._methods:
            self._methods[goal] = []
        self._methods[goal].append(
            {
                "name": method_name,
                "preconditions": preconditions,
                "subtasks": subtasks,
            }
        )
        logger.debug("Registered HTN method '%s' for goal '%s'", method_name, goal)

    def register_vectora_methods(self) -> None:
        """Register default Vectora pipeline decompositions."""
        self.register_method(
            goal="research_cycle",
            method_name="standard_pipeline",
            preconditions={},
            subtasks=[
                {"name": "ingest_data", "parameters": {}, "assigned_to": "data_ingestion_node", "priority": 1.0},
                {"name": "generate_signals", "parameters": {}, "assigned_to": "signal_generation_node", "priority": 0.9},
                {"name": "run_strategy", "parameters": {}, "assigned_to": "strategy_node", "priority": 0.8},
                {"name": "assess_risk", "parameters": {}, "assigned_to": "risk_management_node", "priority": 0.85},
                {"name": "generate_report", "parameters": {}, "assigned_to": "reporting_node", "priority": 0.6},
            ],
        )
        self.register_method(
            goal="risk_breach",
            method_name="risk_response",
            preconditions={"max_drawdown_pct": {">": 10.0}},
            subtasks=[
                {"name": "run_risk_management", "parameters": {"mode": "emergency"}, "assigned_to": "risk_management_node", "priority": 1.0},
                {"name": "rebalance_portfolio", "parameters": {}, "assigned_to": "strategy_node", "priority": 0.95},
                {"name": "generate_report", "parameters": {"type": "risk_breach"}, "assigned_to": "reporting_node", "priority": 0.7},
            ],
        )
        self.register_method(
            goal="data_stale",
            method_name="data_refresh",
            preconditions={},
            subtasks=[
                {"name": "ingest_data", "parameters": {"force_refresh": True}, "assigned_to": "data_ingestion_node", "priority": 1.0},
                {"name": "generate_signals", "parameters": {}, "assigned_to": "signal_generation_node", "priority": 0.9},
            ],
        )
        self.register_method(
            goal="system_improve",
            method_name="self_improvement",
            preconditions={},
            subtasks=[
                {"name": "evaluate_nodes", "parameters": {}, "assigned_to": "orchestrator_node", "priority": 0.9},
                {"name": "improve_weakest_node", "parameters": {}, "assigned_to": "orchestrator_node", "priority": 0.85},
                {"name": "generate_report", "parameters": {"type": "improvement"}, "assigned_to": "reporting_node", "priority": 0.6},
            ],
        )

    def _check_preconditions(
        self, preconditions: dict[str, Any], state: dict[str, Any]
    ) -> bool:
        for key, condition in preconditions.items():
            state_val = state.get(key)
            if state_val is None:
                return False
            if isinstance(condition, dict):
                for op, limit in condition.items():
                    if op == ">":
                        if not (state_val > limit):
                            return False
                    elif op == "<":
                        if not (state_val < limit):
                            return False
                    elif op == ">=":
                        if not (state_val >= limit):
                            return False
                    elif op == "<=":
                        if not (state_val <= limit):
                            return False
                    elif op == "==":
                        if not (state_val == limit):
                            return False
                    else:
                        logger.warning("Unknown precondition operator: %s", op)
                        return False
            else:
                if state_val != condition:
                    return False
        return True

    def applicable_methods(
        self, goal: str, state: dict[str, Any]
    ) -> list[str]:
        """Return method names where all preconditions are satisfied by state."""
        methods = self._methods.get(goal, [])
        return [
            m["name"]
            for m in methods
            if self._check_preconditions(m["preconditions"], state)
        ]

    def _build_tasks(self, subtask_dicts: list[dict[str, Any]]) -> list[Task]:
        tasks: list[Task] = []
        for st in subtask_dicts:
            tasks.append(
                Task(
                    task_id=str(uuid.uuid4()),
                    name=st.get("name", "unknown"),
                    parameters=copy.copy(st.get("parameters", {})),
                    assigned_to=st.get("assigned_to", "orchestrator_node"),
                    priority=float(st.get("priority", 0.5)),
                    preconditions={},
                )
            )
        return tasks

    def decompose(
        self,
        goal: str,
        state: dict[str, Any],
    ) -> list[Task]:
        """Find applicable methods, pick the first, return Tasks."""
        methods = self._methods.get(goal, [])
        for method in methods:
            if self._check_preconditions(method["preconditions"], state):
                logger.debug(
                    "HTN: decomposing goal '%s' using method '%s'",
                    goal,
                    method["name"],
                )
                return self._build_tasks(method["subtasks"])

        logger.warning(
            "HTN: no applicable method for goal '%s'; returning default task",
            goal,
        )
        return [
            Task(
                task_id=str(uuid.uuid4()),
                name=goal,
                parameters={},
                assigned_to="orchestrator_node",
                priority=0.5,
                preconditions={},
            )
        ]


# ---------------------------------------------------------------------------
# Advanced / experimental (not wired into GoalArchitecture by default)
# ---------------------------------------------------------------------------


class NashWelfareAggregator:
    """Nash bargaining solution for balancing competing objectives.

    Advanced component — not activated in the default GoalArchitecture pipeline.
    Enable explicitly when convex utility assumptions hold and objectives are
    well-calibrated.
    """

    def __init__(
        self,
        objectives: list[str],
        disagreement_points: dict[str, float] | None = None,
    ) -> None:
        self._objectives = list(objectives)
        self._disagreement: dict[str, float] = {o: 0.0 for o in objectives}
        if disagreement_points:
            self._disagreement.update(disagreement_points)
        self._weights: dict[str, float] = {o: 1.0 / len(objectives) for o in objectives}
        self._outcomes_history: list[dict[str, float]] = []

    def nash_welfare(self, outcomes: dict[str, float]) -> float:
        """Compute Nash welfare = Π (u_i - d_i) using log-sum for stability."""
        log_sum = 0.0
        for obj in self._objectives:
            u = outcomes.get(obj, 0.0)
            d = self._disagreement.get(obj, 0.0)
            surplus = u - d
            if surplus <= 0:
                return 0.0
            log_sum += math.log(surplus)
        return math.exp(log_sum)

    def _random_simplex_point(self, n: int) -> list[float]:
        seed = int(time.monotonic_ns()) % (2**32)
        result: list[float] = []
        for i in range(n):
            seed = (seed * 1664525 + 1013904223) % (2**32)
            result.append(seed / (2**32))
        exps = [-math.log(max(1e-15, v)) for v in result]
        total = sum(exps)
        return [e / total for e in exps]

    def optimal_weights(
        self,
        outcomes_history: list[dict[str, float]],
        n_trials: int = 50,
    ) -> dict[str, float]:
        """Find objective weights maximising Nash welfare over outcomes_history."""
        if not outcomes_history or not self._objectives:
            return copy.copy(self._weights)

        n = len(self._objectives)
        best_welfare = -1.0
        best_weights = self._random_simplex_point(n)

        for _ in range(n_trials):
            candidate = self._random_simplex_point(n)
            w = {obj: candidate[i] for i, obj in enumerate(self._objectives)}
            total_welfare = 0.0
            for outcomes in outcomes_history:
                weighted_outcomes = {
                    obj: outcomes.get(obj, 0.0) * w[obj] for obj in self._objectives
                }
                total_welfare += self.nash_welfare(weighted_outcomes)
            avg_welfare = total_welfare / len(outcomes_history)
            if avg_welfare > best_welfare:
                best_welfare = avg_welfare
                best_weights = candidate

        self._weights = {obj: best_weights[i] for i, obj in enumerate(self._objectives)}
        return copy.copy(self._weights)

    def aggregate(self, metrics: dict[str, float]) -> float:
        """Return Nash welfare for current metrics using current weights."""
        self._outcomes_history.append(copy.copy(metrics))
        if len(self._outcomes_history) > 200:
            self._outcomes_history = self._outcomes_history[-200:]
        weighted = {obj: metrics.get(obj, 0.0) * self._weights.get(obj, 0.0) for obj in self._objectives}
        return self.nash_welfare(weighted)


class MPCReferenceTracker:
    """Model Predictive Control for tracking reference trajectories.

    Advanced component — retained for experimental use.  For production, prefer
    AdaptiveReferenceTracker which handles dynamic systems correctly.
    """

    K_P = 0.1

    def __init__(self, objectives: list[str], horizon: int = 5) -> None:
        self._objectives = list(objectives)
        self._horizon = horizon
        self._reference: dict[str, list[float]] = {}
        self._history: list[dict[str, float]] = []

    def set_reference(self, trajectory: dict[str, list[float]]) -> None:
        self._reference = {obj: list(vals) for obj, vals in trajectory.items()}

    def update(self, current: dict[str, float]) -> None:
        self._history.append(copy.copy(current))
        if len(self._history) > 200:
            self._history = self._history[-200:]

    def predict_horizon(self) -> dict[str, list[float]]:
        predictions: dict[str, list[float]] = {}
        for obj in self._objectives:
            values = [h[obj] for h in self._history if obj in h]
            if len(values) == 0:
                predictions[obj] = [0.0] * self._horizon
            elif len(values) == 1:
                predictions[obj] = [values[-1]] * self._horizon
            else:
                recent = values[-min(10, len(values)):]
                n = len(recent)
                x_mean = (n - 1) / 2.0
                y_mean = sum(recent) / n
                num = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
                den = sum((i - x_mean) ** 2 for i in range(n))
                slope = num / den if den != 0 else 0.0
                last = recent[-1]
                predictions[obj] = [last + slope * (t + 1) for t in range(self._horizon)]
        return predictions

    def tracking_error(self) -> float:
        if not self._reference:
            return 0.0
        predicted = self.predict_horizon()
        total_mse = 0.0
        count = 0
        for obj in self._objectives:
            ref = self._reference.get(obj)
            pred = predicted.get(obj)
            if ref is None or pred is None:
                continue
            steps = min(len(ref), len(pred), self._horizon)
            for t in range(steps):
                diff = pred[t] - ref[t]
                total_mse += diff * diff
                count += 1
        return total_mse / count if count > 0 else 0.0

    def control_action(self) -> dict[str, float]:
        if not self._history:
            return {obj: 0.0 for obj in self._objectives}
        current = self._history[-1]
        actions: dict[str, float] = {}
        for obj in self._objectives:
            ref_traj = self._reference.get(obj)
            ref_val = ref_traj[0] if ref_traj else 0.0
            cur_val = current.get(obj, 0.0)
            actions[obj] = self.K_P * (ref_val - cur_val)
        return actions


# ---------------------------------------------------------------------------
# GoalArchitecture — orchestrates 3 layers
# ---------------------------------------------------------------------------


class GoalArchitecture:
    """Orchestrates 3 goal layers and produces a GoalDecision each cycle.

    Pipeline: ConstitutionalConstraints → BalancedScorecard → HTNDecomposer
    Tracking: AdaptiveReferenceTracker (rolling EMA, uncertainty-aware)
    """

    _DEFAULT_OBJECTIVES = ["sharpe_ratio", "coverage_rate", "error_rate"]

    def __init__(
        self,
        objectives: list[str] | None = None,
    ) -> None:
        self._objectives = list(objectives) if objectives else list(self._DEFAULT_OBJECTIVES)

        # Layer 1
        self._constraints = ConstitutionalConstraints()
        self._constraints.register_defaults()

        # Layer 2
        self._scorecard = BalancedScorecard()

        # Layer 3
        self._htn = HTNDecomposer()
        self._htn.register_vectora_methods()

        # Adaptive reference tracker (replaces MPC)
        self._tracker = AdaptiveReferenceTracker(objectives=self._objectives)

        self._current_goal: str = "research_cycle"

        logger.info(
            "GoalArchitecture initialised | objectives=%s",
            self._objectives,
        )

    def _infer_goal(
        self, metrics: dict[str, float], system_state: dict[str, Any]
    ) -> str:
        """Heuristically select the current goal from metrics/state."""
        drawdown = metrics.get("max_drawdown_pct", 0.0)
        if drawdown > 10.0:
            return "risk_breach"
        if system_state.get("data_stale", False):
            return "data_stale"
        if system_state.get("trigger_improvement", False):
            return "system_improve"
        return "research_cycle"

    def step(
        self,
        metrics: dict[str, float],
        system_state: dict[str, Any] | None = None,
        cycle: int = 0,
    ) -> GoalDecision:
        """Execute one goal-architecture cycle and return a GoalDecision."""
        if system_state is None:
            system_state = {}

        logger.debug("GoalArchitecture.step() | cycle=%d | metrics=%s", cycle, metrics)

        # Layer 1: Constitutional constraints
        passed, violations = self._constraints.check(metrics)

        # Layer 2: Balanced scorecard
        self._scorecard.update(metrics)
        scorecard = self._scorecard.score()
        composite = self._scorecard.composite_score()

        # Adaptive reference tracker
        self._tracker.update(metrics)
        tracking_err = self._tracker.tracking_error()
        ctrl = self._tracker.control_action()

        # Layer 3: HTN decomposition
        goal = self._infer_goal(metrics, system_state)
        self._current_goal = goal
        merged_state = copy.copy(system_state)
        merged_state.update(metrics)
        subtasks = self._htn.decompose(goal, merged_state)

        decision = GoalDecision(
            approved=passed,
            constraint_violations=violations,
            scorecard=scorecard,
            composite_score=composite,
            subtasks=subtasks,
            tracking_error=tracking_err,
            control_action=ctrl,
            cycle=cycle,
        )

        logger.info(
            "GoalDecision | cycle=%d | approved=%s | goal=%s | composite=%.3f | "
            "tracking_error=%.4f | violations=%d",
            cycle,
            decision.approved,
            goal,
            composite,
            tracking_err,
            len(violations),
        )
        return decision

    def set_reference_trajectory(
        self, trajectory: dict[str, list[float]]
    ) -> None:
        """Set a manual reference trajectory on the adaptive tracker."""
        self._tracker.set_reference(trajectory)
