"""Funding-rate carry signal — extreme rate in flat market = free money.

In perpetual-future markets, the funding rate periodically pays from one
side to the other (longs → shorts when funding > 0). When funding is
extreme AND the price isn't moving fast, you can take the OPPOSITE side
of crowded positioning and collect funding as carry.

This module exposes a single feature `funding_carry_signal`:
    *  >=  1.0  → extreme positive funding → short to collect
    *  <= -1.0  → extreme negative funding → long to collect
    *   0.0     → no carry signal

Threshold is `|funding| >= rate_bps_threshold` (default 0.05% per cycle).
Returns ±1.0 (binary) — the range sub-strategy interprets the sign as a
direction override when no other range condition fires.

Inputs (per-symbol, read from signals_dict):
    funding_rate_signal — the existing funding-velocity z-scored signal
    (already sign-flipped upstream so positive z = overbought).

This is intentionally simple — the real value is putting funding in the
range vote's path when the price-based range signals are ambiguous.
"""

from __future__ import annotations

from typing import Any, Final

_DEFAULT_BPS_THRESHOLD: Final[float] = 0.50  # z-scored ≥ this counts as extreme


class FundingCarrySignal:
    """Convert funding_rate_signal (z-score) into a binary carry-direction
    feature with a configurable extremity threshold."""

    def __init__(self, bps_threshold: float = _DEFAULT_BPS_THRESHOLD) -> None:
        self._threshold = bps_threshold

    def compute(self, signals: dict[str, Any]) -> dict[str, float]:
        z = signals.get("funding_rate_signal", 0.0)
        try:
            z = float(z)
        except (TypeError, ValueError):
            z = 0.0
        if z >= self._threshold:
            return {"funding_carry_signal": 1.0}  # crowded long → short for carry
        if z <= -self._threshold:
            return {"funding_carry_signal": -1.0}  # crowded short → long for carry
        return {"funding_carry_signal": 0.0}
