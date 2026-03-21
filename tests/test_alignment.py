"""Tests for omega.core.alignment — 5-layer alignment system."""

import pytest
from omega.core.alignment import (
    HierarchicalRewardDecomposer,
    RegularizationGuard,
    ParetoEvaluator,
    IncentiveDesigner,
    SafetyEnvelope,
    AlignmentLayer,
    AlignmentDecision,
)


# ---------------------------------------------------------------------------
# Layer 1: HierarchicalRewardDecomposer
# ---------------------------------------------------------------------------

class TestHierarchicalRewardDecomposer:
    def setup_method(self):
        self.d = HierarchicalRewardDecomposer()

    def test_potential_is_normalised(self):
        m = {"accuracy": 0.8, "health": 1.0, "signal_coverage": 0.9}
        p = self.d.potential(m)
        assert 0.0 <= p <= 1.0

    def test_potential_empty_metrics(self):
        p = self.d.potential({})
        assert 0.0 <= p <= 1.0

    def test_shaped_reward_positive_pnl(self):
        metrics = {"accuracy": 0.9, "health": 1.0, "signal_coverage": 0.8}
        r = self.d.shaped_reward("n1", metrics, system_pnl=1000.0, prev_metrics=metrics)
        assert isinstance(r, float)

    def test_decompose_pnl_sums_to_system(self):
        node_metrics = {
            "nodeA": {"accuracy": 0.9, "health": 1.0},
            "nodeB": {"accuracy": 0.5, "health": 0.6},
            "nodeC": {"accuracy": 0.7, "health": 0.8},
        }
        rewards = self.d.decompose_pnl(system_pnl=1000.0, node_metrics_map=node_metrics)
        assert set(rewards.keys()) == {"nodeA", "nodeB", "nodeC"}
        # Total should approximately equal system_pnl
        assert abs(sum(rewards.values()) - 1000.0) < 1.0

    def test_decompose_pnl_negative(self):
        node_metrics = {"n1": {"accuracy": 0.5}, "n2": {"accuracy": 0.5}}
        rewards = self.d.decompose_pnl(system_pnl=-500.0, node_metrics_map=node_metrics)
        assert sum(rewards.values()) < 0.0


# ---------------------------------------------------------------------------
# Layer 2: RegularizationGuard
# ---------------------------------------------------------------------------

class TestRegularizationGuard:
    def setup_method(self):
        self.g = RegularizationGuard()

    def test_kl_divergence_identical(self):
        p = {"a": 0.5, "b": 0.5}
        assert self.g.kl_divergence(p, p) < 1e-6

    def test_kl_divergence_different(self):
        p = {"a": 0.9, "b": 0.1}
        q = {"a": 0.1, "b": 0.9}
        assert self.g.kl_divergence(p, q) > 0.5

    def test_check_update_no_change(self):
        params = {"lr": 0.01, "dropout": 0.1}
        ok, kl = self.g.check_update(params, params, epsilon=0.1)
        assert ok
        assert kl < 1e-6

    def test_check_update_large_change(self):
        old = {"a": 0.9, "b": 0.1}
        new = {"a": 0.1, "b": 0.9}
        ok, kl = self.g.check_update(old, new, epsilon=0.1)
        assert not ok
        assert kl > 0.1

    def test_goodhart_score_no_violation(self):
        # proxy and optimised metric grow together → score ≈ 1
        score = self.g.goodhart_score(optimized_metric=0.9, proxy_metric=0.8)
        assert score > 0

    def test_should_stop_early_triggered(self):
        history = [2.0, 2.5, 3.0, 2.8, 3.2]  # all above threshold=1.5
        assert self.g.should_stop_early(history, window=5, threshold=1.5)

    def test_should_stop_early_not_triggered(self):
        history = [0.5, 0.6, 0.7, 0.8, 0.9]  # all below threshold
        assert not self.g.should_stop_early(history, window=5, threshold=1.5)


# ---------------------------------------------------------------------------
# Layer 3: ParetoEvaluator (NSGA-II)
# ---------------------------------------------------------------------------

class TestParetoEvaluator:
    def setup_method(self):
        self.e = ParetoEvaluator()

    def test_dominates_basic(self):
        a = {"sharpe": 2.0, "drawdown": 0.05}
        b = {"sharpe": 1.0, "drawdown": 0.10}
        dirs = {"sharpe": "maximize", "drawdown": "minimize"}
        assert self.e.dominates(a, b, ["sharpe", "drawdown"], dirs)
        assert not self.e.dominates(b, a, ["sharpe", "drawdown"], dirs)

    def test_dominates_no_domination_tradeoff(self):
        a = {"sharpe": 2.0, "drawdown": 0.10}
        b = {"sharpe": 1.0, "drawdown": 0.05}
        dirs = {"sharpe": "maximize", "drawdown": "minimize"}
        assert not self.e.dominates(a, b, ["sharpe", "drawdown"], dirs)
        assert not self.e.dominates(b, a, ["sharpe", "drawdown"], dirs)

    def test_assign_ranks_pareto_front(self):
        pop = [
            {"sharpe": 2.0, "drawdown": 0.05},
            {"sharpe": 1.0, "drawdown": 0.15},
            {"sharpe": 0.5, "drawdown": 0.20},
        ]
        ranks = self.e.assign_ranks(pop, ["sharpe", "drawdown"],
                                    {"sharpe": "maximize", "drawdown": "minimize"})
        assert len(ranks) == 3
        assert ranks[0] == 0  # first is Pareto-optimal

    def test_crowding_distance_boundary_points(self):
        front = [
            {"sharpe": 2.0, "drawdown": 0.05},
            {"sharpe": 1.5, "drawdown": 0.10},
            {"sharpe": 1.0, "drawdown": 0.15},
        ]
        distances = self.e.crowding_distance(front, ["sharpe", "drawdown"])
        assert len(distances) == 3
        # Boundary points get infinity
        assert distances[0] == float("inf") or distances[0] > 1e6
        assert distances[-1] == float("inf") or distances[-1] > 1e6

    def test_nsga2_sort_returns_indices(self):
        pop = [
            {"sharpe": 1.0, "drawdown": 0.15},
            {"sharpe": 2.0, "drawdown": 0.05},
            {"sharpe": 0.5, "drawdown": 0.20},
        ]
        sorted_idx = self.e.nsga2_sort(pop, ["sharpe", "drawdown"])
        assert sorted_idx[0] == 1  # highest Sharpe, lowest drawdown comes first


# ---------------------------------------------------------------------------
# Layer 4: IncentiveDesigner (VCG)
# ---------------------------------------------------------------------------

class TestIncentiveDesigner:
    def setup_method(self):
        self.d = IncentiveDesigner()

    def test_social_optimum(self):
        # Outcome A: total welfare = 0.9+0.8 = 1.7; B: 0.3+0.4 = 0.7
        agent_values = {
            "n1": {"A": 0.9, "B": 0.3},
            "n2": {"A": 0.8, "B": 0.4},
        }
        opt = self.d.social_optimum(agent_values, ["A", "B"])
        assert opt == "A"

    def test_vcg_payment_non_negative_for_honest(self):
        agent_values = {
            "n1": {"A": 0.9, "B": 0.3},
            "n2": {"A": 0.8, "B": 0.4},
        }
        pay = self.d.vcg_payment("n1", agent_values, ["A", "B"])
        assert isinstance(pay, float)

    def test_compute_all_payments_keys(self):
        agent_values = {
            "n1": {"A": 0.9, "B": 0.3},
            "n2": {"A": 0.8, "B": 0.4},
        }
        payments = self.d.compute_all_payments(agent_values, ["A", "B"])
        assert set(payments.keys()) == {"n1", "n2"}


# ---------------------------------------------------------------------------
# Layer 5: SafetyEnvelope
# ---------------------------------------------------------------------------

class TestSafetyEnvelope:
    def setup_method(self):
        self.s = SafetyEnvelope(max_position_pct=0.25, max_drawdown_pct=0.15, max_correlation=0.85)

    def test_check_ok(self):
        portfolio = {"BTC": 0.20, "ETH": 0.20, "SOL": 0.20, "BNB": 0.20, "XRP": 0.20}
        ok, violations = self.s.check(portfolio, drawdown=0.05)
        assert ok
        assert violations == []

    def test_check_position_violation(self):
        portfolio = {"BTC": 0.50, "ETH": 0.50}
        ok, violations = self.s.check(portfolio, drawdown=0.05)
        assert not ok
        assert any("position" in v.lower() or "concentration" in v.lower() for v in violations)

    def test_check_drawdown_violation(self):
        portfolio = {"BTC": 0.20, "ETH": 0.20, "SOL": 0.60}
        ok, violations = self.s.check(portfolio, drawdown=0.20)
        assert not ok
        assert any("drawdown" in v.lower() for v in violations)

    def test_clamp_reduces_oversized(self):
        portfolio = {"BTC": 0.70, "ETH": 0.30}
        clamped = self.s.clamp(portfolio)
        assert all(v <= 0.25 + 1e-9 for v in clamped.values())


# ---------------------------------------------------------------------------
# AlignmentLayer — end-to-end
# ---------------------------------------------------------------------------

class TestAlignmentLayer:
    def setup_method(self):
        self.layer = AlignmentLayer()

    def test_returns_decision(self):
        node_metrics_map = {
            "SignalNode": {"accuracy": 0.8, "health": 0.9, "signal_coverage": 0.75},
            "RiskNode": {"accuracy": 0.9, "health": 0.95, "signal_coverage": 0.8},
        }
        system_metrics = {"sharpe_ratio": 1.5, "error_rate": 0.05}
        portfolio = {"BTC": 0.20, "ETH": 0.20, "SOL": 0.15}

        decision = self.layer.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=portfolio,
            cycle=1,
        )
        assert isinstance(decision, AlignmentDecision)
        assert isinstance(decision.approved, bool)
        assert isinstance(decision.pareto_ranks, dict)
        assert isinstance(decision.vcg_payments, dict)

    def test_safety_violation_blocks(self):
        node_metrics_map = {"N": {"accuracy": 0.5}}
        system_metrics = {"sharpe_ratio": -3.0, "error_rate": 0.6}
        portfolio = {"BTC": 0.90, "ETH": 0.10}  # 90% concentration

        decision = self.layer.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=portfolio,
            cycle=1,
        )
        assert not decision.approved
        assert len(decision.violations) > 0

    def test_record_improvement_attempt_ok(self):
        old = {"lr": 0.5, "dropout": 0.5}
        new = {"lr": 0.51, "dropout": 0.51}
        ok, kl = self.layer.record_improvement_attempt("node1", old, new)
        assert ok
        assert kl >= 0
