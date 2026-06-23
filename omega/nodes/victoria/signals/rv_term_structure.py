"""Realized-vol term-structure inversion brake for Victoria (V232).

An orthogonal, crisis-*leading* risk-off term derived entirely from the replay
`close` window — no external feed, no network, hermetic by construction. Sibling
of crisis_skew.py (V225-V227); same additive-brake contract, different physics.

## Why this exists (V231 → V232)

V231's distributional eval showed the V227 drawdown-magnitude skew does NOT
generalize across crisis windows (helps 2022h1 +$630, hurts 2020q1 −$424, inert
on 2024aug). Drawdown is a *level* and *lagging* — by the time the per-ticker
drawdown gate trips, price has already broken. The bet here is that the
*term-structure of realized vol* leads the drawdown: when short-window realized
vol spikes ABOVE the longer-window base (an inversion / backwardation of the RV
curve), near-term turbulence is rising faster than the trailing average — the
classic onset signature of a crash, visible BEFORE the drawdown materializes.

This is genuinely orthogonal to crisis_skew (downside-semivariance *skew* of the
return distribution) and to the spot-momentum basket: it is vol-of-the-vol on two
timescales, a ratio, not a level.

## Definition (per ticker, over the close window)

  r_i      = ln(close[i]/close[i-1])                  # i = 1 … n-1, fixed order
  rv_short = sqrt(fsum(r_i^2 for the last `short` returns) / short)   # realized vol
  rv_long  = sqrt(fsum(r_i^2 for the last `long`  returns) / long)
  R        = rv_short / rv_long                        # term-structure ratio; 0 if rv_long==0
  brake    = clamp(0, 1, (R - X) / X)                  # 0 below X; ramps; saturates at R = 2X
  value    = -brake                                    # ∈ [-1, 0]; inversion ⇒ NEGATIVE

The annualization factor (√365 for crypto) cancels in the ratio, so it is omitted
— R is annualization-invariant by construction. Realized vol is the standard
sum-of-squared-log-returns estimator (NOT demeaned): fewer reduction sites, hence
fewer FP-order channels, than a sample-std form (V211/V217/V220/V221 discipline).

Proportional (not binary) and one-sided ([-1, 0]): a binary step at R = X is a
discontinuity that risks single-cycle entry/exit flips near the threshold — the
V220/V221 sub-ulp determinism channel. The proportional ramp is smooth; one-sided
means benign tape (R ≤ X) ⇒ value = 0 ⇒ no effect (the no-harm property). The
basket already supplies the long side.

## Determinism

Every float sum is `math.fsum` over the fixed oldest-first close order; `sqrt`,
divides and `clamp` are exact-rounded scalar ops. No `sum`/numpy/BLAS, no
wall-clock, no network. Missing/degenerate inputs return 0.0, never NaN. A flat
window (max==min) short-circuits to 0.0 — the V221 degenerate-variance fence,
so a constant cached series can never amplify rounding residue into a signal.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger("omega.nodes.victoria.signals.rv_term_structure")

# Defaults — short/long realized-vol windows (daily bars) and the inversion
# threshold X at which the brake starts to fire. X = 1.5 ⇒ short-window RV 50%
# above the 14-day base. Calibrated on the V231 crisis snapshots (Track A): at
# X = 1.5 the brake fires on ~34% of crisis ticker-cycles; the V227 regime+
# drawdown gate further restricts firing to genuine risk-off cycles (R-inversion
# alone also fires in trend rallies, which the gate suppresses).
_RV_SHORT = 3
_RV_LONG = 14
_RV_INVERSION_THRESHOLD = 1.5


class RVTermStructureSignal:
    """Realized-vol term-structure inversion → [-1, 0] risk-off brake.

    Stateless across cycles (reads only the window passed in), so it is immune to
    the call-count / history-length channels (V221) that bit the stateful signals.

    Usage:
        sig = RVTermStructureSignal()
        value = sig.compute(close_window)   # float in [-1, 0]
    """

    def __init__(
        self,
        short_window: int = _RV_SHORT,
        long_window: int = _RV_LONG,
        inversion_threshold: float = _RV_INVERSION_THRESHOLD,
    ) -> None:
        self._short = int(short_window)
        self._long = int(long_window)
        self._threshold = float(inversion_threshold)

    def compute(self, closes: list[float] | None) -> float:
        """Compute the RV-term-structure brake for one ticker's close window.

        Returns a float in [-1, 0]. Returns 0.0 (never NaN) on any degenerate or
        missing input: fewer than ``long_window + 1`` closes, all-equal,
        non-finite, zero/negative price, or zero long-window vol.
        """
        try:
            short, long_ = self._short, self._long
            x = self._threshold
            if short <= 0 or long_ <= 0 or short >= long_ or x <= 0.0:
                return 0.0
            # Need `long_` returns ⇒ long_ + 1 closes.
            if not closes or len(closes) < long_ + 1:
                return 0.0
            seq = [float(c) for c in closes]
            for c in seq:
                if not math.isfinite(c):
                    return 0.0
            if max(seq) == min(seq):
                # Flat window: no realized vol ⇒ no inversion. V221 degenerate-
                # variance fence (never let a constant series amplify residue).
                return 0.0

            # --- Log returns over the whole window (fixed oldest-first order) ---
            sq_returns: list[float] = []
            for i in range(1, len(seq)):
                prev = seq[i - 1]
                if prev <= 0.0:
                    # Non-positive price → undefined log return; skip this step.
                    # (A skipped step shortens the realized-vol windows below; the
                    # length guard already required enough closes, and a sub-window
                    # too short to fill returns 0.0 via the len checks below.)
                    continue
                r = math.log(seq[i] / prev)
                sq_returns.append(r * r)

            if len(sq_returns) < long_:
                return 0.0

            # --- Realized vol on the two trailing windows (fsum, fixed order) ---
            short_seg = sq_returns[-short:]
            long_seg = sq_returns[-long_:]
            rv_short = math.sqrt(math.fsum(short_seg) / short)
            rv_long = math.sqrt(math.fsum(long_seg) / long_)
            if rv_long <= 0.0:
                return 0.0

            # --- Term-structure ratio → proportional one-sided brake ---
            ratio = rv_short / rv_long
            brake = (ratio - x) / x
            brake = 0.0 if brake < 0.0 else (1.0 if brake > 1.0 else brake)
            return -brake
        except Exception as exc:
            logger.debug("rv_term_structure compute failed: %s", exc)
            return 0.0
