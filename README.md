# Project Omega

**Self-improving node orchestration framework.**

Omega validates a core hypothesis: can we define node contracts, compose them via an orchestrator, evaluate collective performance, and improve individual nodes — automatically, iteratively, in a tight feedback loop?

---

## Quick Start

```bash
cd omega
pip install -e ".[dev]"

# Run the demo (watch the calculator node improve over 5 iterations)
python -m omega.examples.calculator_improvement

# Run all tests
pytest
```

No external dependencies.  Stdlib only (`sqlite3`, `urllib`, `abc`, `dataclasses`, `uuid`, `logging`).

---

## The Hypothesis

```
Define contracts → Compose nodes → Evaluate collectively → Improve individually → Repeat
```

Each iteration the orchestrator:
1. Routes tasks to nodes based on declared capabilities.
2. Measures collective performance (latency, accuracy, success rate).
3. Sends improvement feedback to each node.
4. Nodes optionally change their behaviour and bump their version.
5. The loop stops when performance converges or `max_iterations` is reached.

---

## Architecture

```
omega/
├── core/
│   ├── node.py          # Node / NodeInput / NodeOutput / NodeState contracts
│   ├── registry.py      # Capability-indexed node registry
│   ├── evaluator.py     # SQLite-backed metric tracking + reports
│   └── orchestrator.py  # Routing, evaluation, improvement loop
├── nodes/
│   ├── calculator.py    # Arithmetic node (caching improvement)
│   ├── web_fetcher.py   # HTTP fetch node (cache + retry improvement)
│   └── text_analyzer.py # Text analysis node (capability-expansion improvement)
└── examples/
    └── calculator_improvement.py   # Runnable end-to-end demo
```

Full design: [`docs/architecture.md`](docs/architecture.md)

---

## Adding a Node

1. Subclass `omega.core.Node`.
2. Implement the six abstract methods (`get_state`, `get_capabilities`, `describe`, `execute`, `evaluate`, `improve`).
3. Register with the orchestrator.

```python
from omega.core import Node, NodeInput, NodeOutput, NodeState, Orchestrator
import uuid

class MyNode(Node):
    def __init__(self):
        self._id = str(uuid.uuid4())

    def get_state(self):
        return NodeState(
            node_id=self._id, name="MyNode", version="1.0",
            health=1.0, capabilities=["my_action"], metrics={},
        )

    def get_capabilities(self):
        return ["my_action"]

    def describe(self):
        return "Does my_action on the input."

    def execute(self, input: NodeInput) -> NodeOutput:
        return NodeOutput(request_id=input.request_id, result="done")

    def evaluate(self):
        return {"accuracy": 1.0}

    def improve(self, feedback):
        return False  # nothing to change yet

orch = Orchestrator()
orch.register_node(MyNode())
```

---

## What the Demo Shows

Running `python -m omega.examples.calculator_improvement`:

| Iteration | avg latency | cache | node version |
|-----------|-------------|-------|--------------|
| 0         | ~0.05 ms    | off   | 1.0          |
| 1         | ~0.05 ms    | off   | 1.0          |
| 2         | ↓ ~0.001 ms | **on** | **1.1**     |
| 3         | ↓ lower     | on    | **1.2**      |

The orchestrator detects high average latency on iteration 1, passes `improve_latency=True` feedback, and the node self-upgrades by enabling its result cache.  Repeated problems (50 unique × 4 repetitions = 200 tasks) then hit the cache, collapsing latency by 10–50×.

---

## Running Tests

```bash
pytest                        # all tests
pytest tests/test_node.py     # node contracts only
pytest -v --tb=short          # verbose with short tracebacks
pytest --cov=omega            # with coverage (requires pytest-cov)
```
