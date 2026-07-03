"""
omega.nodes.victoria.signal_correlation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Rolling signal correlation monitor.

Maintains a 50-trade rolling window of per-signal values (averaged across
all tickers each cycle) and computes the pairwise Pearson correlation matrix
every N cycles.

Anomaly detection:
  - High correlation (>0.8): signals are redundant → fewer independent bets
  - Unexpected negative correlation (<-0.8): possible sign bug in one signal

Written to: /tmp/{version}_signal_correlation.json on each update.
The Go API reads this file for GET /api/v1/signals/correlation?version=vN.
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signal_correlation")

# The canonical set of signals to track in the correlation matrix.
# Subset of _DIRECTIONAL_SIGNAL_KEYS — only per-cycle numeric signals,
# excluding market-level ones that are constant across tickers each cycle
# (fear_greed, dxy, vix, yield_curve, spy are the same for all tickers so
# their cross-ticker std is zero; we still include them for the time-series).
TRACKED_SIGNALS = [
    "rsi_signal",
    "macd_crossover",
    "bb_signal",
    "zscore_signal",
    "sma_crossover",
    "volume_signal",
    "btc_beta_signal",
    "funding_rate_signal",
    "fear_greed_signal",
    "dxy_signal",
    "vix_signal",
    "yield_curve_signal",
    "spy_signal",
    "ricci_curvature_signal",
    "ollivier_ricci_signal",
]

# How often to recompute the matrix (every N updates / cycles)
RECOMPUTE_EVERY: int = 10

# Thresholds for anomaly detection
HIGH_CORR_THRESHOLD: float = 0.80
LOW_CORR_THRESHOLD: float = -0.80

# Rolling window size (trades / cycles)
WINDOW_SIZE: int = 50


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 if std is zero."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return 0.0
    return num / (dx * dy)


class SignalCorrelationMonitor:
    """Rolling pairwise signal correlation tracker.

    Call update(cycle, signals) each cycle. The matrix is recomputed every
    RECOMPUTE_EVERY updates. Anomalies are returned from update().
    """

    def __init__(
        self,
        window: int = WINDOW_SIZE,
        recompute_every: int = RECOMPUTE_EVERY,
        high_threshold: float = HIGH_CORR_THRESHOLD,
        low_threshold: float = LOW_CORR_THRESHOLD,
    ) -> None:
        self._window = window
        self._recompute_every = recompute_every
        self._high_threshold = high_threshold
        self._low_threshold = low_threshold

        # Rolling window: deque of per-cycle dicts {signal_name: mean_value}
        self._history: deque[dict[str, float]] = deque(maxlen=window)

        # Current correlation matrix result
        self._matrix: dict[str, Any] = {}
        self._n_updates: int = 0

    # ── Public API ─────────────────────────────────────────────────────────

    def update(self, cycle: int, signals: dict) -> list[str]:
        """Add one cycle's signal snapshot and detect anomalies.

        Args:
            cycle: Current training cycle number.
            signals: Full signals dict from strategy (includes per-ticker dicts
                     and basket-level _* metadata keys).

        Returns:
            List of anomaly warning strings (empty if all normal).
        """
        # Aggregate per-signal values across tickers (mean)
        signal_sums: dict[str, float] = {s: 0.0 for s in TRACKED_SIGNALS}
        signal_counts: dict[str, int] = {s: 0 for s in TRACKED_SIGNALS}

        for ticker, sig in signals.items():
            if ticker.startswith("_") or ticker.startswith("adv_") or not isinstance(sig, dict):
                continue
            for s in TRACKED_SIGNALS:
                v = sig.get(s)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if not (math.isnan(fv) or math.isinf(fv)):
                    signal_sums[s] += fv
                    signal_counts[s] += 1

        snapshot = {
            s: signal_sums[s] / signal_counts[s] for s in TRACKED_SIGNALS if signal_counts[s] > 0
        }
        self._history.append(snapshot)
        self._n_updates += 1

        # Recompute matrix every N updates
        anomalies: list[str] = []
        if self._n_updates % self._recompute_every == 0 and len(self._history) >= 5:
            matrix_data, anomalies = self._compute_matrix(cycle)
            self._matrix = matrix_data

            if anomalies:
                for msg in anomalies:
                    logger.warning("Signal correlation anomaly (cycle %d): %s", cycle, msg)

        return anomalies

    def get_matrix(self) -> dict[str, Any]:
        """Return the most recent correlation matrix result.

        Structure:
          {
            "signals": ["rsi_signal", ...],
            "matrix": [[1.0, 0.3, ...], ...],     # row i, col j = corr(i, j)
            "n_observations": 47,
            "high_corr_pairs": [["rsi_signal", "macd_crossover", 0.85], ...],
            "low_corr_pairs": [["vol_signal", "rsi_signal", -0.82], ...],
            "cycle": 150,
          }
        """
        return self._matrix

    def save(self, version: str, output_dir: str = "/tmp") -> None:
        """Write the current matrix to /tmp/{version}_signal_correlation.json.

        NOTE: the /tmp location is load-bearing — the Go API serves this file for
        GET /api/v1/signals/correlation and expects it at /tmp/{version}_*.json.
        Do NOT redirect via OMEGA_AUDIT_OUTPUT_DIR without also updating the Go
        reader. Disk risk is negligible: single small JSON, feature-gated off in
        grid runs (V235 tmp-redirect audit).
        """
        if not self._matrix:
            return
        path = Path(output_dir) / f"{version}_signal_correlation.json"
        try:
            with open(path, "w") as f:
                json.dump(self._matrix, f)
        except Exception as exc:
            logger.warning("SignalCorrelationMonitor.save failed: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────

    def _compute_matrix(self, cycle: int) -> tuple[dict[str, Any], list[str]]:
        """Compute pairwise Pearson correlation matrix from the rolling window."""
        # Build time-series arrays for each signal
        history_list = list(self._history)
        n = len(history_list)

        # Only include signals present in at least 50% of observations
        active_signals = [
            s for s in TRACKED_SIGNALS if sum(1 for obs in history_list if s in obs) >= n * 0.5
        ]

        if len(active_signals) < 2:
            return {}, []

        # Build arrays — use 0.0 for missing observations (neutral)
        series: dict[str, list[float]] = {
            s: [obs.get(s, 0.0) for obs in history_list] for s in active_signals
        }

        # Compute lower-triangular pairwise correlations
        ns = len(active_signals)
        matrix: list[list[float]] = [[0.0] * ns for _ in range(ns)]
        high_corr_pairs: list[list] = []
        low_corr_pairs: list[list] = []

        for i in range(ns):
            matrix[i][i] = 1.0
            for j in range(i + 1, ns):
                r = _pearson(series[active_signals[i]], series[active_signals[j]])
                r = round(r, 4)
                matrix[i][j] = r
                matrix[j][i] = r

                if r > self._high_threshold:
                    high_corr_pairs.append([active_signals[i], active_signals[j], r])
                elif r < self._low_threshold:
                    low_corr_pairs.append([active_signals[i], active_signals[j], r])

        # Generate anomaly strings
        anomalies: list[str] = []
        for sig_a, sig_b, r in high_corr_pairs:
            anomalies.append(
                f"HIGH CORRELATION ({r:.2f}): {sig_a} ↔ {sig_b} — "
                "signals are redundant, effectively fewer independent bets"
            )
        for sig_a, sig_b, r in low_corr_pairs:
            anomalies.append(
                f"UNEXPECTED NEGATIVE CORRELATION ({r:.2f}): {sig_a} ↔ {sig_b} — "
                "possible sign bug or structural regime shift"
            )

        return {
            "signals": active_signals,
            "matrix": matrix,
            "n_observations": n,
            "high_corr_pairs": high_corr_pairs,
            "low_corr_pairs": low_corr_pairs,
            "cycle": cycle,
        }, anomalies
