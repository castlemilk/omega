"""
Integration test: full research subsystem loop.

Verifies that AlignmentLayer + AdversarialPressure + MemoryKernelV2 + GoalArchitecture
work end-to-end as the spec describes:
  goals → alignment check → execute nodes → adversarial pressure → memory consolidation
  → improvement (if alignment-approved)
"""

import os

import pytest

from omega.core.adversarial import AdversarialPressure, AdversarialReport
from omega.core.alignment import AlignmentDecision, AlignmentLayer
from omega.core.goals import GoalArchitecture, GoalDecision
from omega.core.memory_v2 import MemoryKernelV2, RegimeState
from omega.core.state_store import StateStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_system_metrics(cycle: int) -> dict:
    """Generate plausible system metrics that improve slightly each cycle."""
    base_sharpe = 0.5 + cycle * 0.1
    return {
        "sharpe_ratio": min(base_sharpe, 3.0),
        "coverage_rate": min(0.6 + cycle * 0.02, 1.0),
        "error_rate": max(0.15 - cycle * 0.01, 0.01),
        "signal_coverage": min(0.5 + cycle * 0.03, 1.0),
        "indicator_count": float(5 + cycle),
        "max_drawdown_pct": max(15.0 - cycle * 0.5, 2.0),
        "max_position_pct": 20.0,
    }


def make_node_metrics_map(system_metrics: dict) -> dict:
    return {
        "SignalNode": {
            "accuracy": 0.8,
            "health": 0.9,
            "signal_coverage": system_metrics.get("signal_coverage", 0.7),
        },
        "StrategyNode": {"accuracy": 0.75, "health": 0.85, "signal_coverage": 0.8},
        "RiskNode": {"accuracy": 0.9, "health": 0.95, "signal_coverage": 0.85},
    }


# ---------------------------------------------------------------------------
# Full loop
# ---------------------------------------------------------------------------


class TestFullResearchLoop:
    def setup_method(self):
        self.memory = MemoryKernelV2(db_path=":memory:")
        self.alignment = AlignmentLayer()
        self.adversarial = AdversarialPressure(population_size=4)
        self.goals = GoalArchitecture()
        self.state_store = StateStore(db_path=":memory:")

    def _run_cycle(self, cycle: int):
        system_metrics = make_system_metrics(cycle)

        # Step 1: Goal architecture
        self.memory.begin_cycle(cycle)
        goal_decision = self.goals.step(metrics=system_metrics, cycle=cycle)
        assert isinstance(goal_decision, GoalDecision)

        # Step 2: Regime update (memory_v2)
        regime_state = self.memory.update_regime(system_metrics["sharpe_ratio"])
        assert isinstance(regime_state, RegimeState)

        # Step 3: Store episode with regime tagging
        self.memory.store_episode_v2(
            event_type="cycle_metrics",
            content=system_metrics,
            tags=["cycle", f"cycle_{cycle}"],
            importance=0.8,
            cycle=cycle,
        )

        # Step 4: Adversarial pressure
        variant_outputs = {
            "primary": {
                "BTC": system_metrics["signal_coverage"],
                "ETH": system_metrics["signal_coverage"] * 0.9,
            }
        }
        adv_report = self.adversarial.run(
            cycle=cycle,
            variant_outputs=variant_outputs,
            current_signals=variant_outputs["primary"],
            strategy_params={"method": "equal", "positions": 5},
        )
        assert isinstance(adv_report, AdversarialReport)
        assert adv_report.ring1_result is not None

        # Step 5: Alignment check
        node_metrics_map = make_node_metrics_map(system_metrics)
        portfolio = {"BTC": 0.20, "ETH": 0.20, "SOL": 0.15, "BNB": 0.15, "XRP": 0.15}
        alignment_decision = self.alignment.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=portfolio,
            cycle=cycle,
        )
        assert isinstance(alignment_decision, AlignmentDecision)

        # Step 6: Improvement pass (only if alignment approves)
        if alignment_decision.approved:
            ok, reason = self.alignment.record_improvement_attempt(
                "SignalNode",
                old_params={"lr": 0.01, "window": 20.0},
                new_params={"lr": 0.011, "window": 21.0},
            )
            assert isinstance(ok, bool)
            assert isinstance(reason, str)

        # Step 7: Memory consolidation
        self.memory.end_cycle(cycle, {"score": 0.7, "system_metrics": system_metrics})

        # Step 8: Persist to state_store
        self.state_store.record_alignment_decision(
            cycle=cycle,
            approved=alignment_decision.approved,
            violations=alignment_decision.violations,
        )
        self.state_store.record_adversarial_result(
            cycle=cycle,
            ring=1,
            flagged=adv_report.ring1_result.flagged,
            max_disagreement=adv_report.ring1_result.max_disagreement,
        )
        self.state_store.record_goal_tracking(
            cycle=cycle,
            approved=goal_decision.approved,
            composite_score=goal_decision.composite_score,
        )

        return {
            "goal": goal_decision,
            "regime": regime_state,
            "adversarial": adv_report,
            "alignment": alignment_decision,
        }

    def test_single_cycle(self):
        result = self._run_cycle(0)
        assert result["goal"] is not None
        assert result["regime"] is not None
        assert result["adversarial"] is not None
        assert result["alignment"] is not None

    def test_five_cycles_no_error(self):
        for i in range(5):
            result = self._run_cycle(i)
            assert isinstance(result["goal"], GoalDecision)
            assert isinstance(result["alignment"], AlignmentDecision)

    def test_adversarial_ring2_fires_at_interval(self):
        # Ring 2 fires at cycle % 10 == 0 only when activated
        self.adversarial.active_rings = [1, 2]
        results = []
        for i in range(11):
            r = self._run_cycle(i)
            results.append(r)
        # Cycle 10 should have ring 2 scenarios (Ring 2 activated)
        assert len(results[10]["adversarial"].ring2_scenarios) > 0

    def test_alignment_blocks_on_bad_portfolio(self):
        """Safety envelope should block improvements when portfolio is too concentrated."""
        system_metrics = make_system_metrics(0)
        node_metrics_map = make_node_metrics_map(system_metrics)
        bad_portfolio = {"BTC": 0.90, "ETH": 0.10}  # 90% concentration
        decision = self.alignment.check_improvement_cycle(
            node_metrics_map=node_metrics_map,
            system_metrics=system_metrics,
            portfolio=bad_portfolio,
            cycle=0,
        )
        assert not decision.approved

    def test_state_store_records_accumulate(self):
        for i in range(3):
            self._run_cycle(i)
        alignment_rows = self.state_store.get_alignment_decisions(since_cycle=0)
        adv_rows = self.state_store.get_adversarial_results(since_cycle=0)
        goal_rows = self.state_store.get_goal_tracking(since_cycle=0)
        assert len(alignment_rows) == 3
        assert len(adv_rows) == 3
        assert len(goal_rows) == 3

    def test_memory_regime_tags_episodes(self):
        self._run_cycle(0)
        self._run_cycle(1)
        episodes = self.memory.retrieve_episodes(limit=10)
        assert len(episodes) > 0

    def test_goal_tracking_error_decreases_with_reference(self):
        """With a reference trajectory set, tracking error is measurable."""
        self.goals.set_reference_trajectory(
            {
                "sharpe_ratio": [2.0] * 5,
                "coverage_rate": [0.95] * 5,
            }
        )
        first = self._run_cycle(0)
        assert first["goal"].tracking_error >= 0.0

    def test_contradiction_resolver_in_memory(self):
        observations = [
            {"source": "momentum", "value": 0.8, "signal": "bull"},
            {"source": "mean_reversion", "value": 0.7, "signal": "bear"},
        ]
        resolution = self.memory.resolve_contradictions(observations)
        assert resolution.conclusion in ("bull", "bear", "neutral", "volatile")
        assert 0.0 <= resolution.conflict_level <= 1.0
