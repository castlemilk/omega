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

## Feature-flag defaults (`VictoriaFeatures`)

**A flag's default is what an arm gets when it forgets. Default to the safe,
inert, opt-in value — never to the clever one.**

`omega/nodes/victoria/features.py` defines the eval's feature surface. Every
walk-forward grid arm passes a `--features` JSON string, and any key the string
omits silently inherits the dataclass default. That inheritance is invisible in
the run label, in the artifacts, and in the log entry — so a default that
*enables* a mechanism makes every arm that forgot the key a different experiment
than its name says.

This is not hypothetical. V273's lookahead audit flagged `ic_seed_weighting` and
`per_regime_ic_weighting` as **defaults-ON**: the seeded ICs they load are
win-rate priors derived from completed training runs over the same corpus every
walk-forward window is drawn from, and they weight the conviction filter. V274
audited all 32 cells behind the standing baseline (crisis +$599 / trend +$2,997 /
recent +$30) and **cleared** it — every cell recorded `"ic_seed_weighting": false`
explicitly, and re-running drifted 0.000000. But the baseline was clean by
**convention, not by construction**: correctness rested on each grid author
remembering to type `false`. **V275 flipped `ic_seed_weighting` to default
`False`** so IC weighting is something an arm opts into, and pinned it with
`tests/test_features_defaults.py`.

Rules for adding or changing a default:

1. **New flags ship `False` / inert / zero.** The default must be
   byte-identical to not having the feature. Say so in the docstring, as the
   existing V228–V229 flags do (*"Default OFF ⇒ byte-identical to the V228
   stack"*).
2. **Before changing an existing default, audit who inherits it.** Scan every
   `--features` string in `scripts/*.sh` and count the arms that omit the key.
   If any *live* arm inherits the old value, changing the default silently
   redefines what that arm measured — pin the key explicitly into those arms
   first (a no-op edit), and only then flip. V275 found exactly this for
   `per_regime_ic_weighting`: 7 IC-ON arms inherit its `True` default, including
   V274's own `ARM_ON`, so it was deliberately **left at `True`** and the flip
   sequenced as a follow-up. The audit belongs in the pre-registration, before
   the change.
3. **Pin every audited default in `tests/test_features_defaults.py`** — in both
   directions. A flag deliberately held at a non-inert value gets an assertion
   too, with the reason in the docstring, so a future flip has to read it.
4. **Grid scripts stay explicit anyway.** Setting the key you depend on is still
   correct even when the default agrees with you; the default is the backstop,
   not the contract.
