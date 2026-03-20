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
from omega.core.feedback import FeedbackEngine
from omega.core.state_store import StateStore
from omega.core.tracing import Tracer, TraceContext, SpanData, create_tracer
from omega.core.metrics import MetricsCollector
from omega.core.analyzer import SystemAnalyzer, Recommendation

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
    "FeedbackEngine",
    "StateStore",
    "Tracer", "TraceContext", "SpanData", "create_tracer",
    "MetricsCollector",
    "SystemAnalyzer", "Recommendation",
]
