"""omega.core — contracts, orchestration, evaluation, memory, feedback."""

from __future__ import annotations

from omega.core.adversarial import (
    AdversarialPressure,
    AdversarialReport,
    DisagreementResult,
    EnsembleDisagreementDetector,
    EvolutionaryTournament,
    Scenario,
    ScenarioGenerator,
    TournamentResult,
)
from omega.core.alignment import (
    AlignmentDecision,
    AlignmentLayer,
    OutcomeBasedScorer,
    ParetoEvaluator,
    SafetyEnvelope,
)
from omega.core.analyzer import Recommendation, SystemAnalyzer
from omega.core.brain import (
    BRAIN_REGISTRY,
    AnthropicBrain,
    BrainAdapter,
    BrainConfig,
    BrainRequest,
    BrainResponse,
    DeepSeekBrain,
    GoogleBrain,
    NoBrain,
    OllamaBrain,
    OpenAIBrain,
    create_brain,
)
from omega.core.evaluator import Evaluator, GoalSpec
from omega.core.feedback import FeedbackEngine
from omega.core.goals import (
    BalancedScorecard,
    ConstitutionalConstraints,
    ConstraintViolation,
    GoalArchitecture,
    GoalDecision,
    HTNDecomposer,
    MPCReferenceTracker,
    NashWelfareAggregator,
    Task,
)
from omega.core.memory import MemoryKernel, NodeMemory
from omega.core.memory_v2 import (
    BOCPDRegimeDetector,
    ContradictionResolver,
    DempsterShaferFusion,
    EWCProtection,
    MemoryKernelV2,
    RegimeState,
    RegimeTaggedSemanticStore,
    Resolution,
)
from omega.core.metrics import MetricsCollector
from omega.core.node import Node, NodeInput, NodeOutput, NodeState, RoleNode
from omega.core.orchestrator import Orchestrator
from omega.core.registry import NodeRegistry
from omega.core.state_store import StateStore
from omega.core.tracing import SpanData, TraceContext, Tracer, create_tracer

__all__ = [
    "BRAIN_REGISTRY",
    "AdversarialPressure",
    "AdversarialReport",
    "AlignmentDecision",
    "AlignmentLayer",
    "AnthropicBrain",
    "BOCPDRegimeDetector",
    "BalancedScorecard",
    "BrainAdapter",
    "BrainConfig",
    "BrainRequest",
    "BrainResponse",
    "ConstitutionalConstraints",
    "ConstraintViolation",
    "ContradictionResolver",
    "DeepSeekBrain",
    "DempsterShaferFusion",
    "DisagreementResult",
    "EWCProtection",
    "EnsembleDisagreementDetector",
    "Evaluator",
    "EvolutionaryTournament",
    "FeedbackEngine",
    "GoalArchitecture",
    "GoalDecision",
    "GoalSpec",
    "GoogleBrain",
    "HTNDecomposer",
    "MPCReferenceTracker",
    "MemoryKernel",
    "MemoryKernelV2",
    "MetricsCollector",
    "NashWelfareAggregator",
    "NoBrain",
    "Node",
    "NodeInput",
    "NodeMemory",
    "NodeOutput",
    "NodeRegistry",
    "NodeState",
    "OllamaBrain",
    "OpenAIBrain",
    "Orchestrator",
    "OutcomeBasedScorer",
    "ParetoEvaluator",
    "Recommendation",
    "RegimeState",
    "RegimeTaggedSemanticStore",
    "Resolution",
    "RoleNode",
    "SafetyEnvelope",
    "Scenario",
    "ScenarioGenerator",
    "SpanData",
    "StateStore",
    "SystemAnalyzer",
    "Task",
    "TournamentResult",
    "TraceContext",
    "Tracer",
    "create_brain",
    "create_tracer",
]
