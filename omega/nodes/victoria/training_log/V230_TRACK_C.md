# V230 Track C — Honest campaign-trajectory reassessment

**Date:** 2026-06-22
**Author:** claude (strategic-analysis subagent; advisory, no code, no pre-reg)
**Scope:** Is the Victoria training program improving? Grounded ONLY in the
`training_log` high-water table, STRATEGIC_AUDIT_2026-06, RESILIENCY_AUDIT_2026-06,
the V222–V229 overlay-arc results, and REFLECTION_V215/V220/V229.
**Sourcing rule:** every dollar figure below is quoted from the README high-water
table or a V###.md result row, with the gate's documented noise floor attached.
Where the evidence is ambiguous, it says so rather than manufacturing confidence.

---

## Q1 — Where do we honestly stand vs the standing baseline? Is the +$630 crisis durable or noise?

**Standing main (V227-era, the current default-ON configuration), all hermetic at
$0.00 spread:**

| Gate   | Standing main (V227-era)        | Documented noise floor (σ)        |
|--------|--------------------------------:|-----------------------------------|
| recent | **+$4,901.01** (22t, V221-era)  | **$1** (V211 12-run audit)        |
| trend  | **−$217.71** (23t)              | **$166** (V211); V222 control re-anchored equal-weight here |
| crisis | **−$2,991.17** (33t, V227)      | **$12** (V211 12-run audit)       |

The honest read: **we are net slightly positive on the standing snapshot set, but
that headline is carried almost entirely by `recent` (+$4,901), and `recent` is one
window.** Trend is roughly flat-negative (−$218). Crisis is still deeply negative
(−$2,991) — it has *never* cleared zero on the canonical 2022h1 window in this arc.

**Is the +$630 crisis improvement durable or noise-floor?**

It is **durable in the determinism sense, fragile in the generalization sense.**

- *Durable side:* the V227 result is **+$630.08 against a documented crisis noise
  floor of $12** (V211 audit) — i.e. ~52σ above the within-config floor. It was
  measured ON−OFF within the same fenced commit, crisis N=2 hermetic, both arms at
  $0.00 spread, OFF arm reproducing the prior main to the cent. By the program's own
  high-water rules this is a real, non-noise within-window improvement: crisis
  high-water genuinely moved −$3,621.25 → **−$2,991.17**.
- *Fragile side:* the within-window noise floor ($12) is **not** the relevant
  uncertainty for "is this real edge." The STRATEGIC_AUDIT's single cleanest result
  is V218.E: **identical code+data, crisis flips −$2,863 (2022h1) → +$13,052
  (2020q1)** — a ~$16k cross-window swing. So the *between-window* variance on crisis
  is ~1000× the +$630 we banked. **+$630 is a real signal against the wrong yardstick:
  it is well above within-window noise but far below between-window noise.** We cannot
  claim it generalizes to "crisis" as a class; we can only claim it improves the
  LUNA/FTX-2022h1 point estimate.

Verdict on Q1: **Net marginally positive, concentrated in one window; +$630 crisis is
a genuine within-window win and a structurally sound mechanism (additive drawdown
brake), but its generalization is unproven and the between-window variance dwarfs it.**

---

## Q2 — 7-version arc (V222–V229) returned 2 hits. Acceptable, or no edge?

**The arc's complete ledger (from the README):**

| Ver  | Bet                                   | Outcome                                              |
|------|---------------------------------------|-----------------------------------------------------|
| V222 | IC wiring (seeded pooled)             | REFUTED — recent −$2,905, crisis −$4,771 (trend +$3,331 only) |
| V223 | regime-gated IC                       | REFUTED net vs equal-weight (beats always-on IC, loses to eqw) |
| V224 | empirical OOS per-regime IC           | RETIRED — wins 1/3 (trend +$2,206), needs ≥2        |
| V225 | additive crisis-skew (always-on)      | REFUTED — harms all 3 gates (−$6,047 net)           |
| V226 | regime-gated crisis-skew              | REVERTED — gate fires ~half of every window         |
| V227 | **drawdown-gated crisis-skew**        | **SHIP — crisis +$630** ✓                           |
| V228 | stack skew + trend-IC                 | REFUTED — composes additively, drags IC crisis harm in |
| V229 | drawdown-gated IC                     | REFUTED for crisis (5th IC refutation); **banked trend-only +$1,428** ✓ |

So 2 "returns" out of 8 attempts:
1. **V227 crisis-skew: +$630 crisis, promoted to main.** Durable-ish (Q1 caveats).
2. **V229 drawdown-gated-IC trend overlay: +$1,428 hermetic on trend, but
   NOT promotable** (it loses crisis −$2,009 and recent −$212). It is a *parked
   trend-only overlay* that supersedes V224's +$875 IC — it has never entered main.

**Is this hit-rate acceptable?** Honestly, **no, not as a signal-discovery rate** —
and the log itself reached this conclusion. REFLECTION_V229 fired **two mandatory
triggers**: (1) IC re-weighting refuted for crisis **five consecutive times**
(V222/V223/V224/V228/V229), and (2) no gate high-water has broken for several versions.
The crisis loss floor has **not moved off ~−$3k for the entire arc** except for the
single +$630 V227 step. That is the textbook signature the loop's own skill warns
against: **walking the same selection/re-weight parameter surface and getting noise.**

But the arc was **not worthless** — it produced a *sharp structural finding* that is
worth more than the dollars: **"the drawdown-magnitude gate works as an additive brake
(V227 +$630) but fails as a selection re-weight (V229 −$2,009 at every X)."** That
distinction — additive-brake vs selection-concentration — is the most useful piece of
strategic knowledge in the arc and is the correct seed for V231.

Verdict on Q2: **The hit-rate is poor for finding *new edge*, and IC-as-selection is
now closed by 5 refutations. The strategy is not "fundamentally finding no edge" —
`sma_crossover` + the recent-window edge are real — but it has clearly exhausted the
re-weighting/selection dimension. The yield from V222–V229 is mostly methodological/
structural, not alpha.**

---

## Q3 — Is the 3-gate snapshot set sufficient evidence, or are we Goodharting 3 windows?

**We are Goodharting 3 windows. This is the single most important fact in the audit,
and it is proven, not asserted.**

- STRATEGIC_AUDIT §3.1, citing V218.E: *"The entire crisis 'gate' through V199–V217 has
  been optimising against a single-window artifact."* Crisis flips sign (−$2,863 →
  +$13,052) across two crisis windows under **identical code**.
- The audit generalizes it (§3.1): **"every gate is one snapshot."** Recent and trend
  are each a single window too; they simply never got a second window because all the
  diagnostic energy went to crisis.
- §3.2: on daily bars, 200 cycles ≈ one regime episode ≈ a single draw from a
  non-stationary window. Within-config determinism (the entire V207→V221 arc earned
  $0.00 spread) does **not** buy cross-window stability: within-config noise is $0,
  between-window crisis spread is ~$16k.

So the program spent ~14 versions earning a byte-identical eval (a genuine engineering
achievement) and then measured 7 overlay bets against **3 point estimates on a
non-stationary process.** A +$630 or +$1,428 delta on one window cannot distinguish
"new edge" from "this window happened to like this knob."

Verdict on Q3: **No. Three single-window snapshots are insufficient to call any of
V222–V229 "real" in the generalization sense. We are optimizing point estimates. The
within-window determinism is trustworthy; the cross-window claims are not, and the log
has the receipt (V218.E).**

---

## Q4 — Keep iterating on signal-add overlays, OR step back to a fundamental redesign?

The task is explicit: **do not recommend a redesign unless the trajectory is provably
stalled by the numbers.** Let me hold each redesign option to that bar.

**Is the trajectory provably stalled?** On the metric "break a gate high-water," yes:
crisis moved exactly once (+$630) in 8 versions; trend/recent high-waters are
unchanged since V221/V227; IC-as-selection is 5×-refuted. That is a stall on
*signal-add-via-reweighting*. But it is **not** a stall caused by the composite/sizing
architecture being wrong — it is a stall caused by **(a) evaluating against 3 windows
and (b) repeatedly betting on the one dimension (selection re-weight) that is now
closed.** Those are different diagnoses and they point to different fixes.

Weighing the three offered redesigns against the evidence:

- **(b) Rolling-window walk-forward / snapshot distribution — STRONGLY SUPPORTED.**
  This is *the* fix the numbers demand. V218.E directly proves the single-window gate
  is an artifact; STRATEGIC_AUDIT R3 ("evaluate every regime as a distribution over ≥3
  windows") is ranked above every signal-add. It is the only change that makes any
  future overlay *measurable as edge rather than as window-luck*. Effort M (the harness
  already supports `SNAP_OVERRIDE`; the V218.E 2020q1 window already exists; the
  RESILIENCY audit's proposal #7 already wants a 4th held-out snapshot). **This is not
  a "redesign" in the risky sense — it is fixing the measuring instrument, and it is
  cheap.**

- **(c) Continuous sizing instead of binary trade/no-trade — PARTIALLY SUPPORTED, but
  blocked.** STRATEGIC_AUDIT §2.1.3 confirms the real defect: conviction is
  double-quantized (bucketed, then mapped to discrete size steps), and §2.1.4 notes
  the daily-bar baseline is *defined on a sizing bug* (both intraday time-of-day
  windows fire every cycle → uniform ~0.375× sizing). So sizing IS coarse. BUT
  REFLECTION_V220 shows the sizing/exit path was the source of a multi-thousand-dollar
  determinism channel that took until V221 to fence — touching continuous sizing
  reopens that risk class. Defensible as a *later* bet, not the next one.

- **(a) Portfolio-optimization composite instead of conviction-threshold — NOT
  SUPPORTED YET.** The STRATEGIC_AUDIT is blunt: the composite is an *equal-weighted
  average* and the IC-weighting machinery that would quality-weight it is the master
  compounding lever (R2). But V222–V224 *did* wire and test IC-weighting empirically
  and **IC-as-selection is now 5×-refuted for crisis.** A portfolio optimizer is a more
  aggressive form of the same "concentrate conviction on the good signals" idea that
  just failed repeatedly on crisis (the harm is *conviction concentration itself* on
  the 121 normal-labeled crisis cycles — V224/V228/V229). Building a portfolio
  optimizer before fixing the eval would be betting harder on the dimension the data
  just closed. **Reject as next step.**

Verdict on Q4: **Step back — but the step-back is (b) distributional/walk-forward
evaluation, NOT a strategy redesign.** The trajectory is provably stalled on
signal-add-by-reweighting, and the proven root cause is the 3-window eval (Q3), not the
composite or sizing architecture. Fix the instrument first. Continuous sizing (c) is a
defensible follow-on; portfolio-optimization composite (a) is rejected as premature
given 5 IC refutations.

---

## Q5 — Realistic 3-month vs 12-month roadmap under the real constraints

Constraints (taken as given): solo dev; no paid data unless ROI is obvious;
sleep=10 reproducibility (each gate run ~30 min–8 h); the eval is hermetic but slow.

**3-month (the unblockers — do these before any new signal):**

1. **Ship distributional eval (R3 / RESILIENCY #7).** ≥3 windows per regime (crisis:
   2018q4 / 2020q1 / 2021-05 / 2022h1; trend: 2021-bull / 2023q4; recent: ≥2 rolling).
   Report mean ± spread as the gate unit. This is the single highest-leverage move and
   the only one that makes every later bet honest. Cheap (M), harness-ready.
   *Acceptance:* re-measure V227 crisis-skew and the V229 trend overlay across the
   distribution — if +$630 / +$1,428 survive the spread, they are real; if they wash,
   we just avoided shipping window-luck.
2. **Ship the "every flag does something" preflight (R4).** Structurally ends the
   recurring inert-subsystem trap (strategy_selector, regime_signal_weighting, V170 IC
   all shipped-and-inert for many versions). Cheap (M), reuses existing fingerprint
   harness.
3. **Re-run the standing main across the new distribution to get a *distributional*
   baseline.** Everything post-V227 has been a single-window point estimate; we need
   the mean±spread baseline before V231 can claim anything.
4. **One additive-brake signal bet (V231), measured on the distribution.** Per
   REFLECTION_V229's structural lesson, the next signal must be **additive-brake
   shaped, not a selection re-weight** (that dimension is closed). The drawdown-brake
   (V227) is the proof-of-concept that this shape works.

The 3-month plan deliberately front-loads instrument fixes because, under the sleep=10
constraint, a grid is expensive (~hours) — you cannot afford to spend grids measuring
window-luck. Better eval = fewer wasted grids.

**12-month (compounding levers, gated behind the 3-month instrument work):**

5. **Continuous sizing / de-quantized conviction (Q4 option c)** — once the
   distributional eval can tell signal from window-luck and the sizing-path determinism
   is re-audited. Addresses STRATEGIC_AUDIT §2.1.3/§2.1.4 directly.
6. **A live-paper Phase-B track (STRATEGIC_AUDIT Fork C).** The backtest *cannot* by
   its own admission validate live-only signals (microstructure, whale flow, WS) — the
   V176 live high-water (+$1,189, PF 3.22) was real. If the backtest edge is genuinely
   thin (Q1 says it is), the honest 12-month question is whether live paper trading
   surfaces edge the frozen daily-bar eval is blind to. This is the path to *new* alpha
   that 8 overlay versions did not find.
7. **Decide Fork B: retire crisis-as-a-PnL-gate.** If the distributional eval confirms
   crisis PnL is dominated by window choice (V218.E says it is), stop optimizing crisis
   PnL and switch crisis to a *drawdown-control* objective over the distribution. ~15
   versions of crisis tuning chased a number that isn't stable.

What is explicitly **out** under the no-paid-data-unless-obvious-ROI rule: the
options-skew vendor (Track A's call, not mine). Note V224/V225 already established free
historical implied skew is unobtainable — so the paid bet is the only skew path, and it
should only be funded if Track A shows clear ROI *and* the distributional eval exists to
measure it against.

---

## Q6 — Honest verdict (pick one and defend)

> ## VERDICT: STEP BACK — but the step-back is the *evaluation instrument*, not the strategy.
> ### Concretely: V231 = ship distributional (≥3-window) evaluation + the flag-wiring preflight FIRST, then re-measure V227/V229 and run ONE additive-brake signal bet against the distribution. Do NOT redesign the composite or sizing yet; do NOT chase another selection re-weight.

**Why this and not "stay the course with a new additive-brake signal":**
A new additive-brake signal is the *right shape* (REFLECTION_V229's structural lesson;
V227 proved additive brakes can work where selection re-weights fail). But shipping it
*next*, against the same 3 single-window snapshots, repeats the exact mistake the log
just diagnosed: it would be measured against point estimates whose between-window
variance (~$16k on crisis, V218.E) is 10–25× any plausible signal delta (+$630 /
+$1,428). We would not be able to tell a real brake from a window that liked it. The
additive-brake bet is in the plan — it is step 4 of the 3-month roadmap — but it is
*gated behind* the eval fix.

**Why this and not "harvest the value, stop chasing edge":**
There is durable value to acknowledge — the determinism arc (V207→V221) earned a
genuinely byte-identical, provenance-stamped eval (a real engineering asset), V227's
+$630 crisis is a real within-window win with a sound mechanism, and `sma_crossover` +
the recent-window edge are real. But the program has **not** demonstrated that its
backtest edge generalizes (it has demonstrated the opposite for crisis), so "harvest
and stop" would be premature — we have not yet *measured* whether there is durable edge,
because we have never evaluated on a distribution. Harvesting before the distributional
eval would be capturing a number we know is window-dependent.

**Why this and not a full composite/sizing redesign:**
The task bar is "no redesign unless provably stalled by the numbers." The stall is
provable on *signal-add-by-reweighting* (crisis flat for 8 versions, IC 5×-refuted),
but the **proven root cause is the 3-window eval (V218.E), not the composite or sizing
architecture.** A redesign of machinery that has never been measured on a distribution
would be solving the wrong problem. Portfolio-optimization composite (Q4a) is
specifically rejected — it doubles down on the conviction-concentration idea that just
failed 5×.

**The honest one-line summary:** *The program has built an excellent measuring
instrument for the wrong unit (one window per regime) and an additive-brake mechanism
that works within that unit. Before betting another grid, fix the unit. Everything
else — including the next signal — is downstream of that.*

**Where the evidence is genuinely ambiguous (stated, not papered over):**
- Whether the +$630 crisis brake survives a 3-window crisis distribution is **unknown**
  — it could wash, or it could be the one structurally-sound result that does
  generalize (it is additive and mechanism-justified, the best a-priori case in the
  arc). The distributional eval is exactly the experiment that resolves this.
- Whether there is *meaningful* backtest alpha left to find on the frozen daily-bar
  eval at all (vs. the edge living only in the live-only signal classes the backtest
  is structurally blind to) is the deepest open question — Fork C, the 12-month live
  track, is the only honest way to answer it.
