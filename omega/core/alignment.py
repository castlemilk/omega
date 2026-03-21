"""
omega.core.alignment
====================

5-layer alignment system for the Omega autonomous AI framework.

This module enforces safety, incentive-compatibility, and multi-objective
optimality across autonomous node improvement cycles. Each layer addresses a
distinct failure mode in self-improving systems:

Layer 1 — HierarchicalRewardDecomposer
    Potential-based reward shaping (Ng et al. 1999) decomposes system-level PnL
    into node-level sub-goals. Ensures each node optimises for the collective
    rather than local proxies, using φ-potential functions over node health
    metrics and contribution-weighted PnL shares.

Layer 2 — RegularizationGuard
    KL-divergence constraints bound how far parameter distributions may shift in
    a single improvement cycle, preventing catastrophic forgetting and runaway
    gradient steps. Goodhart's law early-stopping detects when an optimised
    proxy metric diverges from the intended objective — the canonical failure
    mode of naive RL reward hacking.

Layer 3 — ParetoEvaluator (NSGA-II)
    Non-dominated sorting with crowding-distance tiebreaking (Deb et al. 2002)
    ranks nodes across multiple conflicting objectives (accuracy, latency,
    signal coverage, etc.) without collapsing them into a scalar. Returns Pareto
    front ranks so the orchestrator can compare nodes without imposing
    arbitrary objective weights.

Layer 4 — IncentiveDesigner (VCG mechanism)
    Vickrey-Clarke-Groves payments make truthful reporting a dominant strategy
    for each node. Each node's payment equals the externality it imposes on
    others: the welfare others would receive without it, minus the welfare they
    actually receive in the social optimum. This removes incentives for nodes to
    misreport capabilities or costs.

Layer 5 — SafetyEnvelope
    Hard constraints enforced unconditionally, regardless of reward or Pareto
    rank. Covers maximum per-asset position concentration, maximum portfolio
    drawdown, and maximum pairwise correlation. These constraints can never be
    "optimised away" by higher layers.

AlignmentLayer orchestrates all five layers in a single
``check_improvement_cycle`` call and exposes ``record_improvement_attempt`` for
per-node parameter update gating.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("omega.core.alignment")


# ---------------------------------------------------------------------------
# Layer 1: HierarchicalRewardDecomposer
# ---------------------------------------------------------------------------

class HierarchicalRewardDecomposer:
    """Potential-based reward shaping decomposing system PnL into node sub-goals.

    The potential function φ is a weighted sum of normalised node health metrics.
    Shaped reward for node i is:

        r̃_i = c_i * R_sys + γ * φ(s'_i) - φ(s_i)

    where c_i is the node's contribution share and R_sys is system PnL.
    """

    # Default weights for the potential function
    _POTENTIAL_WEIGHTS: Dict[str, float] = {
        "accuracy": 0.40,
        "health": 0.35,
        "signal_coverage": 0.25,
    }

    def potential(self, node_metrics: Dict[str, float]) -> float:
        """Scalar potential φ for a node's current state.

        Computes a weighted sum of key health metrics, each clamped to [0, 1].

        Args:
            node_metrics: Metric name → value mapping for one node.

        Returns:
            Scalar potential in [0, 1].
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for metric, weight in self._POTENTIAL_WEIGHTS.items():
            value = node_metrics.get(metric, 0.0)
            # Clamp to [0, 1] — metrics outside this range are normalised.
            value = max(0.0, min(1.0, float(value)))
            weighted_sum += weight * value
            total_weight += weight
        if total_weight == 0.0:
            return 0.0
        return weighted_sum / total_weight

    def _contribution_share(
        self,
        node_id: str,
        node_metrics: Dict[str, float],
        all_node_metrics: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> float:
        """Estimate node i's share of system contribution.

        Share = φ(node_i) / Σ φ(node_j) across all nodes. Falls back to
        φ(node_i) itself (treated as fraction of max=1) when the full map is
        unavailable.
        """
        phi_i = self.potential(node_metrics)
        if not all_node_metrics:
            # No context — treat φ as already a fraction of 1.
            return phi_i
        total_phi = sum(self.potential(m) for m in all_node_metrics.values())
        if total_phi == 0.0:
            n = len(all_node_metrics)
            return 1.0 / n if n > 0 else 0.0
        return phi_i / total_phi

    def shaped_reward(
        self,
        node_id: str,
        node_metrics: Dict[str, float],
        system_pnl: float,
        prev_metrics: Dict[str, float],
        gamma: float = 0.99,
        all_node_metrics: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> float:
        """Compute potential-shaped reward for a single node.

        Args:
            node_id: Identifier of the node (used for logging).
            node_metrics: Current metric values for the node.
            system_pnl: Realised system-level PnL for this cycle.
            prev_metrics: Metric values at the previous cycle.
            gamma: Discount factor for future potentials.
            all_node_metrics: Full node metric map for contribution estimation.

        Returns:
            Shaped reward scalar.
        """
        share = self._contribution_share(node_id, node_metrics, all_node_metrics)
        phi_next = self.potential(node_metrics)
        phi_prev = self.potential(prev_metrics)
        reward = share * system_pnl + gamma * phi_next - phi_prev
        logger.debug(
            "shaped_reward node=%s share=%.4f pnl=%.4f phi_next=%.4f phi_prev=%.4f => %.4f",
            node_id, share, system_pnl, phi_next, phi_prev, reward,
        )
        return reward

    def decompose_pnl(
        self,
        system_pnl: float,
        node_metrics_map: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Distribute system PnL proportionally to each node's potential.

        Args:
            system_pnl: Total system-level PnL to distribute.
            node_metrics_map: node_id → metric dict for all nodes.

        Returns:
            Mapping of node_id → sub-reward (sums to system_pnl).
        """
        if not node_metrics_map:
            return {}
        potentials = {nid: self.potential(m) for nid, m in node_metrics_map.items()}
        total = sum(potentials.values())
        result: Dict[str, float] = {}
        for nid, phi in potentials.items():
            if total == 0.0:
                share = 1.0 / len(potentials)
            else:
                share = phi / total
            result[nid] = share * system_pnl
        logger.debug("decompose_pnl total_phi=%.4f distribution=%s", total, result)
        return result


# ---------------------------------------------------------------------------
# Layer 2: RegularizationGuard
# ---------------------------------------------------------------------------

class RegularizationGuard:
    """KL divergence constraints and Goodhart's law early stopping.

    Prevents runaway parameter updates by bounding KL(old||new) and detects
    proxy-objective divergence via a rolling Goodhart score.
    """

    _EPSILON = 1e-10  # smoothing constant for KL computation

    def kl_divergence(
        self,
        p: Dict[str, float],
        q: Dict[str, float],
    ) -> float:
        """KL divergence KL(P||Q) for discrete distributions.

        Both dicts are normalised internally. Keys present in P but absent in Q
        contribute +inf (approximated with a very large value via epsilon
        smoothing). The distributions need not share the same key set.

        Args:
            p: Reference distribution (unnormalised weights).
            q: Approximate distribution (unnormalised weights).

        Returns:
            Non-negative KL divergence scalar.
        """
        # Build a unified support.
        keys = set(p.keys()) | set(q.keys())
        if not keys:
            return 0.0

        # Normalise both distributions.
        p_total = sum(p.values()) or 1.0
        q_total = sum(q.values()) or 1.0

        kl = 0.0
        for k in keys:
            p_k = p.get(k, 0.0) / p_total + self._EPSILON
            q_k = q.get(k, 0.0) / q_total + self._EPSILON
            kl += p_k * math.log(p_k / q_k)
        return max(0.0, kl)

    def check_update(
        self,
        old_params: Dict[str, float],
        new_params: Dict[str, float],
        epsilon: float = 0.1,
    ) -> Tuple[bool, float]:
        """Gate a parameter update on KL divergence.

        Args:
            old_params: Parameter distribution before update.
            new_params: Proposed parameter distribution after update.
            epsilon: Maximum allowable KL divergence.

        Returns:
            (ok, kl) where ok=True iff kl < epsilon.
        """
        kl = self.kl_divergence(old_params, new_params)
        ok = kl < epsilon
        logger.debug("check_update kl=%.6f epsilon=%.4f ok=%s", kl, epsilon, ok)
        return ok, kl

    def goodhart_score(
        self,
        optimized_metric: float,
        proxy_metric: float,
    ) -> float:
        """Ratio of proxy gain to optimised-metric gain.

        A score > 1 means the proxy improved more than the target — the classic
        Goodhart violation signal. Score ≤ 0 if the optimised metric degraded.

        Args:
            optimized_metric: Change in the true objective (can be negative).
            proxy_metric: Change in the proxy being optimised.

        Returns:
            goodhart_score scalar. Returns 0.0 when optimized_metric is zero.
        """
        if abs(optimized_metric) < self._EPSILON:
            # Avoid division by zero; large proxy gain with no true gain is bad.
            return abs(proxy_metric) / self._EPSILON if abs(proxy_metric) > self._EPSILON else 0.0
        return proxy_metric / optimized_metric

    def should_stop_early(
        self,
        goodhart_history: List[float],
        window: int = 5,
        threshold: float = 1.5,
    ) -> bool:
        """Detect sustained Goodhart violation via rolling window average.

        Args:
            goodhart_history: Time-ordered list of goodhart_score values.
            window: Number of recent observations to average.
            threshold: Average score above which early stopping fires.

        Returns:
            True if recent average goodhart score exceeds threshold.
        """
        if not goodhart_history:
            return False
        recent = goodhart_history[-window:]
        avg = sum(recent) / len(recent)
        stop = avg > threshold
        if stop:
            logger.warning(
                "Goodhart early stop triggered: avg_score=%.4f threshold=%.4f window=%d",
                avg, threshold, window,
            )
        return stop


# ---------------------------------------------------------------------------
# Layer 3: ParetoEvaluator (NSGA-II)
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
# Layer 4: IncentiveDesigner (VCG mechanism)
# ---------------------------------------------------------------------------

class IncentiveDesigner:
    """VCG mechanism ensuring truthful node reporting is the dominant strategy.

    Under VCG, each agent's payment equals the externality it imposes on others:
        payment_i = max_welfare_without_i  -  welfare_of_others_at_social_optimum

    This makes misreporting strictly dominated by truthful reporting.
    """

    def social_optimum(
        self,
        agent_values: Dict[str, Dict[str, float]],
        outcomes: List[str],
    ) -> str:
        """Find the outcome maximising total agent welfare.

        Args:
            agent_values: agent_id → {outcome → value} mapping.
            outcomes: List of feasible outcomes.

        Returns:
            The outcome string with highest total welfare.
        """
        if not outcomes:
            raise ValueError("outcomes must be non-empty")

        best_outcome = outcomes[0]
        best_welfare = -math.inf

        for outcome in outcomes:
            welfare = sum(
                vals.get(outcome, 0.0) for vals in agent_values.values()
            )
            if welfare > best_welfare:
                best_welfare = welfare
                best_outcome = outcome

        logger.debug(
            "social_optimum outcome=%s welfare=%.4f", best_outcome, best_welfare
        )
        return best_outcome

    def _welfare_without(
        self,
        excluded_agent: str,
        agent_values: Dict[str, Dict[str, float]],
        outcomes: List[str],
    ) -> float:
        """Maximum welfare achievable when agent `excluded_agent` is absent."""
        best = -math.inf
        for outcome in outcomes:
            welfare = sum(
                vals.get(outcome, 0.0)
                for aid, vals in agent_values.items()
                if aid != excluded_agent
            )
            if welfare > best:
                best = welfare
        return best if best != -math.inf else 0.0

    def vcg_payment(
        self,
        agent_id: str,
        agent_values: Dict[str, Dict[str, float]],
        outcomes: List[str],
    ) -> float:
        """Compute VCG payment for a single agent.

        payment_i = max_welfare_without_i - Σ_{j≠i} v_j(outcome*)

        A positive payment means the agent owes the mechanism (externality
        imposed on others). In ours context, negative values are subsidies.

        Args:
            agent_id: The agent whose payment to compute.
            agent_values: Full valuation matrix.
            outcomes: Feasible outcomes.

        Returns:
            VCG payment scalar for agent_id.
        """
        opt_outcome = self.social_optimum(agent_values, outcomes)

        # Welfare of all *other* agents at the social optimum.
        others_welfare_at_opt = sum(
            vals.get(opt_outcome, 0.0)
            for aid, vals in agent_values.items()
            if aid != agent_id
        )

        # Maximum welfare others could achieve without this agent.
        max_welfare_without = self._welfare_without(agent_id, agent_values, outcomes)

        payment = max_welfare_without - others_welfare_at_opt
        logger.debug(
            "vcg_payment agent=%s opt=%s others_at_opt=%.4f max_without=%.4f payment=%.4f",
            agent_id, opt_outcome, others_welfare_at_opt, max_welfare_without, payment,
        )
        return payment

    def compute_all_payments(
        self,
        agent_values: Dict[str, Dict[str, float]],
        outcomes: List[str],
    ) -> Dict[str, float]:
        """Compute VCG payments for all agents simultaneously.

        Args:
            agent_values: agent_id → {outcome → value} mapping.
            outcomes: Feasible outcomes.

        Returns:
            {agent_id: vcg_payment} for every agent.
        """
        return {
            aid: self.vcg_payment(aid, agent_values, outcomes)
            for aid in agent_values
        }


# ---------------------------------------------------------------------------
# Layer 5: SafetyEnvelope
# ---------------------------------------------------------------------------

class SafetyEnvelope:
    """Hard constraints enforced unconditionally — cannot be optimised away.

    Covers:
    - Per-asset position concentration (max_position_pct)
    - Portfolio drawdown (max_drawdown_pct)
    - Pairwise asset correlation (max_correlation)
    """

    def __init__(
        self,
        max_position_pct: float = 0.25,
        max_drawdown_pct: float = 0.15,
        max_correlation: float = 0.85,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_correlation = max_correlation

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
# AlignmentDecision dataclass
# ---------------------------------------------------------------------------

@dataclass
class AlignmentDecision:
    """Result of one alignment evaluation cycle.

    Attributes:
        approved: False if any SafetyEnvelope hard constraint was violated.
        violations: List of human-readable violation descriptions.
        pareto_ranks: node_id → Pareto front rank (0 = optimal).
        adjustments: node_id → shaped reward adjustment.
        vcg_payments: node_id → VCG payment (positive = owes mechanism).
        goodhart_warning: True if Goodhart early stopping was triggered globally.
        cycle: Monotonic improvement cycle index.
    """
    approved: bool
    violations: List[str]
    pareto_ranks: Dict[str, int]
    adjustments: Dict[str, float]
    vcg_payments: Dict[str, float]
    goodhart_warning: bool
    cycle: int


# ---------------------------------------------------------------------------
# AlignmentLayer — orchestrator
# ---------------------------------------------------------------------------

class AlignmentLayer:
    """Orchestrates all 5 alignment layers for the Omega improvement loop.

    Call ``check_improvement_cycle`` once per self-improvement cycle to obtain
    an ``AlignmentDecision``. Use ``record_improvement_attempt`` to gate
    individual node parameter updates.

    Args:
        safety_config: Optional dict with keys matching SafetyEnvelope __init__
            parameters (``max_position_pct``, ``max_drawdown_pct``,
            ``max_correlation``).
    """

    def __init__(self, safety_config: Optional[Dict] = None) -> None:
        cfg = safety_config or {}
        self._reward_decomposer = HierarchicalRewardDecomposer()
        self._regularization_guard = RegularizationGuard()
        self._pareto_evaluator = ParetoEvaluator()
        self._incentive_designer = IncentiveDesigner()
        self._safety_envelope = SafetyEnvelope(
            max_position_pct=cfg.get("max_position_pct", 0.25),
            max_drawdown_pct=cfg.get("max_drawdown_pct", 0.15),
            max_correlation=cfg.get("max_correlation", 0.85),
        )
        # Per-node Goodhart history: node_id → [scores]
        self._goodhart_history: Dict[str, List[float]] = {}
        logger.info("AlignmentLayer initialised with safety_config=%s", cfg)

    def check_improvement_cycle(
        self,
        node_metrics_map: Dict[str, Dict[str, float]],
        system_metrics: Dict[str, float],
        portfolio: Dict[str, float],
        cycle: int = 0,
    ) -> AlignmentDecision:
        """Run all 5 alignment layers for one improvement cycle.

        Execution order:
        1. SafetyEnvelope — hard gate; approved=False if violated.
        2. ParetoEvaluator — rank nodes across system_metrics objectives.
        3. IncentiveDesigner — compute VCG payments from node_metrics_map.
        4. HierarchicalRewardDecomposer — shaped sub-rewards from system PnL.
        5. RegularizationGuard — global Goodhart warning.

        Args:
            node_metrics_map: node_id → {metric: value} for all nodes.
            system_metrics: System-level metrics (used as Pareto objectives
                and for PnL extraction via key "pnl" or "system_pnl").
            portfolio: asset → weight for SafetyEnvelope check.
            cycle: Current improvement cycle index.

        Returns:
            AlignmentDecision summarising the outcome of all checks.
        """
        # ---- Layer 5: SafetyEnvelope ----------------------------------------
        drawdown = system_metrics.get("drawdown", 0.0)
        safe_ok, violations = self._safety_envelope.check(
            portfolio,
            drawdown=drawdown,
        )
        logger.info(
            "cycle=%d SafetyEnvelope ok=%s violations=%d", cycle, safe_ok, len(violations)
        )

        # ---- Layer 3: ParetoEvaluator ----------------------------------------
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

        # ---- Layer 4: IncentiveDesigner (VCG) --------------------------------
        # Each node's "value" for an outcome (outcome = node_id selected as
        # "system driver") is its potential scaled by its metrics. We treat
        # each node as both agent and outcome, which creates a contribution
        # auction: truthful reporting of capabilities is dominant.
        outcomes = node_ids if node_ids else ["none"]
        agent_values: Dict[str, Dict[str, float]] = {}
        reward_decomposer = self._reward_decomposer
        for nid in node_ids:
            # Agent nid values outcome o by the potential of node o
            # minus the cost it would impose on nid (simplified as 1-phi_nid).
            phi_self = reward_decomposer.potential(node_metrics_map[nid])
            agent_values[nid] = {}
            for outcome in outcomes:
                phi_outcome = reward_decomposer.potential(node_metrics_map[outcome])
                # Value is high when the outcome node is high-potential AND
                # different from self (no self-serving inflation).
                synergy = phi_outcome * (1.0 if outcome != nid else 0.5)
                agent_values[nid][outcome] = synergy

        vcg_payments: Dict[str, float] = {}
        if len(outcomes) > 0 and agent_values:
            vcg_payments = self._incentive_designer.compute_all_payments(
                agent_values, outcomes
            )
        else:
            vcg_payments = {nid: 0.0 for nid in node_ids}

        logger.debug("cycle=%d vcg_payments=%s", cycle, vcg_payments)

        # ---- Layer 1: HierarchicalRewardDecomposer ---------------------------
        system_pnl = system_metrics.get("pnl", system_metrics.get("system_pnl", 0.0))
        adjustments = self._reward_decomposer.decompose_pnl(system_pnl, node_metrics_map)
        logger.debug("cycle=%d pnl_decomposition=%s", cycle, adjustments)

        # ---- Layer 2: RegularizationGuard (global Goodhart warning) ----------
        # Aggregate Goodhart warning: are any nodes in sustained violation?
        goodhart_warning = False
        for nid, history in self._goodhart_history.items():
            if self._regularization_guard.should_stop_early(history):
                goodhart_warning = True
                logger.warning("cycle=%d Goodhart warning active for node=%s", cycle, nid)
                break

        return AlignmentDecision(
            approved=safe_ok,
            violations=violations,
            pareto_ranks=pareto_ranks,
            adjustments=adjustments,
            vcg_payments=vcg_payments,
            goodhart_warning=goodhart_warning,
            cycle=cycle,
        )

    def record_improvement_attempt(
        self,
        node_id: str,
        old_params: Dict[str, float],
        new_params: Dict[str, float],
    ) -> Tuple[bool, float]:
        """Gate a node parameter update via KL divergence and track Goodhart.

        Records the goodhart_score for this update (using KL as a proxy for
        "how much the parameter distribution changed" vs the improvement the
        update claims — represented as the ratio of new param mean to old param
        mean). The history is used by check_improvement_cycle for global
        Goodhart warnings.

        Args:
            node_id: Identifier for the updating node.
            old_params: Current parameter distribution.
            new_params: Proposed new parameter distribution.

        Returns:
            (ok, kl) — ok=True if update is within KL budget.
        """
        ok, kl = self._regularization_guard.check_update(old_params, new_params)

        # Compute a Goodhart score: how much did the param norm change relative
        # to the KL divergence? A large parameter shift for small KL indicates
        # the proxy (param norm) is being gamed.
        old_mean = sum(abs(v) for v in old_params.values()) / max(len(old_params), 1)
        new_mean = sum(abs(v) for v in new_params.values()) / max(len(new_params), 1)
        delta_proxy = new_mean - old_mean
        # Treat kl as the "true" optimised metric change.
        gs = self._regularization_guard.goodhart_score(
            optimized_metric=kl if kl > 0 else 1e-10,
            proxy_metric=abs(delta_proxy),
        )

        history = self._goodhart_history.setdefault(node_id, [])
        history.append(gs)
        # Keep history bounded to last 100 observations.
        if len(history) > 100:
            self._goodhart_history[node_id] = history[-100:]

        logger.debug(
            "record_improvement_attempt node=%s ok=%s kl=%.6f goodhart_score=%.4f",
            node_id, ok, kl, gs,
        )
        return ok, kl
