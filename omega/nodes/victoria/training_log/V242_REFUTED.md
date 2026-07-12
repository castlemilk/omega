# V242 — REFUTED at the sanity gate (no grid run)

**Date:** 2026-07-12
**Status:** REFUTED before pre-registration. No grid, no cache-fill, no agy calls.
**Bet:** regime-gate `whale_flow` ON in crisis only (OFF in trend/recent), to bank
the crisis lift without the trend tax. Queued at the end of V240 Track B.
**Verdict:** the paper number fails the pre-registered sanity gate, and the regime
tag does not statistically separate whale_flow's benefit. Do NOT spend a 32-cell grid.

---

## Pre-registered decision rule (from the V242 brief)

> Simulate crisis-gated whale_flow POOLED across regimes. If the paper number
> doesn't clear **crisis-only-lift Δ > +$1,500 AND pooled Δ > +$800**, the bet is
> too weak to justify a grid — REFUTE.

Both conditions are required (AND). The pooled condition fails.

## Inputs (all committed on main, pure analysis)

- Per-window `whale_flow` solo-feed Δ (ON−OFF) from
  `V240_SIGNAL_FORENSICS.md` — the 160-cell solo-feed grid over the 32-window
  walk-forward manifest. Δ is measured vs the **V238 legacy 4-name `main`
  baseline, PRE-V240.A** selective-universe adoption (doc caveat #3).
- Regime tags from `data/walk_forward_manifest.json` (crisis 12 / trend 10 / recent 10).
- Reproducer: `scripts/v242_separator.py`. Full output: `V242_SEPARATOR_RESULTS.json`.

## Q1 — Distribution of whale_flow Δ per regime ($ per window)

| regime | n | mean | p25 | p50 | p75 | min | max | +/− |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crisis | 12 | **+2,063** | −1,447 | +1,387 | +5,211 | −7,346 | +11,547 | 8/4 |
| trend  | 10 | −2,433 | −1,693 | +22 | +335 | −22,271 | +4,666 | 5/5 |
| recent | 10 | −435 | −2,701 | −1,143 | +56 | −3,032 | +6,930 | 3/7 |

The crisis mean is genuinely positive, but the spread is enormous ($18,893) and
**p25 = −$1,447**: a quarter of crisis windows LOSE >$1.4k with whale_flow ON.

## Q2 — Does the crisis lift come from ALL windows or a subset?

Neither extreme. 8/12 crisis windows are positive; the positive mass is spread
(top-1 window = 28.5%, top-2 = 55% of positive mass — not a single-window fluke),
but it is heavily offset by four large-negative crisis windows:

- Winners: `20240310` +$11,547, `20210326` +$10,750, `20211221` +$5,768,
  `20220917` +$5,025, `20240608` +$4,266.
- Losers: `20241205` −$7,346, `20220321` −$4,005, `20250901` −$3,664, `20251130` −$708.

Net crisis sum = +$24,757, but it is the residual of ±$40k of gross swings — a
low signal-to-noise "lift".

## Q3 — Mann-Whitney U: does the regime tag separate the benefit?

- crisis (n=12) median **+$1,387** vs non-crisis trend+recent (n=20) median **−$197**.
- U = 157, **p (crisis > non-crisis, one-sided) = 0.078** → does NOT separate at α=0.05.

The direction is right and it is suggestive (p<0.10), but the premise a grid would
buy — "the crisis tag actually discriminates whale_flow's edge" — is **not
statistically established**. Gating on a tag that doesn't significantly separate
the outcome is gating on noise.

## Q4 — Gate sanity check

Crisis-gated whale_flow changes only the 12 crisis windows (trend/recent Δ = 0 by
construction, since whale_flow is OFF = baseline there).

| metric | value | bar | clears? |
|---|---:|---:|:--:|
| crisis-only-lift (per-window mean) | **+$2,063** | > +$1,500 | ✅ |
| pooled Δ (per-window mean over 32) | **+$773.65** | > +$800 | ❌ (miss by $26) |
| — crisis-only-lift (sum) | +$24,757 | — | ref |
| — pooled Δ (sum) | +$24,757 | — | ref |

**AND rule fails** on the pooled bar. The $26 miss is far inside the recent-noise
band (2·SE ≈ $2,400) — the pooled number is statistically indistinguishable from
the bar, i.e. no measurable pooled improvement.

## Why REFUTE (three independent reasons, any one sufficient under the rule)

1. **Pooled bar fails** (+$773.65 < +$800) — the pre-registered AND gate is not met.
2. **Separator non-significant** (Mann-Whitney p=0.078 > 0.05) — the crisis tag
   does not reliably discriminate whale_flow's benefit; the gate would be built on
   a distinction the data doesn't support.
3. **Baseline mismatch amplifies the risk.** Every Δ here is vs the V238 legacy
   4-name universe. The V240 standing baseline blacklists **BTC/DOT/LINK** — the
   exact names that carried V239's crisis loss. Removing them plausibly *shrinks*
   whale_flow's crisis edge on the real target universe, pushing an already-marginal
   pooled number further under the bar. The confirm-grid would very likely measure
   LESS than +$2,063 crisis, not more.

## What would revive the bet (not pursued now)

- A **cleaner separator** than the raw `crisis` tag. The crisis losers
  (`20241205`, `20220321`, `20250901`) suggest whale_flow's edge is conditional on
  something finer than the drawdown-first crisis label (e.g. whale-flow *direction
  agreement* with the composite, or an OI/funding sub-condition). Find a gate whose
  Mann-Whitney separation clears 0.05 on the V240 selective universe FIRST (a
  separator proof, per the standing V234 rule), then pre-register.
- A **selective-universe re-measurement** of whale_flow solo (crisis only) to
  replace the V238-baseline estimate with a real number. If that number still shows
  a crisis lift after the BTC/DOT/LINK blacklist, revisit — but that is itself grid
  work and only worth it if a better separator is in hand.

## Observability note

The refutation was cheap only because V240's forensics doc committed the full
per-window Δ inline (the `v240_signal_forensics/` mount dir is already gone). The
separator proof (Mann-Whitney on the regime tag) is a **~5-line, zero-cost check
that should precede every regime-gate pre-reg** — it would have caught this without
even the paper sanity sum. Reproducer committed as `scripts/v242_separator.py`;
promote the pattern into the standing "pre-grid separator proof" rule for any
regime-gated-signal bet.

## Next

The whale_flow regime-gate is retired at the estimate stage. The interesting
residual is finding a **sub-crisis separator** that clears 0.05; that is the next
candidate, but it needs its own forensic (separator proof on the selective universe)
before any pre-reg. Do not re-queue the raw crisis-tag gate.
