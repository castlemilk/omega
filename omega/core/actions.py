"""omega.core.actions — Centralized action and step-type enumerations.

This is the single source of truth for all string-based dispatch in the
Omega pipeline.  Import from here instead of scattering raw string literals
across node files.

Python ↔ Go contract
--------------------
  StepType values must match the node_type strings sent by Go's orchestrator
  in ExecuteStepRequest.node_type.  The Go side sources these from the YAML
  pipeline config (e.g. victoria.yaml / polymarket.yaml).

  NodeAction values must match the action strings accepted by each Python node's
  execute(inp) dispatcher and validated by its get_capabilities() list.

  STEP_TO_ACTION is the canonical bridge: given a StepType arriving from Go,
  it tells the Python server which NodeAction to invoke on the node.
"""

from __future__ import annotations

from enum import StrEnum


class NodeAction(StrEnum):
    """All valid node actions.

    These are the strings nodes accept in NodeInput.action.
    Values must match what each node's get_capabilities() returns and
    what its execute() dispatcher branches on.
    """

    # Victoria pipeline
    POLL = "poll"
    FETCH_MARKET_DATA = "fetch_market_data"
    COMPUTE_SIGNALS = "compute_signals"
    CONSTRUCT_PORTFOLIO = "construct_portfolio"
    CHECK_RISK_LIMITS = "check_risk_limits"
    BACKTEST_STRATEGY = "backtest_strategy"
    RANK_SIGNALS = "rank_signals"
    DEBATE_GATE = "debategate"
    WALK_FORWARD = "walkforward"
    MONITOR_LIQUIDATIONS = "monitor_liquidations"
    ARCHITECTURAL_REVIEW = "architectural_review"
    RISK_DEBATE = "risk_debate"
    IMPROVEMENT = "improvement"

    # Go step-type aliases registered as capabilities on VictoriaNode
    DATA_INGESTION = "data_ingestion"
    SIGNAL_RESEARCH = "signal_research"
    STRATEGY = "strategy"
    RISK_MANAGEMENT = "risk_management"
    VERIFICATION = "verification"
    MEMORY = "memory"
    IMPROVEMENT_ENGINE = "improvementengine"
    ADVERSARIAL = "adversarial"

    # Polymarket pipeline
    WEATHER_ENSEMBLE = "weather_ensemble"
    PROBABILITY = "probability"
    MARKET_PRICING = "market_pricing"
    # Capability alias: uppercases to "POLYMARKET_PRICING" for Go→Python handler routing.
    # resolve_action maps StepType.POLYMARKET_PRICING → NodeAction.MARKET_PRICING for execution.
    POLYMARKET_PRICING = "polymarket_pricing"
    EDGE_DETECTION = "edge_detection"
    DETECT = "detect"


class StepType(StrEnum):
    """Go-side step node_type values.

    These are the exact strings Go sends in ExecuteStepRequest.node_type.
    They come from the pipeline YAML configs (victoria.yaml, polymarket.yaml).
    """

    # Victoria pipeline step types
    DATA_INGESTION = "DATA_INGESTION"
    SIGNAL_RESEARCH = "SIGNAL_RESEARCH"
    STRATEGY = "STRATEGY"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    VERIFICATION = "VERIFICATION"
    MEMORY = "MEMORY"
    IMPROVEMENT = "IMPROVEMENT"
    ADVERSARIAL = "ADVERSARIAL"
    DEBATE_GATE = "DEBATE_GATE"

    # Polymarket pipeline step types
    WEATHER_ENSEMBLE = "WEATHER_ENSEMBLE"
    POLYMARKET_PRICING = "POLYMARKET_PRICING"
    EDGE_DETECTION = "EDGE_DETECTION"

    # Extended / future step types
    LIQUIDATION_CASCADE = "LIQUIDATION_CASCADE"
    ONCHAIN_DATA = "ONCHAIN_DATA"


# Capability alias groups — each group routes to the same action.
# Used by orchestrator_v2 to check whether a node can handle a step.
POLL_CAPABILITIES: frozenset[str] = frozenset(
    [NodeAction.POLL, NodeAction.FETCH_MARKET_DATA, NodeAction.DATA_INGESTION]
)
SIGNAL_CAPABILITIES: frozenset[str] = frozenset(
    [NodeAction.COMPUTE_SIGNALS, NodeAction.SIGNAL_RESEARCH]
)
STRATEGY_CAPABILITIES: frozenset[str] = frozenset(
    [NodeAction.CONSTRUCT_PORTFOLIO, NodeAction.STRATEGY]
)


# Canonical mapping: StepType (from Go) → NodeAction (to Python node).
STEP_TO_ACTION: dict[StepType, NodeAction] = {
    StepType.DATA_INGESTION: NodeAction.FETCH_MARKET_DATA,
    StepType.SIGNAL_RESEARCH: NodeAction.COMPUTE_SIGNALS,
    StepType.STRATEGY: NodeAction.CONSTRUCT_PORTFOLIO,
    StepType.RISK_MANAGEMENT: NodeAction.CHECK_RISK_LIMITS,
    StepType.VERIFICATION: NodeAction.VERIFICATION,
    StepType.MEMORY: NodeAction.MEMORY,
    StepType.IMPROVEMENT: NodeAction.IMPROVEMENT,
    StepType.ADVERSARIAL: NodeAction.ADVERSARIAL,
    StepType.DEBATE_GATE: NodeAction.DEBATE_GATE,
    StepType.WEATHER_ENSEMBLE: NodeAction.WEATHER_ENSEMBLE,
    StepType.POLYMARKET_PRICING: NodeAction.MARKET_PRICING,
    StepType.EDGE_DETECTION: NodeAction.EDGE_DETECTION,
    StepType.LIQUIDATION_CASCADE: NodeAction.MONITOR_LIQUIDATIONS,
    StepType.ONCHAIN_DATA: NodeAction.FETCH_MARKET_DATA,
}


def resolve_action(node_type: str) -> NodeAction | None:
    """Resolve a Go step node_type string to a Python NodeAction.

    Returns None if the node_type is unknown (caller should return an error).

    Usage in pipeline_server.py::

        action = resolve_action(req.node_type)
        if action is None:
            return error_response(f"unknown node_type={req.node_type!r}")
        inp = NodeInput(action=action.value, ...)
    """
    try:
        step = StepType(node_type)
    except ValueError:
        return None
    return STEP_TO_ACTION.get(step)
