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

| Rank (updated V256) | Option | Status | Next |
|---|---|---|---|
| **1-provisional (structural)** | B. level/regime basis carry (v1) | **VALIDATED, FLAG-GATED (V255.C)** — needs basis data | **V255.D**: acquire real perp/spot basis series + live re-verify (live-host) |
| **1 (structural, buildable-offline now)** | C. On-chain flow primary universe | **UNBLOCKED (V257 executed 2026-07-15)** — 4/4 signals frozen per-asset {BTC,ETH}, 6.5yr daily, byte-identical | **rerun V256 as pre-registered**: flow-primary offline scorer + walk-forward over `data/frozen_series/on_chain/` (follow-on V###) |
| **1 (buildable-offline now)** | E. Specialist-LLM ensemble | untested | **next offline bet** — reuses V241 infra, prompt-only, cheapest; but N=4-pinned |
| 2 (buildable-offline now) | D. Polymarket sentiment/regime | untested | after E — plumbing exists, but thin ~2023+ history; N=4-pinned |
| **—** | B.dead — v2 directional carry | **REFUTED (V255)** | closed |
| 4 | A. Shorter (30d) windows | untested | `regime_label`-at-30d spike |
| 5 | F. News-driven regime | untested | last |

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
