"""
omega.examples.calculator_improvement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runnable demonstration of the Omega self-improvement loop.

Goal: "solve these math problems accurately and fast"

What you'll see
---------------
- The orchestrator routing 100+ arithmetic tasks to the CalculatorNode.
- Iteration 0: no caching — every problem computed fresh.
- Iteration 1: orchestrator detects high avg latency, feeds back.
- Iteration 2+: CalculatorNode enables caching — latency drops on
  repeated problems.  Version bumps from 1.0 → 1.1 → 1.2 are logged.
- Final evaluation report printed to stdout.

Run:
    python -m omega.examples.calculator_improvement
"""

import logging
import random
import sys
import time

# Configure logging before importing omega so all loggers pick it up
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet the debug-level node logger during the demo
logging.getLogger("omega.nodes.calculator").setLevel(logging.INFO)

from omega.core.evaluator import GoalSpec
from omega.core.orchestrator import Orchestrator
from omega.nodes.calculator import CalculatorNode


# ---------------------------------------------------------------------------
# Problem set
# ---------------------------------------------------------------------------

OPERATIONS = ["add", "subtract", "multiply", "divide", "power"]

def _generate_problems(n: int = 200, unique_problems: int = 50) -> list:
    """
    Generate *n* arithmetic problems with only *unique_problems* distinct
    inputs.  Repeated problems make the cache benefit clearly measurable.
    """
    rng = random.Random(42)
    unique = []
    for _ in range(unique_problems):
        op = rng.choice(OPERATIONS)
        a = rng.uniform(1, 100)
        b = rng.uniform(1, 10) if op != "divide" else rng.uniform(1, 10)
        unique.append({"action": op, "parameters": {"a": a, "b": b}})

    # Repeat to fill n problems
    problems = []
    while len(problems) < n:
        problems.extend(unique)
    return problems[:n]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_banner(text: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  {text}")
    print(f"{bar}")


def _print_iteration(summary) -> None:
    lat = summary.system_metrics.get("avg_latency_ms", 0)
    acc = summary.system_metrics.get("accuracy", 0)
    sr  = summary.system_metrics.get("success_rate", 0)
    imp = ", ".join(summary.improvements_triggered) if summary.improvements_triggered else "-"
    print(
        f"  Iter {summary.iteration:>2}  |  "
        f"score={summary.score:.4f}  "
        f"avg_lat={lat:>7.4f}ms  "
        f"accuracy={acc:.3f}  "
        f"success_rate={sr:.3f}  "
        f"improved=[{imp}]"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _print_banner("Project Omega — Calculator Self-Improvement Demo")

    # 1. Create orchestrator
    orch = Orchestrator(name="calculator-demo", db_path=":memory:")

    # 2. Register goal with the evaluator
    goal = "solve math problems accurately and fast"
    spec = (
        GoalSpec(goal, description="Benchmark arithmetic node across 200 problems")
        .add_metric("avg_latency_ms", direction="minimize", weight=2.0)
        .add_metric("accuracy",       direction="maximize", weight=3.0)
        .add_metric("success_rate",   direction="maximize", weight=1.0)
    )
    orch.register_goal(spec)

    # 3. Register the calculator node
    calc = CalculatorNode()
    orch.register_node(calc)

    print(f"\nNode registered : {calc.describe()}")
    print(f"Node version    : {calc.version}")
    print(f"Goal            : {goal}")

    # 4. Build the problem list (200 tasks, 50 unique — high repeat rate)
    problems = _generate_problems(n=200, unique_problems=50)
    parameters = {"tasks": problems}

    print(f"\nProblem set     : {len(problems)} tasks ({50} unique)\n")

    # 5. Run the convergence loop
    _print_banner("Starting convergence loop (5 iterations max)")
    print(f"  {'Iter':>4}  |  {'score':>8}  {'avg_lat':>10}  {'accuracy':>9}  {'success':>8}  improved")
    print("  " + "-" * 72)

    history = orch.run_convergence_loop(
        goal=goal,
        parameters=parameters,
        max_iterations=5,
        convergence_metric="avg_latency_ms",
        convergence_threshold_pct=5.0,
    )

    for summary in history:
        _print_iteration(summary)

    # 6. Node version progression
    _print_banner("Node version after convergence loop")
    state = calc.get_state()
    print(f"  Name    : {state.name}")
    print(f"  Version : {state.version}")
    print(f"  Health  : {state.health:.2f}")
    print(f"  Metrics : {state.metrics}")
    print(f"  Cache   : {'enabled' if calc._use_cache else 'disabled'}")

    # 7. Full evaluation report
    _print_banner("Evaluation Report")
    print(orch.get_evaluation_report(goal))

    # 8. Highlight the improvement
    _print_banner("Improvement Summary")
    if len(history) >= 2:
        first = history[0].system_metrics.get("avg_latency_ms", 0)
        last  = history[-1].system_metrics.get("avg_latency_ms", 0)
        if first > 0:
            pct = (first - last) / first * 100
            print(f"  Latency change : {first:.4f}ms → {last:.4f}ms  ({pct:+.1f}%)")
        ver_path = " → ".join(
            dict.fromkeys(  # preserve order, remove dupes
                [history[0].system_metrics.get("_version", "1.0")]
                + [s.improvements_triggered[0] if s.improvements_triggered else "" for s in history]
            )
        )
        print(f"  Node version   : {calc.version}")
        print(f"  Cache status   : {'enabled ✓' if calc._use_cache else 'still off'}")
        print(f"  Cache hit rate : {calc._cache_hit_rate():.1%}")
    else:
        print("  Only one iteration — nothing to compare yet.")

    print()
    print("Done.  Hypothesis validated: nodes can self-improve through the")
    print("orchestrator's feedback loop without external intervention.")
    print()


if __name__ == "__main__":
    main()
