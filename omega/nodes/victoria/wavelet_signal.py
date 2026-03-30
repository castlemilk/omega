"""
omega.nodes.victoria.wavelet_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Wavelet Transform Signal Decomposition for Victoria.

Concept
-------
Discrete Wavelet Transform (DWT) decomposes a price series into multiple
timescale components simultaneously — trend (low-frequency approximation
coefficients), cycles (mid-frequency detail coefficients), and noise
(high-frequency detail coefficients).  This is analogous to the signal
processing techniques underlying RenTec's approach: different market
participants operate at different timescales, and decomposing a price series
into those timescales lets us read each layer independently.

Algorithm
---------
Given N close prices {p_t}, compute DWT at L levels using a Daubechies-4
wavelet (or Haar fallback if pywt is unavailable):

    DWT(p) → (cA_L, cD_L, cD_{L-1}, …, cD_1)

where:
  cA_L       = approximation coefficients at level L  (trend layer)
  cD_{L-1,L} = detail coefficients at levels 2-3       (cycle layer)
  cD_1       = detail coefficients at level 1           (noise layer)

Three sub-signals
-----------------
  wavelet_trend    : direction of smoothed trend
                     = tanh(mean(diff(cA_L)) * k)  ∈ [-1, +1]
  wavelet_momentum : rate of change of the cycle component
                     = tanh(mean(cD_{L-1}) * k)    ∈ [-1, +1]
  wavelet_noise_ratio : noise-to-signal ratio
                     = E[cD_1²] / (E[cA_L²] + E[cD_1²] + ε)  ∈ [0, 1]
                       High → uncertain; reduce position size.

Composite signal
----------------
  value = wavelet_trend * (1 - noise_penalty) + wavelet_momentum * 0.3

where noise_penalty = noise_ratio²  (quadratic dampening).

Confidence
----------
  confidence = (1 - noise_ratio) * min(n / MIN_SAMPLES, 1.0)

References
----------
- Mallat (1989) "A theory for multiresolution signal decomposition"
- Percival & Walden (2000) "Wavelet Methods for Time Series Analysis"
- Gençay, Selçuk & Whitcher (2001) "Introduction to Wavelets and Other
  Filtering Methods in Finance and Economics"
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.wavelet_signal")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DWT_LEVEL = 4       # default decomposition depth
_MIN_SAMPLES = 32    # minimum price bars before signal is active
_TREND_K = 8.0       # tanh scale for trend signal
_MOMENTUM_K = 10.0   # tanh scale for momentum signal
_EPS = 1e-10


# ---------------------------------------------------------------------------
# PyWavelets availability check
# ---------------------------------------------------------------------------

try:
    import pywt as _pywt  # type: ignore

    _PYWT_AVAILABLE = True
    logger.debug("pywt available — using Daubechies-4 wavelet")
except (ImportError, TypeError):
    _PYWT_AVAILABLE = False
    _pywt = None  # type: ignore
    logger.debug("pywt not available — using numpy-only Haar fallback")


# ---------------------------------------------------------------------------
# SignalValue
# ---------------------------------------------------------------------------


@dataclass
class SignalValue:
    """Standard SignalValue contract used across Victoria signal nodes."""

    value: float       # composite signal ∈ [-1, +1]
    confidence: float  # 0..1
    regime_tag: str    # "bullish_trend" | "bearish_trend" | "high_noise" | "neutral" | "warmup"
    raw: dict


# ---------------------------------------------------------------------------
# Numpy-only Haar DWT
# ---------------------------------------------------------------------------


def _haar_dwt(prices: np.ndarray, level: int) -> tuple[np.ndarray, list[np.ndarray]]:
    """
    Compute a multi-level Haar DWT without pywt.

    Returns
    -------
    approx  : approximation coefficients at ``level``
    details : list of detail coefficient arrays [cD_1, cD_2, …, cD_level]
              (level 1 = finest/noise, level N = coarsest)
    """
    signal = prices.copy().astype(float)
    details: list[np.ndarray] = []

    for _ in range(level):
        n = len(signal)
        if n < 2:
            break
        # Pad to even length
        if n % 2 != 0:
            signal = np.append(signal, signal[-1])
            n += 1

        pairs = signal.reshape(-1, 2)
        approx = (pairs[:, 0] + pairs[:, 1]) / math.sqrt(2)
        detail = (pairs[:, 0] - pairs[:, 1]) / math.sqrt(2)
        details.append(detail)
        signal = approx

    # Return details in order [cD_1, cD_2, …] (finest to coarsest)
    return signal, details


# ---------------------------------------------------------------------------
# WaveletSignal
# ---------------------------------------------------------------------------


class WaveletSignal:
    """
    Decomposes OHLCV close prices via DWT into trend, cycle, and noise
    components and produces three sub-signals plus a composite.

    Parameters
    ----------
    level      : DWT decomposition depth (default 4).
    min_samples: Minimum price bars required before producing a signal.
    """

    def __init__(self, level: int = _DWT_LEVEL, min_samples: int = _MIN_SAMPLES) -> None:
        self._level = level
        self._min_samples = min_samples

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        """
        Compute the wavelet signal from the current market data snapshot.

        Parameters
        ----------
        market_data : dict mapping ticker → OHLCV dict
                      We use BTCUSDT close prices (primary ticker).
        """
        prices = self._extract_prices(market_data)

        if prices is None or len(prices) < self._min_samples:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="warmup",
                raw={
                    "wavelet_trend": 0.0,
                    "wavelet_momentum": 0.0,
                    "wavelet_noise_ratio": 0.5,
                    "n_prices": len(prices) if prices is not None else 0,
                },
            )

        prices_arr = np.asarray(prices, dtype=float)
        # Forward-fill / interpolate any NaN values
        prices_arr = self._fill_nan(prices_arr)

        # All-flat price series → no signal
        if prices_arr.std() < _EPS:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="neutral",
                raw={
                    "wavelet_trend": 0.0,
                    "wavelet_momentum": 0.0,
                    "wavelet_noise_ratio": 0.0,
                    "n_prices": len(prices_arr),
                },
            )

        # Pad to power-of-2 length for cleaner DWT (not required but improves quality)
        prices_padded = self._pad_pow2(prices_arr)

        # Decompose
        approx, details = self._decompose(prices_padded)

        # Sub-signals
        wavelet_trend = self._compute_trend(approx)
        wavelet_momentum = self._compute_momentum(details)
        wavelet_noise_ratio = self._compute_noise_ratio(approx, details)

        # Composite signal: trend dominant, momentum adds high-freq confirmation
        noise_penalty = wavelet_noise_ratio ** 2
        composite = (
            wavelet_trend * (1.0 - noise_penalty)
            + wavelet_momentum * 0.3 * (1.0 - noise_penalty)
        )
        # Clip to [-1, +1]
        value = float(np.clip(composite, -1.0, 1.0))

        # Confidence: inverse noise × warmup factor
        warmup_factor = min(len(prices_arr) / (self._min_samples * 2.0), 1.0)
        confidence = float((1.0 - wavelet_noise_ratio) * warmup_factor)
        confidence = max(0.0, min(1.0, confidence))

        # Regime tag
        regime_tag = self._classify_regime(wavelet_trend, wavelet_noise_ratio)

        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw={
                "wavelet_trend": round(wavelet_trend, 6),
                "wavelet_momentum": round(wavelet_momentum, 6),
                "wavelet_noise_ratio": round(wavelet_noise_ratio, 6),
                "n_prices": len(prices_arr),
                "dwt_level": self._level,
                "pywt_used": _PYWT_AVAILABLE,
            },
        )

    # ------------------------------------------------------------------
    # Decomposition
    # ------------------------------------------------------------------

    def _decompose(
        self, prices: np.ndarray
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        """
        Run DWT at self._level using pywt (db4) or numpy Haar fallback.

        Returns (approx, [cD_1, cD_2, …, cD_level])
        where cD_1 is the finest (noise) detail and cD_level is coarsest.
        """
        level = min(self._level, self._max_level(len(prices)))

        if _PYWT_AVAILABLE and _pywt is not None:
            try:
                coeffs = _pywt.wavedec(prices, wavelet="db4", level=level, mode="periodization")
                approx = np.asarray(coeffs[0])
                # coeffs[1] = cD_level (coarsest detail), coeffs[-1] = cD_1 (finest)
                # Reverse so index 0 = finest
                details = [np.asarray(c) for c in reversed(coeffs[1:])]
                return approx, details
            except Exception as exc:
                logger.debug("pywt.wavedec failed (%s); falling back to Haar", exc)

        return _haar_dwt(prices, level=level)

    @staticmethod
    def _max_level(n: int) -> int:
        """Maximum sensible DWT level for signal of length n."""
        if n < 2:
            return 1
        return max(1, int(math.log2(n)) - 1)

    # ------------------------------------------------------------------
    # Sub-signal computations
    # ------------------------------------------------------------------

    def _compute_trend(self, approx: np.ndarray) -> float:
        """
        Direction of the smoothed trend from approximation coefficients.

        Uses the mean of first-differences of the approximation layer,
        normalised by the RMS amplitude, then mapped through tanh.
        """
        if len(approx) < 2:
            return 0.0
        diffs = np.diff(approx.astype(float))
        mean_diff = float(np.mean(diffs))
        rms = float(np.sqrt(np.mean(approx ** 2))) + _EPS
        normalised = mean_diff / rms
        return float(math.tanh(normalised * _TREND_K))

    def _compute_momentum(self, details: list[np.ndarray]) -> float:
        """
        Rate of change of the cycle component (detail levels 2-3).

        Higher-level detail coefficients represent cycle-length oscillations.
        We take the mean of the second half of those coefficients minus the
        mean of the first half (recent vs past cycle energy direction).
        """
        # Cycle layers: indices 1 and 2 (skipping index 0 = noise)
        cycle_layers = details[1:3] if len(details) >= 3 else details[-1:]

        cycle_energy: list[float] = []
        for layer in cycle_layers:
            arr = layer.astype(float)
            if len(arr) < 2:
                continue
            mid = len(arr) // 2
            recent = float(np.mean(arr[mid:]))
            past = float(np.mean(arr[:mid]))
            rms = float(np.sqrt(np.mean(arr ** 2))) + _EPS
            cycle_energy.append((recent - past) / rms)

        if not cycle_energy:
            return 0.0

        raw_momentum = sum(cycle_energy) / len(cycle_energy)
        return float(math.tanh(raw_momentum * _MOMENTUM_K))

    @staticmethod
    def _compute_noise_ratio(
        approx: np.ndarray, details: list[np.ndarray]
    ) -> float:
        """
        Noise-to-signal ratio.

        noise_energy = energy in finest detail layer (cD_1)
        signal_energy = energy in approx + all detail layers
        ratio = noise / (total + ε)  ∈ [0, 1]
        """
        approx_energy = float(np.sum(approx.astype(float) ** 2))
        total_energy = approx_energy
        noise_energy = 0.0

        for i, layer in enumerate(details):
            arr = layer.astype(float)
            e = float(np.sum(arr ** 2))
            total_energy += e
            if i == 0:  # finest = noise
                noise_energy = e

        if total_energy < _EPS:
            return 0.0

        return float(np.clip(noise_energy / (total_energy + _EPS), 0.0, 1.0))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_prices(market_data: dict[str, Any]) -> list[float] | None:
        """Extract close prices from market_data dict.

        Priority: BTCUSDT → first available ticker.
        """
        if not market_data:
            return None

        ticker = "BTCUSDT" if "BTCUSDT" in market_data else next(iter(market_data))
        ohlcv = market_data.get(ticker)
        if not isinstance(ohlcv, dict):
            return None

        closes = ohlcv.get("close") or ohlcv.get("adjclose")
        if not closes:
            return None

        try:
            return [float(p) for p in closes]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fill_nan(arr: np.ndarray) -> np.ndarray:
        """Forward-fill NaN values; if leading NaNs, back-fill."""
        result = arr.copy()
        # Forward fill
        for i in range(1, len(result)):
            if not math.isfinite(result[i]):
                result[i] = result[i - 1]
        # Back-fill any leading NaNs
        for i in range(len(result) - 2, -1, -1):
            if not math.isfinite(result[i]):
                result[i] = result[i + 1]
        return result

    @staticmethod
    def _pad_pow2(arr: np.ndarray) -> np.ndarray:
        """Pad array to next power-of-2 length using edge-padding."""
        n = len(arr)
        target = 1 << (n - 1).bit_length() if n > 1 else 1
        if target == n:
            return arr
        pad = target - n
        return np.pad(arr, (0, pad), mode="edge")

    @staticmethod
    def _classify_regime(trend: float, noise_ratio: float) -> str:
        if noise_ratio > 0.6:
            return "high_noise"
        if trend > 0.1:
            return "bullish_trend"
        if trend < -0.1:
            return "bearish_trend"
        return "neutral"
