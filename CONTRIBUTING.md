# Contributing to Omega

## Type Safety Rules

All action names, step types, and capabilities **must** use the enums in
`omega/core/actions.py` — never raw string literals.

### Never do this

```python
# BAD — raw string literals scatter the contract
inp = NodeInput(action="fetch_market_data", ...)
capabilities = ["compute_signals", "construct_portfolio"]
if inp.action == "debategate":
```

### Always do this

```python
# GOOD — typed, greppable, compiler-checkable
from omega.core.actions import NodeAction

inp = NodeInput(action=NodeAction.FETCH_MARKET_DATA.value, ...)
capabilities = [NodeAction.COMPUTE_SIGNALS.value, NodeAction.CONSTRUCT_PORTFOLIO.value]
if inp.action == NodeAction.DEBATE_GATE.value:
```

### Rules

1. **Never** use raw string literals for action names, step types, or capabilities.
2. **Always** import from `omega.core.actions` (`NodeAction`, `StepType`, `resolve_action`).
3. **New actions**: add to `NodeAction` enum first, then use the enum value everywhere.
4. **New step types**: add to `StepType` and `STEP_TO_ACTION` mapping first.
5. **Proto types** are generated from `.proto` files: run `make proto-python` after changes.
6. **Contract tests** in `tests/test_action_contracts.py` verify every step name has a handler — run them before merging.
7. **Python bridge types** come from `gen/python/omega/v1.py` (betterproto-generated) — never hand-write proto message classes.

### Dispatch path (Go → Python)

```
Go orchestrator → ExecuteStepRequest.node_type (StepType string)
    → resolve_action(node_type) → NodeAction
    → NodeInput(action=NodeAction.XXX.value)
    → Node.execute(inp)
```

`resolve_action` in `omega/core/actions.py` is the single translation point.
If a node_type is unknown, `resolve_action` returns `None` and the server
returns an error — do not add ad-hoc `.lower()` fallbacks.

### Platform vs Project

- **Omega is the PLATFORM** — `omega/core/`, `omega/bridge/`, `omega/nodes/` base classes are project-agnostic
- **Victoria, Polymarket are PROJECTS** — project-specific code lives in `omega/nodes/{project}/`
- Never import project code from platform code
- Projects register via YAML in `projects/`

### Legacy aliases

A small set of legacy aliases (`"riskcheck"`, `"signalresearch"`,
`"riskmanagement"`, etc.) remain in `victoria_node.py`'s dispatch for
backwards-compatibility with older Go configs. These are the **only**
permitted raw strings and must not be expanded. Prefer adding a `StepType`
entry and `STEP_TO_ACTION` mapping for any new routing needs.
