# Strategic Audit — Victoria stack (2026-06)

**Date:** 2026-06-10
**Author:** claude (senior-quant audit, not a V### iteration)
**Scope:** whole Victoria stack (signals → composite → conviction → sizing → exits →
regime → snapshots → training methodology), the V172→V218 trajectory, and where the
*substantive* signal actually is on the V217 hermetic baseline.
**Status:** advisory. No code changed, no V### pre-registered, no backtest launched.
This is a single doc + a prioritized backlog. It runs independent of the V218 matrix —
which has, in fact, **already completed** (kickoff + results landed 2026-06-09; zero
cells merged; a V219 brief was written). Findings below incorporate those completed
results.

> **Sourcing discipline.** Every hard number cited here was read from the file named.
> The verified empirical spine is the `retrospective-alpha-review.md` per-regime win-rate
> table and the V217/V218 training-log gate results. Cross-asset *priors* (DXY/VIX/yield/
> options-skew effects) are attributed to `docs/research/cross-asset-signals.md` as
> **directional theory, never Victoria-backtested** — do not read them as measured edge.

---

## Executive summary

**The base strategy's measured edge is thin and partly illusory, and the machinery that
was supposed to concentrate it on the good signals does not run.** The only signal with a
verified positive information coefficient across all three regimes is `sma_crossover`
(`retrospective-alpha-review.md:21` — win rate 0.48 recent / 0.52 crisis / 0.61 trending);
`fear_greed_signal` and `ollivier_ricci_signal` are explicitly classified **DEAD WEIGHT**
(lines 22, 24, 38, 40) with the standing recommendation to **remove them from the
composite** (line 218). Yet a 2026-06-era signal-contribution trace
(`data/v213_off_crisis_r1_signal_contribs.jsonl`) shows both dead signals still present at
**`weight: 1.0`**, equal-weighted with `sma_crossover`. The reason is architectural, and it
is the single most important finding in this audit: **the "IC-weighted composite" is a flat
unweighted average at runtime.** The V218 kickoff proved the entire IC-weighting subsystem is
runtime-inert in the eval — `StrategyNode._signal_ics` is initialised empty (`strategy.py:437`),
its only populate path `update_signal_ics` has **zero callers** in the training path, and
`_compute_weighted_conviction` early-returns the raw composite at `strategy.py:1032` before it
ever reaches the per-regime branch. So there is no mechanism, today, to down-weight any signal
regardless of how dead the research says it is.

**The crisis problem — the stated #1 open problem for ~15 versions — is substantially an
evaluation artifact.** V218.E ran the *identical* V217 code and data against a second crisis
window (COVID 2020q1) instead of the canonical LUNA/FTX 2022h1 window. The crisis gate flipped
from **−$2,863 to +$13,052** (`V218-matrix.md:175,222`). The selector-OFF recipe is strongly
profitable on one crisis and loss-making on the other; "crisis" as evaluated has been a
single-window point estimate, and roughly fifteen versions (V199→V217) optimized against that
one artifact. This generalizes: **every gate is one snapshot.** Recent and trend are each a
single window too, with the same fragility — they simply never got a second window because all
the diagnostic energy went to crisis. The headline number the team chased is not a structural
property of the strategy; it is a property of LUNA/FTX.

**The real yield of the V172→V218 arc is methodological, not alpha.** The trajectory shows a
recurring pattern — subsystems that are *coded, flag-gated, and inert*: the strategy_selector
(inert on main for the entire V199–V211 arc), `regime_signal_weighting` (read at
`strategy.py` but never declared on `VictoriaFeatures` → silent no-op), V170 per-regime IC
(never wired), `DAG_PARALLEL` (never set → dead path). The team built good instrumentation to
*detect* this (the V213 wiring banner, the V215 HTTP guard, the V217 per-field fingerprint),
and an 11-version determinism arc (V207→V217) that achieved a genuinely byte-identical eval.
But two foundational facts undercut the comparisons that arc was meant to enable: (1) the
"hermetic" V217 baseline **was not reproducible from committed state** — it depended on an
uncommitted `data/macro_cache.db` (`V218-matrix.md:188`), and a no-op control diverged from the
README baseline by >$6k; and (2) the one clean, reproducible, cross-window result we *do* have —
the **regime-conditional selector** (ON helps recent +$4,240, hurts trend −$7,432, hurts crisis
−$1,221, all at $0.00 noise floor, `V217.md:218-222`) — is arguably the most valuable signal
discovered in 70 versions. The honest read: fix the eval's reproducibility and wire the IC
machinery *before* adding any new signal, because right now no new signal can be measured or can
reach the composite.

---

## Lens 1 — Edge audit: is there actual alpha here?

### 1.1 What is verified

The only first-party, regime-stratified edge measurement in the repo is
`docs/research/retrospective-alpha-review.md` (V136–V137 era). Its verified verdict table
(`:19-26`):

| Signal | Recent WR | Crisis WR | Trending WR | True alpha? |
|--------|----------:|----------:|------------:|:-----------:|
| `sma_crossover`       | 0.48 | 0.52 | 0.61 | ✓ |
| `fear_greed_signal`   | 0.38 | 0.35 | 0.44 | ✗ (dead weight) |
| `ollivier_ricci_signal` | 0.41 | 0.43 | 0.48 | ✗ (dead weight) |

Key finding, quoted (`:26`): *"Only `sma_crossover` shows consistent positive IC across
regimes… Fear/greed and curvature signals are noise amplifiers — they add conviction scoring
without predictive power."* The doc's P1 recommendation (`:218, :328`) is to remove
`fear_greed_signal` and `ollivier_ricci_signal` and keep `sma_crossover` + `ricci_curvature`.

`node-effectiveness-v136-v137.md` is a per-regime accuracy/IC matrix. Read directly, it is
**noisy and not a clean ranking**: `Momentum Crossover` swings from +0.36 to −0.29 across
regime columns (`:35`), `Momentum Derivative` is mostly negative (−0.03 / −0.31 / −0.23,
`:36`), microstructure signals (VPIN, OBI, Book Depth Velocity) sign-flip by regime. The
honest summary is *not* "we measured these ICs precisely" but: **outside `sma_crossover`,
no signal shows a stable cross-regime IC, and several flip sign between regimes** — which is
exactly the behaviour you'd expect from regime-luck rather than alpha.

> ⚠️ A research sub-agent initially returned precise ICs (e.g. fear_greed −0.018,
> momentum_derivative −$73,808) with *page-number* citations to markdown files. Those page
> numbers are fabricated and the precise dollar/IC figures could not be verified in-file; they
> are **excluded** from this audit. Only the win-rate verdict table above and the qualitative
> "no stable cross-regime IC" reading are cited.

### 1.2 The edge that exists is diluted by construction

Combine §1.1 with the architecture: the composite is an **equal-weighted average** of whatever
`*_signal` keys are present (`strategy.py` only admits keys ending `_signal` plus
`sma_crossover` into `_compute_weighted_conviction`). The V213-era trace shows the live signal
set as `sma_crossover, fear_greed_signal, vix_signal, ricci_curvature_signal,
ollivier_ricci_signal` — each at `weight: 1.0`. So in a representative cycle, the one
verified-alpha signal is averaged 1:1 with two research-flagged dead-weight signals. The
"postmortem flip" logic (v112+) that was supposed to invert dead signals does not visibly
rescue this — the trace carries `fear_greed_signal: 1.0` at face value — and even if it did,
inverting a zero-IC signal produces a zero-IC signal, not alpha. **The edge isn't missing; it's
averaged into noise, and the de-noising mechanism (IC weights) is inert.**

### 1.3 Signal-class universe — what we have vs. what we have not tried

WIRED and reaching the composite (per the architecture map): the technical core (`sma`, `rsi`,
`macd`, bollinger, z-score, volume), `funding_rate_signal`, `btc_beta`, the macro/cross-asset
overlay (`fear_greed`, `dxy`, `vix`, yield-curve, spy), and the geometry signals
(`ricci_curvature`, `ollivier_ricci`).

COMPUTED in the DAG but **not reaching the composite / inert in the frozen eval**: carry
(V218.A proved `FundingCarrySignal` gets funding=0 because the snapshots carry no
`funding_rate` and the live fetch is blocked by the HTTP guard, `V218-matrix.md:206-214`);
smart-money, on-chain TVL, VRP, alt-data, market-data (MVRV etc.), finbert, twitter — these
populate `signals` but there is no evidence they enter `_compute_weighted_conviction` (only
`*_signal`/`sma_crossover` keys do), so their decision influence is opaque-to-zero.

THEORY-DRIVEN, no data pipeline: order-flow/VPIN/Kyle and microstructure (`signals_advanced.py`)
require bid/ask depth that the OHLCV ingest does not provide — **dormant for want of data**, the
V185 "strong on snapshot, anemic live" verdict.

NOT TRIED (no implementation), with priors per `cross-asset-signals.md` (theory, not
Victoria-tested):

| Class | Data accessibility | Prior effect / regime (per research, unverified) |
|-------|--------------------|--------------------------------------------------|
| **Spot–perp basis / term structure** | one-fetch (CCXT spot+perp) | carry collapse precedes systemic stress → **crisis** lead |
| **Options skew (Deribit 25Δ risk-reversal)** | one-fetch (Deribit REST, free) | skew inversion precedes crashes → **crisis** lead |
| **Perp OI velocity (dOI/dt)** | one-fetch (Coinglass/CCXT) | leverage-buildup reversal → momentum death, **all regimes** |
| **VIX extreme mean-reversion** | one-fetch (yfinance ^VIX) | VIX>35 sustained → capitulation/recovery; (vix *level* already wired, the *extreme-MR* transform is not) |
| **Cross-venue funding spread** | one-fetch (Binance/Bybit/OKX) | divergence → dislocation; basis of the V137 "Gate 1" idea |
| **On-chain netflows / MVRV-Z / active addrs** | hard (Glassnode/Nansen paid) | inflow surge precedes drawdown → **crisis** lead |

**The strongest a-priori crisis candidates (basis, options skew, OI velocity) are all
one-fetch-away and all untried.** But see Lens 2/3: none of them is *measurable* today, because
(a) the frozen eval blocks new live feeds and has no frozen-feed plumbing for them, and (b) even
if fetched, they only matter if they reach the (currently inert) weighted composite.

---

## Lens 2 — Architecture audit: where the design constrains us

### 2.1 Composite failure modes

The composite is `mean(signal_values)` → conviction bucket → threshold gate → sizing. Failure
modes, in order of how much they bite:

1. **No weighting (the big one).** IC-weighting is inert (§1.1/Lens 3). A dead signal and an
   alpha signal contribute equally. There is no surviving mechanism to express "trust SMA more
   than fear/greed." This is not a tuning gap; the subsystem that would express it does not run.
2. **Signals cancel / one dominates.** With equal weights and signals in [−1,1], two opposed
   mediocre signals null a good one; or a saturated signal (`fear_greed_signal: 1.0` in the
   trace) dominates a proportional one (`sma_crossover: −0.549`). Saturation + equal weight is
   the worst case and it is the live case.
3. **Conviction is coarse + step-functioned.** `score_to_conviction` buckets a continuous
   composite into STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL, then `_CONVICTION_SIZE` maps those to
   {1.5, 1.0, 0, 0.5, 1.0}. A continuous edge is quantized twice (bucket, then size step). A
   trade just over a regime threshold sizes identically to one far over it (modulo the
   continuous `_conv_scale` clamp [0.5, 2.0]).
4. **Sizing discontinuities + the daily-bar artifact.** The frozen trend/crisis snapshots are
   *daily* bars at 00:00 UTC, so both intraday `time_risk_multiplier` windows (14:30–15:30 and
   00:00–01:00 UTC) fire **every** cycle → a uniform ~0.375× sizing regime (`V216.md`,
   README `:48-59`). The current hermetic baseline is *defined on a sizing bug*: the time-of-day
   risk control collapses to a constant on daily data. Every post-V216 number lives in this
   regime.

### 2.2 The selector asymmetry — what it tells us

Clean, reproducible, cross-arm at $0.00 noise (`V217.md:218`): selector ON **helps recent
+$4,240**, **hurts trend −$7,432** (flips a +$1,039 profit to −$6,393), **hurts crisis −$1,221**.

Mechanistically (from the selector map): TREND mode *relaxes* entry thresholds, disables crisis
protections, and lets winners run; CRISIS mode suppresses longs and tightens. The asymmetry
says the selector is a **regime-bias amplifier, not a regime-edge detector**: on the choppy
"recent" window, tightening/suppression avoids bad chop trades (helps); on the "trend" window,
the relaxation+protection-disable *exposes* the crisis sub-periods inside that window (the same
"half-Kelly skip is load-bearing for trend's crisis-labeled cycles" lesson from V202/V204), so
it hurts. In other words the selector doesn't add information; it changes the operating point,
and whether that helps is entirely a function of the snapshot's composition. This is the same
disease as the gate problem (Lens 3): a per-snapshot effect masquerading as a regime strategy.
The V219 "regime-gated selector" idea (toggle per gate) is therefore **fitting to three
snapshots** unless it's validated across a snapshot *distribution* (Lens 3).

> Confirmable cheaply: `data/{ver}_mode_transitions.jsonl` records the per-cycle mode. One read
> would verify "TREND-mode relaxation fires during the trend snapshot's crisis cycles." Left as
> a V219 pre-step rather than asserted here.

### 2.3 Is the training loop approximating live conditions?

Per-snapshot replay, 200 cycles, daily bars. What production sees that this does not:
- **No slippage/queue/partial-fill/cancel-replace realism** beyond a flat slippage model;
  no order-book impact, no OI footprint. Fine for a directional-edge screen, fatal for any
  microstructure signal (which is why VPIN etc. are "snapshot-strong, live-anemic," V185).
- **Daily bars ⇒ the intraday risk controls degenerate** (§2.1.4). Live runs on finer bars;
  the sizing regime in eval is not the sizing regime in production.
- **Live-only features are invisible** (`retrospective:63` — *"the benchmark cannot validate
  live-only improvements"*). Whale flow, WS microstructure are dead weight in backtest by
  construction.
- **200 daily cycles ≈ the snapshot window itself** — a single non-stationary regime episode,
  not a stationary process the edge can converge over (Lens 3.2).

### 2.4 Compounding changes vs. point fixes

The audit's strongest architectural lever is **compounding**: wiring the *existing* IC
machinery (populate `_signal_ics` from `signal_ic_history.json`, clear the `:1032` early-return)
does three things at once — it auto-down-weights the known-dead signals (subsuming the "prune
fear/greed" point fix), it is the **prerequisite** that makes V170 per-regime IC testable, and
it makes the composite finally do what its name claims. Compare to point fixes (delete a signal,
tune a threshold) which the whole V199→V204 arc showed to be noise-tuning. Other genuinely
compounding moves: **per-symbol / per-snapshot calibration** (opens distributional eval),
**multi-timeframe composite** (de-quantizes conviction), **fractional-Kelly on a trustworthy
win-rate** (currently Kelly rides a non-stationary 10-trade window). The recurring trap is
point-tuning a subsystem that turns out to be inert — so *any* change should be gated behind a
runtime-wiring assertion (Lens 3.3).

---

## Lens 3 — Methodology audit: is the loop itself biased?

### 3.1 Three snapshots is not enough — and the data proves it

V218.E is the cleanest result in the whole log: identical code+data, crisis PnL **−$2,863
(2022h1) → +$13,052 (2020q1)** (`V218-matrix.md:175,222`). The conclusion writes itself
(`:224`): *"The entire crisis 'gate' through V199–V217 has been optimising against a
single-window artifact."* The methodology bug is structural: **one gate = one snapshot**, so a
gate number is a point estimate on a non-stationary process, and the per-gate optimization is
overfitting to that point. The fix is not "add a 2020q1 crisis snapshot" — it's **evaluate each
regime as a distribution over ≥3 windows** (e.g. crisis: 2018q4, 2020q1, 2021-05, 2022h1; trend:
2021 bull, 2023q4; recent: rolling). Until then, no gate delta — including the selector Δ — is
known to generalize.

> Magnitude caveat on the +$13k: per `V218-matrix.md:188`, the matrix ran on the *committed*
> `macro_cache.db`, which differs from the README baseline's working-tree cache. Direction
> (crisis flips sign across windows) is robust; the exact +$13,052 rides the committed cache.

### 3.2 Does the edge converge in 200 cycles?

On daily bars, 200 cycles ≈ 200 trading days ≈ the length of one regime episode. The eval is
therefore measuring **a single draw from a non-stationary window**, not a convergent average.
This is why single-seed deltas were 60–70% noise (REFLECTION_V202), why σ_recent was $2,547 at
V203, and why the team had to build the whole determinism arc just to get the *within-config*
noise to $0. But within-config $0 ≠ cross-window stability: V218.E shows the cross-window spread
is ~$16k on crisis. The horizon and the single-window design mean **the eval has high
between-snapshot variance that no amount of within-snapshot determinism fixes.**

### 3.3 Why we keep finding inert code — and the meta-fix

The pattern (from `OBSERVABILITY-BACKLOG.md:14-21`): strategy_selector inert V199–V211;
`regime_signal_weighting` UNDECLARED (read at `strategy.py`, never a `VictoriaFeatures` field);
V170 IC never wired; `DAG_PARALLEL` dead. Root cause: **features are built in worktrees, gated
behind a flag, the flag is never declared/wired on the dataclass, `getattr(...)→False` silently
disables it, and nothing in the eval asserts the flag changed anything.** A subsystem can be
"shipped" and tuned for dozens of versions while executing zero lines.

The team already shipped good *detectors* — the V213 wiring banner, the V218 IC-INERT probe.
But those are **reactive** (they print a warning a human must read). The missing **meta-fix** is
a *test that every flag does something*: a preflight that, for each declared feature flag, runs
one cycle with it ON and one with it OFF on a fixed seed and **asserts the outputs differ**
(or is explicitly marked `no-op-ok`). A flag that produces byte-identical output ON vs OFF fails
preflight. This is the generalization of the V217 methodology lesson ("a determinism fix isn't
done until the full ON/OFF grid is byte-identical") turned into its dual: **a feature isn't
wired until its ON/OFF grid is byte-*different*.** That single test would have caught
strategy_selector, regime_signal_weighting, V170 IC, and the V218.B blocker at cycle 0,
collectively saving the bulk of V148–V218's wasted versions.

### 3.4 The eval-integrity blocker (must fix before any comparison)

`V218-matrix.md:188` — the "hermetic" V217 baseline depended on an **uncommitted**
`data/macro_cache.db`; the committed state produces a different baseline (22 vs 38 trades,
>$6k PnL gap). This is a reflection-trigger-#2 event: **a pre-registered no-op control diverged
from the published baseline.** Consequence: every cross-version PnL comparison in the log that
predates a committed cache is suspect, and the celebrated 6/6-hermetic milestone is hermetic
*within a run* but not *reproducible from the repo*. This is the first thing to fix — it is
upstream of every other recommendation, because none of them can be measured against a baseline
that shifts with a dirty file.

---

## Top 5 recommendations

Ordered by dependency: the first two are **unblockers** — recommendations 3–5 are
*unmeasurable until they land*.

### R1 — Make the eval reproducible from committed state (eval-integrity)
- **(a) What:** Freeze/commit a canonical `macro_cache.db` (or a `data/snapshots/frozen_macro.db`
  + loader pin) and add a cycle-0 preflight that asserts its md5 matches a committed manifest.
  Same treatment the snapshots and `frozen_advanced_signals.json` already get.
- **(b) Why genuine:** Not a tweak — it is the precondition for *any* number to mean anything.
  Today the headline "hermetic baseline" is not reproducible from a clean checkout
  (`V218-matrix.md:188`). Without this, R3–R5 can't be evaluated.
- **(c) Effort:** S.
- **(d) Expected gate effect:** $0 directly; it *stabilizes* all gates so deltas become real.
- **(e) Falsifier:** if two clean checkouts + the committed cache still produce different gate
  PnL, the leak is elsewhere (another uncommitted artifact) — bisect with the V215 HTTP guard +
  V217 per-field fingerprint already in place.

### R2 — Wire the existing IC machinery (master compounding lever)
- **(a) What:** Populate `StrategyNode._signal_ics` from `signal_ic_history.json` in the training
  path (one call to `update_signal_ics`), and remove/condition the `strategy.py:1032`
  `if not self._signal_ics: return composite` early-return so the weighted path actually runs.
  This is V219.B-corrected, scoped as exactly one bet (raw-mean → IC-weighted).
- **(b) Why genuine:** It changes the composite from a flat average to a quality-weighted one —
  the de-dilution of §1.2 — using machinery that already exists but has never executed
  (`V218-matrix.md:22-34`). It **subsumes** "prune fear/greed" (their low IC auto-down-weights
  them) and is the **prerequisite** for the V170 per-regime-IC bet. One change, three unlocks.
- **(c) Effort:** S–M (wiring is small; the honest cost is that `signal_ic_history.json` is
  *pooled*, not regime-tagged, and its ICs are themselves estimated on the noisy single-window
  eval — so validate the source before trusting it).
- **(d) Expected gate effect:** directionally positive where dead signals currently dilute alpha
  (recent/trend); neutral-to-positive on crisis. Must be measured as a *distribution* (R3).
- **(e) Falsifier:** if IC-weighted ≈ equal-weighted across all gates (Δ < band), the pooled ICs
  are too flat/noisy to matter → the real bet is regime-tagged IC (needs an accumulator), or the
  signal set is genuinely undifferentiated and the answer is "trade `sma_crossover` alone."

### R3 — Evaluate every regime as a distribution over ≥3 snapshots
- **(a) What:** Build ≥3 windows per regime (crisis: 2018q4 / 2020q1 / 2021-05 / 2022h1; trend:
  2021-bull / 2023q4; recent: ≥2 rolling). Report mean ± spread across windows as the gate
  unit, not a single number.
- **(b) Why genuine:** V218.E *proved* the single-window gate is an artifact (crisis sign-flips
  across windows). This converts the whole loop from "optimize a point estimate" to "optimize a
  distribution," which is the only way any of R2/R4/R5 can claim generalization.
- **(c) Effort:** M (snapshot construction + harness loop; the harness already supports
  `SNAP_OVERRIDE`).
- **(d) Expected gate effect:** reframes, doesn't move — but it will likely show the crisis
  "problem" is half illusory and re-rank prior conclusions.
- **(e) Falsifier:** if per-regime cross-window spread is small (gates *do* agree across
  windows), then single-snapshot eval was fine and this is overhead — but V218.E already makes
  that outcome unlikely for crisis.

### R4 — Ship the "every flag does something" preflight (meta-fix for inert subsystems)
- **(a) What:** A preflight that, per declared feature flag, runs 1 cycle ON and 1 cycle OFF at
  fixed seed and asserts the fingerprints differ (or the flag is annotated `# no-op-ok`).
  Fails the run on a silently-inert flag. Generalizes the V213 banner from a printed warning to
  an enforced gate.
- **(b) Why genuine:** It structurally ends the V148–V218 recurring failure mode (tuning inert
  code). It is the dual of the V217 determinism lesson and would have caught strategy_selector,
  `regime_signal_weighting`, V170 IC, and V218.B at cycle 0.
- **(c) Effort:** M (reuses the per-field fingerprint + `check_determinism.sh` harness).
- **(d) Expected gate effect:** $0 directly; prevents whole wasted versions.
- **(e) Falsifier:** if most flags legitimately no-op under the frozen eval (data not present),
  the test is noisy and needs an allowlist — acceptable, that allowlist *is* the documented
  inventory of what's actually live.

### R5 — Add ONE crisis-prior signal end-to-end, but only as a frozen-feed bet: spot–perp basis
- **(a) What:** Pick the single strongest untried crisis prior — **spot–perp basis / term
  structure** — and do it *properly*: add a `frozen_basis_feed.json` (the V218.A lesson: a
  correct signal is untestable without a frozen feed), route it as a `*_signal` key so it
  reaches the composite, and verify via the PipelineTracer it produces ≥5 attributed trades.
- **(b) Why genuine:** It is the highest-prior crisis signal (`cross-asset-signals.md`: carry
  collapse leads systemic stress), one-fetch-away, and orthogonal to the technical core. Doing
  it as a frozen feed also builds the reusable plumbing R5-class signals all need (options skew,
  OI velocity follow the same path).
- **(c) Effort:** M (fetch + freeze + route + tracer-verify).
- **(d) Expected gate effect:** targeted at crisis (across the R3 distribution); prior says
  positive lead, but **unverified** — this is a genuine bet, not a known win.
- **(e) Falsifier:** < 5 basis-attributed trades → still gated out (plumbing bug, the V218.A
  failure mode); or crisis-distribution Δ within band → the prior doesn't survive Victoria's
  universe/horizon. Either is a clean, cheap "no."

**Honest meta-point:** R5 is deliberately *last*. The temptation in a 70-version quant project
is to add signals; the evidence says the constraints are upstream (R1 reproducibility, R2
weighting, R3 distributional eval, R4 wiring discipline). A new signal added before R1–R2 cannot
be measured (no stable baseline) and cannot influence the decision (inert composite). Fix the
loop, then bet.

---

## Secondary candidates for the V219+ backlog

(Proposed additions to `V213-MATRIX-CANDIDATES.md` — none merges without clearing R3's
distributional band.)

1. **Regime-tagged IC accumulator** — once R2 lands pooled IC, build the per-regime IC source
   V170 needs (`signal_ic_history.json` is pooled). Unlocks the per-regime-IC bet for real.
   Effort M.
2. **Options skew (Deribit 25Δ risk-reversal)** — second crisis-prior signal, same frozen-feed
   plumbing as R5. One-fetch, free API. Effort M.
3. **Perp OI velocity (dOI/dt)** — leverage-buildup-reversal momentum signal, all-regime prior.
   Frozen-feed. Effort M.
4. **VIX extreme mean-reversion transform** — the VIX *level* is already wired; add the
   sustained-extreme (>35 for N days → capitulation) transform as a distinct signal. Effort S.
5. **De-quantize conviction → multi-timeframe composite** — replace the single-bar bucketed
   conviction with a 2–3 timeframe blend to reduce the double-quantization of §2.1.3. Effort M–L.
6. **Cadence-gate the intraday risk windows on daily bars** — fix the §2.1.4 artifact so the
   eval sizing regime isn't defined by a degenerate time-of-day control. Effort S. (Orthogonal
   to determinism; re-bases the baseline, so pre-register.)
7. **Fractional-Kelly on a windowed, trustworthy win-rate** — current Kelly rides a 10-trade
   non-stationary window; tie it to the R3 distribution. Effort M.
8. **Drop the dead signals outright (point-fix control)** — remove `fear_greed_signal` +
   `ollivier_ricci_signal` from the composite as a *control* against R2 (does explicit pruning
   match IC-down-weighting?). Effort S. Diagnostic, not a merge candidate on its own.
9. **Selector as a per-regime distribution test** — re-run the V217 selector Δ across the R3
   snapshot distribution before committing to a regime-gated toggle (the V219 idea); the current
   Δ is three single-window point estimates. Effort S (eval only).
10. **Mode-transition mechanism confirmation** — read `mode_transitions.jsonl` on the trend gate
    to confirm the §2.2 hypothesis (TREND-mode relaxation fires in the trend snapshot's crisis
    cycles) before designing any selector change. Effort S (one read).

---

## Forks / open decisions (recorded, not asked)

- **Fork A — base-strategy verdict.** The evidence supports the blunt read that *the base
  composite has one verified alpha signal (`sma_crossover`) diluted by inert weighting, and the
  most robust thing found in 70 versions is the regime-conditional selector + the discovery that
  crisis is snapshot-dependent.* A defensible aggressive path is to **strip the composite to
  `sma_crossover` (+`ricci_curvature`) and rebuild weighting from R2**, rather than continue
  carrying ~5 equal-weighted signals. Recorded as a fork because it's a strategic call, not an
  audit fact; R2+R3 will decide it empirically (if IC-weighting can't beat SMA-alone across the
  distribution, take this fork).
- **Fork B — is "crisis" even a gate?** If R3 shows crisis PnL is dominated by which window is
  chosen (V218.E says it is), the crisis gate as a single optimization target should be
  **retired** in favour of a crisis *distribution* with a drawdown-control objective, not a
  PnL-maximization objective. The ~15 versions of crisis_short_bias / half-Kelly / exit-side
  tuning were optimizing a number that isn't stable.
- **Fork C — live vs. backtest divergence.** Several of the most-promising signal classes
  (microstructure, whale flow, anything order-book) are *structurally* invisible to the frozen
  daily-bar eval. A separate **live-paper Phase-B track** (the V176 live high-water was real:
  +$1,189, PF 3.22) may be the only honest way to measure them — the backtest cannot, by its own
  admission (`retrospective:63`).

---

## Pointers

- Verified edge table: `docs/research/retrospective-alpha-review.md:19-44, :218, :328`
- Cross-asset priors (theory only): `docs/research/cross-asset-signals.md`
- IC-weighting inert proof: `V218-matrix.md:22-34`; `strategy.py:437, :1025, :1032`
- Equal-weight trace: `data/v213_off_crisis_r1_signal_contribs.jsonl`
- Selector clean Δ: `V217.md:218-231`; README `:70-78`
- Crisis-is-snapshot-specific: `V218-matrix.md:175, :201, :222-224`
- Eval-integrity blocker: `V218-matrix.md:180-193, :239-243`
- Inert-subsystem pattern + detectors: `OBSERVABILITY-BACKLOG.md:10-54`
- Snapshot-diversity + horizon: `V204.md:138-141`; `REFLECTION_V202.md` (60–70% no-op drift)
