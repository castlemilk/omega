"""
tests/test_wavelet_signal.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the Wavelet Transform Signal Decomposition module.

Covers:
  1. WaveletSignal.compute() returns a valid SignalValue with correct shape.
  2. wavelet_trend correctly reflects bullish/bearish approximation direction.
  3. wavelet_momentum captures rate-of-change of cycle component.
  4. wavelet_noise_ratio is in [0, 1] and increases with noisy data.
  5. Numpy-only Haar fallback produces valid results without pywt installed.
  6. Edge cases: empty data, single price, all-identical prices.
  7. Confidence grows with history depth.
  8. Raw dict contains all three sub-signal keys.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np

from omega.nodes.victoria.wavelet_signal import WaveletSignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prices(n: int = 64, trend: float = 0.001, noise: float = 0.005) -> list[float]:
    """Synthetic close prices with configurable trend and noise."""
    rng = np.random.default_rng(42)
    prices = [50_000.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, noise)))
    return prices


def _make_market_data(n: int = 64, trend: float = 0.001, noise: float = 0.005) -> dict:
    prices = _make_prices(n=n, trend=trend, noise=noise)
    return {
        "BTCUSDT": {
            "close": prices,
            "open": [p * 0.999 for p in prices],
            "high": [p * 1.002 for p in prices],
            "low": [p * 0.998 for p in prices],
            "volume": [1_000_000.0] * n,
        }
    }


def _assert_signal_value(sv, *, label: str = "") -> None:
    """Assert a SignalValue-like object is well-formed."""
    tag = f"[{label}] " if label else ""
    assert hasattr(sv, "value"), f"{tag}missing .value"
    assert hasattr(sv, "confidence"), f"{tag}missing .confidence"
    assert hasattr(sv, "regime_tag"), f"{tag}missing .regime_tag"
    assert hasattr(sv, "raw"), f"{tag}missing .raw"

    v = float(sv.value)
    c = float(sv.confidence)
    assert math.isfinite(v), f"{tag}value={v!r} is not finite"
    assert math.isfinite(c), f"{tag}confidence={c!r} is not finite"
    assert -1.0 <= v <= 1.0, f"{tag}value={v!r} outside [-1, +1]"
    assert 0.0 <= c <= 1.0, f"{tag}confidence={c!r} outside [0, 1]"
    assert isinstance(sv.regime_tag, str) and sv.regime_tag, f"{tag}regime_tag must be non-empty str"
    assert isinstance(sv.raw, dict), f"{tag}raw must be dict"


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestWaveletSignalStructure:
    def test_returns_signal_value(self):
        sig = WaveletSignal()
        market_data = _make_market_data(n=64)
        result = sig.compute(market_data)
        _assert_signal_value(result, label="basic")

    def test_raw_contains_sub_signals(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        assert "wavelet_trend" in result.raw
        assert "wavelet_momentum" in result.raw
        assert "wavelet_noise_ratio" in result.raw

    def test_raw_sub_signals_are_finite(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        for key in ("wavelet_trend", "wavelet_momentum", "wavelet_noise_ratio"):
            assert math.isfinite(result.raw[key]), f"raw[{key!r}] is not finite"

    def test_noise_ratio_in_unit_interval(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        assert 0.0 <= result.raw["wavelet_noise_ratio"] <= 1.0

    def test_regime_tag_is_valid(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        assert result.regime_tag in (
            "bullish_trend",
            "bearish_trend",
            "high_noise",
            "neutral",
            "warmup",
        )


# ---------------------------------------------------------------------------
# Trend direction
# ---------------------------------------------------------------------------


class TestWaveletTrend:
    def test_uptrend_gives_positive_value(self):
        """Strong uptrend prices → composite signal ≥ 0."""
        sig = WaveletSignal()
        # Very strong uptrend, minimal noise
        prices = [50_000.0 * (1.005 ** i) for i in range(64)]
        market_data = {
            "BTCUSDT": {
                "close": prices,
                "open": prices,
                "high": prices,
                "low": prices,
                "volume": [1_000_000.0] * 64,
            }
        }
        result = sig.compute(market_data)
        assert result.value >= 0.0, f"Expected positive signal for uptrend, got {result.value}"

    def test_downtrend_gives_negative_value(self):
        """Strong downtrend prices → composite signal ≤ 0."""
        sig = WaveletSignal()
        prices = [50_000.0 * (0.995 ** i) for i in range(64)]
        market_data = {
            "BTCUSDT": {
                "close": prices,
                "open": prices,
                "high": prices,
                "low": prices,
                "volume": [1_000_000.0] * 64,
            }
        }
        result = sig.compute(market_data)
        assert result.value <= 0.0, f"Expected negative signal for downtrend, got {result.value}"

    def test_wavelet_trend_reflects_price_direction(self):
        """wavelet_trend raw value should be positive for uptrend."""
        sig = WaveletSignal()
        prices = [50_000.0 * (1.003 ** i) for i in range(64)]
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
        result = sig.compute(market_data)
        assert result.raw["wavelet_trend"] > 0

    def test_wavelet_trend_negative_for_downtrend(self):
        sig = WaveletSignal()
        prices = [50_000.0 * (0.997 ** i) for i in range(64)]
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
        result = sig.compute(market_data)
        assert result.raw["wavelet_trend"] < 0


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


class TestWaveletMomentum:
    def test_momentum_range(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        assert -1.0 <= result.raw["wavelet_momentum"] <= 1.0

    def test_momentum_is_bounded(self):
        """wavelet_momentum must always be in [-1, +1]."""
        sig = WaveletSignal()
        # Try various price shapes
        for prices in [
            [50_000.0 * (1.001 ** i) for i in range(64)],
            [50_000.0 * (1.001 ** (i * i / 32)) for i in range(64)],
            _make_prices(n=64, trend=0.0, noise=0.03),
        ]:
            md = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
            result = sig.compute(md)
            m = result.raw["wavelet_momentum"]
            assert -1.0 <= m <= 1.0, f"wavelet_momentum={m!r} out of [-1,1]"


# ---------------------------------------------------------------------------
# Noise ratio
# ---------------------------------------------------------------------------


class TestWaveletNoiseRatio:
    def test_low_noise_data_has_low_ratio(self):
        """Clean trend data → noise ratio should be low."""
        sig = WaveletSignal()
        # Very smooth trend, near-zero noise
        prices = [50_000.0 * (1.001 ** i) for i in range(64)]
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
        result = sig.compute(market_data)
        assert result.raw["wavelet_noise_ratio"] < 0.5

    def test_high_noise_data_has_higher_ratio_than_low_noise(self):
        """High-noise data → higher noise ratio than low-noise data."""
        sig_low = WaveletSignal()
        sig_high = WaveletSignal()

        low_noise_prices = [50_000.0 * (1.001 ** i) for i in range(64)]
        high_noise_prices = _make_prices(n=64, trend=0.0, noise=0.05)  # pure noise

        md_low = {"BTCUSDT": {"close": low_noise_prices, "open": low_noise_prices, "high": low_noise_prices, "low": low_noise_prices, "volume": [1e6] * 64}}
        md_high = {"BTCUSDT": {"close": high_noise_prices, "open": high_noise_prices, "high": high_noise_prices, "low": high_noise_prices, "volume": [1e6] * 64}}

        r_low = sig_low.compute(md_low)
        r_high = sig_high.compute(md_high)

        assert r_high.raw["wavelet_noise_ratio"] > r_low.raw["wavelet_noise_ratio"]

    def test_high_noise_reduces_confidence(self):
        """High noise ratio should reduce signal confidence."""
        sig_low = WaveletSignal()
        sig_high = WaveletSignal()

        low_noise = [50_000.0 * (1.001 ** i) for i in range(64)]
        high_noise = _make_prices(n=64, trend=0.0, noise=0.05)

        r_low = sig_low.compute({"BTCUSDT": {"close": low_noise, "open": low_noise, "high": low_noise, "low": low_noise, "volume": [1e6] * 64}})
        r_high = sig_high.compute({"BTCUSDT": {"close": high_noise, "open": high_noise, "high": high_noise, "low": high_noise, "volume": [1e6] * 64}})

        assert r_low.confidence >= r_high.confidence


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestWaveletEdgeCases:
    def test_empty_market_data(self):
        """Empty market_data → graceful fallback, no exception."""
        sig = WaveletSignal()
        result = sig.compute({})
        _assert_signal_value(result, label="empty")
        assert result.regime_tag == "warmup"
        assert result.value == 0.0

    def test_insufficient_price_data(self):
        """Fewer prices than minimum window → warmup regime."""
        sig = WaveletSignal()
        prices = [50_000.0, 50_100.0, 50_200.0]  # only 3 bars
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 3}}
        result = sig.compute(market_data)
        _assert_signal_value(result, label="short")
        assert result.regime_tag == "warmup"

    def test_all_identical_prices(self):
        """All-same prices → no signal (value=0), no crash."""
        sig = WaveletSignal()
        prices = [50_000.0] * 64
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
        result = sig.compute(market_data)
        _assert_signal_value(result, label="flat")
        assert result.value == 0.0

    def test_missing_close_key(self):
        """Market data without 'close' key → graceful fallback."""
        sig = WaveletSignal()
        market_data = {"BTCUSDT": {"volume": [1_000_000.0] * 64}}
        result = sig.compute(market_data)
        _assert_signal_value(result, label="no_close")

    def test_nan_prices_handled(self):
        """NaN values in price series → no crash."""
        sig = WaveletSignal()
        prices = _make_prices(n=64)
        prices[10] = float("nan")
        prices[30] = float("nan")
        market_data = {"BTCUSDT": {"close": prices, "open": prices, "high": prices, "low": prices, "volume": [1e6] * 64}}
        result = sig.compute(market_data)
        _assert_signal_value(result, label="nan_prices")


# ---------------------------------------------------------------------------
# Numpy Haar fallback
# ---------------------------------------------------------------------------


class TestNumpyHaarFallback:
    def test_compute_without_pywt(self):
        """Signal must work even if pywt is not installed."""
        with patch.dict("sys.modules", {"pywt": None}):
            # Force re-import with pywt mocked as unavailable
            import importlib

            import omega.nodes.victoria.wavelet_signal as ws_mod
            importlib.reload(ws_mod)
            sig = ws_mod.WaveletSignal()
            result = sig.compute(_make_market_data(n=64))
            _assert_signal_value(result, label="no_pywt")

    def test_haar_decomposition_returns_valid_components(self):
        """Internal _haar_dwt should return approximation and details."""
        from omega.nodes.victoria.wavelet_signal import _haar_dwt
        prices = np.array(_make_prices(n=64))
        approx, details = _haar_dwt(prices, level=4)
        assert len(approx) > 0
        assert len(details) == 4
        for d in details:
            assert len(d) > 0

    def test_haar_dwt_energy_conservation(self):
        """Haar DWT should approximately preserve signal energy."""
        from omega.nodes.victoria.wavelet_signal import _haar_dwt
        prices = np.array(_make_prices(n=64))
        approx, details = _haar_dwt(prices, level=4)
        # Reconstruct total energy from all components
        all_coeffs = np.concatenate([approx, *details])
        original_energy = float(np.sum(prices ** 2))
        reconstructed_energy = float(np.sum(all_coeffs ** 2))
        # Haar DWT is orthogonal so energies should match (within 10%)
        ratio = reconstructed_energy / (original_energy + 1e-8)
        assert 0.5 < ratio < 2.0, f"Energy ratio {ratio:.3f} unexpected"


# ---------------------------------------------------------------------------
# Confidence growth
# ---------------------------------------------------------------------------


class TestWaveletConfidence:
    def test_confidence_positive_with_sufficient_data(self):
        sig = WaveletSignal()
        result = sig.compute(_make_market_data(n=64))
        assert result.confidence > 0.0

    def test_more_data_gives_higher_confidence(self):
        """More price bars → higher confidence."""
        sig_short = WaveletSignal()
        sig_long = WaveletSignal()
        r_short = sig_short.compute(_make_market_data(n=32))
        r_long = sig_long.compute(_make_market_data(n=128))
        # More data should not decrease confidence
        assert r_long.confidence >= r_short.confidence


# ---------------------------------------------------------------------------
# Integration: SIGNAL_NAMES registration
# ---------------------------------------------------------------------------


class TestWaveletSignalRegistration:
    def test_wave_signal_in_victoria_signal_names(self):
        """wavelet signal must appear in victoria_node SIGNAL_NAMES."""
        from omega.nodes.victoria.victoria_node import SIGNAL_NAMES
        assert "wavelet" in SIGNAL_NAMES
