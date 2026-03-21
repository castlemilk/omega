"""
omega.core.orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~
The coordination layer of the Omega system.

Responsibilities
----------------
- Maintain a registry of available nodes.
- Decompose a goal into sub-tasks and route each to an appropriate node.
- Collect and aggregate execution results.
- Evaluate collective performance against a GoalSpec.
- Identify underperforming nodes and trigger improvement cycles.
- Log every decision and outcome for post-hoc analysis.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from omega.core.evaluator import Evaluator, GoalSpec
from omega.core.node import Node, NodeInput, NodeOutput
from omega.core.registry import NodeRegistry

logger = logging.getLogger("omega.orchestrator")


# ---------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    task_action: str
    node_id: str
    node_name: str
    rationale: str


@dataclass
class IterationSummary:
    iteration: int
    goal: str
    routing_decisions: list[RoutingDecision] = field(default_factory=list)
    outputs: list[NodeOutput] = field(default_factory=list)
    system_metrics: dict[str, float] = field(default_factory=dict)
    improvements_triggered: list[str] = field(default_factory=list)
    score: float = 0.0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Coordinates nodes to achieve goals through iterative improvement.

    Quick-start::

        orch = Orchestrator()
        orch.register_node(my_node)
        orch.register_goal(GoalSpec("my_goal").add_metric("accuracy", "maximize"))
        history = orch.run_convergence_loop("my_goal", parameters={...}, max_iterations=5)
    """

    def __init__(self, name: str = "omega", db_path: str = ":memory:") -> None:
        self.name = name
        self.registry = NodeRegistry()
        self.evaluator = Evaluator(db_path=db_path)
        self._iteration_history: list[IterationSummary] = []
        logger.info("Orchestrator '%s' initialised", name)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(self, node: Node) -> None:
        self.registry.register(node)

    def register_goal(self, spec: GoalSpec) -> None:
        self.evaluator.register_goal(spec)

    # ------------------------------------------------------------------
    # Goal execution
    # ------------------------------------------------------------------

    def execute_goal(
        self,
        goal: str,
        parameters: dict[str, Any] | None = None,
        iteration: int = 0,
    ) -> list[NodeOutput]:
        """
        Decompose *goal* into sub-tasks and route each to the best node.

        Sub-task decomposition strategy (MVP)
        --------------------------------------
        1. The *parameters* dict may include ``"tasks"``: a list of
           ``{"action": str, "parameters": dict}`` dicts — these are
           routed directly.
        2. Otherwise we treat the entire goal as a single task whose
           ``action`` is derived from the goal string by taking the first
           word that matches a registered capability.  Failing that we
           broadcast to all nodes.

        Returns the list of NodeOutputs in task order.
        """
        parameters = parameters or {}
        tasks = parameters.get("tasks")

        if tasks is None:
            # Derive a single task from the goal
            action = self._infer_action(goal)
            tasks = [{"action": action, "parameters": parameters}]

        outputs: list[NodeOutput] = []
        routing_decisions: list[RoutingDecision] = []

        for task_spec in tasks:
            action = task_spec.get("action", "")
            task_params = task_spec.get("parameters", {})

            node = self._select_node(action)
            if node is None:
                logger.warning(
                    "No healthy node found for action '%s' — skipping", action
                )
                out = NodeOutput(
                    success=False,
                    errors=[f"No node available for action '{action}'"],
                )
                outputs.append(out)
                continue

            state = node.get_state()
            decision = RoutingDecision(
                task_action=action,
                node_id=state.node_id,
                node_name=state.name,
                rationale=f"Selected for capability '{action}'",
            )
            routing_decisions.append(decision)
            logger.debug(
                "[iter %d] Routing action='%s' → node '%s'", iteration, action, state.name
            )

            inp = NodeInput(
                action=action,
                parameters=task_params,
                context={
                    "goal": goal,
                    "iteration": iteration,
                    "orchestrator": self.name,
                },
            )

            t0 = time.perf_counter()
            output = node.execute(inp)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            if "latency_ms" not in output.metrics:
                output.metrics["latency_ms"] = elapsed_ms

            if not output.success:
                logger.warning(
                    "Node '%s' failed for action '%s': %s",
                    state.name,
                    action,
                    output.errors,
                )

            outputs.append(output)

        # log routing summary
        for d in routing_decisions:
            logger.info(
                "[iter %d] action='%s' → node='%s' (%s)",
                iteration,
                d.task_action,
                d.node_name,
                d.rationale,
            )

        return outputs

    # ------------------------------------------------------------------
    # Performance evaluation
    # ------------------------------------------------------------------

    def evaluate_performance(
        self, goal: str, outputs: list[NodeOutput], iteration: int
    ) -> dict[str, float]:
        """
        Aggregate node-level metrics from *outputs* into system-level metrics,
        record them in the evaluator, and return the dict.
        """
        if not outputs:
            return {}

        latencies = [
            o.metrics.get("latency_ms", 0.0) for o in outputs if o.success
        ]
        successes = [o for o in outputs if o.success]
        accuracy_vals = [
            o.metrics.get("accuracy", 1.0) for o in successes
        ]

        system_metrics: dict[str, float] = {
            "total_tasks": float(len(outputs)),
            "success_rate": len(successes) / len(outputs) if outputs else 0.0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "accuracy": sum(accuracy_vals) / len(accuracy_vals) if accuracy_vals else 0.0,
        }

        # Merge any extra metrics nodes pushed up via suggestions/metrics
        for out in outputs:
            for k, v in out.metrics.items():
                if k not in system_metrics:
                    system_metrics[k] = v

        node_states = self.registry.all_states()
        self.evaluator.record(goal, iteration, node_states, system_metrics)

        score = self.evaluator.score(goal, system_metrics)
        logger.info(
            "[iter %d] system metrics: %s | score=%.4f",
            iteration,
            {k: f"{v:.3f}" for k, v in system_metrics.items()},
            score,
        )
        return system_metrics

    # ------------------------------------------------------------------
    # Improvement
    # ------------------------------------------------------------------

    def improve_system(
        self, goal: str, system_metrics: dict[str, float], iteration: int
    ) -> list[str]:
        """
        Identify underperforming nodes and send them improvement feedback.

        Returns list of node names that received improvement calls.
        """
        improved: list[str] = []
        spec = self.evaluator._goal_specs.get(goal)

        for node in self.registry.all_nodes():
            state = node.get_state()
            node_metrics = state.metrics

            # Build feedback: which metrics are lagging and by how much
            feedback: dict[str, Any] = {
                "iteration": iteration,
                "goal": goal,
                "system_metrics": system_metrics,
                "node_metrics": node_metrics,
                "suggestions": [],
            }

            if spec:
                for ms in spec.metrics:
                    node_val = node_metrics.get(ms.name)
                    sys_val = system_metrics.get(ms.name)
                    if node_val is not None and sys_val is not None:
                        if ms.direction == "minimize" and node_val > sys_val * 1.2:
                            feedback["suggestions"].append(
                                f"Reduce {ms.name}: node={node_val:.3f} sys={sys_val:.3f}"
                            )
                        elif ms.direction == "maximize" and node_val < sys_val * 0.8:
                            feedback["suggestions"].append(
                                f"Improve {ms.name}: node={node_val:.3f} sys={sys_val:.3f}"
                            )

            # Always pass iteration count so nodes can decide when to kick in
            feedback["improve_latency"] = system_metrics.get("avg_latency_ms", 0) > 0.2
            feedback["improve_accuracy"] = system_metrics.get("accuracy", 1.0) < 0.95

            try:
                changed = node.improve(feedback)
                if changed:
                    improved.append(state.name)
                    logger.info(
                        "[iter %d] Node '%s' applied improvement", iteration, state.name
                    )
                else:
                    logger.debug(
                        "[iter %d] Node '%s' declined improvement", iteration, state.name
                    )
            except Exception as exc:
                logger.error("improve() raised for node '%s': %s", state.name, exc)

        return improved

    # ------------------------------------------------------------------
    # Convergence loop
    # ------------------------------------------------------------------

    def run_convergence_loop(
        self,
        goal: str,
        parameters: dict[str, Any] | None = None,
        max_iterations: int = 10,
        convergence_metric: str | None = None,
        convergence_threshold_pct: float = 1.0,
    ) -> list[IterationSummary]:
        """
        The main self-improvement loop.

        For each iteration:
          1. Execute the goal (dispatch tasks → nodes).
          2. Evaluate collective performance.
          3. Decide whether the system has converged.
          4. If not, trigger improvement cycles.
          5. Repeat.

        Returns the full iteration history.
        """
        logger.info(
            "Starting convergence loop: goal='%s' max_iter=%d", goal, max_iterations
        )
        parameters = parameters or {}
        self._iteration_history.clear()

        for i in range(max_iterations):
            logger.info("--- Iteration %d / %d ---", i, max_iterations - 1)

            outputs = self.execute_goal(goal, parameters=parameters, iteration=i)
            system_metrics = self.evaluate_performance(goal, outputs, iteration=i)
            score = self.evaluator.score(goal, system_metrics)

            summary = IterationSummary(
                iteration=i,
                goal=goal,
                outputs=outputs,
                system_metrics=system_metrics,
                score=score,
            )

            # Check convergence after the first two iterations
            if i >= 1 and convergence_metric:
                if self.evaluator.has_improved(
                    goal, convergence_metric, min_delta_pct=convergence_threshold_pct
                ):
                    improved = self.improve_system(goal, system_metrics, iteration=i)
                    summary.improvements_triggered = improved
                else:
                    logger.info(
                        "[iter %d] Convergence detected on '%s' — stopping.",
                        i,
                        convergence_metric,
                    )
                    self._iteration_history.append(summary)
                    break
            else:
                improved = self.improve_system(goal, system_metrics, iteration=i)
                summary.improvements_triggered = improved

            self._iteration_history.append(summary)

        logger.info(
            "Convergence loop complete after %d iterations",
            len(self._iteration_history),
        )
        return self._iteration_history

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def print_summary(self, goal: str) -> None:
        """Print a concise table of iteration scores to stdout."""
        print(f"\nConvergence summary — goal: '{goal}'")
        print(f"  {'Iter':>4}  {'Score':>8}  {'avg_lat_ms':>12}  {'accuracy':>10}  Improved nodes")
        print("  " + "-" * 70)
        for s in self._iteration_history:
            lat = s.system_metrics.get("avg_latency_ms", 0)
            acc = s.system_metrics.get("accuracy", 0)
            improved = ", ".join(s.improvements_triggered) if s.improvements_triggered else "-"
            print(f"  {s.iteration:>4}  {s.score:>8.4f}  {lat:>12.3f}  {acc:>10.4f}  {improved}")
        print()

    def get_evaluation_report(self, goal: str) -> str:
        return self.evaluator.report(goal)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_action(self, goal: str) -> str:
        """
        Derive a single action verb from a natural-language goal string.

        Strategy: scan the goal words against registered capabilities;
        return the first match.  Fall back to the first registered
        capability, or empty string.
        """
        capabilities = self.registry.all_capabilities()
        goal_lower = goal.lower()
        for cap in capabilities:
            if cap in goal_lower:
                return cap
        return capabilities[0] if capabilities else ""

    def _select_node(self, action: str) -> Node | None:
        """Return the healthiest node for *action*, or None."""
        candidates = self.registry.nodes_for_capability(action, healthy_only=True)
        if not candidates:
            # Fallback: any node at all
            candidates = self.registry.all_nodes()
        if not candidates:
            return None

        # Pick the node with the highest health score
        def health(n: Node) -> float:
            try:
                return n.get_state().health
            except Exception:
                return 0.0

        return max(candidates, key=health)
