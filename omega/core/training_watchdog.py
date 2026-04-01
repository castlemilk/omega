"""
omega.core.training_watchdog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
WatchdogState — tracks zero-trade cycles during a training run and escalates
visibility when the system sits out for too long.

Thresholds
----------
WARN_THRESHOLD  (default 20) — logs a WARNING with sit-out reason breakdown
ERROR_THRESHOLD (default 50) — logs an ERROR with a structured gate-blocking summary

Usage
-----
    watchdog = WatchdogState()

    # inside training loop, after each cycle:
    had_trade = (len(engine.closed_trades) > last_closed)
    watchdog.record_cycle(
        had_trade=had_trade,
        sit_out_reason=sit_out_reason,    # "vol_low" / "regime_uncertain" / "normal" / …
        regime=regime,                    # string from regime detector
        conviction_failures=0,            # count of tickers that failed conviction filters
        proposals_generated=0,            # count of tickers that entered conviction filter
        ring1_pass=True,                  # did any symbol pass _passes_conviction_filters
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("omega.core.training_watchdog")

WARN_THRESHOLD: int = 20
ERROR_THRESHOLD: int = 50


@dataclass
class WatchdogState:
    """Tracks zero-trade streak and emits escalating warnings."""

    warn_threshold: int = WARN_THRESHOLD
    error_threshold: int = ERROR_THRESHOLD

    # Running counters (reset on each trade)
    consecutive_zero_trade_cycles: int = 0

    # Cumulative counters (never reset)
    total_cycles: int = 0
    total_zero_trade_cycles: int = 0
    total_trades: int = 0

    # Reason distribution (cumulative, across entire run)
    sit_out_reason_counts: dict[str, int] = field(default_factory=dict)

    # Regime distribution during zero-trade streak
    regime_distribution_streak: dict[str, int] = field(default_factory=dict)

    # Conviction gate stats (cumulative)
    conviction_failures_total: int = 0
    proposals_generated_total: int = 0

    # Ring-1 pass rate (rolling last 20 cycles)
    _ring1_results: list[bool] = field(default_factory=list)

    def record_cycle(
        self,
        *,
        had_trade: bool,
        sit_out_reason: str = "normal",
        regime: str = "unknown",
        conviction_failures: int = 0,
        proposals_generated: int = 0,
        ring1_pass: bool = True,
    ) -> None:
        """Call once per cycle. Emits warnings when thresholds are crossed."""
        self.total_cycles += 1
        self.sit_out_reason_counts[sit_out_reason] = (
            self.sit_out_reason_counts.get(sit_out_reason, 0) + 1
        )
        self.conviction_failures_total += conviction_failures
        self.proposals_generated_total += proposals_generated
        self._ring1_results.append(ring1_pass)
        if len(self._ring1_results) > 20:
            self._ring1_results.pop(0)

        if had_trade:
            self.total_trades += 1
            self.consecutive_zero_trade_cycles = 0
            self.regime_distribution_streak = {}
        else:
            self.total_zero_trade_cycles += 1
            self.consecutive_zero_trade_cycles += 1
            self.regime_distribution_streak[regime] = (
                self.regime_distribution_streak.get(regime, 0) + 1
            )
            self._maybe_escalate(sit_out_reason=sit_out_reason)

    def ring1_pass_rate(self) -> float | None:
        """Fraction of recent cycles where any symbol passed conviction filters."""
        if not self._ring1_results:
            return None
        return sum(self._ring1_results) / len(self._ring1_results)

    def conviction_filter_rate(self) -> float | None:
        """Fraction of proposals blocked by conviction filters (cumulative)."""
        if self.proposals_generated_total == 0:
            return None
        return self.conviction_failures_total / self.proposals_generated_total

    def _maybe_escalate(self, *, sit_out_reason: str) -> None:
        n = self.consecutive_zero_trade_cycles

        if n == self.warn_threshold:
            dominant_reason = max(
                self.sit_out_reason_counts, key=lambda k: self.sit_out_reason_counts.get(k, 0)
            )
            ring1_rate = self.ring1_pass_rate()
            logger.warning(
                "WATCHDOG WARNING: %d consecutive zero-trade cycles. "
                "Dominant sit-out reason: '%s' (%d times). "
                "Current regime streak: %s. "
                "Ring-1 pass rate (last 20): %s.",
                n,
                dominant_reason,
                self.sit_out_reason_counts.get(dominant_reason, 0),
                _fmt_dist(self.regime_distribution_streak),
                f"{ring1_rate:.0%}" if ring1_rate is not None else "n/a",
            )

        elif n == self.error_threshold:
            self._emit_error_summary()

        elif n > self.error_threshold and n % 25 == 0:
            # Repeat error every 25 cycles to stay visible in long runs
            self._emit_error_summary()

    def _emit_error_summary(self) -> None:
        n = self.consecutive_zero_trade_cycles
        total_run = self.total_cycles
        sit_pct = (self.total_zero_trade_cycles / total_run * 100) if total_run else 0.0
        ring1_rate = self.ring1_pass_rate()
        conv_rate = self.conviction_filter_rate()

        reasons_str = ", ".join(
            f"{r}={c}" for r, c in sorted(self.sit_out_reason_counts.items(), key=lambda x: -x[1])
        )

        logger.error(
            "WATCHDOG ERROR: %d consecutive zero-trade cycles "
            "(%.0f%% of %d total cycles have had no trades). "
            "Gate blocking summary → sit-out reasons: [%s] | "
            "regime during streak: %s | "
            "ring-1 pass rate (last 20 cycles): %s | "
            "conviction filter rate (cumulative): %s. "
            "ACTION: check vol thresholds, regime detection, and signal pipeline.",
            n,
            sit_pct,
            total_run,
            reasons_str,
            _fmt_dist(self.regime_distribution_streak),
            f"{ring1_rate:.0%}" if ring1_rate is not None else "n/a",
            f"{conv_rate:.0%}" if conv_rate is not None else "n/a",
        )


def _fmt_dist(dist: dict[str, int]) -> str:
    if not dist:
        return "{}"
    total = sum(dist.values())
    parts = [f"{k}={v}({v / total:.0%})" for k, v in sorted(dist.items(), key=lambda x: -x[1])]
    return "{" + ", ".join(parts) + "}"
