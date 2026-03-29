"""
omega.core.sit_out_breaker
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SitOutCircuitBreaker — detects sustained vol_low sit-outs and automatically
lowers the volatility threshold so the system can trade again.

Problem it solves
-----------------
Victoria computes a vol percentile rank over a 100-bar lookback window and
sits out entirely when vol_rank < _vol_low_threshold (default 0.20).  On a
quiet Sunday — or during a broad crypto low-volatility regime — the system can
sit out every single cycle of a 500-cycle run.  The circuit breaker detects
this and halves the threshold so some trading resumes.

Behaviour
---------
* Counts consecutive cycles where sit_out_reason == "vol_low".
* At TRIP_THRESHOLD (default 30): mutates strat._vol_low_threshold to
  threshold * 0.5, emits a WARNING, and logs old/new values.
* Resets the counter on any non-vol_low cycle.
* Caps threshold reduction: will not lower below MIN_THRESHOLD (default 0.05)
  to avoid trading in genuinely broken markets.
* Restores the original threshold when the streak ends (system self-heals).

Usage
-----
    breaker = SitOutCircuitBreaker(strat)   # pass StrategyNode instance

    # inside training loop after each cycle:
    breaker.record(sit_out_reason)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("omega.core.sit_out_breaker")

TRIP_THRESHOLD: int = 30
REDUCTION_FACTOR: float = 0.5
MIN_THRESHOLD: float = 0.05


class SitOutCircuitBreaker:
    """Monitors consecutive vol_low sit-outs and adapts the threshold."""

    def __init__(
        self,
        strategy_node: Any,
        trip_threshold: int = TRIP_THRESHOLD,
        reduction_factor: float = REDUCTION_FACTOR,
        min_threshold: float = MIN_THRESHOLD,
    ) -> None:
        self._strat = strategy_node
        self._trip_threshold = trip_threshold
        self._reduction_factor = reduction_factor
        self._min_threshold = min_threshold

        self._consecutive_vol_low: int = 0
        self._tripped: bool = False
        self._original_threshold: float | None = None
        self._trip_count: int = 0  # how many times we've tripped in this run

    def record(self, sit_out_reason: str) -> None:
        """Call once per cycle with the sit_out_reason for that cycle."""
        if sit_out_reason == "vol_low":
            self._consecutive_vol_low += 1
            if self._consecutive_vol_low == self._trip_threshold:
                self._trip()
        else:
            if self._tripped:
                self._restore()
            self._consecutive_vol_low = 0

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def consecutive_vol_low(self) -> int:
        return self._consecutive_vol_low

    def _trip(self) -> None:
        if not hasattr(self._strat, "_vol_low_threshold"):
            logger.warning(
                "SitOutCircuitBreaker: strategy node has no _vol_low_threshold attribute — "
                "cannot adapt. Update StrategyNode to expose this attribute."
            )
            return

        current = self._strat._vol_low_threshold
        new_threshold = max(self._min_threshold, current * self._reduction_factor)

        if new_threshold >= current:
            logger.warning(
                "SitOutCircuitBreaker: already at minimum threshold (%.3f) — "
                "cannot lower further. Market may be genuinely illiquid.",
                current,
            )
            return

        self._original_threshold = current
        self._strat._vol_low_threshold = new_threshold
        self._tripped = True
        self._trip_count += 1

        logger.warning(
            "SIT-OUT CIRCUIT BREAKER TRIPPED (#%d): %d consecutive vol_low sit-outs. "
            "Lowering _vol_low_threshold %.3f → %.3f (%.0f%% reduction). "
            "Trading will resume when vol_rank >= %.3f.",
            self._trip_count,
            self._consecutive_vol_low,
            current,
            new_threshold,
            (1 - self._reduction_factor) * 100,
            new_threshold,
        )

    def _restore(self) -> None:
        if self._original_threshold is None:
            return
        if not hasattr(self._strat, "_vol_low_threshold"):
            return

        restored = self._original_threshold
        self._strat._vol_low_threshold = restored
        self._tripped = False
        self._original_threshold = None

        logger.info(
            "SIT-OUT CIRCUIT BREAKER RESET: vol_low streak ended. "
            "Restored _vol_low_threshold to %.3f.",
            restored,
        )
