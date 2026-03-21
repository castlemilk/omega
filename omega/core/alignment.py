"""
omega.core.alignment
====================

3-layer alignment system for the Omega autonomous AI framework.

This module enforces safety, outcome-based scoring, and multi-objective
optimality across autonomous node improvement cycles. Each layer addresses a
distinct failure mode in self-improving systems:

Layer 1 — SafetyEnvelope
    Hard constraints enforced unconditionally, regardless of reward or Pareto
    rank. Covers maximum per-asset position concentration, maximum portfolio
    drawdown, and maximum pairwise correlation. Also gates improvement
    magnitude to prevent runaway parameter shifts. These constraints can never
    be "optimised away" by higher layers.

Layer 2 — ParetoEvaluator (NSGA-II)
    Non-dominated sorting with crowding-distance tiebreaking (Deb et al. 2002)
    ranks nodes across multiple conflicting objectives (accuracy, latency,
    signal coverage, etc.) without collapsing them into a scalar. Returns Pareto
    front ranks so the orchestrator can compare nodes without imposing
    arbitrary objective weights.

Layer 3 — OutcomeBasedScorer
    Scores nodes by actual prediction accuracy and risk-adjusted returns,
    tracking a rolling history of predicted vs actual outcomes per node.
    Accuracy is computed as 1 - mean absolute relative error. Sharpe
    contribution measures risk-adjusted return contribution. The composite
    score is 0.6 * accuracy + 0.4 * sharpe_contribution, clamped to [0, 1].

AlignmentLayer orchestrates all three layers in a single
``check_improvement_cycle`` call, exposes ``record_improvement_attempt`` for
per-node parameter update gating, and ``record_outcome`` for tracking
prediction accuracy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("omega.core.alignment")


# ---------------------------------------------------------------------------
# Layer 1: SafetyEnvelope
# ---------------------------------------------------------------------------

class SafetyEnvelope:
    """Hard constraints enforced unconditionally — cannot be optimised away.

    Covers:
    - Per-asset position concentration (max_position_pct)
    - Portfolio drawdown (max_drawdown_pct)
    - Pairwise asset correlation (max_correlation)
    - Improvement magnitude (max_improvement_magnitude)
    """

    def __init__(
        self,
        max_position_pct: float = 0.25,
        max_drawdown_pct: float = 0.15,
        max_correlation: float = 0.85,
        max_improvement_magnitude: float = 0.5,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_correlation = max_correlation
        self.max_improvement_magnitude = max_improvement_magnitude

    def check(
        self,
        portfolio: Dict[str, float],
        drawdown: float = 0.0,
        correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Tuple[bool, List[str]]:
        """Validate portfolio against all hard constraints.

        Args:
            portfolio: asset → weight mapping. Weights need not sum to 1.
            drawdown: Current portfolio drawdown as a fraction (0–1).
            correlation_matrix: asset_i → {asset_j → correlation} mapping.

        Returns:
            (ok, violations) where ok=True iff no constraints are breached.
        """
        violations: List[str] = []
        total_weight = sum(abs(w) for w in portfolio.values()) or 1.0

        # 1. Position concentration check.
        for asset, weight in portfolio.items():
            pct = abs(weight) / total_weight
            if pct > self.max_position_pct:
                violations.append(
                    f"position_concentration: {asset} = {pct:.4f} > {self.max_position_pct}"
                )

        # 2. Drawdown check.
        if drawdown > self.max_drawdown_pct:
            violations.append(
                f"drawdown: {drawdown:.4f} > {self.max_drawdown_pct}"
            )

        # 3. Correlation check.
        if correlation_matrix:
            assets = list(portfolio.keys())
            seen: set = set()
            for i, asset_i in enumerate(assets):
                if asset_i not in correlation_matrix:
                    continue
                for asset_j, corr in correlation_matrix[asset_i].items():
                    if asset_j == asset_i:
                        continue
                    pair = tuple(sorted([asset_i, asset_j]))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    if abs(corr) > self.max_correlation:
                        violations.append(
                            f"correlation: ({asset_i}, {asset_j}) = {corr:.4f} > {self.max_correlation}"
                        )

        ok = len(violations) == 0
        if not ok:
            logger.warning("SafetyEnvelope violations: %s", violations)
        return ok, violations

    def check_improvement_magnitude(
        self,
        improvement_delta: float,
    ) -> Tuple[bool, str]:
        """Gate an improvement step on absolute magnitude.

        Returns (ok, reason) where ok=False if the magnitude of the delta
        exceeds max_improvement_magnitude.

        Args:
            improvement_delta: Signed scalar representing the change in
                parameter magnitude from the proposed update.

        Returns:
            (ok, reason) tuple.
        """
        if abs(improvement_delta) > self.max_improvement_magnitude:
            reason = (
                f"improvement_magnitude: |{improvement_delta:.6f}| "
                f"> {self.max_improvement_magnitude}"
            )
            logger.warning("SafetyEnvelope magnitude gate triggered: %s", reason)
            return False, reason
        return True, ""

    def clamp(self, portfolio: Dict[str, float]) -> Dict[str, float]:
        """Return a copy of portfolio with position concentrations clamped.

        Weights exceeding max_position_pct are clipped and the remainder is
        redistributed proportionally among unclamped positions. Correlation and
        drawdown cannot be clamped by this method — those require external
        portfolio reconstruction.

        Args:
            portfolio: asset → weight mapping.

        Returns:
            Clamped portfolio dict (same keys, adjusted weights).
        """
        if not portfolio:
            return {}

        total_weight = sum(abs(w) for w in portfolio.values()) or 1.0

        # Normalise to fraction space.
        fractions = {a: w / total_weight for a, w in portfolio.items()}

        # Iterative clamping: clip violators and redistribute surplus.
        max_iter = len(fractions) + 1
        for _ in range(max_iter):
            clipped: Dict[str, float] = {}
            free: Dict[str, float] = {}
            surplus = 0.0
            for asset, frac in fractions.items():
                sign = 1.0 if frac >= 0 else -1.0
                if abs(frac) > self.max_position_pct:
                    clipped[asset] = sign * self.max_position_pct
                    surplus += abs(frac) - self.max_position_pct
                else:
                    free[asset] = frac

            if surplus < 1e-10:
                # No violations remain.
                fractions = {**clipped, **free}
                break

            if not free:
                # All positions already at the cap; there is nowhere to redistribute.
                # Accept that the total may be < original and stop.
                fractions = clipped
                break

            # Redistribute surplus proportionally among free positions.
            free_total = sum(abs(v) for v in free.values()) or 1.0
            redistributed = {
                a: v + (v / free_total) * surplus for a, v in free.items()
            }
            fractions = {**clipped, **redistributed}

        # Re-scale back to original magnitude.
        return {a: f * total_weight for a, f in fractions.items()}


# ---------------------------------------------------------------------------
# Layer 2: ParetoEvaluator (NSGA-II)
# ---------------------------------------------------------------------------

class ParetoEvaluator:
    """Multi-objective NSGA-II ranking for node populations.

    Implements non-dominated sorting and crowding distance calculation following
    Deb et al. (2002) without any external dependencies.
    """

    _DEFAULT_DIRECTION = "maximize"

    def _compare(
        self,
        val_a: float,
        val_b: float,
        direction: str,
    ) -> int:
        """Return -1 if a < b, 0 if equal, 1 if a > b in the optimisation sense.

        For maximisation: higher is better (1). For minimisation: lower is better (1).
        """
        if direction == "minimize":
            # Lower value is "better", so flip.
            val_a, val_b = -val_a, -val_b
        if val_a > val_b:
            return 1
        if val_a < val_b:
            return -1
        return 0

    def dominates(
        self,
        a: Dict[str, float],
        b: Dict[str, float],
        objectives: List[str],
        directions: Dict[str, str],
    ) -> bool:
        """True if solution a Pareto-dominates solution b.

        a dominates b iff a is no worse in ALL objectives and strictly better in
        at least one.

        Args:
            a: Objective values for solution a.
            b: Objective values for solution b.
            objectives: List of objective names to consider.
            directions: objective → "maximize" | "minimize".

        Returns:
            True if a dominates b.
        """
        at_least_one_better = False
        for obj in objectives:
            direction = directions.get(obj, self._DEFAULT_DIRECTION)
            cmp = self._compare(
                a.get(obj, 0.0),
                b.get(obj, 0.0),
                direction,
            )
            if cmp < 0:
                # a is worse in this objective — cannot dominate.
                return False
            if cmp > 0:
                at_least_one_better = True
        return at_least_one_better

    def assign_ranks(
        self,
        population: List[Dict[str, float]],
        objectives: List[str],
        directions: Dict[str, str],
    ) -> List[int]:
        """Non-dominated sorting — returns Pareto front rank per individual.

        Rank 0 = Pareto-optimal (front 0). Rank 1 = optimal after removing
        front 0, etc.

        Args:
            population: List of objective-value dicts.
            objectives: Objectives to sort on.
            directions: Optimisation direction per objective.

        Returns:
            List of integer ranks aligned with population indices.
        """
        n = len(population)
        if n == 0:
            return []

        # domination_count[i] = number of solutions that dominate i
        # dominated_by[i] = set of solutions that i dominates
        domination_count = [0] * n
        dominated_by: List[List[int]] = [[] for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                if self.dominates(population[i], population[j], objectives, directions):
                    dominated_by[i].append(j)
                elif self.dominates(population[j], population[i], objectives, directions):
                    domination_count[i] += 1

        ranks = [-1] * n
        current_front = [i for i in range(n) if domination_count[i] == 0]
        rank = 0

        while current_front:
            for i in current_front:
                ranks[i] = rank
            next_front: List[int] = []
            for i in current_front:
                for j in dominated_by[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        next_front.append(j)
            current_front = next_front
            rank += 1

        return ranks

    def crowding_distance(
        self,
        front: List[Dict[str, float]],
        objectives: List[str],
    ) -> List[float]:
        """NSGA-II crowding distance for a single Pareto front.

        Measures the perimeter of the cuboid formed by nearest neighbours in
        objective space. Higher distance = more isolated = preferred for
        diversity.

        Args:
            front: List of objective-value dicts on one Pareto front.
            objectives: Objectives to use for distance computation.

        Returns:
            List of crowding distances aligned with front indices.
        """
        n = len(front)
        if n == 0:
            return []
        if n == 1:
            return [math.inf]

        distances = [0.0] * n

        for obj in objectives:
            # Sort front by this objective's value.
            sorted_idx = sorted(range(n), key=lambda i: front[i].get(obj, 0.0))
            obj_values = [front[i].get(obj, 0.0) for i in sorted_idx]
            obj_range = obj_values[-1] - obj_values[0]

            # Boundary individuals get infinite distance.
            distances[sorted_idx[0]] = math.inf
            distances[sorted_idx[-1]] = math.inf

            if obj_range == 0.0:
                continue

            for k in range(1, n - 1):
                distances[sorted_idx[k]] += (
                    (obj_values[k + 1] - obj_values[k - 1]) / obj_range
                )

        return distances

    def nsga2_sort(
        self,
        population: List[Dict[str, float]],
        objectives: List[str],
        directions: Optional[Dict[str, str]] = None,
    ) -> List[int]:
        """Sort population indices by NSGA-II rank then crowding distance.

        Args:
            population: List of objective-value dicts.
            objectives: Objectives to sort on.
            directions: Optional objective → direction mapping; defaults to
                maximize for all objectives.

        Returns:
            Indices into population sorted best→worst.
        """
        if not population:
            return []
        if directions is None:
            directions = {obj: "maximize" for obj in objectives}

        ranks = self.assign_ranks(population, objectives, directions)

        # Group indices by rank.
        rank_groups: Dict[int, List[int]] = {}
        for idx, rank in enumerate(ranks):
            rank_groups.setdefault(rank, []).append(idx)

        sorted_indices: List[int] = []
        for rank in sorted(rank_groups.keys()):
            group = rank_groups[rank]
            front_items = [population[i] for i in group]
            cd = self.crowding_distance(front_items, objectives)
            # Sort by crowding distance descending (higher = more diverse = better).
            group_sorted = sorted(
                range(len(group)),
                key=lambda k: cd[k],
                reverse=True,
            )
            sorted_indices.extend(group[k] for k in group_sorted)

        return sorted_indices


# ---------------------------------------------------------------------------
# Layer 3: OutcomeBasedScorer
# ---------------------------------------------------------------------------

class OutcomeBasedScorer:
    """Score nodes by actual prediction accuracy and risk-adjusted returns.

    Maintains a rolling history of (predicted, actual, return_contribution)
    tuples per node (last 50 observations). Computes:

    - accuracy = 1 - mean(|predicted - actual| / max(|actual|, 1e-6))
    - sharpe_contribution = mean(returns) / (std(returns) + 1e-8)
    - score = clamp(0.6 * accuracy + 0.4 * sharpe_contribution, 0, 1)
    """

    _MAX_HISTORY = 50

    def __init__(self) -> None:
        # node_id → list of (predicted, actual, return_contribution)
        self._history: Dict[str, List[Tuple[float, float, float]]] = {}

    def record_outcome(
        self,
        node_id: str,
        predicted: float,
        actual: float,
        return_contribution: float = 0.0,
    ) -> None:
        """Record one prediction outcome for a node.

        Args:
            node_id: Identifier of the node.
            predicted: The value the node predicted.
            actual: The realised value.
            return_contribution: The node's contribution to portfolio returns
                for this period.
        """
        history = self._history.setdefault(node_id, [])
        history.append((predicted, actual, return_contribution))
        if len(history) > self._MAX_HISTORY:
            self._history[node_id] = history[-self._MAX_HISTORY:]

    def _accuracy(self, node_id: str) -> float:
        """Rolling accuracy for a node: 1 - mean(|pred - actual| / max(|actual|, 1e-6))."""
        history = self._history.get(node_id, [])
        if not history:
            return 0.0
        errors = [
            abs(pred - actual) / max(abs(actual), 1e-6)
            for pred, actual, _ in history
        ]
        return 1.0 - (sum(errors) / len(errors))

    def _sharpe_contribution(self, node_id: str) -> float:
        """Sharpe ratio of return contributions: mean / (std + 1e-8)."""
        history = self._history.get(node_id, [])
        if not history:
            return 0.0
        returns = [rc for _, _, rc in history]
        mean_r = sum(returns) / len(returns)
        if len(returns) < 2:
            std_r = 0.0
        else:
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(variance)
        return mean_r / (std_r + 1e-8)

    def score(self, node_id: str) -> float:
        """Composite score for a node, clamped to [0, 1].

        score = 0.6 * accuracy + 0.4 * sharpe_contribution

        Args:
            node_id: Node to score.

        Returns:
            Scalar score in [0, 1].
        """
        acc = self._accuracy(node_id)
        sharpe = self._sharpe_contribution(node_id)
        raw = 0.6 * acc + 0.4 * sharpe
        return max(0.0, min(1.0, raw))

    def get_scores(self) -> Dict[str, float]:
        """Return scores for all tracked nodes.

        Returns:
            {node_id: score} for every node with recorded outcomes.
        """
        return {nid: self.score(nid) for nid in self._history}


# ---------------------------------------------------------------------------
# AlignmentDecision dataclass
# ---------------------------------------------------------------------------

@dataclass
class AlignmentDecision:
    """Result of one alignment evaluation cycle.

    Attributes:
        approved: False if any SafetyEnvelope hard constraint was violated.
        violations: List of human-readable violation descriptions.
        pareto_ranks: node_id → Pareto front rank (0 = optimal).
        outcome_scores: node_id → composite outcome score from OutcomeBasedScorer.
        improvement_magnitude_ok: True if the improvement magnitude check passed.
        magnitude_warning: True if any improvement exceeded the magnitude limit.
        cycle: Monotonic improvement cycle index.
    """
    approved: bool
    violations: List[str]
    pareto_ranks: Dict[str, int]
    outcome_scores: Dict[str, float]
    improvement_magnitude_ok: bool
    magnitude_warning: bool
    cycle: int


# ---------------------------------------------------------------------------
# AlignmentLayer — orchestrator
# ---------------------------------------------------------------------------

class AlignmentLayer:
    """Orchestrates all 3 alignment layers for the Omega improvement loop.

    Call ``check_improvement_cycle`` once per self-improvement cycle to obtain
    an ``AlignmentDecision``. Use ``record_improvement_attempt`` to gate
    individual node parameter updates. Use ``record_outcome`` to track
    prediction accuracy for OutcomeBasedScorer.

    Args:
        safety_config: Optional dict with keys matching SafetyEnvelope __init__
            parameters (``max_position_pct``, ``max_drawdown_pct``,
            ``max_correlation``, ``max_improvement_magnitude``).
    """

    def __init__(self, safety_config: Optional[Dict] = None) -> None:
        cfg = safety_config or {}
        self._safety_envelope = SafetyEnvelope(
            max_position_pct=cfg.get("max_position_pct", 0.25),
            max_drawdown_pct=cfg.get("max_drawdown_pct", 0.15),
            max_correlation=cfg.get("max_correlation", 0.85),
            max_improvement_magnitude=cfg.get("max_improvement_magnitude", 0.5),
        )
        self._pareto_evaluator = ParetoEvaluator()
        self._scorer = OutcomeBasedScorer()
        # Track magnitude warnings per node: node_id → bool
        self._magnitude_warnings: Dict[str, bool] = {}
        logger.info("AlignmentLayer initialised with safety_config=%s", cfg)

    def check_improvement_cycle(
        self,
        node_metrics_map: Dict[str, Dict[str, float]],
        system_metrics: Dict[str, float],
        portfolio: Dict[str, float],
        cycle: int = 0,
    ) -> AlignmentDecision:
        """Run all 3 alignment layers for one improvement cycle.

        Execution order:
        1. SafetyEnvelope — hard gate; approved=False if violated.
        2. ParetoEvaluator — rank nodes across node_metrics objectives.
        3. OutcomeBasedScorer — return current node performance scores.

        Args:
            node_metrics_map: node_id → {metric: value} for all nodes.
            system_metrics: System-level metrics (used for drawdown extraction
                via key "drawdown").
            portfolio: asset → weight for SafetyEnvelope check.
            cycle: Current improvement cycle index.

        Returns:
            AlignmentDecision summarising the outcome of all checks.
        """
        # ---- Layer 1: SafetyEnvelope ----------------------------------------
        drawdown = system_metrics.get("drawdown", 0.0)
        safe_ok, violations = self._safety_envelope.check(
            portfolio,
            drawdown=drawdown,
        )
        logger.info(
            "cycle=%d SafetyEnvelope ok=%s violations=%d", cycle, safe_ok, len(violations)
        )

        # ---- Layer 2: ParetoEvaluator ----------------------------------------
        node_ids = list(node_metrics_map.keys())
        population = [node_metrics_map[nid] for nid in node_ids]
        objectives = [k for k in (population[0].keys() if population else []) if k not in ("node_id",)]
        directions: Dict[str, str] = {}
        for obj in objectives:
            # Convention: metrics ending in "_latency" or "_error" are minimised.
            if obj.endswith("_latency") or obj.endswith("_error") or obj == "drawdown":
                directions[obj] = "minimize"
            else:
                directions[obj] = "maximize"

        pareto_ranks: Dict[str, int] = {}
        if population and objectives:
            ranks_list = self._pareto_evaluator.assign_ranks(population, objectives, directions)
            for nid, rank in zip(node_ids, ranks_list):
                pareto_ranks[nid] = rank
        else:
            pareto_ranks = {nid: 0 for nid in node_ids}

        logger.debug("cycle=%d pareto_ranks=%s", cycle, pareto_ranks)

        # ---- Layer 3: OutcomeBasedScorer ------------------------------------
        outcome_scores = self._scorer.get_scores()
        logger.debug("cycle=%d outcome_scores=%s", cycle, outcome_scores)

        # Determine improvement magnitude warning (any node triggered it).
        magnitude_warning = any(self._magnitude_warnings.values())
        # The magnitude check result for this cycle: True if no warnings active.
        improvement_magnitude_ok = not magnitude_warning

        return AlignmentDecision(
            approved=safe_ok,
            violations=violations,
            pareto_ranks=pareto_ranks,
            outcome_scores=outcome_scores,
            improvement_magnitude_ok=improvement_magnitude_ok,
            magnitude_warning=magnitude_warning,
            cycle=cycle,
        )

    def record_improvement_attempt(
        self,
        node_id: str,
        old_params: Dict[str, float],
        new_params: Dict[str, float],
    ) -> Tuple[bool, str]:
        """Gate a node parameter update via improvement magnitude check.

        Computes improvement_delta as the change in mean absolute parameter
        value and checks it against SafetyEnvelope.max_improvement_magnitude.

        Args:
            node_id: Identifier for the updating node.
            old_params: Current parameter values.
            new_params: Proposed new parameter values.

        Returns:
            (ok, reason) — ok=True if update is within magnitude budget.
        """
        old_mean = sum(abs(v) for v in old_params.values()) / max(len(old_params), 1)
        new_mean = sum(abs(v) for v in new_params.values()) / max(len(new_params), 1)
        delta = new_mean - old_mean

        ok, reason = self._safety_envelope.check_improvement_magnitude(delta)
        self._magnitude_warnings[node_id] = not ok

        logger.debug(
            "record_improvement_attempt node=%s ok=%s delta=%.6f reason=%s",
            node_id, ok, delta, reason,
        )
        return ok, reason

    def record_outcome(
        self,
        node_id: str,
        predicted: float,
        actual: float,
        return_contribution: float = 0.0,
    ) -> None:
        """Record a prediction outcome for a node.

        Delegates to OutcomeBasedScorer.record_outcome.

        Args:
            node_id: Identifier of the node.
            predicted: The value the node predicted.
            actual: The realised value.
            return_contribution: The node's contribution to portfolio returns.
        """
        self._scorer.record_outcome(node_id, predicted, actual, return_contribution)
        logger.debug(
            "record_outcome node=%s predicted=%.6f actual=%.6f return_contribution=%.6f",
            node_id, predicted, actual, return_contribution,
        )
