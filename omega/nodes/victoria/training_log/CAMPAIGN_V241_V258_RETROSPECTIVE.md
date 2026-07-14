# Campaign Synthesis Retrospective — V241 → V260

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** Cross-cutting synthesis (NOT a mechanism V###, NOT planning)
**Scope:** the 20-version arc from V241 (reasoning-layer refutation) through V260 (news-regime probe),
spanning the Phase-1 alpha search, the V249 phase transition, the V250–V253 live-paper build, the
V254–V258 alt-data scoping, and the V259/V260 offline closeout.
**Companion docs:** [`CAMPAIGN_STATUS.md`](CAMPAIGN_STATUS.md) (phase tracker + resume criteria),
[`V249.md`](V249.md) (phase-transition rationale), [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md)
(alt-data ranking), [`REFLECTION_V246.md`](REFLECTION_V246.md) (the reflection that triggered the transition).

> **This document is synthesis, not planning.** It proposes **no new V###**. Its job is to make the
> shape of the whole campaign legible: what died and why, what the discipline caught, what we learned
> about the measuring instrument, and an honest map of where in signal space we have and have not
> searched. Resume ordering (§E) is a *recommendation given today's constraints*, not a pre-registration.

---

## A. Refutation-pattern taxonomy

Every dead end in this arc, classified by **root cause**. The category set:

- **R1 — Signal absence:** the mechanism's discriminating variable does not separate winners from
  losers; the effect claimed does not exist.
- **R2 — Signal below resolution:** a real-looking effect that is smaller than the eval's noise floor;
  "unadjudicable," not "absent."
- **R3 — Signal-not-adjudicable (calendar-bound N):** the targeted regime has too few *independent*
  windows to measure any effect of the relevant size, regardless of mechanism.
- **R4 — Data absence:** the data the hypothesis pre-declared is not frozen; the thesis is untested,
  not falsified.
- **R5 — Structural:** the payload/input structure destroyed the information *before* the test ran, so
  the test measured wording/variance, not the hypothesized signal.
- **R6 — Friction geometry:** real alpha, real signal, real regime — but transaction cost / hold
  amortization eats the median.

### The ledger

| V### | Bet | Where it died | Root cause | Note |
|---|---|---|---|---|
| **V241** | Whole-basket LLM risk-review (reasoning layer) | Full grid + cache fill | **R2** | ACTIVE 99.6% but adds *variance, not expectancy*; pooled +$31 on a $27k spread |
| **V242** | Whale-flow gate | Pre-registration sanity gate ($0, no grid) | **R1** | The paper number failed the sanity check — the claimed effect was an artifact |
| **V243** | Portfolio corr-spike cap | Separator proof ($0, no grid) | **R1** | corr-spike variable did not discriminate; portfolio-corr family CLOSED |
| **V244** | Portfolio-separation sizing | Offline scorer ($0) | **R1** | no separation between the sized and unsized cohorts |
| **V245** | GDELT daily-aggregate as a **trading signal** | Grid | **R2** | entry-side info feeds saturated against the momentum composite |
| **V246** | Regime-adaptive **exit** | Grid (the 2·SE edge) | **R2** | pooled +$627 ≈ 2·SE; recent flat — the *canonical* below-resolution death |
| **V248** | Portfolio-level sizing | Offline scorer ($0) | **R2** | best cell +$494 < +$625 bar — "zero new information" |
| **V255 (Ph0)** | Directional funding-carry | Phase-0 offline scorer ($0) | **R2** | price risk swamps the carry signal in a directional book |
| **V255.B** | Basis-hedged funding-carry | Offline scorer | **R6** | alpha **CONFIRMED** (gross 36% ann., p≈0 separator) but 3-day hold + 2-leg fees → median net −$5.95 |
| **V256** | On-chain flow primary universe | Phase-0 data audit ($0) | **R4** | 1 of 4 signals frozen, and it's the wrong (market-wide) shape — PAUSED, not refuted |
| **V258** | Specialist LLM ensemble | Phase-0 divergence probe ($0) | **R5** | V241 payload collapses all signals to one `composite` scalar → 5 specialists see identical inputs |
| **V259** | Polymarket crowd-sentiment | Phase-0 data audit ($0) | **R4** | no frozen probability time series exists — PAUSED, not refuted |
| **V260** | News-as-regime-detector (LLM over GDELT) | Phase-0 offline scorer (32 agy calls) | **R2/R5** | degenerate classifier: 94% one class, MI 0.11 bits — aggregate collapse (R5) below resolution (R2) |

### Frequency distribution (13 dead ends)

| Root cause | Count | Versions |
|---|---:|---|
| **R2 — below resolution** | **5** | V241, V245, V246, V248, V255-Ph0 |
| R1 — signal absence | 3 | V242, V243, V244 |
| R4 — data absence | 2 | V256, V259 |
| R5 — structural | 1 (+1 hybrid) | V258 (+V260) |
| R6 — friction geometry | 1 | V255.B |
| R3 — calendar-bound N | 0 direct, **but the framing of the entire arc** | (V249 meta-diagnosis) |

**R2 dominates (≈40%)**, and this is the single most important finding of the campaign. The R2 cluster
is *not* five independent failures — it is one structural fact wearing five masks. **R3 is the meta-cause
behind the R2 cluster:** the reason so many "real-looking" effects were unadjudicable is that the targeted
regimes (especially `recent`) have too few independent windows to resolve effects of the size these
mechanisms produce. V247 built the ruler that exposed the R2 deaths as noise; V249 proved the ruler could
not be sharpened from frozen data (only **4 independent recent windows** in the whole 2020→2026 span).

The R1 cluster (V242/V243/V244) is the *cheap-win* story: three mechanisms killed at $0 by sanity gates
and separator proofs before any grid burned. The R4/R5 cluster (V256/V258/V259/V260) is the *closeout*
story: once the entry-side composite was exhausted, every remaining offline lane hit either missing data
(R4) or an input structure that had already destroyed the signal (R5).

---

## B. Discipline outcomes

### Clean-refuted at $0 vs grid-burned

| Outcome | Count | Versions |
|---|---:|---|
| **Refuted at $0** (sanity gate / separator / offline scorer / data audit — no grid) | **7** | V242, V243, V244, V255-Ph0, V256, V258, V259 |
| **Cheap-refuted** (offline scorer or budget-capped probe, ≪ a grid) | 3 | V248, V255.B, V260 (32 agy calls) |
| **Grid-burned before refuting** (~8h walk-forward grid each) | 3 | V241, V245, V246 |

### Compute saved by the Phase-0 discipline

The pre-grid gates — **separator proof** (V234 rule), **offline Phase-0 scorer**, **data audit** — turned
what would have been ~8h walk-forward grids into minutes-to-$0 checks. Ten of the thirteen dead ends never
reached a grid. Conservatively, the separator/scorer/audit discipline **avoided ~10 × 8h ≈ 80 grid-hours**,
plus V258 specifically avoided a **~26h agy cache-fill grid** by killing the ensemble at a 38-minute
Phase-0 probe (the "do-not-grid-on-hope" rule). The three grids that *did* run (V241/V245/V246) were the
ones whose falsifier genuinely required the full distribution — that is the discipline working as intended,
not failing.

### Which discipline patterns actually caught bugs (vs belt-and-suspenders)

| Pattern | Caught a real bug/waste? | Evidence |
|---|---|---|
| **Pre-registration** (hypothesis + falsifier before code) | **YES — load-bearing** | Made V256/V259 anti-Goodhart salvages *visible as* HARKing and refused them; forced V260's degeneracy read to override the mechanical band honestly |
| **Separator proof before grid** (V234) | **YES — load-bearing** | Killed V236 (ER/VR don't separate) and V243 (corr-spike) at $0; the single highest-ROI gate in the loop |
| **The V247 ruler** (2·SE noise floor) | **YES — reframed the whole arc** | Exposed V246 (+$627 ≈ 2·SE) and V248 (+$494 < $625) as noise, not wins — without it both would have "shipped" |
| **Calendar-independent-N preflight** (V249) | **YES — ended the search** | Proved the recent regime has 4 independent windows; converted "8 refutations" from failure into a correct STOP signal |
| **Reflection triggers** (stagnation / Goodhart tripwire) | **YES** | The 3rd consecutive refutation at V246 fired the reflection that produced the V249 phase transition |
| **Hermetic frozen LLM cache** (V240.D) | **YES — infra win** | Makes every LLM experiment (V241/V258/V260) $0 to replay and deterministic; V260 re-runs cost nothing |
| **Matrix mode** | Belt-and-suspenders here | Available but the arc was mostly sequential-dependent; not the bottleneck |
| **Anti-Goodhart refusal** | **YES** | V256 and V259 both had a tempting single-scalar / live-forward salvage; both correctly refused |

The through-line: **the cheap gates (separator, ruler, N-preflight, sanity gate) did the heavy lifting.**
The expensive apparatus (full grids) was only worth running three times. The most valuable single artifact
was the V247 ruler — a noise floor in dollars — because it converted a stream of "marginal wins" into an
honest "inside noise, no adopt" verdict and thereby stopped the campaign from Goodhart-shipping variance.

---

## C. What we learned about the eval instrument

The campaign's deepest lessons are about the **measuring apparatus**, not any one signal.

1. **Measure the ruler before the thing (V247).** For 13 versions the loop read $100–$700 deltas as
   signal while the eval's own 2·SE noise floor on the recent regime was **~$727**. Once the ruler was
   built, half the "wins" evaporated. *Transferable lesson:* a backtest delta is meaningless without a
   co-measured noise floor; compute σ from multi-seed / multi-window variance **first**, and treat any
   delta < 2σ as unadjudicable by construction.

2. **Nominal N ≠ independent N (V249).** The manifest advertised 10 recent windows; only **4 are
   independent** (the other 6 are ±45d overlapping offsets — literal data reuse). Effect sizes below the
   n=4 MDE (~$2,043 at 2·SE) are **structurally unfalsifiable** from frozen data. *Transferable lesson:*
   before targeting a regime, count its independent windows mechanically (`floor(span/window)` cross-checked
   against non-offset manifest entries); if the target effect is below that floor, do not run the bet —
   no mechanism can rescue an unresolvable measurement.

3. **The passage of time is the only source of new independent windows (V249→V253).** Frozen data is
   fully tiled; denser offsets only add overlap; shorter windows break the warmup/cap contract. The only
   way to widen recent-N is to *wait* — each elapsed 90d = one new independent, un-Goodhartable,
   correctly-labelled window. This is why the phase transition points at **live paper**, and why the
   V250–V252 harness was reconciled **bit-identical** to the frozen backtest (V251: 32/32 windows,
   $0.00 arm-Δ) — so the accumulating forward windows are measured on the *same ruler* as the frozen ones.

4. **Hermeticity is a precondition for trusting any delta (V214–V221, carried forward).** The determinism
   arc that closed six FP-order channels is what makes a $30 mean-Δ legible at all; without byte-identical
   replay, the noise floor would swamp every result. The frozen LLM cache (V240.D) extends this to the
   LLM lanes — V241/V258/V260 are all $0-replayable.

5. **A validated off-Victoria alpha lane exists (V255.C).** The single genuinely *positive* discovery of
   the alt-data phase: funding-carry alpha is real (gross **29% annualized** at 7-day hold, net **18.6%**,
   p≈0 entry-funding separator, net-positive pooled). It is **KEEP-FLAG-GATED** pending basis (perp/spot)
   data to test the hedge (V255.D). *Transferable lesson:* when the primary universe saturates, an
   *uncorrelated mechanism* (carry, not momentum) is the escape hatch — but it must clear the same friction
   geometry (R6) that killed its directional and short-hold variants.

---

## D. Validated / unvalidated / impossible-to-validate map

An honest accounting of **where in signal space we have searched** and with what result.

### Validated (measured, holds within its stated scope)

- **Standing baseline** (V240 selective universe): crisis **+$599** / trend **+$2,997** / recent **+$30**
  = **+$3,626 pooled**, measured on the 32-window walk-forward distribution, DETERMINISM PASS $0.00,
  reconciled bit-identical to the live-paper feed (V251). This IS the Phase-1 deliverable. *Caveat:*
  awaiting the 90-day live-paper soak (V253) for genuinely out-of-sample confirmation.
- **V255.C funding-carry alpha:** validated *within scope* (single price series, no basis split) —
  gross 29% ann. carry, separator p≈0. Capped KEEP-FLAG-GATED.

### Refuted (measured, does not work — at the tested granularity)

- **Entry-side composite additions:** whale-gate (V242), corr-spike (V243), portfolio-sep (V244),
  GDELT-as-signal (V245) — the entry-side info-feed lane is **saturated at daily bars**.
- **Reasoning/LLM layer:** whole-basket review (V241) and specialist ensemble (V258) — variance, not
  expectancy; the second was input-starved by the first's collapsed payload.
- **Exit and portfolio sizing:** regime-adaptive exit (V246), portfolio sizing (V248) — inside noise.
- **News-as-regime-detector (V260):** degenerate at daily-aggregate granularity.
- **Directional / short-hold carry:** V255-Ph0 (price risk swamps), V255.B (friction eats median).

### Untested — data-blocked (thesis alive, needs a data freeze)

- **On-chain flow (V256/V257):** needs per-asset frozen inflow/velocity/whale/stablecoin series.
- **Basis-hedged carry (V255.D):** needs Binance mark/index (perp vs spot) freeze.
- **Polymarket sentiment (V259):** needs a frozen crypto-binary probability time series.

### Impossible to validate here (calendar-bound — needs elapsed time, not compute)

- **Any recent-regime effect below ~$2,043 (2·SE at n=4).** No offline mechanism can adjudicate it. Only
  live-paper accumulation to N≥20 independent recent windows can. This is the R3 wall.

### The signal-space map in one sentence

We have **exhaustively searched the daily-bar, entry-side, single-price-series corner** of signal space
(and found it saturated), **validated one uncorrelated carry lane** (pending hedge data), and **left
untouched** everything gated on finer time resolution (intraday), a different data modality (on-chain,
options, prediction markets), or elapsed forward time (recent-N).

---

## E. Strategic recommendations for the training-loop resume

**Not a pre-registration — a recommended ordering given today's constraints.** When V253 provisioning
completes and the acquisition runbooks (V255.D basis, V257 on-chain) deliver frozen data, the natural
priority order for V##9+ is:

1. **V255.D basis-hedged carry first** — it is the only lane with *already-confirmed alpha* (V255.C) that
   is merely one dataset away from a full test. Highest expected value, smallest remaining unknown. The
   V255.B R6 (friction) death is the specific thing the basis hedge is designed to fix; test that directly.
2. **V257/V256 on-chain flow second** — the structural escape from the recent-N wall (an uncorrelated
   per-asset mechanism manufactures *independent* windows), but only once ≥3 of 4 signals are frozen with
   ≥3-year history. Re-run V256 **exactly as pre-registered**, no salvage.
3. **Live-paper soak (V253) runs in parallel throughout** — it is the *only* source of new independent
   recent windows, accruing ~1/quarter toward the N≥20 resume gate. It requires no training-loop attention
   beyond the weekly audit; let it run.
4. **Do NOT reopen the daily-bar entry-side composite** without a genuine resolution change (intraday
   OHLCV freeze). V236→V248 closed that lane at daily bars; re-running mechanisms there is variance mining.

### Pause-vs-continue criteria (the campaign's operating rule, distilled)

**Continue the sequential V### loop when:** the next hypothesis targets a regime with sufficient
independent N for its effect size (N-preflight passes), AND a pre-grid separator/scorer can be built to
kill it cheaply if wrong, AND the data it needs is frozen.

**Pause (declare a phase transition) when ALL hold:** (a) the reflection stagnation trigger has fired and
the binding constraint is the *instrument/data*, not a subsystem; (b) the V247 ruler shows near-misses sit
inside the noise band (unadjudicable, not absent); (c) the N-preflight shows the targeted regime is
calendar-bound below the effect size. This is exactly the V249 condition — and the correct response was
not another mechanism but the live-paper harness.

**The one-line rule the whole campaign earned:** *never read a delta without its ruler, never target a
regime without counting its independent windows, and never grid a mechanism a $0 gate can kill first.*
