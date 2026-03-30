# Meta-Harness — Autonomous Self-Improvement for LLM Harnesses

**Date:** 2026-03-31
**Source:** @yoonholeee, Stanford IRIS Lab
**Category:** Self-improvement, LLM infrastructure, autonomous agents

---

## Overview

Meta-Harness is a framework from Stanford's IRIS Lab that enables LLM harnesses (scaffolding, prompt pipelines, orchestration code) to autonomously improve themselves over time — without human intervention after initial setup. The core idea: the harness that runs an LLM agent can itself be the target of LLM-driven optimization.

---

## The 3-Step Loop

```
Propose → Evaluate → Store
```

### 1. Propose
- The meta-harness inspects its own codebase, recent run logs, and failure traces
- An LLM generates candidate modifications: new prompts, altered retrieval strategies, changed orchestration logic, updated tool configurations
- Proposals include **textual rationales** — natural language explanations of *why* this change should help, grounded in observed failure modes
- Full filesystem history is available to the proposer: diffs, commit logs, error outputs, evaluation metrics

### 2. Evaluate
- Each proposed change is **isolated** — applied in a sandbox or temporary branch, not the live system
- A suite of evaluation tasks runs against the modified harness (regression suite + targeted benchmarks for the failure mode the change addresses)
- Results are compared to a baseline captured before the modification
- The evaluator uses a separate LLM call (or deterministic scoring) to assess whether the change genuinely improves performance

### 3. Store
- Changes that pass evaluation are committed to the harness codebase with their rationale as the commit message
- Failed proposals are stored in a rejection log with the evaluation result — this rejection log becomes training signal for future proposals
- Over time, the proposal LLM learns from the accumulated rationale/outcome pairs without explicit fine-tuning (in-context learning from the log)

---

## Key Insights

### Full Filesystem History
The proposer LLM has access to the **complete history** of the harness — not just current state. This means it can observe:
- What has been tried and failed before (avoiding redundant proposals)
- Performance trends over time (detecting regressions vs. improvements)
- Which types of changes correlate with positive outcomes

### Isolate Changes
**Never apply proposals to the live system directly.** Each proposal runs in isolation:
- Git worktrees for code changes
- Separate database snapshots for state-dependent changes
- Rollback is trivial because the baseline is always preserved

### Textual Rationales
Proposals must include human-readable explanations of the expected mechanism of improvement. This serves multiple purposes:
- Forces the proposer LLM to reason about causality, not just pattern-match
- Creates a searchable audit trail ("why did we add this prompt prefix?")
- Enables human review to be fast and high-signal
- Rationales that turned out to be wrong become valuable negative examples

---

## Omega Integration Plan

### Immediate Fit: Victoria Signal Loop
The Victoria node already has a self-improvement cycle (improvement_engine.py). Meta-Harness can augment this:

1. **Propose phase**: After each training cycle, scan `/tmp/v{N}_training.log`, recent backtest results, and signal performance metrics. Generate 3-5 candidate harness changes (e.g., "increase HMM lookback from 100 to 150 bars because regime transitions are being detected 2-3 bars late based on the lag analysis in v28 results").

2. **Evaluate phase**: Run a 50-cycle mini-backtest with the proposed change in a git worktree. Compare Sharpe, max drawdown, and win rate against the baseline from the same period.

3. **Store phase**: If evaluation passes (Sharpe delta > +0.05, max DD does not worsen), auto-commit with the rationale. If it fails, append to `data/rejected_proposals.jsonl`.

### Infrastructure Requirements
- **Worktree-based isolation**: Already available via `.claude/worktrees/`
- **Baseline capture**: Store per-version eval results in `data/v{N}_results.json` (already exists)
- **Rationale log**: New file `data/improvement_rationales.jsonl`
- **Proposal LLM**: Use existing brain provider (Claude Sonnet) with a specialized system prompt for harness analysis

### Longer-Term: Orchestrator Self-Modification
The Go orchestrator (`internal/core/orchestrator.go`) could expose a "harness modification" interface that allows:
- Updating node weights in the attention router
- Adjusting cycle timing
- Adding/removing signal modules from the pipeline

These modifications would go through the same Propose→Evaluate→Store loop, but with Go test suites as the evaluation mechanism.

### Safety Constraints
- **Never auto-apply to live trading**: All meta-harness improvements go through paper trading validation first
- **Human approval gate for structural changes**: Changes to orchestration logic or node topology require a one-line approval before committing
- **Rollback always available**: All changes are committed (not squashed), so `git revert` is the safety valve
- **Scope limits**: Proposals can only modify files in `omega/nodes/victoria/`, `omega/core/`, and `scripts/` — not infrastructure, auth, or API handlers

---

## Related Work
- **Self-Refine** (Madaan et al., 2023): Iterative self-improvement via feedback, but operates on outputs not infrastructure
- **Reflexion** (Shinn et al., 2023): Stores verbal feedback in memory, closer but still output-level
- **LLM-as-optimizer** (Yang et al., 2023): Uses LLMs for optimization but requires explicit objective functions
- **Meta-Harness** distinguishes itself by targeting the *infrastructure layer* rather than task outputs

---

## References
- @yoonholeee on X/Twitter
- Stanford IRIS Lab: [iris.stanford.edu](https://iris.stanford.edu)
