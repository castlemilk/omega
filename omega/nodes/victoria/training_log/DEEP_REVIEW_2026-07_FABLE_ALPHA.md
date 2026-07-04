# DEEP REVIEW — Alpha sources, advanced math, new data (Fable 5, review #2)

**Date:** 2026-07-04
**Author:** claude (Fable 5) — strategic review, NOT a V### iteration
**Scope:** Given the honest V235 walk-forward baselines (trend +$1,941 / crisis
+$819 / recent −$516), answer: what generates real alpha in modern crypto, what
mathematics captures it, and what new data is worth freezing? Produce the V236
plan.
**Prior:** `DEEP_REVIEW_2026-06_FABLE.md` (instrument-vs-alpha accounting),
`REFLECTION_V235.md` (inverted findings), `V235_WALKFORWARD_RESULTS.md`.
**Status:** advisory. No strategy.py change, no grid run.

---

## Executive summary

1. **The single cheapest alpha unlock is not a new signal — it is making the
   information signals we already own actually run.** The macro/sentiment roster
   (fear_greed, VIX, DXY, yield_curve, whale_flow, GDELT geopolitical) is
   live-fetch-only. Under the V215 network guard, every one of them returns 0.0
   or stale cache in every hermetic backtest — the campaign has **never once
   distributionally tested its own information signals**. Freezing their
   *historical series* into snapshots (FRED, alternative.me, GDELT are all free
   with full daily history) turns six dead signals live for ~M effort.
2. **The deepest free data source we are not using is `data.binance.vision`** —
   Binance's public bulk-dump S3 bucket (static files, not the geo-blocked API):
   full historical funding rates (2019→), futures klines, and daily futures
   metrics (open interest, long/short ratio, taker buy/sell volume) per symbol.
   This is exactly the "orthogonal to OHLCV" series data Track B said the
   snapshots lack, it is trivially V215-freezable (files, not endpoints), and
   funding/OI/taker-imbalance are the three most-cited persistent retail-flow
   edges in the daily-frequency crypto literature.
3. **Recent's failure has a mechanistic shape: it is the chop regime, and the
   composite is a momentum blend.** Momentum in low-trend-efficiency windows is
   structurally negative-expectation (whipsaw), and no amount of signal-weight
   tuning fixes an edge that doesn't exist in that state. The first-order fix is
   **conditional exposure, not new alpha**: measure trend efficiency (Kaufman ER
   / variance-ratio) at entry and throttle when the tape is chop. This is
   V236 — S effort, zero new data, separator provable from artifacts we already
   have before any grid.
4. **Of the advanced-math menu, three fit the daily-bar frozen-replay
   architecture without rebuild:** (a) BTC-factor residualization (regress each
   alt on BTC, trade the idiosyncratic residual — a proper version of what the
   cross-sectional demean crudely approximates), (b) correlation-structure
   monitoring (PCA absorption ratio / mean pairwise corr — feeds the already-
   queued V237 tail cap), (c) a 2-state Markov-switching / Kalman trend filter
   to replace threshold regime labels. Hawkes, copulas, vol surfaces, and GNNs
   are honestly scored below — mostly starved by daily bars or missing data.
5. **Hawkes processes are the right model for the crisis-tail problem but the
   wrong model for daily bars.** Self-excitation is an intraday/event-time
   phenomenon; at 60–90 daily bars per window a Hawkes fit is numerology. It
   becomes real if/when liquidation event data (binance.vision
   `liquidationSnapshot`, or Coinglass paid) is frozen — queue behind the data,
   not ahead of it.
6. **Polymarket is a genuinely novel, free, freezable sentiment source — but
   thin before 2024.** CLOB `prices-history` gives full historical series per
   market; crypto-relevant markets ("BTC above X by Y", Fed decisions, election
   risk) are dense only from ~2024. Useful as a *forward* signal and for the
   2024–2026 windows (12 of 32), not as a full-corpus backfill. Score it as a
   V238+ add-on to the feed build, not a program.
7. **Structural edges (funding-basis carry, cross-exchange arb, MEV) are mostly
   out of reach of this infrastructure** — they need live execution, latency,
   or intraday data. The two exceptions that degrade gracefully to daily bars:
   funding-rate extremes as a positioning/sentiment signal (data exists, free)
   and vol-risk-premium tilts (needs Deribit DVOL, free post-2021 only).
8. **Statistical power remains the binding constraint and biases every choice
   toward S-effort, high-prior interventions.** With n=10 windows and
   σ≈$3.5–4.3k per regime, only effects ≥ ~$2k/window mean-shift are resolvable.
   That kills "add a weak new signal to the composite" as a strategy — weak
   signals are unmeasurable here. Interventions must be *state-conditional
   exposure changes* (big effect when they fire) or *data that changes what the
   system can see*.
9. **On strategy shape (Section 6): don't rebuild — re-balance the ambition.**
   Keep the cross-sectional core for trend/crisis where it measurably earns;
   treat recent as a risk-to-be-suppressed (chop throttle) rather than an
   alpha-to-be-found; expand the universe (V238/V239 blacklist flip) for power
   rather than concentrating further; add the portfolio-level risk layer (V237)
   that the architecture has always lacked. A ground-up rebuild would discard
   the campaign's one world-class asset (the hermetic distributional eval) to
   re-litigate solved problems.
10. **Recommended queue: V236 = chop-conditional exposure throttle (recent),
    V237 = corr-spike tail cap (unchanged), V238 = frozen-series feed build
    (FRED + fear/greed history + binance.vision funding/OI) activating the
    information-signal class, V239 = blacklist flip on the new baseline.**
    No paid data until the free tier is exhausted — today nothing paid is
    blocking.

---

## Section 1 — What is real alpha in modern crypto? (2026 reality check)

Honest taxonomy of edges that have demonstrably persisted through 2024–2026,
scored for accessibility from a 200-cycle daily-bar frozen-snapshot replay.

### 1.1 Structural edges

| Edge | Alive in 2026? | Fits our infra? |
|---|---|---|
| **Funding-basis carry** (short perp / long spot when funding is rich) | Yes — compressed vs 2021 but persistently positive; it is a risk premium paid by levered longs, not an anomaly | Partially. True carry needs perp+spot legs and funding accrual accounting we don't model. But the *signal content* of funding extremes (crowded positioning → mean-reversion of price) survives at daily frequency and only needs frozen funding history (§3). |
| **Cross-exchange / latency arb** | Yes, for HFT firms | No. Milliseconds and colocation. Not our game; do not build toward it. |
| **Liquidation-cascade prediction** | Yes — cascades are mechanical (forced sellers at known leverage bands) | Not at daily bars. Needs liquidation/OI event data + intraday granularity. Revisit behind the §3 feed build (Hawkes, §2). |
| **Options vol risk premium** (systematic short-vol / skew harvesting) | Yes — crypto IV persistently overprices RV | Data-blocked. Deribit DVOL free but 2021-03+ (covers ~24 of 32 windows); full surfaces are Tardis-paid. Park (unchanged Track A verdict). |

### 1.2 Statistical edges

- **Time-series momentum (daily, weeks-scale):** decayed since 2017–2021 but
  still the best-documented crypto anomaly; our trend distribution (+$1,941
  mean, n=10) is consistent with us already harvesting it. *This is our
  existing edge. Protect it; don't dilute it.*
- **Cross-sectional momentum across alts:** weak when the universe is 4
  correlated alts (prior review's central finding). Becomes real only with the
  universe expansion (V238/V239) — width is the input to cross-sectional alpha.
- **Short-horizon mean reversion:** exists at hours-scale; at daily bars it
  blends into noise. Not worth a version.

### 1.3 Information edges

- **Positioning/sentiment extremes** (funding extremes, fear/greed extremes,
  taker buy/sell imbalance, long/short ratio): the best-fit info edge for us —
  daily granularity is native, data is free and freezable, and the mechanism
  (retail crowding → reversal) is regime-relevant to *recent/chop*.
- **News/event-first trading:** real but decays in minutes-to-hours; a daily
  replay can't monetize the fast component. The slow component (multi-day drift
  after macro surprises) is tradable — that's the FRED/macro-calendar series in
  §3, and it's what our (inert) VIX/DXY/yield-curve signals were meant to be.
- **Large-wallet / exchange netflow:** noisy, heavily mined, mostly paywalled
  now (Glassnode free tier is nearly empty in 2026). CoinMetrics community CSVs
  remain the honest free source. Expected marginal alpha: low but non-zero.

### 1.4 Regime-timing edges

Real, and this is where our architecture already lives (regime-adaptive
thresholds). What we lack is a *statistically grounded* regime state — current
labels are hand thresholds on bear_prob/vol. §2's Markov-switching /
Kalman-trend candidates upgrade exactly this. The V235 distribution is itself
evidence regime-conditioning matters: the same code is +$1,941 in trend and
−$516 in recent.

### 1.5 Microstructure edges

Order-book pressure, OFI, VPIN, Kyle's λ: alive but structurally invisible to a
frozen daily replay (V185 lesson stands — WS-only signals can't be evaluated
here). These belong to the live-paper Phase B program, which remains
deliberately parked. Do not spend versions on signals the yardstick cannot see.

### 1.6 Meta/behavioral edges

Retail-vs-pro flow divergence (taker imbalance vs OI change composition),
"everyone-knows" crowding (funding + fear/greed at joint extremes): accessible
at daily frequency from the §3 feeds, and mechanistically targeted at chop
regimes where trend signals fail. This is the most promising *new-alpha* class
for recent — but per summary #8, it must enter as a *conditional-exposure
modifier* (big when it fires), not as one more term in a linear composite.

**Bottom line:** our infrastructure can honestly host (i) the momentum edge we
already have, (ii) positioning/sentiment-extreme edges pending the feed build,
(iii) regime-timing upgrades, (iv) macro-drift signals pending frozen series.
It cannot host latency arb, intraday cascades, options surfaces (data), or
microstructure (measurement) — and should stop implicitly aspiring to.

---

## Section 2 — Advanced mathematical pathways

Scores: Effort S/M/L · Impact 1–5 · Conviction 1–5 · Infra-fit (✓ = no
architecture change).

### 2.1 BTC-factor residualization (factor model, first PC ≈ BTC) — S–M · 4 · 4 · ✓

The cross-sectional demean *is* a degenerate one-factor model with all betas
pinned to 1. Replace it: rolling OLS of each alt's daily return on BTC return
(60d window, computable from frozen OHLCV — BTC is in every snapshot even
though blacklisted from *trading*), then feed the composite the **residual**
series. Mechanism: in high-correlation states (crisis, chop) nearly all
variance is factor variance; betas of these alts range ~0.9–1.5, so demeaning
with β=1 leaves systematic contamination in the "idiosyncratic" signal the
system trades. Residualization removes it properly and gives a defensible
market-neutral construction. Implementation: one function in
`signal_generation.py` beside `_basket_mean` (fsum-fenced from day one), flag
`factor_residualization`. Falsifier: walk-forward, all 32 windows, mean-Δ and
tail bars. Directly attacks recent AND crisis-tail simultaneously.

### 2.2 Trend-efficiency state variable (variance ratio / Kaufman ER) — S · 4 · 4 · ✓

Not exotic math, but the right math: Lo–MacKinlay variance ratio or Kaufman
efficiency ratio ER = |P_t − P_{t−n}| / Σ|P_i − P_{i−1}| computed on the basket
(or BTC) over a 20–30d window measures whether the tape is trending or mean-
reverting *right now*. A momentum composite's conditional expectancy given
ER is the cleanest testable structure in this codebase: winners should enter at
higher ER than losers. This is the V236 separator (§5). No new data; ~40 lines.

### 2.3 Correlation structure: PCA absorption ratio / eigenvalue concentration — S · 3 · 4 · ✓

Absorption ratio = share of basket variance explained by the first eigenvector
of the rolling correlation matrix (Kritzman et al. 2010). Cheap from frozen
OHLCV, well-behaved even on a 13-name universe, and a strictly better trigger
for the queued V237 corr-spike cap than raw mean pairwise correlation (it
detects one-factor collapse, which is exactly the crisis-tail state:
p25 −$2,135 / min −$5,819). Feed V237's mechanism; not a separate version.

### 2.4 Markov-switching regime model (2–3 state HMM on basket returns) — M · 3 · 3 · ✓

Hamilton-style switching on (return, |return|) with Student-t emissions;
filtered state probability replaces the hand-thresholded bear_prob/bull_prob.
Fits offline on 2020→2026 daily history, filters causally in replay (no
smoother in the trading path — smoothing is look-ahead). Honest caveats: on
daily crypto data 2-state vol-switching models are robust, 3-state less so;
and the win over the existing thresholds may be < resolvable effect size.
Worth a version only after V236/V237, and only as a *replacement* (not another
overlay on the ~30 existing).

### 2.5 Kalman latent-trend filter (local-linear-trend DLM per asset) — M · 3 · 3 · ✓

State-space [level, slope] with adaptive gain: extracts a de-noised slope
estimate whose posterior variance is itself a chop detector (high innovation
variance ⇒ trendless). Overlaps heavily with 2.2 at far higher complexity; the
principled version of the same bet. Do 2.2 first; escalate here only if ER
separates but the crude throttle fails the distribution bar.

### 2.6 Hawkes processes for cascade risk — M–L · 3 (conditional) · 2 · needs data

The right formalism for liquidation cascades (self-exciting point process,
branching ratio ≈ cascade fragility), and 2020-Q1/2022-H1/2024-Aug is indeed a
good corpus — but **event-time models need events**: at 60–90 daily bars per
window there is nothing to fit. Viable path: freeze liquidation events from
binance.vision (`liquidationSnapshot` daily files exist per futures symbol) or
Coinglass (paid, ~$29/mo tier), estimate branching ratio on a trailing window,
use it as a crisis-tail sizing input. Queue strictly behind the §3 feed build.
Reference: Hawkes (1971); crypto application e.g. Jain et al. on BitMEX
liquidations.

### 2.7 Copulas for tail dependence — M · 2–3 · 2 · ✓(analysis) / ✗(runtime)

Clayton/t-copula on alt-pair returns to quantify lower-tail dependence
(λ_L ≫ ρ implies diversification vanishes exactly when needed — the crisis-tail
mechanism). Honest use here: **offline analysis to calibrate V237's cap level**,
not a runtime model — with 4 tradeable names and ~25 trades/window a runtime
copula is unfalsifiable. One notebook, feeds one number into V237.

### 2.8 Vol surfaces (SVI/SABR on Deribit) — L · 3 · 2 · needs paid data

IV skew/term-structure dynamics are real signals (25Δ skew leads spot drawdowns
at daily horizon). Free path is DVOL only (a single index, post-2021-03);
surfaces need Tardis (~$300 one-off historical). Unchanged verdict from the
prior review: park until a specific vol hypothesis survives on the windows DVOL
covers — a DVOL-vs-realized spread signal is a cheap S-effort probe *within*
the V238 feed build for the 2021+ windows.

### 2.9 Graph neural nets on the asset graph — L · 1 · 1 · ✗

With 13 assets, n=32 windows, and ~25 trades/window, a GNN is an overfit
machine with a literature review attached. The graph *structure* insight is
already captured by 2.3 (eigenstructure) and the existing Fiedler machinery.
Rejected.

### 2.10 Optimization surfaces — see Section 4 (promoted to its own treatment).

### Ranked (math only)

| Technique | Effort | Impact | Conviction | Infra fit |
|---|:---:|:---:|:---:|:---:|
| Trend-efficiency state variable (VR/ER) | S | 4 | 4 | ✓ |
| BTC-factor residualization | S–M | 4 | 4 | ✓ |
| PCA absorption ratio (→V237 trigger) | S | 3 | 4 | ✓ |
| Markov-switching regime state | M | 3 | 3 | ✓ |
| Kalman latent-trend DLM | M | 3 | 3 | ✓ |
| Copula tail-dependence (offline, calibrates V237) | M | 2–3 | 2 | ✓ |
| Hawkes cascade intensity | M–L | 3 | 2 | needs event data |
| Vol surfaces SVI/SABR | L | 3 | 2 | needs paid data |
| GNN portfolio state | L | 1 | 1 | ✗ |

---

## Section 3 — Novel disparate data sources

Freeze-recipe context: a source is hermetic-viable iff its **full history** can
be fetched once at freeze time and written into the snapshot (per-window slice),
so replay reads files, never the network (V215 guard stays absolute). Sources
that only serve "current value" endpoints are useless to us regardless of
quality — that is precisely the defect of the six existing macro signals.

### 3.1 The headline finding: our information signals have never run

`fear_greed.py`, `vix_signal.py`, `dxy_signal.py`, `yield_curve.py`,
`whale_flow.py`, `geopolitical.py` all fetch live with TTL caches;
`freeze_snapshot.py` stores only point-in-time scalars (`fear_greed: N`, one
funding value per symbol). Under the hermetic guard these signals contribute
0.0/stale in every eval — six implemented, wired, flag-gated signals with
**zero honest measurements ever**. Before buying or building anything new, make
these run on frozen series. That reframes "novel data" as mostly *history
backfill for existing signals*.

### 3.2 Free / open sources, scored

| Source | Provides | History | Freeze recipe | Effort | Expected quality |
|---|---|---|---|:---:|:---:|
| **data.binance.vision** (public S3 dumps; NOT the geo-blocked API — verify from US at freeze time, else route the one-time pull via EU proxy/VPS) | Funding rates (2019→), futures klines, daily futures **metrics**: open interest, top-trader long/short ratio, taker buy/sell vol; `liquidationSnapshot` | Full | Download monthly zips at freeze; write per-symbol daily series into snapshot | M | **High** — the only free source of positioning series; orthogonal to OHLCV by construction |
| **FRED** (api.stlouisfed.org, free key) | VIX, DXY (DTWEXBGS), 10y−2y (T10Y2Y), EFFR, CPI release values | Decades | One CSV pull per series per freeze; slice per window | S | Medium-high — activates 3 existing signals with real history |
| **alternative.me fear/greed** | Daily crypto F&G index | 2018→, full series in ONE call (`?limit=0`) | Trivial | S | Medium — extremes are the signal, mid-range is noise |
| **CoinMetrics community** (free CSV/API) | Active addresses, transfer values, realized cap era metrics, some exchange flows | 2010s→ daily | Bulk CSV at freeze | S–M | Medium — heavily mined, but free and clean |
| **Deribit public API** | DVOL index history (`get_volatility_index_data`) | 2021-03→ | JSON pull per freeze | S | Medium — enables IV−RV spread probe on 2021+ windows (~24/32) |
| **Polymarket** (Gamma + CLOB `prices-history`) | Event probabilities: BTC/ETH price targets, Fed decisions, elections, macro events | Dense 2024→ only (~12/32 windows) | Enumerate crypto/macro markets per window via Gamma API; freeze price series | M | Speculative-medium — genuinely novel (crowd probability ≠ price-derived sentiment); thin backfill is the honest limiter |
| **GDELT DOC 2.0** (already wired in `geopolitical.py`) | News event counts/tone by theme | 2015→ | Historical query per window at freeze (API supports date ranges) | S–M | Low-medium — signal already built, just needs frozen series + replay timestamps |
| **Google Trends** (pytrends, unofficial) | Retail search interest ("buy bitcoin" etc.) | 2004→ weekly (daily only ≤90d spans; requires stitch-normalization) | Pull + stitch at freeze | M | Low — rescaling/sampling noise is notorious; classic 2013-era signal, heavily decayed |
| **Blockchain.com charts API** | BTC-only on-chain basics | Full | Trivial | S | Low — BTC-only, mined out |
| **mempool.space** | Fee rates, mempool depth (congestion = activity proxy) | Partial | S | S | Low |
| ~~Glassnode free tier~~ | (2026: free tier reduced to near-nothing at daily resolution) | — | — | — | not worth wiring |

### 3.3 Paid tier — none recommended now

| Source | Cost | Would unblock | Verdict |
|---|---|---|---|
| **Tardis.dev** | ~$300 one-off historical / ~$100–300/mo | Full Deribit options surfaces + L2 books | Only if a DVOL-level probe (free) shows vol signal survives the distribution bar. Then it's justified; not before. |
| **Coinglass** | ~$29–79/mo | Cross-exchange liquidation + OI history, aggregated | The cheap unlock for Hawkes (§2.6) if binance.vision liquidation dumps prove insufficient. Second in the paid queue. |
| **Kaiko / Amberdata / CoinAPI** | $500+/mo | Consolidated feeds we mostly don't need | No — everything they'd give us that we can use is free elsewhere at daily frequency. |

### 3.4 Integration shape (one feed build, not five)

One version (V238 proposal, §5): extend `walk_forward_freeze.py` with a
`series/` section in the snapshot — `{source}/{symbol_or_index}.json` daily
series per window — and a `SeriesProvider` in the replay that serves the
frozen series bar-aligned (same bar-time fence as V216). Signals read the
provider, never the network. Wrap-seam rule applies: series must cover the
window exactly; provider raises on out-of-range reads rather than wrapping.
Priority order inside the build: FRED + fear/greed (S, activates 4 existing
signals) → binance.vision funding/OI/taker (M, the new-alpha payload) → DVOL
(S) → Polymarket/GDELT (M, 2024+ windows only).

---

## Section 4 — Cross-cutting linkages: one concrete optimization surface

**Proposal: the regime-conditional signal-effectiveness surface** — replace
"tune weights on windows" (13 versions of Goodhart) with "estimate the
response surface once, read decisions off it, validate walk-forward."

- **Dimensions (2D, deliberately small):** x = trend-efficiency state (ER,
  §2.2, bucketed ~5 levels); y = correlation-absorption state (§2.3, ~4
  levels). Both computable from frozen OHLCV on every one of the 32 windows —
  no new data required.
- **Response:** per-signal forward IC (signal value at t vs residual return
  t→t+3), pooled across all 32 windows, estimated per (x,y) cell; plus the
  composite's conditional expectancy per cell in $/trade from existing
  trades.csv artifacts.
- **Data volume check (honest):** 32 windows × ~60–90 bars × 13 symbols ≈
  30k signal-return observations — enough for a 5×4 surface of ICs with
  ridge-style shrinkage toward the pooled mean, NOT enough for anything finer.
  Fit with leave-one-window-out CV; a cell's IC is "real" only if its LOWO
  sign is stable.
- **Optimizer:** none fancy — the surface IS the deliverable. Decisions read
  off it: (a) exposure multiplier per cell (the V236 throttle is its 1D
  x-axis marginal), (b) which signals earn weight in which cells (kills or
  confirms the regime-adaptive threshold stack with data), (c) where the
  system should sit out entirely (cells with negative pooled expectancy —
  prediction: the low-ER cells that recent windows occupy).
- **Falsifier:** the surface must be *stable*: estimated on odd-numbered
  windows, it must hold sign per cell on even-numbered windows. If cells flip,
  the surface is noise and conditional weighting is dead as a direction —
  which would itself be a campaign-grade finding (it would say: stop
  conditioning, simplify to unconditional trend + risk caps).
- **Effort:** M (one offline script + one markdown of heatmaps; zero runtime
  risk). Natural companion piece to V236 — V236's separator probe is this
  surface's first column.

The sentiment–price–vol joint model (copula over F&G × return × RV) is the
same pattern once V238's series exist; it is scored lower because its data
axis doesn't exist yet. Build the OHLCV-native surface first.

---

## Section 5 — Concrete recommendation: V236 and the queue

### V236 — chop-conditional exposure throttle (recent-regime intervention)

**Hypothesis (one sentence):** the momentum composite has negative conditional
expectancy when trend efficiency is low, and recent's −$516 mean / −$2,551 p25
is concentrated in low-ER states, so throttling size (or raising the
conviction bar) when basket ER falls below a threshold moves the recent
distribution's mean and tail without materially regressing trend (whose
entries are high-ER by construction).

**Why this over alternatives:** it comes off REFLECTION_V235's untouched-
dimensions list (recent intervention + cross-window-robust sizing); it is a
*conditional exposure* change, so its per-window effect is large when it fires
(resolvable against σ≈$3.5k, unlike weak-signal additions); it needs zero new
data and ~40 lines; and its separator is provable from existing artifacts
before any run.

**Pre-grid separator proof (V234 rule, costs ~0 runs):** from the 10 recent-
window main-arm trades.csv files ($AUDIT/v235_wf cells) + frozen OHLCV,
compute basket ER (20d) at each entry. Requirement: winners' median entry-ER
exceeds losers' by a margin that survives a rank test on the pooled ~140
recent trades, and the low-ER tercile's pooled PnL is materially negative. If
ER doesn't separate, try the Lo–MacKinlay variance ratio; if neither
separates, V236's mechanism is refuted for $0 and the fallback (below)
promotes.

**Implementation outline:** `_trend_efficiency()` in `signal_generation.py`
(fsum-fenced, computed on frozen bars only — no wall-clock); one multiplicative
size modifier in the existing sizing stack (site: the same `raw_weights`
normalization layer retained from V234) gated by flag `chop_throttle`;
threshold set from the separator analysis, NOT gridded (one value, pre-
registered; a 2-point sensitivity check at ±25% is diagnostic color only).

**Falsifier / acceptance bar (pre-registered on the n=10 recent
distribution):** recent mean-Δ > +$400 AND recent p25-Δ > +$500 AND trend
mean-Δ > −$300 AND crisis mean-Δ > −$300, on all 32 windows (the throttle is
regime-agnostic code; it must be measured everywhere). Refuted ⇒ recent is
declared structurally unwinnable for a momentum book at daily bars, and the
program's recent posture becomes "minimize exposure" permanently.

**Effort budget:** separator ~1 session; implementation ~1 session; grid = one
32-window × 2-config walk-forward pass (solved, resumable).

### V237 — unchanged: portfolio corr-spike tail cap

As already queued (regime-agnostic tail-width control, pooled p25/min bars on
all 32 windows) — upgraded per §2.3 to use the PCA absorption ratio as the
trigger and §2.7's offline copula fit to calibrate the cap level.

### V238 — frozen-series feed build (the data unlock)

Instrument-plus-data version, zero strategy risk: snapshot `series/` section +
`SeriesProvider` + freeze pullers for FRED, alternative.me F&G history,
binance.vision funding/OI/taker metrics, DVOL. Re-run the standing main on all
32 windows with the info-signal flags ON to get the first honest measurement
of the six dead signals (this re-baseline is the version's deliverable — any
alpha found is V239+ material). Blacklist flip moves to **V239**, where it
benefits from the same run anyway (justification: one grid re-baseline instead
of two; the blacklist flip's baseline would be invalidated by the feed build
landing after it).

### V239 — universe/blacklist flip on the new baseline

As previously specified (hermetic-era N≥50, ≥3-window evidence bar per
exclusion), measured as universe_full vs universe_legacy on the walk-forward
distribution.

---

## Section 6 — Is the current strategy even the right shape? (direct answer)

**Keep the shape; change the ambition per regime. Do not rebuild.**

1. **Universe: expand, don't concentrate.** The de facto 4-name book is
   already over-concentrated — that's the prior review's core structural
   finding, and it caps both cross-sectional alpha and statistical power.
   Concentrating further into BTC+ETH would turn the book into a beta timer
   and discard the cross-sectional machinery that trend/crisis profitably use.
   The blacklist flip (V239) is the right move, on the honest baseline.
2. **Per-ticker vs portfolio-first: hybridize, don't invert.** Per-ticker
   entry logic is fine and measurably works in trend. What's missing is the
   portfolio layer ON TOP (gross exposure, factor beta, corr-collapse cap) —
   exactly V237. A full portfolio-first rewrite (optimize weights jointly per
   cycle) is unfalsifiable at ~25 trades/window and would reset five years of
   eval calibration.
3. **Recent: yes — accept it, then suppress it.** The honest read is that a
   momentum book at daily bars has no demonstrated edge in chop, and no
   composite tweak manufactures one. The correct objective for recent is
   *don't lose* (V236 throttle). If V236's separator holds, recent's target
   distribution is "mean ≈ 0, tail lifted," not "find +$2k of chop alpha."
   The only credible paths to genuine chop alpha are new-information classes
   (positioning extremes via V238's funding/OI/taker series; possibly
   Polymarket for 2024+) — pursue as V239+ hypotheses with separator proofs,
   not as prerequisites for V236.
4. **The one modeling change that could plausibly *fix* rather than suppress
   recent** is BTC-factor residualization (§2.1): if chop losses are partly
   mis-demeaned factor noise being traded as idio signal, residualization
   fixes a real defect rather than gating a symptom. It is the strongest
   §2 candidate for the V236 *fallback* slot — promoted if ER fails to
   separate — or for V240 if both work independently.
5. **What a rebuild would and wouldn't buy:** a clean-room strategy (portfolio
   optimizer + factor model + regime HMM) is the fashionable shape, but every
   one of its components is individually adoptable into the current
   architecture behind flags with distributional measurement — which is
   strictly more falsifiable than a big-bang rewrite. The 4,000-line sediment
   in strategy.py is real debt, but the cure is the planned simplification
   pass (delete unmeasured overlays after V238's re-baseline gives cover),
   not abandonment.

---

## Ranked recommendations (top 5)

| # | Recommendation | Effort | Impact | Conviction | Infra fit | Slot |
|---|---|:---:|:---:|:---:|:---:|---|
| 1 | Chop-conditional exposure throttle (ER/VR state variable) | S | 4 | 4 | ✓ | **V236** |
| 2 | Frozen-series feed build: FRED + F&G history + binance.vision funding/OI/taker (+DVOL) — activates 6 dead info signals + the only free positioning data | M | 4 | 4 | ✓ (freeze-side) | V238 |
| 3 | BTC-factor residualization of the composite | S–M | 4 | 4 | ✓ | V236 fallback / V240 |
| 4 | Corr-spike tail cap with PCA absorption-ratio trigger (+offline copula calibration) | S–M | 3 | 4 | ✓ | V237 (queued) |
| 5 | Regime-conditional signal-effectiveness surface (ER × absorption, LOWO-validated) | M | 3 | 3 | ✓ (offline) | companion analysis to V236 |

De-prioritized with reasons on record: Hawkes (starved until liquidation
events are frozen), vol surfaces (paid data, DVOL probe first), HMM/Kalman
(replacement-grade only, after the queue), GNN (rejected), Google Trends
(decayed), paid data (nothing currently blocked by money).

---

*Prepared as review-of-record for the alpha/math/data question. Next action:
pre-register V236 per Section 5 (separator proof first — costs zero grid
runs).*
