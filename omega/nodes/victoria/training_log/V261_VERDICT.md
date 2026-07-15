# V261 — On-chain flow-primary offline scorer — VERDICT

**Date:** 2026-07-15 · **Author:** claude (Opus 4.8) · **Type:** Phase-0 offline scorer verdict (no strategy code)
**Pre-reg:** [`V261.md`](V261.md) · **Data:** [`V257_VERDICT.md`](V257_VERDICT.md) (12 frozen CM community series)
**Code:** NEW `omega/nodes/on_chain_flow/` (parallel book). **NO** strategy/flag edit. No live-broker. No network. **$0.**

## Verdict: **REFUTED** — F2 (mechanism gate) fired decisively.

The pre-registered 4-signal on-chain flow-primary composite has **no dose-response edge** on BTC+ETH spot
daily bars. A stronger composite |z| is a coin-flip on trade outcome (MWU **p = 0.942**), the pooled median
PnL is statistically **indistinguishable from zero** (bootstrap CI95 spans zero), and every single component
alone is net-negative. This is a clean, evidence-backed refutation — not a data-absence pause. **The
on-chain-flow alpha lane closes.**

---

## 1 — Falsifier-by-falsifier

| Clause | Threshold | Measured (full 4-component composite) | Fired? |
|---|---|---|---|
| **F1** pooled median PnL ≤ $0 | > $0 required | median **+$11.74** (mean +$39.91) | no (nominally) |
| **F2** MWU p ≥ 0.05, winners vs losers by entry \|z\| | p < 0.05 required | **p = 0.942** — winners' median \|z\| 1.275 ≈ losers' 1.288 | **YES → REFUTED** |
| **F3** annualized gross < 5% | ≥ 5% required | **36.43%** gross | no |
| **F4** SplyExNtv whale proxy dominance (≥80% of lift / flips verdict) | proxy not dominant | LOO-whale median +$23.83 / 43.5% ann but **core still fails** (MWU p=0.62) — nothing carries a mechanism | no (moot) |

**F2 is the binding failure.** The other clauses are informative but do not rescue the result: F1's +$11.74
median has a bootstrap **CI95 of [−$45.69, +$62.69]** — it includes zero, so the "positive median" is not
significant. F3's 36% annualized gross is a **magnitude without a mechanism**: the strategy takes directional
risk that happens to net positive over this pooled sample, but the signal that selects entries carries no
predictive relationship to which trades win. Per the pre-registered mapping, **any single falsifier bars
ADOPT**, and F2 firing → REFUTED.

## 2 — Full-composite numbers (LOCKED params, deterministic)

- **Universe:** BTCUSDT, ETHUSDT · spot-index price proxy (`binance_futures/*/index_price.json`).
- **Composite days:** 2357 per asset (2020-06→2026-07 after the 30d warmup + price-coverage intersection).
- **Trades:** 334 total (BTC 171, ETH 163), non-overlapping 5-day holds, $10k notional, 5bps/side.

| Metric | Pooled | BTC | ETH |
|---|---|---|---|
| N trades | 334 | 171 | 163 |
| total PnL | +$13,328.57 | +$6,559.77 | +$6,768.80 |
| median PnL | +$11.74 | +$9.03 | +$28.69 |
| mean PnL | +$39.91 | +$38.36 | +$41.53 |
| p25 / p75 | −$415.06 / +$474.11 | −$323.00 / +$397.16 | −$499.76 / +$607.58 |
| win rate | 51.2% | 51.5% | 50.9% |
| profit factor | 1.14 | 1.17 | 1.12 |

- **Bootstrap CI95 on pooled median** (10k resamples, seed 20250715): **[−$45.69, +$62.69]** — includes zero.
- **Annualized gross:** 36.43% (mean gross return/hold 0.499% × 365/5).
- **MWU winners vs losers by entry \|z\|:** U=13872, z=−0.073, **p₂=0.942** (one-sided winners>losers p=0.529).
  Winners' median \|z\| **1.275** vs losers' **1.288** — the signal magnitude is if anything *lower* on winners.

**Determinism:** re-run into a scratch dir is **byte-identical** (`v261_scorer.json` + `v261_trades.csv`,
md5 `d9d68239…`). Pure-python stats, `math.fsum`, canonical sort, fixed-seed local `random.Random`.

## 3 — Ablation (SplyExNtv proxy honesty — F4)

Each single-component book and the leave-one-out-whale book, run through the identical windowing/fence:

| Book | N | median PnL | ann gross % | MWU p₂ | core_pass |
|---|---|---|---|---|---|
| netflow only (−1× FlowIn−FlowOut) | 500 | −$33.78 | −36.66% | 0.119 | ✗ |
| addr_velocity only (+1× ΔAdrActCnt) | 562 | −$1.72 | −4.19% | 0.701 | ✗ |
| whale_velocity only (−1× ΔSplyExNtv) | 483 | −$30.48 | −21.87% | 0.081 | ✗ |
| tx_velocity only (+1× ΔTxTfrCnt) | 563 | −$12.52 | −1.90% | 0.063 | ✗ |
| **leave-one-out whale** (3-signal) | 326 | +$23.83 | +43.50% | 0.618 | ✗ |

**F4 does not fire — and the reason is stronger than "proxy is fine": there is no mechanism for the proxy to
dominate.** Every single component is net-negative and none separates winners from losers (all MWU p > 0.06).
Removing the SplyExNtv proxy (LOO-whale) actually *raises* the nominal median/annualized, but its MWU p=0.62
still shows no dose-response — the 3-signal book fails the mechanism gate exactly like the 4-signal one. The
SplyExNtv proxy is **not** the thing that broke V261; the whole daily-bar flow composite lacks edge. The proxy
caveat is therefore not load-bearing on this verdict.

## 4 — Interpretation (why the pooled PnL is a mirage)

The pooled book nets +$13.3k gross-positive with a 36% annualized gross, which looks like alpha at a glance.
It is not, and the pre-registered MWU is exactly the instrument that catches it:

- A real signal shows **dose-response** — larger \|composite z\| → better expected outcome. V261's winners and
  losers have **statistically identical** entry \|z\| (1.275 vs 1.288, p=0.942). The composite tells you nothing
  about *which* of its own high-conviction entries will work.
- The positive pooled median (+$11.74) is **inside its own noise** (CI95 spans −$46→+$63). With WR 51.2% and
  PF 1.14 on 334 non-overlapping trades, the book is a marginally-better-than-coinflip directional taker whose
  positive expectancy is not tied to the flow signal — it is not separable from a zero-edge random-entry book
  over this span (BTC+ETH both trended up 2020→2026, so a slightly-long-biased taker nets positive regardless).
- Consistent with the R2 (below-resolution) / saturation pattern that killed the V241→V258 entry-side lane:
  **daily-bar entry-side information is exhausted.** On-chain flow at daily cadence is one more entry-side feed
  that carries no daily dose-response for BTC/ETH.

## 5 — Anti-Goodhart integrity

- Params were LOCKED in [`V261.md`](V261.md) and committed (`96d5d0e`) **before** the scorer ran. Signs,
  window (30d), entry bar (\|z\|≥1.0), hold (5d), sizing ($10k), fee (5bps/side), bootstrap seed — all
  pre-declared, none touched after seeing the result.
- **No post-hoc re-parameterization.** The temptation (relax \|z\|, flip a sign, extend the hold, drop the
  weak components until the MWU passes) is textbook Goodhart/HARKing and is exactly what the F2 clause exists
  to forbid. The refutation is recorded as measured.
- The signal SET is whatever V257 froze (4/4), run as pre-registered — not redesigned to fit the data.

## 6 — Scope / integrity ledger

- **DID:** add `omega/nodes/on_chain_flow/{__init__,loader,signals,sim,v261_scorer}.py`; run the $0 offline
  scorer over the V257 frozen series; write [`V261.md`](V261.md) pre-reg + this verdict; update
  [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) Track C.
- **Did NOT:** touch `strategy.py`, `signal_generation.py`, `victoria_node.py`, `funding_carry/*`, or any
  flag; touch the live-paper daemon; run any live-broker anything; hit the network. **$0.** Artifacts under
  `/Volumes/gamma-systems-2/omega-victoria-data/v261/` (gitignored).

## 7 — Consequence for the parallel-alpha lanes

Three independent offline alpha lanes have now reported:

| Lane | Verdict | Note |
|---|---|---|
| Spot Victoria (V235→V253 walk-forward) | standing baseline (selective universe) | daily-bar entry-side saturated |
| Funding-carry BTC/ETH (V255.C/.D) | **ADOPT** (real basis, KEEP-FLAG-GATED→ADOPT) | the one confirmed cross-mechanism alpha |
| **On-chain flow BTC/ETH (V261)** | **REFUTED** | no daily-bar dose-response; F2 p=0.942 |

Track C is spent: it was the last data-blocked offline lane, V257 unblocked it, and the pre-registered test
refuted it with evidence. **The offline alpha search is now fully reported** — funding-carry is the single
surviving confirmed lane. The remaining escape from the daily-bar entry-side wall is unchanged: **intraday
resolution** (a finer OHLCV/flow freeze reopening the composite the daily lanes exhausted) or **live-paper
accumulation** of independent recent windows (V253 soak). A paid-tier on-chain escalation (Glassnode/CryptoQuant
true whale cohorts + intraday flow) is only worth it *if* an intraday reopen shows edge first — V261 shows the
free daily community tier does not.

## 8 — Falsifier gate summary

| V261 falsifier | Result |
|---|---|
| F1 pooled median ≤ $0 | pass (median +$11.74) — but CI95 includes zero |
| **F2 MWU p ≥ 0.05** | **FIRED — p=0.942 → REFUTED** |
| F3 annualized gross < 5% | pass (36.43%) — magnitude without mechanism |
| F4 SplyExNtv proxy dominance | not fired (no mechanism to dominate; caveat not load-bearing) |

**VERDICT: REFUTED. On-chain flow-primary lane CLOSES with specific evidence (no daily-bar dose-response),
not data absence.**
