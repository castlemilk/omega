# V218 — Matrix experiment (3 cells, shared V217-OFF hermetic baseline)

**Date:** 2026-06-09 (pre-staged in V217; DO NOT START until V217 ships 6/6)
**Author:** claude
**Parent:** V217 — third determinism channel (multi-threaded Accelerate BLAS) closed;
eval is 6/6 hermetic at sleep=10 (the precondition the matrix waited on since V213).
**Status:** PRE-STAGED (not yet running). Per the skill, the matrix runs only on a fully
hermetic eval. V217 delivered it.

## Why matrix now

The matrix has waited since V213 because the eval was not hermetic (V212 selector
non-determinism → V213 sleep/async → V214 network → V215 network fix → V216 sizing
wall-clock → V217 BLAS threading). With 6/6 cells byte-identical at sleep=10, per-cell
deltas are finally trustworthy and three **independent** bets can run in parallel against
one baseline instead of three sequential ~8h versions.

## Shared baseline (V217 OFF, hermetic, single-threaded BLAS, sleep=10)

| Gate    | V217 OFF baseline (det.) | Trades | Noise floor |
|---------|-------------------------:|-------:|------------:|
| recent  | -$1,905.71               | 38     | $0 (hermetic — every cell $0.00) |
| trend   | +$1,039.24               | 35     | $0 |
| crisis  | -$2,199.50               | 38     | $0 |

(V217 ON arm, for reference: recent +$2,334.40 / trend −$6,392.99 / crisis −$3,420.26;
selector Δ = recent +$4,240 / trend −$7,432 / crisis −$1,221 — all clean.)

Because V217 is byte-identical, the within-config noise floor is **$0** — but to guard
against many-comparisons false positives with N=3 cells, use the skill's **2.5σ → here a
flat acceptance band**: a cell counts as a real move only if its gate Δ exceeds the larger of
(a) the V203 variance 2σ thresholds (recent $5,094 / crisis $1 / trend $2) and (b) any
residual within-cell spread (expected $0). Document the chosen band per cell below.

> ⚠️ **Stale-σ caveat (resolve at V218 kickoff).** The V203 2σ thresholds were measured under
> the OLD regime (**multi-threaded BLAS + pre-fence sizing**). The V217 hermetic baseline is a
> DIFFERENT regime (single-threaded BLAS + 0.375× bar-time sizing). Within-config spread is now
> $0, but the *cross-config* variance that actually governs cell-vs-baseline comparisons is
> **unmeasured under the new regime**. Before trusting the V203 band, either re-derive a noise
> floor under V217 HEAD or treat the V203 numbers as a conservative upper bound only.

## Cells (each in its own worktree `.claude/worktrees/v218-<letter>-<name>/`)

> **Worktrees are created at V218 kickoff, NOT pre-created in V217.** V217 is
> pre-registration only (the skill's "don't START matrix runs in V217" rule). The paths
> below are the agreed naming convention; the three worktrees do not yet exist on disk.

### V218.A — V199 carry plumbing isolation
- **Hypothesis:** routing the funding-carry signal into the composite (V199's carry-only
  sub-strategy plumbing) adds a clean normal-regime edge on recent.
- **Change:** cherry-pick `cbbfb07` (V199 carry plumbing) onto V217 HEAD; verify with the
  V197 PipelineTracer that carry actually enters the composite (≥1 carry-attributed trade).
- **Files touched:** `strategy.py`, `ensemble_voter.py` (carry routing).
- **Targeted gate:** recent.
- **Falsifier:** < 5 carry-attributed trades in 200 cycles → carry still gated out (tracer
  bug, not edge); recent Δ within 2σ → no edge.

### V218.B — V170 per-regime IC weighting
- **Hypothesis:** recomputing IC weights per regime label (crisis/high_vol/normal) instead
  of pooled changes which sub-signals dominate the composite in crisis without touching the
  reflection-flagged `crisis_short_bias` dead end.
- **Change:** activate the dormant `update_regime_ics` path; verify weights actually diverge
  per regime (tracer evidence).
- **Files touched:** ensemble voter / IC weighting config.
- **Targeted gate:** crisis (primary), trend (secondary).
- **Falsifier:** per-regime weights identical to pooled (switch inert) → no read; crisis Δ
  within 2σ → no effect.

### V218.E — `snap_crisis_2020q1` generalisation check (no code change)
- **Hypothesis:** if V217's crisis loss is snapshot-specific (LUNA/FTX 2022h1 dynamics) vs
  structural (any drawdown), a second crisis snapshot (COVID 2020q1) reveals it.
- **Change:** NONE. Run V217 HEAD against `data/snapshots/snap_crisis_2020q1.json`.
- **Files touched:** none (eval extension only).
- **Targeted gate:** crisis (extended).
- **Falsifier:** n/a (pure diagnostic) — informative either way.

## Independence argument (required before running matrix)

A (carry routing, `strategy.py`/`ensemble_voter`) and B (IC weighting path) touch disjoint
subsystems; E is a pure eval extension (no code). No shared parameter surface →
matrix-eligible. Pre-flight: each worktree pins `OMEGA_FROZEN_CACHE` + the V217 BLAS pin and
isolates cache writes (`data/macro_cache.db`, `state.db`) so cells don't contaminate each
other (the matrix-mode shared-state failure mode).

## Merge rule

Only ONE cell's code merges to main (or zero if none clears the band). A + B both passing →
V219 stacks the pair OR runs a 2×2 interaction; do not silently merge two cells. E never
merges (no code); its result informs whether crisis work generalises.

## Results

_(filled after the matrix runs — one row per cell)_

| Cell | Hypothesis | recent Δ | trend Δ | crisis Δ | Verdict |
|------|------------|---------:|--------:|---------:|---------|
| V218.A | carry plumbing |  |  |  |  |
| V218.B | V170 IC |  |  |  |  |
| V218.E | 2020q1 snapshot |  |  |  |  |
