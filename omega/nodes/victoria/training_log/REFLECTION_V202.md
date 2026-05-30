# Reflection — V199–V202 trajectory (post-V202)

**Date:** 2026-05-30
**Author:** claude (mandatory reflection trigger: 3 versions failed to break high-water, crisis static for 4 versions, current hypothesis cluster unchanged)
**Scope:** V199 → V202 four-version arc. Question: are we patching reactively in too narrow a space and confusing eval noise for signal?

This document is brutally honest by request. It is NOT a plan. V203
is proposed in a separate **Next steps** section at the end.

---

## 1. Is the eval itself stable?

**Probably not at the precision we've been treating it.** Direct
evidence from the existing artifacts, no re-runs needed:

I aligned trades across versions by `(cycle, symbol, side)` — the
stable identity of a backtest setup. Result:

| Gate     | Versions          | Same trade IDs | PnL differs on...    | Total PnL delta |
|----------|-------------------|----------------|----------------------|----------------:|
| trend    | V199 → V200       | 106 / 106      | **68 (64%)**         | +$46 (noise)    |
| trend    | V200 → V201       | 94 shared (V200-only=12, V201-only=11) | 67 (71% of shared) | +$5,086 (real) |
| trend    | V201 → V202       | 98 shared (V201-only=7,  V202-only=8)  | 58 (59% of shared) | −$4,166 (real) |
| crisis   | V199 → V200       | 64 / 64        | **44 (69%)**         | −$92 (noise)    |
| crisis   | V200 → V201       | 63 shared (V200-only=1) | 44 (70%)        | +$414 (noise)   |
| crisis   | V201 → V202       | 63 / 63        | 43 (68%)             | −$7 (noise)     |
| recent   | V199 → V200       | 67 shared (V200-only=3) | 48 (72%)        | −$2,051 (mixed) |
| recent   | V200 → V201       | 70 / 70        | 54 (77%)             | −$204 (noise)   |
| recent   | V201 → V202       | 70 / 70        | 51 (73%)             | +$6 (noise)     |

**What this means:**

- On gates where the code change pre-registered as a no-op (V200 on
  trend/crisis, V202's size/kelly bundle on recent), **60–70% of
  identically-IDed trades have non-zero PnL drift between
  versions.** Same cycle, same symbol, same side, but different
  entry/exit/PnL. That is the signature of dict-iteration / RNG
  consumption coupling — the new code branch isn't firing, but it
  exists in the source, and it perturbs downstream draw order.
- The aggregate gate PnL hides this. Individual-trade noise mostly
  cancels in aggregate; the totals come out within $50–$500. So
  we've been *reading* the eval as stable when the *trade-level*
  evidence is that it isn't.
- The threshold for "this delta is real" should not be a few
  hundred dollars. The V200 → V201 trend delta of **+$5,086** is
  real (12 new trades + 11 dropped + per-trade shifts on the
  shared 94). The V201 → V202 trend delta of **−$4,166** is real
  by the same standard. But V199 → V200 trend's +$46 was *all
  noise*, and V199 → V200 crisis's −$92 was *all noise*.

**Implication for "V199 recent high-water = +$2,478":** we have
exactly **one observation at one seed at one snapshot**. The
**immediate next observation** of the same snapshot under a near-
no-op change (V200) read **+$427** — a $2,051 swing. If V199's
+$2,478 is one tail of a wide noise distribution, **the high-water
mark we've been chasing for three versions may not exist**.

This needs to be measured before any more parameter-pulling. See
"Variance estimate to commission" below.

---

## 2. Are we patching reactively in too narrow a space?

**Yes.** Last four hypotheses, in chronological order:

| Version | What it changed                                       | Subsystem |
|---------|-------------------------------------------------------|-----------|
| V199    | Add per-ticker carry signal + carry-only sub-strategy | carry injection (NEW) |
| V200    | HMM-gated suppressor on the V199 carry injection       | same |
| V201    | Remove `crisis_short_bias` threshold discount (×0.6×0.6 → ×1.0) | crisis_short_bias entry-side |
| V202    | Remove `crisis_short_bias` size amp (×1.3 short / ×0.5 long) + restore half-Kelly | crisis_short_bias sizing |

Two subsystems in four versions. **Both about `crisis_short_bias`
or its interaction with carry injection.** V199's carry path
introduced cross-coupling that V200 tried to gate; V201/V202 then
pulled two of the four amplifier branches inside `crisis_short_bias`.

The whole `crisis_short_bias` design has **four amplification
branches** stacked (threshold ×0.6 at line 1132, threshold ×0.6
again at 1476, size ×1.3 short / ×0.5 long at 2816, half-Kelly skip
at 2841). V201 pulled branches 1+2. V202 pulled branches 3+4. **The
crisis PnL has not moved** across either pull — same 63 trades,
same ≈−$19K loss, same 33% WR. That is not "we haven't found the
right amplifier"; that is "the binding constraint is not in this
subsystem."

The pattern is recognisable from the V148→V189 phase too: V178,
V181, V183, V189 each added a new entry gate; V189's retro said
"don't add more entry gates." We're doing the entry/sizing equivalent
on `crisis_short_bias`. Same shape, same dead end.

---

## 3. Have we drifted from the actual best (V172)?

**Substantially, and recoverably.** V172 ran 64 trades on the trend
snapshot for +$18,437 (PnL/trade $288, 43.8% WR, PF 2.07). V202 runs
106 trades on the same snapshot for +$8,830 (PnL/trade $83, 37.7%
WR, PF 1.30).

Structural delta V172 → V202 includes everything from V173 onward:

- V173: ensemble strategy + VWAP + RSI-divergence
- V174: adaptive decay + adversarial gate
- V178: regime selector
- V180: short-side filter + long-side threshold override
- V182–V185: exit trail wiring + microstructure signals (VPIN / Kyle / OFI)
- V186: LLM tie-breaker + risk-scaling + kitchen-sink
- V196: strong-signal bypass
- V199: carry sub-strategy + per-ticker carry injection
- V200–V202: incremental fixes on V199/`crisis_short_bias`

The trend regression V172 → V199 is +$10,573 of PnL/trade lost
across 42 added trades. Some of those 42 are good (the V201 trend
recovery of +$5K came from this set), most are not. **Reverting
to V172's strategy.py and branching from there — keeping only the
specific additions whose unit value we can re-derive — is a
legitimate option** and is currently untested in the log.

---

## 4. What's NOT being tested?

Cataloguing the dimensions we've *not* touched in the last 10+
versions:

**Exit-side (the V202 retro flagged this and we didn't act on it
yet):**
- Per-regime trail multipliers (one knob for trend, another for crisis snapback)
- Time-stop / max-hold-cycles by regime
- R-multiple-based partial exits
- MAE-based stop adaptation

**Defensive abstention:**
- Skip crisis trading entirely (cash in the regime where we lose)
- Skip crisis *shorts* only (the failing direction in our 64 trades)
- Skip when HMM confidence < threshold

**Direction filters:**
- `skip crisis shorts when 1h momentum > 0` (snapback signature)
- Skip shorts on the cluster that consistently loses (NEAR, etc.)

**Sizing approaches not tried:**
- Volatility-targeted sizing (not Kelly)
- Confidence-weighted (HMM probability) sizing
- Per-symbol sizing caps (one bad symbol can't dominate the gate)

**Data / snapshot diversity (this is the one nobody has questioned):**
- The crisis snapshot is **one window** (`snap_crisis_2022h1`).
  If it's a particularly snapback-heavy month, no parameter pull
  inside the same window will fix it. **A second crisis snapshot
  (e.g. 2020-03, 2018-Q4) would tell us whether "crisis" is hard
  or this specific snapshot is hard.**
- Same applies to trend (only `snap_trending_2023q4`) and recent.

**Cross-asset structure:**
- Long-basket vs short-BTC hedge in crisis
- Funding-rate-arb sub-strategy (entirely different return source)

**Meta:**
- Multi-snapshot ensemble (best version per snapshot, weighted)
- Holdout validation (we don't have one — V172 may be the global
  optimum of a single train set)

This is a long list of unexplored axes. The fact that we are
re-tuning `crisis_short_bias` parameters for the third version in a
row while not a single one of these dimensions has been touched is
the structural problem.

---

## 5. The honest assessment

1. **The recent high-water +$2,478 (V199) is suspect.** Probably
   not noise alone — V200 added 3 real new trades worth −$2,127 in
   addition to ~30% per-trade drift. But the per-trade-drift noise
   floor on this snapshot is plausibly $500+. **V199's number has
   never been re-measured.** We've been treating it as a fixed
   target. It should be treated as one draw from an unknown
   distribution until variance is estimated.

2. **The trend high-water +$18,437 (V172) is from a different
   stack era.** We've been chasing it for 30 versions without
   matching it. The closest single recovery was V201 at +$12,996.
   The shortest path to +$18K may not be more `crisis_short_bias`
   tuning; it may be reverting to V172's strategy.py and
   surgically adding *only* the changes that have unit-tested
   positive impact (and none of the others).

3. **Crisis is structurally an exit/abstention problem, not an
   entry/sizing one.** Four versions of evidence:
   - V201 changes entry threshold: −$18,996 (vs V200 −$19,410). No move.
   - V202 changes entry size: −$19,003. No move.
   - Same 63 trades, same MAE/MFE profile, same 33% WR, same
     ≈$300 average loss across all four versions.
   - The signature is *the same trade losing the same way no matter
     how you change selection or sizing*. That is the signature of
     either (a) the exit-side bleeding, or (b) the snapshot being
     a single bad regime that no symmetric strategy can win on, or
     (c) the direction itself being wrong.

4. **The eval has hidden state coupling we are not measuring.**
   60–70% of identically-IDed trades drift PnL across "no-op" code
   changes. Aggregate PnL hides this because the noise cancels;
   individual gates with small deltas are noise. We've been
   reporting deltas of $100–$2K as "results." Some of those are
   noise.

5. **We are over-fitting to one snapshot per gate.** With one
   snapshot, the eval has no out-of-distribution signal. V199's
   recent number could be a snapshot-specific quirk we'd never
   reproduce on `snap_20260415` or `snap_20260413`. Same for V172
   on a second trending window.

---

## 6. What the reflection step should commission BEFORE V203

These three things must happen before another `crisis_short_bias`
parameter pull:

**A. Multi-seed variance estimate on the current best of each gate.**
- Re-run V199 (recent best) with `--seed` ∈ {1, 2, 3, 42} ×
  `--snapshot recent`. Four results, std deviation reported.
- Same for V201 (trend best) on `--snapshot trend`.
- Same for some crisis baseline (V199 or V201) on `--snapshot crisis`.
- **This tells us the noise floor.** Any future gate delta < 2σ is
  reported as "in noise" and does not count as a high-water move.
- Cost: 12 runs × ~30 min ≈ 6 hours. Run in background overnight.

**B. Reproduce V199 at seed=42 on the current snapshot.**
- Checkout V199 strategy.py, re-run `--version v199_repro --seed 42
  --snapshot recent`. If the result is not within ±$50 of +$2,478,
  the snapshot data itself has drifted (live data update or
  cleanup), and **all comparisons across versions are
  contaminated**. This is the cheapest sanity check we have.

**C. A second crisis snapshot.**
- Build `snap_crisis_2020q1` or `snap_crisis_2018q4` so crisis is
  evaluated on at least two distinct stress windows. If a version
  is positive on one and not the other, we have a regime-specific
  signal. If a version is consistently negative on both, the
  current "skip crisis trading" prior is correct and we should
  ship a defensive-abstention version, not another size tweak.

---

## 7. V203 proposal — revert-and-branch (not another parameter pull)

Given the above, V203 should **not** continue the
`crisis_short_bias` parameter walk. Two routes are candidates; I
recommend Route B and submit Route A as the diagnostic prerequisite.

### Route A — Diagnostic (commission before V203 ships)
Run the variance / reproduction / second-snapshot work in §6 as a
single background batch. No code change. This is the V203
"infrastructure" version — the entry in the log is "Re-baseline
the eval before any further parameter changes." Output: a noise
floor in dollars, a confirmation V199 still reads +$2,478 at
seed=42 (or a refutation), and a second crisis snapshot to break
the single-window dependence.

### Route B — Crisis defensive abstention
Hypothesis: crisis P&L is structurally bad regardless of selection
and sizing (V201, V202 evidence). Test the *strongest* defensive
prior: **skip all new crisis shorts in cycles where 1h momentum
is positive** (snapback signature). One file (`strategy.py`), one
guard at the short-entry gate.

Falsifiers:
- Crisis trade count drops from 63 to < 30 → suppression engaged.
  Crisis PnL must clear −$10K. If it stays below −$15K with
  ≈30 trades, even the snapback filter isn't enough → V204 = full
  crisis-short abstention.
- Trend trade count drops by > 10 → we're suppressing trend trades
  that happen to be in crisis-labeled cycles. Need a recent
  baseline to compare per-symbol distributions.
- Recent unchanged within noise floor (see §6 A — TBD).

### Route C — Revert-and-branch from V172
Hypothesis: trend high-water is recoverable in full by reverting
strategy.py to V172's state and branching only the crisis fix from
Route B onto it. **Do not ship this as V203** without Route A's
variance estimate — otherwise we have no way to tell whether the
"V172 recovery" was real or another single-seed peak.

### Recommendation
**V203 = Route A (re-baseline).** This is the meta-fix the user
asked for. We've spent three versions tuning a subsystem whose
movement is below our noise floor; the next version should be
about measuring the noise floor, not pulling another lever.

**V204 candidate** (conditional on Route A confirming +$2,478 is
real and crisis noise floor < $1K): Route B (crisis snapback
short-skip). **V204 alternative** (if Route A refutes V199): Route
C (revert to V172 + crisis defensive guard).

---

## Process change codified in the skill

The reflection step (this document's structure) is now mandatory
in `.claude/skills/victoria-training-loop/SKILL.md` when any of:

- 3 consecutive versions fail to break **any** gate's high-water.
- A pre-registered no-op change moves a gate by > $500 (eval-noise flag).
- Crisis (or any gate) is static for K=3 versions and the current
  hypothesis is on the same subsystem as the prior K-1.
- The most recent best on any gate is > 5 versions ago.

Reflection step output is `REFLECTION_V###.md` next to the version
file. Pre-registration of the next version is blocked until the
reflection is committed.
