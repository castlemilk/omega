"""signal_memory.py — Temporal signal memory for Victoria.

Tracks per-ticker signal history across cycles and computes derivative,
persistence, crossover, and trend features for injection into signal_generation.py.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, ClassVar


class SignalMemory:
    """Tracks per-ticker signal history for temporal feature computation.

    Records the last `lookback` cycles of numeric signals per ticker. Used by
    signal_generation.py to inject temporal features (derivatives, persistence,
    crossovers, trends) into the signal dict before conviction scoring.

    Thread-safe: all history mutations are protected by a single reentrant lock.

    Args:
        lookback: Number of cycles to retain per signal per ticker. Default 20.

    Example::

        mem = SignalMemory(lookback=20)
        mem.update("BTCUSDT", {"sma_crossover": 0.4, "composite": 0.3, ...})
        features = mem.get_temporal_features("BTCUSDT")
        # {"momentum_derivative": 0.12, "funding_derivative": 0.0, ...}
    """

    # Signals tracked for temporal features, keyed by the internal signal name
    # used in self.history.  Maps to the output feature name(s).
    _TRACKED_SIGNALS: ClassVar[set[str]] = {
        "composite",
        "sma_crossover",
        "funding_rate_signal",
        "agreement_ratio",
        "vol_regime",  # string-valued; handled separately for regime_duration
    }

    def __init__(self, lookback: int = 20, improved_momentum_derivative: bool = False) -> None:
        self.lookback = lookback
        self.improved_momentum_derivative = improved_momentum_derivative
        # ticker → signal_name → deque[float]  (maxlen=lookback)
        self.history: dict[str, dict[str, deque]] = {}
        # ticker → signal_key → last EMA value (for improved_momentum_derivative)
        self._ema_deriv: dict[str, dict[str, float]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, ticker: str, signals: dict[str, Any]) -> None:
        """Record current cycle's signal values for *ticker*.

        Non-numeric values (e.g. regime strings like ``"normal"``, ``"high_vol"``)
        are stored in a separate string-typed deque under the same key so that
        :meth:`get_temporal_features` can compute ``regime_duration``.

        Args:
            ticker: Market symbol, e.g. ``"ETHUSDT"``.
            signals: Mapping of signal name → value for this cycle.
        """
        with self._lock:
            if ticker not in self.history:
                self.history[ticker] = {}

            ticker_hist = self.history[ticker]

            for k, v in signals.items():
                if k not in self._TRACKED_SIGNALS:
                    continue

                if k == "vol_regime":
                    # Store string values in a separate sub-key
                    regime_key = "_vol_regime_str"
                    if regime_key not in ticker_hist:
                        ticker_hist[regime_key] = deque(maxlen=self.lookback)
                    ticker_hist[regime_key].append(v)
                    continue

                if not isinstance(v, (int, float)):
                    # Skip non-numeric values for numeric signals
                    continue

                if k not in ticker_hist:
                    ticker_hist[k] = deque(maxlen=self.lookback)
                ticker_hist[k].append(float(v))

    def get_temporal_features(self, ticker: str, manifold_regime: str = "transitional") -> dict[str, float]:
        """Compute temporal features from stored signal history for *ticker*.

        Requires at least 3 cycles of history for any feature to be computed.
        Returns an empty dict if no history exists for *ticker* or fewer than
        3 cycles have been recorded for the primary tracked signals.

        Returns:
            Dict with keys:
                - ``momentum_derivative``  — is momentum accelerating?
                - ``funding_derivative``   — is funding rate changing?
                - ``momentum_persistence`` — consecutive positive cycles / lookback
                - ``regime_duration``      — how long in current regime [0, 1]
                - ``momentum_crossover``   — did momentum flip sign this cycle?
                - ``funding_crossover``    — did funding flip sign this cycle?
                - ``conviction_trend``     — is composite conviction strengthening?
                - ``agreement_trend``      — are signals converging or diverging?

            All values are in [-1, 1] (regime_duration in [0, 1]).
            Returns ``{}`` if fewer than 3 cycles of history exist.
        """
        with self._lock:
            if ticker not in self.history:
                return {}

            ticker_hist = self.history[ticker]

            # Need at least 3 cycles on the primary signals to be useful
            sma_hist = ticker_hist.get("sma_crossover")
            if sma_hist is None or len(sma_hist) < 3:
                return {}

            features: dict[str, float] = {}

            # --- momentum (sma_crossover) ---
            if self.improved_momentum_derivative:
                raw_deriv = self._derivative("sma_crossover", ticker)
                mom_deriv, mom_accel = self._ema_derivative(
                    "sma_crossover", ticker, raw_deriv, manifold_regime
                )
                features["momentum_derivative"] = mom_deriv
                features["momentum_acceleration"] = mom_accel
            else:
                features["momentum_derivative"] = self._derivative("sma_crossover", ticker)
            features["momentum_persistence"] = self._persistence("sma_crossover", ticker)
            features["momentum_crossover"] = self._crossover("sma_crossover", ticker)

            # --- funding rate ---
            features["funding_derivative"] = self._derivative("funding_rate_signal", ticker)
            features["funding_crossover"] = self._crossover("funding_rate_signal", ticker)

            # --- conviction / agreement ---
            features["conviction_trend"] = self._trend("composite", ticker)
            features["agreement_trend"] = self._trend("agreement_ratio", ticker)

            # --- regime duration ---
            features["regime_duration"] = self._regime_duration(ticker)

            return features

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _derivative(self, signal: str, ticker: str, window: int = 3) -> float:
        """Compute rate-of-change relative to recent mean.

        Formula: ``(current - mean_prev_window) / (|mean_prev_window| + eps)``
        Clamped to [-1, 1].

        Args:
            signal: Signal key in ``self.history[ticker]``.
            ticker: Market symbol.
            window: Number of preceding cycles to average. Default 3.

        Returns:
            Normalised derivative in [-1, 1], or 0.0 if insufficient data.
        """
        history = self.history.get(ticker, {}).get(signal)
        if not history or len(history) < 3:
            return 0.0
        current = history[-1]
        prev_mean = sum(list(history)[-4:-1]) / 3  # mean of 3 cycles before current
        denom = abs(prev_mean) + 1e-8
        return max(-1.0, min(1.0, (current - prev_mean) / denom))

    def _persistence(self, signal: str, ticker: str) -> float:
        """Count consecutive cycles sharing the same sign as the current value.

        Normalized to [-1, 1]: ``sign * count / lookback``.

        Args:
            signal: Signal key.
            ticker: Market symbol.

        Returns:
            Persistence score in [-1, 1], or 0.0 if no data.
        """
        history = list(self.history.get(ticker, {}).get(signal, []))
        if not history:
            return 0.0
        sign = 1 if history[-1] > 0 else -1
        count = 0
        for v in reversed(history[:-1]):  # look back before current
            if (1 if v > 0 else -1) == sign:
                count += 1
            else:
                break
        # Normalize: count / lookback, signed by direction
        return max(-1.0, min(1.0, sign * count / self.lookback))

    def _crossover(self, signal: str, ticker: str) -> float:
        """Detect zero-crossing between the last two cycles.

        Returns:
            1.0  — signal crossed from non-positive to positive (bullish).
            -1.0 — signal crossed from non-negative to negative (bearish).
            0.0  — no crossing or insufficient data.
        """
        history = list(self.history.get(ticker, {}).get(signal, []))
        if len(history) < 2:
            return 0.0
        prev, curr = history[-2], history[-1]
        if prev <= 0 and curr > 0:
            return 1.0  # crossed positive
        if prev >= 0 and curr < 0:
            return -1.0  # crossed negative
        return 0.0

    def _trend(self, signal: str, ticker: str) -> float:
        """Compute a normalised linear-regression slope over stored history.

        Slope is divided by ``(|y_mean| + eps) / n`` to be scale-invariant.
        Clamped to [-1, 1].

        Args:
            signal: Signal key.
            ticker: Market symbol.

        Returns:
            Normalised trend slope in [-1, 1], or 0.0 if fewer than 3 cycles.
        """
        history = list(self.history.get(ticker, {}).get(signal, []))
        n = len(history)
        if n < 3:
            return 0.0
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(history) / n
        numerator = sum((xs[i] - x_mean) * (history[i] - y_mean) for i in range(n))
        denominator = sum((xs[i] - x_mean) ** 2 for i in range(n)) + 1e-8
        slope = numerator / denominator
        # Normalize by typical signal magnitude scaled by series length
        return max(-1.0, min(1.0, slope / (abs(y_mean) + 1e-8) * n))

    def _regime_duration(self, ticker: str) -> float:
        """Count consecutive cycles in the current vol_regime.

        Returns:
            Fraction of lookback spent in current regime, in [0, 1].
            0.0 if no regime history.
        """
        regime_hist = list(self.history.get(ticker, {}).get("_vol_regime_str", []))
        if not regime_hist:
            return 0.0
        current_regime = regime_hist[-1]
        count = 0
        for r in reversed(regime_hist):
            if r == current_regime:
                count += 1
            else:
                break
        return min(1.0, count / self.lookback)

    def _ema_derivative(
        self,
        signal: str,
        ticker: str,
        raw_deriv: float,
        manifold_regime: str,
        alpha: float = 0.4,
    ) -> tuple[float, float]:
        """EMA-smoothed derivative with regime-conditional semantics.

        Returns:
            (adjusted_derivative, acceleration) both clamped to [-1, 1].
        """
        key = f"_ema_{signal}"
        if ticker not in self._ema_deriv:
            self._ema_deriv[ticker] = {}
        prev_ema = self._ema_deriv[ticker].get(key, raw_deriv)
        ema = alpha * raw_deriv + (1.0 - alpha) * prev_ema
        acceleration = max(-1.0, min(1.0, ema - prev_ema))
        self._ema_deriv[ticker][key] = ema

        if manifold_regime == "trending":
            adjusted = ema
        elif manifold_regime == "mean_reversion":
            # Crisis/bear regimes map to mean_reversion — dampen momentum signal 0.5×
            # rather than sign-flip to avoid injecting spurious directional noise.
            adjusted = ema * 0.5
        else:  # transitional
            adjusted = ema * 0.5
        return max(-1.0, min(1.0, adjusted)), acceleration

    def warm_start(self, ticker_signals_list: list[dict[str, Any]]) -> None:
        """Pre-seed signal history from replay cycles before trading begins.

        Iterates over a list of per-cycle dicts mapping ticker → signal_dict,
        calling update() for each without advancing the trading cursor.

        Args:
            ticker_signals_list: List of {ticker: {signal: value}} dicts,
                one entry per warm-up cycle.
        """
        for cycle_signals in ticker_signals_list:
            for ticker, signals in cycle_signals.items():
                if isinstance(signals, dict):
                    self.update(ticker, signals)
