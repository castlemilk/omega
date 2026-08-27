# V285 — Data-source audit: the best "new" source is one already on disk

**Date:** 2026-08-27
**Author:** claude
**Status:** AUDIT / SCOPING — read-only, nothing implemented, no version pre-registered
**Companion to:** [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) (the 2026-07 external-source menu)
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §1 — Most external sources are already tried and refuted

V254 ranked the external options in July. Every high-priority one has since been run:

| V254 option | Priority | What happened |
|---|---|---|
| **B — funding-rate carry** | **1** | V255.C ADOPT retrospectively → **V272 REFUTED live-deployability**: residue 1.3–1.5 bps sits *below* V270's measured ~1.86 bps spread cost |
| **C — on-chain flow primary** | 2 | V256 Phase-0 data audit, V257 pipeline, **V261 refuted** |
| **A — shorter windows** | 3 | resamples the same 6 years at finer grain; never promoted |
| **D — Polymarket** | 4 | **V259 PAUSED** — no frozen crypto-binary probability series exists |
| **F — LLM specialists** | — | **V258 REFUTED at Phase 0**; V260's news→regime classifier degenerate |

So the honest starting point is that the external menu is largely exhausted, and
proposing a *new* external feed means re-entering a space with five refutations in it.

## §2 — What is already frozen, and what consumes it

| Frozen source | Size | Consumed by |
|---|---:|---|
| **`binance_bookticker`** | **46 MB / 71 files** | **`scripts/v269_qc_report.py`, `scripts/v270_spread_budget.py` — analysis only. No signal, no strategy, no node.** |
| `binance_intraday` (1h) | 14 MB / 920 files | `omega/nodes/intraday_alpha/loader.py`, V262 scripts |
| `binance_futures` | 1.3 MB | `on_chain_flow/loader.py`, `funding_carry/basis_data.py` |
| `on_chain` | 892 KB | `on_chain_flow/loader.py`, `intraday_alpha/sim.py` |
| `binance_funding_*.json` | — | `funding_carry` |

**The largest frozen dataset in the repo has no trading consumer.** 46 MB of
top-of-book data, acquired by V269, is read by two report scripts and nothing else —
and V279 separately established that the entire `microstructure` signal family is
**0/5 live**, so nothing was going to consume it as signal either.

## §3 — Why that matters more than any new feed

Bookticker's natural consumer is **not signal — it is execution**. V270 already used
exactly this data to measure the 4-fill spread cost at **~1.86 bps**, and V272 then
showed the one confirmed alpha dies against that number by **0.3–0.5 bps**.

That is the narrowest, best-quantified gap on the board, and the data needed to attack
it is already frozen, already manifest-able, and already paid for:

- **no acquisition cost, no vendor, no API key, no ongoing fee**
- **no new lookahead surface** — it is frozen historical data under the same
  substrate discipline as everything else (and V282 just hardened that discipline)
- **it attacks the one axis nothing has attacked** — every refutation above is
  entry-side or signal-side; execution cost has never been optimised, only *measured*

Against the V254 dead-end patterns: an execution-cost improvement is not R1 (the effect
is measured and non-zero — 1.86 bps of real cost), not R2 (it is well above the
resolution that killed the entry-side work), and not R3 (it does not depend on
recent-window N at all, because execution cost is measurable per-fill rather than
per-window).

## §4 — Second-best: the 1h corpus, for a horizon reason

`binance_intraday` (920 shards, 2020→2026) is consumed by `intraday_alpha`, whose V262-2
composite was refuted at F1/F2/F3. But today's V285 IC sweep found something adjacent:
**every signal's |IC| rises monotonically with horizon** (`sma_crossover` +0.009 at H=1 →
+0.110 at H=20). Daily bars may simply be the wrong resolution for the *holding period*
the strategy actually realises.

That is a hypothesis about resolution, not about a new feed, and the data to test it is
already frozen. Lower priority than §3 because V262 already explored this space and the
refutation was not about resolution per se.

## §5 — Recommendation

**Do not integrate a new external data source.** Five refutations say that space is
picked over, and a sixth would cost acquisition, wiring, a lookahead audit and a grid.

**Use `binance_bookticker` for execution-cost work instead.** It is the only large,
frozen, un-consumed dataset in the repo; its natural application is the one unexplored
axis; and V270 has already demonstrated the read path. The concrete first step is not a
strategy change but a measurement: **what does the realised spread cost look like per
fill, and how much of the ~1.86 bps is addressable by order placement** (posting rather
than crossing, venue choice, hold-length) — which is exactly the number V272's refutation
turns on.

If that measurement shows a meaningful addressable share, *then* an execution mechanism
is worth pre-registering — with V284 as the cautionary precedent that a live, correct
mechanism can still fail to pay.
