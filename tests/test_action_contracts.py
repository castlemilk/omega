"""tests/test_action_contracts.py — Type-safety contract tests for action dispatch.

Verifies that:
  1. Every StepType has a corresponding entry in STEP_TO_ACTION.
  2. Every NodeAction value is a non-empty string (no accidental empty enum members).
  3. Every NodeAction value is unique (no two actions share the same string).
  4. Every StepType value is unique.
  5. The canonical node capability lists advertise at least one NodeAction.
  6. The STEP_TO_ACTION targets are valid NodeAction members.
"""

from __future__ import annotations

import pytest

from omega.core.actions import STEP_TO_ACTION, NodeAction, StepType, resolve_action

# ---------------------------------------------------------------------------
# 1. Every StepType must have a STEP_TO_ACTION entry.
# ---------------------------------------------------------------------------


def test_all_step_types_have_action_mapping() -> None:
    missing = [st for st in StepType if st not in STEP_TO_ACTION]
    assert not missing, (
        f"StepType members without a STEP_TO_ACTION entry: {[m.value for m in missing]}\n"
        "Add each to STEP_TO_ACTION in omega/core/actions.py."
    )


# ---------------------------------------------------------------------------
# 2 & 3. NodeAction values are non-empty and unique.
# ---------------------------------------------------------------------------


def test_node_action_values_are_non_empty() -> None:
    empty = [a for a in NodeAction if not a.value]
    assert not empty, f"NodeAction members with empty values: {empty}"


def test_node_action_values_are_unique() -> None:
    values = [a.value for a in NodeAction]
    duplicates = {v for v in values if values.count(v) > 1}
    assert not duplicates, f"Duplicate NodeAction values: {duplicates}"


# ---------------------------------------------------------------------------
# 4. StepType values are unique.
# ---------------------------------------------------------------------------


def test_step_type_values_are_unique() -> None:
    values = [st.value for st in StepType]
    duplicates = {v for v in values if values.count(v) > 1}
    assert not duplicates, f"Duplicate StepType values: {duplicates}"


# ---------------------------------------------------------------------------
# 5. STEP_TO_ACTION targets are valid NodeAction members (no stale entries).
# ---------------------------------------------------------------------------


def test_step_to_action_targets_are_valid_node_actions() -> None:
    invalid = [
        (st.value, action)
        for st, action in STEP_TO_ACTION.items()
        if not isinstance(action, NodeAction)
    ]
    assert not invalid, f"STEP_TO_ACTION entries with non-NodeAction targets: {invalid}"


# ---------------------------------------------------------------------------
# 6. resolve_action returns the correct NodeAction for known StepTypes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step_type,expected_action",
    [
        ("DATA_INGESTION", NodeAction.FETCH_MARKET_DATA),
        ("SIGNAL_RESEARCH", NodeAction.COMPUTE_SIGNALS),
        ("STRATEGY", NodeAction.CONSTRUCT_PORTFOLIO),
        ("RISK_MANAGEMENT", NodeAction.CHECK_RISK_LIMITS),
        ("WEATHER_ENSEMBLE", NodeAction.WEATHER_ENSEMBLE),
        ("POLYMARKET_PRICING", NodeAction.MARKET_PRICING),
        ("EDGE_DETECTION", NodeAction.EDGE_DETECTION),
        ("IMPROVEMENT", NodeAction.IMPROVEMENT),
        ("ADVERSARIAL", NodeAction.ADVERSARIAL),
        ("MEMORY", NodeAction.MEMORY),
        ("VERIFICATION", NodeAction.VERIFICATION),
        ("DEBATE_GATE", NodeAction.DEBATE_GATE),
        ("LIQUIDATION_CASCADE", NodeAction.MONITOR_LIQUIDATIONS),
    ],
)
def test_resolve_action_known_types(step_type: str, expected_action: NodeAction) -> None:
    result = resolve_action(step_type)
    assert result == expected_action, (
        f"resolve_action({step_type!r}) returned {result!r}, expected {expected_action!r}"
    )


def test_resolve_action_unknown_type_returns_none() -> None:
    assert resolve_action("TOTALLY_UNKNOWN_TYPE") is None
    assert resolve_action("") is None
    assert resolve_action("data_ingestion") is None  # case-sensitive


# ---------------------------------------------------------------------------
# 7. Node capabilities include the primary dispatch action for each node type.
# ---------------------------------------------------------------------------


def test_victoria_node_capabilities_use_enums() -> None:
    """VictoriaNode capabilities must include all primary dispatched actions."""
    from omega.nodes.victoria.victoria_node import VictoriaNode

    node = VictoriaNode()
    caps = node.get_capabilities()

    required = [
        NodeAction.POLL.value,
        NodeAction.FETCH_MARKET_DATA.value,
        NodeAction.COMPUTE_SIGNALS.value,
        NodeAction.CONSTRUCT_PORTFOLIO.value,
    ]
    missing = [r for r in required if r not in caps]
    assert not missing, f"VictoriaNode.get_capabilities() missing required actions: {missing}"


def test_data_ingestion_node_capabilities() -> None:
    from omega.nodes.victoria.data_ingestion import DataIngestionNode

    caps = DataIngestionNode().get_capabilities()
    assert NodeAction.FETCH_MARKET_DATA.value in caps


def test_signal_generation_node_capabilities() -> None:
    from omega.nodes.victoria.signal_generation import SignalGenerationNode

    caps = SignalGenerationNode().get_capabilities()
    assert NodeAction.COMPUTE_SIGNALS.value in caps


def test_strategy_node_capabilities() -> None:
    from omega.nodes.victoria.strategy import StrategyNode

    caps = StrategyNode().get_capabilities()
    assert NodeAction.CONSTRUCT_PORTFOLIO.value in caps
    assert NodeAction.BACKTEST_STRATEGY.value in caps
    assert NodeAction.RANK_SIGNALS.value in caps


def test_risk_management_node_capabilities() -> None:
    from omega.nodes.victoria.risk_management import RiskManagementNode

    caps = RiskManagementNode().get_capabilities()
    assert NodeAction.CHECK_RISK_LIMITS.value in caps


def test_weather_ensemble_node_capabilities() -> None:
    from omega.nodes.polymarket.weather_ensemble import WeatherEnsembleNode

    caps = WeatherEnsembleNode().get_capabilities()
    assert NodeAction.PROBABILITY.value in caps
    assert NodeAction.WEATHER_ENSEMBLE.value in caps


def test_edge_detection_node_capabilities() -> None:
    from omega.nodes.polymarket.edge_detection import EdgeDetectionNode

    caps = EdgeDetectionNode().get_capabilities()
    assert NodeAction.EDGE_DETECTION.value in caps


def test_polymarket_pricing_node_capabilities() -> None:
    from omega.nodes.polymarket.pricing import PolymarketPricingNode

    caps = PolymarketPricingNode().get_capabilities()
    assert NodeAction.MARKET_PRICING.value in caps


# ---------------------------------------------------------------------------
# 8. Smoke-test: all StepType values parse cleanly via resolve_action.
# ---------------------------------------------------------------------------


def test_all_step_types_resolve_cleanly() -> None:
    for st in StepType:
        action = resolve_action(st.value)
        assert action is not None, (
            f"resolve_action({st.value!r}) returned None — add to STEP_TO_ACTION."
        )
        assert isinstance(action, NodeAction)
