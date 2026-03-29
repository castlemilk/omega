"""
omega.core.node_registry
~~~~~~~~~~~~~~~~~~~~~~~~~
Universal node type system — the type lattice that makes Omega extensible.

Anyone can define a new project (Victoria, Flaggr, Cuttlefish…) by wiring
together node types declared here.  The registry validates that connections
are type-safe at startup so mismatches are caught before the first trade.

Concepts
--------
Port       : a named data channel with a semantic dtype (e.g. "market_data").
             Ports are the *contract* between nodes — two ports connect only
             when their dtypes are compatible (identical or one is "any").

NodeTypeSpec : declares the input/output ports for a node class.  Registered
               via the ``@node_type`` decorator.

NodeTypeRegistry : singleton — all node types land here.

Connection validation :
    validate_connection(src_type, src_port, dst_type, dst_port) returns a
    list of error strings (empty == valid).

Usage::

    @node_type(
        "signal_generator",
        inputs=[Port("market_data", dtype="market_data")],
        outputs=[Port("signal_value", dtype="signal_value"),
                 Port("confidence",   dtype="float")],
        description="Produces trading signals from market data",
    )
    class MySignalNode(Node):
        ...

    # Later
    registry = get_registry()
    errors = registry.validate_connection(
        "data_provider", "market_data",
        "signal_generator", "market_data",
    )
    assert errors == []
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.node_registry")


# ---------------------------------------------------------------------------
# Port — single data channel on a node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Port:
    """
    A named, typed data channel on a node.

    Attributes
    ----------
    name  : the port identifier used in YAML wiring (e.g. ``"market_data"``).
    dtype : semantic type of data flowing through this port.
            Use "any" to accept/produce anything.
    many  : True if the port can fan-in (input) or fan-out (output) to
            multiple connections simultaneously.
    required : False means the node can run without this input being wired.
    """

    name: str
    dtype: str = "any"
    many: bool = False
    required: bool = True

    def is_compatible_with(self, other: Port) -> bool:
        """Return True if *self* (source output) can feed *other* (dest input)."""
        return self.dtype == "any" or other.dtype == "any" or self.dtype == other.dtype


# ---------------------------------------------------------------------------
# NodeTypeSpec — the full interface declaration for a node type
# ---------------------------------------------------------------------------


@dataclass
class NodeTypeSpec:
    """
    Describes one registered node type.

    Attributes
    ----------
    name        : kebab-case type name, e.g. ``"signal_generator"``.
    cls         : the Python class backing this type.
    inputs      : ordered list of input ports.
    outputs     : ordered list of output ports.
    description : plain-English description for docs and routing.
    """

    name: str
    cls: type
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    description: str = ""

    # Index by port name for O(1) lookup
    _input_index: dict[str, Port] = field(default_factory=dict, repr=False, compare=False)
    _output_index: dict[str, Port] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._input_index = {p.name: p for p in self.inputs}
        self._output_index = {p.name: p for p in self.outputs}

    def get_input(self, name: str) -> Port | None:
        return self._input_index.get(name)

    def get_output(self, name: str) -> Port | None:
        return self._output_index.get(name)

    def all_output_names(self) -> list[str]:
        return list(self._output_index)


# ---------------------------------------------------------------------------
# NodeTypeRegistry — singleton
# ---------------------------------------------------------------------------


class NodeTypeRegistry:
    """
    Global registry of all node types.

    Node types are added via the ``@node_type`` decorator or
    ``register_type()`` directly.  The registry is consulted by
    ProjectLoader to validate connections before any nodes are started.
    """

    def __init__(self) -> None:
        self._types: dict[str, NodeTypeSpec] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_type(self, spec: NodeTypeSpec) -> None:
        if spec.name in self._types:
            logger.warning("Node type '%s' already registered; replacing.", spec.name)
        self._types[spec.name] = spec
        logger.debug("Registered node type '%s' (%s)", spec.name, spec.cls.__name__)

    def get_type(self, name: str) -> NodeTypeSpec | None:
        return self._types.get(name)

    def all_types(self) -> list[NodeTypeSpec]:
        return list(self._types.values())

    def known_type_names(self) -> list[str]:
        return list(self._types)

    # ------------------------------------------------------------------
    # Connection validation
    # ------------------------------------------------------------------

    def validate_connection(
        self,
        src_type_name: str,
        src_port_name: str,
        dst_type_name: str,
        dst_port_name: str,
    ) -> list[str]:
        """
        Check that (src_type.src_port) → (dst_type.dst_port) is valid.

        Returns a list of error strings; empty list means the connection is
        type-safe.

        Wildcard port ``"*"`` on the source means "all outputs" — each output
        port is validated independently against *dst_port_name*.
        """
        errors: list[str] = []

        src_spec = self._types.get(src_type_name)
        if src_spec is None:
            errors.append(f"Unknown source node type '{src_type_name}'")
            return errors

        dst_spec = self._types.get(dst_type_name)
        if dst_spec is None:
            errors.append(f"Unknown destination node type '{dst_type_name}'")
            return errors

        # Wildcard: validate each output against the destination port
        if src_port_name == "*":
            for out_port in src_spec.outputs:
                errors.extend(self._check_port_pair(src_spec, out_port, dst_spec, dst_port_name))
            return errors

        src_port = src_spec.get_output(src_port_name)
        if src_port is None:
            errors.append(
                f"Node type '{src_type_name}' has no output port '{src_port_name}'. "
                f"Available: {src_spec.all_output_names()}"
            )
            return errors

        errors.extend(self._check_port_pair(src_spec, src_port, dst_spec, dst_port_name))
        return errors

    def _check_port_pair(
        self,
        src_spec: NodeTypeSpec,
        src_port: Port,
        dst_spec: NodeTypeSpec,
        dst_port_name: str,
    ) -> list[str]:
        errors: list[str] = []
        dst_port = dst_spec.get_input(dst_port_name)
        if dst_port is None:
            errors.append(
                f"Node type '{dst_spec.name}' has no input port '{dst_port_name}'. "
                f"Available: {[p.name for p in dst_spec.inputs]}"
            )
            return errors

        if not src_port.is_compatible_with(dst_port):
            errors.append(
                f"Type mismatch: '{src_spec.name}.{src_port.name}' produces "
                f"dtype='{src_port.dtype}' but '{dst_spec.name}.{dst_port.name}' "
                f"expects dtype='{dst_port.dtype}'"
            )
        return errors

    def validate_project_connections(
        self,
        node_defs: list[dict[str, Any]],
    ) -> list[str]:
        """
        Validate all connections in a list of node definitions.

        Each item in *node_defs* must have:
          - ``type``   : the registered node type name
          - ``name``   : the instance name within the project
          - ``inputs`` : list of connection strings like ``"source_node.port"``

        Returns all errors found across all connections.
        """
        errors: list[str] = []
        # Build name → type_name map for this project
        name_to_type: dict[str, str] = {}
        for nd in node_defs:
            name_to_type[nd["name"]] = nd["type"]

        for nd in node_defs:
            dst_type_name = nd.get("type", "")
            dst_node_name = nd.get("name", "")
            for conn_str in nd.get("inputs", []):
                parts = conn_str.split(".", 1)
                if len(parts) != 2:
                    errors.append(
                        f"Node '{dst_node_name}': malformed connection '{conn_str}' "
                        f"(expected 'node_name.port_name' or 'node_name.*')"
                    )
                    continue
                src_node_name, src_port_name = parts
                src_type_name = name_to_type.get(src_node_name)
                if src_type_name is None:
                    errors.append(
                        f"Node '{dst_node_name}': connection '{conn_str}' references "
                        f"unknown node '{src_node_name}'"
                    )
                    continue

                # For wildcard, validate each output against "any" dst input
                if src_port_name == "*":
                    # Just check that source type is known; wildcard = all outputs
                    src_spec = self._types.get(src_type_name)
                    if src_spec is None:
                        errors.append(
                            f"Node '{dst_node_name}': source type '{src_type_name}' unknown"
                        )
                    continue

                # Infer which input port on the destination the source port feeds
                # Convention: if the source port name matches a dst input port, wire directly.
                # Otherwise, use "any" as the dest port name (for flexible wiring).
                dst_spec = self._types.get(dst_type_name)
                if dst_spec is None:
                    errors.append(f"Node '{dst_node_name}': type '{dst_type_name}' unknown")
                    continue

                # Find best-matching destination input port
                dst_port_name = src_port_name  # try exact name first
                if dst_spec.get_input(dst_port_name) is None:
                    # Fall back to first required input of compatible type
                    src_spec = self._types.get(src_type_name)
                    src_port = src_spec.get_output(src_port_name) if src_spec else None
                    matched = None
                    for inp in dst_spec.inputs:
                        if src_port is None or src_port.is_compatible_with(inp):
                            matched = inp.name
                            break
                    if matched is None:
                        errors.append(
                            f"Node '{dst_node_name}': cannot wire '{conn_str}' — "
                            f"no compatible input port found on '{dst_type_name}'"
                        )
                        continue
                    dst_port_name = matched

                conn_errors = self.validate_connection(
                    src_type_name, src_port_name, dst_type_name, dst_port_name
                )
                errors.extend(conn_errors)

        return errors


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_REGISTRY: NodeTypeRegistry | None = None


def get_registry() -> NodeTypeRegistry:
    """Return the process-global NodeTypeRegistry, creating it on first call."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = NodeTypeRegistry()
        _register_builtins(_REGISTRY)
    return _REGISTRY


def reset_registry() -> None:
    """Reset the global registry (test helper — do not call in production)."""
    global _REGISTRY
    _REGISTRY = None


# ---------------------------------------------------------------------------
# @node_type decorator
# ---------------------------------------------------------------------------


def node_type(
    type_name: str,
    inputs: list[Port] | None = None,
    outputs: list[Port] | None = None,
    description: str = "",
) -> Callable[[type], type]:
    """
    Class decorator that registers a class as a node type.

    Parameters
    ----------
    type_name   : unique kebab-case name, e.g. ``"signal_generator"``.
    inputs      : list of :class:`Port` objects this node type accepts.
    outputs     : list of :class:`Port` objects this node type produces.
    description : human-readable description.

    Example::

        @node_type(
            "signal_generator",
            inputs=[Port("market_data", dtype="market_data")],
            outputs=[Port("signal_value", dtype="signal_value"),
                     Port("confidence",   dtype="float")],
            description="Produces trading signals from market data",
        )
        class MySignalNode(Node):
            ...
    """

    def decorator(cls: type) -> type:
        spec = NodeTypeSpec(
            name=type_name,
            cls=cls,
            inputs=inputs or [],
            outputs=outputs or [],
            description=description,
        )
        get_registry().register_type(spec)
        # Attach spec to the class for introspection
        cls._node_type_spec = spec  # type: ignore[attr-defined]
        return cls

    return decorator


# ---------------------------------------------------------------------------
# Built-in node type declarations
# ---------------------------------------------------------------------------
# Interface stubs — one per foundational node type.  These carry no logic;
# they exist only so that @node_type can attach a _node_type_spec and so
# that concrete implementations can subclass them as a marker.


class DataProviderNode:
    """Abstract interface for data provider nodes (Binance, CoinGecko, …)."""


class SignalGeneratorNode:
    """Abstract interface for signal generator nodes."""


class RegimeDetectorNode:
    """Abstract interface for regime detection nodes."""


class StrategyNode:
    """Abstract interface for strategy/portfolio construction nodes."""


class ExecutorNode:
    """Abstract interface for execution nodes (paper or live)."""


class IntelligenceNode:
    """Abstract interface for intelligence overlay nodes."""


class RiskManagerNode:
    """Abstract interface for risk management nodes."""


def _register_builtins(registry: NodeTypeRegistry) -> None:
    """
    Populate *registry* with the seven foundational node type specs.

    Called automatically by :func:`get_registry` whenever a fresh registry is
    created.  This means the built-ins survive :func:`reset_registry` + a
    subsequent :func:`get_registry` call (important for test isolation).
    """
    _specs = [
        NodeTypeSpec(
            name="data_provider",
            cls=DataProviderNode,
            inputs=[],
            outputs=[
                Port("market_data", dtype="market_data", many=True),
                Port("metadata", dtype="dict", many=True, required=False),
            ],
            description="Fetches external data (prices, news, on-chain) and emits it downstream",
        ),
        NodeTypeSpec(
            name="signal_generator",
            cls=SignalGeneratorNode,
            inputs=[
                Port("market_data", dtype="market_data"),
                Port("regime", dtype="regime", required=False),
                Port("metadata", dtype="dict", required=False),
            ],
            outputs=[
                Port("signal_value", dtype="signal_value", many=True),
                Port("confidence", dtype="float", many=True),
                Port("signal_metadata", dtype="dict", many=True, required=False),
            ],
            description="Consumes market data and emits typed trading signals with confidence",
        ),
        NodeTypeSpec(
            name="regime_detector",
            cls=RegimeDetectorNode,
            inputs=[Port("market_data", dtype="market_data")],
            outputs=[Port("regime", dtype="regime", many=True)],
            description="Detects the current market regime from data",
        ),
        NodeTypeSpec(
            name="strategy",
            cls=StrategyNode,
            inputs=[
                Port("signal_value", dtype="signal_value", many=True),
                Port("confidence", dtype="float", many=True),
                Port("regime", dtype="regime", required=False),
                Port("risk_params", dtype="dict", required=False),
            ],
            outputs=[
                Port("trade_decision", dtype="trade_decision", many=True),
                Port("position_weights", dtype="dict", many=True),
            ],
            description="Aggregates signals into portfolio decisions and position sizing",
        ),
        NodeTypeSpec(
            name="executor",
            cls=ExecutorNode,
            inputs=[
                Port("trade_decision", dtype="trade_decision"),
                Port("position_weights", dtype="dict", required=False),
            ],
            outputs=[
                Port("execution_report", dtype="dict", many=True),
                Port("fill", dtype="dict", many=True, required=False),
            ],
            description="Executes trade decisions — paper trading, live, or simulation",
        ),
        NodeTypeSpec(
            name="intelligence",
            cls=IntelligenceNode,
            inputs=[
                Port("any_output", dtype="any"),
                Port("metrics", dtype="dict", required=False),
            ],
            outputs=[
                Port("reflection", dtype="dict", many=True),
                Port("improvement_hint", dtype="dict", many=True, required=False),
            ],
            description="Wraps any node with LLM reasoning/reflection capability",
        ),
        NodeTypeSpec(
            name="risk_manager",
            cls=RiskManagerNode,
            inputs=[
                Port("trade_decision", dtype="trade_decision"),
                Port("position_weights", dtype="dict", required=False),
                Port("signal_value", dtype="signal_value", required=False),
            ],
            outputs=[
                Port("approved_decision", dtype="trade_decision", many=True),
                Port("risk_params", dtype="dict", many=True),
            ],
            description="Applies risk controls and position limits to trade decisions",
        ),
    ]
    for spec in _specs:
        registry.register_type(spec)
