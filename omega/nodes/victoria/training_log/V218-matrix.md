# V218 — Matrix experiment (3 cells, shared V217-OFF hermetic baseline)

**Date:** 2026-06-09 (pre-staged in V217; DO NOT START until V217 ships 6/6)
**Author:** claude
**Parent:** V217 — third determinism channel (multi-threaded Accelerate BLAS) closed;
eval is 6/6 hermetic at sleep=10 (the precondition the matrix waited on since V213).
**Status:** RUNNING (kickoff 2026-06-09). Per the skill, the matrix runs only on a fully
hermetic eval. V217 delivered it.

## Kickoff preflight (2026-06-09) — Step-1 observability-gap audit results

Before launching, a wiring audit of the two code cells (A, B) surfaced a finding that
**reclassifies cell B from a runnable bet to BLOCKED**, and ships the instrument that would
have caught it at pre-reg time:

- **Cell A — RUNNABLE.** `signals["carry"]` IS populated in the replay eval
  (`victoria_node.py:1120`, fields `value`/`confidence`/`regime_tag`) — exactly what
  cbbfb07's hunk-1 injection reads. Whether `_carry_value != 0.0` holds under `--frozen-cache`
  is precisely what A's falsifier (≥1 carry-attributed trade) measures. Proceed.
- **Cell B — BLOCKED (deeper than the pre-reg anticipated).** The pre-reg assumed pooled IC
  weighting was the live baseline and only the *per-regime* branch was dormant. Static + log
  audit shows the **entire IC-weighting subsystem is runtime-inert in the eval**:
  1. `StrategyNode._signal_ics` is initialised empty (`strategy.py:437`) and its **only**
     populate path is `update_signal_ics`, which has **zero callers** in the training/audit
     path (not in `run_training.py` HEAD, not in `victoria_node.py`). Confirmed empirically:
     **no `"StrategyNode: loaded ICs"` line appears in any V217 run log.**
  2. `_compute_weighted_conviction` (`strategy.py:1025`) runs every cycle (called at `:1429`
     inside `_passes_conviction_filters`) but hits `if not self._signal_ics: return composite`
     at `:1032` — it **returns before ever reaching the `_per_regime` branch at `:1056`.**
  3. `per_regime_ic_weighting` is **undeclared** on `VictoriaFeatures`; `from_env` filters
     overrides to declared fields (`features.py:699`), so even passing it via env is a no-op.
  4. `update_regime_ics` has **no cycle-feasible data source**: `signal_ic_history.json` is
     pooled, not regime-tagged; the only regime-IC producer is the on-demand
     `_analyze_regime_ic` *action* (`signal_research.py:311`), not a per-cycle hook.

  → Per the advisor and the matrix one-bet rule, **B's scope is NOT expanded** (loading pooled
  ICs to clear the early-return is a *second* bet — raw-composite → IC-weighted — that would
  confound B's Δ). B runs as a **flag-only no-op** (declare the field, default True in its
  worktree) to empirically confirm Δ=$0.00 even with the flag ON, then carries verdict
  **BLOCKED**. Its pre-registered falsifier ("switch inert → no read") anticipated exactly this.
  V219.B-corrected gets the real prerequisite: **wire pooled ICs from `signal_ic_history.json`
  as its own one-bet version, then per-regime becomes testable.**

**Observability shipped this kickoff (the instrument that catches this class at cycle 0):**
- `run_training.py` startup banner extended: probes `per_regime_ic_weighting` (→ prints
  `UNDECLARED — silent no-op` on main) **and** a new post-build `_signal_ics`-populated probe
  (→ warns `IC-WEIGHTING INERT: _signal_ics empty` when the subsystem is unwired).
- `scripts/v218_matrix_status.sh` — single-pane health monitor for the 3 concurrent cells
  (PID liveness + log tail + per-cell gate progress).
- `check_determinism.sh` gains `SNAP_OVERRIDE` env (lets cell E run its crisis gate against
  `snap_crisis_2020q1.json` with no code diff). Remaining backlog item (`size_ratio.jsonl`
  automated artifact) queued to `OBSERVABILITY-BACKLOG.md`.

## σ band (resolves the stale-σ caveat below)

Within-config spread is **$0** under the V217 hermetic regime (each cell re-confirms via its
own trend determinism gate). The V203 2σ thresholds were measured under the OLD regime
(multi-threaded BLAS + pre-fence sizing) and are NOT trusted for cross-config comparison.
**Decision:** use a flat **$100 acceptance band** (noise-floor $0 × generous margin; well
above the 2.5σ-at-N=3 inflation when σ≈$0). A cell's gate Δ counts as real signal only if
**|Δ| > $100**. Cell E compares **absolute PnL** on the new 2020q1 snapshot, not Δ vs the
2022h1 crisis baseline (different window).

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

### V218.B — V170 per-regime IC weighting  →  **BLOCKED at kickoff (see preflight above)**
- **Hypothesis (original):** recomputing IC weights per regime label (crisis/high_vol/normal)
  instead of pooled changes which sub-signals dominate the composite in crisis without touching
  the reflection-flagged `crisis_short_bias` dead end.
- **Change (as run):** declare `per_regime_ic_weighting: bool = True` on `VictoriaFeatures` in
  the cell-B worktree only — a **flag-only no-op** to empirically confirm the subsystem is
  inert even with the flag ON. **NOT** expanded to load pooled ICs or build a regime-IC
  accumulator (that would be a second bet; see preflight).
- **Files touched:** `features.py` (one field declaration).
- **Targeted gate:** crisis (primary), trend (secondary) — *moot; subsystem unwired*.
- **Falsifier (FIRED at preflight):** "per-regime weights identical to pooled / switch inert →
  no read." Confirmed: `_signal_ics` empty → `_compute_weighted_conviction` early-returns the
  raw composite before the per-regime branch. Expected audit Δ = **$0.00 on all gates**.
- **Verdict:** BLOCKED. Root cause = pooled `update_signal_ics` never called in the eval.
  V219.B-corrected = wire pooled ICs first (its own version).

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
