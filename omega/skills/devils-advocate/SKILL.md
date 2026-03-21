# Devil's Advocate Skill

Think adversarially about system design. Challenge every assumption, find failure modes, and produce a structured critique before committing to an approach.

## When to Invoke

- Before committing a new subsystem design
- After any improvement cycle that changes node behaviour
- When a new architectural primitive is proposed (EWC, Nash welfare, VCG, etc.)
- When "this will converge" or "this is bounded" is stated without proof

## Adversarial Thinking Playbook

### 1. Invert the Success Assumption
For every claim "X ensures Y", ask: "Under what conditions does X *not* ensure Y?"
- "EWC protects against catastrophic forgetting" → what if the task boundary is misidentified?
- "Nash welfare maximises fairness" → what if one agent has unbounded or non-comparable utility?
- "VerificationNode catches regressions" → what if the regression is in a metric not being checked?

### 2. Find the Hidden O(n) / O(t) Growth
Every abstraction has a cost. Ask: "What grows unboundedly as this system runs longer?"
- BOCPD run-length distribution: O(t) memory
- ChallengeRegistry without pruning: grows indefinitely
- EpisodicStore without aggressive pruning: unbounded disk use
- SemanticMemory without confidence decay: stale beliefs never expire

### 3. The Rational Agent Assumption
LLMs are not rational agents. Any mechanism that assumes truthful reporting,
utility maximisation, or stable preferences breaks when applied to LLM nodes:
- VCG incentive compatibility requires truthful bidding — LLMs don't bid
- Nash equilibrium requires rational responses to rational opponents
- Constitutional constraints rely on the constrained node cooperating

### 4. The Grounding Problem
Any system that writes LLM-generated content back to persistent memory must
verify it against ground truth. Ungrounded beliefs compound:
- IterDRAG: retrieval → generation → memory write with no verification step
- SemanticConsolidation: if an episodic memory was hallucinated, the semantic
  pattern extracted from it is also hallucinated, with higher confidence

### 5. Circular Dependency Hunt
Draw the dependency graph. Look for cycles:
- Does the alignment layer check nodes that implement alignment checks?
- Does the registry depend on nodes that depend on the registry?
- Does the improvement loop use the evaluator, and does the evaluator affect what gets improved?

### 6. Regression in Disguise
Improvements that raise one metric often lower another silently:
- Adding more indicators → higher apparent signal coverage → lower out-of-sample Sharpe
- Improving latency with caching → higher hit rates → stale data in volatile regimes
- Increasing EWC protection → less catastrophic forgetting → less beneficial plasticity

### 7. YAGNI Check
For every abstraction layer, ask: "What is the simplest thing that achieves 80% of this benefit?"
- 5 alignment layers vs. 1 constitutional constraint check
- Full VCG mechanism vs. simple priority queue
- BOCPD vs. a 50-day rolling z-score for regime detection

## Challenge Severity Guide

| Severity | Meaning | Action |
|----------|---------|--------|
| CRITICAL | Will cause system failure, data corruption, or mathematical unsoundness | Block deployment; must resolve first |
| HIGH | Will cause silent degradation or incorrect results in production | Require resolution before next release |
| MEDIUM | Suboptimal behaviour; workarounds exist | Track and schedule fix |
| LOW | Stylistic or future-proofing concern | Log and accept |

## Using the Code

```python
from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity
from omega.core.verification_gates import VerificationGateSystem, RegressionGate
from omega.nodes.devils_advocate import DevilsAdvocateNode
from omega.core.node import NodeInput

# Set up
registry = ChallengeRegistry(db_path="omega.db")
registry.seed_initial_challenges()  # loads 18 pre-defined challenges

gates = VerificationGateSystem()
gates.register(RegressionGate(
    "sharpe_regression", metric="sharpe_ratio",
    direction="maximize", threshold_pct=15.0,
))

da = DevilsAdvocateNode(registry=registry, gate_system=gates)

# Run a review
out = da.execute(NodeInput(
    action="architectural_review",
    parameters={"subsystem": "alignment"},
))
print(out.result["verdict"])  # APPROVED or VETOED
print(out.result["open_count"])

# Check if you're blocked before deploying
if registry.has_blocking_challenges():
    print("CRITICAL challenges open — deployment blocked")
    for ch in registry.open_challenges():
        if ch.severity.value == "critical":
            print(f"  [{ch.target_subsystem}] {ch.description[:80]}")
```

## Operating Modes Reference

| Mode | Action Key | Purpose |
|------|-----------|---------|
| Architectural Review | `architectural_review` | Challenge design decisions for a subsystem |
| Implementation Audit | `implementation_audit` | Find gaps between spec and code |
| Assumption Stress Test | `assumption_stress_test` | Break implicit assumptions system-wide |
| Regression Hunt | `regression_hunt` | Detect metric regressions in before/after snapshots |
| Complexity Audit | `complexity_audit` | Flag over-engineering, suggest simpler alternatives |
