# V262-2 F4b — regime-autocorrelation / effective-N gate — VERDICT: **CAVEATED PASS**

**Date:** 2026-07-28
**Parent:** [`V262_F4_VERDICT.md`](V262_F4_VERDICT.md) §6 residual risk 1, [`V262.md`](V262.md)
**Scorer:** `scripts/v262_f4b_autocorrelation.py` (new, purely observational)
**Artifact:** `data/v262_f4b_autocorrelation.json` (byte-identical on re-run,
sha256 `bf5027e2…2a2c90bf`)

**No strategy code touched. No flag flipped. Standing baseline (V240-selective:
crisis +$599 / trend +$2,997 / recent +$30) untouched.**

---

## 1. The pre-registered clause

> **Serial dependence.** Low correlation with the *macro* label ≠ mutual
> independence *between consecutive hourly windows*. If adjacent 90-bar windows
> are autocorrelated, effective N grows sub-linearly in bar count. V262-2 should
> measure the lag-1 label transition matrix **before quoting any N**.
> — `V262_F4_VERDICT.md` §6.1

Pre-registered thresholds on the **universe-mean lag-1 same-state probability**,
primary arm (locked before running; nothing tuned after):

| Band | Reading | Consequence |
|---|---|---|
| `> 0.90` | FAIL | effective N is ~1×, not 24× — F3 not worth the burn |
| `0.60 < p ≤ 0.90` | **CAVEATED PASS** | effective N grows ~5–15×; F3 runs with honest N |
| `≤ 0.60` | CLEAN PASS | effective N genuinely grows |

Run before F1/F2/F3, per the standing V234 separator-proof rule.

## 2. Method — every component inherited from F4, nothing tuned

| Component | Source |
|---|---|
| Windows | The **same** non-overlapping 90-bar tiling of each name's own 1h close series used by `scripts/v262_f4_regime_independence.py` (`HOURLY_WINDOW_BARS == HOURLY_STRIDE_BARS == 90`). Adjacent tiles *are* the lag-1 pairs. |
| Labels | The **same** `regime_label` thresholds (crisis: `max_dd ≥ 0.30` or `ret ≤ −0.15`; trend: `ret ≥ +0.20`; else recent). |
| Arms | **Primary** (unscaled, pre-declared) is the verdict arm. **Diagnostic** re-runs with the sqrt-time-scaled thresholds (×0.2041) F4 used to defeat the degeneracy objection. Both reported, per F4's dual-track discipline. |
| Universe | V240-selective tradable 10. BTC/ETH (regime reference) and DOT/LINK (blacklisted) computed and reported but **excluded from the universe mean**. |
| Contiguity | A lag-1 transition counts **only** when window *i+1* begins exactly 90 h after window *i* — a **timestamp** check, not index adjacency. Load-bearing: the corpus has real holes (the MATIC/POL 80h migration gap, V262.md §3), and index-adjacency across a hole fabricates a transition between non-consecutive periods. |
| N_eff | λ₂ = second-largest eigenvalue modulus (SLEM) of the row-stochastic lag-1 matrix — the Markov analogue of an AR(1) ρ. Reported both as `1 − λ₂` (the form named in the pre-registration) and `(1−λ₂)/(1+λ₂)` (the standard, strictly more conservative, serial-correlation ESS deflator). |
| Chance guard | Same-state probability is inflated **mechanically** by a skewed marginal. The memoryless baseline Σᵢpᵢ² and the excess over it are reported per name. **The verdict still uses the raw pre-registered quantity** — the baseline is interpretation, not a moved goalpost. |

## 3. A corpus defect found en route (material, affects the committed F4)

The contiguity check rejected ~26% of transitions, which forced an audit rather
than an assumption. The cause is a **real unit defect in the V262 frozen corpus**:

> Every name's **2025-01 → 2026-07** monthly files store column 0 (`open_ms`) in
> **microseconds**, not milliseconds. 19 files × 13,680 bars per name =
> **177,840 of 665,824 bars — 26.7% of the corpus** — with a clean edge at
> 2025-01. (MATICUSDT is unaffected only because its history ends 2024-09.)

**This silently truncated F4.** `v262_f4_regime_independence.py:macro_label_at`
returns `None` for an out-of-range timestamp and the window is skipped, so the
entire 2025-01→2026-07 era was dropped from F4's contingency tables. The
arithmetic is exact: XRPUSDT 638 nominal windows − 486 F4-scored = **152 =
13,680 / 90**.

F4's PASS is **not inverted** by this — see §5, where this scorer's ms-era-only
arm (F4's effective coverage) and its full-corpus arm land in the same band —
but F4's stated per-name `n` understates coverage by ~24% and its verdict was
computed on 2020-01→2024-12 only. This scorer magnitude-detects and rescales
(a data-**read** correction, not a threshold change) and reports **both**
coverages so the two are directly comparable.

## 4. Per-name results — primary arm, full corpus (verdict arm)

| Symbol | N nominal | transitions | **lag-1 same-state** | chance | excess | λ₂ | **N_eff/N** (1−λ₂) | N_eff |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 579 | 568 | 0.842 | 0.814 | +0.027 | 0.181 | 0.819 | 474.4 |
| BNBUSDT | 638 | 622 | 0.942 | 0.928 | +0.014 | 0.227 | 0.773 | 493.4 |
| AVAXUSDT | 568 | 558 | 0.817 | 0.796 | +0.021 | 0.158 | 0.842 | 478.1 |
| XRPUSDT | 638 | 622 | 0.892 | 0.881 | +0.012 | 0.127 | 0.873 | 556.9 |
| SUIUSDT | 314 | 313 | 0.853 | 0.856 | −0.003 | 0.081 | 0.919 | 288.7 |
| POLUSDT | 181 | 180 | 0.900 | 0.904 | −0.004 | 0.053 | 0.947 | 171.5 |
| ADAUSDT | 638 | 622 | 0.876 | 0.866 | +0.010 | 0.102 | 0.898 | 573.2 |
| NEARUSDT | 562 | 551 | 0.811 | 0.797 | +0.014 | 0.070 | 0.930 | 522.6 |
| ARBUSDT | 325 | 323 | 0.870 | 0.877 | −0.007 | 0.070 | 0.930 | 302.4 |
| MATICUSDT | 456 | 440 | 0.818 | 0.785 | +0.034 | 0.212 | 0.788 | 359.2 |
| **Universe mean (10)** | | | **0.862180** | 0.850298 | **+0.011882** | 0.128 | **0.872** | |

sd 0.0422, min 0.8113 (NEAR), max 0.9421 (BNB). Conservative SLEM deflator
`(1−λ₂)/(1+λ₂)` universe mean = **0.778**.

Excluded reference/blacklisted names (no outlier): BTC 0.974, ETH 0.920,
DOT 0.867, LINK 0.863.

## 5. Both arms, both coverages — the verdict is robust to every axis

| Arm | Coverage | mean same-state | chance | **excess** | mean N_eff/N (1−λ₂) | mean N_eff/N (SLEM) | Band |
|---|---|---:|---:|---:|---:|---:|---|
| **primary (verdict)** | full corpus | **0.8622** | 0.8503 | **+0.0119** | 0.872 | 0.778 | CAVEATED |
| diagnostic (scaled) | full corpus | 0.6007 | 0.5370 | +0.0637 | 0.802 | 0.672 | CAVEATED (by 0.0007) |
| primary | ms era only | 0.8351 | 0.8227 | +0.0124 | 0.859 | 0.758 | CAVEATED |
| diagnostic (scaled) | ms era only | 0.6032 | 0.5453 | +0.0579 | 0.781 | 0.653 | CAVEATED |

**All four cells land in the same band.** The verdict does not depend on the
degeneracy arm, and it does not depend on whether the µs-era bars are included.

## 6. The number that matters more than the headline

The raw 0.8622 sits high in the CAVEATED band, but **almost none of it is
memory**. A memoryless sampler drawing from the *same* label marginals scores
0.8503. The persistence actually present is the **excess: +1.19 points.**

That is the same degeneracy F4 already documented — 90-*day* return thresholds
applied unchanged to a 3.75-*day* window put ~90% of windows in `recent`, and
pre-registration forbids retuning them. The arm built specifically to remove the
degeneracy (diagnostic, marginals no longer skewed: chance drops 0.850 → 0.537)
shows the same story with more headroom: same-state 0.6007 against a 0.5370
baseline, excess +6.4 points.

The eigenvalue estimate is the honest reading, and it agrees across both arms:

> **λ₂ ≈ 0.13 (primary) / 0.18 (diagnostic) ⇒ N_eff/N ≈ 0.78–0.87.**

## 7. Verdict

> ### **F4b = CAVEATED PASS**
> **Universe-mean lag-1 same-state probability = 0.8622** (primary,
> pre-declared, full corpus) — inside the pre-registered
> `0.60 < p ≤ 0.90` CAVEATED band, **0.038 below the FAIL cut**. Corroborated at
> 0.6007 in the non-degenerate diagnostic arm and at 0.8351 / 0.6032 on F4's
> ms-only coverage. All four cells agree.

Adjacent hourly windows are **not** near-deterministic repeats of each other:
per-name λ₂ runs 0.05–0.23, and the excess over the memoryless baseline is
≤ 3.4 points on every name (three names are *negative* — very slightly
anti-persistent). The `> 0.90` FAIL scenario — "consecutive windows carry
near-zero new information" — is **not** what the corpus shows.

**Honest effective N for F3 (this is the number to quote, not 24×):**

| | Value |
|---|---|
| Nominal intraday multiplier | 24× |
| N_eff/N, `1 − λ₂` (pre-registered form) | 0.872 |
| N_eff/N, SLEM `(1−λ₂)/(1+λ₂)` (conservative) | 0.778 |
| **Effective multiplier vs daily bars** | **≈ 19–21×** |

This is at the **optimistic end** of the CAVEATED band's stated "~5–15×"
expectation, and materially better than the band label alone implies. The
caveat is real but narrow: **quote ~19–21×, never 24×**, and deflate every F1/F2
significance calculation by N_eff, not N.

## 8. Consequence

**F1/F2/F3 proceed.** The autocorrelation killer that F4 flagged as its own
first residual risk did **not** materialize. Intraday manufactures genuinely
new samples at ~0.78–0.87 efficiency, so the walk-forward burn buys real
independent evidence rather than resampled copies.

The burden is now where F4 left it: **F3 (annualized net ≥ 15%) remains the most
likely killer** (V262.md §7; V255.B precedent — real 36.4% gross alpha still
died at −$5.95 median net on friction). F4b does not lighten transaction cost;
it only confirms the samples are real.

## 9. Residual risks F4b does **not** clear

1. **The µs corpus defect is diagnosed, not fixed at source.** This scorer works
   around it in its own loader. `v262_f4_regime_independence.py` still silently
   drops the 2025–2026 era, and any *future* consumer of
   `data/frozen_series/binance_intraday/` will hit the same trap. The freeze
   (`scripts/v262_freeze_intraday.py`) should be corrected and the byte-identity
   manifest re-asserted before F1–F3 read the corpus. **Tracked as follow-up.**
2. **λ₂ is a lag-1 statistic.** Longer-range dependence (a slowly-varying vol
   regime with a multi-day time constant) would not show up at lag 1. F4b tested
   what it was pre-registered to test.
3. **Label-space autocorrelation ≠ return-space autocorrelation.** F4b measures
   persistence of the *regime label*. Overlapping-signal or serially-correlated
   *returns* remain a separate question for F1/F2's significance maths.
4. **POLUSDT n=180** and the degenerate primary marginals remain, exactly as F4
   recorded them. POL is no longer the outlier here (0.900, excess −0.004).

## 10. What this task delivered

**Delivered:** `scripts/v262_f4b_autocorrelation.py`, the frozen result JSON
(byte-identical re-run verified), this verdict, the corpus-defect diagnosis in
§3, a correction note on `V262_F4_VERDICT.md`, and the
[`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) intraday-entry update.

**Explicitly NOT delivered:** no scorer for F1–F3, no grid, no 5m freeze, no
strategy code, no flag, no corpus re-freeze. Every V241–V262 flag stays **OFF**.
