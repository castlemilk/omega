"""
omega.core.deterministic_compiler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DeterministicCompiler — freezes a node's current parameters into a versioned,
LLM-free strategy that can execute with zero external calls.

This is the PICO-mode execution engine. When a node is at AutonomyLevel.PICO,
the controller compiles its current parameters into a DeterministicStrategy.
The strategy executes rule-based logic only — no brain, no LLM, no network.

Design
------
DeterministicStrategy   — frozen, versioned rule set + execute()
DeterministicCompiler   — compiles a node snapshot → DeterministicStrategy
Signal                  — output of DeterministicStrategy.execute()
StrategyRegistry        — in-memory + optional StateStore-backed version history

Rollback
--------
Each compilation is assigned a monotonically increasing version. Any prior
version can be retrieved and re-activated via rollback().

Usage
-----
    compiler = DeterministicCompiler()
    strategy = compiler.compile_strategy(node)
    signal = strategy.execute(market_data)
    print(signal.direction, signal.confidence)

    # Rollback to a previous version
    old_strategy = compiler.rollback(node_id="my-node", version=1)
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Signal — output of a deterministic strategy
# ---------------------------------------------------------------------------


class SignalDirection(str, Enum):  # noqa: UP042
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"  # no position


@dataclass
class Signal:
    """
    Trading / action signal produced by a DeterministicStrategy.

    direction   — LONG, SHORT, or FLAT
    confidence  — [0.0, 1.0]; how strongly the rules fired
    metadata    — any additional context (rule names, thresholds used, etc.)
    generated_at — Unix timestamp of signal creation
    """

    direction: SignalDirection = SignalDirection.FLAT
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)

    def is_actionable(self, min_confidence: float = 0.5) -> bool:
        return self.direction != SignalDirection.FLAT and self.confidence >= min_confidence


# ---------------------------------------------------------------------------
# DeterministicStrategy — frozen, versioned rule set
# ---------------------------------------------------------------------------


@dataclass
class DeterministicStrategy:
    """
    A frozen, versioned representation of a node's rule-based logic.

    Created by DeterministicCompiler.compile_strategy().  Executes with
    zero LLM calls — purely deterministic given the frozen parameters.

    Attributes
    ----------
    strategy_id     — unique ID for this compiled artifact
    node_id         — source node
    node_version    — node version at compile time
    version         — monotonically increasing compilation version
    parameters      — deep-frozen copy of node parameters at compile time
    rules           — ordered list of rule dicts (see _apply_rules)
    compiled_at     — Unix timestamp
    checksum        — SHA-256 of the serialised parameters (integrity check)
    """

    strategy_id: str
    node_id: str
    node_version: str
    version: int
    parameters: dict[str, Any]
    rules: list[dict[str, Any]]
    compiled_at: float = field(default_factory=time.time)
    checksum: str = ""

    # ------------------------------------------------------------------
    # Execution — pure rule engine, no LLM
    # ------------------------------------------------------------------

    def execute(self, market_data: dict[str, Any]) -> Signal:
        """
        Evaluate frozen rules against *market_data* and return a Signal.

        Rules are evaluated in order; the first rule whose conditions all
        pass determines the signal direction. If no rule fires, returns
        Signal(FLAT, 0.0).

        Each rule dict has the shape:
        {
            "name":       str,
            "direction":  "long" | "short" | "flat",
            "conditions": [
                {"field": str, "op": ">"|"<"|">="|"<="|"=="|"!=", "value": float}
            ],
            "confidence": float
        }
        """
        for rule in self.rules:
            if self._evaluate_rule(rule, market_data):
                return Signal(
                    direction=SignalDirection(rule.get("direction", "flat")),
                    confidence=float(rule.get("confidence", 0.5)),
                    metadata={
                        "rule_name": rule.get("name", "unnamed"),
                        "strategy_id": self.strategy_id,
                        "strategy_version": self.version,
                    },
                )
        return Signal(
            direction=SignalDirection.FLAT,
            confidence=0.0,
            metadata={"strategy_id": self.strategy_id, "reason": "no_rule_fired"},
        )

    def _evaluate_rule(self, rule: dict[str, Any], data: dict[str, Any]) -> bool:
        """Return True if all conditions in *rule* pass against *data*."""
        conditions = rule.get("conditions", [])
        if not conditions:
            return False
        for cond in conditions:
            field_val = self._resolve_field(cond.get("field", ""), data)
            if field_val is None:
                return False
            op = cond.get("op", "==")
            threshold = cond.get("value", 0.0)
            if not self._compare(field_val, op, threshold):
                return False
        return True

    @staticmethod
    def _resolve_field(field_path: str, data: dict[str, Any]) -> Any:
        """Support dot-notation field paths like 'price.close'."""
        parts = field_path.split(".")
        current: Any = data
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    @staticmethod
    def _compare(value: Any, op: str, threshold: float) -> bool:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        ops = {
            ">": v > threshold,
            "<": v < threshold,
            ">=": v >= threshold,
            "<=": v <= threshold,
            "==": v == threshold,
            "!=": v != threshold,
        }
        return ops.get(op, False)

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_checksum(self) -> bool:
        """Return True if the parameters have not been tampered with."""
        expected = _compute_checksum(self.parameters)
        return expected == self.checksum

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "node_id": self.node_id,
            "node_version": self.node_version,
            "version": self.version,
            "parameters": self.parameters,
            "rules": self.rules,
            "compiled_at": self.compiled_at,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeterministicStrategy:
        return cls(
            strategy_id=d["strategy_id"],
            node_id=d["node_id"],
            node_version=d["node_version"],
            version=int(d["version"]),
            parameters=d["parameters"],
            rules=d["rules"],
            compiled_at=float(d.get("compiled_at", time.time())),
            checksum=d.get("checksum", ""),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_checksum(parameters: dict[str, Any]) -> str:
    serialised = json.dumps(parameters, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _extract_parameters(node: Any) -> dict[str, Any]:
    """
    Best-effort extraction of a node's current parameters.

    Tries, in order:
    1. node.get_parameters()
    2. node.parameters (attribute)
    3. node.get_state().metadata
    4. empty dict
    """
    if hasattr(node, "get_parameters") and callable(node.get_parameters):
        try:
            return copy.deepcopy(node.get_parameters())
        except Exception:
            pass
    if hasattr(node, "parameters") and isinstance(node.parameters, dict):
        return copy.deepcopy(node.parameters)
    if hasattr(node, "get_state"):
        try:
            state = node.get_state()
            return copy.deepcopy(state.metadata)
        except Exception:
            pass
    return {}


def _extract_rules(node: Any, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract or synthesise rules from the node's current configuration.

    Tries node.get_rules() first. Falls back to synthesising rules from
    common parameter keys (e.g. 'signal_threshold', 'rsi_oversold', etc.)
    so that even nodes without explicit rule support get a sensible default.
    """
    if hasattr(node, "get_rules") and callable(node.get_rules):
        try:
            node_rules: Any = node.get_rules()
            if isinstance(node_rules, list) and node_rules:  # only use if non-empty
                return copy.deepcopy(node_rules)
        except Exception:
            pass

    # Synthesise rules from well-known parameter keys
    rules: list[dict[str, Any]] = []

    # RSI-style rules
    if "rsi_oversold" in parameters:
        rules.append(
            {
                "name": "rsi_oversold_long",
                "direction": "long",
                "conditions": [
                    {"field": "rsi", "op": "<=", "value": float(parameters["rsi_oversold"])}
                ],
                "confidence": 0.7,
            }
        )
    if "rsi_overbought" in parameters:
        rules.append(
            {
                "name": "rsi_overbought_short",
                "direction": "short",
                "conditions": [
                    {"field": "rsi", "op": ">=", "value": float(parameters["rsi_overbought"])}
                ],
                "confidence": 0.7,
            }
        )

    # Generic threshold rules
    if "signal_threshold_long" in parameters:
        rules.append(
            {
                "name": "signal_long",
                "direction": "long",
                "conditions": [
                    {
                        "field": "signal",
                        "op": ">=",
                        "value": float(parameters["signal_threshold_long"]),
                    }
                ],
                "confidence": float(parameters.get("signal_confidence", 0.6)),
            }
        )
    if "signal_threshold_short" in parameters:
        rules.append(
            {
                "name": "signal_short",
                "direction": "short",
                "conditions": [
                    {
                        "field": "signal",
                        "op": "<=",
                        "value": float(parameters["signal_threshold_short"]),
                    }
                ],
                "confidence": float(parameters.get("signal_confidence", 0.6)),
            }
        )

    # Always add a flat fallback (lowest priority, caught by default in execute())
    return rules


# ---------------------------------------------------------------------------
# StrategyRegistry — in-memory version history with optional persistence
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """
    Versioned strategy store.

    Keeps all compiled strategies for each node indexed by version number.
    The current (latest) strategy is the one with the highest version.
    """

    def __init__(self) -> None:
        # node_id → {version: DeterministicStrategy}
        self._strategies: dict[str, dict[int, DeterministicStrategy]] = {}

    def register(self, strategy: DeterministicStrategy) -> None:
        node_strategies = self._strategies.setdefault(strategy.node_id, {})
        node_strategies[strategy.version] = strategy

    def get(self, node_id: str, version: int) -> DeterministicStrategy | None:
        return self._strategies.get(node_id, {}).get(version)

    def get_current(self, node_id: str) -> DeterministicStrategy | None:
        node_strategies = self._strategies.get(node_id, {})
        if not node_strategies:
            return None
        latest_version = max(node_strategies.keys())
        return node_strategies[latest_version]

    def list_versions(self, node_id: str) -> list[int]:
        return sorted(self._strategies.get(node_id, {}).keys())

    def next_version(self, node_id: str) -> int:
        versions = self.list_versions(node_id)
        return (max(versions) + 1) if versions else 1


# ---------------------------------------------------------------------------
# DeterministicCompiler
# ---------------------------------------------------------------------------


class DeterministicCompiler:
    """
    Compiles a node's current parameters into a DeterministicStrategy.

    Each call to compile_strategy() freezes the node's parameters as of
    that moment, assigns a new version, and registers it in the StrategyRegistry.

    Rollback
    --------
    Any previously compiled version can be retrieved with rollback(). The
    compiler does not automatically apply rolled-back strategies to nodes —
    callers must do that explicitly (e.g. by calling node.load_strategy()).

    Usage
    -----
        compiler = DeterministicCompiler()
        strategy = compiler.compile_strategy(node)
        signal = strategy.execute({"rsi": 28.0, "price": {"close": 100.0}})

        # List versions for a node
        compiler.registry.list_versions("my-node-id")

        # Rollback to version 1
        old = compiler.rollback("my-node-id", version=1)
    """

    def __init__(self, registry: StrategyRegistry | None = None) -> None:
        self.registry = registry or StrategyRegistry()

    def compile_strategy(self, node: Any) -> DeterministicStrategy:
        """
        Freeze *node*'s current parameters as a DeterministicStrategy.

        1. Extract parameters from the node (deep copy — no references)
        2. Extract / synthesise rules from the parameters
        3. Assign a monotonically increasing version
        4. Compute an integrity checksum
        5. Register and return

        The node must implement the Node base class interface (get_state()).
        """
        # Extract node identity
        try:
            state = node.get_state()
            node_id = state.node_id
            node_version = state.version
        except Exception:
            node_id = getattr(node, "node_id", str(uuid.uuid4()))
            node_version = getattr(node, "version", "unknown")

        parameters = _extract_parameters(node)
        rules = _extract_rules(node, parameters)
        version = self.registry.next_version(node_id)
        checksum = _compute_checksum(parameters)

        strategy = DeterministicStrategy(
            strategy_id=str(uuid.uuid4()),
            node_id=node_id,
            node_version=node_version,
            version=version,
            parameters=parameters,
            rules=rules,
            compiled_at=time.time(),
            checksum=checksum,
        )
        self.registry.register(strategy)
        return strategy

    def rollback(self, node_id: str, version: int) -> DeterministicStrategy | None:
        """
        Retrieve a previously compiled strategy by version number.

        Returns None if the version does not exist in the registry.
        Does NOT automatically apply the strategy to the node.
        """
        return self.registry.get(node_id, version)

    def get_current(self, node_id: str) -> DeterministicStrategy | None:
        """Return the most recently compiled strategy for a node."""
        return self.registry.get_current(node_id)
