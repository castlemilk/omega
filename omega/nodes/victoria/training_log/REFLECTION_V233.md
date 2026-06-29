# REFLECTION_V233

**Trigger:** The reflection-trigger pre-armed in `V233.md` fired. V233 deliberately stepped
off the additive-term *signal* walk onto the untouched **application-site** dimension — and
the site dimension failed the binding window too. With 12/12 crisis cells PASS at $0.00
determinism, **2024aug (−$9,508, the worst crisis window) returns Δ == $0.00 under every
additive-composition-site variant tested**: pre-demean injection, common-mode re-injection,
and 3× weight escalation (0.2 → 0.4 → 0.6). This is the **subsystem-patching-loop** trigger
on the *site* subsystem, layered on top of the same trigger already exhausted on the *signal*
subsystem.

## What is now exhausted (the honest tally for 2024aug)

The 2024aug crisis loss has resisted, at byte-identical $0.00, **every additive-term-at-the-
composite intervention across seven versions**:

| version | intervention | 2024aug Δ |
|---|---|---:|
| V227 | drawdown-gated crisis-**skew** (the signal) | $0.00 |
| V231 | instrument swap (VRP→drawdown selector) | $0.00 |
| V232 | RV-term-structure inversion **brake** | $0.00 |
| V233 | **pre-demean** site (w0.2) | $0.00 |
| V233 | **pre-demean** site (w0.4) | $0.00 |
| V233 | **pre-demean** site (w0.6) | $0.00 |
| V233 | pre-demean **common-mode re-injection** (w0.2) | +$6.31 (cosmetic; 0 trades flipped) |

Four distinct *signals* and three distinct *sites/weights* — all enter the per-ticker
composite additively, all hit the same wall. The +$6.31 from common-mode re-injection is the
closest anything has come, and it is a price-level rounding perturbation (same 47 trades, no
selection change) that costs −$182 on 2020q1. The hypothesis class "**make the additive
crisis term enter the composite differently / louder**" is refuted.

## The structural lesson (sharpened)

2024aug's $0.00 is a **downstream decision-boundary deadband**, not an upstream composition
artifact. The mechanism (Track A, grid-confirmed): the V227 drawdown-AND-gate *fires* on
2024aug (drawdown 0.292 = 2.4× threshold), so the term IS computed and added — but after
`×_cs_norm` into `w_conv` (`strategy.py:~1922`), the residual is smaller than the gap to any
conviction floor/threshold (`strategy.py:~1594-1614`), so **no trade flips** and the ledger is
identical. Moving the add earlier (pre-demean), re-injecting its common mode, or tripling its
weight all change the *number* fed into `w_conv` but none of them move it across a decision
boundary on the broad, correlated, slow yen-carry grind-down — and where the louder term DOES
bite (2022h1), it over-tilts the basket and makes the loss **worse** (−$4,461 → −$4,852,
monotone in weight). The lever that controls whether crisis capital is at risk is **not** the
composite at all; it is the **sizing/exit layer** that turns conviction into position and
decides when to cut.

## Reflection action → V234 = sizing/exit-layer crisis intervention

Per the pre-committed branch 4, V234 abandons additive-term-at-composite work entirely and
intervenes **downstream of the composite**, where 2024aug's deadband actually lives:

1. **Crisis position-sizing throttle / exit overlay** — gate the *size* and *hold* of crisis
   trades on the same V227 drawdown signal that already fires correctly on 2024aug, instead of
   nudging an upstream conviction number that never crosses a boundary. The signal is sound and
   selective (12/21/29 fires across windows); the failure was always at the conviction→trade
   translation, so act *at* the translation.
2. **Pre-register against the same 3-window crisis distribution** (2020q1 / 2022h1 / 2024aug)
   with the V232 bar (mean-Δ>0 AND min-Δ>0). The binding read stays 2024aug; the new success
   criterion is that the *trade ledger actually changes* on 2024aug (Δtrades ≠ 0), which no
   composite-site change ever achieved.

See `V234.md` for the pre-registered brief.

## Carry-forward (still open, deliberately deferred)

- **Track B #2** cross-sectional correlation-spike signal — was gated on a proven site; the
  site is now refuted, so this stays parked unless a *sizing/exit* win re-opens the question.
- **B2 trend-IC** ≥3-window trend distribution; **recent 2025** distribution (MATIC→POL fork)
  — both still open from V231/V232, both lower priority than breaking the 2024aug deadband.
