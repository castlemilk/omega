"""Crisis-skew signal for Victoria (V225).

An orthogonal, crisis-*leading* risk-off term derived entirely from the replay
`close` window — no external feed, no network, hermetic by construction.

## Why this exists

The existing basket (sma/rsi/macd/bb/zscore/volume/funding) is
momentum/mean-reversion: all long-biased and all *coincident-to-lagging* in a
crash — they flip bearish only after price has already broken. The crisis gate
has been negative in every version because nothing in the basket *leads* a
drawdown.

V225's brief asked for a Deribit 25-delta options-skew signal; that data is not
freely/deterministically obtainable for the snapshot windows (no historical IV;
DVOL misses 2020-Q1 and is a level not a skew), and the cross-venue funding-spread
fallback is unbuildable from the single static funding scalar the snapshots hold.
This is the honest realization: a **realized downside-semivariance skew** (a skew
of the *return distribution*) plus drawdown acceleration — both computable from
already-frozen OHLCV and both genuinely orthogonal to the spot-momentum basket.

## Definition (per ticker, over the close window)

  r_i      = ln(close[i]/close[i-1])                     # i = 1 … n-1, fixed order
  downside = fsum(r_i^2 for r_i < 0)                     # downside semivariance
  upside   = fsum(r_i^2 for r_i > 0)                     # upside semivariance
  skew     = (downside - upside) / (downside + upside)   # ∈ [-1, 1]; 0 if denom==0
  semivar  = max(0.0, skew)                              # one-sided ∈ [0, 1]
  peak     = max(close)
  accel    = clamp(0,1, ((close[-2]/peak-1) - (close[-1]/peak-1)) / 0.05)
  risk_off = clamp(0,1, fsum([0.65*semivar, 0.35*accel]))
  value    = -risk_off                                   # ∈ [-1, 0]; risk-off ⇒ NEGATIVE

One-sided (never bullish): the basket already supplies the long side. Benign tape
⇒ value ≈ 0 ⇒ no effect outside crisis (the no-harm property).

## Determinism

Every float sum is `math.fsum` over the fixed oldest-first close order; `max` is
exact. No `sum`/numpy/BLAS, no wall-clock, no network. Missing/degenerate inputs
return 0.0, never NaN.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger("omega.nodes.victoria.signals.crisis_skew")

# Drawdown-acceleration normalizer: a 5%/bar deepening saturates the term to 1.0.
_ACCEL_SCALE = 0.05
# Component weights (must sum to 1.0). Funding (component C) is dropped from the
# first cut — inert in frozen mode (static scalar). Candidate V226 add.
_W_SEMIVAR = 0.65
_W_ACCEL = 0.35


class CrisisSkewSignal:
    """Realized downside-semivariance skew + drawdown acceleration → [-1, 0].

    Stateless across cycles (reads only the window passed in), so it is immune to
    the call-count / history-length channels (V221) that bit the stateful signals.

    Usage:
        sig = CrisisSkewSignal()
        value = sig.compute(close_window)   # float in [-1, 0]
    """

    def __init__(self, accel_scale: float = _ACCEL_SCALE) -> None:
        self._accel_scale = accel_scale

    def compute(self, closes: list[float] | None) -> float:
        """Compute the crisis-skew value for one ticker's close window.

        Returns a float in [-1, 0]. Returns 0.0 (never NaN) on any degenerate or
        missing input: < 2 closes, all-equal, non-finite, zero/negative peak.
        """
        try:
            if not closes or len(closes) < 2:
                return 0.0
            # Defensive copy to a fixed-order float list; reject non-finite.
            seq = [float(c) for c in closes]
            for c in seq:
                if not math.isfinite(c):
                    return 0.0
            if max(seq) == min(seq):
                return 0.0

            # --- Component A: realized downside-semivariance skew ---
            down_sq: list[float] = []
            up_sq: list[float] = []
            for i in range(1, len(seq)):
                prev = seq[i - 1]
                if prev <= 0.0:
                    # Non-positive price → undefined log return; skip this step.
                    continue
                r = math.log(seq[i] / prev)
                if r < 0.0:
                    down_sq.append(r * r)
                elif r > 0.0:
                    up_sq.append(r * r)
            downside = math.fsum(down_sq)
            upside = math.fsum(up_sq)
            denom = downside + upside
            skew_raw = (downside - upside) / denom if denom > 0.0 else 0.0
            semivar = skew_raw if skew_raw > 0.0 else 0.0

            # --- Component B: drawdown acceleration ---
            peak = max(seq)
            if peak <= 0.0:
                accel_norm = 0.0
            else:
                dd_now = seq[-1] / peak - 1.0
                dd_prev = seq[-2] / peak - 1.0
                dd_accel = dd_prev - dd_now  # > 0 when drawdown deepening this bar
                accel_norm = dd_accel / self._accel_scale
                accel_norm = 0.0 if accel_norm < 0.0 else (1.0 if accel_norm > 1.0 else accel_norm)

            # --- Combine (fsum; fixed two-term order) ---
            risk_off = math.fsum([_W_SEMIVAR * semivar, _W_ACCEL * accel_norm])
            risk_off = 0.0 if risk_off < 0.0 else (1.0 if risk_off > 1.0 else risk_off)
            return -risk_off
        except Exception as exc:
            logger.debug("crisis_skew compute failed: %s", exc)
            return 0.0
