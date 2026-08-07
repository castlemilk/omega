# V254 — Alt-Data Scoping: escaping the calendar-bound recent-N wall (SCOPING ONLY)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** SCOPING MENU — **no implementation**
**Companion to:** [`V253.md`](V253.md) (the live-paper soak that accrues ~1 recent window/quarter) ·
[`V249.md`](V249.md) (phase-transition declaration) · [`CAMPAIGN_STATUS.md`](CAMPAIGN_STATUS.md)

> **The bottleneck.** The user's mandate is "get profitable reliably". The blocker
> is statistical, not mechanical: the **recent regime has only N=4 independent
> 90-day windows** in 2020→2026. The V247 ruler showed the recent bar (2·SE ≈ $727
> at n=10; ≈ $2,400 at n=4) is so wide that every entry-side mechanism V236→V246
> died at the noise floor. Widening recent-N to ≥20 either takes **~4 more years of
> calendar** (V253's live-paper drip, ~1 window/quarter) **or a new data source that
> changes the window structure**.
>
> This doc is the **parking lot** of alternatives to "wait 5 years". It is a
> **menu, not a proposal** — the user picks priorities for a hypothetical Phase 3.
> Nothing here touches `strategy.py`, `signal_generation.py`, or any flag. Each
> option is scoped, costed, and ranked, with an explicit **dead-end risk** grounded
> in the V241–V246 refutation patterns.

## The refutation patterns these options must survive

Every entry-side idea since V236 died one of these deaths. New options are risk-rated
against them:

- **R1 — Noise-floor death (V246):** an effect real in-sample (+$627 pooled ≈ 2·SE)
  but below the recent-N=4 noise floor (2·SE ≈ $2,400). *Anything that only adds
  signal without adding independent windows inherits this floor.*
- **R2 — Saturation death (V242–V245):** entry-side info feeds (corr-spike, gdelt
  solo, portfolio-sep, whale-gate) scored **$0** at the grid — the daily-bar
  composite is information-saturated. *New feeds at daily granularity likely
  saturate too.*
- **R3 — Whole-basket-review death (V241):** one LLM reviewing the composite basket
  = 99.6% intervention for +$31 pooled (variance-for-nothing). *Coarse, basket-level
  LLM framings are refuted.*
- **R4 — Goodhart death (V231, victoria_snapshot memory):** an effect that fit one
  crisis window ($25k cross-window spread) and didn't generalize. *In-sample tuning
  without out-of-sample windows repeats this.*

The **only** structural escape from R1 is **more independent windows** — which is why
options that *manufacture new independent recent-regime distributions* (B, and to a
degree A) rank above options that *add signal to the existing one* (C, F).

---

## A. Higher-frequency / shorter backtest windows

**Idea.** Get more windows out of the same calendar by shortening the window span
and/or the bar interval.

- **Hourly bars, same 90-day span:** bar count ×24, but the number of *independent*
  windows is unchanged — a 90-day hourly window still spans the same 90 calendar
  days and overlaps its neighbours identically. **This does not move recent-N.** It
  only helps if the *strategy horizon* also shortens (intraday alpha), which is a
  different strategy, not a re-windowing of this one.
- **Shorter windows (30d / 10d):** a 30-day window is genuinely a shorter calendar
  span, so 2020→2026 yields **more non-overlapping windows** — roughly 3× the count
  of 90-day windows. Naive arithmetic: if 90d gave N=4 recent, 30d gives **~N=12
  recent**; 10d gives ~N=36.
- **The catch — regime-label reliability.** The regime label
  (`walk_forward_freeze.py:regime_label`) is derived from macro/vol structure that is
  only meaningful over a multi-week horizon. At 30d the label is noisier; at 10d it's
  largely meaningless (a 10-day "recent" window can't be reliably distinguished from
  "trend" or "crisis"). So the **effective** independent-N is far below the naive
  count — shrinking the window trades window *count* for label *reliability* and for
  per-window *signal* (each window has fewer trades → wider per-window SE). You move
  the noise floor from "few windows, each tight" to "many windows, each loose" — the
  pooled SE may barely improve.
- **Realistic read:** 30d windows *might* get to a **defensible N≈8–12 recent** if
  the label holds, but only after re-validating that `regime_label` means anything at
  30d (it may need re-derivation). 10d is almost certainly below the label-validity
  floor. This is the **cheapest** option but the **most likely to be an illusion** —
  the windows are less independent than they look because the regime structure that
  defines "recent" doesn't refresh every 30 days.

| | |
|---|---|
| **Cost** | 2–4 dev-days (re-window the walk-forward harness + re-validate `regime_label` at 30d). $0 ongoing (uses frozen data). |
| **N accumulation** | Instant one-shot: naive N=4→~12 at 30d, but **effective N likely ~6–9** after label-reliability discount. Does not accrue over time. |
| **Dead-end risk** | **HIGH.** Squarely in **R1/R4**: shorter windows don't add *independent* regime information, they resample the same 6 years at finer grain. High risk the "extra" windows are label-contaminated and the pooled SE barely tightens. |
| **Priority** | **3** — cheap enough to be worth a **1-day feasibility spike** (just re-validate `regime_label` at 30d and count truly-independent windows) before investing. If the label holds at 30d, promote; if not, discard. |

---

## B. Cross-asset / carry universe expansion (independent strategies)

**Idea.** The current 10-name selective universe is all directional crypto. Add
**structurally different strategies** — crypto-carry (funding-rate arb), stablecoin
depeg, DeFi yield, cross-chain arb — **each as its own strategy with its own
recent-regime distribution.** Because each strategy trades a different mechanism, its
recent windows are **statistically independent of the directional book's** — this
manufactures genuinely new independent-N rather than resampling the same one.

- Funding-rate carry: long-spot/short-perp (or vice versa) harvesting the funding
  basis. Its PnL is driven by funding dynamics, ~uncorrelated with the directional
  composite's momentum alpha.
- Stablecoin depeg: mean-reversion around USDC/USDT/DAI peg deviations. Rare, fat-
  tailed, its own regime structure.
- DeFi yield / cross-chain arb: even further from directional crypto.
- **The structural win:** N is *per strategy*. Four independent strategies each with
  N=4 recent windows give you four independent noise floors — and a portfolio-level
  "reliably profitable" claim can rest on **diversification across mechanisms**, which
  is a stronger route to "profitable reliably" than tightening one strategy's SE.
- **The cost:** each new strategy needs its own V240-style loop (freeze the data,
  build the signal, walk-forward, gate). This is real infra — you're standing up 1–4
  new sub-projects, not adding a signal.

| | |
|---|---|
| **Cost** | 8–15 dev-days **per strategy** (data freeze + signal + walk-forward harness + gates). Carry is the cheapest (funding data already partially wired — `data_cache.get_funding_rate`). Ongoing: exchange/DeFi data fees, low $. |
| **N accumulation** | **Best structural story.** Each strategy adds an *independent* recent-N=4 immediately (from its own frozen history), and they accrue in parallel during any live soak. Diversification, not just SE-tightening. |
| **Dead-end risk** | **MEDIUM.** Avoids R1/R2 (different mechanism, not the saturated directional composite). Real risk is per-strategy: carry has capacity/borrow-cost realism issues; depeg is fat-tailed and rare (its own small-N problem); DeFi adds smart-contract/oracle risk the backtest can't model (a new R4 surface). |
| **Priority** | **1** — the highest-leverage structural escape. **Funding-rate carry first** (cheapest, data half-wired, cleanest mechanism). It's the only option that credibly delivers "reliably profitable" via diversification rather than waiting on SE. |

---

## C. On-chain flow as a *primary* signal universe

**Idea.** Whale flow was tried as a *signal inside the composite* (V240 Track B,
regime-gated) and refuted. The rehab is to treat on-chain flow as a **primary
signal universe** — a strategy whose entries are *driven* by flow, not a feature
bolted onto the momentum composite.

- Candidate primaries: net exchange inflow/outflow, stablecoin supply changes
  (mint/burn), funding-rate divergence across venues, Coinbase premium
  (US-institutional demand proxy).
- The distinction from V240-B: V240-B asked "does whale_flow improve the *existing*
  composite's entries?" (answer: no, it's the V238 tradeoff — crisis +$2,063 /
  trend −$2,433). This asks "can a flow-*primary* book stand on its own?" — a
  different strategy with its own N, closer in spirit to option B.

| | |
|---|---|
| **Cost** | 6–12 dev-days (freeze on-chain series — Glassnode/CryptoQuant/Dune or free RPC-derived — wire as feeds, build a flow-primary entry rule, walk-forward). Ongoing: on-chain data API ($50–500/mo depending on provider) OR self-hosted node/indexer (dev-heavy, $0 data). **[V256: the data-freeze step is the actual blocker — see status below.]** |
| **N accumulation** | Its own independent recent-N=4 from frozen on-chain history (data goes back to ~2017 for most metrics). Accrues in parallel during a soak. |
| **Dead-end risk** | **MEDIUM-HIGH.** V240-B already showed flow is a *tradeoff*, not free alpha, inside the composite — as a primary it inherits R2 risk (flow may be priced at daily granularity) and R4 (on-chain metrics are heavily revised/re-defined by providers → look-ahead/label drift). Lower risk than A, higher than B. |
| **Priority** | **2** — structurally similar to B (new independent universe) but with more data-integrity landmines. Pursue **after** carry (B), or fold in as one of B's strategies rather than a separate track. |

> **STATUS UPDATE (V256, 2026-07-14): PAUSED — needs data acquisition.** V256
> attempted Track C and **stopped at the Phase-0 data audit** ([`V256.md`](V256.md)).
> Blocker: **no historical per-asset on-chain data is frozen** — only 1 of the 4
> pre-declared signals exists on disk (`stablecoin_total_usd`), and it's a
> **market-wide aggregate**, not the cross-sectional per-asset shape the flow-primary
> design needs. Net exchange inflow + whale-cluster movement are live-only (no
> historical endpoint sourced); active-address velocity was never sourced. The thesis
> is **untested, not refuted** — the offline data to test it does not exist in frozen
> form. **Reclassified from "#1-offline" to "PAUSED — needs data acquisition
> (V257)".** [`V257.md`](V257.md) pre-registers the data-freeze pipeline that unblocks
> it (Coin Metrics community as free MVP source for BTC+ETH). Track C reopens the
> moment V257 delivers 3+ frozen signals; until then it is **not** the lead offline
> bet.

> **STATUS UPDATE (V257 executed, 2026-07-15): UNBLOCKED — Track C is PRIMARY
> offline (buildable) again.** V257 ran the freeze pipeline
> (`scripts/v257_freeze_on_chain.py`) against Coin Metrics **community** tier (free,
> no key) and delivered **4 of 4** V256 signals frozen per-asset for {BTC, ETH},
> each **6.5-year daily** coverage (2020-01-01 → 2026-07-14, 2387 obs, 0% gaps),
> byte-identical on re-run. Signal → community-metric mapping:
> #1 net exchange netflow ← `FlowInExNtv`−`FlowOutExNtv`; #2 active-address velocity
> ← `AdrActCnt`; #3 whale-cluster movement ← `SplyExNtv` (exchange-held-supply
> accumulation/distribution proxy); #4 transaction volume ← `TxTfrCnt`(+`TxCnt`).
> The runbook's assumed `TxTfrValNtv`/`SplyAct1yr` are paid-tier (403) and
> `FlowInBTC`/`FlowOutBTC` are invalid ids (400); the community substitutes above
> cover all four signals. Data at `data/frozen_series/on_chain/{BTC,ETH}/`. Track C
> **reclassified from "PAUSED — needs data acquisition" back to "PRIMARY offline
> (buildable)"**. Next: build the V256 flow-primary offline scorer + walk-forward
> **exactly as pre-registered** (a follow-on V###, not this data task). See
> [`V257_VERDICT.md`](V257_VERDICT.md).

> **FINAL STATUS (V261 built + scored, 2026-07-15): REFUTED — Track C CLOSES.**
> The V256 flow-primary offline scorer was built exactly as pre-registered
> (`omega/nodes/on_chain_flow/`, [`V261.md`](V261.md)) over V257's 4/4 frozen
> signals and scored against the locked falsifiers ([`V261_VERDICT.md`](V261_VERDICT.md)).
> **F2 (mechanism gate) fired decisively: MWU p=0.942** — a stronger composite \|z\|
> is a coin-flip on trade outcome (winners' median \|z\| 1.275 ≈ losers' 1.288). The
> nominally-positive pooled median (+$11.74 over 334 BTC+ETH trades, 36% annualized
> gross) is **inside its own noise** (bootstrap CI95 [−$45.69, +$62.69] spans zero)
> and carries **no dose-response** — consistent with the R2/saturation deaths of the
> V241→V258 daily-bar entry-side lane. Every single component is net-negative; the
> SplyExNtv proxy is not load-bearing (LOO-whale also fails the mechanism gate,
> p=0.62). Reclassified from "PRIMARY offline (buildable)" to **"attempted, REFUTED
> at Phase-0 offline — no daily-bar dose-response; reason not data absence."** Track C
> was the last data-blocked offline lane; the offline alpha search is now fully
> reported (funding-carry V255.C/.D the single surviving confirmed lane). Remaining
> escape from the daily-bar wall is unchanged: intraday resolution or live-paper
> recent-N accumulation. NO strategy/flag code touched; $0.

---

## D. Polymarket / prediction-market sentiment

**Idea.** Omega already has a substantial Polymarket subsystem
(`omega/nodes/polymarket/`: `clob_client.py`, `edge_detection.py`, `vol_arb.py`,
`top_traders.py`). Two sub-ideas:
1. **As a continuous live feed into Victoria:** map relevant binary-option prices
   (macro/crypto-outcome markets) to a continuous sentiment/probability series and
   add it as a V250-style info feed.
2. **As a regime indicator:** use Polymarket *volumes* and price *dispersion*
   themselves as a market-stress / regime signal.

- **Feasibility of "continuous enough":** individual binary markets are **not**
  continuous — they resolve and disappear, have thin/gappy books, and short lifespans.
  A *basket* of related markets (e.g. an aggregated "crypto-up-by-EOY" family) can be
  smoothed into a continuous series, but the history is **short** (Polymarket liquidity
  is mostly 2023+) and **sparse** — which directly undercuts the recent-N goal (you
  can't build many independent recent windows from ~2 years of thin data).
- **As a regime indicator:** volume spikes / probability dispersion around macro
  events are plausibly a stress proxy, but this is a *feature*, not a new independent
  universe — so it inherits **R2 saturation risk** against the existing composite.

| | |
|---|---|
| **Cost** | 4–8 dev-days (the CLOB/data plumbing exists; the work is series-construction + freeze + wiring as a feed). Ongoing: Polymarket data is free (public CLOB). |
| **N accumulation** | **Poor** — short/thin history (~2023+) means *fewer* independent recent windows than crypto already has, not more. Helps signal, not N. |
| **Dead-end risk** | **HIGH.** As a feed → **R2** (another daily-granularity feature into a saturated composite). As a regime indicator → **R4** (short history, structural changes in Polymarket liquidity over its own short life). Does not attack the N bottleneck. |
| **Priority** | **4** — interesting and cheap-ish because the plumbing exists, but it does **not** solve the recent-N wall (its history is *shorter* than what we have). Park unless a specific event-driven overlay is wanted for its own sake. |

---

## E. TradingAgents-style specialist-LLM ensemble (rehabilitated from V241)

**Idea.** V241 refuted **one** LLM framing: a single agent reviewing the *whole
composite basket* (R3). It did **not** test the TradingAgents pattern —
**many specialist agents**, each narrow, contributing per-name or per-signal-type
inputs that the composite aggregates.

- Sketch of a specialist architecture (reusing `reasoning_layer.py` infra, already
  built in V240-D):
  - **Per-signal-type analysts:** a momentum analyst, a macro analyst, an on-chain
    analyst — each emits a structured view for its slice only, not the basket.
  - **Per-name analysts** for the 10-name universe, each reasoning about one asset's
    idiosyncratic setup.
  - **A risk/regime debate layer:** bull vs bear agents argue, a judge emits a
    regime-conditional conviction — feeding the *existing* regime gate rather than
    overriding entries wholesale.
  - Aggregation is **structured and per-name**, so intervention is targeted (unlike
    V241's 99.6% whole-basket veto).
- **Why it might survive R3:** the refutation was specifically about coarse,
  basket-level review producing indiscriminate intervention. Narrow specialists that
  contribute *bounded per-name deltas* are a categorically different intervention
  profile — testable against the same walk-forward gates.
- **Why it still might not:** it adds *signal*, not *independent windows* → inherits
  **R1** (evaluated on the same N=4 recent, below the noise floor) and **R2** (the
  composite may already be saturated, so specialist views add nothing net). The V241
  reasoning-layer infra lowers the *build* cost, but the *evidence* cost is unchanged.

| | |
|---|---|
| **Cost** | 5–10 dev-days (prompt-harness for specialists + aggregation + `frozen_llm_cache` extension; `reasoning_layer.py` + `frozen_llm_cache` exist). Ongoing: LLM inference $ — but the frozen cache means backtests replay cached completions ($0 re-run); live soak pays per-cycle inference (low, one pass/day). |
| **N accumulation** | **Zero** — a signal layer, not a new universe. Evaluated on the existing recent-N=4. |
| **Dead-end risk** | **MEDIUM-HIGH.** Escapes R3 (narrow ≠ whole-basket) but sits directly on **R1+R2**: even if specialists are individually sensible, they're judged at the N=4 noise floor against a saturated composite. Needs option A or B to have widened N *first* to be evaluable at all. |
| **Priority** | **4** — architecturally the most interesting rehab, and cheap to build on existing infra, but **gated on N widening** — running it before recent-N grows just re-buys a V241-style inconclusive at the noise floor. Revisit **after** B or A moves N. |

---

## F. Deep-research / news-driven regime detection

**Idea.** V245 refuted **gdelt solo at daily granularity** (R2). The rehab is a
**richer, LLM-extracted regime signal**: a daily pass that reads GDELT tone + top
news headlines + the FOMC/macro-event calendar and emits a **regime probability**,
used to gate ent/exit of the *standing* strategy (not to add entries).

- Sketch: daily LLM job → structured `{regime: crisis|trend|recent, p: 0..1,
  drivers: [...]}` → feeds the existing regime gate's prior. Finer than gdelt-tone-
  alone because it fuses calendar (known-ahead events) + extracted event semantics +
  quantitative tone.
- **Why it might beat V245:** V245 used raw GDELT *tone* as a scalar; this uses an
  LLM to *extract regime-relevant events* (rate decisions, ETF flows, exchange
  failures) that tone alone smears out. It's a semantics upgrade, not more of the
  same scalar.
- **Why it still might not:** it's a **regime-gate feature**, so it's judged on the
  same recent-N=4 (**R1**), and the composite's existing regime detection may already
  capture most of it (**R2**). Also a fresh **R4** surface: LLM event-extraction over
  a *frozen* news corpus risks look-ahead if the corpus isn't strictly as-of
  (headline timestamps must be point-in-time — a real freeze-integrity hazard).

| | |
|---|---|
| **Cost** | 6–10 dev-days (as-of news corpus freeze — the hard part — + FOMC calendar + LLM extraction harness on `reasoning_layer.py` + regime-gate wiring). Ongoing: news API ($ varies) + daily LLM inference (low). |
| **N accumulation** | **Zero** — a regime-gate feature on the existing universe/N. |
| **Dead-end risk** | **MEDIUM-HIGH.** Escapes R2-at-scalar (semantic extraction ≠ raw tone) but lands on **R1** (noise floor) and a sharp **R4** (as-of news integrity — look-ahead is easy to introduce and hard to detect). Regime-gate features have a poor track record (V241 reasoning-layer, V245 gdelt). |
| **Priority** | **5** — the weakest N story combined with the highest data-integrity hazard (point-in-time news). Interesting research, but last for a profitability-driven Phase 3. Only pursue if a specific event class (e.g. FOMC) is believed under-captured **and** N has already widened. |

---

## UPDATE 2026-07-14 — Option B Phase 0 result: v2 directional carry REFUTED

V255 built option B's cheapest sub-bet (funding-rate carry) and ran a $0 Phase-0
separator ([`V255.md`](V255.md) / [`V255_PHASE0.md`](V255_PHASE0.md)). Outcome:

- **v2 directional (funding mean-reversion) is REFUTED** — entry z-score does not
  discriminate winners from losers (MWU p=0.61, scipy-confirmed), −$260k / 2300
  trades. The directional form is a momentum-contrarian bet whose price risk
  (−$292k) swamps the carry.
- **The carry component is real** (+$55k gross, +$24/trade) but the hedged v1
  basis form is thin: ~7–10% annualized **gross, median ≈ $0, tail-driven**,
  *before* real basis-execution frictions. Separators point at the *correct* form
  (funding **level** entry p<0.0001; exclude `near_zero` regime which is 58% of
  trades and >100% of the loss).
- **The "much more independent N" premise is partially undercut:** funding regimes
  DO form a different partition than spot (independence holds), but `near_zero`
  swamps 16/26 slots and effective carry-regime N ≈ 10 — comparable to spot, not
  a windfall.

**Reprioritization (updated after V255.C — 2026-07-14):** the carry lane ran to
completion. **V255.B** REFUTED the v1 basis-hedged carry on friction geometry
(3-day hold, median net −$5.95) but CONFIRMED the alpha is real (36.4% annualized
gross, |entry funding| separator p≈0 in every regime). **V255.C** — its own
pre-registered recommendation — then re-parameterized (7-day hold + level-scaled
sizing + maker fees) and **PASSED every falsifier**: pooled median net **+$1.56**
(bootstrap CI95 [+$0.85, +$2.39], excludes zero), WR 63.9%, annualized gross 29.0%
/ net 18.6%, separator p≈0 in all 3 regimes, total net **+$41.1k**. Verdict:
**KEEP-FLAG-GATED** — the funding-carry edge is **validated but blocked** on a hard
data caveat: frozen data has one `close` series per symbol, so the basis hedge is
verified algebraically not empirically, capping any verdict below ADOPT.

**Consequence for the ranking:** B (funding-carry) is **NOT closed** — it is
**PROVISIONAL: needs basis data**. It is a proven edge whose only remaining unlock
is a real perp-mark + spot-index basis series (V255.D: live-host provisioning, out
of scope offline). Because that unlock is a data-acquisition task rather than an
offline modeling bet, on-chain flow (C) was promoted to lead offline bet.

## UPDATE 2026-07-14 (b) — Track C paused at Phase 0; C AND B both data-blocked

V256 attempted Track C and **stopped at the Phase-0 data audit** before writing any
code ([`V256.md`](V256.md)). The flow-primary universe is **unbuildable offline
today**: only 1 of 4 pre-declared on-chain signals is frozen (`stablecoin_total_usd`,
a market-wide aggregate — not the cross-sectional per-asset shape the design needs).
Net exchange inflow and whale-cluster movement are live-only; active-address velocity
was never sourced. Salvaging into a 1-signal market-timing test would be a post-hoc
Goodhart redesign (R4) — explicitly declined.

**Both of the top-2 offline candidates are now data-acquisition-blocked, not
modeling-blocked:**
- **B** (funding-carry) — needs a real perp/spot **basis** series (V255.D, live-host).
- **C** (on-chain flow) — needs frozen historical **per-asset on-chain** series (V257).

**Consequence: the next *buildable-offline* bet is a signal-only path.** With C and B
both parked on data, the highest-ranked option that can be *built and tested today with
data already on disk* is **Track E (specialist LLMs)** — it reuses the V241
`reasoning_layer.py` + `frozen_llm_cache` infra, is a **prompt-only change** (no new
data freeze), and is therefore the **cheapest to test**. **Track D (Polymarket)** is
the next-cheapest (CLOB plumbing exists) but needs series-construction from thin ~2023+
history. **Caveat (unchanged from original scoping):** both D and E are **signal-only**
— they add signal to the existing universe and are judged at the **N=4 recent noise
floor** (R1), and against a possibly-saturated composite (R2). Neither attacks the
recent-N wall. They are "buildable now" bets, **not** structural escapes; the
structural escapes (B, C) remain gated on their respective data unlocks.

## UPDATE 2026-07-15 — Track B UNBLOCKED: V255.D froze real basis → **ADOPT** (BTC/ETH)

The V255.D data-acquisition + re-verify ran ([`V255_D_VERDICT.md`](V255_D_VERDICT.md)).
`scripts/v255d_freeze_basis.py` froze the real Binance perp-**mark** + spot-**index**
daily series for BTC + ETH (2020-06 → 2026-07, 6.1 yr, <1% missing, byte-identical
re-freeze). Re-pricing the two carry legs independently made the basis residual a
**measured** number instead of an algebraic zero:

- **Measured basis residual = median 3.04 bps of notional** (p95 12.85 bps) — well
  under the pre-registered 10 bps "clean" bar (§5.4), and *slightly favorable*
  (residual PnL +$122.88 over 168 trades). Real basis was a small tailwind, not a tax.
- **Full-universe pooled median holds at +$1.56, CI95 [+$0.86, +$2.53]** (excludes 0);
  the **BTC+ETH measured-only subset is stronger** (+$3.09, CI [+$0.83, +$6.74], both
  names positive independently).
- **Verdict = ADOPT.** The zero-basis assumption V255.C rested on was sound. The
  KEEP-FLAG-GATED cap is **removed for the BTC/ETH funding-carry book.**

**Consequence for the ranking:** Track B is **NO LONGER data-blocked** — it is the
first alt-data track to reach ADOPT. Scope is BTC/ETH (the measured names); extending
to SOL/XRP/AVAX only needs `--symbols` on the freeze script + a rerun (their mark/index
archives begin ~2022). This makes B the **shipped structural escape**; C (on-chain,
V257) remains the next data unlock.

## UPDATE 2026-07-15b — Track B STRENGTHENED: ADOPT extends to the full liquid universe

The V255.D freeze was extended from BTC/ETH to the whole 11-name selective universe
([`V255_D_EXTENDED_VERDICT.md`](V255_D_EXTENDED_VERDICT.md)). All 11 names have
mark+index archives on `data.binance.vision`; all froze with < 1% missing bars
(byte-identical per settled bar). Real basis now prices **1,108 of 1,225 trades
(90.4%, up from 168 / 13.7%)**:

- **Pooled median net rises +$1.56 → +$1.95, CI95 [+$1.13, +$2.80]** (excludes 0, tighter
  than the BTC/ETH-only run). Real basis was again a *net tailwind* (+$3,248.80 across
  1,108 trades, PF 3.41), not a tax.
- **Every one of the 12 measured names is basis-CLEAN** — median |residual| < 5 bps each,
  all under the 10 bps §5.4 bar. **Zero dirty names.** No name's ADOPT flipped to REVERT
  *because of basis*.
- **Per-name eligibility is gated by carry alpha, not basis:** decisively-positive majors
  **BNB +$10.54, SOL +$3.31, BTC +$3.60, ETH +$2.97, DOT +$3.02** = ADOPT; LINK/ADA/XRP/AVAX
  positive but thin; **ARB / NEAR / SUI stay FLAG-GATED on carry thinness + small-N**
  (all basis-CLEAN — their weakness is alpha, not friction). **MATIC is ADOPT-provisional**:
  the trade universe names it `MATICUSDT` but the futures archive is `POLUSDT` (post-rename),
  so POL froze but doesn't join the 86 MATIC trades — needs a MATIC→POL alias in
  `basis_data.py` (follow-on).
- **SOL tail caveat:** one FTX-week hold (2022-11) shows a genuine 21% mark/index basis
  dislocation — real, name-specific tail risk to size for, but robust to the median test.

**Consequence:** Track B is not just shipped, it is **broad** — the ADOPT covers the full
liquid book, the zero-basis assumption held across 90% of trades, and the only cap on
per-name adoption is carry-alpha thinness on the small alts (not basis cost). C (on-chain,
V257) remains the next data unlock.

| Rank (updated V262-2) | Option | Status | Next |
|---|---|---|---|
| **— CLOSED, zero-shot AND fine-tuned (V263 2026-08-02 → V264 2026-08-08; see UPDATE below)** | **H. Pretrained K-line foundation model (Kronos)** | **REFUTED at F4, the pre-declared smoke gate.** First candidate in the campaign that is *not* a re-weighting of the existing composite: `NeoQuasar/Kronos-small` (24.7M, 512 ctx), decoder-only transformer pretrained on 45+ exchanges' OHLCV, run zero-shot over the V262 frozen 1h corpus. Install clean (torch 2.13 cp314 + einops only — **no pandas/hf_hub downgrade**, Kronos's pins ignored safely); MPS inference 1.0 s/window; forecasts non-degenerate and seed-reproducible **bit-identical**. But across **8 pre-declared cells (3 symbols × horizons {1,4,12,24}, n≈405 each, 3,238 windows)**: **mean Spearman ρ = −0.027 vs the +0.05 F4 bar**, **0/8 cells beat a naive random-walk on RMSE** (median ratio 1.12–1.37), **0/8 survive Bonferroni** (α=0.0063), and forecast paths carry only **~1/3 of realized bar-to-bar volatility** (vol ratio 0.31–0.39) — conditional-mean collapse, no volatility clustering. The one nominally-interesting cell (SOLUSDT h24, raw 56.2%, uncorrected p=0.015) is a 1-in-8 draw that points opposite BTCUSDT h24. Also a systematic unconditional **short bias** (forecast↑ 0.46 vs realized↑ 0.51) | **Closed on evidence at Phase 0/1 — the cheapest closure in the campaign (~2h, $0, no scorer built).** Pattern **R1 (no effect present)**, not R2/R3: unlike V262-2 there is no gross effect for friction to kill. **V263-2 NOT queued.** Reopeners if ever revisited, in cost order: (1) **fine-tuning** via Kronos's `finetune/` pipeline — zero-shot failure on crypto 1h is genuinely uninformative about the fine-tuned case; (2) Kronos-base/mini to separate capacity vs context; (3) **distributional use** — forecast *spread* as a volatility/regime input, which needs no directional edge. See [`V263_ONBOARDING_VERDICT.md`](V263_ONBOARDING_VERDICT.md) + [`V263.md`](V263.md) |
| **— CLOSED at 1h (V262-2, 2026-07-30)** | **G. Intraday resolution (1h)** | **REFUTED at F1+F2+F3, both arms.** P0 first re-froze the corpus (µs/ms normaliser + a structural in-month gate + a **second** wall-clock channel closed: the archives-fetched count in the daily-splice provenance string); byte-identity **919/919**, 672 pre-2025 cells preserved; **F4 re-run on full coverage still PASS and stronger, V = 0.1274** (was 0.1509), and the POL n=29 caveat retired (true n=166, V=0.1869). Then F1–F3 on the pre-registered composite (`V262-2.md`, committed before the build): **median net −$31.98 (M) / −$9.96 (R); MWU p_deflated 0.331 / 0.488 vs α=0.025; annualized net −415% / −200%.** What fired is a real ~14 bps 1h **mean-reversion** gross effect (R: gross median +$14.04, WR 52.9%, PF 1.151) that (a) has **no dose-response** — p=0.923 at n=38,139 on the native-only arm, the bid-ask-bounce fingerprint — and (b) is **below the 24 bps friction at every hold in the ladder** (best break-even 14.04 bps, and the edge *decays* with hold: 10.6 bps at 1d, negative at 3d/7d) | **Closed on evidence, not data absence.** F4/F4b survive — effective-N is real (~19–21×); the *payoff* is not. **Do NOT freeze 5m**: the pre-declared tier order gated it on 1h clearing F4 **and F3**, and 5m would be 288× the bars against a friction wall that already won, with 288× the overfit surface. Redirects to spot Victoria + funding-carry; **live-paper (V253) is now the only lane accruing new independent evidence** (~1 recent window/quarter toward the N≥20 resume gate). See [`V262_F1F2F3_VERDICT.md`](V262_F1F2F3_VERDICT.md) + [`V262-2.md`](V262-2.md) |
| ~~1 — TOP-PRIORITY FOLLOW-ON (V262, superseded above)~~ | **G. Intraday resolution (1h / 5m)** | **DATA UNLOCKED (V262, 2026-07-25) + BOTH CHEAP GATES PASSED (2026-07-28)** — 1h OHLCV frozen for all 13 universe names + MATIC, 2020-01→2026-07, byte-identical; 5m available and *cheap* (~0.6 GB) but deliberately NOT frozen pending user call. **F4 regime-independence: universe-mean Cramér's V = 0.1509 vs the 0.7 refute cut** (corroborated 0.1782 in the non-degenerate diagnostic arm) → hourly per-name regime is **genuinely orthogonal** to the macro-day regime. **F4b autocorrelation: CAVEATED PASS — universe-mean lag-1 same-state = 0.8622 vs the 0.90 FAIL cut**; the raw figure is almost all marginal skew (excess over memoryless baseline **+1.2 pts**), λ₂ ≈ 0.13 ⇒ **N_eff/N ≈ 0.78–0.87, effective multiplier ~19–21× (NOT 24×)**. All four arm×coverage cells agree. Adjacent hourly windows are genuinely new samples | **V262-2 proceeds to F1–F3** (pooled median, MWU p, annualized net) via the 1h walk-forward, **deflating every significance calc by N_eff, never N**. F3 (friction at intraday trade frequency) remains the most likely killer. **P0 before F1–F3: fix the µs/ms unit defect in the frozen corpus** (2025-01→2026-07 files store `open_ms` in microseconds — 26.7% of bars; it silently truncated F4's coverage). Remaining F4 residual risks: lag>1 dependence, new-labeller correctness, POL n=180. See [`V262_F4b_AUTOCORRELATION_VERDICT.md`](V262_F4b_AUTOCORRELATION_VERDICT.md) + [`V262_F4_VERDICT.md`](V262_F4_VERDICT.md) + [`V262.md`](V262.md) |
| **1-SHIPPED (structural)** | B. level/regime basis carry (v1) | **ADOPT — full liquid universe (V255.D-EXT)**: real basis frozen on 12 names (90.4% of trades), pooled median +$1.95 (CI [+$1.13,+$2.80] excl 0), all 12 basis-CLEAN < 5 bps; majors decisive, ARB/NEAR/SUI FLAG on alpha-thinness | MATIC→POL alias in `basis_data.py`; wire ADOPT'd majors carry book |
| **1 (structural, buildable-offline now)** | C. On-chain flow primary universe | **UNBLOCKED (V257 executed 2026-07-15)** — 4/4 signals frozen per-asset {BTC,ETH}, 6.5yr daily, byte-identical | **rerun V256 as pre-registered**: flow-primary offline scorer + walk-forward over `data/frozen_series/on_chain/` (follow-on V###) |
| **1 (buildable-offline now)** | E. Specialist-LLM ensemble | untested | **next offline bet** — reuses V241 infra, prompt-only, cheapest; but N=4-pinned |
| 2 (buildable-offline now) | D. Polymarket sentiment/regime | untested | after E — plumbing exists, but thin ~2023+ history; N=4-pinned |
| **—** | B.dead — v2 directional carry | **REFUTED (V255)** | closed |
| 4 | A. Shorter (30d) windows | untested | `regime_label`-at-30d spike |
| 5 | F. News-driven regime | untested | last |

---

## UPDATE 2026-08-08 — Track H CLOSES: fine-tuned Kronos also fails F4

V263 closed Track H at zero-shot and named **fine-tuning as reopener (1)**, on the
explicit ground that *"zero-shot failure on crypto 1h is genuinely uninformative
about the fine-tuned case."* [`V264`](V264.md) executed that reopener. It is now
closed too.

**Result: F4-ft FAILED at pooled Spearman ρ = +0.0465 vs the locked +0.05 bar.**

| Arm (identical 2025–2026 holdout windows, 8 cells × 405) | pooled ρ | CI95 (10k paired bootstrap) |
|---|---:|---|
| Zero-shot | +0.0277 | [−0.0088, +0.0645] — includes 0 |
| **Fine-tuned** | **+0.0465** | [+0.0096, +0.0830] — **excludes 0**, does **not** exclude the bar |
| **Δ (fine-tuned − zero-shot)** | **+0.0188** | **[−0.0108, +0.0469] — includes 0** |

P(true ρ > bar) = **0.42**. The pre-registered claim — *fine-tuning produces edge
zero-shot lacked* — is **unsupported**: the delta's CI includes zero. The stretch
error gate failed harder than zero-shot did (**0/8** cells beat a naive random
walk; RMSE ratios *rose* vs zero-shot, BTC h24 1.321 → 2.093).

**What fine-tuning actually bought.** V263 diagnosed conditional-mean collapse
(forecast paths ~⅓ of realized volatility). Fine-tuning partially corrected that —
higher-dispersion paths, which nudge rank correlation up and make point-forecast
error much worse. **It taught Kronos our volatility, not our direction.**

**Pattern reclassification: R2 (below resolution), not V263's R1 (no effect).** A
small positive directional correlation genuinely exists (CI excludes zero); it sits
below the tradability bar. And a caution for the campaign record: the *same*
zero-shot model scores −0.027 over 2020–2026 (V263) and +0.0277 over 2025–2026
(V264) — a **between-period swing larger than the entire F4 bar**, so neither
number is a stable estimate. V263's confident R1 label softens accordingly.

**Fine-tune was mechanically sound** (so this is not a training failure): tokenizer
val loss ↓ monotone over 3 epochs (0.003665 → 0.003470); predictor val bottomed at
epoch 1 (2.5697) and drifted up after — best-by-val checkpoint used, and the epoch
budget was fixed *before* the gate was checked. Longer training is contraindicated
by the epoch-2 val turn, and capacity is not obviously the constraint (a 24.7M
model already overfits 374k bars) — **data is**.

**Track H is CLOSED for this universe.** The only untested Kronos idea left is
V263's reopener (3), **distributional use** — forecast *spread* as a
volatility/uncertainty input to the **regime layer**, which needs no directional
edge and is now *better* motivated by §"what fine-tuning bought". That belongs to
the regime-detection lane, not the alpha lane, and is **not queued**.

Standing state unchanged: **spot Victoria + funding-carry** remain the two validated
lanes; **live-paper (V253)** remains the only lane accruing independent recent-N.
All V241–V264 flags stay OFF. See [`V264_FINETUNE_VERDICT.md`](V264_FINETUNE_VERDICT.md)
+ [`V264.md`](V264.md).

---

## Summary ranking (ORIGINAL, pre-V255 — superseded above for option B)

| Rank | Option | Attacks the N wall? | Cost (dev-days) | Dead-end risk | One-line |
|---|---|---|---|---|---|
| **1** | **B. Cross-asset / carry strategies** | **Yes — new independent N per strategy** | 8–15 /strategy | MEDIUM | Diversification across mechanisms; funding-carry first. The real structural escape. |
| **2** | **C. On-chain flow as primary universe** | Yes — own independent N | 6–12 | MED-HIGH | Like B but more data-integrity landmines; consider folding into B. |
| **3** | **A. Shorter (30d) windows** | Partially — cheap but illusory | 2–4 | HIGH | Worth a 1-day `regime_label`-at-30d spike; promote only if the label holds. |
| **4** | **D. Polymarket** / **E. Specialist LLMs** | No (D shorter history; E signal-only) | 4–8 / 5–10 | HIGH / MED-HIGH | D doesn't help N; E is gated on N widening first. Park. |
| **5** | **F. News-driven regime** | No | 6–10 | MED-HIGH | Weakest N story + sharpest as-of hazard. Last. |

**The through-line:** only **B** (and partly **C**, and speculatively **A**) actually
manufacture new *independent* recent-regime windows — the single thing the V247 ruler
says is missing. **E and F add signal to a saturated composite judged at the N=4
noise floor**, so they can't clear the bar until N widens by some other means. If
Phase 3 has budget for exactly one bet, it is **funding-rate carry as an independent
strategy** — it's the cheapest path to "reliably profitable" via diversification
rather than the 4-year wait, and it dodges every refutation pattern R1–R4.

**Nothing here is a commitment.** This is the menu; the user picks the priorities and
the eventual V254+ that resumes the training loop (per [`V253.md`](V253.md) §"Resume
criteria") pins one of these — or waits for live-paper recent-N to reach ≥20.
