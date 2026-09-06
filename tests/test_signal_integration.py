"""
tests/test_signal_integration.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for all 18+ Victoria signal types.

Each test validates:
  1. Signal accepts valid OHLCV market data without raising.
  2. Returns a SignalValue-compatible object with value, confidence, regime_tag, raw.
  3. value ∈ [-1.0, +1.0], confidence ∈ [0.0, 1.0], no NaN/inf.
  4. Graceful fallback when called with empty market data.
  5. No uncaught exceptions when external network calls fail (mocked as errors).

Network calls are mocked to raise URLError so tests are deterministic and fast.
"""

from __future__ import annotations

import math
import urllib.error
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 60, base: float = 50_000.0, trend: float = 0.001) -> dict:
    """Synthetic OHLCV data — enough bars for all signal warmup windows."""
    prices = [base * (1 + trend) ** i for i in range(n)]
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [1_000_000.0 + i * 10_000 for i in range(n)],
    }


def _make_market_data(
    tickers: list[str] | None = None,
    n: int = 60,
) -> dict[str, dict]:
    tickers = tickers or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    return {t: _make_ohlcv(n=n) for t in tickers}


_TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "ADAUSDT", "BNBUSDT"]


def _assert_signal_value(sv: Any, *, label: str = "") -> None:
    """Assert a SignalValue-like object has valid fields."""
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

    # Check raw values are finite where present
    for rk, rv in sv.raw.items():
        if isinstance(rv, float):
            assert math.isfinite(rv), f"{tag}raw[{rk!r}]={rv!r} is not finite"


def _network_error(*args, **kwargs):
    """Drop-in replacement for urllib.request.urlopen that always raises."""
    raise urllib.error.URLError("network mocked offline")


# ---------------------------------------------------------------------------
# 1. OrderFlowSignal
# ---------------------------------------------------------------------------


class TestOrderFlowSignal:
    def test_valid_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import OrderFlowSignal

        sig = OrderFlowSignal()
        md = _make_market_data()
        result = sig.compute(md)
        _assert_signal_value(result, label="order_flow")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import OrderFlowSignal

        sig = OrderFlowSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0
        assert 0.0 <= result.confidence <= 1.0

    def test_no_nan_after_repeated_calls(self) -> None:
        from omega.nodes.victoria.signals_advanced import OrderFlowSignal

        sig = OrderFlowSignal()
        md = _make_market_data()
        for _ in range(5):
            result = sig.compute(md)
        _assert_signal_value(result, label="order_flow_repeated")


# ---------------------------------------------------------------------------
# 2. CrossAssetSignal
# ---------------------------------------------------------------------------


class TestCrossAssetSignal:
    def test_valid_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import CrossAssetSignal

        sig = CrossAssetSignal()
        md = _make_market_data()
        result = sig.compute(md)
        _assert_signal_value(result, label="cross_asset")

    def test_single_ticker(self) -> None:
        from omega.nodes.victoria.signals_advanced import CrossAssetSignal

        sig = CrossAssetSignal()
        result = sig.compute({"BTCUSDT": _make_ohlcv()})
        assert -1.0 <= result.value <= 1.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import CrossAssetSignal

        sig = CrossAssetSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 3. MicrostructureSignal
# ---------------------------------------------------------------------------


class TestMicrostructureSignal:
    def test_valid_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import MicrostructureSignal

        sig = MicrostructureSignal()
        md = _make_market_data()
        result = sig.compute(md)
        _assert_signal_value(result, label="microstructure")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import MicrostructureSignal

        sig = MicrostructureSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 4. SentimentSignal
# ---------------------------------------------------------------------------


class TestSentimentSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_valid_input_offline(self, _mock) -> None:
        from omega.nodes.victoria.signals_advanced import SentimentSignal

        sig = SentimentSignal()
        md = _make_market_data()
        result = sig.compute(md)
        _assert_signal_value(result, label="sentiment")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import SentimentSignal

        sig = SentimentSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 5. LongShortRatioSignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestLongShortRatioSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.signals_advanced import LongShortRatioSignal

        sig = LongShortRatioSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="long_short_ratio")
        # When offline, confidence should be 0 (no data)
        assert result.confidence == 0.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import LongShortRatioSignal

        sig = LongShortRatioSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 6. BTCDominanceSignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestBTCDominanceSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.signals_advanced import BTCDominanceSignal

        sig = BTCDominanceSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="btc_dominance")
        assert result.confidence == 0.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import BTCDominanceSignal

        sig = BTCDominanceSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 7. OnChainSignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestOnChainSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.signals_advanced import OnChainSignal

        sig = OnChainSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="onchain")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.signals_advanced import OnChainSignal

        sig = OnChainSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 8. MarketDataSignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestMarketDataSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.market_data_signals import MarketDataSignal

        sig = MarketDataSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="market_data")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.market_data_signals import MarketDataSignal

        sig = MarketDataSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 9. PairsTradingSignal (stateful — needs repeated calls to build history)
# ---------------------------------------------------------------------------


class TestPairsTradingSignal:
    def test_valid_input_warmup(self) -> None:
        from omega.nodes.victoria.pairs_signals import PairsTradingSignal

        sig = PairsTradingSignal()
        md = _make_market_data()
        # Feed multiple cycles to build history
        for _ in range(30):
            result = sig.compute(md)
        _assert_signal_value(result, label="pairs")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.pairs_signals import PairsTradingSignal

        sig = PairsTradingSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0

    def test_single_ticker(self) -> None:
        from omega.nodes.victoria.pairs_signals import PairsTradingSignal

        sig = PairsTradingSignal()
        result = sig.compute({"BTCUSDT": _make_ohlcv()})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 10. CrossSectionalMomentumSignal (Jegadeesh-Titman)
# ---------------------------------------------------------------------------


class TestMomentumFactor:
    def test_valid_input(self) -> None:
        from omega.nodes.victoria.momentum_factor import CrossSectionalMomentumSignal

        sig = CrossSectionalMomentumSignal()
        md = _make_market_data(tickers=_TICKERS, n=60)
        result = sig.compute(md)
        _assert_signal_value(result, label="momentum_factor")

    def test_few_tickers(self) -> None:
        from omega.nodes.victoria.momentum_factor import CrossSectionalMomentumSignal

        sig = CrossSectionalMomentumSignal()
        result = sig.compute(_make_market_data(tickers=["BTCUSDT", "ETHUSDT"]))
        assert -1.0 <= result.value <= 1.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.momentum_factor import CrossSectionalMomentumSignal

        sig = CrossSectionalMomentumSignal()
        result = sig.compute({})
        assert result.value == 0.0
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# 11. TimeseriesForecastSignal (Holt + AR — stdlib only, no network)
# ---------------------------------------------------------------------------


class TestTimeseriesForecast:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_valid_input(self, _mock) -> None:
        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        sig = TimeseriesForecastSignal()
        md = _make_market_data()
        result = sig.compute(md)
        _assert_signal_value(result, label="timeseries_forecast")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        sig = TimeseriesForecastSignal()
        result = sig.compute({})
        assert result.value == 0.0
        assert result.confidence == 0.0

    def test_insufficient_bars(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        sig = TimeseriesForecastSignal()
        # Only 5 bars — below the 30-bar window requirement
        md = _make_market_data(n=5)
        result = sig.compute(md)
        assert result.value == 0.0
        assert result.confidence == 0.0

    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_repeated_calls_cache(self, _mock) -> None:
        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        sig = TimeseriesForecastSignal()
        md = _make_market_data()
        results = [sig.compute(md) for _ in range(3)]
        for r in results:
            _assert_signal_value(r, label="timeseries_cache")


# ---------------------------------------------------------------------------
# 12. AltDataSignalProvider (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestAltDataSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.alt_data_signals import AltDataSignalProvider

        sig = AltDataSignalProvider()
        # compute() takes no market data: the provider fetches its own alt-data
        # sources, which is exactly why this test patches urlopen to fail.
        result = sig.compute()
        _assert_signal_value(result, label="alt_data")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.alt_data_signals import AltDataSignalProvider

        sig = AltDataSignalProvider()
        result = sig.compute()
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 13. SpectralGraphSignal (Fiedler / Laplacian — needs historical vectors)
# ---------------------------------------------------------------------------


class TestSpectralGraphSignal:
    def test_warmup_returns_neutral(self) -> None:
        from omega.nodes.victoria.spectral_signals import SpectralGraphSignal

        sig = SpectralGraphSignal()
        # Feed 5 cycles — below min_samples
        for _ in range(5):
            signal_values = {name: 0.1 for name in [
                "basic_signals", "order_flow", "cross_asset",
                "microstructure", "sentiment", "vrp", "market_data",
                "onchain", "long_short_ratio", "btc_dominance",
            ]}
            result = sig.compute(signal_values)
        # During warmup, should return a neutral/low-confidence signal
        assert -1.0 <= result.value <= 1.0
        assert 0.0 <= result.confidence <= 1.0

    def test_produces_signal_after_warmup(self) -> None:
        from omega.nodes.victoria.spectral_signals import SpectralGraphSignal

        sig = SpectralGraphSignal()
        # Feed enough cycles (min_samples = 15)
        rng = np.random.default_rng(42)
        for _ in range(25):
            signal_values = {
                name: float(rng.uniform(-0.5, 0.5))
                for name in [
                    "basic_signals", "order_flow", "cross_asset",
                    "microstructure", "sentiment", "vrp", "market_data",
                    "onchain", "long_short_ratio", "btc_dominance",
                ]
            }
            result = sig.compute(signal_values)
        _assert_signal_value(result, label="spectral_graph")

    def test_empty_signal_values(self) -> None:
        from omega.nodes.victoria.spectral_signals import SpectralGraphSignal

        sig = SpectralGraphSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 14. FundingCarrySignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestCarrySignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.carry_signals import FundingCarrySignal

        sig = FundingCarrySignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="carry")
        assert result.confidence == 0.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.carry_signals import FundingCarrySignal

        sig = FundingCarrySignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 15. SmartMoneySignal (Binance leaderboard — always mocked)
# ---------------------------------------------------------------------------


class TestSmartMoneySignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.smart_money_signal import SmartMoneySignal

        sig = SmartMoneySignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="smart_money")
        assert result.confidence == 0.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.smart_money_signal import SmartMoneySignal

        sig = SmartMoneySignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 16. FinBertSentimentSignal (keyword-based, fetches news — mocked)
# ---------------------------------------------------------------------------


class TestFinBertSentiment:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.finbert_sentiment import FinBertSentimentSignal

        sig = FinBertSentimentSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="finbert_sentiment")

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.finbert_sentiment import FinBertSentimentSignal

        sig = FinBertSentimentSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 17. WhaleFlowSignal (fetches from internet — mocked)
# ---------------------------------------------------------------------------


class TestWhaleFlowSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.whale_signal import WhaleFlowSignal

        sig = WhaleFlowSignal()
        result = sig.compute(_make_market_data())
        _assert_signal_value(result, label="whale_flow")
        assert result.confidence == 0.0

    def test_empty_input(self) -> None:
        from omega.nodes.victoria.whale_signal import WhaleFlowSignal

        sig = WhaleFlowSignal()
        result = sig.compute({})
        assert -1.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# 18. WassersteinRegimeDetector (no network, pure math)
# ---------------------------------------------------------------------------


class TestWassersteinRegimeDetector:
    def test_warmup_fallback(self) -> None:
        from omega.nodes.victoria.wasserstein_regime import WassersteinRegimeDetector

        det = WassersteinRegimeDetector(window=50, min_samples=20)
        signal_values = {
            "basic_signals": 0.2, "order_flow": 0.1, "cross_asset": 0.15,
            "microstructure": -0.1, "sentiment": 0.3, "vrp": 0.0,
            "market_data": 0.1, "onchain": 0.05, "long_short_ratio": 0.2,
            "btc_dominance": -0.1, "alt_data": 0.0,
        }
        result = det.update(signal_values)
        # During warmup (< 20 samples) — confidence=0.0, regime="sideways"
        assert result.confidence == 0.0
        assert result.regime == "sideways"

    def test_produces_regime_after_warmup(self) -> None:
        from omega.nodes.victoria.wasserstein_regime import WassersteinRegimeDetector

        det = WassersteinRegimeDetector(window=50, min_samples=20)
        rng = np.random.default_rng(99)
        result = None
        for _ in range(30):
            sv = {
                name: float(rng.uniform(0.1, 0.5))  # consistently positive → bull
                for name in [
                    "basic_signals", "order_flow", "cross_asset",
                    "microstructure", "sentiment", "vrp", "market_data",
                    "onchain", "long_short_ratio", "btc_dominance", "alt_data",
                ]
            }
            result = det.update(sv)

        assert result is not None
        assert result.regime in ("bull", "bear", "sideways")
        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.bull_prob <= 1.0
        assert 0.0 <= result.bear_prob <= 1.0
        assert 0.0 <= result.sideways_prob <= 1.0
        total = result.bull_prob + result.bear_prob + result.sideways_prob
        assert abs(total - 1.0) < 1e-6, f"probabilities don't sum to 1: {total}"

    def test_update_centroids(self) -> None:
        from omega.nodes.victoria.wasserstein_regime import (
            BULL,
            N_SIGNALS,
            WassersteinRegimeDetector,
        )

        det = WassersteinRegimeDetector()
        labeled = {
            BULL: [[0.5] * N_SIGNALS for _ in range(15)],
        }
        det.update_centroids(labeled)
        # Centroid should move toward 0.5
        centroid = det._centroids[BULL]
        assert all(abs(c - 0.5) < 0.01 for c in centroid)


# ---------------------------------------------------------------------------
# 19. RMTDenoiser (pure math — no network)
# ---------------------------------------------------------------------------


class TestRMTDenoiser:
    def test_produces_signal_after_warmup(self) -> None:
        from omega.nodes.victoria.rmt_denoiser import RMTDenoiser

        denoiser = RMTDenoiser(window=50)
        rng = np.random.default_rng(7)
        result = None
        for _ in range(55):
            price_matrix = {
                ticker: float(rng.uniform(0.8, 1.2))
                for ticker in _TICKERS
            }
            result = denoiser.compute(price_matrix)

        assert result is not None
        # RMTDenoiser returns a dict/SignalValue — check the key output fields
        if hasattr(result, "value"):
            assert -1.0 <= result.value <= 1.0
        elif isinstance(result, dict) and "value" in result:
            assert -1.0 <= float(result["value"]) <= 1.0

    def test_warmup_fallback(self) -> None:
        from omega.nodes.victoria.rmt_denoiser import RMTDenoiser

        denoiser = RMTDenoiser(window=50)
        result = denoiser.compute({"BTCUSDT": 1.0})
        # Should not raise; during warmup returns a low-confidence signal
        assert result is not None


# ---------------------------------------------------------------------------
# 20. VRP signal (end-to-end with mocked data sources)
# ---------------------------------------------------------------------------


class TestVRPSignal:
    @patch("urllib.request.urlopen", side_effect=_network_error)
    def test_offline_fallback(self, _mock) -> None:
        from omega.nodes.victoria.vrp_signal import VRPSignalNode

        sig = VRPSignalNode()
        from omega.core.node import NodeInput

        inp = NodeInput(action="compute_vrp", parameters={"market_data": _make_market_data()})
        out = sig.execute(inp)
        # Should not raise; success or fail_gracefully
        assert out is not None
        assert isinstance(out.success, bool)


# ---------------------------------------------------------------------------
# Cross-cutting: all signals handle malformed ticker data gracefully
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signal_class,module",
    [
        ("OrderFlowSignal", "omega.nodes.victoria.signals_advanced"),
        ("CrossAssetSignal", "omega.nodes.victoria.signals_advanced"),
        ("MicrostructureSignal", "omega.nodes.victoria.signals_advanced"),
        ("SentimentSignal", "omega.nodes.victoria.signals_advanced"),
        ("PairsTradingSignal", "omega.nodes.victoria.pairs_signals"),
        ("CrossSectionalMomentumSignal", "omega.nodes.victoria.momentum_factor"),
    ],
)
def test_malformed_ohlcv_does_not_raise(signal_class: str, module: str) -> None:
    """Signals should not crash on malformed input."""
    import importlib

    mod = importlib.import_module(module)
    cls = getattr(mod, signal_class)
    sig = cls()

    malformed = {
        "BTCUSDT": {"close": [None, float("nan"), "bad", 50000.0]},
        "ETHUSDT": {},
        "SOLUSDT": None,
    }
    try:
        result = sig.compute(malformed)
        # If it returns something, it must be valid
        if result is not None and hasattr(result, "value"):
            assert math.isfinite(float(result.value))
    except (TypeError, AttributeError, KeyError):
        pytest.fail(f"{signal_class}.compute() raised on malformed input")


# ---------------------------------------------------------------------------
# Regression: signal values are deterministic on identical input
# ---------------------------------------------------------------------------


def test_timeseries_forecast_deterministic() -> None:
    """Same price data → same signal (cache hit or fresh compute)."""
    from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

    with patch("urllib.request.urlopen", side_effect=_network_error):
        sig = TimeseriesForecastSignal()
        md = _make_market_data()
        r1 = sig.compute(md)
        r2 = sig.compute(md)  # cache hit
        assert r1.value == r2.value, "TimeseriesForecast not deterministic on same input"


def test_momentum_factor_deterministic() -> None:
    """Cross-sectional momentum on identical input → same rank ordering."""
    from omega.nodes.victoria.momentum_factor import CrossSectionalMomentumSignal

    sig = CrossSectionalMomentumSignal()
    md = _make_market_data(tickers=_TICKERS, n=60)
    r1 = sig.compute(md)
    r2 = sig.compute(md)
    assert r1.value == r2.value
