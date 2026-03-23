"""
Tests for Ticket #3 — AdversarialPressureV2 wiring + DevilsAdvocateNode structural challenges.

Covers:
  - Concentration risk fires when single position > 30% of portfolio
  - Data staleness fires when freshness > 60 minutes
  - Signal correlation fires when top-2 signals are co-directional and close
  - None of the checks fire on clean data
  - strategy_params in _step_adversarial contains real position data
  - _run_da_structural_checks integrates with the orchestrator cycle
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from omega.core.challenge_registry import Challenge, ChallengeSeverity, ChallengeStatus
from omega.nodes.devils_advocate import DevilsAdvocateNode

# ---------------------------------------------------------------------------
# In-memory ChallengeRegistry for testing (no DATABASE_URL required)
# ---------------------------------------------------------------------------


class _InMemoryRegistry:
    """Minimal in-memory ChallengeRegistry shim for unit tests."""

    def __init__(self) -> None:
        self._challenges: dict[str, Challenge] = {}

    def add(
        self,
        target_subsystem: str,
        severity: ChallengeSeverity,
        description: str,
        evidence: str = "",
        challenge_id: str | None = None,
    ) -> str:
        cid = challenge_id or str(uuid.uuid4())
        self._challenges[cid] = Challenge(
            challenge_id=cid,
            target_subsystem=target_subsystem,
            severity=severity,
            description=description,
            evidence=evidence,
            status=ChallengeStatus.OPEN,
            resolution_notes="",
            created_at=time.time(),
            updated_at=time.time(),
        )
        return cid

    def get(self, challenge_id: str) -> Challenge | None:
        return self._challenges.get(challenge_id)

    def open_challenges(self) -> list[Challenge]:
        return [c for c in self._challenges.values() if c.status == ChallengeStatus.OPEN]

    def all_challenges(self, subsystem: str = "") -> list[Challenge]:
        if subsystem:
            return [
                c
                for c in self._challenges.values()
                if subsystem.lower() in c.target_subsystem.lower()
            ]
        return list(self._challenges.values())

    def has_blocking_challenges(self) -> bool:
        return any(
            c.severity == ChallengeSeverity.CRITICAL and c.status == ChallengeStatus.OPEN
            for c in self._challenges.values()
        )

    def resolution_rate(self) -> float:
        total = len(self._challenges)
        if total == 0:
            return 1.0
        resolved = sum(
            1 for c in self._challenges.values() if c.status == ChallengeStatus.RESOLVED
        )
        return resolved / total

    def update_status(
        self, challenge_id: str, status: ChallengeStatus, resolution_notes: str = ""
    ) -> None:
        c = self._challenges.get(challenge_id)
        if c:
            self._challenges[challenge_id] = Challenge(
                challenge_id=c.challenge_id,
                target_subsystem=c.target_subsystem,
                severity=c.severity,
                description=c.description,
                evidence=c.evidence,
                status=status,
                resolution_notes=resolution_notes,
                created_at=c.created_at,
                updated_at=time.time(),
            )

    def seed_initial_challenges(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_da() -> DevilsAdvocateNode:
    reg: Any = _InMemoryRegistry()
    return DevilsAdvocateNode(registry=reg)


# ---------------------------------------------------------------------------
# Concentration risk
# ---------------------------------------------------------------------------


class TestConcentrationRisk:
    def test_fires_when_single_position_exceeds_30_pct(self):
        da = make_da()
        proposals = [
            {"symbol": "BTCUSDT", "weight": 0.80},  # 80% → should fire
            {"symbol": "ETHUSDT", "weight": 0.20},
        ]
        results = da.run_structural_checks(proposals=proposals, signals={})
        conc = next(r for r in results if r.check_name == "concentration_risk")
        assert conc.fired is True
        assert conc.value > 0.30
        assert conc.severity == ChallengeSeverity.HIGH.value

    def test_does_not_fire_when_positions_balanced(self):
        da = make_da()
        proposals = [
            {"symbol": "BTCUSDT", "weight": 0.25},
            {"symbol": "ETHUSDT", "weight": 0.25},
            {"symbol": "SOLUSDT", "weight": 0.25},
            {"symbol": "ADAUSDT", "weight": 0.25},
        ]
        results = da.run_structural_checks(proposals=proposals, signals={})
        conc = next(r for r in results if r.check_name == "concentration_risk")
        assert conc.fired is False

    def test_threshold_boundary_exactly_30_pct_does_not_fire(self):
        da = make_da()
        # Max fraction = exactly 0.30/1.0 = 30% → should NOT fire (check is strictly >)
        proposals = [
            {"symbol": "A", "weight": 0.30},
            {"symbol": "B", "weight": 0.30},
            {"symbol": "C", "weight": 0.20},
            {"symbol": "D", "weight": 0.20},
        ]
        results = da.run_structural_checks(proposals=proposals, signals={})
        conc = next(r for r in results if r.check_name == "concentration_risk")
        assert conc.fired is False

    def test_no_proposals_returns_not_fired(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={})
        conc = next(r for r in results if r.check_name == "concentration_risk")
        assert conc.fired is False

    def test_fired_challenge_registered_in_registry(self):
        da = make_da()
        proposals = [{"symbol": "BTCUSDT", "weight": 1.0}]
        before = len(da._registry.all_challenges())
        da.run_structural_checks(proposals=proposals, signals={})
        after = len(da._registry.all_challenges())
        assert after > before


# ---------------------------------------------------------------------------
# Data staleness
# ---------------------------------------------------------------------------


class TestDataStaleness:
    def test_fires_when_data_older_than_60_minutes(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={}, data_freshness_minutes=90.0)
        stale = next(r for r in results if r.check_name == "data_staleness")
        assert stale.fired is True
        assert stale.severity == ChallengeSeverity.CRITICAL.value

    def test_does_not_fire_when_data_is_fresh(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={}, data_freshness_minutes=5.0)
        stale = next(r for r in results if r.check_name == "data_staleness")
        assert stale.fired is False

    def test_boundary_exactly_60_minutes_does_not_fire(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={}, data_freshness_minutes=60.0)
        stale = next(r for r in results if r.check_name == "data_staleness")
        assert stale.fired is False

    def test_default_freshness_0_does_not_fire(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={})
        stale = next(r for r in results if r.check_name == "data_staleness")
        assert stale.fired is False


# ---------------------------------------------------------------------------
# Signal correlation
# ---------------------------------------------------------------------------


class TestSignalCorrelation:
    def test_fires_when_top_signals_are_co_directional_and_close(self):
        da = make_da()
        # Both strongly positive and nearly identical → should fire
        signals = {"BTCUSDT": 0.9, "ETHUSDT": 0.91, "SOLUSDT": -0.5}
        results = da.run_structural_checks(proposals=[], signals=signals)
        corr = next(r for r in results if r.check_name == "signal_correlation")
        assert corr.fired is True
        assert corr.value > 0.7

    def test_does_not_fire_when_signals_diverge(self):
        da = make_da()
        signals = {"BTCUSDT": 0.9, "ETHUSDT": -0.8}
        results = da.run_structural_checks(proposals=[], signals=signals)
        corr = next(r for r in results if r.check_name == "signal_correlation")
        assert corr.fired is False

    def test_does_not_fire_when_opposite_directions(self):
        da = make_da()
        # Same magnitude but opposite sign → different directions → no fire
        signals = {"BTCUSDT": 0.85, "ETHUSDT": -0.85}
        results = da.run_structural_checks(proposals=[], signals=signals)
        corr = next(r for r in results if r.check_name == "signal_correlation")
        assert corr.fired is False

    def test_fewer_than_2_signals_not_fired(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={"BTCUSDT": 0.9})
        corr = next(r for r in results if r.check_name == "signal_correlation")
        assert corr.fired is False

    def test_empty_signals_not_fired(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={})
        corr = next(r for r in results if r.check_name == "signal_correlation")
        assert corr.fired is False


# ---------------------------------------------------------------------------
# All checks pass on clean data
# ---------------------------------------------------------------------------


class TestAllClean:
    def test_no_checks_fire_on_clean_cycle(self):
        da = make_da()
        proposals = [
            {"symbol": "BTCUSDT", "weight": 0.25},
            {"symbol": "ETHUSDT", "weight": 0.25},
            {"symbol": "SOLUSDT", "weight": 0.25},
            {"symbol": "ADAUSDT", "weight": 0.25},
        ]
        signals = {"BTCUSDT": 0.5, "ETHUSDT": -0.3, "SOLUSDT": 0.1, "ADAUSDT": -0.6}
        results = da.run_structural_checks(
            proposals=proposals, signals=signals, data_freshness_minutes=2.0
        )
        assert all(not r.fired for r in results)

    def test_always_returns_3_results(self):
        da = make_da()
        results = da.run_structural_checks(proposals=[], signals={})
        assert len(results) == 3
        check_names = {r.check_name for r in results}
        assert check_names == {"concentration_risk", "data_staleness", "signal_correlation"}


# ---------------------------------------------------------------------------
# Orchestrator strategy_params enrichment
# ---------------------------------------------------------------------------


class TestStrategyParamsEnrichment:
    """
    Verify that _step_adversarial passes real position data in strategy_params
    to AdversarialPressureV2.run_v2.
    """

    def test_positions_in_strategy_params(self):
        """AdversarialPressureV2.run_v2 receives positions dict from proposals."""
        from unittest.mock import MagicMock

        from omega.core.orchestrator_v2 import OmegaOrchestrator

        orch = OmegaOrchestrator()

        # Mock _adversarial.run_v2 to capture strategy_params
        captured: dict[str, Any] = {}
        mock_report = MagicMock()
        mock_report.base_report.ring1_result = None
        mock_report.attribution = None

        def fake_run_v2(**kwargs):
            captured.update(kwargs)
            return mock_report

        orch._adversarial.run_v2 = fake_run_v2

        from omega.core.cycle import CycleContext, CycleResult

        ctx = CycleContext.new(
            cycle_number=1,
            regime="normal",
            active_node_ids=(),
            autonomy_levels={},
        )
        result = CycleResult(context=ctx)
        proposals = [
            {"symbol": "BTCUSDT", "weight": 0.6, "node_id": "n1"},
            {"symbol": "ETHUSDT", "weight": 0.4, "node_id": "n1"},
        ]
        import logging

        log = logging.LoggerAdapter(logging.getLogger("test"), {})
        signal_data: dict = {}

        orch._step_adversarial(ctx, result, proposals, signal_data, log)

        assert "strategy_params" in captured
        sp = captured["strategy_params"]
        assert "positions" in sp
        assert sp["positions"]["BTCUSDT"] == pytest.approx(0.6)
        assert sp["positions"]["ETHUSDT"] == pytest.approx(0.4)
        assert "total_weight" in sp
        assert sp["total_weight"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Orchestrator DA structural check integration
# ---------------------------------------------------------------------------


class TestOrchestratorDAIntegration:
    def test_structural_flags_added_when_da_node_registered(self):
        """When a DA node is active, stale data triggers a critical adversarial flag."""
        from unittest.mock import MagicMock

        from omega.core.cycle import CycleContext, CycleResult
        from omega.core.node import NodeState
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        orch = OmegaOrchestrator()

        # Register a DA node
        da = make_da()
        orch._registry.register(da)
        da_state = da.get_state()
        orch._active_node_ids.add(da_state.node_id)
        orch._node_health[da_state.node_id] = MagicMock()

        ctx = CycleContext.new(
            cycle_number=0,
            regime="normal",
            active_node_ids=(da_state.node_id,),
            autonomy_levels={},
        )
        result = CycleResult(context=ctx)
        import logging

        log = logging.LoggerAdapter(logging.getLogger("test"), {})

        # Provide a node with stale data metric
        from omega.core.node import Node, NodeOutput

        class StaleDataNode(Node):
            def get_state(self):
                return NodeState(
                    node_id="stale-node",
                    name="StaleDataNode",
                    version="1.0",
                    health=0.9,
                    capabilities=[],
                    metrics={"data_freshness_minutes": 120.0},
                )

            def get_capabilities(self):
                return []

            def describe(self):
                return "stale"

            def execute(self, inp):
                return NodeOutput(request_id=inp.request_id, success=True)

            def evaluate(self):
                return {}

            def improve(self, feedback):
                return False

        stale_node = StaleDataNode()
        orch._registry.register(stale_node)
        stale_state = stale_node.get_state()
        orch._active_node_ids.add(stale_state.node_id)
        orch._node_health[stale_state.node_id] = MagicMock()

        orch._run_da_structural_checks(
            ctx=ctx,
            result=result,
            proposals=[],
            current_signals={},
            log=log,
        )

        flag_reasons = [f["reason"] for f in result.adversarial_flags]
        assert "data_staleness" in flag_reasons

    def test_no_flags_without_da_node(self):
        """No structural flags when no DA node is registered."""
        from omega.core.cycle import CycleContext, CycleResult
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        orch = OmegaOrchestrator()
        ctx = CycleContext.new(
            cycle_number=0,
            regime="normal",
            active_node_ids=(),
            autonomy_levels={},
        )
        result = CycleResult(context=ctx)
        import logging

        log = logging.LoggerAdapter(logging.getLogger("test"), {})
        orch._run_da_structural_checks(
            ctx=ctx, result=result, proposals=[], current_signals={}, log=log
        )

        assert result.adversarial_flags == []
