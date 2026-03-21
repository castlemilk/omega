"""Tests for omega.core.deterministic_compiler — DeterministicCompiler."""

from __future__ import annotations

import pytest

from omega.core.deterministic_compiler import (
    DeterministicCompiler,
    DeterministicStrategy,
    Signal,
    SignalDirection,
    StrategyRegistry,
    _compute_checksum,
)

# ---------------------------------------------------------------------------
# Minimal node stub
# ---------------------------------------------------------------------------


class _StubNode:
    """Minimal node stub for compiler tests — no real Node base class needed."""

    def __init__(
        self,
        node_id: str = "stub-node-1",
        version: str = "1.0",
        parameters: dict | None = None,
        rules: list | None = None,
    ) -> None:
        self._node_id = node_id
        self._version = version
        self.parameters: dict = parameters or {}
        self._rules = rules

    def get_state(self):
        from datetime import datetime

        from omega.core.node import NodeState

        return NodeState(
            node_id=self._node_id,
            name="StubNode",
            version=self._version,
            health=1.0,
            capabilities=["execute"],
            metrics={},
            last_updated=datetime.now(),
        )

    def get_rules(self) -> list:
        return self._rules or []


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------


def test_signal_is_actionable_above_threshold() -> None:
    s = Signal(direction=SignalDirection.LONG, confidence=0.8)
    assert s.is_actionable(min_confidence=0.5)


def test_signal_not_actionable_flat() -> None:
    s = Signal(direction=SignalDirection.FLAT, confidence=0.9)
    assert not s.is_actionable()


def test_signal_not_actionable_below_confidence() -> None:
    s = Signal(direction=SignalDirection.SHORT, confidence=0.3)
    assert not s.is_actionable(min_confidence=0.5)


# ---------------------------------------------------------------------------
# StrategyRegistry tests
# ---------------------------------------------------------------------------


def _make_strategy(node_id: str = "n1", version: int = 1) -> DeterministicStrategy:
    params = {"x": 1.0}
    return DeterministicStrategy(
        strategy_id=f"sid-{version}",
        node_id=node_id,
        node_version="1.0",
        version=version,
        parameters=params,
        rules=[],
        checksum=_compute_checksum(params),
    )


def test_registry_register_and_get() -> None:
    reg = StrategyRegistry()
    s = _make_strategy(version=1)
    reg.register(s)
    assert reg.get("n1", 1) is s


def test_registry_get_current_returns_latest() -> None:
    reg = StrategyRegistry()
    reg.register(_make_strategy(version=1))
    reg.register(_make_strategy(version=2))
    reg.register(_make_strategy(version=3))
    current = reg.get_current("n1")
    assert current is not None
    assert current.version == 3


def test_registry_next_version_empty() -> None:
    reg = StrategyRegistry()
    assert reg.next_version("new-node") == 1


def test_registry_next_version_increments() -> None:
    reg = StrategyRegistry()
    reg.register(_make_strategy(version=5))
    assert reg.next_version("n1") == 6


def test_registry_list_versions() -> None:
    reg = StrategyRegistry()
    for v in [1, 3, 2]:
        reg.register(_make_strategy(version=v))
    assert reg.list_versions("n1") == [1, 2, 3]


# ---------------------------------------------------------------------------
# DeterministicCompiler — compile_strategy
# ---------------------------------------------------------------------------


def test_compile_basic(tmp_path) -> None:
    compiler = DeterministicCompiler()
    node = _StubNode(parameters={"rsi_oversold": 30.0, "rsi_overbought": 70.0})
    strategy = compiler.compile_strategy(node)
    assert strategy.node_id == "stub-node-1"
    assert strategy.version == 1
    assert strategy.checksum != ""
    assert strategy.verify_checksum()


def test_compile_increments_version() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode()
    s1 = compiler.compile_strategy(node)
    s2 = compiler.compile_strategy(node)
    assert s1.version == 1
    assert s2.version == 2


def test_compile_registers_in_registry() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode()
    compiler.compile_strategy(node)
    compiler.compile_strategy(node)
    assert compiler.registry.list_versions("stub-node-1") == [1, 2]


def test_compile_deep_copies_parameters() -> None:
    params = {"threshold": 0.5}
    node = _StubNode(parameters=params)
    compiler = DeterministicCompiler()
    strategy = compiler.compile_strategy(node)
    # Mutating original should not affect compiled strategy
    params["threshold"] = 999.0
    assert strategy.parameters["threshold"] == pytest.approx(0.5)


def test_compile_synthesises_rsi_rules() -> None:
    node = _StubNode(parameters={"rsi_oversold": 30.0, "rsi_overbought": 70.0})
    compiler = DeterministicCompiler()
    strategy = compiler.compile_strategy(node)
    rule_names = [r["name"] for r in strategy.rules]
    assert "rsi_oversold_long" in rule_names
    assert "rsi_overbought_short" in rule_names


def test_compile_uses_node_get_rules_when_present() -> None:
    custom_rules = [
        {
            "name": "custom_long",
            "direction": "long",
            "conditions": [{"field": "score", "op": ">", "value": 0.8}],
            "confidence": 0.9,
        }
    ]
    node = _StubNode(rules=custom_rules)
    compiler = DeterministicCompiler()
    strategy = compiler.compile_strategy(node)
    assert any(r["name"] == "custom_long" for r in strategy.rules)


# ---------------------------------------------------------------------------
# DeterministicStrategy.execute — rule engine
# ---------------------------------------------------------------------------


def _make_rsi_strategy(compiler: DeterministicCompiler | None = None) -> DeterministicStrategy:
    if compiler is None:
        compiler = DeterministicCompiler()
    node = _StubNode(parameters={"rsi_oversold": 30.0, "rsi_overbought": 70.0})
    return compiler.compile_strategy(node)


def test_execute_rsi_oversold_returns_long() -> None:
    strategy = _make_rsi_strategy()
    signal = strategy.execute({"rsi": 25.0})
    assert signal.direction == SignalDirection.LONG
    assert signal.confidence > 0


def test_execute_rsi_overbought_returns_short() -> None:
    strategy = _make_rsi_strategy()
    signal = strategy.execute({"rsi": 75.0})
    assert signal.direction == SignalDirection.SHORT


def test_execute_neutral_rsi_returns_flat() -> None:
    strategy = _make_rsi_strategy()
    signal = strategy.execute({"rsi": 50.0})
    assert signal.direction == SignalDirection.FLAT


def test_execute_missing_field_returns_flat() -> None:
    strategy = _make_rsi_strategy()
    signal = strategy.execute({"price": 100.0})  # no 'rsi' field
    assert signal.direction == SignalDirection.FLAT


def test_execute_dot_notation_field() -> None:
    custom_rules = [
        {
            "name": "price_close_long",
            "direction": "long",
            "conditions": [{"field": "price.close", "op": ">", "value": 100.0}],
            "confidence": 0.6,
        }
    ]
    node = _StubNode(rules=custom_rules)
    compiler = DeterministicCompiler()
    strategy = compiler.compile_strategy(node)
    signal = strategy.execute({"price": {"close": 150.0}})
    assert signal.direction == SignalDirection.LONG


def test_execute_no_rules_returns_flat() -> None:
    strategy = DeterministicStrategy(
        strategy_id="s1",
        node_id="n1",
        node_version="1.0",
        version=1,
        parameters={},
        rules=[],
    )
    signal = strategy.execute({"rsi": 20.0})
    assert signal.direction == SignalDirection.FLAT


def test_execute_first_matching_rule_wins() -> None:
    """Rules are evaluated in order; first match returns immediately."""
    rules = [
        {
            "name": "rule_a",
            "direction": "long",
            "conditions": [{"field": "x", "op": ">", "value": 0.0}],
            "confidence": 0.9,
        },
        {
            "name": "rule_b",
            "direction": "short",
            "conditions": [{"field": "x", "op": ">", "value": 0.0}],
            "confidence": 0.5,
        },
    ]
    node = _StubNode(rules=rules)
    strategy = DeterministicCompiler().compile_strategy(node)
    signal = strategy.execute({"x": 1.0})
    assert signal.direction == SignalDirection.LONG
    assert signal.metadata["rule_name"] == "rule_a"


# ---------------------------------------------------------------------------
# Checksum / integrity
# ---------------------------------------------------------------------------


def test_checksum_detects_tampering() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode(parameters={"threshold": 0.5})
    strategy = compiler.compile_strategy(node)
    assert strategy.verify_checksum()
    # Tamper
    strategy.parameters["threshold"] = 999.0
    assert not strategy.verify_checksum()


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_returns_earlier_version() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode(parameters={"threshold": 0.5})
    compiler.compile_strategy(node)
    node.parameters = {"threshold": 0.8}
    compiler.compile_strategy(node)  # version 2
    rolled_back = compiler.rollback("stub-node-1", version=1)
    assert rolled_back is not None
    assert rolled_back.version == 1
    assert rolled_back.parameters["threshold"] == pytest.approx(0.5)


def test_rollback_nonexistent_version_returns_none() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode()
    compiler.compile_strategy(node)
    result = compiler.rollback("stub-node-1", version=99)
    assert result is None


def test_get_current_returns_latest() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode()
    compiler.compile_strategy(node)
    compiler.compile_strategy(node)
    current = compiler.get_current("stub-node-1")
    assert current is not None
    assert current.version == 2


# ---------------------------------------------------------------------------
# Serialisation roundtrip
# ---------------------------------------------------------------------------


def test_strategy_serialisation_roundtrip() -> None:
    compiler = DeterministicCompiler()
    node = _StubNode(parameters={"rsi_oversold": 30.0})
    original = compiler.compile_strategy(node)
    recovered = DeterministicStrategy.from_dict(original.to_dict())
    assert recovered.strategy_id == original.strategy_id
    assert recovered.version == original.version
    assert recovered.node_id == original.node_id
    assert recovered.parameters == original.parameters
    assert recovered.checksum == original.checksum
    assert recovered.verify_checksum()
