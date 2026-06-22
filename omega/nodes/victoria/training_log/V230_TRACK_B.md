# V230 Track B — orthogonal crisis-predictive signal shortlist (additive-brake class)

**Date:** 2026-06-22
**Author:** claude (research + codebase-exploration subagent)
**Status:** candidate menu + V231 pre-registration brief. No code changed, no run launched.
**Parent context:** V229 retired the crisis-IC-overlay program (5th refutation). V227's
drawdown-gated **crisis-skew additive brake** is the ONLY crisis win in the V222→V229 arc
(crisis −$3,621.25 → −$2,991.17, +$630.08). V230's mandate: find the *next* orthogonal,
additive-brake, zero-recurring-cost crisis signal — NOT another re-weight of the existing
momentum/mean-rev basket.

---

## The structural lesson this doc obeys (V222–V229)

Seven versions re-weighted the existing momentum/mean-rev signals via Information
Coefficient (IC) selection. **PROVEN DEAD END for crisis** — refuted at V222, V223, V224,
V228, V229. V229 specifically proved the *same drawdown-gate shape that works as an additive
brake* (V227) **fails when applied as a selection re-weight**. The discriminator is not the
gate, it is the **application shape**:

- ❌ **Selection re-weight** — changes *which* existing signals dominate the composite. The
  existing basket is all long-biased and coincident-to-lagging in a crash (it flips bearish
  only *after* price breaks). Re-weighting lagging signals cannot manufacture a lead.
- ✅ **Additive brake** — a *new*, one-sided ([-1, 0]) risk-off term added to the composite
  **after** the cross-sectional demean (`signal_generation.py:1336–1409`), gated to fire only
  in genuine stress, ≈0 in benign tape (the no-harm property).

Therefore every candidate below is scored on three hard constraints, and any candidate that
can only be expressed as a re-weight is disqualified on sight:

1. **Orthogonality** vs the existing basket (different *timescale* AND different *mechanism*).
2. **Additive-brake feasibility** — can it be shaped as a one-sided [-1, 0] term added
   post-demean, mirroring `crisis_skew.py`?
3. **Zero recurring cost** — data already in our frozen snapshots, or cheaply freezable via
   the V215 recipe (one JSON snapshot committed; no paid vendor, no per-cycle live fetch).

---

## Data-availability ground truth (the binding constraint)

I inventoried what the frozen snapshots actually hold (`data/snapshots/*.json`). This is
**decisive** and reorders the candidate list relative to the V213/audit menus, which assumed
feeds we do not have frozen.

| Field | In frozen snapshot? | Shape | Implication |
|---|---|---|---|
| OHLCV per symbol (`close/open/high/low/volume/timestamps`) | ✅ YES | **daily time series**, 90–183 bars × 7–13 symbols | Any OHLCV-derived signal is **zero-cost, hermetic today**. |
| Funding rates (`_macro.funding_rates`) | ⚠️ partial | **single static scalar** per symbol (BTC/ETH/SOL only) | NO history → basis/funding-spread/OI-velocity signals are **NOT buildable** from the current snapshots. Confirmed by `crisis_skew.py` docstring lines 14–20 (same blocker hit at V225). |
| FRED macro (`DGS2/DGS10/DTWEXBGS/VIXCLS`) | ✅ YES | daily series in `data/macro_cache.db` (125–126 rows, 2025-12 → 2026-06) | DXY/VIX/yield **levels are wired**; their *1st derivative* is computable. BUT the macro_cache only covers the **recent** window — it does NOT span the 2020-Q1 / 2022-H1 crisis snapshot dates, so a macro-derivative crisis signal is **un-evaluable on the crisis gate** without backfilling FRED history into the snapshots. |
| `btc_dominance`, `fear_greed` | ❌ `None` in every snapshot | — | Dominance-velocity / sentiment signals are **un-evaluable** on frozen snapshots. |
| Advanced (`btc_dominance_pct`, `long_short_ratio`) | ⚠️ `frozen_advanced_signals.json` | **single static scalar**, recent capture only | No history, no crisis coverage. |

**Hard conclusion:** the only data that is (a) a true time series, (b) present in ALL
snapshots, and (c) spans the crisis windows is **per-symbol daily OHLCV**. Every top-ranked
candidate below is therefore OHLCV-derived. Candidates requiring funding/OI/basis history or
macro-crisis-window coverage are demoted to "blocked — needs a frozen feed first," because
the V218.A/V225 lesson is explicit: *a correct signal is untestable without a frozen feed,*
and we currently have none for those fields across the crisis dates.

This is the same wall `crisis_skew.py` hit and solved correctly: it dropped the requested
Deribit options-skew (no free historical IV for 2020-Q1) and the cross-venue funding spread
(only a static scalar) and instead built a **realized** proxy from OHLCV. V230 follows that
precedent.

---

## Ranked shortlist

Scoring key — Orthogonality / Crisis-predictive prior: ●●● strong, ●●○ moderate, ●○○ weak.
Data: ✅ have now · 🟡 cheap freeze · 🔴 blocked. Effort: S/M/L. Brake-feasible: ✅/⚠️/❌.

| # | Candidate | Orthogonality (timescale + mechanism) | Crisis prior | Data | Effort | Brake-feasible | Verdict |
|---|---|---|---|---|---|---|---|
| **1** | **Realized-vol term-structure inversion** (short/long RV ratio, e.g. 3d vs 14d) | ●●● new mechanism (vol-of-vol regime, not price direction); short timescale vs basket's level-momentum | ●●● near-term RV surging above long-term RV = acute stress / regime shift; high RV ratio → lower fwd returns (lit.) | ✅ OHLCV only | **S** | ✅ one-sided [-1,0] when ratio > 1 | **TOP PICK** |
| 2 | **Realized cross-sectional correlation spike** (mean pairwise Spearman of top-N daily returns) | ●●● basket is per-ticker & long-biased; this is a *cross-ticker* co-movement measure — fully orthogonal | ●●● "diversification dies in a crash": pairwise corr 0.30→0.70+ in systemic stress; downside-asymmetric | ✅ OHLCV only (needs ≥2 symbols' close windows together) | **M** | ✅ one-sided brake when corr > baseline | Strong #2 |
| 3 | **Volume-shock / illiquidity spike** (Amihud-style \|ret\|/volume z-score, or volume-surge-on-down-bar) | ●●○ uses `volume` (basket has a volume *momentum* signal but not an illiquidity/shock transform) | ●●○ liquidity evaporation + forced-selling volume spikes precede cascade legs | ✅ OHLCV+volume | S | ✅ one-sided on down-bars | Solid, lower prior |
| 4 | **Downside-gap / overnight-jump intensity** (count/size of large negative bar-to-bar gaps in window) | ●●○ jump component is distinct from continuous momentum; same OHLCV source as crisis-skew so partial overlap risk | ●●○ jump clustering precedes crash legs; but overlaps crisis-skew's accel term | ✅ OHLCV | S | ✅ | Watch for redundancy w/ V227 |
| 5 | **Cross-asset / macro 1st-derivative brake** (DXY velocity or VIX-extreme transform as additive risk-off) | ●●● genuinely exogenous mechanism (liquidity channel) | ●●● strong lit. prior (DXY ↑ tightens liquidity; VIX>35 → −12% BTC 5d) | 🔴 macro_cache has NO crisis-window coverage; un-evaluable on crisis gate | M (+L to backfill FRED history into snapshots) | ✅ | **BLOCKED** until FRED history frozen into crisis snapshots |
| — | Spot-perp basis / funding-spread / OI-velocity | ●●● strong | ●●● strong | 🔴 only a static scalar in snapshots — no history | M + frozen-feed build | ✅ | **BLOCKED** (V225 already hit this wall) |

**Why #1 over #2:** both are zero-cost and high-prior, but #1 is **S-effort, per-ticker, and
strictly stateless** (mirrors `crisis_skew.py`'s clean determinism profile — no cross-ticker
accumulation, immune to the V221 history-length/call-count channels). #2 is **M-effort** and
**stateful across tickers** (it must aggregate the whole basket's return matrix in one place),
which reintroduces a cross-ticker ordering surface — exactly the class of determinism channel
the V216→V221 arc spent 6 versions closing (`_basket_mean` fsum order, V221). #1 is the lower-
risk first bet; #2 is the natural V232 follow-on if #1 fires.

**Why not #4 first:** it shares the OHLCV-drawdown source with V227's crisis-skew accel
component (`crisis_skew.py:109–118`), so its incremental signal over the incumbent brake is
likely small and hard to attribute. Keep it parked until #1 is measured.

---

## TOP PICK → V231 hypothesis: realized-vol term-structure inversion brake

### Hypothesis

The existing basket measures price *level* momentum/mean-reversion; it carries **no measure
of the volatility regime's term structure**. When short-horizon realized volatility surges
above long-horizon realized volatility (an inverted/backwardated *realized* vol curve), the
tape is in acute near-term stress that historically *leads* the deepest drawdown legs — and
high realized-vol ratios predict lower forward returns (literature). This is **orthogonal in
both axes**: a *vol-of-the-distribution* mechanism (not price direction) on a *shorter*
timescale than the basket's level signals. Shaped as a one-sided additive brake, it should
**help crisis (Δ > +$200) with trend/recent within ±$200** (the V227 success template), and
be **near-inert in benign tape** because in calm regimes short-RV ≈ long-RV ⇒ ratio ≈ 1 ⇒
term ≈ 0.

### Signal definition (per ticker, over the `close` window — mirrors `crisis_skew.py`)

```
r_i        = ln(close[i]/close[i-1])          # i = 1 … n-1, fixed oldest-first order
rv_short   = sqrt(fsum(r_i^2 for last S bars) / S)     # S = 3  (short horizon)
rv_long    = sqrt(fsum(r_i^2 for last L bars) / L)     # L = 14 (long horizon)
ratio      = rv_short / rv_long               # >1 ⇒ near-term vol elevated (inversion)
inversion  = clamp(0, 1, (ratio - 1.0) / K)   # K ≈ 1.0 normalizer; calibrate like X
value      = -inversion                        # ∈ [-1, 0]; risk-off ⇒ NEGATIVE, one-sided
# degenerate guards identical to crisis_skew: <L+1 closes, all-equal, non-finite,
# rv_long==0 → return 0.0 (never NaN). All sums math.fsum, no numpy/BLAS/sum().
```

One-sided by construction (never bullish — the basket supplies the long side). Stateless
across cycles (reads only the passed window), so immune to the V221 call-count / history-
length channels. Every float sum is `math.fsum` over fixed order, `sqrt` is exact-rounded ⇒
permutation-invariant ⇒ no new determinism channel.

### Implementation outline (files + the exact wiring, mirroring V227)

1. **`omega/nodes/victoria/signals/rv_term_structure.py`** (new) — a `RVTermStructureSignal`
   class with `compute(closes: list[float] | None) -> float`, byte-for-byte structured like
   `crisis_skew.py` (same guards, same fsum discipline, returns [-1, 0]).
2. **`omega/nodes/victoria/features.py`** — add flags, all defaulting to the inert value so
   the byte-reachable default reproduces the V227 main exactly:
   - `rv_term_brake_enabled: bool = False`
   - `rv_term_brake_regime_gate_enabled: bool = False`  (reuse the V227 regime+drawdown gate)
   - `rv_term_brake_threshold: float = 0.0`  (the inversion threshold K-cut / drawdown AND-gate, calibrated like V227's X=0.12)
   - `rv_term_brake_weight: float = 0.2`  (start at the V227 gated weight `_SKEW_W_GATED`)
3. **`omega/nodes/victoria/signal_generation.py`** —
   - instantiate `self._rv_term = RVTermStructureSignal()` alongside `self._crisis_skew`
     (line ~402).
   - in the **post-demean additive block** (lines 1336–1409, where crisis-skew is applied),
     add a **sibling** block computing `ts["rv_term"] = _regime_gated_brake(...)` and applying
     it with the **same fsum-add pattern** as line 1404:
     `_adj = math.fsum([_s["composite"], _w * _rv_val]); _s["composite"] = clamp(-1, 1, _adj)`.
   - **Reuse** `_regime_gated_skew` / `_realized_drawdown_mag` (lines 98, ~1150) — the V227
     drawdown-AND-gate is the proven discriminator; gate the new brake the same way (fire only
     when regime ∈ {crisis,high_vol} AND realized recent drawdown ≥ threshold). This is the
     single most important design choice: V229 proved the gate works as a brake, fails as a
     re-weight — we are deliberately on the brake side.
   - add a calibration sink mirroring `OMEGA_SKEW_DD_LOG` (e.g. `OMEGA_RVTERM_LOG`) writing
     per-cycle `ratio`/`inversion`/gate-decision, guarded exactly like the V214 fingerprint
     writers (observability only, never a numeric path).
4. **`tests/test_rv_term_structure.py`** (new) — pin: returns [-1,0]; 0.0 on degenerate input;
   ≈0 on flat tape; fires on a synthetic inverted-vol window; determinism (same input →
   identical bytes); permutation note. Mirror `tests/test_crisis_skew_regime_gate.py`.
5. **Harness:** `scripts/v231_calib.sh` (single threshold=0 run with `OMEGA_RVTERM_LOG` to pick
   K and the drawdown AND-gate X, counting `brake_on_cycles < 40` on trend/recent — the V227
   calibration protocol) + `scripts/v231_run_grid.sh` (3-gate falsifier).
6. **Cell identity:** extend `assert_cell_identity.py` with an `--expect-rvbrake on` check so a
   silently-inert run is caught (the V218.B inertness trap).

### Calibration (copy V227's protocol exactly)

Run a single regime-only (threshold=0) pass per gate with `OMEGA_RVTERM_LOG`; pick the
smallest threshold that keeps `brake_on_cycles < 40` on BOTH trend and recent while still
firing enough genuine-crisis cycles to actually test the thesis. Also sweep `S∈{2,3,5}` and
`L∈{10,14,20}` on the calibration window only (not the falsifier) — but pre-commit to the
chosen (S, L, K, X) **before** the decisive grid to avoid the multiple-comparisons trap.

### Falsifier grid (the decisive read — mirror V227 §"Falsifier grid")

Decisive comparison = brake-ON vs within-grid brake-OFF equal-weight control, **same commit +
frozen caches, IC-off**, on all three gates. The OFF controls MUST reproduce the standing
V227 mains exactly (trend −$217.71, crisis −$2,991.17 with crisis-skew on, recent +$4,901.01-
class) or the grid is contaminated. Require N=2 hermetic ($0.00 spread) on crisis.

### Falsifier (what result kills this bet)

- **REFUTED if crisis Δ (ON−OFF) ≤ +$200** at the calibrated threshold while
  `brake_on_cycles` is in a sane firing range (i.e. the term *did* fire on crisis but didn't
  help) → the realized-vol-inversion prior does not survive Victoria's daily-bar horizon;
  retire it (do NOT chase X like V229 did — that path is the IC trap).
- **REFUTED if trend or recent Δ < −$200** (no-harm broken) → the term leaks into benign tape;
  the one-sided/gated shape failed to contain it.
- **REFUTED if it is merely redundant with crisis-skew** — i.e. stacking it on top of the
  V227 crisis-skew brake adds < +$100 over crisis-skew alone (run a 3-way: OFF / skew-only /
  skew+rvterm). The vol-term-structure brake must earn its keep *beyond* the incumbent
  drawdown-accel brake, not re-express it. (This is the redundancy risk flagged for candidate
  #4; test it explicitly here.)
- **DETERMINISM FAIL** (any cell spread ≠ $0.00) → a new ordering channel was introduced;
  bisect with `per_field_diff.py` / `signal_contribs.jsonl` before trusting any PnL.

### Why this is the right next bet (one paragraph)

It is the **only** candidate that is simultaneously (a) data-available and crisis-window-
covered *today* (pure OHLCV), (b) orthogonal to the basket in both timescale and mechanism,
(c) expressible as a one-sided additive brake with the exact determinism profile of the one
thing that has worked (`crisis_skew.py`), and (d) reuses the V227 drawdown-AND-gate that V229
proved is the correct gate *on the brake side*. It is S-effort and stateless, so the downside
of a refutation is one cheap version, not a determinism regression. The blocked candidates
(basis/funding/OI/macro-derivative) all have strong priors but each requires building and
freezing a new feed across the crisis dates first — that is a separate prerequisite version
(a "V###.I-class frozen-feed build"), not a same-cycle signal experiment.

---

## Parking lot (explicitly deferred, with the unblock condition)

- **Cross-sectional correlation-spike brake (#2)** — V232 if V231 fires. Unblock: accept the
  stateful cross-ticker aggregation and re-verify determinism (it touches the same surface as
  the V221 `_basket_mean` channel).
- **Volume-shock / illiquidity brake (#3)** — strong S-effort backup if #1 refutes on the
  "doesn't help" branch rather than the "leaks" branch.
- **Macro 1st-derivative brake (#5, DXY velocity / VIX-extreme)** — strongest *exogenous*
  prior in the literature, but **blocked**: `macro_cache.db` only covers 2025-12→2026-06, not
  the 2020-Q1 / 2022-H1 crisis snapshots. Unblock = backfill FRED `DTWEXBGS`/`VIXCLS` history
  into the crisis snapshots (`_macro` block), then it becomes a clean additive brake. This is
  the single highest-value *feed* investment, separate from V231.
- **Spot-perp basis / cross-venue funding spread / OI velocity** — highest a-priori crisis
  signals but **blocked** by the static-scalar snapshot (the wall V225 already documented).
  Unblock = a `frozen_basis_feed.json` / `frozen_oi_feed.json` built via the V215 recipe
  across the crisis dates. A frozen-feed-plumbing version, not a signal version.

---

## Sources (crisis-predictive priors)

- Realized-vol term structure / short-vs-long vol as a regime/risk signal; high RV ratio →
  lower forward crypto returns:
  [Amberdata — vol term-structure regime shifts](https://blog.amberdata.io/utilizing-volatility-term-structure-changes-to-spot-regime-shifts),
  [Variance decomposition & crypto return prediction (Lee & Wang, Georgia Tech)](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/crypto_variance_leewang_5feb2024.pdf),
  [Long- & short-term crypto volatility components (GARCH-MIDAS)](https://www.mdpi.com/1911-8074/11/2/23).
- Cross-asset / cross-sectional correlation spikes in crises (diversification fails;
  downside-asymmetric), and the Forbes-Rigobon caveat that raw correlation can be a poor
  early-warning indicator (favours tail / EVT measures):
  [Cross-asset correlation shifts in crisis periods](https://jdacm.com/index.php/jdacm/article/download/58/47),
  [BIS — evaluating correlation breakdowns](https://www.bis.org/publ/confer08k.pdf),
  [ECB — financial market contagion (EVT)](https://www.ecb.europa.eu/pub/pdf/fsr/art/ecb.fsrart200512_02.en.pdf),
  [Volatility spillovers & contagion: deep-learning early warning](https://link.springer.com/article/10.1007/s10614-023-10412-4).
- Crypto-specific caveat (reversed/inverted leverage effect — validate on crypto, don't borrow
  equity intuition):
  [Comparison of cryptocurrency volatility (Financial Innovation)](https://jfin-swufe.springeropen.com/articles/10.1186/s40854-024-00646-y).
