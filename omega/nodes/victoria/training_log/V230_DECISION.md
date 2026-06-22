# V230_DECISION — synthesis sprint (reflection action after V229)

**Date:** 2026-06-22
**Type:** research/synthesis V### — NO determinism grid, NO flag flips, NO `strategy.py` changes.
**Parent:** V229 (`a4c4533`) — IC retired for crisis (5th refutation); banked drawdown-gated-IC trend-only overlay (+$1,428 hermetic, un-promotable).
**Trigger:** `REFLECTION_V229.md` — subsystem-patching loop (IC-as-selection refuted 5×) + no high-water break for several versions.
**Inputs:** `V230_TRACK_A.md` (vendor due diligence), `V230_TRACK_B.md` (free-data signal audit), `V230_TRACK_C.md` (direction reassessment).

---

## Executive summary (3 paragraphs)

The V222→V229 overlay arc spent seven versions re-weighting the existing momentum/mean-reversion basket via Information-Coefficient (IC) selection and produced exactly one shippable crisis win — V227's drawdown-magnitude-gated **additive brake** (+$630 crisis) — plus one un-promotable trend-only overlay (V229, +$1,428 hermetic). The sharp structural lesson, now triply confirmed, is that the drawdown-magnitude gate **works as an additive brake but fails as a selection re-weight** (V229 proved it: crisis Δ −$2,008 at every X). IC-as-selection is closed by five refutations. The three V230 tracks were commissioned to answer "what next" without walking that dead end again.

The three tracks converge on an unusually clean answer. **Track A** (vendor research) found a free DVOL MVP exists but covers only 2 of our 3 windows (DVOL didn't exist before March 2021, so no 2020-Q1) and would require a fresh frozen-feed build regardless of vendor — so options-skew is **not** worth any spend now and is strictly inferior to a signal we can build from data we already own. **Track B** (free-data audit) found that the only true time series spanning all three crisis windows in our frozen snapshots is **per-symbol daily OHLCV** (funding/OI/basis are static scalars; macro history doesn't cover the crisis dates), and identified a top pick that is zero-cost, all-3-windows, orthogonal, and additive-brake-shaped: a **realized-vol term-structure inversion brake**. **Track C** (direction) delivered the load-bearing caveat: the +$630 crisis win is real *within* its window (~52σ over the $12 floor) but **unproven across windows** — identical code swings crisis ±$16k between 2020-Q1 and 2022-H1 (V218.E). We are Goodharting three single windows.

The integrated decision resolves the one genuine tension between the tracks — Track B says "ship the additive brake," Track C says "fix the eval first." **Track C wins on sequencing, Track B wins on the eventual bet.** V231 = build the distributional (≥3-window-per-regime) evaluation harness and re-measure V227/V229 against it; V232 = ship Track B's realized-vol term-structure brake *measured on that distribution*. This costs one extra version but stops us from shipping window-luck — the exact mistake the seven-version arc kept making. The options-skew DVOL MVP (Track A) is parked as a V233+ probe behind both.

---

## Track A summary — vendor: NO purchase, free MVP only (and it's still inferior)

- **Free MVP exists:** Deribit's public no-auth `public/get_volatility_index_data` (and free CryptoDataDownload CSVs) give historical DVOL OHLC, one-shot freezable per V215 at $0 recurring.
- **Hard limit:** DVOL launched ~March 2021 → **no 2020-Q1 coverage**. A DVOL signal is testable on only 2 of 3 windows. True 25-Δ risk-reversal history is **not** free (Deribit serves no historical order books); it needs a paid raw-chain vendor (Tardis Business, ~$300 min, treatable as a one-time freeze-then-cancel) or live forward accumulation.
- **Verdict:** **No spend.** Even the free MVP requires a fresh frozen-feed build and covers fewer windows than Track B's pick. Options-skew is parked behind Track B. Escalate to a one-time Tardis Business freeze only if a free DVOL MVP shows a signal worth backfilling 2020-Q1.

## Track B summary — ranked shortlist (free-data, additive-brake)

Binding constraint discovered: **only daily OHLCV is a true time series present in all three snapshots.** Funding/OI/basis are static scalars; macro (DXY/VIX) history doesn't span the crisis dates. So every viable near-term candidate is OHLCV-derived.

| # | Candidate | Orthogonality | Crisis prior | Data | Effort | Verdict |
|---|---|---|---|---|---|---|
| **1** | **Realized-vol term-structure inversion brake** (short/long RV ratio, 3d vs 14d) | ●●● (vol-of-vol, shorter timescale) | ●●● | ✅ OHLCV | **S** | **TOP PICK** |
| 2 | Realized cross-sectional correlation spike (mean pairwise Spearman) | ●●● | ●●● | ✅ OHLCV | M (stateful) | V232+ follow-on |
| 3 | Volume-shock / illiquidity (Amihud z-score) | ●●○ | ●●○ | ✅ OHLCV | S | backup |
| 4 | Downside-gap / jump intensity | ●●○ | ●●○ | ✅ OHLCV | S | redundancy risk vs V227 |
| — | Basis / funding-spread / OI-velocity / macro-derivative | ●●● | ●●● | 🔴 blocked (no history in snapshots) | — | needs a feed-build version first |

Top pick mirrors `crisis_skew.py` exactly: stateless, per-ticker, one-sided [-1,0], `math.fsum` discipline, applied in the post-demean additive block (`signal_generation.py:1336–1409`), gated by the proven V227 drawdown-AND-gate.

## Track C summary — honest direction call

- **Where we stand:** net marginally positive but carried almost entirely by `recent` (+$4,901, one window). Trend ≈ −$218, crisis still −$2,991 (never cleared zero).
- **+$630 crisis:** real within-window (~52σ over the $12 floor) but **between-window variance is ~$16k** (V218.E: identical code, crisis −$2,863 → +$13,052 across the two crisis windows). Right signal, wrong yardstick.
- **Verdict (verbatim):** **STEP BACK — but the step-back is the evaluation instrument, not the strategy.** Ship distributional (≥3-window) evaluation + the flag-wiring preflight FIRST, then re-measure V227/V229 and run ONE additive-brake signal against the distribution. Do NOT redesign the composite/sizing yet (continuous sizing reopens the V220/V221 determinism channel — a 12-month item). Do NOT chase another selection re-weight (closed, 5×).

---

## Integrated V231 brief

**The three tracks agree on the eventual bet (Track B's RV-term-structure additive brake) and on what NOT to do (no vendor spend, no IC re-weight, no composite/sizing redesign yet). The only tension is sequencing, and Track C's evidence is decisive: shipping any single-window signal next repeats the just-diagnosed mistake.** Therefore:

> **V231 = build the distributional evaluation harness, then re-measure the standing main + V227 + V229 across it.**
>
> Concretely: add ≥3 snapshot windows per regime (crisis already has 2020-Q1 and 2022-H1 frozen — wire 2020-Q1 in as a second crisis gate first; add a 3rd crisis window and 2nd trend/recent windows where freezable via the V215 recipe). The gate runner reports **mean ± spread per regime** instead of a single point estimate. Ship the cheap "every declared flag does something" wiring-preflight alongside (Track C R4 / OBSERVABILITY-BACKLOG). No `strategy.py` logic change — this is harness + eval only, so it cannot move any PnL and is a pure instrument upgrade. Re-baseline the standing main as a distribution and re-test whether V227's +$630 and V229's +$1,428 survive the cross-window spread.
>
> **V232 (gated behind V231) = ship Track B's #1: the realized-vol term-structure inversion additive brake**, measured on the V231 distribution, following the V227 recipe (new `signals/rv_term_structure.py`, default-inert flags reproducing V227 main byte-for-byte, post-demean fsum-add, V227 drawdown-AND-gate). **V233+ = the free DVOL options-skew MVP** (Track A), only if appetite remains after V232.

### Falsifier for the V231 hypothesis

V231's hypothesis is **"our single-window gates are hiding the true generalization of recent overlays; a distributional eval will change at least one verdict."** It is **falsified** if, after wiring ≥3 windows per regime: (a) the per-regime cross-window spread is small (e.g. crisis spread < ~$2k, contradicting the V218.E ±$16k finding) AND (b) V227's +$630 and V229's +$1,428 reproduce within that spread on every window — i.e. the single-window numbers were representative all along. If that happens, the eval-instrument concern was overblown, the 3-gate set was adequate, and we revert to shipping Track B's brake directly as V231-redux with no harness change. Secondary falsifier: if no additional window is freezable via the V215 recipe at acceptable effort (data genuinely unobtainable), the distributional eval is infeasible and we fall back to Track B's brake on the existing 3 gates with an explicit "single-window, may not generalize" caveat.

---

## Decision log

- **No code/strategy change this version.** Deliverables: this file + `V230_TRACK_{A,B,C}.md` + `REFLECTION_V229.md`.
- **No vendor spend authorized.** Options-skew parked to V233+.
- **Next pre-registered version:** V231 = distributional eval harness (instrument upgrade), per the brief above.
