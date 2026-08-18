# V271 — Funding-carry live-paper lane (k=1 OOS reconciliation): VERDICT = **R5 STOP (0/2)**

**Date:** 2026-08-18 · **Pre-registration:** [`V271.md`](V271.md) (committed
`6f93202`, before any lane activation) · **Scorer:**
[`scripts/v271_lane_feasibility.py`](../../../../scripts/v271_lane_feasibility.py) ·
**Artifact:** `data/v271_lane_feasibility.json` (gitignored) ·
**Determinism:** byte-identical re-run **PASS** (md5 `0122fb1d…`) ·
**Refutation code:** **R5** (structural payload)

**No lane was activated. Daemon PID 13829 untouched and not restarted. Depth
collector PID 76450 untouched. No strategy code, no flag, no trade, no funds.**

---

## 0. Headline

**The confirmed alpha cannot be run forward, because its entry rule reads the
future.**

V255.C/D's entry filter excludes the `near_zero` funding regime. That regime
label is produced by `FundingRegimeClassifier.classify_span`, which standardizes
the market funding index **over the full span** — every date's label depends on
the mean and standard deviation of the *entire* series, including dates after
it. On a live date *t* that quantity does not exist. Recomputed causally, the
label changes the **trade / no-trade** decision on **21.5%** of dates, against a
pre-registered bar of 5%.

The filter is not cosmetic: it gates out **53.5%** of all level-passing
candidate entries. It is load-bearing, and it is not online-computable.

| Gate | Statistic | Bar | Result | Outcome |
|---|---|---:|---:|---|
| **F0a** | dates where a causal regime label flips trade/no-trade | ≤ 5.0% | **21.5%** | **FAIL → R5** |
| **F0b** | additive multi-lane seam in the V253 harness | exists | **absent** (single `cycle_fn`, 0 lane tokens) | **FAIL → R5** |
| | | | | **STOP (0/2)** |

Verdict computed mechanically from the gate booleans by the scorer. No bar was
moved after seeing a result.

---

## 1. F0a — the entry rule is not online-computable (**FAIL, R5**)

Span 2020-01-01 → 2026-05-29, 2,341 days, 13 symbols.

**The filter is load-bearing.** Of 12,733 candidate symbol-days passing the
level threshold (`|funding| >= 1e-4`), the regime filter gates out **6,812 =
53.5%**. Candidate regime mix: `near_zero` 6,812 · `high_vol` 2,163 ·
`positive_carry` 1,883 · `negative_carry` 1,875.

**The filter's input is not causal.** Recomputing each date's label with an
expanding window (data up to and including *t* only) and comparing to the
frozen full-span label, over the 2,311 comparable dates:

| | count | rate |
|---|---:|---:|
| label flips (any) | 560 | **24.2%** |
| **flips that cross the trade/no-trade boundary** | **498** | **21.5%** |

Dominant transitions: `near_zero → negative_carry` **346**,
`positive_carry → near_zero` **118**, and `high_vol →` {`near_zero` 34,
`positive_carry` 31, `negative_carry` 31}.

**Why this is fatal to V271 specifically, not merely inconvenient.** There are
only two ways to put this rule on a live wire, and both destroy the version's
own premise:

1. **Make the classifier causal** (trailing standardization instead of
   full-span). That is an edit to `omega/nodes/funding_carry/regime.py` — the
   exact modification the operator brief's anti-Goodhart clause pre-excludes.
   Worse, it is *circular*: it changes the entry decision on 21.5% of dates, so
   the live lane would no longer be running the rule whose ledger G2 reconciles
   against. You would be testing OOS reproduction of a strategy you just
   replaced.
2. **Freeze the full-span constants** from the 2020–2026 era and apply them
   forward. Also a strategy change (a new, untested parameterization), and the
   labels drift further from the frozen definition every day the live span
   extends past the freeze.

**Scope note — this is not a V255.C quirk.** The non-causal filter is shared by
the whole basis-hedged family: `basis_hedge.py` (V255.B) line 105 and
`hold_scaled.py` (V255.C/D) line 105 both consume `date_regimes`. The only
funding-carry variant without it is `strategy.py`'s v2 directional rule — which
V255 Phase 0 **refuted**. There is no online-safe variant of the confirmed
alpha to activate.

**Honest scoping of the finding.** `regime.py`'s own docstring says full-span
standardization "is never fed to the trading signal (which uses only trailing
per-symbol z-scores)." That statement is **true of `strategy.py`** (the v2
directional rule, which has no regime filter) and **false of the V255.B/C/D
basis-hedged rule**, which added the `excluded_regimes` gate. The docstring was
not updated when the filter was introduced. **This does not invalidate the
V255.C/D ADOPT verdict** — those are retrospective scorers over a fully
observed span, where a descriptive full-span classification is a legitimate
window-labelling device. It invalidates only the assumption that the rule as
written can be run forward.

## 2. F0b — the V253 harness has no lane (**FAIL, R5**)

`LivePaperRunner.__init__` takes **one** `cycle_fn`:
`(scheduler, checkpoint, cycle_fn, initial_capital, pnl_log_path, install_signals)`.
The token "lane" appears **0 times** in `omega/live_paper/runner.py`. One
runner ⇒ one cycle function ⇒ one checkpoint ⇒ one strictly-monotonic PnL curve.

**Correction to the operating picture:** the brief's "do not touch its other
lanes" describes an architecture that does not exist. The daemon runs a *single*
forward cycle (`make_forward_cycle` — live V250 feeds → signals → StrategyNode →
PaperTradingEngine, the V240-selective spot composite). There are no other
lanes to preserve, and no seam to hot-add one into. A funding-carry lane would
require new runner-layer composition (multi-cycle-fn fan-out, per-lane
checkpoint namespacing, per-lane PnL curves) plus a **new** online forward
driver — `simulate_symbol_scaled` is a batch enumerator that `break`s whenever
the 7-day exit lies beyond the data end, which is *every* live entry.

F0b alone is buildable work, not a refutation. It is scored FAIL because it
falsifies "additive hot-add," and because combined with F0a the build would be
in service of a rule that cannot be run forward anyway.

## 3. Bonus finding — G2 as pre-registered is near-vacuous at any feasible N

Not a gate; surfaced because it would have bitten at the far end of an 18-month
lane. Frozen V255.C ledger: **1,225 trades**, median net **$1.5646**,
distribution-free CI95 **[$0.868, $2.295]**, half-width **$0.713**.

Arrival rate: **77.1 trades/yr** (last 12m) · 75.6 (24m) · 101.7 (36m). The
precommitted **N = 100** is therefore **1.30 years** — the horizon is sound.

But CI half-width scales as 1/√n: at N=100 it is **$2.50**. G2 asks whether the
live CI *overlaps* [$1.13, $2.80]. A live median anywhere in roughly
**[−$1.37, +$5.30]** would overlap. That interval comfortably contains $0 and
both signs of any plausible effect, so **G2 would pass on essentially any
outcome, including a lane with no edge at all.** Had the lane run, it would have
returned a PASS carrying almost no information — the R1 pattern (a bar that the
data cannot fail). If this question is revisited, G2 needs a directional or
equivalence-test formulation, not an overlap test.

## 4. What is NOT refuted

Stated explicitly so this verdict is not over-read:

1. **Funding-carry's alpha is untouched.** V255.C/D remain the campaign's one
   confirmed alpha (median +$1.56 full-universe, +$1.95 with real basis).
   Nothing here re-scores it.
2. **V267 and V270 stand.** Capacity is not binding (V267, 2/3); the realized
   half-spread is 0.4650 bps against a 1.6475 bps budget (V270). Unaffected.
3. **The frozen backtest is unaffected.** No strategy code, no flag, no data.
4. **The standing baseline has not moved** (crisis +$599 / trend +$2,997 /
   recent +$30). This version wrote no strategy code and could not move it.
5. **"Cannot be run forward as written" ≠ "has no forward edge."** The rule may
   well work causally. That is an untested, separate question.

## 5. Campaign-level consequence

V268 closed the "wait for the calendar" path for the G3 objective. V271 closes
V268's own option (a) — the OOS reconciliation fallback — for a different and
more basic reason: **the confirmed alpha was only ever specified retrospectively.**
Its entry rule is a scorer's rule, not a trader's rule.

That is a genuinely new item on the campaign's dead-end map. R2
(below-resolution) and R3 (calendar-bound N) are about not having enough data.
This is **R5**: the artifact itself is not shaped for the question. The one
confirmed alpha has never been expressed in a form that could be run forward at
all, and no prior version noticed because every version that touched it was a
retrospective scorer.

## 6. Options (user's call — no default taken)

**(a) Pre-register V272 = "causal funding-carry re-specification."** Build a
trailing-standardized regime classifier, re-score V255.C/D on the frozen ledger
under the causal rule, and check whether the ADOPT verdict survives the 21.5%
decision change. This is the honest prerequisite to any live lane and is a
pure offline scorer ($0, no host, no calendar). **Recommended if the lane is
still wanted** — it is the cheapest way to learn whether there is anything to
activate. Note it is a real risk: the alpha may not survive causal labelling.

**(b) Drop the regime filter entirely and re-score.** Simpler than (a) and
trivially causal, but it re-admits the 53.5% of `near_zero` candidates the rule
was built to exclude. Cheap to run alongside (a) as a second cell.

**(c) Build the multi-lane harness seam anyway.** Runner-layer only, useful for
any future lane, independent of (a)/(b). Defensible as infrastructure but
activates nothing on its own.

**(d) Accept the standing baseline and stop.** Capacity is answered, execution
cost is confirmed, and the alpha is confirmed *retrospectively*. The campaign
has a shippable deliverable.

**Not recommended: activating a lane with a hand-patched regime rule.** It
would produce OOS-looking numbers for a strategy that is not the one in the
ledger, which is worse than no measurement.

---

**HEAD SHA at verdict:** see the commit that adds this file
**Pre-registration SHA:** `6f93202` (committed before any Phase-0 gate was scored)
**Lane activation:** **NONE**
**Daemon restart:** **NONE** — `com.omega.live_paper` PID **13829** ran
uninterrupted (last tick 2026-08-18T02:55:00.144Z, drift 0.144s, equity
$98,439.41, 5 open positions). `com.omega.depth_collector` PID **76450**
untouched.
**G-MEAS precommitted N:** 100 closed funding-carry trades or 18 months,
whichever first — **not started** (no lane).
