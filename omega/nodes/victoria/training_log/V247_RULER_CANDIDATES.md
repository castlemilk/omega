# V247 Phase 1 — Ruler-repair candidates

**Date:** 2026-07-13 · **Author:** claude (Fable 5)
**Input:** `V247_RULER.md` (Phase 0). Recent MDE $1,043 at n=10; pooled MDE
$875 (V246-class low-coupling) / $633 (near-inert) at n=32.
**Anti-Goodhart guard (standing):** V241–V246 verdicts are NOT re-adjudicated
under any bar produced here. New bars bind only bets pre-registered after
this document.

## Candidate α — widen the window manifest

**How many more windows exist?** The frozen data is 2020-01→2026-06 daily
OHLCV via the V215 freeze recipe (`fetch_ohlcv_historical`, ccxt/Binance).
Only the 32 manifest window FILES exist on disk; every additional window
requires a network re-fetch of historical klines (same recipe/source — cheap
and historical, but it IS a fetch; "no extra data acquisition" does not
strictly hold).

Three sub-paths, each with a hard problem:

1. **Refetch the 20 dropped offset-45d windows** (the V235 supplement pass
   labeled all 26 offset windows and kept only the 6 recent ones).
   → pooled n 32→52, **recent n unchanged** (the offset series' recent
   windows are already in). Every offset window overlaps two primary
   neighbors by 45d, so nominal n=52 overstates information; pooled SE
   should then be computed cluster-robust (cluster = calendar quarter).
   Cost: fetch ~minutes + 20 OFF-arm fills ≈ 1.2h; future grids 104 cells
   ≈ 6h (vs 3.7h today) at the measured ~3.5 min/cell. Honest gain:
   pooled MDE ~$875 → ~$750 (less than the naive √(52/32) because of
   overlap). **Does not touch the recent problem.**
2. **Denser offsets (30d/15d stride) to harvest more recent windows.**
   Recent occupies a fixed set of calendar stretches; 90d windows at 30d
   stride re-sample the same stretches with 67% overlap. Effective recent
   n grows from 10 to perhaps 13–15, MDE $1,043 → ~$880. Not $500-class.
3. **Shorter windows (45–60d) to multiply non-overlapping count.**
   **INFEASIBLE with the current replay.** ReplayIngestionNode needs a
   30-bar warmup and the grid caps cycles at `min_bars − 31`: a 45d window
   leaves ~15 honest cycles — below typical hold lengths (trades wouldn't
   close); a 60d window leaves ~30 cycles and halves per-window trade
   count while breaking comparability with every committed 90d result.

**α verdict: PARTIAL.** The manifest can be widened for POOLED inference
(sub-path 1, honest, ~1.2h sunk + ~60% grid-cost increase forever), but no
α variant reaches a $500-class recent MDE — the binding limit is calendar:
recent/chop stretches in 2020–2026 support ~10–15 independent 90d windows,
full stop. The Phase 0 guardrail arithmetic (need ~46) cannot be satisfied
from this span at this granularity.

## Candidate β — pooled-gated bars with a recent no-regression floor

Reframe acceptance from "recent mean-Δ ≥ +$100" (unfalsifiable, MDE $1,043)
to a conjunction the instrument can actually adjudicate:

- **Primary gate (pooled, n=32):** pooled mean-Δ ≥ a bar set at/above the
  mechanism-class 2·SE (V246-class: $625; pre-registered as a fixed $
  number), AND seeded-bootstrap 95% CI on pooled mean-Δ excludes 0.
- **Recent no-regression floor (one-sided):** recent mean-Δ ≥ −1·SE
  (≈ −$360 for low-coupling mechanisms). Power check from the ruler: this
  floor rejects a true −$900 recent regression with ~93% probability and a
  true −$500 with ~65% — it cannot certify recent improvement (nothing at
  n=10 can) but it guards against the failure mode that matters.
- **Dual-tail guard (from Phase 2 instrumentation):** report BOTH Δ-p25 and
  level-p25 per regime; the pre-reg must name which one it gates on. This
  is the named trade-off of β — a pooled gate can accept bets that worsen
  the recent Δ-tail — so the tail is surfaced as an explicit co-gate, not
  silently dropped.

**β verdict: PRIMARY.** It uses the only sub-instrument with sub-$1,000
resolution (pooled, n=32), costs zero new data and zero extra grid hours,
and converts "recent" from an unfalsifiable target into a guarded floor.
Trade-off is real but instrumented (dual-tail + floor).

## Candidate γ — block bootstrap on within-window trades

**Measured, and REFUTED by the measurement.** Joining V246's ON/OFF ledgers
per window (key `(cycle,symbol,side)`) and comparing observed between-window
Var(Δ) against the iid trade-resampling variance (Σ per-trade Δ² structure):

| regime | observed between-window sd(Δ) | iid trade-bootstrap sd(Δ) | ratio Var_between/Var_iid |
|---|---:|---:|---:|
| recent | $1,149 | $2,419 | 0.23 |
| trend | $2,699 | $7,837 | 0.12 |
| crisis | $1,023 | $3,406 | 0.09 |
| pooled | $1,767 | $5,037 | 0.12 |

Within-window trade Δs are strongly **anti-correlated** (capital coupling:
an exit change that removes one trade frees budget for another whose Δ
partially cancels — ~30% of all trades are ON-only/OFF-only). A trade-level
resample destroys that cancellation structure and would report CIs 2–3×
WIDER than the truth, in the wrong direction from the hoped-for repair. The
window is the correct exchangeable unit; there is no free n inside it.

## Recommendation

**Adopt β now; α sub-path 1 as a deferred, optional pooled-sharpener; γ
rejected.**

Concretely, for the next pre-registration (Phase 3):

1. Gates move to the pooled instrument with a recent no-regression floor
   and a pre-named tail metric (β structure above). Exact $ bars are fixed
   in the pre-reg BEFORE any run, per REFLECTION_V246.
2. α sub-path 1 (20 offset windows, pooled n→52 cluster-robust) is queued
   as a separate infrastructure bet — worth doing when a pooled verdict
   lands within ~$150 of its bar, not before (it permanently raises every
   future grid's cost ~60% for a ~15% MDE gain).
3. The stagnation-era refutations all stand. Nothing here re-opens them.

**"Profitable reliably" restated under the new ruler:** the Phase 0 level
table shows the baseline's recent and crisis LEVEL means are themselves
indistinguishable from zero at current n. The honest objective the
instrument supports is: grow POOLED mean-Δ with certified no-regression
floors per regime — i.e., accumulate pooled edge without buying it with any
regime's tail.
