"""Adaptive IC-weighted signal combiner for Victoria.

Key insight: a consistently wrong signal (IC < -0.02) is valuable —
its inverse is consistently right. We flip the sign rather than exclude.

Falls back to equal-weight when < MIN_SIGNALS have IC data.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _balanced_composite(directional: list[float]) -> float:
    """Trimmed-mean composite. Reimplemented locally to avoid circular imports."""
    if not directional:
        return 0.0
    if len(directional) < 4:
        return sum(directional) / len(directional)
    n_trim = max(1, len(directional) // 5)
    trimmed = sorted(directional)[n_trim:-n_trim]
    return sum(trimmed) / len(trimmed) if trimmed else sum(directional) / len(directional)


class AdaptiveCombiner:
    """IC-weighted adaptive composite with anti-predictive signal flipping.

    Key insight: a consistently wrong signal (IC < -0.02) is valuable —
    its inverse is consistently right. We flip the sign rather than exclude.

    Falls back to equal-weight when < MIN_SIGNALS have IC data.
    """

    # IC thresholds
    ANTI_PRED_THRESHOLD = -0.02   # below this → flip signal
    WEAK_THRESHOLD = 0.0          # below this but above anti-pred → weight = 0.1
    ACTIVE_THRESHOLD = 0.05       # above this → weight = IC / 0.05
    MIN_SIGNALS_FOR_IC = 3        # minimum signals with IC before using adaptive weights

    SIGNAL_FAMILIES = {
        "momentum": ["sma_crossover", "macd_crossover", "zscore_signal"],
        "mean_reversion": ["rsi_signal", "bb_signal"],
        "volatility": ["vol_regime_signal"],
        "sentiment": ["fear_greed_signal", "funding_rate_signal"],
        "cross_asset": ["dxy_signal", "vix_signal", "spy_signal", "yield_curve_signal"],
        "microstructure": [
            "order_book_imbalance_signal",
            "trade_flow_signal",
            "spread_zscore_signal",
            "volume_profile_signal",
            "tick_momentum_signal",
        ],
        "temporal": ["momentum_derivative", "conviction_trend", "agreement_trend"],
    }

    def compute_adaptive_weights(
        self,
        signals_dict: dict[str, float],
        decay_detector: Any,  # SignalDecayDetector | None
    ) -> dict[str, float]:
        """Compute per-signal adaptive weights based on rolling IC.

        Returns {signal_name: weight} where weight may be negative (flipped signal).
        Returns empty dict to signal fallback to equal-weight.
        """
        if decay_detector is None:
            return {}

        weights: dict[str, float] = {}
        n_with_ic = 0

        for key in self._get_signal_keys(signals_dict):
            ic = decay_detector.ic_for(key)
            if ic is None:
                weights[key] = 0.5  # neutral for unknown signals
                continue
            n_with_ic += 1
            if ic < self.ANTI_PRED_THRESHOLD:
                # Flip: apply negative weight so the signal contributes opposite direction
                logger.debug(
                    "AdaptiveCombiner: flipping anti-predictive signal '%s' (IC=%.4f)",
                    key,
                    ic,
                )
                weights[key] = -0.3  # flipped contribution
            elif ic < self.WEAK_THRESHOLD:
                weights[key] = 0.1   # downweighted but kept
            elif ic < self.ACTIVE_THRESHOLD:
                weights[key] = max(0.2, ic / self.ACTIVE_THRESHOLD)
            else:
                weights[key] = ic / self.ACTIVE_THRESHOLD  # scales above 1.0 for strong IC

        if n_with_ic < self.MIN_SIGNALS_FOR_IC:
            return {}  # signal fallback to equal-weight

        return weights

    def compute_composite(
        self,
        signals_dict: dict,
        decay_detector: Any,  # SignalDecayDetector | None
    ) -> tuple[float, str]:
        """Compute adaptive composite. Returns (composite_value, method_str).

        method_str is "adaptive_ic" when using IC weights, "equal_weight" for fallback.
        Matches interface of _ic_weighted_composite in signal_generation.py.
        """
        weights = self.compute_adaptive_weights(signals_dict, decay_detector)
        signal_keys = self._get_signal_keys(signals_dict)

        if not weights or not signal_keys:
            # Fallback: equal-weight trimmed mean
            vals = [float(signals_dict[k]) for k in signal_keys if k in signals_dict]
            return _balanced_composite(vals), "equal_weight"

        num = 0.0
        den = 0.0
        n_flipped = 0

        for key in signal_keys:
            if key not in signals_dict:
                continue
            val = float(signals_dict[key])
            w = weights.get(key, 0.5)
            if w < 0:
                n_flipped += 1
            num += val * w
            den += abs(w)

        if den == 0.0:
            vals = [float(signals_dict[k]) for k in signal_keys if k in signals_dict]
            return _balanced_composite(vals), "equal_weight"

        composite = max(-1.0, min(1.0, num / den))
        method = f"adaptive_ic(flipped={n_flipped})" if n_flipped > 0 else "adaptive_ic"
        return composite, method

    def _get_signal_keys(self, signals_dict: dict) -> list[str]:
        """Get all signal keys from the dict (ends with _signal or is sma_crossover/macd_crossover)."""
        return [
            k for k in signals_dict
            if (
                k.endswith("_signal")
                or k == "sma_crossover"
                or k == "macd_crossover"
            )
            and isinstance(signals_dict[k], (int, float))
        ]
