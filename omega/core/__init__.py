"""omega.core — contracts, orchestration, evaluation, memory, feedback."""
from omega.core.brain import (
    BrainConfig, BrainRequest, BrainResponse, BrainAdapter,
    NoBrain, AnthropicBrain, OpenAIBrain, OllamaBrain,
    DeepSeekBrain, GoogleBrain, BRAIN_REGISTRY, create_brain,
)
from omega.core.node import Node, NodeInput, NodeOutput, NodeState, RoleNode
from omega.core.registry import NodeRegistry
from omega.core.evaluator import Evaluator, GoalSpec
from omega.core.orchestrator import Orchestrator
from omega.core.memory import MemoryKernel, NodeMemory
from omega.core.memory_v2 import (
    MemoryKernelV2, BOCPDRegimeDetector, RegimeTaggedSemanticStore,
    EWCProtection, DempsterShaferFusion, ContradictionResolver,
    RegimeState, Resolution,
)
from omega.core.feedback import FeedbackEngine
from omega.core.state_store import StateStore
from omega.core.tracing import Tracer, TraceContext, SpanData, create_tracer
from omega.core.metrics import MetricsCollector
from omega.core.analyzer import SystemAnalyzer, Recommendation
from omega.core.alignment import (
    AlignmentLayer, AlignmentDecision,
    ParetoEvaluator, OutcomeBasedScorer, SafetyEnvelope,
)
from omega.core.adversarial import (
    AdversarialPressure, AdversarialReport,
    EnsembleDisagreementDetector, ScenarioGenerator, EvolutionaryTournament,
    DisagreementResult, Scenario, TournamentResult,
)
from omega.core.goals import (
    GoalArchitecture, GoalDecision,
    ConstitutionalConstraints, BalancedScorecard,
    NashWelfareAggregator, MPCReferenceTracker, HTNDecomposer,
    ConstraintViolation, Task,
)

__all__ = [
    # Brain adapter layer
    "BrainConfig", "BrainRequest", "BrainResponse", "BrainAdapter",
    "NoBrain", "AnthropicBrain", "OpenAIBrain", "OllamaBrain",
    "DeepSeekBrain", "GoogleBrain", "BRAIN_REGISTRY", "create_brain",
    # Node contracts
    "Node", "NodeInput", "NodeOutput", "NodeState", "RoleNode",
    "NodeRegistry",
    "Evaluator", "GoalSpec",
    "Orchestrator",
    "MemoryKernel", "NodeMemory",
    "MemoryKernelV2", "BOCPDRegimeDetector", "RegimeTaggedSemanticStore",
    "EWCProtection", "DempsterShaferFusion", "ContradictionResolver",
    "RegimeState", "Resolution",
    "FeedbackEngine",
    "StateStore",
    "Tracer", "TraceContext", "SpanData", "create_tracer",
    "MetricsCollector",
    "SystemAnalyzer", "Recommendation",
    # Alignment layer
    "AlignmentLayer", "AlignmentDecision",
    "ParetoEvaluator", "OutcomeBasedScorer", "SafetyEnvelope",
    # Adversarial pressure
    "AdversarialPressure", "AdversarialReport",
    "EnsembleDisagreementDetector", "ScenarioGenerator", "EvolutionaryTournament",
    "DisagreementResult", "Scenario", "TournamentResult",
    # Goal architecture
    "GoalArchitecture", "GoalDecision",
    "ConstitutionalConstraints", "BalancedScorecard",
    "NashWelfareAggregator", "MPCReferenceTracker", "HTNDecomposer",
    "ConstraintViolation", "Task",
]
