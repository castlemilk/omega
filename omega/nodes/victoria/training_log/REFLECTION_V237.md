# Reflection after V237 — composite-side interventions on recent are exhausted; only the new-data path remains

**Date:** 2026-07-04 · **Author:** claude (Fable 5)
**Trigger:** stagnation (trigger 1) — V235 / V236 / V237 are three consecutive
versions with no distributional-baseline improvement on any regime; V236 and
V237 were both refuted at $0 by their pre-grid separator proofs, and both
targeted the same objective (the recent distribution, honest mean −$516).
The Goodhart tripwire (trigger 0) does **not** fire in its original form —
these were distributional targets (n=10 windows), not a single snapshot
window — but its spirit is engaged below in §3/§5: two mechanism families
died at their separators against the same objective, so the *objective's
tractability with current data* is the question, not the next mechanism.

## 1. Eval stability

No new runs occurred in V236/V237 (that is the point of the separator rule),
so there is no fresh stability evidence to add. The standing basis is the
V235 walk-forward grid: 64 deterministic cells (all `DETERMINISM: PASS` from
committed state, the V214→V221 arc's guarantee), so within-cell noise is $0.00
by construction. The relevant uncertainty is now **across-window sampling
variance**, not eval noise.

## 2. Variance estimate

The acceptance unit since V235 is the distribution itself. For recent:
n=10, mean −$516, median −$1,571, p25 −$2,551, min −$5,356, max +$6,551.
The naive standard error of the mean is ≈ $1,200 (per-window sd ≈ $3,700 —
computed from the 10 recent cell PnLs). **Any future recent mean-Δ below
~$2,400 (2·SE) on a same-windows paired comparison is in sampling noise**
unless the paired per-window deltas themselves are consistent (which is why
the V237 bar was written as mean-Δ AND p25-Δ jointly). This threshold carries
forward to V238's re-baseline comparisons.

## 3. Subsystem audit (the last K hypotheses)

| V | Mechanism | Subsystem | Outcome |
|---|---|---|---|
| V235 | universe/hermetic walk-forward re-baseline | eval methodology | shipped (measurement, not alpha) |
| V236 | ER/VR chop throttle | state-conditional **sizing gate** on the OHLCV composite | refuted at $0 (separator: p=0.40/0.70, wrong direction) |
| V237 | BTC-factor OLS residualization | **factor construction** of the OHLCV composite | refuted at $0 (separator: p=0.567, wrong direction at 4/5 windows) |

Both V236 and V237 are *composite-side, OHLCV-native* interventions on the
recent book: one conditioned the size on a price-derived state variable, the
other rebuilt the cross-sectional neutralization from the same prices. Both
separators returned the same shape of answer: **recent's losses are not
concentrated along any price-derived conditioning axis tried so far** (ER, VR,
own-ticker ER, β-contamination at 5 windows, aggregated contamination). The
V236 analysis additionally showed the two profitable recent windows sit at
mid-pack ER; V237's showed they sit at *opposite ends* of the contamination
scale. The named dead end is therefore not one mechanism but the family:
**conditioning or re-constructing the momentum composite from OHLCV alone**.

The deeper diagnosis, consistent with DEEP_REVIEW_2026-07_FABLE_ALPHA: the
book's information set at daily bars is a single price stream per name; every
composite-side transform is a reprojection of the same information, and the
recent-era market (post-2023 alt regime) appears to price that information
out. New conditioning power requires **new information classes**, not new
projections.

## 4. Revert-and-branch option

Nothing to revert: V236 and V237 shipped zero code, and the standing main
(V227-skew config) IS the distributional baseline holder on all three regimes
(trend +$1,941 / crisis +$819 / recent −$516). The branch decision is purely
forward: the queue's V238 (feed build) is the only remaining item that changes
the information set rather than reprojecting it.

## 5. Untouched dimensions

Explicitly enumerated; starred = reachable by V238's frozen-series feed:

- **Funding-rate history*** — the live `FundingRateSignal` has never run in a
  frozen eval (no historical series). Carry/crowding is the canonical
  crypto-native non-price signal.
- **Open interest + taker-flow imbalance*** — positioning/flow, never
  evaluated (binance.vision `metrics` daily files confirmed reachable).
- **Macro regime series (FRED) + Fear&Greed + DVOL*** — the info signals
  built in V186-era code that are inert for lack of frozen history.
- **Universe/blacklist flip (V239)** — the effective 4-name universe was a
  silent decision (V235 finding); never measured as a strategy variable on
  the honest distribution.
- **Portfolio-level tail cap (V240 candidate)** — corr-spike new-entry
  throttle; the only mechanism class matching the correlated-grind-down
  failure mode; offline PCA/copula calibration is $0 and may run anytime.
- **Section-4 conditional-expectancy surface** (DEEP_REVIEW §2) — LOWO-validated
  multi-variable surface instead of single-variable thresholds; the V236 mid-VR
  anomaly is parked there.
- **Exit-side mechanics** — every recent-targeted bet so far has been
  entry-side (selection/sizing/construction). MAE/MFE columns exist in every
  trades CSV and have never been mined distributionally.
- **Not worth further effort without new data:** any additional OHLCV-derived
  entry conditioner (ER, VR, β, vol-rank, drawdown variants) — three
  separators' worth of evidence says the axis family is dry.

Per the skill rule: V238's hypothesis comes from this list (top three items —
it activates the starred rows wholesale).

## 6. Observability-gap audit

*What instrumentation would have caught this sooner?* The separator rule IS
the instrument — V236+V237 together cost ~$0 and two sessions where the
pre-V234 loop would have burned ~12h of grid per bet. The gaps are now on the
analysis side:

1. **Separator harness dedup (S, ship with V238):** V236 and V237 each
   re-derived the same 140-trade extraction + entry-bar mapping + MW/bootstrap
   scaffolding inline. Commit a small `omega/tools/forensics/separator_lab.py`
   (load pooled walk-forward trades + snapshots, provide `mann_whitney`,
   `terciles`, `bootstrap_ci`) so the next separator is a 20-line conditioning
   function, not a rewrite. Also removes transcription-error risk in the
   stats.
2. **Per-trade conditioning dump (S, ship with V238):** persist the per-trade
   table (window, symbol, entry bar, PnL + every conditioning variable
   computed to date: ER20, VR, β60, C60) as a committed CSV artifact next to
   the analysis docs, so future separators and the Section-4 surface reuse
   identical rows instead of regenerating them.
3. **Feed-freshness probe for V238 (M, queue):** the feed build introduces a
   new failure class — silent staleness/gaps in frozen non-price series. A
   freeze-time validator (bar-count + gap report per series per window)
   should gate snapshot acceptance. → OBSERVABILITY-BACKLOG.md.
4. **Entry/exit attribution split (M, queue):** MAE/MFE-based decomposition of
   per-trade PnL into entry-timing vs exit-timing loss, to direct the first
   exit-side bet if V238's information classes don't move recent.
   → OBSERVABILITY-BACKLOG.md.

*Next blind spot:* V238 re-baselines the whole grid with new signals active —
if any new signal is accidentally non-deterministic or wall-clock-coupled, the
V214→V221 hermetic guarantee breaks silently. The existing
`check_determinism.sh` + startup wiring banner must run on the first V238
smoke cell **before** the 32-window grid (standard rule, restated here because
the feed build is the first information-set change since the arc closed).

## Conclusion

Composite-side residualization/conditioning on OHLCV is exhausted for recent
(three separator refutations, two mechanism families, zero dollars burned).
The only path that adds conditioning power is new information: **V238
(frozen-series feed build) promotes**, with V239 (universe flip) on its
re-baseline and the tail cap as V240 candidate. Recent's posture question —
whether a daily-bar momentum book can be positive in the post-2023 alt regime
at all — stays open until the new information classes have been measured.
