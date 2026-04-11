"""
omega.nodes.victoria.anomaly_detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Simple anomaly detector for training run health.

Tracks a rolling baseline of key per-cycle metrics and fires WARNING logs
when any metric deviates >3σ from recent history. Designed to catch
regressions early — e.g. V94-style zero-streak spikes would have been
detected within 10 cycles.

Metrics tracked:
  - pnl_per_cycle: realised PnL change each cycle
  - trades_per_cycle: new trades opened each cycle
  - zero_streak: consecutive zero-trade cycles (spike → system stopped trading)
  - basket_std: cross-sectional composite std (collapse → signals converged)

Usage (in run_training.py per-cycle loop):
    detector = AnomalyDetector(version=version)
    ...
    anomalies = detector.check(
        cycle=cycle,
        pnl_delta=cycle_pnl,
        n_new_trades=new_trades_this_cycle,
        zero_streak=zero_streak,
        basket_std=basket_std,
    )
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger("omega.nodes.victoria.anomaly_detector")

# Minimum observations before we start checking (avoid false alarms at startup)
MIN_BASELINE: int = 20

# σ threshold for anomaly detection
SIGMA_THRESHOLD: float = 3.0

# Rolling window for baseline stats
BASELINE_WINDOW: int = 50


def _rolling_stats(window: deque[float]) -> tuple[float, float]:
    """Return (mean, std) of a deque. Returns (0, 0) if empty."""
    n = len(window)
    if n < 2:
        return 0.0, 0.0
    mean = sum(window) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in window) / n)
    return mean, std


@dataclass
class AnomalyEvent:
    """A single detected anomaly."""

    cycle: int
    metric: str
    value: float
    mean: float
    std: float
    sigma: float
    message: str


class AnomalyDetector:
    """Rolling 3σ anomaly detector for training run health metrics.

    All metrics use a sliding window baseline. No external state — pure Python.
    """

    def __init__(
        self,
        version: str = "",
        window: int = BASELINE_WINDOW,
        sigma_threshold: float = SIGMA_THRESHOLD,
        min_baseline: int = MIN_BASELINE,
    ) -> None:
        self._version = version
        self._window = window
        self._sigma = sigma_threshold
        self._min_baseline = min_baseline

        # Rolling windows (most-recent N observations)
        self._pnl: deque[float] = deque(maxlen=window)
        self._trades: deque[float] = deque(maxlen=window)
        self._zero_streak: deque[float] = deque(maxlen=window)
        self._basket_std: deque[float] = deque(maxlen=window)

        self._n_checks: int = 0

    # ── Public API ─────────────────────────────────────────────────────────

    def check(
        self,
        cycle: int,
        pnl_delta: float,
        n_new_trades: int,
        zero_streak: int,
        basket_std: float = 0.0,
    ) -> list[AnomalyEvent]:
        """Check current cycle metrics against rolling baseline.

        Returns a list of AnomalyEvent objects (empty if normal).
        Each event is also logged at WARNING level.

        Args:
            cycle: Current training cycle.
            pnl_delta: Change in realised PnL this cycle (positive or negative).
            n_new_trades: New trades opened this cycle.
            zero_streak: Current consecutive zero-trade cycle count.
            basket_std: Cross-sectional composite std for this cycle.
        """
        self._n_checks += 1

        anomalies: list[AnomalyEvent] = []

        if self._n_checks >= self._min_baseline:
            # Check each metric against its rolling baseline
            anomalies += self._check_metric(
                cycle,
                "pnl_per_cycle",
                pnl_delta,
                self._pnl,
                direction="both",
            )
            anomalies += self._check_metric(
                cycle,
                "trades_per_cycle",
                float(n_new_trades),
                self._trades,
                direction="both",
            )
            anomalies += self._check_metric(
                cycle,
                "zero_streak",
                float(zero_streak),
                self._zero_streak,
                direction="high",  # only alert when spike is HIGH (not low)
            )
            if basket_std > 0:
                anomalies += self._check_metric(
                    cycle,
                    "basket_std",
                    basket_std,
                    self._basket_std,
                    direction="both",
                )

        # Update baselines AFTER the check (so current observation doesn't inflate std)
        self._pnl.append(pnl_delta)
        self._trades.append(float(n_new_trades))
        self._zero_streak.append(float(zero_streak))
        if basket_std > 0:
            self._basket_std.append(basket_std)

        # Emit logs
        for evt in anomalies:
            logger.warning(
                "ANOMALY [%s] cycle=%d metric=%s value=%.3f mean=%.3f std=%.3f σ=%.1f — %s",
                self._version or "?",
                evt.cycle,
                evt.metric,
                evt.value,
                evt.mean,
                evt.std,
                evt.sigma,
                evt.message,
            )

        return anomalies

    def summary(self) -> dict:
        """Return current baseline stats for all tracked metrics."""
        pnl_mean, pnl_std = _rolling_stats(self._pnl)
        tr_mean, tr_std = _rolling_stats(self._trades)
        zs_mean, zs_std = _rolling_stats(self._zero_streak)
        bs_mean, bs_std = _rolling_stats(self._basket_std)
        return {
            "n_observations": self._n_checks,
            "pnl_per_cycle": {"mean": pnl_mean, "std": pnl_std},
            "trades_per_cycle": {"mean": tr_mean, "std": tr_std},
            "zero_streak": {"mean": zs_mean, "std": zs_std},
            "basket_std": {"mean": bs_mean, "std": bs_std},
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_metric(
        self,
        cycle: int,
        name: str,
        value: float,
        window: deque[float],
        direction: str = "both",
    ) -> list[AnomalyEvent]:
        """Check a single metric. direction: 'both' | 'high' | 'low'."""
        if len(window) < self._min_baseline:
            return []

        mean, std = _rolling_stats(window)
        if std == 0.0:
            return []

        sigma = (value - mean) / std

        fired = (
            (direction == "both" and abs(sigma) > self._sigma)
            or (direction == "high" and sigma > self._sigma)
            or (direction == "low" and sigma < -self._sigma)
        )

        if not fired:
            return []

        if name == "zero_streak" and value < 5:
            # Don't alert on zero_streak=3 when baseline is 2 — low-stakes noise
            return []

        msg = self._explain(name, value, mean, std, sigma)
        return [
            AnomalyEvent(
                cycle=cycle,
                metric=name,
                value=value,
                mean=mean,
                std=std,
                sigma=round(sigma, 2),
                message=msg,
            )
        ]

    @staticmethod
    def _explain(name: str, value: float, mean: float, std: float, sigma: float) -> str:
        direction = "spike" if sigma > 0 else "collapse"
        if name == "zero_streak":
            return (
                f"zero_streak={value:.0f} cycles is {sigma:.1f}σ above recent baseline "
                f"({mean:.1f}±{std:.1f}) — system may have stopped trading. "
                "Check regime cooldown, threshold inflation, or signal failure."
            )
        if name == "pnl_per_cycle":
            return (
                f"PnL per cycle {direction}: {value:+.2f} is {abs(sigma):.1f}σ from baseline "
                f"({mean:+.2f}±{std:.2f}). "
                + (
                    "Unusual loss — check regime or signal direction."
                    if sigma < 0
                    else "Unusually large gain — may indicate outlier trade."
                )
            )
        if name == "trades_per_cycle":
            return (
                f"Trade rate {direction}: {value:.0f} trades/cycle is {abs(sigma):.1f}σ from "
                f"baseline ({mean:.1f}±{std:.1f}). "
                + (
                    "Check threshold deflation or filter override."
                    if sigma > 0
                    else "Check threshold inflation or signal failure."
                )
            )
        if name == "basket_std":
            return (
                f"basket_std {direction}: {value:.4f} is {abs(sigma):.1f}σ from baseline "
                f"({mean:.4f}±{std:.4f}). "
                + (
                    "Signals may have converged — cs_norm inflated, HOLD cycles likely."
                    if sigma < 0
                    else "High dispersion — check for outlier ticker or data error."
                )
            )
        return f"{name}={value:.3f} is {abs(sigma):.1f}σ from baseline ({mean:.3f}±{std:.3f})"
