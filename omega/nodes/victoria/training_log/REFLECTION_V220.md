# Reflection after V220 — the fence peels to the next layer (sizing/exit magnitude)

**Date:** 2026-06-11
**Author:** claude
**Trigger:** Eval-noise flag (#2) — a change pre-registered to *close* trend_OFF
determinism instead left it FAIL and regressed recent_OFF PASS→FAIL. Consecutive
determinism failures on trend_OFF (V219 $597 → V220 $2,851). Determinism is the
gating blocker; the IC-wiring bet cannot run on a non-deterministic baseline.

## The pattern — each fence reveals the next layer

This eval has now peeled **four** floating-point / state order-channels, each one
exposed only after the previous was closed:

| Version | Channel closed | Layer | How named |
|---|---|---|---|
| V211 | `basket_std`/`basket_mean` cross-sectional sums | signal aggregation | hand bisect → 2 `sorted()` wraps |
| V217 | Apple vecLib BLAS multi-threaded parallel-reduction order | numpy/BLAS | per-field IEEE-754 fingerprint (`per_field_diff.py`) |
| V219→V220 | `basic_signals.value` sub-ulp sign-flip (entry-flip) | composite mean → **entry decision** | per-field bisect → `math.fsum` |
| **V220 (new)** | **sizing/exit PnL magnitude** | **trade-PnL accounting** | **trade count locked 26/26, PnL still spans $2,851** |

The shape is consistent: **a binary channel (entry in/out) sits on top of an analog
channel (dollar magnitude).** While the binary channel is open, its single-trade
flips dominate the spread and hide the analog channel beneath. Close the binary
channel and the analog one becomes the dominant signal. V220 is the moment the
binary entry channel finally locked (26/26 on both trend arms) and the analog
sizing/exit channel underneath stepped into view.

## Hypothesis to carry into V221

**There is an architectural sizing/exit pathway that compounds tiny FP differences
into $1–3K PnL deltas — structurally different from entry decisions.** Entry
decisions are *threshold-clipped*: a sub-ulp wobble either does or doesn't cross a
conviction boundary, so it is binary and, once the composite is fsum-fenced,
deterministic. Sizing and exit-price/PnL accounting are *continuous*: a sub-ulp
wobble in a position size or an exit price flows linearly into dollar PnL with **no
threshold to clip it**, and it can compound across 26 trades into thousands of
dollars. That is why the same 26 trades produce $697 vs $3,549. The channel was
always there; it was masked, not absent.

Corollary for the bisect: the divergence will **not** show at the cycle-1 signal
fingerprint (that layer is clean post-V217 BLAS-pin + V220 fsum). It will show at
the **trade level** — entry_price, exit_price, position_size, slippage, fees. The
existing `per_field_diff.py` instruments the signal layer and will report "no
divergence," which is precisely the blind spot.

## The six required answers (abbreviated — determinism, not noise-floor, is blocked)

1. **Eval stability.** Not a hidden-RNG noise question this time — it is a *named,
   reproducible* order-channel (same code, same seed, deterministic divergence
   driven by FP summation/wall-clock order, not stochastic). The "noise floor" is
   $0.00 once the channel is fenced (crisis_OFF proves it: $0.72 with the channel
   absent). So the action is **fence the channel**, not estimate σ.
2. **Variance estimate.** Deferred — multi-seed σ is meaningless while a
   deterministic order-channel dominates the spread ($2,851 ≫ any plausible σ). Run
   the N-seed audit only *after* V221 restores 4/4 hermetic, on the new baseline.
3. **Subsystem audit.** Last 4 versions all targeted the **determinism substrate**
   (V217 BLAS, V219 diagnosis, V220 fsum, V221 will be sizing/exit). This is *not*
   the V199–V202 "tuning a dead subsystem" trap — each fence verifiably closed its
   named channel (V217 6/6, V220 entry-count locked). It is a legitimate peel of a
   layered defect, not a parameter walk. **But it has consumed 4 versions of pure
   substrate work with zero strategy progress** — the IC-wiring lever (the actual
   alpha bet) has been blocked since V218. V221 must be the *last* determinism
   version before either (a) 4/4 is restored and V222 wires ICs, or (b) we accept a
   bounded-noise baseline and measure ICs against it with a documented threshold.
4. **Revert-and-branch.** Not applicable — there is no high-water-holding baseline
   to revert to that is *more* deterministic; the channel is intrinsic to real-macro
   inputs (V219 substrate) and would re-appear on any branch using committed macro.
   The fences are additive and correct; keep all of them.
5. **Untouched dimensions.** Sizing/exit determinism itself is the untouched
   dimension — every prior fence targeted the *signal/entry* path; none touched the
   *sizing/exit/PnL-accounting* path. Beyond determinism, still untouched in 10+
   versions: exit-strategy variants, snapshot diversity (only 3 fixed gate
   snapshots), per-regime sizing curves, and the IC-weighting subsystem (inert since
   V218). V221's hypothesis comes from this list (sizing/exit determinism); V222's
   from IC-weighting.
6. **Observability-gap audit.** See below — the headline gap is that
   `per_field_diff.py` stops at the signal layer.

## Observability-gap audit (required output #6)

**What would have caught this sooner:** an instrument that diffs **trade-level**
fields, not just signal-level. We have a clean cycle-1 signal fingerprint (V214 #4)
and a per-field IEEE-754 signal fingerprint (V217), but **nothing fingerprints the
trade ledger** — so a channel that is invisible at the signal layer and only emerges
in position sizing / exit PnL is undetectable until it flips a trade count or blows
up a spread. V220 is exactly that: signal layer clean, trade layer divergent.

**Next blind spot:** anywhere a continuous (un-thresholded) quantity is computed
from an unordered FP reduction or a wall-clock read *downstream of the signal layer*
— position sizing, exit-price interpolation, slippage/fee accrual, PnL aggregation.
`check_no_wallclock.py` only scans 2 declared sizing modules; the channel may live
outside them.

Proposed deltas (ship the 2 cheapest with V221; queue the rest):

| # | Delta | Where | Effort | Ship/Queue |
|---|---|---|---|---|
| #13 | **Extend `per_field_diff.py` to trade-level fields** (entry_price, exit_price, position_size, slippage, fees) — align trades by `(cycle,symbol,side)`, diff PnL contributors row-by-row | `scripts/per_field_diff.py` | **S** | **SHIP V221** |
| #14 | **Trade-ledger fingerprint** in the determinism gate's FAIL path — when trade count matches but PnL spread > floor, auto-emit the trade-level diff (so the next magnitude channel self-names) | `scripts/check_determinism.sh` + `run_training.py` | **S** | **SHIP V221** |
| #15 | Widen `check_no_wallclock.py` AST scan beyond the 2 declared sizing modules to the full strategy/exit path | `scripts/check_no_wallclock.py` | M | queue |
| #16 | A "channel-genealogy" line in each determinism summary: which prior fences are active + which layer the residual sits in (signal vs trade) | `check_determinism.sh` | M | queue |
| #17 | Per-trade PnL-contributor decomposition (size × price-move × side, minus fees) logged per trade, so a magnitude divergence points to *which factor* | `strategy.py` trade log | L | queue |

## V221 brief (verbatim — carried into V220.md "Next steps" and OBSERVABILITY-BACKLOG.md)

> **V221 = sizing/exit PnL-magnitude bisect (NOT IC wiring — IC wiring pushed to
> V222, blocked until determinism is restored).** Per-cell bisect using an extended
> `per_field_diff.py` on the trend_OFF FAIL replicates (r1 $697 vs r2 $3,549,
> identical 26 trades) — name which sizing/exit field diverges first **at the
> trade-PnL level**, not the signal-entry level (the cycle-1 signal layer is now
> clean post-V217+V220). FP-order audit pattern is the first check: grep the
> sizing/exit path for unsorted FP reductions and residual wall-clock reads.
> Falsifier: trend_OFF and recent_OFF both return to PASS with crisis_OFF staying
> PASS = 4/4 hermetic. Observability shipped V221: extend `per_field_diff.py` to
> trade-level fields (#13) + auto-emit a trade-level diff on the magnitude-FAIL path
> (#14).
