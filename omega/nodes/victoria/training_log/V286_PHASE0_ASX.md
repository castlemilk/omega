# V286 Phase 0 — ASX on delayed data: the signal inverts, and that is the finding

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — read-only, nothing built, no version pre-registered, no strategy module imported
**Prompted by:** operator question — "build a model that can trade the ASX off delayed data?"
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §1 — Delayed data is not the blocker

ASX delayed feeds run ~20 minutes behind. Victoria trades **daily bars with multi-day
holds**, and §4 below points to *months*, not days. At those horizons a 20-minute lag is
irrelevant — it only bites on execution-sensitive or intraday strategies.

The real obstacles are elsewhere, and they are not the ones the question implies:

| Obstacle | Severity |
|---|---|
| **Costs** — ASX retail is ~0.1%/side or ~$5–10 flat ⇒ **~20 bps round trip** | **Severe.** V272 killed the campaign's one confirmed alpha because a 1.3–1.5 bps residue sat under **1.86 bps** of crypto friction. ASX friction is ~10× that. |
| **Shorting** — the composite is cross-sectionally demeaned, which *guarantees* balanced longs and shorts | **Structural.** Retail ASX shorting is hard/expensive, so half the strategy may be unavailable as designed. |
| Market hours, open/close auctions, corporate actions | Moderate — the codebase assumes continuous 24/7 bars. |
| Survivorship bias in any quick universe | See §5; it is the main threat to §3's result. |

What transfers cleanly is the **harness** — walk-forward, frozen substrate, determinism
gates, standing-baseline discipline are all asset-class agnostic — and `CLAUDE.md`'s
platform/project split means an `omega/nodes/asx/` project node is the architecturally
correct shape.

## §2 — Victoria's one working signal does NOT transfer

V285 established `sma_crossover` (5/20, ×10) as the campaign's entire signal edge:
**+0.0283** in-sample, **+0.0399** OOS on crypto. On ASX, same implementation, 20 liquid
names, 5 years, H=5:

| | IC |
|---|---:|
| all data | **−0.0226** (p=3.7e-04) |
| first half | −0.0466 |
| second half (held out) | **+0.0004** (p=0.97) |

Negative in one half, indistinguishable from zero in the other. Implied edge ≈ **0.1 bps**
against ~20 bps costs. **A direct port of the crypto model to the ASX is dead on
arrival** — not because of delayed data, but because the signal carries no transferable
information at that timescale.

## §3 — At equity timescales it inverts, consistently

The H=5 test used *crypto's* holding period, which is unfair to equities: classic equity
momentum is a 3–12 month effect. Sweeping signal timescale × forward horizon, 20 names,
**10 years**, IC_all / IC_OOS with implied OOS edge:

| MA pair | H=5 | H=20 | H=60 | H=120 |
|---|---|---|---|---|
| 5/20 | −0.0117 / −0.0171 (6bp) | −0.0214 / −0.0326 (23bp) | −0.0496 / **−0.0731** (91bp) | −0.0411 / −0.0444 (78bp) |
| 20/60 | −0.0237 / −0.0391 (14bp) | −0.0668 / **−0.0871** (63bp) | −0.0882 / −0.0622 (78bp) | −0.0571 / −0.0623 (**109bp**) |
| 50/200 | −0.0235 / −0.0212 (8bp) | −0.0575 / −0.0512 (37bp) | −0.0711 / −0.0610 (76bp) | −0.0794 / −0.0436 (76bp) |

**Every one of the twelve cells is negative, in-sample and out-of-sample.** On ASX large
caps, MA-crossover *mean-reverts*: a high short-vs-long MA predicts **lower** forward
returns. That is the opposite sign to crypto, and it is not a marginal effect —
|IC| reaches 0.087 OOS, more than double `sma_crossover`'s +0.0399 on crypto.

**Why this is stronger evidence than V285 §3's refuted sign-flip.** There, the inversion
hypothesis died because signs fitted on the train half *disagreed* with the test half.
Here the sign is stable in **all twelve cells across both halves** — it is not being
fitted, it is simply what the data does at every parameterisation tried.

Implied OOS edges of 63–109 bps at H=60–120 sit **3–5× above** the ~20 bps round-trip
cost, and a 1–6 month hold amortises that cost over very few trades per year.

## §4 — Consequence for the original question

The answer to "can we trade the ASX off delayed data" is **yes on the data question and
no on the model question**: delayed data is a non-issue at these horizons, but the model
that would trade it is *not* Victoria. It would be a **longer-horizon, reversion-signed
equity strategy** — a different mechanism, in a different asset class, sharing only the
harness.

## §5 — What must be true before any of §3 is believed

**Survivorship bias is the specific threat to this specific result, and it is not a
footnote.** The universe is today's ASX large caps over ten years. For a *reversion*
finding this is exactly the wrong bias: names that fell and kept falling were delisted
and are absent, while names that fell and recovered are over-represented. A reversion
signal is precisely what that selection manufactures. **§3 could be entirely an artifact
of the universe construction.**

Also outstanding:

1. **20 names is cross-sectionally tiny**, and they are heavily correlated (four banks,
   three miners). The strategy demeans cross-sectionally, which with 20 correlated names
   is a very different operation than with a broad universe.
2. **IC is not PnL.** This session alone: V283 measured TimesFM as a genuinely better
   volatility forecaster with no consumer; V284 built the consumer and it lost money.
3. **No portfolio construction, no cost model, no borrow model, no auction handling.**
4. **One regime.** Ten years spans post-GFC bull, COVID, and the 2022 selloff — a
   reversion effect could be a property of that specific path.

## §6 — Recommendation

**Do not build yet. Re-run §3 on a survivorship-free universe first.** That single test
decides whether this is a real effect or a selection artifact, it needs no strategy code,
and it is the cheapest possible way to be wrong. Delisted-inclusive ASX constituent
history is the one input that has to be acquired.

If it survives that, the next step is still a *measurement* — a portfolio backtest with
realistic ASX costs, long-only and long/short variants — not a mechanism. V284 is the
standing precedent that a live, correct mechanism can still fail to pay, and V285 is the
precedent that an encouraging in-sample table can vanish under a proper split.

**If it does not survive, that is a cheap and complete answer**, and the ASX question
closes for the price of one data acquisition rather than a project node.
