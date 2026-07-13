# V247 Phase 0 — Ruler diagnostic

**Date:** 2026-07-13 · **Author:** claude (Fable 5)
**Mandate:** REFLECTION_V246 §2/§5 — quantify the walk-forward instrument's
resolution BEFORE proposing any new grid. This document is the deliverable;
no mechanism is pre-registered here.

**Reproduction:** `python3 scripts/v247_ruler.py` (deterministic, seed 42,
reads the four committed grid `distribution.json` files on
`$OMEGA_AUDIT_OUTPUT_DIR`; writes `data/v247_ruler.json`). Replicate noise is
$0.00 (byte-deterministic eval), so ALL variance below is window-sampling
variance — the ruler itself, not eval noise.

## 1. What the instrument measures

A verdict is a **paired per-window Δ (ON − OFF)** aggregated per regime.
Two distributions matter and they are NOT the same ruler:

- **OFF-arm levels** — how heterogeneous the windows themselves are. This is
  the $27k-spread problem; it can never be the gate.
- **Paired Δ** — the actual verdict instrument. Pairing cancels most window
  heterogeneity; how much survives depends on the mechanism's coupling
  (an entry-side mechanism that changes WHICH trades exist decouples the
  arms and inflates Δ-sd; a pure exit-side tweak keeps them coupled).

We have four completed paired grids to calibrate Δ-sd empirically:
V241 (reasoning, heavy intervention), V243-A (blacklist ext), V245 (gdelt),
V246 (exit adaptivity).

## 2. OFF-arm (baseline) level distribution — window PnL, USD

| regime | n | mean | sd | SE | 2·SE | p10 | p25 | p75 | p90 | boot 95% CI (mean) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| recent | 10 | +30 | 1,790 | 566 | 1,132 | -1,198 | -857 | +603 | +2,641 | [-939, +1,150] |
| trend | 10 | +2,997 | 5,865 | 1,855 | 3,709 | -1,426 | -572 | +4,182 | +8,582 | [+55, +6,829] |
| crisis | 12 | +599 | 3,841 | 1,109 | 2,217 | -2,638 | -1,089 | +1,243 | +3,897 | [-1,284, +2,828] |
| pooled | 32 | +1,170 | 4,216 | 745 | 1,491 | -2,059 | -839 | +2,169 | +4,630 | [-131, +2,718] |

Read: the standing baseline "recent +$30 / trend +$2,997 / crisis +$599" is
itself a draw — the bootstrap CI on the recent LEVEL mean is [-$939, +$1,150].
Only trend's level mean is distinguishable from zero. **The baseline is not
provably profitable in recent or crisis at this N.** (This is the "get
profitable reliably" framing made quantitative.)

## 3. Paired Δ distributions — the verdict instrument

| grid | regime | n | Δ mean | Δ sd | SE | 2·SE | Δ p25 | boot 95% CI (Δ mean) |
|---|---|---:|---:|---:|---:|---:|---:|---|
| v241_reasoning | recent | 10 | +227 | 1,660 | 525 | 1,050 | -705 | [-675, +1,267] |
| v241_reasoning | trend | 10 | -69 | 7,354 | 2,326 | 4,651 | -938 | [-4,866, +3,610] |
| v241_reasoning | crisis | 12 | -48 | 2,848 | 822 | 1,644 | -910 | [-1,703, +1,380] |
| v241_reasoning | pooled | 32 | +31 | 4,404 | 779 | 1,557 | -910 | [-1,637, +1,388] |
| v243a_blacklist_ext | recent | 10 | +232 | 1,127 | 356 | 713 | -236 | [-434, +896] |
| v243a_blacklist_ext | trend | 10 | +2,007 | 6,596 | 2,086 | 4,172 | -632 | [-593, +6,363] |
| v243a_blacklist_ext | crisis | 12 | +1,326 | 2,581 | 745 | 1,490 | -464 | [+56, +2,831] |
| v243a_blacklist_ext | pooled | 32 | +1,197 | 3,985 | 705 | 1,409 | -529 | [+110, +2,735] |
| v245_gdelt | recent | 10 | -129 | 1,206 | 381 | 763 | -641 | [-762, +646] |
| v245_gdelt | trend | 10 | -236 | 1,414 | 447 | 894 | -1,291 | [-987, +659] |
| v245_gdelt | crisis | 12 | +220 | 1,289 | 372 | 744 | -187 | [-425, +969] |
| v245_gdelt | pooled | 32 | -31 | 1,278 | 226 | 452 | -716 | [-449, +418] |
| v246_exit_adapt | recent | 10 | +72 | 1,149 | 363 | 727 | -407 | [-572, +783] |
| v246_exit_adapt | trend | 10 | +1,307 | 2,699 | 854 | 1,707 | -444 | [-201, +2,969] |
| v246_exit_adapt | crisis | 12 | +523 | 1,023 | 295 | 591 | +0 | [-26, +1,082] |
| v246_exit_adapt | pooled | 32 | +627 | 1,767 | 312 | 625 | -378 | [+56, +1,270] |

Structural findings:

1. **Δ-sd is mechanism-conditional, by up to 5×.** Recent Δ-sd is tightly
   clustered ($1,127–$1,660) but trend Δ-sd ranges $1,414 (gdelt, near-inert)
   to $7,354 (reasoning, 99.6% intervention). Coupling — how many trades the
   mechanism creates/destroys vs merely resizes — is the variance driver.
   Any future pre-reg must state its expected coupling class.
2. **Trend is the WORST-instrumented regime, not recent.** Trend 2·SE is
   $1,707–$4,651 across mechanisms. The V246 "trend +$1,307" queued result is
   inside even its own best-case noise ($1,707). Trend claims at n=10 are
   effectively unfalsifiable for any mechanism that touches trade selection.
3. **Pooling works.** Pooled SE ($226–$779) is 1.5–3× tighter than any
   per-regime SE for the same mechanism, because n=32 and cross-regime
   heterogeneity partially cancels in the paired Δ.

## 4. MDE at 80% power, α=0.05 (median Δ-sd across the 4 grids)

MDE = (1.96+0.84)·sd/√n; min-N = ⌈((1.96+0.84)·sd/E)²⌉+2 (small-sample
correction). Normal approximation — slightly optimistic below n≈15.

| regime | n now | median Δ sd | Δ sd range | **MDE now** | min-N $100 | $250 | $500 | $1000 |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| recent | 10 | 1,178 | [1,127, 1,660] | **$1,043** | 1,091 | 177 | **46** | 13 |
| trend | 10 | 4,648 | [1,414, 7,354] | **$4,118** | 16,959 | 2,715 | 681 | 172 |
| crisis | 12 | 1,935 | [1,023, 2,848] | **$1,565** | 2,941 | 473 | 120 | 32 |
| pooled | 32 | 2,876 | [1,278, 4,404] | **$1,425** | 6,496 | 1,041 | 262 | 67 |

Mechanism-conditional pooled MDE (more decision-relevant than the median row):
for a **V246-class low-coupling mechanism** (pooled Δ-sd $1,767) the pooled
MDE at n=32 is **$875**; for a V245-class near-inert feed ($1,278) it is
**$633**. For a V241-class heavy intervention ($4,404) it is $2,180 —
heavy-coupling mechanisms are unmeasurable on this manifest, full stop.

## 5. The queued results, re-read against the ruler (NOT re-adjudicated)

Anti-Goodhart guard: these verdicts STAND under the bars they were
pre-registered with. This section only states what the instrument can say.

- **V246 pooled +$627** — exactly at 2·SE ($625); boot CI [+$56, +$1,270]
  excludes zero by a hair. Plausible, unconfirmed. Below the $875
  V246-class pooled MDE → a same-size true effect would be detected <80%
  of the time. REFUTED verdict stands.
- **V243-A pooled +$1,197** — 2·SE $1,409, boot CI [+$110, +$2,735].
  Same status: plausible, unconfirmed, and its coupling (universe change ⇒
  different trades) puts it in the high-variance class. REFUTED-at-bar
  verdict stands.
- **V246 trend +$1,307** — inside noise even at V246's own trend 2·SE
  ($1,707). Uninterpretable. Stands refuted.

## 6. Guardrail assessment (the mandated STOP check)

**The condition fires at the per-regime level: the current manifest CANNOT
support a $500 recent effect at 80% power.** Recent MDE is $1,043; $500
detection needs ~46 recent windows vs the 10 we have. No bar redesign changes
that arithmetic for a RECENT-MEAN target.

It does NOT force a full stop, for two reasons the Phase 1 doc must weigh:

1. **More windows exist in already-frozen data** (candidate α). The frozen
   series span 2020-01→2026-06 daily; the manifest uses 90d/90d + a 45d-offset
   supplement. Shorter windows and/or denser offsets can raise recent-n
   without acquiring any new external data — but overlapping windows are NOT
   independent, so nominal n ≠ effective n. Whether α can reach ~$500-class
   recent MDE honestly is exactly Phase 1's α analysis.
2. **The pooled instrument already resolves $875-class effects** for
   low-coupling mechanisms (candidate β reframes the gate onto it, with
   recent as a one-sided no-regression floor — a floor does not need to
   DETECT small effects, only to reject large regressions, which the recent
   arm can do at ~$900 one-sided).

**Ruling:** V247 proceeds to Phase 1. If Phase 1's α analysis shows the
frozen data cannot honestly deliver ≥~2× effective recent-n AND β is judged
unacceptable (tail-risk trade-off), THEN the hard stop fires and V247
becomes "acquire more data."

## 7. Standing thresholds (until superseded by the Phase 1 bar redesign)

- Recent mean-Δ claims below **$1,043** at n=10: unfalsifiable, may not be
  used as an acceptance bar or reported as signal.
- Trend mean-Δ claims below **$4,118** (median-sd basis) at n=10: same.
- Crisis mean-Δ claims below **$1,565** at n=12: same.
- Pooled mean-Δ: resolvable down to ~**$875** (low-coupling mechanisms only).
- Any pre-reg must declare its expected coupling class (exit-only /
  sizing-only / selection-changing) — it determines which MDE row applies.
