# REFLECTION after V246 — three consecutive refutations; the binding constraint is the objective, not the mechanism menu

**Date:** 2026-07-13 · **Author:** claude (Fable 5)
**Trigger:** skill trigger #1 (stagnation): V244, V245, V246 are three
consecutive post-REFLECTION_V241 refutations with no baseline move. Trigger #0
(Goodhart window) does NOT fire — all three targeted the full 32-window
distribution, not a single snapshot. Trigger #3 (subsystem loop) does NOT
fire — three different subsystems (portfolio-corr sizing, info feed, exit
layer).

## 1. Eval stability

Byte-deterministic from committed state throughout: V245 and V246 grids ran
64 cells each with 0 determinism FAILs, all $0.00 spread, sentinels N=2
byte-identical; V246's OFF arm reproduced the V240 confirm cell byte-identical
ex-timestamp; the V240 baseline re-certified 4/4 at session start. Replicate
noise floor: **$0.00**. All uncertainty is window-sampling, not eval noise.

## 2. Variance estimate

From the V246 grid's per-window Δ distribution (multi-seed is moot, seed
pinned, replicates identical):

| regime | n | Δ sd | 2·SE(Δ mean) | V246 Δ mean |
|---|---:|---:|---:|---:|
| crisis | 12 | $1,023 | $591 | +$523 |
| trend | 10 | $2,699 | $1,707 | +$1,307 |
| recent | 10 | $1,149 | $727 | +$72 |
| pooled | 32 | $1,767 | $625 | **+$627** |

Standing thresholds implied: **a recent mean claim below ~$727 is
unfalsifiable at n=10**; the launch-standard +$100 recent bar is 7× below the
noise floor of the instrument it is measured on. V246's pooled mean sits
exactly at 2·SE — the first plausibly-real pooled effect since V240 — while
its recent number is uninterpretable. This mismatch between bar granularity
and instrument resolution is the central finding of this reflection.

## 3. Subsystem audit

Post-REFLECTION_V241 bets: V244 portfolio-corr sizing cap (REFUTED at $0 —
zero winner/loser separation), V245 gdelt info feed (REFUTED at grid —
pooled-flat-with-variance, the 5th such info-feed result since V236), V246
exit adaptivity (REFUTED at grid — pooled mean +$627 ≈ 2·SE but recent flat
and Δ-tail negative). No two touched the same subsystem. Wider arc since
V236: **eight mechanism families** (chop throttle, β-residual, frozen-series
feeds, whale gate, LLM review, corr cap, gdelt, exits) have failed to move
the RECENT regime; the one adopted change (V240 selective universe) came from
the universe/selection dimension. The dead end is not a subsystem — it is
**"recent mean-Δ ≥ +$100 at n=10 windows" as a falsifiable objective.**

## 4. Revert-and-branch

Nothing to revert: all three bets are flag-OFF with OFF byte-identical proofs;
main == baseline-holding configuration structurally. Branch decision: stay on
main; the V246 engine parametrization stays as dormant, tested infrastructure
(same posture as the V240.D scaffolding and the V131-era ExitController it
generalizes).

## 5. Untouched dimensions (and the objective question that gates them)

**The objective question first (this reflection's actual recommendation):**
recent at n=10 / 2·SE ≈ $727 cannot adjudicate +$100-class effects. The next
pre-registration must either (a) re-derive its bars from the measured noise
floor (e.g. gate on POOLED mean/tail where n=32 gives 2·SE ≈ $625, with
recent as a no-regression floor rather than a target), or (b) grow n for
recent (more recent-regime windows in the manifest — `walk_forward_freeze.py`
can cut 2023→2026 into more, shorter windows at the cost of per-window trade
count). Explicit anti-Goodhart guard: V246 is NOT re-adjudicated under any
new bars; bar redesign applies only to bets pre-registered AFTER this
document, and the choice (a)/(b) must be fixed in the pre-reg before results
exist.

Untouched mechanism dimensions, in rough order of prior:

1. **Regime-conditional exit parameters** — V246 tested ONE global (keep,
   hold) pair; its scorer showed regime-heterogeneous effects and the grid
   confirmed (trend +$1,307 / crisis +$523 / recent +$72). Same subsystem as
   V246 but a different bet: exits adapted BY regime, gated on the redesigned
   objective above.
2. **V243-A blacklist extension {ADA,NEAR,ARB}** — parked at a $18 gate miss
   on the Opus track; universe/selection is the ONLY dimension that has ever
   produced an adopt in this era (V240). Re-score against the V246-era
   variance numbers.
3. **Sizing surface reshaping** (conviction→size curve, kelly clamp) — never
   touched in the walk-forward era.
4. **Intraday granularity** — new data class (the bar-mark analysis showed
   winners' intra-bar excursions are invisible at daily closes); expensive,
   queue only with a concrete feed plan.
5. **Entry-side anything: CLOSED** (five refutations); portfolio-corr:
   CLOSED (V237 clause + V244).

## 6. Observability-gap audit

What would have caught V246's scorer-vs-grid inversion sooner: nothing
cheaper existed — the scorer was validated against realized ledgers (99.1%
exit-cycle reproduction) and the divergence came from re-entry coupling,
which no per-trade replay can see. The gap is *capital-coupling attribution*.
Deltas:

1. **(S, ship with V247) Aggregator dual-tail report:** every future
   aggregator reports BOTH Δ-distribution p25 AND level-p25 side by side
   (V245/V246 both showed level-tail tightening while Δ-p25 fired — the
   falsifier metric and the stated intent "tail must not worsen" diverge;
   future pre-regs must name which one they gate on, and why).
2. **(S, ship with V247) Re-entry coupling counter:** ON-vs-OFF ledger join
   already exists (`trade_field_diff.py` pattern) — emit per-window counts of
   trades present in ON but not OFF (and vice versa) keyed by open cycle, so
   "the mechanism changed WHICH trades exist, not just their exits" is a
   one-line read instead of a manual diff. V246: 343→327 trades went
   unnoticed until the verdict.
3. **(S, queued) `scripts/ledger_join.py`** — still pending from V245 #1
   (fourth re-derivation avoided).

## Conclusion

The mechanism menu is not exhausted, but the recent-regime objective as
currently posed is unfalsifiable at the instrument's resolution. V247 must
begin by re-deriving its acceptance bars from §2's variance table (choice
fixed in pre-reg), then draw its mechanism from §5 — regime-conditional
exits and the V243-A universe re-score are the two live candidates.
