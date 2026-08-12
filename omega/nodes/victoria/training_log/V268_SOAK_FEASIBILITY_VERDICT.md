# V268 — Scaled funding-carry live-paper soak: VERDICT = **STOP (0/2)**

**Date:** 2026-08-12 · **Pre-registration:** [`V268.md`](V268.md) (committed
`fa7660f`, before any lane activation) · **Scorer:**
[`scripts/v268_soak_feasibility.py`](../../../../scripts/v268_soak_feasibility.py) ·
**Artifact:** `data/v268_soak_feasibility.json` (gitignored) ·
**Determinism:** byte-identical re-run **PASS** (md5 `b007c672…`) ·
**Refutation codes:** **R3** (calendar-bound N) + **R5** (structural payload)

**No lane was activated. Daemon PID 10329 untouched. No strategy code, no flag,
no trade, no funds.**

---

## 0. Headline

**The soak cannot buy what V267 needs, and the "scaled" half of it measures
nothing at all.**

The blocking quantity — high-ADV-tercile funding-carry trades in the `recent`
regime — accrues at **7–22 trades per year**, and V267's G3 CI needs **138 more
of them**. Best case that is **6.4 years**; on the most recent 12 months of
evidence it is **19.4 years**. And scaling the paper book to V267's
capacity-relevant size changes annualised Sharpe by **exactly 0.000e+00**,
because the harness has no impact model — so a "capacity-relevant" paper soak
would produce a number labelled capacity-relevant that carries zero capacity
information.

| Gate | Statistic | Bar | Result | Outcome |
|---|---|---:|---:|---|
| **F1** | best-case years to CI width < 1.0 | ≤ 3.0 yr | **6.36 yr** | **FAIL → R3** |
| **F2** | max \|Sharpe(k) − Sharpe(1)\|, k ∈ {1…1000} | > 0.01 | **0.000e+00** | **FAIL → R5** |
| | | | | **STOP (0/2)** |

Verdict computed mechanically from the gate booleans by the scorer. No bar was
moved after seeing a result.

---

## 1. F1 — the calendar cannot supply the quantity (**FAIL, R3**)

ADV join **100%** (1225/1225), tercile cut identical to V267's
(high tercile = entry-date ADV > **$288M**; n = 408, reproducing V267's 409 to
one boundary trade).

**Requirement.** Sharpe CI width scales ≈ 1/√n. V267 G3: width
**1.794** at **n = 62**. For width < **1.0**:

```
n_req = 62 × (1.794 / 1.0)² = 200   →   138 additional high-tercile recent trades
```

**Supply.** Empirical arrival rate of high-tercile funding-carry trades:

| era | high-tercile trades | all trades | rate | years to reach n=200 |
|---|---:|---:|---:|---:|
| last 36m | 64 | 301 | **21.6 / yr** | **6.36** |
| last 24m | 24 | 151 | **12.2 / yr** | **11.31** |
| last 12m | **7** | 77 | **7.1 / yr** | **19.38** |

**Even the most generous window misses the 3-year bar by more than 2×, and the
trend is the wrong way** — the rate has fallen by 3× over three years. Loosening
the bar does not rescue it: CI < 1.2 is **6.3–10.8 yr**, and even CI < 1.5 —
which would still not adjudicate the 1.0 Sharpe bar — is **2.2–3.8 yr**.

**Why the rate is collapsing.** Funding-carry fires on |funding| extremes, and
funding has compressed in the liquid names — exactly the names V267 G3 proved
carry the edge. Pooled trade rate fell **0.535/day (lifetime) → 0.214/day
(last 12m)**; in the high tercile it is **0.019/day**. Per-symbol over the last
24 months: **BTC 1 trade, ETH 4** — the two largest books have all but stopped
producing signals, while DOT (24), AVAX (20) and NEAR (17) dominate, and those
sit in the *low* tercile whose edge V267 measured at **1.05 bps with a CI that
includes zero**.

This is the V249 calendar wall (**R3**), but sharper than the campaign assumed:
the phase-transition doctrine budgeted ~1 independent window per quarter, which
is true of *calendar windows* — it is **not** true of the capacity-conditioned
trade count, which is ~30× scarcer. The V267 finding that "capacity is not the
binding constraint" is correct and unchanged; what this adds is that
**conditioning on tradeable liquidity makes the recent-N wall dramatically
worse, not merely equal.**

## 2. F2 — "scaled" is an empty adjective (**FAIL, R5**)

| k | median notional / trade | annualised Sharpe | Δ vs k=1 |
|---:|---:|---:|---:|
| 1 | $3,267 | 2.2072390097 | — |
| 10 | $32,667 | 2.2072390097 | 0.00e+00 |
| 100 | $326,667 | 2.2072390097 | 0.00e+00 |
| **315.9** (V267 k_max) | **$1,032,268** | **2.2072390097** | **0.00e+00** |
| 1000 | $3,266,670 | 2.2072390097 | 0.00e+00 |

Not "approximately invariant" — **bit-identical at every k**. (The k=1 value
also reproduces V267 G2's 2.20723900965707 exactly, which cross-validates that
this scorer's calendar-day book grid matches the one G3 was scored on.)

**The mechanism is structural, not incidental.** V267 §1 declared the
fitted-impact lane **R4**: there is no orderbook depth on disk and no fill above
the $10k cap, so no impact coefficient is estimable. With no impact model, the
harness's cost is purely proportional (flat 5 bps/side), so per-trade PnL is
exactly linear in notional and **every ratio statistic — Sharpe, its CI, the
edge in bps — cancels k identically.** The quantity V268 exists to narrow is a
Sharpe CI. It is invariant to the one knob V268 proposed to turn.

**The only nonlinearity available is an artifact.** The paper book holds
$100,000 of equity (`LivePaperConfig.initial_capital`). Peak concurrent gross
funding-carry book at k=1 is **$259,599 — already 2.6× the paper equity**. At
V267's k_max it is **$82.0M, or 820× paper equity**. Honouring "capacity-relevant
size" would therefore require scaling the paper capital by the same factor,
which cancels again — or leaving it, which produces a margin/liquidation
artifact that measures the capital constraint, not the market. Neither is a
capacity measurement.

Per the operator brief's own anti-Goodhart clause — *"do not fudge sim fidelity
to fake capacity"* — this leg is reported as **R5 (structural payload)** and not
attempted.

## 3. What is NOT refuted

Stated explicitly so this verdict is not over-read:

1. **Funding-carry's alpha is untouched.** V255.C/D remain the campaign's one
   confirmed alpha; V267's capacity verdict (2/3, ~$154M book, 11.8 bps
   slippage headroom, edge concentrated in the liquid tercile) stands.
2. **G3 is still R2, not negative.** Sharpe 0.762 [−0.601, +1.193] means
   *unadjudicable*, and this verdict adds only that it will remain so for years.
   "Cannot be measured" ≠ "is not there."
3. **A live-paper funding-carry lane is not worthless** — it is worthless *for
   the stated objective*. See §5.
4. **The standing baseline has not moved** (crisis +$599 / trend +$2,997 /
   recent +$30). This version wrote no strategy code and could not move it.

## 4. Campaign-level consequence

The V241–V258 retrospective named **R2 (below-resolution)** as the dominant dead
end and **R3 (calendar-bound N)** as its meta-cause. V268 is the first version to
measure R3's magnitude on the *surviving* lane rather than infer it, and the
number is worse than the doctrine assumed: **6.4–19.4 years**, against a resume
gate the campaign had been treating as quarters.

**The honest reading: offline alpha search closed at V261; with V268, the
"wait for the calendar" path closes too — for this objective.** What remains is
not another mechanism and not more patience. It is a **data-acquisition
decision**, which is the user's call, not the loop's.

## 5. Options, with the case for each (user's call — no default taken)

**(a) Activate the lane anyway, re-scoped as OOS validation, at k=1.**
Drop the G3-adjudication objective and the "scaled" adjective, both refuted
above. What remains is genuinely valuable and cheap: the first *out-of-sample*
observation of the campaign's only confirmed alpha — does live funding-carry
reproduce the frozen ledger's regime mix, funding distribution and per-trade
edge at all? That is a **reconciliation** question (V251-class), answerable in
months, not a CI question. It needs a new pre-registration with different gates;
it must not inherit V268's.

**(b) Buy orderbook depth history for the 13 names.** V267 §8's option (b), and
the only purchase that unblocks the R4 impact lane. Note it does **not** fix F1
— depth data adjudicates *capacity*, which V267 already answered favourably; it
would not narrow the recent CI.

**(c) Accept the standing baseline and stop spending on this question.**
Defensible: capacity is answered, the alpha is confirmed, and the one open leg
is unadjudicable on any timescale that matters. The campaign has a shippable
deliverable and no obligation to keep buying resolution it cannot afford.

**Not recommended: a V268-2 that loosens the CI bar.** CI < 1.5 is still
2.2–3.8 years *and* would not clear the 1.0 Sharpe bar it exists to test —
mining a CI that spans the bar is the exact R1 pattern that kept V266-2 and
V267-2 out of the queue.

---

**HEAD SHA at verdict:** see the commit that adds this file
**Pre-registration SHA:** `fa7660f` (committed before any lane activation)
**Lane activation:** **NONE** — no lane was activated; daemon PID 10329 was not
restarted, reconfigured, or touched.
