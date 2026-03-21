"""
omega.core.domain
~~~~~~~~~~~~~~~~~
Domain abstraction layer for Omega framework.

Defines the building blocks that let any domain (trading, code review,
data pipeline, etc.) plug into Omega by implementing the DomainConfig
protocol.  Framework code imports only from this module — never from
domain-specific packages.

Key types
---------
PerformanceMetric
    Describes one dimension of node performance used for autonomy decisions.

DomainConfig
    Protocol that domain authors implement to configure Omega for their
    domain.  A single instance is registered with the orchestrator at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# PerformanceMetric
# ---------------------------------------------------------------------------


@dataclass
class PerformanceMetric:
    """
    Describes one dimension of node performance for graduated autonomy.

    direction
    ---------
    "higher_is_better"
        Tracked as an exponential moving average (EMA) over cycles.
        Promote when EMA >= threshold_promote.
        Demote  when EMA <  threshold_demote.

    "lower_is_better"
        Tracked as a running maximum (worst value seen) over cycles.
        Promote when max_observed <= threshold_promote.
        Demote  when max_observed >  threshold_demote.

    Examples
    --------
    Trading domain::

        PerformanceMetric("sharpe",       "higher_is_better", 0.5, 0.0)
        PerformanceMetric("max_drawdown", "lower_is_better",  0.15, 0.20)

    Code-review domain (hypothetical)::

        PerformanceMetric("f1_score",    "higher_is_better", 0.80, 0.60)
        PerformanceMetric("latency_ms",  "lower_is_better",  500,  2000)
    """

    name: str
    direction: Literal["higher_is_better", "lower_is_better"]
    threshold_promote: float  # value needed for promotion eligibility
    threshold_demote: float  # value that triggers demotion


# ---------------------------------------------------------------------------
# DomainConfig protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DomainConfig(Protocol):
    """
    Protocol for domain-specific Omega configuration.

    Implement this and register it with the orchestrator at startup::

        orchestrator.register_domain(MyDomainConfig())

    The orchestrator propagates each attribute to the appropriate subsystem:

    metrics        → GraduatedAutonomyController (AutonomyThresholds)
    debate_gate    → AdversarialPressureV2 (optional Ring-1 debate layer)
    regime_actions → RegimeSignalModifier (signal multiplier table)
    evaluator      → ImprovementEngine (TPE self-improvement)

    Attributes
    ----------
    name : str
        Short human-readable identifier, e.g. "trading", "code_review".
    metrics : list[PerformanceMetric]
        One or more PerformanceMetric instances.  ALL must be satisfied for
        autonomy promotion; ANY breach triggers demotion.
    debate_gate : optional
        A DebateGate-compatible object or None.  None means no adversarial
        debate — the framework runs Ring 1 threshold checks only.
    regime_actions : dict[str, Any]
        Passed to RegimeSignalModifier as the multiplier table.
        Keys are regime labels; values are {signal_name: multiplier} dicts.
        Pass {} for no regime-based signal adjustment.
    evaluator : ImprovementEvaluator
        Evaluates candidate parameter sets for the TPE improvement loop.
        Must not be None — every domain must provide its own evaluator.
    """

    name: str
    metrics: list[PerformanceMetric]
    debate_gate: Any | None
    regime_actions: dict[str, Any]
    evaluator: Any  # ImprovementEvaluator
