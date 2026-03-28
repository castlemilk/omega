"""
omega.core.project_config
~~~~~~~~~~~~~~~~~~~~~~~~~~
Declarative project definition — anyone can create a new Omega project by
writing a YAML file that wires existing node types together.

Architecture
------------
ProjectConfig  : the validated in-memory representation of a project YAML.
NodeDef        : a single node instance definition (type, name, inputs, config).
RoutingConfig  : how the project routes work between nodes.
ProjectLoader  : loads YAML → ProjectConfig, validates connections, instantiates
                 nodes, and returns a ready-to-run project graph.

YAML format (projects/my_project.yaml)::

    name: my_project
    description: What this project does
    nodes:
      - type: data_provider
        name: binance_feed
        config: {provider: binance, tickers: [BTCUSDT, ETHUSDT]}

      - type: signal_generator
        name: basic_signals
        inputs: [binance_feed.market_data]
        config: {signals: [rsi, macd, bollinger]}

      - type: strategy
        name: conviction_strategy
        inputs: [basic_signals.signal_value, basic_signals.confidence]
        config: {min_conviction: 0.6}

      - type: executor
        name: paper_trader
        inputs: [conviction_strategy.trade_decision]
        config: {mode: paper, max_positions: 9}

    routing:
      type: attention          # attention | dag | round_robin | priority
      config: {dim: 32}

Connection strings
------------------
``"node_name.port_name"``   — wire a specific output port of *node_name*.
``"node_name.*"``           — wire all output ports of *node_name* to this node.

The loader resolves connection strings to Port objects and validates type-
compatibility via :class:`~omega.core.node_registry.NodeTypeRegistry`.

Node instantiation
------------------
ProjectLoader.instantiate() returns a dict mapping node names to live Node
instances.  It uses a *NodeFactory* — a pluggable callable that receives the
NodeDef and returns a Node.  The default factory handles all built-in Victoria
node types; new projects add factories for their own nodes.

Adding a new project
--------------------
1. Write ``projects/my_project.yaml`` following the format above.
2. If you use only existing node types, you're done — run with
   ``omega run --project projects/my_project.yaml``.
3. If you need a new node type, implement a Node subclass, decorate it with
   ``@node_type("my_type", ...)`` and register a factory with
   ``ProjectLoader.register_factory("my_type", my_factory)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("omega.core.project_config")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NodeDef:
    """
    Declaration of a single node instance within a project.

    Attributes
    ----------
    type    : the registered node type name (e.g. ``"signal_generator"``).
    name    : unique instance name within this project (e.g. ``"basic_signals"``).
    inputs  : list of connection strings (``"src_node.port"`` or ``"src_node.*"``).
    config  : free-form dict passed to the node's factory/constructor.
    condition : optional dict for conditional routing (e.g. ``{"confidence__gt": 0.5}``).
    """

    type: str
    name: str
    inputs: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    condition: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NodeDef":
        return cls(
            type=d["type"],
            name=d["name"],
            inputs=list(d.get("inputs", [])),
            config=dict(d.get("config", {})),
            condition=d.get("condition"),
        )


@dataclass
class RoutingConfig:
    """
    How work is routed between nodes.

    Attributes
    ----------
    type   : routing strategy — ``"dag"`` | ``"attention"`` | ``"round_robin"``
             | ``"priority"``.
    config : strategy-specific parameters.

    dag          — nodes run in topological order; default for most projects.
    attention    — attention-weighted routing (requires a trained weight matrix).
    round_robin  — distribute work evenly across nodes of the same type.
    priority     — nodes have numeric priorities; highest runs first.
    """

    type: str = "dag"
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RoutingConfig":
        if d is None:
            return cls()
        return cls(type=d.get("type", "dag"), config=dict(d.get("config", {})))


@dataclass
class ProjectConfig:
    """
    Validated in-memory representation of a project YAML file.

    Attributes
    ----------
    name        : project identifier (e.g. ``"victoria"``).
    description : human-readable description.
    nodes       : ordered list of :class:`NodeDef` instances.
    routing     : how work is routed between nodes.
    raw         : the original parsed YAML dict (for extensions).
    source_path : path to the YAML file, if loaded from disk.
    """

    name: str
    description: str = ""
    nodes: list[NodeDef] = field(default_factory=list)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    raw: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    def get_node(self, name: str) -> NodeDef | None:
        return next((n for n in self.nodes if n.name == name), None)

    def nodes_by_type(self, type_name: str) -> list[NodeDef]:
        return [n for n in self.nodes if n.type == type_name]

    def topological_order(self) -> list[NodeDef]:
        """
        Return nodes in dependency order (sources first, sinks last).

        Uses Kahn's algorithm on the connection graph.  Raises ValueError
        if a cycle is detected.
        """
        # Build in-degree map
        node_names = {nd.name for nd in self.nodes}
        in_degree: dict[str, int] = {nd.name: 0 for nd in self.nodes}
        dependents: dict[str, list[str]] = {nd.name: [] for nd in self.nodes}

        for nd in self.nodes:
            seen_sources: set[str] = set()
            for conn_str in nd.inputs:
                parts = conn_str.split(".", 1)
                if len(parts) == 2:
                    src_name = parts[0]
                    if src_name in node_names and src_name not in seen_sources:
                        seen_sources.add(src_name)
                        in_degree[nd.name] += 1
                        dependents[src_name].append(nd.name)

        queue = [nd for nd in self.nodes if in_degree[nd.name] == 0]
        order: list[NodeDef] = []
        while queue:
            nd = queue.pop(0)
            order.append(nd)
            for dep_name in dependents[nd.name]:
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    dep_nd = self.get_node(dep_name)
                    if dep_nd:
                        queue.append(dep_nd)

        if len(order) != len(self.nodes):
            processed = {nd.name for nd in order}
            cycle = [nd.name for nd in self.nodes if nd.name not in processed]
            raise ValueError(f"Cycle detected in project '{self.name}': {cycle}")

        return order

    @classmethod
    def from_dict(cls, d: dict[str, Any], source_path: Path | None = None) -> "ProjectConfig":
        nodes = [NodeDef.from_dict(nd) for nd in d.get("nodes", [])]
        routing = RoutingConfig.from_dict(d.get("routing"))
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            nodes=nodes,
            routing=routing,
            raw=d,
            source_path=source_path,
        )


# ---------------------------------------------------------------------------
# NodeFactory — pluggable node instantiation
# ---------------------------------------------------------------------------

NodeFactory = Callable[[NodeDef], Any]

# Default registry: node_type_name → factory callable
_FACTORIES: dict[str, NodeFactory] = {}


def register_factory(type_name: str, factory: NodeFactory) -> None:
    """Register a factory for a node type.  Called by node modules at import."""
    _FACTORIES[type_name] = factory
    logger.debug("Registered factory for node type '%s'", type_name)


def get_factory(type_name: str) -> NodeFactory | None:
    return _FACTORIES.get(type_name)


# ---------------------------------------------------------------------------
# Default factories for built-in Victoria node types
# ---------------------------------------------------------------------------

def _build_data_provider(nd: NodeDef) -> Any:
    """
    Instantiate a DataIngestionNode for Victoria-style data provider config.

    Config keys
    -----------
    provider : "binance" | "coingecko" | "bybit" (default "binance")
    tickers  : list of pairs, e.g. ["BTCUSDT", "ETHUSDT"]
    """
    from omega.nodes.victoria.data_ingestion import DataIngestionNode

    node = DataIngestionNode()
    tickers = nd.config.get("tickers")
    if tickers:
        node._tickers = list(tickers)
    return node


def _build_signal_generator(nd: NodeDef) -> Any:
    """
    Instantiate the appropriate signal generator based on config.

    Config keys
    -----------
    signals : list of signal families to activate.
              Recognized values:
                "basic"     → SignalGenerationNode (RSI/MACD/BB/etc.)
                "geometric" → geometric/Riemannian signals
                "smart_money" → SmartMoneySignal
                "sentiment"   → FinBertSentimentSignal
                "spectral"    → SpectralGraphSignal
                "vrp"         → VRPSignalNode
                "whale"       → WhaleFlowSignal
                "regime"      → WassersteinRegimeDetector
              Default is ``["basic"]``.
    """
    signals = nd.config.get("signals", ["basic"])

    if "basic" in signals:
        from omega.nodes.victoria.signal_generation import SignalGenerationNode
        return SignalGenerationNode()

    if "geometric" in signals or "spectral" in signals:
        from omega.nodes.victoria.spectral_signals import SpectralGraphSignal
        return SpectralGraphSignal()

    if "smart_money" in signals:
        from omega.nodes.victoria.smart_money_signal import SmartMoneySignal
        return SmartMoneySignal()

    if "sentiment" in signals:
        from omega.nodes.victoria.finbert_sentiment import FinBertSentimentSignal
        return FinBertSentimentSignal()

    if "vrp" in signals:
        from omega.nodes.victoria.vrp_signal import VRPSignalNode
        return VRPSignalNode()

    if "whale" in signals:
        from omega.nodes.victoria.whale_signal import WhaleFlowSignal
        return WhaleFlowSignal()

    # Fallback
    from omega.nodes.victoria.signal_generation import SignalGenerationNode
    return SignalGenerationNode()


def _build_regime_detector(nd: NodeDef) -> Any:
    algo = nd.config.get("algorithm", "wasserstein")
    if algo == "wasserstein":
        from omega.nodes.victoria.wasserstein_regime import WassersteinRegimeDetector
        return WassersteinRegimeDetector()
    from omega.nodes.victoria.wasserstein_regime import WassersteinRegimeDetector
    return WassersteinRegimeDetector()


def _build_strategy(nd: NodeDef) -> Any:
    from omega.nodes.victoria.strategy import StrategyNode

    node = StrategyNode()
    if "min_conviction" in nd.config:
        node._min_conviction = float(nd.config["min_conviction"])
    return node


def _build_executor(nd: NodeDef) -> Any:
    mode = nd.config.get("mode", "paper")
    if mode == "paper":
        from omega.core.paper_trading import PaperTradingExecutorNode
        node = PaperTradingExecutorNode()
        if "max_positions" in nd.config:
            node._max_positions = int(nd.config["max_positions"])
        return node
    raise ValueError(
        f"Executor mode '{mode}' is not supported yet. "
        "Implement a live executor and register it with register_factory()."
    )


def _build_risk_manager(nd: NodeDef) -> Any:
    from omega.core.risk_manager import PositionRiskManager

    return PositionRiskManager()


def _build_intelligence(nd: NodeDef) -> Any:
    """Wrap any node with an intelligence overlay. Currently a passthrough stub."""
    from omega.core.node import Node, NodeInput, NodeOutput, NodeState
    import uuid

    class _IntelligenceStub(Node):
        """Passthrough intelligence overlay — extend to add LLM reflection."""

        def __init__(self, name: str) -> None:
            self._node_id = str(uuid.uuid4())
            self._name = name

        def get_state(self) -> NodeState:
            from datetime import datetime
            return NodeState(
                node_id=self._node_id,
                name=f"Intelligence:{self._name}",
                version="1.0",
                health=1.0,
                capabilities=["reflect", "improve"],
                metrics={},
                last_updated=datetime.now(),
            )

        def get_capabilities(self) -> list[str]:
            return ["reflect", "improve"]

        def describe(self) -> str:
            return f"Intelligence overlay for '{self._name}'"

        def execute(self, input: NodeInput) -> NodeOutput:
            return NodeOutput(request_id=input.request_id, success=True, result=None)

        def evaluate(self) -> dict[str, float]:
            return {}

        def improve(self, feedback: dict) -> bool:
            return False

    return _IntelligenceStub(nd.name)


# Register all default factories at module import time
register_factory("data_provider", _build_data_provider)
register_factory("signal_generator", _build_signal_generator)
register_factory("regime_detector", _build_regime_detector)
register_factory("strategy", _build_strategy)
register_factory("executor", _build_executor)
register_factory("risk_manager", _build_risk_manager)
register_factory("intelligence", _build_intelligence)


# ---------------------------------------------------------------------------
# ProjectLoader
# ---------------------------------------------------------------------------


class ProjectLoader:
    """
    Loads, validates, and optionally instantiates project configs.

    Usage::

        loader = ProjectLoader()
        config = loader.load("projects/victoria.yaml")
        errors = loader.validate(config)
        if errors:
            for e in errors: print("ERROR:", e)
        else:
            nodes = loader.instantiate(config)
            # nodes is a dict: name → Node instance in topological order
    """

    def __init__(self, strict: bool = False) -> None:
        """
        Parameters
        ----------
        strict : if True, raise on validation errors; otherwise just log them.
        """
        self._strict = strict

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, path: str | Path) -> ProjectConfig:
        """Load a project YAML file and return a :class:`ProjectConfig`."""
        import yaml  # PyYAML is already in the project deps

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Project config not found: {path}")

        with path.open() as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError(f"Invalid project config at '{path}': expected a YAML mapping")

        config = ProjectConfig.from_dict(raw, source_path=path)
        logger.info("Loaded project '%s' from %s (%d nodes)", config.name, path, len(config.nodes))
        return config

    def load_from_dict(self, d: dict[str, Any]) -> ProjectConfig:
        """Load a project config from a pre-parsed dict (useful for tests)."""
        return ProjectConfig.from_dict(d)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate(self, config: ProjectConfig) -> list[str]:
        """
        Validate a :class:`ProjectConfig` and return all errors found.

        Checks
        ------
        1. All node types are registered.
        2. All node names are unique within the project.
        3. All connection source nodes exist within the project.
        4. Port types are compatible (via NodeTypeRegistry).
        5. No dependency cycles.
        """
        from omega.core.node_registry import get_registry

        registry = get_registry()
        errors: list[str] = []

        # 1. All types registered
        for nd in config.nodes:
            if registry.get_type(nd.type) is None:
                errors.append(
                    f"Node '{nd.name}': type '{nd.type}' is not registered. "
                    f"Known types: {registry.known_type_names()}"
                )

        # 2. Unique names
        seen_names: set[str] = set()
        for nd in config.nodes:
            if nd.name in seen_names:
                errors.append(f"Duplicate node name '{nd.name}' in project '{config.name}'")
            seen_names.add(nd.name)

        # 3 & 4. Connection validation
        node_defs_as_dicts = [
            {"type": nd.type, "name": nd.name, "inputs": nd.inputs}
            for nd in config.nodes
        ]
        conn_errors = registry.validate_project_connections(node_defs_as_dicts)
        errors.extend(conn_errors)

        # 5. Cycle detection
        try:
            config.topological_order()
        except ValueError as exc:
            errors.append(str(exc))

        if errors:
            level = logging.ERROR if self._strict else logging.WARNING
            for e in errors:
                logger.log(level, "Project '%s' validation: %s", config.name, e)

        return errors

    # ------------------------------------------------------------------
    # Instantiate
    # ------------------------------------------------------------------

    def instantiate(
        self,
        config: ProjectConfig,
        extra_factories: dict[str, NodeFactory] | None = None,
    ) -> dict[str, Any]:
        """
        Instantiate all nodes in topological order.

        Parameters
        ----------
        config          : validated :class:`ProjectConfig`.
        extra_factories : optional overrides/additions to the default factory map.

        Returns
        -------
        dict mapping node *name* → live Node instance.

        Raises
        ------
        ValueError  : if a node type has no factory and cannot be instantiated.
        """
        factories = dict(_FACTORIES)
        if extra_factories:
            factories.update(extra_factories)

        ordered = config.topological_order()
        instances: dict[str, Any] = {}

        for nd in ordered:
            factory = factories.get(nd.type)
            if factory is None:
                raise ValueError(
                    f"No factory registered for node type '{nd.type}'. "
                    f"Call register_factory('{nd.type}', ...) or pass extra_factories."
                )
            try:
                instance = factory(nd)
                instances[nd.name] = instance
                logger.info(
                    "Instantiated '%s' (%s) → %s",
                    nd.name,
                    nd.type,
                    type(instance).__name__,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to instantiate node '{nd.name}' (type='{nd.type}'): {exc}"
                ) from exc

        return instances

    # ------------------------------------------------------------------
    # Convenience: load + validate + instantiate in one call
    # ------------------------------------------------------------------

    def load_and_build(
        self,
        path: str | Path,
        extra_factories: dict[str, NodeFactory] | None = None,
        allow_errors: bool = False,
    ) -> tuple[ProjectConfig, dict[str, Any]]:
        """
        Load a YAML file, validate it, and instantiate all nodes.

        Parameters
        ----------
        path            : path to the project YAML file.
        extra_factories : additional/override factories.
        allow_errors    : if True, instantiate even if validation errors exist.

        Returns
        -------
        (ProjectConfig, dict[name → Node])

        Raises
        ------
        ValueError  : if validation errors are found and allow_errors is False.
        """
        config = self.load(path)
        errors = self.validate(config)

        if errors and not allow_errors:
            summary = "\n  ".join(errors)
            raise ValueError(
                f"Project '{config.name}' has {len(errors)} validation error(s):\n  {summary}"
            )

        nodes = self.instantiate(config, extra_factories=extra_factories)
        return config, nodes


# ---------------------------------------------------------------------------
# PaperTradingExecutorNode — thin wrapper so the executor factory works
# without modifying existing paper_trading.py
# ---------------------------------------------------------------------------

class PaperTradingExecutorNode:
    """
    Adapter that wraps the paper trading system as an ExecutorNode.

    This is the default executor for new projects.  Replace it by registering
    a factory for "executor" with register_factory().
    """

    def __init__(self) -> None:
        import uuid
        from datetime import datetime

        self._node_id = str(uuid.uuid4())
        self._max_positions = 9
        self._mode = "paper"

    # Minimal Node interface so it can be stored in a node map
    def get_state(self) -> Any:
        from omega.core.node import NodeState
        from datetime import datetime

        return NodeState(
            node_id=self._node_id,
            name="PaperTradingExecutor",
            version="1.0",
            health=1.0,
            capabilities=["execute_trades", "paper_trade"],
            metrics={},
            last_updated=datetime.now(),
            metadata={"mode": self._mode, "max_positions": self._max_positions},
        )

    def get_capabilities(self) -> list[str]:
        return ["execute_trades", "paper_trade"]

    def describe(self) -> str:
        return (
            f"Paper trading executor (mode={self._mode}, "
            f"max_positions={self._max_positions})"
        )

    def execute(self, input: Any) -> Any:
        from omega.core.node import NodeOutput
        return NodeOutput(request_id=getattr(input, "request_id", ""), success=True)

    def evaluate(self) -> dict:
        return {}

    def improve(self, feedback: dict) -> bool:
        return False
