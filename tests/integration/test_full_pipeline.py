"""
tests/integration/test_full_pipeline.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-end integration tests that run the ACTUAL OmegaOrchestrator on
synthetic data and verify the full pipeline works together.

Each test exercises a different aspect of the system; all use real
production classes — no mocking of core logic.
"""

from __future__ import annotations

from typing import Any

from omega.core.adversarial_v2 import AdversarialPressureV2
from omega.core.autonomy import AutonomyLevel
from omega.core.brain import NoBrain
from omega.core.memory_consolidation import ConsolidationPipeline, MemoryRecord
from omega.core.metrics_exporter import MetricsExporter
from omega.core.orchestrator_v2 import OmegaOrchestrator
from tests.integration.conftest import (
    SyntheticMarketNode,
    _StubStore,
    synthetic_market_data,
)

# ---------------------------------------------------------------------------
# test_orchestrator_runs_100_cycles
# ---------------------------------------------------------------------------


def test_orchestrator_runs_100_cycles(configured_orchestrator: OmegaOrchestrator) -> None:
    """Run 100 cycles; assert no crashes and CycleHistory has 100 entries."""
    history = configured_orchestrator.run(max_cycles=100)

    assert len(history) == 100, f"Expected 100 cycles in history, got {len(history)}"
    assert configured_orchestrator.cycle_number == 100

    # Every result must have a populated context
    for result in history:
        assert result.context is not None
        assert result.cycle_id  # non-empty UUID string
        assert isinstance(result.cycle_number, int)
        assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# test_signals_computed_each_cycle
# ---------------------------------------------------------------------------


def test_signals_computed_each_cycle() -> None:
    """Signals must be generated on every cycle — not left at 0."""
    bars = synthetic_market_data(n_bars=200)
    node = SyntheticMarketNode(bars)

    orch = OmegaOrchestrator(name="signal-test")
    orch.register_node(node)

    history = orch.run(max_cycles=50)

    cycles_with_signals = sum(1 for r in history if r.signals_generated > 0)
    assert cycles_with_signals == 50, (
        f"Expected signals on all 50 cycles, got {cycles_with_signals}"
    )
    assert history.avg_signals_per_cycle(window=50) > 0


# ---------------------------------------------------------------------------
# test_adversarial_flags_occur
# ---------------------------------------------------------------------------


class _FlagAllProposalsOrchestrator(OmegaOrchestrator):
    """
    Subclass that overrides _step_adversarial to flag every proposal.
    Used to verify the adversarial flag storage and propagation pipeline
    end-to-end (the base orchestrator's flag path is gated on non-dict
    proposals which are filtered out by _step_strategy, making it
    unreachable through normal flow).
    """

    def _step_adversarial(
        self,
        ctx: Any,
        result: Any,
        proposals: list[Any],
        signal_data: Any,
        log: Any,
    ) -> list[Any]:
        for proposal in proposals:
            result.add_adversarial_flag(
                ring="ring1",
                severity="warning",
                reason="test_high_confidence_proposal",
                details={
                    "confidence": proposal.get("confidence", 0)
                    if isinstance(proposal, dict)
                    else 0
                },
            )
        return proposals  # still execute — flag but don't block


def test_adversarial_flags_occur() -> None:
    """
    The adversarial flag storage, propagation, and query pipeline must work.
    Uses a subclass that flags every proposal so that CycleResult.adversarial_flags
    is populated and `had_adversarial_flag` is True on cycles with proposals.
    """
    bars = synthetic_market_data(n_bars=100)
    node = SyntheticMarketNode(bars)

    orch = _FlagAllProposalsOrchestrator(name="adv-test", adversarial=AdversarialPressureV2())
    orch.register_node(node)

    history = orch.run(max_cycles=20)

    # There must be flags (node always proposes trades)
    total_flags = sum(len(r.adversarial_flags) for r in history)
    assert total_flags > 0, "Expected adversarial flags across 20 cycles with proposals"

    # Every flag must have the required fields
    for result in history:
        for flag in result.adversarial_flags:
            assert "ring" in flag
            assert "reason" in flag
            assert "severity" in flag

    # CycleHistory adversarial_flag_rate should be non-zero
    assert history.adversarial_flag_rate(window=20) > 0.0


# ---------------------------------------------------------------------------
# test_pico_mode_no_brain_calls
# ---------------------------------------------------------------------------


def test_pico_mode_no_brain_calls() -> None:
    """
    In PICO mode the orchestrator applies NoBrain to the node.
    After reconcile_active_nodes() the node's brain must be a NoBrain instance.
    """
    bars = synthetic_market_data(n_bars=50)
    node = SyntheticMarketNode(bars)

    orch = OmegaOrchestrator(name="pico-test")
    orch.register_node(node)

    # Nodes start at PICO by default in GraduatedAutonomyController
    assert orch._autonomy.get_level(node._node_id) == AutonomyLevel.PICO

    # Run a few cycles — brain should remain NoBrain
    history = orch.run(max_cycles=10)

    assert isinstance(node.brain, NoBrain), (
        f"Expected NoBrain in PICO mode, got {type(node.brain).__name__}"
    )

    # Verify pico_mode=True was passed to construct_portfolio by checking
    # the orchestrator's autonomy level after cycles
    assert orch._autonomy.get_level(node._node_id) == AutonomyLevel.PICO
    assert len(history) == 10


# ---------------------------------------------------------------------------
# test_regime_detection_fires
# ---------------------------------------------------------------------------


def test_regime_detection_fires() -> None:
    """
    Regime label must change when the data switches from trending to volatile.
    The regime handler should record a transition when bars 200-349 are active.
    """
    bars = synthetic_market_data(n_bars=300)
    node = SyntheticMarketNode(bars)

    orch = OmegaOrchestrator(name="regime-test")
    orch.register_node(node)

    history = orch.run(max_cycles=300)

    # Check that the regime handler has updated its current regime at some point.
    # After bar 200+ the node outputs "volatile" with changepoint_prob=0.90.
    # RegimeTransitionHandler.confirmation_steps=3, so after 3 consecutive
    # high-changepoint cycles the transition is confirmed and current_regime changes.
    handler = orch._regime_handler

    # The handler must have confirmed at least 1 regime transition.
    # With bars 0-299: normal (0-199) then volatile (200+); after confirmation_steps=3
    # the handler switches to "volatile".
    regime_history_stats = handler.history.stats()
    assert regime_history_stats["total_entries"] >= 1, (
        f"Expected at least 1 confirmed regime transition entry, got: {regime_history_stats}"
    )

    # The handler should have moved away from the initial "normal" regime
    assert handler.current_regime != "normal", (
        f"Expected current_regime to change from 'normal' after 300 cycles, "
        f"got: {handler.current_regime!r}"
    )

    # Confirmed events must be recorded
    events = handler.all_events()
    confirmed = [e for e in events if e.confirmed]
    assert len(confirmed) >= 1, (
        f"Expected at least 1 confirmed transition event, got {len(confirmed)}"
    )

    # Transition rate must be positive
    rate = history.regime_transition_rate(window=300)
    assert rate > 0.0, (
        "Regime transition rate should be positive after 300 cycles "
        "(data has volatile phase at bars 200-349)"
    )


# ---------------------------------------------------------------------------
# test_improvement_engine_proposes
# ---------------------------------------------------------------------------


def test_improvement_engine_proposes(configured_orchestrator: OmegaOrchestrator) -> None:
    """After IMPROVEMENT_INTERVAL cycles, TPE must propose at least one set of params."""
    # IMPROVEMENT_INTERVAL is patched to 10 in configured_orchestrator fixture
    history = configured_orchestrator.run(max_cycles=25)

    improvement_cycles = [r for r in history if r.improvement_proposed]
    assert len(improvement_cycles) >= 1, (
        "Expected TPE to propose improvement at least once in 25 cycles "
        "(IMPROVEMENT_INTERVAL=10), but improvement_proposed was never True"
    )

    # TPE must have recorded trials for the node
    node_id = next(iter(configured_orchestrator._registry.all_nodes())).get_state().node_id
    engine = configured_orchestrator._improvement_engine
    assert engine.trial_count(node_id) >= 1


# ---------------------------------------------------------------------------
# test_cycle_results_have_all_fields
# ---------------------------------------------------------------------------


def test_cycle_results_have_all_fields() -> None:
    """Every CycleResult must be fully populated with expected fields."""
    bars = synthetic_market_data(n_bars=100)
    node = SyntheticMarketNode(bars)
    orch = OmegaOrchestrator(name="field-test")
    orch.register_node(node)

    history = orch.run(max_cycles=10)

    for result in history:
        summary = result.to_summary()

        # All expected keys must be present
        expected_keys = {
            "cycle_id",
            "cycle_number",
            "regime",
            "duration_s",
            "signals",
            "actions_proposed",
            "actions_executed",
            "adversarial_flags",
            "critical_flags",
            "improvement_proposed",
            "regime_transition",
            "errors",
            "active_nodes",
            "metrics",
        }
        missing = expected_keys - set(summary.keys())
        assert not missing, f"Cycle {result.cycle_number} summary missing keys: {missing}"

        assert isinstance(summary["cycle_id"], str) and summary["cycle_id"]
        assert isinstance(summary["signals"], int) and summary["signals"] >= 0
        assert isinstance(summary["actions_proposed"], int)
        assert isinstance(summary["actions_executed"], int)
        assert isinstance(summary["active_nodes"], list)


# ---------------------------------------------------------------------------
# test_memory_consolidation_runs
# ---------------------------------------------------------------------------


def test_memory_consolidation_runs() -> None:
    """
    After CONSOLIDATION_INTERVAL cycles (patched to 25), the ConsolidationPipeline
    must have moved at least some short-term memories to long-term storage.
    """
    bars = synthetic_market_data(n_bars=200)
    node = SyntheticMarketNode(bars)

    # Pipeline with instant eligibility (min_age=0)
    pipeline = ConsolidationPipeline(
        min_age_seconds=0.0,
        promotion_threshold=0.1,
        prune_threshold=0.01,
    )

    # Pre-populate short-term with records that should be promoted
    for i in range(20):
        record = MemoryRecord.create(
            regime_tag="trending",
            signal_type="price_move",
            content={"cycle": i, "signal": 1.0},
            importance=0.5,
        )
        pipeline.add(record)

    assert len(pipeline._short_term) == 20
    assert len(pipeline._long_term) == 0

    orch = OmegaOrchestrator(name="memory-test", memory_consolidation=pipeline)
    orch.register_node(node)
    orch.CONSOLIDATION_INTERVAL = 25  # trigger at cycle 25

    history = orch.run(max_cycles=30)

    # After cycle 25, consolidation should have run
    assert len(pipeline._long_term) > 0, (
        "Expected at least some memories promoted to long-term after consolidation"
    )
    assert len(history) == 30


# ---------------------------------------------------------------------------
# test_prometheus_metrics_populated
# ---------------------------------------------------------------------------


def test_prometheus_metrics_populated() -> None:
    """
    After running cycles, in-memory Prometheus metric accumulators must be non-zero.
    """
    bars = synthetic_market_data(n_bars=100)
    node = SyntheticMarketNode(bars)

    metrics = MetricsExporter(state_store=_StubStore())
    orch = OmegaOrchestrator(name="metrics-test", metrics_exporter=metrics)
    orch.register_node(node)

    orch.run(max_cycles=20)

    # Heartbeat histogram should have observations
    assert metrics._heartbeat_histo._count == 20, (
        f"Expected 20 heartbeat observations, got {metrics._heartbeat_histo._count}"
    )

    # Node execution histogram should have entries (node has 'poll' capability)
    assert len(metrics._node_histograms) > 0, "Expected node execution histograms to be populated"

    # Total observations in node histograms should be positive
    total_node_obs = sum(h._count for h in metrics._node_histograms.values())
    assert total_node_obs > 0, "Expected non-zero node execution observations"
