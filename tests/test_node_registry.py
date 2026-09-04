"""
Tests for omega.core.node_registry
"""

from __future__ import annotations

import pytest

from omega.core.node_registry import (
    NodeTypeRegistry,
    NodeTypeSpec,
    Port,
    get_registry,
    node_type,
    reset_registry,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Reset the global registry before each test."""
    reset_registry()
    yield
    reset_registry()


# ---------------------------------------------------------------------------
# Port compatibility
# ---------------------------------------------------------------------------


class TestPortCompatibility:
    def test_exact_dtype_match(self):
        src = Port("out", dtype="market_data")
        dst = Port("in", dtype="market_data")
        assert src.is_compatible_with(dst)

    def test_dtype_mismatch(self):
        src = Port("out", dtype="market_data")
        dst = Port("in", dtype="signal_value")
        assert not src.is_compatible_with(dst)

    def test_any_source_accepts_all(self):
        src = Port("out", dtype="any")
        dst = Port("in", dtype="signal_value")
        assert src.is_compatible_with(dst)

    def test_any_destination_accepts_all(self):
        src = Port("out", dtype="market_data")
        dst = Port("in", dtype="any")
        assert src.is_compatible_with(dst)

    def test_both_any(self):
        src = Port("out", dtype="any")
        dst = Port("in", dtype="any")
        assert src.is_compatible_with(dst)


# ---------------------------------------------------------------------------
# NodeTypeRegistry
# ---------------------------------------------------------------------------


class TestNodeTypeRegistry:
    def _make_registry_with_types(self):
        reg = NodeTypeRegistry()

        class Provider:
            pass

        class Signal:
            pass

        class Strategy:
            pass

        reg.register_type(NodeTypeSpec(
            name="data_provider",
            cls=Provider,
            inputs=[],
            outputs=[Port("market_data", dtype="market_data")],
            description="Provides market data",
        ))
        reg.register_type(NodeTypeSpec(
            name="signal_generator",
            cls=Signal,
            inputs=[Port("market_data", dtype="market_data")],
            outputs=[Port("signal_value", dtype="signal_value"),
                     Port("confidence", dtype="float")],
            description="Generates signals",
        ))
        reg.register_type(NodeTypeSpec(
            name="strategy",
            cls=Strategy,
            inputs=[Port("signal_value", dtype="signal_value"),
                    Port("confidence", dtype="float")],
            outputs=[Port("trade_decision", dtype="trade_decision")],
            description="Strategy",
        ))
        return reg

    def test_register_and_get(self):
        reg = self._make_registry_with_types()
        spec = reg.get_type("data_provider")
        assert spec is not None
        assert spec.name == "data_provider"

    def test_get_unknown_type(self):
        reg = NodeTypeRegistry()
        assert reg.get_type("nonexistent") is None

    def test_known_type_names(self):
        reg = self._make_registry_with_types()
        names = reg.known_type_names()
        assert "data_provider" in names
        assert "signal_generator" in names

    def test_valid_connection(self):
        reg = self._make_registry_with_types()
        errors = reg.validate_connection(
            "data_provider", "market_data",
            "signal_generator", "market_data",
        )
        assert errors == []

    def test_type_mismatch_connection(self):
        reg = self._make_registry_with_types()
        errors = reg.validate_connection(
            "data_provider", "market_data",
            "strategy", "signal_value",
        )
        assert len(errors) == 1
        assert "mismatch" in errors[0].lower()

    def test_unknown_source_type(self):
        reg = self._make_registry_with_types()
        errors = reg.validate_connection(
            "unknown_type", "out",
            "signal_generator", "market_data",
        )
        assert any("Unknown source" in e for e in errors)

    def test_unknown_source_port(self):
        reg = self._make_registry_with_types()
        errors = reg.validate_connection(
            "data_provider", "no_such_port",
            "signal_generator", "market_data",
        )
        assert any("no output port" in e for e in errors)

    def test_wildcard_connection_skips_validation(self):
        reg = self._make_registry_with_types()
        # Wildcard on unknown type should produce an error about the type
        errors = reg.validate_connection(
            "data_provider", "*",
            "signal_generator", "market_data",
        )
        # market_data port on data_provider is compatible with market_data on signal_generator
        assert errors == []


# ---------------------------------------------------------------------------
# @node_type decorator
# ---------------------------------------------------------------------------


class TestNodeTypeDecorator:
    def test_decorator_registers_class(self):
        @node_type(
            "test_emitter",
            inputs=[],
            outputs=[Port("value", dtype="float")],
            description="Test emitter",
        )
        class MyEmitter:
            pass

        reg = get_registry()
        spec = reg.get_type("test_emitter")
        assert spec is not None
        assert spec.cls is MyEmitter

    def test_decorator_attaches_spec_to_class(self):
        @node_type(
            "test_receiver",
            inputs=[Port("value", dtype="float")],
            outputs=[],
        )
        class MyReceiver:
            pass

        assert hasattr(MyReceiver, "_node_type_spec")
        assert MyReceiver._node_type_spec.name == "test_receiver"

    def test_decorator_preserves_class(self):
        @node_type("test_passthrough", inputs=[], outputs=[])
        class MyClass:
            def hello(self):
                return "world"

        obj = MyClass()
        assert obj.hello() == "world"


# ---------------------------------------------------------------------------
# Project-level connection validation
# ---------------------------------------------------------------------------


class TestProjectConnectionValidation:
    def _reg(self):
        reg = NodeTypeRegistry()

        class P:
            pass

        class S:
            pass

        class T:
            pass

        reg.register_type(NodeTypeSpec(
            name="data_provider", cls=P, inputs=[],
            outputs=[Port("market_data", dtype="market_data")],
        ))
        reg.register_type(NodeTypeSpec(
            name="signal_generator", cls=S,
            inputs=[Port("market_data", dtype="market_data")],
            outputs=[Port("signal_value", dtype="signal_value"),
                     Port("confidence", dtype="float")],
        ))
        reg.register_type(NodeTypeSpec(
            name="strategy", cls=T,
            inputs=[Port("signal_value", dtype="signal_value"),
                    Port("confidence", dtype="float", required=False)],
            outputs=[Port("trade_decision", dtype="trade_decision")],
        ))
        return reg

    def test_valid_project_connections(self):
        reg = self._reg()
        node_defs = [
            {"type": "data_provider", "name": "feed", "inputs": []},
            {"type": "signal_generator", "name": "signals", "inputs": ["feed.market_data"]},
            {"type": "strategy", "name": "strat", "inputs": ["signals.signal_value"]},
        ]
        errors = reg.validate_project_connections(node_defs)
        assert errors == [], errors

    def test_missing_source_node(self):
        reg = self._reg()
        node_defs = [
            {"type": "signal_generator", "name": "signals", "inputs": ["ghost.market_data"]},
        ]
        errors = reg.validate_project_connections(node_defs)
        assert any("ghost" in e for e in errors)

    def test_malformed_connection_string(self):
        reg = self._reg()
        node_defs = [
            {"type": "data_provider", "name": "feed", "inputs": []},
            {"type": "signal_generator", "name": "signals", "inputs": ["feed_no_dot"]},
        ]
        errors = reg.validate_project_connections(node_defs)
        assert any("malformed" in e for e in errors)

    def test_wildcard_connection(self):
        reg = self._reg()
        node_defs = [
            {"type": "data_provider", "name": "feed", "inputs": []},
            {"type": "signal_generator", "name": "signals", "inputs": ["feed.*"]},
        ]
        errors = reg.validate_project_connections(node_defs)
        # wildcard from data_provider — should pass because type is known
        assert errors == [], errors


# ---------------------------------------------------------------------------
# Built-in types are registered at import
# ---------------------------------------------------------------------------


class TestBuiltinTypes:
    def test_builtin_types_registered(self):
        # Importing the module registers the built-in types
        from omega.core import node_registry  # noqa: F401

        reg = get_registry()
        for name in [
            "data_provider",
            "signal_generator",
            "regime_detector",
            "strategy",
            "executor",
            "intelligence",
            "risk_manager",
        ]:
            assert reg.get_type(name) is not None, f"Built-in type '{name}' not registered"
