"""Tests for omega.core.alignment — 3-layer alignment system."""

from omega.core.alignment import (
    AlignmentDecision,
    AlignmentLayer,
    OutcomeBasedScorer,
    ParetoEvaluator,
    SafetyEnvelope,
)

# ---------------------------------------------------------------------------
# Layer 1: SafetyEnvelope
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

    def test_check_improvement_magnitude_ok(self):
        s = SafetyEnvelope(max_improvement_magnitude=0.5)
        ok, reason = s.check_improvement_magnitude(0.3)
        assert ok
        assert reason == ""

    def test_check_improvement_magnitude_exceeded(self):
        s = SafetyEnvelope(max_improvement_magnitude=0.5)
        ok, reason = s.check_improvement_magnitude(0.6)
        assert not ok
        assert "improvement_magnitude" in reason

    def test_check_improvement_magnitude_negative_delta(self):
        s = SafetyEnvelope(max_improvement_magnitude=0.5)
        ok, reason = s.check_improvement_magnitude(-0.7)
        assert not ok
        assert "improvement_magnitude" in reason

    def test_check_improvement_magnitude_boundary(self):
        s = SafetyEnvelope(max_improvement_magnitude=0.5)
        # Exactly at the limit — abs(0.5) is NOT > 0.5, so ok
        ok, reason = s.check_improvement_magnitude(0.5)
        assert ok

    def test_custom_max_improvement_magnitude(self):
        s = SafetyEnvelope(max_improvement_magnitude=0.1)
        ok, _ = s.check_improvement_magnitude(0.05)
        assert ok
        ok2, _ = s.check_improvement_magnitude(0.15)
        assert not ok2


# ---------------------------------------------------------------------------
# Layer 2: ParetoEvaluator (NSGA-II)
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
# Layer 3: OutcomeBasedScorer
# ---------------------------------------------------------------------------

class TestOutcomeBasedScorer:
    def setup_method(self):
        self.scorer = OutcomeBasedScorer()

    def test_get_scores_empty(self):
        scores = self.scorer.get_scores()
        assert scores == {}

    def test_record_outcome_single(self):
        self.scorer.record_outcome("n1", predicted=1.0, actual=1.0, return_contribution=0.1)
        scores = self.scorer.get_scores()
        assert "n1" in scores
        assert 0.0 <= scores["n1"] <= 1.0

    def test_accuracy_perfect_prediction(self):
        # Perfect predictions → accuracy = 1.0
        for _ in range(5):
            self.scorer.record_outcome("n1", predicted=2.0, actual=2.0, return_contribution=0.1)
        # accuracy = 1 - 0 = 1.0; score = 0.6 * 1.0 + 0.4 * sharpe
        score = self.scorer.score("n1")
        assert score > 0.5

    def test_accuracy_poor_prediction(self):
        # Predictions far off → accuracy near 0
        for _ in range(10):
            self.scorer.record_outcome("n1", predicted=100.0, actual=1.0, return_contribution=0.0)
        score = self.scorer.score("n1")
        # accuracy ≈ 1 - 99 = very negative, clamped to 0; sharpe = 0/tiny ≈ 0
        assert score == 0.0

    def test_sharpe_contribution_positive_returns(self):
        # Consistent positive returns → positive sharpe → higher score
        for i in range(10):
            self.scorer.record_outcome("n1", predicted=1.0, actual=1.0, return_contribution=0.05)
        score = self.scorer.score("n1")
        assert score > 0.5

    def test_sharpe_contribution_negative_returns(self):
        # Consistent negative returns → negative sharpe → pulls score down
        for _ in range(10):
            self.scorer.record_outcome("n1", predicted=1.0, actual=1.0, return_contribution=-0.1)
        score = self.scorer.score("n1")
        # accuracy=1.0 (perfect pred), sharpe negative → score < 0.6
        assert score < 0.6

    def test_rolling_history_capped_at_50(self):
        for i in range(60):
            self.scorer.record_outcome("n1", predicted=float(i), actual=float(i), return_contribution=0.01)
        # Should only keep last 50
        assert len(self.scorer._history["n1"]) == 50

    def test_get_scores_multiple_nodes(self):
        self.scorer.record_outcome("n1", 1.0, 1.0, 0.1)
        self.scorer.record_outcome("n2", 2.0, 2.0, 0.2)
        scores = self.scorer.get_scores()
        assert set(scores.keys()) == {"n1", "n2"}

    def test_score_unknown_node_returns_zero(self):
        score = self.scorer.score("unknown")
        assert score == 0.0

    def test_score_clamped_to_zero(self):
        # Extreme scenario: accuracy very negative → still clamped to 0
        for _ in range(5):
            self.scorer.record_outcome("n1", predicted=1000.0, actual=0.001, return_contribution=-1.0)
        score = self.scorer.score("n1")
        assert score >= 0.0


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
        assert isinstance(decision.outcome_scores, dict)
        assert isinstance(decision.improvement_magnitude_ok, bool)
        assert isinstance(decision.magnitude_warning, bool)

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

    def test_record_improvement_attempt_small_delta(self):
        old = {"lr": 0.5, "dropout": 0.5}
        new = {"lr": 0.51, "dropout": 0.51}
        ok, reason = self.layer.record_improvement_attempt("node1", old, new)
        assert ok
        assert reason == ""

    def test_record_improvement_attempt_large_delta(self):
        old = {"lr": 0.1, "dropout": 0.1}
        new = {"lr": 0.9, "dropout": 0.9}
        ok, reason = self.layer.record_improvement_attempt("node1", old, new)
        assert not ok
        assert "improvement_magnitude" in reason

    def test_magnitude_warning_propagates_to_decision(self):
        # Trigger a magnitude warning first
        old = {"lr": 0.0}
        new = {"lr": 1.0}
        self.layer.record_improvement_attempt("n1", old, new)

        node_metrics_map = {"n1": {"accuracy": 0.8}}
        system_metrics = {}
        portfolio = {"BTC": 0.2, "ETH": 0.2}

        decision = self.layer.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=portfolio,
        )
        assert decision.magnitude_warning is True
        assert decision.improvement_magnitude_ok is False

    def test_record_outcome_delegates_to_scorer(self):
        self.layer.record_outcome("n1", predicted=1.0, actual=1.0, return_contribution=0.1)
        scores = self.layer._scorer.get_scores()
        assert "n1" in scores

    def test_outcome_scores_in_decision(self):
        self.layer.record_outcome("n1", predicted=1.0, actual=1.0, return_contribution=0.05)
        node_metrics_map = {"n1": {"accuracy": 0.9}}
        decision = self.layer.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics={},
            portfolio={"BTC": 0.2},
        )
        assert "n1" in decision.outcome_scores

    def test_no_magnitude_warning_by_default(self):
        node_metrics_map = {"n1": {"accuracy": 0.9}}
        decision = self.layer.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics={},
            portfolio={"BTC": 0.2},
        )
        assert decision.magnitude_warning is False
        assert decision.improvement_magnitude_ok is True
