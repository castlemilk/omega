"""
omega.core.node
~~~~~~~~~~~~~~~
The fundamental contract for all Omega nodes.

Every node in the system must implement this interface. The contract is
intentionally minimal so that LLMs or humans can create new nodes by
reading only this file.

Design intent
--------------
- NodeState  : what the node knows about *itself* right now
- NodeInput  : standardised envelope arriving *into* a node
- NodeOutput : standardised envelope coming *out* of a node
- Node       : abstract base class — implement this to join the network
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Optional

if TYPE_CHECKING:
    from omega.core.brain import BrainAdapter, BrainConfig, BrainResponse
    from omega.core.state_tensor import StateTensor


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass
class NodeState:
    """The state tensor of a node — what it knows about itself."""

    node_id: str
    name: str
    version: str
    health: float  # 0.0 (broken) → 1.0 (perfect)
    capabilities: list[str]  # verbs the node can execute
    metrics: dict[str, float]  # performance metrics (latency, accuracy, …)
    last_updated: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_healthy(self, threshold: float = 0.5) -> bool:
        return self.health >= threshold


@dataclass
class NodeInput:
    """Standardised input envelope delivered to a node."""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ""  # verb the node should execute
    parameters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)  # orchestrator metadata


@dataclass
class NodeOutput:
    """Standardised output envelope produced by a node."""

    request_id: str = ""
    success: bool = True
    result: Any = None
    metrics: dict[str, float] = field(default_factory=dict)  # this execution's perf
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)  # node-initiated hints


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class Node(ABC):
    """
    Base class for all Omega nodes.

    To add a new node to the network:
    1. Subclass Node.
    2. Implement every abstract method.
    3. Register an instance with the Orchestrator.

    That's it.

    Brain adapter
    -------------
    Every node optionally carries a BrainAdapter. Pass a BrainConfig at
    construction time or call set_brain_config() at runtime. When no brain
    is configured (the default), consult_brain() returns action="pass" and
    the node falls back to its own rule-based logic — preserving all existing
    behaviour.

        node = MyNode(brain_config=BrainConfig(provider="anthropic", model="claude-sonnet-4-6"))
        node.set_brain_config(BrainConfig(provider="ollama", model="llama3"))

    Skills
    ------
    Subclasses declare relevant skill tags via the ``skill_tags`` class attribute.
    When ``consult_brain()`` is called, matching SKILL.md content is loaded from
    ``omega/skills/`` and prepended to the brain's ``domain_context``::

        class MyGoNode(Node):
            skill_tags = ["go", "protobuf"]
    """

    # Subclasses override to declare which skill tags apply to this node.
    # These tags are resolved by consult_brain() against omega/skills/ and
    # their content is injected into BrainRequest.domain_context.
    skill_tags: ClassVar[list[str]] = []

    def __init__(self, brain_config: Optional["BrainConfig"] = None) -> None:
        from omega.core.brain import BrainConfig as BrainConfigCls
        from omega.core.brain import create_brain

        self.brain: BrainAdapter = create_brain(brain_config or BrainConfigCls())

    def __getattr__(self, name: str) -> Any:
        # Lazily initialise self.brain for subclasses that don't call super().__init__()
        if name == "brain":
            from omega.core.brain import NoBrain

            object.__setattr__(self, "brain", NoBrain())
            return object.__getattribute__(self, "brain")
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ------------------------------------------------------------------
    # Brain helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_brain(config: "BrainConfig") -> "BrainAdapter":
        """Factory: create a BrainAdapter from a BrainConfig."""
        from omega.core.brain import create_brain

        return create_brain(config)

    def set_brain_config(self, config: "BrainConfig") -> None:
        """
        Swap the brain adapter at runtime.

        Safe to call mid-cycle — the new adapter is used on the next
        consult_brain() call. The config change should also be persisted
        to StateStore.save_config_revision() by the caller.
        """
        self.brain = self._create_brain(config)

    def consult_brain(
        self,
        operation: str,
        metrics: dict[str, float] | None = None,
        memories: list[dict] | None = None,
        trace_id: str = "",
    ) -> "BrainResponse":
        """
        Ask the brain for a decision.

        Builds a BrainRequest from the node's current state and calls
        brain.think(). Relevant SKILL.md content (based on ``skill_tags``) is
        loaded from ``omega/skills/`` and prepended to ``domain_context`` so
        the LLM brain has domain-specific guidance.

        If brain is NoBrain (default), returns action="pass" immediately with
        zero latency / cost.

        Callers should check response.action == "pass" and fall back to
        their own rule-based logic in that case.

        Args:
            operation:  "execute" | "evaluate" | "improve" | "analyze"
            metrics:    recent evaluation metrics (defaults to self.evaluate())
            memories:   list of memory dicts from MemoryKernel (optional)
            trace_id:   distributed trace ID for correlation

        Returns:
            BrainResponse with action, parameters, reasoning, confidence
        """
        import os

        from omega.core.brain import BrainRequest

        state = self.get_state()
        if metrics is None:
            try:
                metrics = self.evaluate()
            except Exception:
                metrics = {}

        # Build domain context — start with node description
        domain_context = self.describe()

        # Inject relevant skill content if this node declares skill tags.
        # Skills are advisory: any failure here must never break brain consultation.
        tags = list(getattr(self, "skill_tags", []))
        if tags:
            try:
                from omega.core.skill_loader import SkillLoader

                skills_root = os.path.normpath(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills")
                )
                # Cache loader per node instance to avoid repeated filesystem scans
                if not hasattr(self, "_skill_loader") or self._skill_loader._root != skills_root:
                    object.__setattr__(self, "_skill_loader", SkillLoader(skills_root))
                loader = self._skill_loader
                skill_content = loader.load_for_tags(tags)
                if skill_content:
                    domain_context = f"{domain_context}\n\n# Relevant Skills\n\n{skill_content}"
            except Exception:
                pass  # skills are advisory — never break brain consultation

        request = BrainRequest(
            node_id=state.node_id,
            operation=operation,
            current_state={
                "version": state.version,
                "health": state.health,
                **state.metadata,
            },
            recent_metrics=metrics,
            relevant_memories=memories or [],
            available_actions=self.get_capabilities(),
            domain_context=domain_context,
            trace_id=trace_id,
            skill_hints=tags,
        )
        return self.brain.think(request)

    # ------------------------------------------------------------------
    # Identity & introspection
    # ------------------------------------------------------------------

    @abstractmethod
    def get_state(self) -> NodeState:
        """
        Return a fresh snapshot of this node's state tensor.

        Called by the orchestrator before routing to check health and
        capabilities, and by the evaluator to record metrics over time.
        """

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """
        Return the list of action verbs this node can execute.

        Example: ["add", "subtract", "multiply", "divide"]

        The orchestrator uses this list to route tasks.  Keep verbs
        lowercase and unambiguous.
        """

    @abstractmethod
    def describe(self) -> str:
        """
        Return a human/LLM-readable description of what this node does.

        Written in plain English.  Should be enough for an LLM to
        understand whether to route a task here.
        """

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @abstractmethod
    def execute(self, input: NodeInput) -> NodeOutput:
        """
        Execute an action described by *input* and return a result.

        Implementations MUST:
        - Populate output.request_id = input.request_id.
        - Populate output.metrics with at least {"latency_ms": <float>}.
        - Set output.success = False and populate output.errors on failure.
        - Never raise; catch all exceptions and encode them in output.errors.
        """

    # ------------------------------------------------------------------
    # Self-evaluation & improvement
    # ------------------------------------------------------------------

    @abstractmethod
    def evaluate(self) -> dict[str, float]:
        """
        Self-evaluate and return a dict of performance metrics.

        Keys should be consistent across calls so the evaluator can
        track trends.  Common keys: "accuracy", "avg_latency_ms",
        "cache_hit_rate", "error_rate".
        """

    @abstractmethod
    def improve(self, feedback: dict[str, Any]) -> bool:
        """
        Accept improvement feedback and modify internal behaviour.

        *feedback* is a free-form dict produced by the orchestrator
        after evaluating the system.  The node interprets it and
        decides what (if anything) to change.

        Returns True if the node actually changed something.
        """

    # ------------------------------------------------------------------
    # TPE improvement (optional — override to participate in self-improvement)
    # ------------------------------------------------------------------

    def get_param_space(self) -> list:
        """
        Return the TPE parameter space for this node.

        The default returns an empty list, which disables self-improvement
        for this node.  Override in project-specific nodes to define the
        hyperparameters that the improvement engine should optimise.

        Returns a list of ``Param`` objects (``ContinuousParam``,
        ``DiscreteParam``, or ``CategoricalParam`` from
        ``omega.core.bayesian_optimizer``).
        """
        return []

    # State tensor (optional — override to participate in attention routing)
    # ------------------------------------------------------------------

    def get_state_tensor(self) -> "StateTensor | None":
        """
        Return a StateTensor snapshot for attention-based routing.

        The default implementation returns None, meaning this node will
        not contribute tensor data to the coordinator.  Nodes that want
        to participate in attention routing should override this method
        and return a fully populated StateTensor using their schema.

        The coordinator calls this on every heartbeat; implementations
        must be cheap (< 1 ms) and must never raise.
        """
        return None


# ---------------------------------------------------------------------------
# RoleNode — composite of capability nodes (bridge to Paperclip company-role model)
# ---------------------------------------------------------------------------


class RoleNode(Node):
    """
    A role that composes multiple capability nodes.

    Inspired by Paperclip's company-role model where a "Marketing Manager"
    role orchestrates content generation, analytics, and outreach capabilities.

    In Omega, a role wraps capability nodes and orchestrates them:
      - "Quant Research Analyst" = DataIngestion + SignalGen + Reporting
      - "Risk Officer"           = RiskMgmt + DataIntegrity + HealthMonitor
      - "Portfolio Manager"      = Strategy + RiskMgmt + Reporting

    Architecture note:
      The current Victoria pipeline IS effectively a "Quant Research" role
      composed of 7 capability nodes. RoleNode formalises this pattern so
      future roles can be created by composition without duplication.

    Implementation note:
      This is an ARCHITECTURAL PLACEHOLDER. The concrete execute() here
      sequentially chains capability nodes. Production implementations should
      add parallel execution, conditional branching, and inter-node message
      passing via StateStore.messages.

    Usage::
        role = RoleNode("QuantResearch", [ingestion, signals, reporting])
        output = role.execute(NodeInput(action="research", parameters={}))
    """

    def __init__(self, role_name: str, capability_nodes: list["Node"]) -> None:
        import uuid

        self._node_id = str(uuid.uuid4())
        self._role_name = role_name
        self._capability_nodes = list(capability_nodes)
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0

    # -- Node interface

    def get_state(self) -> NodeState:
        avg_health = sum(n.get_state().health for n in self._capability_nodes) / max(
            1, len(self._capability_nodes)
        )
        all_caps = []
        for n in self._capability_nodes:
            all_caps.extend(n.get_capabilities())
        return NodeState(
            node_id=self._node_id,
            name=f"Role:{self._role_name}",
            version=self._version,
            health=avg_health,
            capabilities=all_caps,
            metrics={
                "node_count": float(len(self._capability_nodes)),
                "avg_health": avg_health,
                "error_rate": self._error_count / max(1, self._execution_count),
            },
            metadata={
                "role": self._role_name,
                "composed_nodes": [n.get_state().name for n in self._capability_nodes],
            },
        )

    def get_capabilities(self) -> list[str]:
        caps = []
        for n in self._capability_nodes:
            caps.extend(n.get_capabilities())
        return list(dict.fromkeys(caps))  # deduplicate preserving order

    def describe(self) -> str:
        node_names = ", ".join(n.get_state().name for n in self._capability_nodes)
        return (
            f"Role '{self._role_name}' composing {len(self._capability_nodes)} capability nodes: "
            f"{node_names}. Routes actions to the appropriate capability node."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        """
        Route to the first capability node that handles the requested action.

        TODO (production): add parallel execution, conditional branching,
        inter-node message passing via StateStore.
        """
        import time

        t0 = time.perf_counter()
        self._execution_count += 1

        action = input.action
        for node in self._capability_nodes:
            if action in node.get_capabilities():
                output = node.execute(input)
                if not output.success:
                    self._error_count += 1
                output.metrics["role_latency_ms"] = (time.perf_counter() - t0) * 1000
                return output

        self._error_count += 1
        return NodeOutput(
            request_id=input.request_id,
            success=False,
            errors=[f"Role '{self._role_name}': no capability node handles action '{action}'"],
            metrics={"role_latency_ms": (time.perf_counter() - t0) * 1000},
        )

    def evaluate(self) -> dict[str, float]:
        metrics = {"error_rate": self._error_count / max(1, self._execution_count)}
        for node in self._capability_nodes:
            try:
                node_metrics = node.evaluate()
                for k, v in node_metrics.items():
                    metrics[f"{node.get_state().name}.{k}"] = v
            except Exception:
                pass
        return metrics

    def improve(self, feedback: dict[str, Any]) -> bool:
        """Delegate improvement to all composed nodes. Returns True if any improved."""
        any_improved = False
        for node in self._capability_nodes:
            try:
                if node.improve(feedback):
                    any_improved = True
            except Exception:
                pass
        return any_improved
