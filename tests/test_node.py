"""Tests for the Node interface and data contracts."""

import pytest
from omega.core.node import NodeInput, NodeOutput, NodeState
from omega.nodes.calculator import CalculatorNode
from omega.nodes.text_analyzer import TextAnalyzerNode
from omega.nodes.web_fetcher import WebFetcherNode


# ---------------------------------------------------------------------------
# NodeInput / NodeOutput / NodeState — data contract sanity checks
# ---------------------------------------------------------------------------

class TestDataContracts:
    def test_node_input_defaults(self):
        inp = NodeInput()
        assert inp.request_id  # auto-generated
        assert inp.action == ""
        assert inp.parameters == {}
        assert inp.context == {}

    def test_node_input_custom(self):
        inp = NodeInput(action="add", parameters={"a": 1, "b": 2})
        assert inp.action == "add"
        assert inp.parameters["a"] == 1

    def test_node_output_defaults(self):
        out = NodeOutput()
        assert out.success is True
        assert out.errors == []
        assert out.suggestions == []

    def test_node_state_is_healthy(self):
        state = NodeState(
            node_id="x",
            name="Test",
            version="1.0",
            health=0.9,
            capabilities=["foo"],
            metrics={},
        )
        assert state.is_healthy()
        assert not state.is_healthy(threshold=0.95)


# ---------------------------------------------------------------------------
# CalculatorNode
# ---------------------------------------------------------------------------

class TestCalculatorNode:
    def setup_method(self):
        self.node = CalculatorNode()

    def _exec(self, action, a, b=0):
        inp = NodeInput(action=action, parameters={"a": a, "b": b})
        return self.node.execute(inp)

    def test_add(self):
        out = self._exec("add", 3, 4)
        assert out.success
        assert out.result == 7.0

    def test_subtract(self):
        out = self._exec("subtract", 10, 3)
        assert out.success
        assert out.result == 7.0

    def test_multiply(self):
        out = self._exec("multiply", 6, 7)
        assert out.success
        assert out.result == 42.0

    def test_divide(self):
        out = self._exec("divide", 10, 4)
        assert out.success
        assert out.result == 2.5

    def test_divide_by_zero(self):
        out = self._exec("divide", 10, 0)
        assert not out.success
        assert any("zero" in e.lower() for e in out.errors)

    def test_power(self):
        out = self._exec("power", 2, 10)
        assert out.success
        assert out.result == 1024.0

    def test_sqrt(self):
        out = self._exec("sqrt", 9)
        assert out.success
        assert out.result == pytest.approx(3.0)

    def test_unknown_action(self):
        out = self._exec("fly", 1, 2)
        assert not out.success
        assert out.errors

    def test_invalid_input(self):
        inp = NodeInput(action="add", parameters={"a": "not_a_number", "b": 1})
        out = self.node.execute(inp)
        assert not out.success

    def test_get_capabilities(self):
        caps = self.node.get_capabilities()
        assert "add" in caps
        assert "multiply" in caps

    def test_get_state_structure(self):
        state = self.node.get_state()
        assert state.health == 1.0
        assert "avg_latency_ms" in state.metrics
        assert "add" in state.capabilities

    def test_caching_improves_on_feedback(self):
        assert self.node._use_cache is False
        changed = self.node.improve({"improve_latency": True, "iteration": 0})
        assert changed
        assert self.node._use_cache is True
        assert self.node.version == "1.1"

    def test_cache_returns_same_result(self):
        self.node.improve({"improve_latency": True, "iteration": 0})
        out1 = self._exec("add", 5, 3)
        out2 = self._exec("add", 5, 3)
        assert out1.result == out2.result
        # Second call should be a cache hit
        assert self.node._cache_hits == 1

    def test_evaluate_returns_metrics(self):
        self._exec("add", 1, 2)
        metrics = self.node.evaluate()
        assert "avg_latency_ms" in metrics
        assert metrics["execution_count"] == 1.0

    def test_describe_returns_string(self):
        desc = self.node.describe()
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_request_id_propagated(self):
        inp = NodeInput(action="add", parameters={"a": 1, "b": 1})
        out = self.node.execute(inp)
        assert out.request_id == inp.request_id


# ---------------------------------------------------------------------------
# TextAnalyzerNode
# ---------------------------------------------------------------------------

class TestTextAnalyzerNode:
    def setup_method(self):
        self.node = TextAnalyzerNode()

    def test_word_count(self):
        inp = NodeInput(action="word_count", parameters={"text": "hello world foo"})
        out = self.node.execute(inp)
        assert out.success
        assert out.result == 3

    def test_analyze_basic(self):
        inp = NodeInput(action="analyze", parameters={"text": "One two three."})
        out = self.node.execute(inp)
        assert out.success
        assert out.result["word_count"] == 3

    def test_analyze_adds_extended_after_improve(self):
        self.node.improve({})
        inp = NodeInput(action="analyze", parameters={"text": "The quick brown fox jumps"})
        out = self.node.execute(inp)
        assert "avg_word_length" in out.result
        assert "lexical_diversity" in out.result

    def test_sentiment_unlocked_after_second_improve(self):
        self.node.improve({})   # v1.1
        self.node.improve({})   # v1.2
        inp = NodeInput(action="sentiment", parameters={"text": "great wonderful happy"})
        out = self.node.execute(inp)
        assert out.success
        assert out.result > 0.0   # positive sentiment

    def test_negative_sentiment(self):
        self.node.improve({})
        self.node.improve({})
        inp = NodeInput(action="sentiment", parameters={"text": "bad terrible horrible"})
        out = self.node.execute(inp)
        assert out.success
        assert out.result < 0.0

    def test_capability_grows_with_improvement(self):
        caps_v1 = set(self.node.get_capabilities())
        self.node.improve({})
        caps_v11 = set(self.node.get_capabilities())
        assert caps_v11 > caps_v1

    def test_unknown_action_fails(self):
        inp = NodeInput(action="fly", parameters={"text": "hi"})
        out = self.node.execute(inp)
        assert not out.success

    def test_empty_text(self):
        inp = NodeInput(action="word_count", parameters={"text": ""})
        out = self.node.execute(inp)
        assert out.success
        assert out.result == 0


# ---------------------------------------------------------------------------
# WebFetcherNode (dry_run mode — no real network)
# ---------------------------------------------------------------------------

class TestWebFetcherNode:
    def setup_method(self):
        self.node = WebFetcherNode(dry_run=True)

    def test_fetch_success(self):
        inp = NodeInput(action="fetch", parameters={"url": "https://example.com"})
        out = self.node.execute(inp)
        assert out.success
        assert "stub response" in out.result

    def test_missing_url_fails(self):
        inp = NodeInput(action="fetch", parameters={})
        out = self.node.execute(inp)
        assert not out.success

    def test_unknown_action_fails(self):
        inp = NodeInput(action="delete", parameters={"url": "https://x.com"})
        out = self.node.execute(inp)
        assert not out.success

    def test_caching_after_improve(self):
        self.node.improve({"improve_latency": True, "iteration": 0})
        assert self.node._use_cache is True
        inp = NodeInput(action="fetch", parameters={"url": "https://example.com"})
        out1 = self.node.execute(inp)
        out2 = self.node.execute(inp)
        assert out1.success and out2.success
        assert self.node._cache_hits == 1

    def test_get_state(self):
        state = self.node.get_state()
        assert "fetch" in state.capabilities
        assert state.health == 1.0
