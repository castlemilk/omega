# V283 Phase 0 — the volatility gate cannot move PnL, so TimesFM has nowhere to land

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — probe arms are env-gated and default byte-identical. No version pre-registered.
**Parent:** [`V283_PHASE1_TIMESFM.md`](V283_PHASE1_TIMESFM.md) §5 (which asked for exactly this test first)
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched, sentinels reproduce throughout

---

## §1 — The question

V283 Phase 1 established that TimesFM forecasts volatility materially better than the
naive baseline, subsumes it conditionally, and shows no memorisation signature. Phase 1
§5 then refused to recommend integration until one question was answered:

> **Does a better volatility forecast change Victoria's PnL at all?**

Because V265 already proved that a good forecast with no consumer is worth nothing.

## §2 — Answer: no. The volatility gate is inert, measured 7 ways.

The only volatility-driven *decision* in the strategy is `_check_sit_out`
(`strategy.py:1788`, called unconditionally at `:2333`):

- `vol_rank < _vol_low_threshold` → sit out entirely (size 0.0)
- `vol_rank > _vol_high_threshold` → half size (0.50)

Swept across thresholds and lookbacks, on all three sentinels:

| lookback | high threshold | crisis | trend | recent | `vol_high` fires |
|---|---|---:|---:|---:|---:|
| 100 (default) | 0.80 (default) | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 100 | 1.01 (gate off) | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 100 | 0.60 | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 100 | 0.90 | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 60 | 0.80 | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 60 | 0.60 | $1,149.76 | $4,679.67 | $771.98 | **0** |
| 40 | 0.80 | $1,149.76 | $4,679.67 | $771.98 | **0** |

**Byte-identical in every configuration**, including with the gate fully disabled. The
`"Market chaotic"` branch never executed once.

## §3 — Why, exactly (three independent reasons, all live)

1. **Unreachable by arithmetic.** `_check_sit_out` computes `vol_rank` only when
   `len(prices) >= 101`. Walk-forward windows carry a 90-day lookback — **91 bars**
   (`snap_wf_20240310`: `_lookback: 90`, `BTCUSDT.close` length 91). The gate has been
   **structurally dead in every walk-forward run of the entire campaign**, off by ten
   bars.
2. **Still doesn't fire when made reachable.** With the lookback fitted to the window,
   the computed rank on real bars is **0.0167** (lookback 60) and **0.025** (lookback 40)
   — the current window's vol sits at the *bottom* of its own history, nowhere near 0.80
   or even 0.60.
3. **The other branch was switched off deliberately.** `_vol_low_threshold = 0.0` since
   **V55**, which disabled it because it blocked 200/200 cycles. So the one branch that
   *would* fire at a rank of 0.017 was removed for being too aggressive.

Reasons 1 and 2 are independent: fixing the bar count does not wake the gate.

## §4 — Consequence for the TimesFM lane

**The lane is closed as currently routed.** No improvement to a volatility *estimate* can
change a decision that (a) never evaluates, and (b) would not trigger if it did. TimesFM's
+0.39 conditional edge over naive is real and has **no consumer**.

This is the V265 outcome reached one step earlier and for $0 of grid spend — which is
precisely why Phase 1 §5 asked for it before integration. Had the order been reversed,
this would have been discovered after building the integration.

**It is a fourth instance of the session's dominant defect class:** a subsystem that is
correctly declared, correctly wired, imports cleanly, and never executes. The others:
V279 (6 of 7 signal families inert), V280 (six technical signals disabled by a callback
nothing calls), V282 (scipy's silent algorithm swap).

## §5 — What would have to be true for volatility to matter

Not a recommendation — a statement of the requirement, so nobody builds on sand:

1. **A live consumer.** Volatility currently reaches decisions only through this dead
   gate. A forecast needs a path that actually executes.
2. **A non-diluting shape.** V280 measured that *adding* signals to the equal-weight
   composite costs $1k–$3.2k per window. Any volatility use must be **multiplicative**
   (sizing, risk scaling, gating) rather than additive into the composite — structurally
   different from what V280 refuted.
3. **A pre-registered falsifier on the distribution**, per V235 — three sentinels are a
   diagnostic, and this probe is one.

That is a strategy change with its own pre-registration, not a TimesFM integration.
TimesFM would be the *input* to a mechanism that does not yet exist, and the mechanism —
not the model — is the thing that has to be proved.

## §6 — Probe arms shipped (both default byte-identical)

- `OMEGA_VOL_HIGH_THRESHOLD` — overrides the only live vol gate. Unset ⇒ 0.80.
- `OMEGA_VOL_LOOKBACK` — fits the rank window to the bar count. Unset ⇒ 100.

Kept because the sweep above is worth being able to re-run, and because both make an
otherwise invisible deadness measurable in one command.
