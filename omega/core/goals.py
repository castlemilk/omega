"""
omega.core.goals — 5-layer goal architecture for the Omega autonomous AI framework.

Layers:
  1. ConstitutionalConstraints — hard/soft safety rules
  2. BalancedScorecard        — multi-dimensional goal tracking
  3. NashWelfareAggregator    — Nash bargaining for competing objectives
  4. MPCReferenceTracker      — Model Predictive Control trajectory tracking
  5. HTNDecomposer            — Hierarchical Task Network decomposition

Orchestrated by GoalArchitecture.step() which returns a GoalDecision each cycle.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
    parameters: Dict[str, Any]
    assigned_to: str
    priority: float
    preconditions: Dict[str, Any]


@dataclass
class GoalDecision:
    approved: bool
    constraint_violations: List[ConstraintViolation]
    scorecard: Dict[str, float]
    composite_score: float
    nash_weights: Dict[str, float]
    subtasks: List[Task]
    tracking_error: float
    control_action: Dict[str, float]
    cycle: int


# ---------------------------------------------------------------------------
# Layer 1: ConstitutionalConstraints
# ---------------------------------------------------------------------------


class ConstitutionalConstraints:
    """Hard safety rules that override everything else."""

    def __init__(self) -> None:
        self._constraints: List[Dict[str, Any]] = []

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
        self, metrics: Dict[str, float]
    ) -> Tuple[bool, List[ConstraintViolation]]:
        """Evaluate all constraints against current metrics.

        Returns:
            (passed, violations) where passed=False if any hard constraint is violated.
        """
        violations: List[ConstraintViolation] = []
        for c in self._constraints:
            key = c["metric_key"]
            if key not in metrics:
                continue
            value = metrics[key]
            limit = c["limit"]
            direction = c["direction"]
            violated = False
            if direction == "max" and value > limit:
                violated = True
            elif direction == "min" and value < limit:
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

    def __init__(self, dimension_weights: Optional[Dict[str, float]] = None) -> None:
        if dimension_weights is None:
            equal = 1.0 / len(self.DIMENSIONS)
            self._weights: Dict[str, float] = {d: equal for d in self.DIMENSIONS}
        else:
            self._weights = {d: dimension_weights.get(d, 0.0) for d in self.DIMENSIONS}
            self._normalise_weights()

        # Current dimension scores
        self._scores: Dict[str, float] = {d: 0.0 for d in self.DIMENSIONS}
        # History of score snapshots for trend()
        self._history: List[Dict[str, float]] = []

    def _normalise_weights(self) -> None:
        total = sum(self._weights.values())
        if total > 0:
            for k in self._weights:
                self._weights[k] /= total

    def _map_returns(self, metrics: Dict[str, float]) -> float:
        """Combine sharpe_ratio (sigmoid-normalised) with pnl direction."""
        parts: List[float] = []
        if "sharpe_ratio" in metrics:
            parts.append(_sigmoid(metrics["sharpe_ratio"]))
        if "pnl" in metrics:
            # Normalise pnl: use sigmoid centred at 0 — positive pnl > 0.5
            parts.append(_sigmoid(metrics["pnl"]))
        if not parts:
            return 0.5
        return sum(parts) / len(parts)

    def _map_risk(self, metrics: Dict[str, float]) -> float:
        """Lower drawdown and lower error rate → higher score."""
        parts: List[float] = []
        if "max_drawdown_pct" in metrics:
            parts.append(max(0.0, 1.0 - metrics["max_drawdown_pct"] / 100.0))
        if "error_rate" in metrics:
            parts.append(max(0.0, 1.0 - metrics["error_rate"]))
        if not parts:
            return 0.5
        return sum(parts) / len(parts)

    def _map_diversification(self, metrics: Dict[str, float]) -> float:
        if "max_correlation" in metrics:
            return max(0.0, 1.0 - abs(metrics["max_correlation"]))
        if "coverage_rate" in metrics:
            return max(0.0, min(1.0, metrics["coverage_rate"]))
        return 0.5

    def _map_information_ratio(self, metrics: Dict[str, float]) -> float:
        if "information_ratio" in metrics:
            return _sigmoid(metrics["information_ratio"])
        if "accuracy" in metrics:
            return max(0.0, min(1.0, metrics["accuracy"]))
        return 0.5

    def update(self, metrics: Dict[str, float]) -> None:
        """Map incoming metrics to scorecard dimensions and record history."""
        self._scores["returns"] = self._map_returns(metrics)
        self._scores["risk"] = self._map_risk(metrics)
        self._scores["diversification"] = self._map_diversification(metrics)
        self._scores["information_ratio"] = self._map_information_ratio(metrics)
        self._history.append(copy.copy(self._scores))
        logger.debug("Scorecard updated: %s", self._scores)

    def score(self) -> Dict[str, float]:
        """Return current dimension scores."""
        return copy.copy(self._scores)

    def composite_score(self) -> float:
        """Weighted average of dimension scores."""
        return sum(self._scores[d] * self._weights[d] for d in self.DIMENSIONS)

    def trend(self, window: int = 5) -> Dict[str, float]:
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
# Layer 3: NashWelfareAggregator
# ---------------------------------------------------------------------------


class NashWelfareAggregator:
    """Nash bargaining solution for balancing competing objectives."""

    def __init__(
        self,
        objectives: List[str],
        disagreement_points: Optional[Dict[str, float]] = None,
    ) -> None:
        self._objectives = list(objectives)
        self._disagreement: Dict[str, float] = {o: 0.0 for o in objectives}
        if disagreement_points:
            self._disagreement.update(disagreement_points)
        self._weights: Dict[str, float] = {o: 1.0 / len(objectives) for o in objectives}
        self._outcomes_history: List[Dict[str, float]] = []

    def nash_welfare(self, outcomes: Dict[str, float]) -> float:
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

    def _random_simplex_point(self, n: int) -> List[float]:
        """Sample a random point on the probability simplex using exponential trick."""
        # Draw exponentials and normalise
        vals = [-math.log(max(1e-12, (i + 0.5) / n)) for i in range(n)]
        # Use a deterministic quasi-random approach for reproducibility across calls
        # Simple: generate via hash-based pseudo-random without random module
        # We use a linear congruential generator seeded by current time
        seed = int(time.monotonic_ns()) % (2**32)
        result: List[float] = []
        for i in range(n):
            seed = (seed * 1664525 + 1013904223) % (2**32)
            result.append(seed / (2**32))
        # Convert to simplex: -log(uniform) normalised
        exps = [-math.log(max(1e-15, v)) for v in result]
        total = sum(exps)
        return [e / total for e in exps]

    def optimal_weights(
        self,
        outcomes_history: List[Dict[str, float]],
        n_trials: int = 50,
    ) -> Dict[str, float]:
        """Find objective weights maximising Nash welfare over outcomes_history."""
        if not outcomes_history or not self._objectives:
            return copy.copy(self._weights)

        n = len(self._objectives)
        best_welfare = -1.0
        best_weights = self._random_simplex_point(n)

        for _ in range(n_trials):
            candidate = self._random_simplex_point(n)
            w = {obj: candidate[i] for i, obj in enumerate(self._objectives)}
            # Weighted aggregate welfare over history
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
        logger.debug("Nash optimal weights: %s (welfare=%.4f)", self._weights, best_welfare)
        return copy.copy(self._weights)

    def aggregate(self, metrics: Dict[str, float]) -> float:
        """Return Nash welfare for current metrics using current weights."""
        self._outcomes_history.append(copy.copy(metrics))
        # Keep history bounded
        if len(self._outcomes_history) > 200:
            self._outcomes_history = self._outcomes_history[-200:]
        weighted = {obj: metrics.get(obj, 0.0) * self._weights.get(obj, 0.0) for obj in self._objectives}
        return self.nash_welfare(weighted)


# ---------------------------------------------------------------------------
# Layer 4: MPCReferenceTracker
# ---------------------------------------------------------------------------


class MPCReferenceTracker:
    """Model Predictive Control for tracking reference trajectories."""

    K_P = 0.1  # Conservative proportional gain

    def __init__(self, objectives: List[str], horizon: int = 5) -> None:
        self._objectives = list(objectives)
        self._horizon = horizon
        self._reference: Dict[str, List[float]] = {}
        self._history: List[Dict[str, float]] = []

    def set_reference(self, trajectory: Dict[str, List[float]]) -> None:
        """Set target trajectories {objective: [values over horizon]}."""
        self._reference = {obj: list(vals) for obj, vals in trajectory.items()}
        logger.debug("MPC reference trajectory set for objectives: %s", list(self._reference.keys()))

    def update(self, current: Dict[str, float]) -> None:
        """Record current observations."""
        self._history.append(copy.copy(current))
        if len(self._history) > 200:
            self._history = self._history[-200:]

    def predict_horizon(self) -> Dict[str, List[float]]:
        """Linear extrapolation from recent history for each objective."""
        predictions: Dict[str, List[float]] = {}
        for obj in self._objectives:
            # Collect recent values
            values = [h[obj] for h in self._history if obj in h]
            if len(values) == 0:
                predictions[obj] = [0.0] * self._horizon
            elif len(values) == 1:
                predictions[obj] = [values[-1]] * self._horizon
            else:
                # Linear regression over last min(10, len) points
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
        """MSE between predicted horizon and reference trajectory."""
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

    def control_action(self) -> Dict[str, float]:
        """Proportional control: suggest adjustment = K_p * (reference - current)."""
        if not self._history:
            return {obj: 0.0 for obj in self._objectives}
        current = self._history[-1]
        actions: Dict[str, float] = {}
        for obj in self._objectives:
            ref_traj = self._reference.get(obj)
            # Use first step of reference as immediate target
            ref_val = ref_traj[0] if ref_traj else 0.0
            cur_val = current.get(obj, 0.0)
            actions[obj] = self.K_P * (ref_val - cur_val)
        return actions


# ---------------------------------------------------------------------------
# Layer 5: HTNDecomposer
# ---------------------------------------------------------------------------


class HTNDecomposer:
    """Hierarchical Task Network that decomposes high-level goals into subtasks."""

    def __init__(self) -> None:
        # goal → list of methods
        # method: {name, preconditions: Dict, subtasks: List[Dict]}
        # subtask dict: {name, parameters, assigned_to, priority}
        self._methods: Dict[str, List[Dict[str, Any]]] = {}

    def register_method(
        self,
        goal: str,
        method_name: str,
        preconditions: Dict[str, Any],
        subtasks: List[Dict[str, Any]],
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
        # research_cycle: normal pipeline
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
        # risk_breach: risk management priority
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
        # data_stale: refresh data
        self.register_method(
            goal="data_stale",
            method_name="data_refresh",
            preconditions={},
            subtasks=[
                {"name": "ingest_data", "parameters": {"force_refresh": True}, "assigned_to": "data_ingestion_node", "priority": 1.0},
                {"name": "generate_signals", "parameters": {}, "assigned_to": "signal_generation_node", "priority": 0.9},
            ],
        )
        # system_improve: self-improvement cycle
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
        self, preconditions: Dict[str, Any], state: Dict[str, Any]
    ) -> bool:
        """Check all preconditions against state.

        Supports: {"metric": {">": val}}, {"metric": {"<": val}},
                  {"metric": {">=": val}}, {"metric": {"<=": val}},
                  {"metric": {"==": val}}, simple equality {"metric": val}
        """
        for key, condition in preconditions.items():
            state_val = state.get(key)
            if state_val is None:
                # If key not in state, precondition cannot be satisfied
                # Allow it if condition is an equality check with None
                if isinstance(condition, dict):
                    return False
                # Simple value: treat missing as not-equal
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
                # Simple equality
                if state_val != condition:
                    return False
        return True

    def applicable_methods(
        self, goal: str, state: Dict[str, Any]
    ) -> List[str]:
        """Return method names where all preconditions are satisfied by state."""
        methods = self._methods.get(goal, [])
        return [
            m["name"]
            for m in methods
            if self._check_preconditions(m["preconditions"], state)
        ]

    def _build_tasks(self, subtask_dicts: List[Dict[str, Any]]) -> List[Task]:
        tasks: List[Task] = []
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
        state: Dict[str, Any],
    ) -> List[Task]:
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

        # No applicable method: return a default single task
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
# GoalArchitecture — orchestrates all 5 layers
# ---------------------------------------------------------------------------


class GoalArchitecture:
    """Orchestrates all 5 goal layers and produces a GoalDecision each cycle."""

    _DEFAULT_OBJECTIVES = ["sharpe_ratio", "coverage_rate", "error_rate"]

    def __init__(
        self,
        objectives: Optional[List[str]] = None,
        horizon: int = 5,
    ) -> None:
        self._objectives = list(objectives) if objectives else list(self._DEFAULT_OBJECTIVES)
        self._horizon = horizon

        # Layer 1
        self._constraints = ConstitutionalConstraints()
        self._constraints.register_defaults()

        # Layer 2
        self._scorecard = BalancedScorecard()

        # Layer 3
        self._nash = NashWelfareAggregator(objectives=self._objectives)

        # Layer 4
        self._mpc = MPCReferenceTracker(objectives=self._objectives, horizon=horizon)

        # Layer 5
        self._htn = HTNDecomposer()
        self._htn.register_vectora_methods()

        # History for Nash optimal weights computation
        self._metrics_history: List[Dict[str, float]] = []

        # Current goal to decompose (default: research_cycle)
        self._current_goal: str = "research_cycle"

        logger.info(
            "GoalArchitecture initialised | objectives=%s | horizon=%d",
            self._objectives,
            self._horizon,
        )

    def _infer_goal(
        self, metrics: Dict[str, float], system_state: Dict[str, Any]
    ) -> str:
        """Heuristically select the current goal from metrics/state."""
        # Priority order: risk_breach > data_stale > system_improve > research_cycle
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
        metrics: Dict[str, float],
        system_state: Optional[Dict[str, Any]] = None,
        cycle: int = 0,
    ) -> GoalDecision:
        """Execute one goal-architecture cycle and return a GoalDecision."""
        if system_state is None:
            system_state = {}

        logger.debug("GoalArchitecture.step() | cycle=%d | metrics=%s", cycle, metrics)

        # ------------------------------------------------------------------ #
        # Layer 1: Constitutional constraints
        # ------------------------------------------------------------------ #
        passed, violations = self._constraints.check(metrics)

        # ------------------------------------------------------------------ #
        # Layer 2: Balanced scorecard
        # ------------------------------------------------------------------ #
        self._scorecard.update(metrics)
        scorecard = self._scorecard.score()
        composite = self._scorecard.composite_score()

        # ------------------------------------------------------------------ #
        # Layer 3: Nash welfare + optimal weights
        # ------------------------------------------------------------------ #
        self._metrics_history.append(copy.copy(metrics))
        if len(self._metrics_history) > 500:
            self._metrics_history = self._metrics_history[-500:]

        nash_weights = self._nash.optimal_weights(
            self._metrics_history, n_trials=50
        )
        self._nash.aggregate(metrics)  # update internal history

        # ------------------------------------------------------------------ #
        # Layer 4: MPC tracker
        # ------------------------------------------------------------------ #
        self._mpc.update(metrics)
        tracking_err = self._mpc.tracking_error()
        ctrl = self._mpc.control_action()

        # ------------------------------------------------------------------ #
        # Layer 5: HTN decomposition
        # ------------------------------------------------------------------ #
        goal = self._infer_goal(metrics, system_state)
        self._current_goal = goal

        # Enrich system_state with relevant metrics for precondition checks
        merged_state = copy.copy(system_state)
        merged_state.update(metrics)

        subtasks = self._htn.decompose(goal, merged_state)

        decision = GoalDecision(
            approved=passed,
            constraint_violations=violations,
            scorecard=scorecard,
            composite_score=composite,
            nash_weights=nash_weights,
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
        self, trajectory: Dict[str, List[float]]
    ) -> None:
        """Set the MPC reference trajectory."""
        self._mpc.set_reference(trajectory)

    def register_objective(
        self, name: str, disagreement_point: float = 0.0
    ) -> None:
        """Add a new objective to the Nash aggregator and MPC tracker."""
        if name not in self._objectives:
            self._objectives.append(name)
        # Rebuild Nash aggregator preserving existing disagreement points
        existing_d = copy.copy(self._nash._disagreement)
        existing_d[name] = disagreement_point
        self._nash = NashWelfareAggregator(
            objectives=self._objectives,
            disagreement_points=existing_d,
        )
        # MPC tracker: rebuild with new objective list
        ref = copy.copy(self._mpc._reference)
        history = copy.copy(self._mpc._history)
        self._mpc = MPCReferenceTracker(
            objectives=self._objectives, horizon=self._horizon
        )
        self._mpc._reference = ref
        self._mpc._history = history
        logger.info("Registered new objective '%s' (d=%.4f)", name, disagreement_point)
