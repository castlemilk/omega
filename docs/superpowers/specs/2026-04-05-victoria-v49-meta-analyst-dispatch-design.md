# Victoria V49 — Meta-Analyst Dispatch Design

**Date**: 2026-04-05
**Author**: Brainstormed with Claude (Opus 4.6)
**Status**: Approved, pending implementation plan
**Baseline**: V48 at commit `6aef159f` (+$31.97 PnL, 103 trades, WR 31%, PF 1.34)
**Target**: V49 with forensics-driven calibration + two new intelligence surfaces

---

## Problem

V35 hit a +$151 PnL breakthrough by introducing cross-sectional demeaning. V36–V48 over-iterated on that config and only partially recovered (V48: +$31.97). The root cause has been consistently mis-diagnosed as "conviction threshold miscalibration", but no run has produced a structured diff between V35 and V48 to prove that hypothesis. Meanwhile, the decision-traceability observability infrastructure just landed (`internal/heartbeat/decisions.go`, `/decisions` + `/health-score` + `/lifecycle` REST endpoints, DecisionTrace/NodeHealth/TradeAnalysis dashboard pages) but is not yet exercised by the training loop — the platform can *describe* distributed intelligent use cases but isn't yet *learning from* them.

V49 closes both gaps simultaneously: the training process becomes forensics-driven and regime-gated, and the platform gains two new intelligence surfaces (a new signal producer, a meta-analyst node) both anchored on the decision-trace substrate. Victoria is the first distributed intelligent use case; this design treats that fact as load-bearing, not incidental.

## Goals

1. Ship V49 with PnL ≥ V48 across **every** regime (bull, bear, chop) — no single-regime wins.
2. Produce a machine-readable forensics report explaining the V35 → V48 PnL gap.
3. Introduce TimesFM and Wasserstein K-means regime detection as new signal producers, dry-run only in V49, enablement deferred to V50.
4. Introduce a meta-analyst node that consumes decision traces and produces structured `TrainingProposal` protobuf messages, with full stages 1+2+3 of the trust ladder active in V49 (advisory + auto-apply with caps + trust-score gated authority).
5. Wire three dashboard pages off mock data onto real endpoints so the training loop is visually auditable during the run, not just post-hoc.
6. Prevent another V36–V44 over-iteration: V49's training script enforces hard gates that fail closed.

## Non-goals

- Not a live trading execution project. Victoria remains research/paper.
- Not a dashboard wiring project beyond the three high-value observability pages.
- Not a meta-analyst safety-hardening project (adversarial inputs, prompt-injection defenses are V50+).
- TimesFM and Wasserstein profitability is V50's concern. V49 only proves they load, wire, and emit decision-trace entries.
- Not a Python-platform expansion. All new platform code is Go where applicable. Python is limited to signal producers (TimesFM, Wasserstein, meta-analyst LLM client).

## Architecture

Five parallel agents, each in its own git worktree branched off `main` at `6aef159f`. Agent 1 blocks Agents 2/3/5; Agent 4 is independent and runs from the start. All agents share the decision-trace substrate as the single source of truth for cross-agent communication and observability.

```
                  main @ 6aef159f (V48 baseline)
                                |
       +------------+-----------+-----------+------------+
       |            |           |           |            |
    Agent 1      Agent 2     Agent 3     Agent 4      Agent 5
  Forensics   Calibration   TimesFM +   Dashboard   Meta-Analyst
   (V35 vs    + IS/OOS      Wasserstein  (mock→     (Claude node,
    V48 diff) gates          (dry-run)    real)      stages 1+2+3)
       |            ^           ^                       ^
       |            |           |                       |
       +---- forensics JSON ----+-----------------------+
                         (shared substrate)
```

**Dependency rules:**
- Agent 1 runs first, produces `data/v35-v48-forensics.json`.
- Agents 2, 3, 5 wait on that artifact, then run in parallel.
- Agent 4 has zero dependencies, launches immediately.
- Consolidation merges Agents 2, 3, 5 via cherry-pick into `main` only after V49 gate passes. Agent 4 merges independently when it lands.

**Platform/project split compliance:**
- Agent 5's meta-analyst node lives in `omega/nodes/meta_analyst.py` (platform, project-agnostic), not under `omega/nodes/victoria/`.
- Agent 3's TimesFM and Wasserstein signals live under `omega/nodes/victoria/` (project-specific).
- `TrainingProposal` proto lives in `proto/omega/v1/training_proposal.proto` (platform-level schema).

## Components

### Agent 1 — Forensics (blocking)

**Branch**: `forensics/v35-v48-diff`
**Scope**: Read-only analysis. Does not modify any signal/strategy code.

**Deliverables:**
- `docs/training/v35-v48-forensics.md` — human-readable report with per-signal contribution deltas, conviction band histogram, trade-by-trade attribution, top-3 ranked hypotheses, regime breakdown.
- `data/v35-v48-forensics.json` — machine-readable sidecar consumed by Agents 2, 3, 5.
- If `data/v35_results.json` is missing, Agent 1 re-runs the V35 configuration against the current data window to reconstruct it, annotating the forensics JSON with `source: "rerun"` for provenance.

**Hard constraint**: Read-only with respect to signal/strategy code. Re-run fallback may write to `data/v35_*.json` only if the originals are missing.

### Agent 2 — Calibration + V49 Training Run

**Branch**: `training/v49-calibration`
**Depends on**: `data/v35-v48-forensics.json`

**Deliverables:**
- HOLD band recalibration driven by forensics findings (proportional, regime-adaptive).
- New gate block in `scripts/run_training.py` enforcing the V49 hard gates (see Error Handling section).
- `tests/test_training_regression.py` — new regression suite covering the hard gates.
- V49 run artifacts: `data/v49_results.json`, `data/v49_trades.csv`, `data/v49_progress.json`.

**Hard constraint**: Does NOT modify signal producers. Only conviction/strategy/gate code is touched.

### Agent 3 — TimesFM + Wasserstein Signal Producers

**Branch**: `signals/timesfm-wasserstein`
**Depends on**: `data/v35-v48-forensics.json` (to target appropriate regimes/horizons)

**Deliverables:**
- `omega/nodes/victoria/timesfm_signal.py` — TimesFM (Google time-series foundation model) signal producer.
- `omega/nodes/victoria/wasserstein_regime.py` (extension of existing stub if present) — Wasserstein K-means regime detector.
- Both wired into `signal_generation.py` behind off-by-default flags.
- Decision-trace hooks via `HeartbeatClient.post_decision()` so outputs are visible in traces even with weight=0.
- `tests/test_timesfm_signal.py`, `tests/test_wasserstein_regime.py`.
- If one of the two models fails to install, the working one ships and the other lands as a degraded-mode skeleton (returns zeros, decision-trace wired) so V50 can pick up.

**Hard constraint**: Additive only. No existing signal is modified. Both producers ship with weight=0 in V49. V49 profitability is independent of their output.

### Agent 4 — Dashboard Real-Data Wiring

**Branch**: `dashboard/real-data`
**Depends on**: nothing

**Deliverables:**
- `DecisionTrace` page reads from `/decisions` endpoint.
- `NodeHealth` page reads from `/health-score` + `/lifecycle` endpoints.
- `VictoriaTrades` page reads from a new Connect-RPC method on the Go side, which in turn reads from the training run CSVs or Postgres (wherever trades land).
- Uses shadcn components. Connect-ES client generated from proto. No hand-written proto types.
- Dashboard contract tests (`dashboard/src/**/__tests__/*.test.tsx`) verify shapes match generated Connect-ES types.

**Hard constraint**: Frontend + minimal Go glue only. Python untouched. If an endpoint needs to be added server-side, it goes into the same worktree.

### Agent 5 — Meta-Analyst Node (stages 1+2+3 active)

**Branch**: `nodes/meta-analyst`
**Depends on**: `data/v35-v48-forensics.json` (used as ground truth for sanity check)

**Deliverables:**
- `omega/nodes/meta_analyst.py` — new Node subclass living at platform level.
- `proto/omega/v1/training_proposal.proto` — new protobuf with `TrainingProposal`, `ProposalHypothesis`, `ProposedDiff`, `ExpectedOutcome`, `VerificationPlan`, `ProposalStatus` enum.
- Generated Go + Python bindings via `make proto` and `make proto-python`.
- Wired into `omega/core/meta_harness.py` (currently unwired) so meta-analyst runs post-cycle as an advisory + auto-apply step.
- Backed by Claude via the existing brain adapter.
- Trust-score persistence at `data/meta_analyst_trust.json`.
- `tests/test_meta_analyst.py`, `tests/test_meta_analyst_sanity.py`.
- Post-V49 assessment: `docs/training/v49-meta-analyst-assessment.md`.

**Trust ladder active in V49:**

| Stage | Trust band | Behavior |
|-------|-----------|----------|
| 1 (advisory) | `trust < 0.3` | Proposals logged to decision trace, zero auto-apply, kill switch armed |
| 2 (auto-apply) | `0.3 ≤ trust < 0.7` | Param/threshold/signal_weight diffs auto-apply with caps; code diffs never auto-apply |
| 3 (expanded) | `trust ≥ 0.7` | Stage 2 behavior + proposals may group related param/threshold/signal_weight diffs into a single atomic change (still counted against the 3-diffs-per-run cap as one group). Never code diffs in V49. |

**Cold-start seeding:** First-run trust score computed from forensics-alignment only (`trust = 0.5 * forensics_alignment + 0.5 * 0.5`). Most likely initial band is 0.3–0.7 (stage 2).

**Auto-apply guardrails (all stages 2+):**
- Max 3 auto-applied diffs per V49 iteration.
- Max ±25% parameter delta per diff.
- Every auto-applied diff writes a `proposal.auto_applied` decision-trace span with before/after snapshot.
- Unmatched auto-applied spans (auto-apply without corresponding before-snapshot) fail the V49 hard gate.

**Kill switch:** If Agent 5's proposals collectively drive V49 PnL below V48, the post-run report auto-sets `meta_analyst.enabled=false` so V50 starts without active meta-analyst. V49 itself still ships if other gates pass.

**Hard constraint**: Never auto-applies `code` diffs in V49 regardless of trust score. Code-level changes remain advisory-only.

## Data Flow & Shared Contracts

### Forensics JSON schema (v1.0, JSON in V49, promote to protobuf in V50)

`data/v35-v48-forensics.json`:
- `schema_version`, `generated_at`, `status` ("ok" | "degraded")
- `baselines`: V35 and V48 summary stats
- `signal_contribution_delta[]`: per-signal weight and PnL attribution deltas
- `conviction_histogram`: HOLD band / trade band percentages per version
- `skipped_trades[]`: V35 trades that V48 missed, with reason codes
- `hypotheses[]`: top 3 ranked structural explanations with confidence and evidence refs
- `regime_breakdown`: per-regime PnL deltas

### `TrainingProposal` protobuf

New file: `proto/omega/v1/training_proposal.proto`

```proto
syntax = "proto3";
package omega.v1;
import "google/protobuf/timestamp.proto";

message TrainingProposal {
  string proposal_id = 1;
  string source_node = 2;
  google.protobuf.Timestamp generated_at = 3;
  string baseline_version = 4;
  string target_version = 5;
  repeated ProposalHypothesis hypotheses = 6;
  repeated ProposedDiff diffs = 7;
  ExpectedOutcome expected = 8;
  VerificationPlan verification = 9;
  float overall_confidence = 10;
  ProposalStatus status = 11;
}

message ProposalHypothesis {
  int32 rank = 1;
  string claim = 2;
  float confidence = 3;
  repeated string evidence_refs = 4;
}

message ProposedDiff {
  string file_path = 1;
  string change_kind = 2;  // "param" | "threshold" | "signal_weight" | "code"
  string before = 3;
  string after = 4;
  string rationale = 5;
  bool auto_applicable = 6;  // only true for non-code diffs
}

message ExpectedOutcome {
  float expected_pnl_usd = 1;
  float expected_win_rate = 2;
  float expected_max_drawdown = 3;
  string regime_applicability = 4;
}

message VerificationPlan {
  repeated string regression_tests = 1;
  repeated string backtest_ranges = 2;
  bool requires_human_approval = 3;
}

enum ProposalStatus {
  PROPOSAL_STATUS_UNSPECIFIED = 0;
  PROPOSAL_STATUS_ADVISORY = 1;
  PROPOSAL_STATUS_ACCEPTED = 2;
  PROPOSAL_STATUS_REJECTED = 3;
  PROPOSAL_STATUS_APPLIED = 4;
}
```

Generated via `make proto` (Go) and `make proto-python` (betterproto). Agent 5 imports from the generated file per CONTRIBUTING.md.

### Decision-trace writes (observability substrate)

Every agent's output is visible in the decision trace:
- Agent 1: `forensics.completed` span tagged with baseline versions and hypothesis count
- Agent 2: `calibration.applied` spans per parameter change + `training.run.completed` span for V49
- Agent 3: `signal.registered` spans for TimesFM and Wasserstein (dry-run, weight=0)
- Agent 5: `proposal.generated` spans carrying `TrainingProposal.proposal_id`; `proposal.auto_applied` spans for stage 2+ applications

The meta-analyst's own suggestions are visible in the same dashboard Agent 4 is wiring — closing the self-observation loop.

## Error Handling & V49 Hard Gates

### V49 hard gates (enforced in `scripts/run_training.py`)

V49 ships to `main` only if **all six** of these pass:

1. **PnL floor**: `v49_pnl >= v48_pnl` (≥ $31.97)
2. **Regime parity**: V49 is non-negative in every regime (bull, bear, chop). A single-regime win is not acceptable.
3. **Drawdown ceiling**: `v49_max_drawdown <= v48_max_drawdown`
4. **Trade count floor**: `v49_trades >= 50`. Prevents calibrations that "win" by skipping the market.
5. **Signal integrity tests pass**: `tests/test_signal_integrity.py` + `tests/test_training_regression.py`
6. **Auto-apply audit**: every `proposal.auto_applied` span has a matching before-snapshot span; unmatched spans fail the gate.

A failed gate writes `data/v49_gate_failure.json` with the specific failing criterion and exits non-zero. The training run is not committed to `main`.

### Post-run actions (not gates)

These run after V49 passes the six gates and ships. They adjust V50's starting state without blocking V49:

- **Meta-analyst kill switch**: if Agent 5's proposals collectively reduced PnL below V48 (measured by attributing the delta of auto-applied diffs), the post-run report sets `meta_analyst.enabled=false` in the config committed for V50. V49 itself still ships.
- **Trust score persistence**: final trust score is written to `data/meta_analyst_trust.json` so V50 starts at the correct ladder stage.

### Per-agent failure handling

| Agent | Failure mode | Behavior |
|-------|--------------|----------|
| Agent 1 | V35 artifacts missing + re-run fails | Partial forensics JSON with `status: "degraded"`. Agents 2/3/5 block pending user decision. |
| Agent 1 | V35 artifacts missing, re-run succeeds | Proceeds normally, `source: "rerun"` recorded in JSON. |
| Agent 2 | V49 fails any hard gate | Does not merge. `v49_gate_failure.json` written. Worktree stays alive for iteration. |
| Agent 2 | V49 run crashes mid-cycle | Partial results logged, worktree stays alive, no merge. |
| Agent 3 | One model fails to install | Working model ships; failing model lands as degraded skeleton. |
| Agent 3 | Both fail | Both ship as degraded skeletons with decision-trace hooks so V50 can resume. |
| Agent 4 | Go API endpoint missing | Add the Connect-RPC method in the same worktree. If data is unavailable server-side entirely, page falls back to direct decision-trace DB read. |
| Agent 5 | Claude API unreachable | Meta-analyst initializes, logs `brain_unavailable`, emits no proposals. Does not block V49. |
| Agent 5 | Sanity check fails (analyst diverges from forensics) | `meta_analyst.enabled=false` in V49 config. Proposal logged to decision trace. GitHub issue opened. V49 ships without active meta-analyst. |
| Agent 5 | Sanity check passes | Meta-analyst enabled in V49 at trust-score-appropriate stage. |

### Rollback plan

Merges happen via cherry-pick to `main`. If V49 ships and regressions appear within 24h:
- `git revert` Agent 2's training commit only.
- Meta-analyst and TimesFM/Wasserstein code stay on `main` (additive, off-by-default, no harm).
- Dashboard wiring stays on `main` (cosmetic improvement, unrelated to PnL).
- Forensics doc stays on `main` (historical record).

Rollback is surgical: only Agent 2's changes are reverted.

## Testing Strategy

### Per-agent test matrix

| Agent | Test files | Coverage |
|-------|-----------|----------|
| Agent 1 | `tests/test_forensics.py` | Schema validation, degraded mode, signal contribution delta sum matches PnL delta within tolerance, re-run fallback schema parity |
| Agent 2 | `tests/test_training_regression.py`, `tests/test_gate_enforcement.py` | Hard gate enforcement for every criterion; synthetic passing/failing fixtures; V48-lookalike regression guard |
| Agent 3 | `tests/test_timesfm_signal.py`, `tests/test_wasserstein_regime.py` | Model load, numeric output shape, dry-run decision-trace wiring, degraded-mode fallback |
| Agent 4 | `dashboard/src/**/__tests__/*.test.tsx` | Contract tests for three wired pages against generated Connect-ES types |
| Agent 5 | `tests/test_meta_analyst.py`, `tests/test_meta_analyst_sanity.py` | Proposal generation with mocked Claude, `auto_applicable` enforcement, per-run/per-diff caps, trust band → authority mapping, kill switch activation, forensics-alignment sanity check with diverging fixture |

### Cross-agent contract tests

- `tests/test_action_contracts.py` (existing, must still pass) — all new actions use `NodeAction` enum.
- `tests/test_proto_contracts.py` (new, small) — `TrainingProposal` round-trips Go ↔ Python via betterproto; enum stability; unknown status values don't crash.

### V49 end-to-end smoke test

`tests/test_v49_e2e.py`:
1. Run a 10-cycle V49 on a frozen fixture dataset.
2. Assert: gates pass on fixture, decision trace contains forensics + proposal + lifecycle spans, meta-analyst emits ≥1 advisory proposal, TimesFM + Wasserstein appear in trace with weight=0.
3. Runs in CI on every PR.

### Extended signal integrity regression suite

Extend `tests/test_signal_integrity.py` (V44 suite):
- V35 canonical fixture → signal outputs match frozen snapshot within tolerance.
- "No silent HOLD-band widening" assertion: default HOLD band width cannot exceed 2.0× V35 snapshot without explicit override flag.

### Manual pre-merge verification (Agent 2 only)

Before Agent 2's worktree merges:
1. Eyeball `v49_results.json` vs `v48_results.json` side by side.
2. Confirm first and last decision-trace spans render sanely in the dashboard.
3. Verify the forensics top hypothesis maps to the applied calibration change.

This is the only manual step. Listed explicitly because the whole point of V49 is preventing another V36–V44 over-iteration, and a human visual check catches regressions unit tests miss.

### Out of scope for V49 testing

- Live execution paths (Victoria is paper/research).
- Multi-day continuous stability (nightly job).
- TimesFM/Wasserstein profitability (V50 concern).
- Meta-analyst adversarial input handling (V50+ hardening).

## Assessment Deliverable (post-V49)

Agent 5 produces `docs/training/v49-meta-analyst-assessment.md`:
- Proposals generated / auto-applied counts
- Per-stage effectiveness: did stage-2 auto-applies improve PnL? Did stage-3 ever activate?
- Final trust score
- Recommendation: expand, hold, or disable meta-analyst for V50

Combined with Agent 1's forensics report and the V49 gate-pass artifacts, this forms the decision input for V50 scoping.

## Success Criteria

V49 is considered successful if:
1. V49 passes all six hard gates and ships to `main`.
2. `data/v35-v48-forensics.json` exists and identifies a top-ranked hypothesis that Agent 2's calibration change addresses.
3. TimesFM and Wasserstein both appear in V49 decision traces (even if only one is non-degraded).
4. Meta-analyst generates at least one proposal during the V49 run, and the assessment doc exists.
5. Three dashboard pages render real data.
6. No regression in existing signal integrity tests.

Stretch (not required):
- Meta-analyst stage 2 auto-applies at least one diff that survives the hard gates.
- V49 PnL exceeds V35 (+$151), not just V48 (+$31.97).
