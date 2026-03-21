"""Tests for the Orchestrator coordination layer."""

import uuid

import pytest

from omega.core.evaluator import GoalSpec
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.orchestrator import Orchestrator
from omega.nodes.calculator import CalculatorNode
from omega.nodes.text_analyzer import TextAnalyzerNode

# ---------------------------------------------------------------------------
# Minimal stub node for isolation tests
# ---------------------------------------------------------------------------

class EchoNode(Node):
    """Returns its input parameters as result.  Always healthy."""

    def __init__(self, name="echo", capabilities=None):
        self._id = str(uuid.uuid4())
        self._name = name
        self._caps = capabilities or ["echo"]
        self._exec_count = 0

    def get_state(self):
        return NodeState(
            node_id=self._id,
            name=self._name,
            version="1.0",
            health=1.0,
            capabilities=self._caps,
            metrics={"avg_latency_ms": 0.0, "accuracy": 1.0},
        )

    def get_capabilities(self):
        return self._caps

    def describe(self):
        return f"Echo node '{self._name}'"

    def execute(self, input: NodeInput) -> NodeOutput:
        self._exec_count += 1
        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=input.parameters,
            metrics={"latency_ms": 0.1, "accuracy": 1.0},
        )

    def evaluate(self):
        return {"accuracy": 1.0, "avg_latency_ms": 0.0}

    def improve(self, feedback):
        return False


# ---------------------------------------------------------------------------
# Orchestrator construction
# ---------------------------------------------------------------------------

class TestOrchestratorInit:
    def test_empty_registry(self):
        orch = Orchestrator()
        assert len(orch.registry) == 0

    def test_register_node(self):
        orch = Orchestrator()
        orch.register_node(EchoNode())
        assert len(orch.registry) == 1

    def test_register_multiple_nodes(self):
        orch = Orchestrator()
        orch.register_node(EchoNode("a", ["echo"]))
        orch.register_node(EchoNode("b", ["transform"]))
        assert len(orch.registry) == 2


# ---------------------------------------------------------------------------
# Goal execution
# ---------------------------------------------------------------------------

class TestExecuteGoal:
    def setup_method(self):
        self.orch = Orchestrator()
        self.orch.register_node(EchoNode("echo", ["echo", "respond"]))

    def test_execute_single_task(self):
        outputs = self.orch.execute_goal(
            "respond to request",
            parameters={"tasks": [{"action": "echo", "parameters": {"x": 42}}]},
        )
        assert len(outputs) == 1
        assert outputs[0].success
        assert outputs[0].result["x"] == 42

    def test_execute_multiple_tasks(self):
        tasks = [
            {"action": "echo", "parameters": {"n": i}}
            for i in range(5)
        ]
        outputs = self.orch.execute_goal("echo", parameters={"tasks": tasks})
        assert len(outputs) == 5
        assert all(o.success for o in outputs)

    def test_no_node_for_action(self):
        # An empty orchestrator (no nodes registered) cannot route any action
        empty_orch = Orchestrator()
        outputs = empty_orch.execute_goal(
            "unknown",
            parameters={"tasks": [{"action": "fly", "parameters": {}}]},
        )
        assert len(outputs) == 1
        assert not outputs[0].success

    def test_infer_action_from_goal(self):
        """If no tasks provided, action is inferred from goal words."""
        orch = Orchestrator()
        orch.register_node(EchoNode("echo", ["add"]))
        outputs = orch.execute_goal("add numbers together", parameters={"a": 1, "b": 2})
        assert len(outputs) == 1
        assert outputs[0].success


# ---------------------------------------------------------------------------
# Performance evaluation
# ---------------------------------------------------------------------------

class TestEvaluatePerformance:
    def setup_method(self):
        self.orch = Orchestrator()
        self.orch.register_node(EchoNode())
        spec = GoalSpec("test_goal").add_metric("accuracy", "maximize")
        self.orch.register_goal(spec)

    def test_returns_dict_with_expected_keys(self):
        from omega.core.node import NodeOutput
        outputs = [
            NodeOutput(success=True, metrics={"latency_ms": 1.0, "accuracy": 1.0}),
            NodeOutput(success=True, metrics={"latency_ms": 2.0, "accuracy": 0.9}),
        ]
        metrics = self.orch.evaluate_performance("test_goal", outputs, iteration=0)
        assert "avg_latency_ms" in metrics
        assert "success_rate" in metrics
        assert "accuracy" in metrics

    def test_success_rate_calculation(self):
        from omega.core.node import NodeOutput
        outputs = [
            NodeOutput(success=True, metrics={"latency_ms": 1.0}),
            NodeOutput(success=False, errors=["oops"], metrics={}),
        ]
        metrics = self.orch.evaluate_performance("test_goal", outputs, iteration=0)
        assert metrics["success_rate"] == pytest.approx(0.5)

    def test_empty_outputs(self):
        metrics = self.orch.evaluate_performance("test_goal", [], iteration=0)
        assert metrics == {}


# ---------------------------------------------------------------------------
# Improvement cycle
# ---------------------------------------------------------------------------

class TestImproveSystem:
    def test_improve_called_on_nodes(self):
        improved_calls = []

        class TrackingNode(EchoNode):
            def improve(self, feedback):
                improved_calls.append(feedback)
                return True

        orch = Orchestrator()
        orch.register_node(TrackingNode())
        spec = GoalSpec("g").add_metric("accuracy", "maximize")
        orch.register_goal(spec)

        orch.improve_system("g", {"accuracy": 0.5, "avg_latency_ms": 5.0}, iteration=1)
        assert len(improved_calls) == 1
        assert "iteration" in improved_calls[0]


# ---------------------------------------------------------------------------
# Convergence loop — integration with CalculatorNode
# ---------------------------------------------------------------------------

class TestConvergenceLoop:
    def test_runs_and_returns_history(self):
        orch = Orchestrator()
        calc = CalculatorNode()
        orch.register_node(calc)

        spec = (
            GoalSpec("math")
            .add_metric("avg_latency_ms", "minimize", weight=2.0)
            .add_metric("accuracy", "maximize", weight=3.0)
        )
        orch.register_goal(spec)

        problems = [
            {"action": "add", "parameters": {"a": i, "b": i + 1}}
            for i in range(20)
        ] * 3   # repeat to make cache useful

        history = orch.run_convergence_loop(
            "math",
            parameters={"tasks": problems},
            max_iterations=3,
        )
        assert len(history) >= 1
        assert all(s.score >= 0 for s in history)

    def test_node_improves_across_iterations(self):
        orch = Orchestrator()
        calc = CalculatorNode()
        orch.register_node(calc)

        spec = GoalSpec("math").add_metric("avg_latency_ms", "minimize")
        orch.register_goal(spec)

        problems = [
            {"action": "multiply", "parameters": {"a": i % 10, "b": i % 5}}
            for i in range(40)
        ]

        orch.run_convergence_loop(
            "math",
            parameters={"tasks": problems},
            max_iterations=3,
        )
        # After 3 iterations of feedback the calculator should have enabled caching
        assert calc._use_cache is True

    def test_multi_node_routing(self):
        """Both calculator and text_analyzer nodes can coexist."""
        orch = Orchestrator()
        orch.register_node(CalculatorNode())
        orch.register_node(TextAnalyzerNode())

        spec = GoalSpec("mixed").add_metric("accuracy", "maximize")
        orch.register_goal(spec)

        tasks = [
            {"action": "add",        "parameters": {"a": 1, "b": 2}},
            {"action": "word_count", "parameters": {"text": "hello world"}},
            {"action": "multiply",   "parameters": {"a": 3, "b": 4}},
            {"action": "analyze",    "parameters": {"text": "one two three"}},
        ]

        outputs = orch.execute_goal("mixed", parameters={"tasks": tasks})
        assert len(outputs) == 4
        successes = [o for o in outputs if o.success]
        assert len(successes) >= 3   # most should succeed
