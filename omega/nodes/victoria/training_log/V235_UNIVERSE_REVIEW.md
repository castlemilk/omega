# V235 — Universe re-validation forensic (`_TRADING_BLACKLIST`)

**Date:** 2026-07-02
**Author:** claude (Fable 5)
**Trigger:** DEEP_REVIEW_2026-06_FABLE Lens 2.2 — effective tradeable universe is 4/13
symbols; every exclusion predates the hermetic eval and was never re-validated.
**Scope:** paper forensic only. No code change in V235; this document is the
preflight for the walk-forward eval (if the blacklist were justified, the
walk-forward baseline should keep it; if not, universe re-expansion becomes a
first-class V238 target with this doc as its evidence base).

---

## Method

Evidence audited = the exclusion rationale comments in
`omega/nodes/victoria/strategy.py:176-231` (the only surviving artifacts — **no
V55–V93 training logs exist**; the log series starts at V148). For each ticker:
claimed trade count, era, and whether the measurement predates the determinism
substrate (V215 HTTP guard / V217 BLAS pin / V219 substrate freeze / V220-V221
fsum fences) and the distributional harness (V231).

Two campaign-level facts frame every verdict:

1. **REFLECTION_V202 measured 60–70% per-trade PnL drift** across changes
   pre-registered as no-ops in the pre-deterministic eval. Every blacklist
   decision below was made in that eval regime. The dollar figures cited in the
   comments are not trustworthy at the magnitudes involved ($4–$105).
2. **V231 measured $25,435 cross-window spread** for identical code on the
   crisis distribution. Single-window, single-run PnL — the evidence class for
   all 9 exclusions — cannot distinguish signal from window luck even when the
   run itself is deterministic.

## Ticker-by-ticker audit

| Ticker | Excluded | Evidence (from strategy.py comments) | N trades | Era vs substrate | Verdict |
|---|---|---|---:|---|---|
| BTCUSDT | pre-V148 (undocumented) | "27.8% win rate — used only as regime indicator"; no run, no count retained | unknown | pre-everything; no artifact at all | **Noise-founded.** Weakest documentation of the nine; most liquid asset in the universe excluded on an unlogged statistic. Re-include. |
| DOTUSDT | V61 | 12.5% WR, −$33.89; "blacklisting projected +$47.44" | ~8 | pre-hermetic | **Noise-founded.** N=8, and the justification is a *projection* from one run. Re-include. |
| MATICUSDT | V62 | "16 zero-PnL trades wasting capacity; signal not credible" | 16 (all zero-PnL) | pre-hermetic | **Noise-founded** (not even losses — a capacity argument). Separate REAL issue: MATIC→POL migration means thin/absent bars in recent windows (58/63 bars in 2024aug). Handle as a per-window **data-coverage attribute** in the walk-forward manifest, not a strategy blacklist. |
| XRPUSDT | V73 | V71: 6T 1W −$44.91; V72: 8T 2W −$105.30 | 14 | pre-hermetic | **Noise-founded.** N=14 across two runs whose per-trade PnL had 60–70% drift. Re-include. |
| SOLUSDT | V80 (re-affirmed V81) | V73: 10T 0W −$78.87; V77: 4T −$4.10; V78: 2T −$13.19; V81: 2 crisis shorts −$30.32 | ~18 | pre-hermetic | **Noise-founded.** The most-documented exclusion still totals N≈18 across four noisy runs; "signal consistently wrong-direction" was never re-tested after the composite/demean core changed (V166+, V211+, V220–V222). Re-include. |
| AVAXUSDT | V83 | 3/3 losing trades, −$42.06 total | 3 | pre-hermetic | **Noise-founded.** N=3. Re-include. |
| LINKUSDT | V86 | cumulative −$55.73: 30 longs (V58) + 4–5 shorts (V81–V85) | ~35 | pre-hermetic, spans V58→V85 (different composite each era) | **Noise-founded despite N≈35.** The count is pooled across incompatible strategy eras; the stated rationale ("mean-reverting in $9.01–$9.10 range… in current market conditions") is explicitly regime-local and ~150 versions stale; net magnitude −$55.73 is far inside per-window noise. Re-include. |
| BNBUSDT | V87 | 3/3 short losses −$53.82 in first 40 cycles of one run | 3 | pre-hermetic | **Noise-founded AND explicitly temporary** ("removing entirely until trend clears" — the trend cleared ~150 versions ago; nobody came back). Re-include. |
| SUIUSDT | V93 | 2T 0W −$9.14; comment itself says "insufficient data to trust either direction" | 2 | pre-hermetic | **Noise-founded by its own admission.** N=2. Re-include. |

Aggregate: the nine exclusions — which removed **69% of the trading universe** and
shrank cross-sectional demeaning's actionable set to 4 correlated alts — rest on
**≈99 trades total**, all measured before the eval was deterministic, none ever
re-validated. For comparison, the campaign now refuses to accept a *single-flag*
change on fewer than 3 windows × 2 replicates of a byte-identical eval.

## Secondary lists

- `_LONG_BLACKLIST = {BTCUSDT}` — same undocumented "27.8% WR" provenance.
  Same verdict: re-validate, don't trust.
- `_CRISIS_BYPASS_BLACKLIST = {}` — already empty; no action.
- `postmortem_signal_filter` short-suppressions on NEAR/ARB (noted in
  DEEP_REVIEW 2.2) are out of scope here but belong to the same evidence class;
  queue with V238.

## Recommendation

1. **Standard:** a ticker stays blacklisted only on hermetic-era evidence of
   **N≥50 trades** with a distributional read (≥3 windows), per the campaign's
   own current bar. **No current entry meets it. Recommended new blacklist: ∅**
   (empty), with MATICUSDT handled as a per-window data-coverage attribute
   (excluded automatically where bars are missing, present where they exist).
2. **Sequencing (important):** do NOT flip `_TRADING_BLACKLIST` inside V235.
   The walk-forward baseline (V235) must measure the **standing main as-is**
   (4-symbol universe) so the new distribution is comparable to every existing
   number. Universe re-expansion is a *strategy* change → it is **V238 (Fork A)**
   per the deep review, measured as `universe_full` vs `universe_legacy` cells
   on the walk-forward distribution this version builds.
3. **Impact on V235 itself:** snapshots are built 13/13 regardless (the
   blacklist is runtime, `strategy.py:2335`), so the walk-forward windows built
   now serve both the V235 baseline AND the V238 re-expansion grid unchanged.
4. **Loop-process rule (shipped with V235, see SKILL.md):** any evidence that
   the effective universe is materially smaller than the nominal one triggers a
   universe re-validation forensic before the next intervention.

**Bottom line: the 4/13 universe is an artifact of ~99 pre-hermetic trades and
was never a validated portfolio decision. The walk-forward baselines measured in
V235 are honest measurements *of the standing main*, but the standing main's
universe itself is unvalidated — treat V238's re-expansion as the first
universe decision the system will ever have actually measured.**
