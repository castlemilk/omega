"""
omega.nodes.victoria.dynamic_weights
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dynamic signal weighting using recent Information Coefficient performance.

DynamicWeightAllocator:
  - Adjusts signal weights based on exponential moving average of IC
  - Regime-aware: maintains separate weight profiles per market regime
  - Risk parity constraint: no single signal can exceed 40% weight
  - Graceful fallback to equal weights when IC data is insufficient
"""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from omega.nodes.victoria.natural_gradient import NaturalGradientOptimizer

logger = logging.getLogger("omega.nodes.victoria.dynamic_weights")

MAX_SINGLE_WEIGHT = 0.40  # risk parity cap
EMA_ALPHA = 0.3  # smoothing factor for IC EMA (higher = more reactive)
MIN_IC_SAMPLES = 5  # minimum samples before trusting IC
KNOWN_REGIMES = ["trending", "ranging", "high_vol", "low_vol", "crisis", "default"]


@dataclass
class WeightProfile:
    """Weight allocation for a set of signals in a given regime."""

    regime: str
    weights: dict[str, float]  # signal_name → weight (sum to 1.0)
    ic_ema: dict[str, float]  # exponential moving average of IC per signal
    sample_counts: dict[str, int]  # how many IC observations per signal
    last_updated: int = 0  # bar index of last update


@dataclass
class AllocationResult:
    """Output of a weight allocation call."""

    weights: dict[str, float]
    regime: str
    is_fallback: bool  # True if fell back to equal weights
    dominant_signal: str  # signal with highest weight
    capped_signals: list[str]  # signals that hit the 40% cap
    ic_ema: dict[str, float] = None  # type: ignore[assignment]  # IC EMA per signal


class DynamicWeightAllocator:
    """
    Adjusts signal weights based on exponential moving average of IC.

    Usage::
        allocator = DynamicWeightAllocator(["signal_a", "signal_b", "signal_c"])
        allocator.update_ic("signal_a", ic_value=0.12, regime="trending")
        result = allocator.allocate(regime="trending")
        weights = result.weights  # {"signal_a": 0.40, "signal_b": 0.35, ...}
    """

    def __init__(
        self,
        signal_names: list[str],
        ema_alpha: float = EMA_ALPHA,
        use_natural_gradient: bool = False,
        ng_learning_rate: float = 0.01,
    ) -> None:
        self._signals = list(signal_names)
        self._ema_alpha = ema_alpha
        self._profiles: dict[str, WeightProfile] = {}
        self._bar = 0
        self._use_natural_gradient = use_natural_gradient

        # One NaturalGradientOptimizer per regime (statistically independent)
        self._ng_optimizers: dict[str, NaturalGradientOptimizer] = {}
        if use_natural_gradient:
            for regime in KNOWN_REGIMES:
                self._ng_optimizers[regime] = NaturalGradientOptimizer(
                    n_signals=len(signal_names),
                    learning_rate=ng_learning_rate,
                )

        # Initialize a weight profile for each known regime + default
        for regime in KNOWN_REGIMES:
            self._profiles[regime] = WeightProfile(
                regime=regime,
                weights=self._equal_weights(),
                ic_ema={s: 0.0 for s in self._signals},
                sample_counts={s: 0 for s in self._signals},
            )

    # ------------------------------------------------------------------ public API

    def update_ic(self, signal_name: str, ic_value: float, regime: str = "default") -> None:
        """
        Record a new IC observation for a signal in the given regime.

        Updates the EMA of IC for that signal, then recomputes weights.
        """
        if signal_name not in self._signals:
            logger.warning("Unknown signal '%s'; ignoring IC update", signal_name)
            return

        regime = self._normalize_regime(regime)
        profile = self._profiles[regime]

        old_ema = profile.ic_ema[signal_name]
        n = profile.sample_counts[signal_name]

        if n == 0:
            # First observation: use raw IC
            new_ema = ic_value
        else:
            # EMA update: newer obs weighted by alpha
            new_ema = self._ema_alpha * ic_value + (1 - self._ema_alpha) * old_ema

        profile.ic_ema[signal_name] = new_ema
        profile.sample_counts[signal_name] = n + 1

        # Recompute weights for this regime
        profile.weights = self._compute_weights(profile)

        # Weight decay: pull weights toward equal after each IC update to prevent
        # any single signal dominating through IC drift
        n_signals = len(self._signals)
        if n_signals > 0:
            equal_w = 1.0 / n_signals
            profile.weights = {s: 0.95 * w + 0.05 * equal_w for s, w in profile.weights.items()}
            # Re-normalize after decay
            total = sum(profile.weights.values())
            if total > 0:
                profile.weights = {s: w / total for s, w in profile.weights.items()}

        profile.last_updated = self._bar
        self._bar += 1

        logger.debug(
            "IC update — signal=%s regime=%s ic=%.4f ema=%.4f → weight=%.3f",
            signal_name,
            regime,
            ic_value,
            new_ema,
            profile.weights.get(signal_name, 0),
        )

    def update_ic_batch(self, ic_updates: dict[str, float], regime: str = "default") -> None:
        """Update IC for multiple signals at once."""
        for signal_name, ic_value in ic_updates.items():
            self.update_ic(signal_name, ic_value, regime)

    def update_ng(
        self,
        signal_values: dict[str, float],
        forward_return: float,
        regime: str = "default",
    ) -> None:
        """
        Update signal weights via natural gradient using a full signal vector
        and the realised forward return.

        This is the geometry-aware alternative to ``update_ic``.  The Fisher
        information matrix is estimated from the rolling history of signal
        vectors and returns; weights are updated along the natural gradient
        direction rather than the flat EMA path.

        Args:
            signal_values:  {signal_name: value} for the current bar.
            forward_return: Realised return for this bar (used as the target).
            regime:         Current market regime.
        """
        if not self._use_natural_gradient:
            raise RuntimeError(
                "update_ng requires use_natural_gradient=True; "
                "pass use_natural_gradient=True to DynamicWeightAllocator.__init__."
            )

        regime = self._normalize_regime(regime)
        optimizer = self._ng_optimizers[regime]
        profile = self._profiles[regime]

        # Build signal array in canonical signal order
        sv = np.array([signal_values.get(s, 0.0) for s in self._signals], dtype=float)

        # Natural gradient step → returns updated weight array
        new_weights_arr = optimizer.update(sv, forward_return)

        # Write back into the WeightProfile (dict form)
        new_weights = dict(zip(self._signals, new_weights_arr.tolist(), strict=False))

        # Apply the same 40% risk parity cap used by the EMA path
        new_weights = self._apply_cap(new_weights)

        # Update sample counts so allocate() does not fall back to equal weights
        for s in self._signals:
            if signal_values.get(s, 0.0) != 0.0:
                profile.sample_counts[s] = profile.sample_counts.get(s, 0) + 1

        profile.weights = new_weights
        profile.last_updated = self._bar
        self._bar += 1

        logger.debug(
            "NG update — regime=%s return=%.5f weights=%s",
            regime,
            forward_return,
            {s: round(w, 4) for s, w in new_weights.items()},
        )

    def seed_priors(
        self,
        priors: dict[str, float],
        n_samples: int = MIN_IC_SAMPLES,
    ) -> None:
        """
        Seed initial IC EMA values based on prior knowledge of signal quality.

        Bypasses the MIN_IC_SAMPLES warmup so the allocator starts with
        informed weights rather than equal weights from cycle 1.

        Args:
            priors  : {signal_name: ic_value} — higher value = better predictor.
                      Typical range 0.04-0.20 (crypto IC values).
            n_samples: Fake sample count assigned per signal; must be >= MIN_IC_SAMPLES
                       to satisfy the eligibility check in _compute_weights().
        """
        n = max(n_samples, MIN_IC_SAMPLES)
        for regime in KNOWN_REGIMES:
            profile = self._profiles[regime]
            updated = False
            for signal_name, ic_value in priors.items():
                if signal_name not in self._signals:
                    logger.debug("seed_priors: unknown signal '%s', skipping", signal_name)
                    continue
                profile.ic_ema[signal_name] = float(ic_value)
                # Only seed if the signal hasn't accumulated real observations yet
                if profile.sample_counts.get(signal_name, 0) < n:
                    profile.sample_counts[signal_name] = n
                updated = True
            if updated:
                profile.weights = self._compute_weights(profile)
        logger.debug(
            "seed_priors: seeded %d signals across %d regimes",
            len(priors),
            len(KNOWN_REGIMES),
        )

    def allocate(self, regime: str = "default") -> AllocationResult:
        """
        Return the current weight allocation for the given regime.

        Falls back to equal weights if insufficient IC data.
        """
        regime = self._normalize_regime(regime)
        profile = self._profiles[regime]

        # Check if we have enough data; fall back to equal if not
        min_samples = min(profile.sample_counts.get(s, 0) for s in self._signals)
        is_fallback = min_samples < MIN_IC_SAMPLES

        if is_fallback:
            weights = self._equal_weights()
        else:
            weights = dict(profile.weights)

        # Find dominant and capped signals
        dominant = max(weights, key=lambda s: weights[s])
        capped = [s for s in self._signals if abs(weights.get(s, 0) - MAX_SINGLE_WEIGHT) < 1e-6]

        return AllocationResult(
            weights=weights,
            regime=regime,
            is_fallback=is_fallback,
            dominant_signal=dominant,
            capped_signals=capped,
            ic_ema=dict(profile.ic_ema),
        )

    def blend_signals(
        self,
        signal_values: dict[str, float],
        regime: str = "default",
    ) -> float:
        """
        Compute the weighted composite signal value.

        Args:
            signal_values: {signal_name: value} where value ∈ [-1, 1]
            regime: current market regime

        Returns:
            Weighted composite signal ∈ [-1, 1]
        """
        result = self.allocate(regime)
        weights = result.weights

        total = 0.0
        weight_used = 0.0
        for signal_name, value in signal_values.items():
            w = weights.get(signal_name, 0.0)
            total += value * w
            weight_used += w

        # Normalize for missing signals
        if weight_used > 0:
            total = total / weight_used

        return max(-1.0, min(1.0, total))

    def get_profile(self, regime: str = "default") -> dict[str, Any]:
        """Return a serializable snapshot of the weight profile for a regime."""
        regime = self._normalize_regime(regime)
        profile = self._profiles[regime]
        info: dict[str, Any] = {
            "regime": regime,
            "weights": dict(profile.weights),
            "ic_ema": dict(profile.ic_ema),
            "sample_counts": dict(profile.sample_counts),
            "last_updated_bar": profile.last_updated,
            "is_data_sufficient": all(
                profile.sample_counts.get(s, 0) >= MIN_IC_SAMPLES for s in self._signals
            ),
            "optimizer": "natural_gradient" if self._use_natural_gradient else "ema",
        }
        return info

    def get_all_profiles(self) -> dict[str, dict[str, Any]]:
        return {regime: self.get_profile(regime) for regime in self._profiles}

    def apply_rmt_adjustment(
        self,
        quality_scores: dict[str, float],
        regime: str = "default",
    ) -> None:
        """
        Nudge IC EMAs using RMT-derived signal quality scores.

        Signals with high RMT quality (large participation in above-MP
        eigenmodes) have their IC EMA boosted; noise-dominated signals are
        attenuated.  The adjustment is mild (max ±20%) so it supplements
        rather than overrides the empirical IC history.

        Parameters
        ----------
        quality_scores : dict
            {signal_name: score ∈ [0, 1]} from RMTDenoiser.signal_quality_scores().
        regime : str
            Which regime profile to update.
        """
        if not quality_scores:
            return

        regime = self._normalize_regime(regime)
        profile = self._profiles[regime]

        for name, score in quality_scores.items():
            if name not in self._signals:
                continue
            if profile.sample_counts.get(name, 0) < MIN_IC_SAMPLES:
                continue  # don't adjust before enough real IC observations

            # score is normalised to [0, 1]; centre around 0.5 → adjustment ∈ [-0.1, 0.1]
            adjustment = (score - 0.5) * 0.2
            old_ema = profile.ic_ema[name]
            profile.ic_ema[name] = old_ema * (1.0 + adjustment)

        # Recompute weights after EMA nudge
        profile.weights = self._compute_weights(profile)
        logger.debug(
            "RMT IC adjustment applied for regime=%s signals=%d", regime, len(quality_scores)
        )

    def apply_news_prior(
        self,
        signal_multipliers: dict[str, float],
        strength: float = 1.0,
        regime: str = "default",
    ) -> None:
        """
        Apply news-projection multipliers as a soft prior on IC EMAs.

        The news-projection layer provides per-signal relevance multipliers
        based on the current news/sentiment context.  This method nudges IC
        EMAs by ``(multiplier - 1.0) * strength * max_adjustment`` so that
        signals more relevant to today's news get a temporary weight boost.

        The adjustment is intentionally mild (max ±15% of current IC EMA)
        so that it never overrides the empirical IC history — it only provides
        directional guidance when the empirical data is sparse or neutral.

        Parameters
        ----------
        signal_multipliers : dict
            {signal_name: multiplier} from NewsProjectionResult.signal_multipliers.
            Values near 1.0 = neutral; > 1.0 = boost; < 1.0 = attenuate.
        strength : float
            News informativeness score [0, 1] from NewsProjectionResult.news_strength.
            Scales the adjustment so low-confidence news has less impact.
        regime : str
            Which regime profile to update.
        """
        if not signal_multipliers or strength < 0.05:
            return

        regime = self._normalize_regime(regime)
        profile = self._profiles[regime]
        _max_adj = 0.15  # max ±15% IC EMA adjustment per cycle

        updated = 0
        for name, multiplier in signal_multipliers.items():
            if name not in self._signals:
                continue
            if profile.sample_counts.get(name, 0) < MIN_IC_SAMPLES:
                continue  # only adjust after enough real IC observations

            deviation = multiplier - 1.0  # range ≈ [-0.30, +0.30]
            adjustment = deviation * strength * _max_adj
            old_ema = profile.ic_ema[name]
            profile.ic_ema[name] = old_ema * (1.0 + adjustment)
            updated += 1

        if updated > 0:
            profile.weights = self._compute_weights(profile)
            logger.debug(
                "news_prior applied: regime=%s signals_adjusted=%d strength=%.3f",
                regime,
                updated,
                strength,
            )

    # ------------------------------------------------------------------ weight computation

    def _compute_weights(self, profile: WeightProfile) -> dict[str, float]:
        """
        Compute signal weights proportional to abs(IC EMA).

        Steps:
          1. Use abs(IC EMA) as raw weight (positive IC = useful, negative IC = contrarian)
          2. Normalize to sum to 1.0
          3. Apply 40% risk parity cap (iteratively redistribute excess)
          4. Re-normalize
        """
        ic_emas = profile.ic_ema
        sample_counts = profile.sample_counts

        # Only include signals with enough observations
        eligible = {
            s: abs(ic_emas[s]) for s in self._signals if sample_counts.get(s, 0) >= MIN_IC_SAMPLES
        }

        if not eligible:
            return self._equal_weights()

        total_ic = sum(eligible.values())
        if total_ic == 0:
            return self._equal_weights()

        # Initial proportional weights
        raw_weights = {s: ic / total_ic for s, ic in eligible.items()}

        # Add zero weights for signals without data
        for s in self._signals:
            if s not in raw_weights:
                raw_weights[s] = 0.0

        # Apply cap with redistribution
        weights = self._apply_cap(raw_weights)
        return weights

    def _apply_cap(self, weights: dict[str, float]) -> dict[str, float]:
        """
        Iteratively redistribute excess weight from capped signals to uncapped ones.
        """
        weights = dict(weights)
        max_iters = 20

        for _ in range(max_iters):
            capped = {s: w for s, w in weights.items() if w > MAX_SINGLE_WEIGHT}
            if not capped:
                break

            excess = sum(w - MAX_SINGLE_WEIGHT for w in capped.values())
            uncapped = {s: w for s, w in weights.items() if w <= MAX_SINGLE_WEIGHT}

            # Cap capped signals
            for s in capped:
                weights[s] = MAX_SINGLE_WEIGHT

            # Redistribute excess proportionally to uncapped
            if not uncapped:
                break
            uncapped_total = sum(uncapped.values())
            if uncapped_total == 0:
                # Distribute evenly
                per_signal = excess / len(uncapped)
                for s in uncapped:
                    weights[s] += per_signal
            else:
                for s, w in uncapped.items():
                    weights[s] += excess * (w / uncapped_total)

        # Final normalize to ensure sum = 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {s: w / total for s, w in weights.items()}

        return weights

    def _equal_weights(self) -> dict[str, float]:
        n = len(self._signals)
        if n == 0:
            return {}
        w = 1.0 / n
        return {s: w for s in self._signals}

    def _normalize_regime(self, regime: str) -> str:
        """Map unknown regimes to 'default'."""
        return regime if regime in self._profiles else "default"


# ---------------------------------------------------------------------------
# RegimeAwareWeightManager — manages allocators per asset universe
# ---------------------------------------------------------------------------


class RegimeAwareWeightManager:
    """
    Manages per-ticker weight allocators with shared regime signals.

    This allows each asset to have its own IC history while sharing
    the same regime detection, reducing regime-estimation noise.

    Usage::
        manager = RegimeAwareWeightManager(
            signal_names=["order_flow", "cross_asset", "microstructure", "sentiment"],
        )
        manager.record_ic("BTCUSDT", "order_flow", ic=0.15, regime="trending")
        result = manager.compute_composite("BTCUSDT", signal_values, regime="trending")
    """

    def __init__(self, signal_names: list[str]) -> None:
        self._signal_names = list(signal_names)
        self._allocators: dict[str, DynamicWeightAllocator] = {}
        # Shared global allocator as prior
        self._global = DynamicWeightAllocator(signal_names)

    def _get_allocator(self, ticker: str) -> DynamicWeightAllocator:
        if ticker not in self._allocators:
            self._allocators[ticker] = DynamicWeightAllocator(self._signal_names)
        return self._allocators[ticker]

    def record_ic(self, ticker: str, signal_name: str, ic: float, regime: str = "default") -> None:
        """Record IC for a specific ticker + signal + regime."""
        self._get_allocator(ticker).update_ic(signal_name, ic, regime)
        # Also update global prior
        self._global.update_ic(signal_name, ic * 0.3, regime)  # shrunk toward mean

    def compute_composite(
        self,
        ticker: str,
        signal_values: dict[str, float],
        regime: str = "default",
    ) -> dict[str, Any]:
        """
        Compute the composite signal for a ticker.

        If the ticker-specific allocator has insufficient data,
        blends with the global allocator.
        """
        alloc = self._get_allocator(ticker)
        result = alloc.allocate(regime)

        if result.is_fallback:
            # Blend 50/50 with global allocator
            global_result = self._global.allocate(regime)
            blended_weights: dict[str, float] = {}
            for s in self._signal_names:
                blended_weights[s] = 0.5 * result.weights.get(
                    s, 0
                ) + 0.5 * global_result.weights.get(s, 0)
            # Normalize
            total = sum(blended_weights.values())
            if total > 0:
                blended_weights = {s: w / total for s, w in blended_weights.items()}
            weights = blended_weights
            source = "global_blended"
        else:
            weights = result.weights
            source = "ticker_specific"

        composite = sum(
            signal_values.get(s, 0.0) * weights.get(s, 0.0) for s in self._signal_names
        )
        weight_sum = sum(weights.get(s, 0.0) for s in signal_values)
        if weight_sum > 0:
            composite = composite / weight_sum

        return {
            "composite": max(-1.0, min(1.0, composite)),
            "weights": weights,
            "regime": regime,
            "source": source,
            "dominant_signal": max(weights, key=lambda s: weights[s]),
        }

    def get_summary(self) -> dict[str, Any]:
        return {
            "tickers_tracked": list(self._allocators.keys()),
            "signals": self._signal_names,
            "global_profile": self._global.get_profile("default"),
        }
