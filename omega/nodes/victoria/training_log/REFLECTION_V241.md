# REFLECTION after V241 — reasoning layer refuted; where the next bet comes from

**Date:** 2026-07-12 · **Author:** claude (Fable 5)
**Trigger:** the V241 launch falsifier itself ("ANY clause fails → …
revert-and-branch reflection required"). No skill-level trigger fired
independently (see §3 — no subsystem loop, no stagnation streak, no Goodhart
window), but the pre-reg made reflection mandatory on refutation, so it is.

## 1. Eval stability

The eval is byte-deterministic from committed state at the V241 condition:
32 cells 0 determinism FAILs; 3 sentinels N=2 spread $0.00; 100% frozen-cache
hits (zero `LLMCacheMiss` across ~1,400 replayed calls); OFF arm reproduced
from current tree 4/4 windows identical ex-run-timestamp against cells
archived two days earlier. Replicate noise floor: **$0.00**. The binding
uncertainty is *sampling* noise across windows, not eval noise.

## 2. Variance estimate

Multi-seed runs are moot (seed pinned, replicates byte-identical). The
window-level dispersion IS σ:

| regime | n | Δ sd | 2·SE(Δ mean) | V241 Δ mean |
|---|---:|---:|---:|---:|
| crisis | 12 | $2,848 | $1,644 | −$48 |
| trend | 10 | $7,354 | $4,651 | −$69 |
| recent | 10 | $1,660 | $1,050 | +$227 |

Every V241 regime mean is deep inside its own 2·SE — the layer's mean effect
is indistinguishable from zero everywhere. What is NOT noise-shaped is the
per-window dispersion itself: the layer *injects* variance (trend Δ sd $7.4k
vs the baseline's own cross-window texture) while its p25 tail worsens.
Standing threshold reaffirmed: any future recent claim needs the conjunction
(mean + p25 + no-regression), not a mean alone.

## 3. Subsystem audit

Last five bets: V236 chop throttle (composite/OHLCV) → V237 BTC-residualization
(composite) → V238 frozen-series feed (info layer) → V239/V240 universe
(selection; V240 ADOPTED, baseline moved) → V241 reasoning layer (basket
review, NEW dimension). No two consecutive bets on the same subsystem since
V237; V240 broke the refutation streak with an adopt. No Goodhart window:
V241 targeted the full walk-forward distribution, not a single snapshot.
Named dead end from this cycle: **whole-basket LLM review as an expectancy
source** — 99.6% intervention with zero pooled edge means the model's
portfolio-level judgment is uncorrelated with realized PnL at this
granularity. Do not re-run the same shape with a different model/prompt.

## 4. Revert-and-branch

Nothing to revert: the layer never touched the default path (flag OFF, not
constructed; OFF cells byte-identical to baseline). Structural delta of main
vs the baseline-holding configuration: **zero**. Branch decision: the
scaffolding (hermetic cache, tracer, fill/replay contract) is sound
infrastructure and stays; the *bet* is retired unless the counterfactual drop
scorer (V241.md obs delta #1 — computable from EXISTING ledgers for $0) shows
the drop set has negative-PnL skew. That scorer is the gate for any
veto-only/confidence-gated variant; no grid before that separator proof
(standing V234 rule).

## 5. Untouched dimensions (next bet comes from here)

- **Corr-spike portfolio tail cap** — spec complete (V237.md), $0 offline
  PCA/copula calibration, never executed. Strongest candidate; targets
  exactly the tail (p25) dimension V241 failed on.
- **gdelt solo cell** — source frozen in V240.C, never evaluated in-grid.
- **{dxy, yield_curve} subset** of frozen-series (V240.B: benign near-inert
  solo; cheap combined cell).
- **Exit-side adaptivity** (hold-time / profit-taking by regime) — the entire
  V148→V241 arc has been entry/selection/sizing; exits untouched for 40+
  versions.
- **Universe blacklist extension {ADA,NEAR,ARB}** — parked on
  `v243-portfolio-sep` (Opus), missed its gate by $18; re-scorable against
  new evidence rather than re-run.
- Version numbering note: V242/V243 consumed by parallel Opus tracks (both
  refuted/parked); next pre-reg here is **V244**.

## 6. Observability-gap audit

Shipped this cycle: the inertness tracer + intervention report (standing
instruments; they did their phase-0 job). The gap they exposed: **activity ≠
quality**. Three deltas recorded in V241.md and OBSERVABILITY-BACKLOG.md:
counterfactual drop scorer (S — ship BEFORE any reasoning revisit; it was
computable 4h before the grid ran), intervention→PnL attribution ledger (M),
fill cost predictor (S). Next blind spot named: we still cannot attribute a
single window's Δ to a specific intervention without a manual trade diff.
