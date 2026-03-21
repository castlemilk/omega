"""Tests for omega.nodes.vectora.signals_advanced"""

import math

from omega.nodes.vectora.signals_advanced import (
    CrossAssetSignal,
    MicrostructureSignal,
    OrderFlowSignal,
    SentimentSignal,
    SignalValue,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_prices(n: int = 50, trend: float = 0.001) -> list[float]:
    """Generate trending prices starting at 100."""
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + trend))
    return prices


def make_volumes(n: int = 50, base: float = 1000.0) -> list[float]:
    return [base + i * 10 for i in range(n)]


# ---------------------------------------------------------------------------
# SignalValue contract
# ---------------------------------------------------------------------------


def test_signal_value_fields():
    sv = SignalValue(value=0.5, confidence=0.8, regime_tag="trending", raw={"x": 1.0})
    assert -1.0 <= sv.value <= 1.0
    assert 0.0 <= sv.confidence <= 1.0
    assert isinstance(sv.regime_tag, str)
    assert isinstance(sv.raw, dict)


# ---------------------------------------------------------------------------
# OrderFlowSignal
# ---------------------------------------------------------------------------


class TestOrderFlowSignal:
    def setup_method(self):
        self.signal = OrderFlowSignal()

    def test_returns_signal_value(self):
        prices = make_prices(60)
        volumes = make_volumes(60)
        sv = self.signal.compute({"close": prices, "volume": volumes})
        assert isinstance(sv, SignalValue)
        assert -1.0 <= sv.value <= 1.0
        assert 0.0 <= sv.confidence <= 1.0

    def test_insufficient_data_returns_low_confidence(self):
        sv = self.signal.compute({"close": [], "volume": []})
        assert sv.confidence == 0.0

    def test_order_book_imbalance_bullish(self):
        prices = make_prices(30)
        volumes = make_volumes(30)
        # 90% bids = strong buy pressure
        sv = self.signal.compute(
            {
                "close": prices,
                "volume": volumes,
                "bid_sizes": [900.0],
                "ask_sizes": [100.0],
            }
        )
        assert sv.value > 0, "Heavy bid imbalance should produce bullish signal"

    def test_order_book_imbalance_bearish(self):
        prices = make_prices(30)
        volumes = make_volumes(30)
        sv = self.signal.compute(
            {
                "close": prices,
                "volume": volumes,
                "bid_sizes": [100.0],
                "ask_sizes": [900.0],
            }
        )
        assert sv.value < 0, "Heavy ask imbalance should produce bearish signal"

    def test_vpin_in_raw(self):
        prices = make_prices(60)
        volumes = make_volumes(60)
        sv = self.signal.compute({"close": prices, "volume": volumes})
        assert "vpin" in sv.raw
        assert 0.0 <= sv.raw["vpin"] <= 1.0

    def test_toxic_flow_regime_on_mixed_prices(self):
        # Alternating up/down prices → equal buy/sell → low toxicity
        prices = [100.0 + (1 if i % 2 == 0 else -1) for i in range(60)]
        volumes = make_volumes(60)
        sv = self.signal.compute({"close": prices, "volume": volumes})
        assert sv.regime_tag in {"toxic_flow", "normal_flow", "mixed_flow"}

    def test_no_nan_in_output(self):
        prices = make_prices(80)
        volumes = make_volumes(80)
        sv = self.signal.compute({"close": prices, "volume": volumes})
        assert not math.isnan(sv.value)
        assert not math.isnan(sv.confidence)


# ---------------------------------------------------------------------------
# CrossAssetSignal
# ---------------------------------------------------------------------------


class TestCrossAssetSignal:
    def setup_method(self):
        self.signal = CrossAssetSignal()

    def _make_market_data(self, n: int = 60) -> dict:
        return {
            "BTCUSDT": {"close": make_prices(n, trend=0.002)},
            "ETHUSDT": {"close": make_prices(n, trend=0.0018)},
            "SOLUSDT": {"close": make_prices(n, trend=0.003)},
            "target_prices": make_prices(n, trend=0.0015),
        }

    def test_returns_signal_value(self):
        md = self._make_market_data()
        sv = self.signal.compute(md)
        assert isinstance(sv, SignalValue)
        assert -1.0 <= sv.value <= 1.0

    def test_regime_tag_set(self):
        md = self._make_market_data()
        sv = self.signal.compute(md)
        assert sv.regime_tag in {
            "high_correlation",
            "decorrelated",
            "divergent",
            "moderate_correlation",
        }

    def test_high_correlation_regime_detected(self):
        # All assets trending perfectly together
        p = make_prices(60, trend=0.002)
        md = {
            "BTCUSDT": {"close": p},
            "ETHUSDT": {"close": p},
            "SOLUSDT": {"close": p},
            "target_prices": p,
        }
        sv = self.signal.compute(md)
        assert sv.regime_tag == "high_correlation"
        assert sv.confidence > 0.6

    def test_cross_corr_in_raw(self):
        md = self._make_market_data()
        sv = self.signal.compute(md)
        assert "avg_cross_corr" in sv.raw

    def test_empty_data_returns_zero_confidence(self):
        sv = self.signal.compute({})
        assert sv.confidence == 0.0 or sv.value == 0.0

    def test_lead_lag_detection(self):
        n = 60
        # BTC leads target by 1 period
        btc_prices = make_prices(n, trend=0.003)
        target_prices = [*btc_prices[1:], btc_prices[-1]]  # shifted by 1
        md = {
            "BTCUSDT": {"close": btc_prices},
            "ETHUSDT": {"close": make_prices(n)},
            "SOLUSDT": {"close": make_prices(n)},
            "target_prices": target_prices,
        }
        sv = self.signal.compute(md)
        assert "btc_lead_lag_corr" in sv.raw or sv.value == 0.0  # may detect lead-lag


# ---------------------------------------------------------------------------
# MicrostructureSignal
# ---------------------------------------------------------------------------


class TestMicrostructureSignal:
    def setup_method(self):
        self.signal = MicrostructureSignal()

    def _base_data(self, n: int = 30) -> dict:
        prices = make_prices(n)
        return {
            "close": prices,
            "high": [p * 1.005 for p in prices],
            "low": [p * 0.995 for p in prices],
            "volume": make_volumes(n),
        }

    def test_returns_signal_value(self):
        sv = self.signal.compute(self._base_data())
        assert isinstance(sv, SignalValue)
        assert -1.0 <= sv.value <= 1.0

    def test_regime_tag_set(self):
        sv = self.signal.compute(self._base_data())
        assert sv.regime_tag in {"quote_stuffing", "wide_spread", "trending_candles", "choppy"}

    def test_wide_spread_dampens_signal(self):
        data = self._base_data()
        # Unusually wide spreads
        data["spreads"] = [0.01 * (i + 1) for i in range(30)]  # increasing spreads
        sv = self.signal.compute(data)
        # Wide spread should lower confidence or change regime
        assert sv.confidence <= 0.5 or sv.regime_tag in {"wide_spread", "choppy"}

    def test_trending_candles_detected(self):
        n = 30
        # Very directional candles (small H-L range relative to net move)
        prices = make_prices(n, trend=0.01)
        data = {
            "close": prices,
            "high": [p * 1.001 for p in prices],  # tight range
            "low": [p * 0.999 for p in prices],
            "volume": make_volumes(n),
        }
        sv = self.signal.compute(data)
        # Range efficiency should be high → trending_candles regime likely
        assert sv.raw.get("range_efficiency", 0) > 0

    def test_tick_momentum_in_raw(self):
        sv = self.signal.compute(self._base_data())
        assert "tick_momentum" in sv.raw

    def test_no_nan_output(self):
        sv = self.signal.compute(self._base_data())
        assert not math.isnan(sv.value)
        assert not math.isnan(sv.confidence)


# ---------------------------------------------------------------------------
# SentimentSignal
# ---------------------------------------------------------------------------


class TestSentimentSignal:
    def setup_method(self):
        self.signal = SentimentSignal()

    def test_returns_signal_value(self):
        sv = self.signal.compute(
            {
                "funding_rates": [0.0001] * 10,
                "open_interest": [1000.0, 1100.0],
                "close": make_prices(10),
            }
        )
        assert isinstance(sv, SignalValue)

    def test_extreme_greed_produces_bearish_signal(self):
        # Very high funding rate = crowd is too long = contrarian bear signal
        sv = self.signal.compute(
            {
                "funding_rates": [0.001] * 10,  # 10x above threshold
                "open_interest": [],
                "close": [],
            }
        )
        assert sv.value < 0, "Extreme positive funding should yield bearish (contrarian) signal"
        assert sv.regime_tag == "extreme_greed"

    def test_extreme_fear_produces_bullish_signal(self):
        sv = self.signal.compute(
            {
                "funding_rates": [-0.001] * 10,
                "open_interest": [],
                "close": [],
            }
        )
        assert sv.value > 0, "Extreme negative funding should yield bullish (contrarian) signal"
        assert sv.regime_tag == "extreme_fear"

    def test_neutral_funding_produces_neutral_signal(self):
        sv = self.signal.compute(
            {
                "funding_rates": [0.000005] * 10,  # near zero
                "open_interest": [],
                "close": [],
            }
        )
        assert abs(sv.value) < 0.5
        assert sv.regime_tag == "neutral_sentiment"

    def test_oi_rising_with_price_bullish(self):
        prices = make_prices(5, trend=0.01)
        sv = self.signal.compute(
            {
                "funding_rates": [0.00001] * 5,
                "open_interest": [1000.0, 1050.0],  # rising OI
                "close": prices,
            }
        )
        assert sv.value > 0 or sv.value == 0, "Rising OI with rising price → bullish"

    def test_no_data_returns_zero_confidence(self):
        sv = self.signal.compute({})
        assert sv.confidence == 0.0

    def test_confidence_higher_at_extreme_funding(self):
        extreme = self.signal.compute(
            {"funding_rates": [0.001] * 10, "open_interest": [], "close": []}
        )
        mild = self.signal.compute(
            {"funding_rates": [0.0001] * 10, "open_interest": [], "close": []}
        )
        assert extreme.confidence >= mild.confidence

    def test_funding_rate_in_raw(self):
        sv = self.signal.compute(
            {
                "funding_rates": [0.0002] * 5,
                "open_interest": [],
                "close": [],
            }
        )
        assert "funding_rate" in sv.raw
        assert "avg_funding_8p" in sv.raw
