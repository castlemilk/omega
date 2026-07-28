# V262-2 F4 — regime-independence gate — VERDICT: **PASS**

**Date:** 2026-07-28
**Parent:** [`V262.md`](V262.md) §6 (pre-registration), [`V262_AUDIT_VERDICT.md`](V262_AUDIT_VERDICT.md)
**Scorer:** `scripts/v262_f4_regime_independence.py` (new, purely observational)
**Artifact:** `data/v262_f4_regime_independence.json` (byte-identical on re-run,
sha256 `aee6b687…4d9a844a`)

> **⚠ CORRECTION (2026-07-28, from F4b §3) — COVERAGE, not verdict.** The V262
> frozen corpus stores `open_ms` in **microseconds** for every name's 2025-01 →
> 2026-07 files (19 files × 13,680 bars/name = **177,840 of 665,824 bars, 26.7%
> of the corpus**, clean edge at 2025-01). `macro_label_at()` returns `None` for
> those out-of-range timestamps, so **F4 silently skipped the entire
> 2025-01→2026-07 era**; the per-name `n` below is ~24% below true coverage
> (XRPUSDT: 638 nominal − 486 scored = 152 = 13,680/90 exactly). The **PASS is
> not inverted** — F4b re-measured on both coverages and both land in the same
> band — but F4's numbers are for **2020-01→2024-12 only**. The freeze
> (`scripts/v262_freeze_intraday.py`) should be corrected before F1–F3 read the
> corpus.

**No strategy code touched. No flag flipped. Standing baseline (V240-selective:
crisis +$599 / trend +$2,997 / recent +$30) untouched.**

---

## 1. The pre-registered clause

> **F4 — regime independence (the gate on the thesis).** Compute per-name hourly
> regime labels and correlate against the macro-day regime label. If
> **correlation > 0.7**, intraday regime is the daily regime with more sampling —
> no new information, effective N does not grow → **REFUTED**, stop before any
> grid. — V262.md §6

Run first and alone, per V262.md §2a and the standing V234 separator-proof rule.

## 2. Method — every component pre-declared, none tuned

| Component | Source |
|---|---|
| Macro-day regime | `data/walk_forward_manifest.json` — the **32 committed** non-overlapping 90-day windows, each already carrying a mechanical `regime` label from `scripts/walk_forward_freeze.py:regime_label`. Each 1h bar inherits its containing window's label. |
| Hourly regime | The **identical** `regime_label` thresholds (crisis: `max_dd >= 0.30` or `ret <= -0.15`; trend: `ret >= +0.20`; else recent) applied to **non-overlapping 90-bar** windows of the name's own 1h close series. 90 bars at 1h = the 3.75-day window named verbatim in V262.md §2a; STRIDE = WINDOW mirrors the daily `STRIDE_DAYS == WINDOW_DAYS` tiling. |
| Correlation | **Cramér's V** over the (hourly label × macro label) contingency table — the standard bounded-[0,1] association measure for categorical × categorical, so the pre-declared 0.7 cut applies directly. Agreement rate + normalized MI reported alongside. |
| Universe | V240-selective tradable 10. BTC/ETH (regime reference) and DOT/LINK (blacklisted) computed and reported but **excluded from the universe mean**, per V262.md §3 ("freezing data ≠ admitting a name"). |
| MATIC/POL | Two **separate name-histories**; the 80h migration hole is never spliced (V262.md §3). |

No threshold, window length, or classifier choice was selected after seeing a
result. The one non-pre-declared number — Cramér's V as the concrete reading of
"correlation" — is the only measure of the family that is bounded on [0,1] and
therefore the only one on which a 0.7 cut is even well-posed.

## 3. Per-name results — primary arm (pre-declared thresholds, unscaled)

| Symbol | n windows | **Cramér's V** | Agreement | nMI | hourly dist (crisis/trend/recent) |
|---|---:|---:|---:|---:|---|
| SOLUSDT | 427 | 0.1299 | 0.290 | 0.0344 | 26/30/371 |
| BNBUSDT | 486 | 0.0806 | 0.222 | 0.0411 | 12/9/465 |
| AVAXUSDT | 416 | 0.1951 | 0.320 | 0.0805 | 29/26/361 |
| XRPUSDT | 486 | 0.0788 | 0.235 | 0.0237 | 18/20/448 |
| SUIUSDT | 162 | 0.1432 | 0.333 | 0.0705 | 5/8/149 |
| POLUSDT | 29 | 0.3664 | 0.483 | 0.3072 | 1/3/25 |
| ADAUSDT | 486 | 0.1330 | 0.245 | 0.0659 | 16/21/449 |
| NEARUSDT | 410 | 0.1346 | 0.290 | 0.0414 | 27/25/358 |
| ARBUSDT | 173 | 0.1360 | 0.358 | 0.0777 | 5/5/163 |
| MATICUSDT | 456 | 0.1113 | 0.246 | 0.0277 | 26/29/401 |
| **Universe mean (10 names)** | | **0.150898** | | | max 0.3665 |

Excluded-from-mean reference/blacklisted names (same ballpark, no outlier):
BTC 0.1045, ETH 0.1279, DOT 0.1416, LINK 0.1285.

## 4. Degeneracy guard — the check that makes the PASS trustworthy

V260 was refuted for a degenerate classifier (94% one class). A degenerate hourly
labeller would push Cramér's V toward 0 and manufacture a **spurious PASS**, so it
had to be checked rather than assumed.

The primary arm **is** partly degenerate: **5 of 10** names put ≥90% of hourly
windows in `recent`. That is the honest and expected consequence of applying a
90-*day* return threshold (±0.20 / −0.15) unchanged to a 3.75-*day* window — and
pre-registration forbids retuning it.

So a **diagnostic-only** second arm re-ran with the return/drawdown thresholds
sqrt-time-scaled to the 3.75-day horizon (×0.2041). That arm is **not degenerate
at all — 0 of 10 names** — and gives:

- **universe-mean Cramér's V = 0.1782** (max 0.4978), agreement ≈ 0.41

Both arms land an order of magnitude below the cut. **The PASS is not a
degeneracy artifact** — it survives the arm specifically constructed to break it.
The verdict itself is taken from the primary (pre-declared, unscaled) arm only.

## 5. Verdict

> ### **F4 = PASS**
> **Universe-mean Cramér's V = 0.1509** (primary, pre-declared) — **0.55 below**
> the 0.7 refute cut. Corroborated at **0.1782** in the non-degenerate diagnostic
> arm. Per-name max is **0.3664** (POLUSDT, n=29 — the thinnest history and the
> only name within 2× of nothing-like-the-cut).

Hourly per-name regime structure is **genuinely orthogonal** to the macro-day
regime. Agreement with the macro label runs 0.22–0.48 — at or below what three
labels would produce by chance — and normalized mutual information is 0.02–0.08
bits-fraction for every name but POL. Intraday is **not** the daily regime with
more sampling.

**Consequence:** the load-bearing assumption in V262.md §2a survives its own
hardest test. The intraday thesis is worth the full V262-2 build. **F1–F3
(pooled median, MWU p, annualized net) now proceed** — that is the follow-on task.

## 6. Residual risks F4 does **not** clear — carry these into V262-2

F4 tested **label association**, which is what it was pre-registered to test. It
does not by itself certify effective-N multiplication:

1. **Serial dependence.** Low correlation with the *macro* label ≠ mutual
   independence *between consecutive hourly windows*. If adjacent 90-bar windows
   are autocorrelated, effective N grows sub-linearly in bar count. V262-2 should
   measure the lag-1 label transition matrix before quoting any N.
   → **CLOSED 2026-07-28 by [`V262_F4b_AUTOCORRELATION_VERDICT.md`](V262_F4b_AUTOCORRELATION_VERDICT.md):
   CAVEATED PASS.** Universe-mean lag-1 same-state = 0.8622 (below the 0.90 FAIL
   cut), but that is almost entirely marginal skew — excess over the memoryless
   baseline is only +1.2 points, and λ₂ ≈ 0.13 ⇒ **N_eff/N ≈ 0.78–0.87, i.e. an
   effective multiplier of ~19–21×, NOT 24×.** Quote N_eff, never N, in F1–F3.
2. **F3 remains the most likely killer** (V262.md §7, and the V255.B precedent:
   real 36.4% gross alpha still died at −$5.95 median net on friction). Passing F4
   moves the burden onto transaction cost, it does not lighten it.
3. **The intraday regime labeller is new code** with its own correctness risk
   (V262.md §7). This scorer's labeller is deliberately the *daily* function
   re-applied, not a new design — V262-2's labeller is still to be built and
   justified.
4. **POLUSDT n=29** is thin, and is the one elevated reading. It carries little
   weight but should not be quietly dropped in V262-2.

## 7. What this task delivered

**Delivered:** `scripts/v262_f4_regime_independence.py`, the frozen result JSON
(byte-identical re-run verified), this verdict, and the
[`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) rank-table update.

**Explicitly NOT delivered:** no scorer for F1–F3, no grid, no 5m freeze, no
strategy code, no flag. Every V241–V262 flag stays **OFF**.
