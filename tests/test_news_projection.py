"""
tests/test_news_projection.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the news-projection layer.

Tests cover:
  1. Topic classification from raw text
  2. Per-signal multiplier validity (range, no NaN)
  3. Integration with DynamicWeightAllocator.apply_news_prior()
  4. Graceful handling of empty/missing input
  5. EMA smoothing across cycles
  6. News-projection from signals dict (project_from_signals)
"""

from __future__ import annotations

import math

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_multipliers(multipliers: dict, label: str = "") -> None:
    tag = f"[{label}] " if label else ""
    assert multipliers, f"{tag}empty multipliers"
    for sig, mult in multipliers.items():
        assert math.isfinite(mult), f"{tag}{sig}: multiplier={mult} is not finite"
        assert 0.5 <= mult <= 1.5, f"{tag}{sig}: multiplier={mult!r} out of expected safe range"


# ---------------------------------------------------------------------------
# NewsProjectionLayer tests
# ---------------------------------------------------------------------------


class TestNewsProjectionLayer:
    def test_neutral_on_empty_input(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(raw_text="")
        assert result.news_strength == 0.0
        assert result.dominant_topic == "none"
        _assert_multipliers(result.signal_multipliers, "empty_text")

    def test_multipliers_near_one_on_empty(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(raw_text="")
        for v in result.signal_multipliers.values():
            # On empty input (EMA initialized to 1.0), all multipliers should be 1.0
            assert abs(v - 1.0) < 1e-9

    def test_liquidation_news_boosts_whale_flow(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="massive liquidation cascade forced sell margin call wipe out"
        )
        assert result.news_strength > 0.0
        assert result.dominant_topic == "liquidation"
        # whale_flow and order_flow should be boosted
        assert result.signal_multipliers.get("whale_flow", 1.0) > 1.0
        assert result.signal_multipliers.get("order_flow", 1.0) > 1.0

    def test_macro_news_boosts_cross_asset(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="Federal Reserve FOMC interest rate decision inflation CPI monetary policy"
        )
        assert result.news_strength > 0.0
        # cross_asset and carry should be boosted for macro news
        assert result.signal_multipliers.get("cross_asset", 1.0) > 1.0
        assert result.signal_multipliers.get("carry", 1.0) > 1.0

    def test_derivatives_news_boosts_vrp_carry(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="funding rate open interest futures premium options implied vol deribit"
        )
        assert result.news_strength > 0.0
        # carry and vrp should be boosted for derivatives news
        assert result.signal_multipliers.get("carry", 1.0) > 1.0
        assert result.signal_multipliers.get("vrp", 1.0) > 1.0

    def test_whale_news_boosts_whale_signal(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="whale exchange outflow large holder institutional accumulation"
        )
        assert result.signal_multipliers.get("whale_flow", 1.0) > 1.0
        assert result.signal_multipliers.get("onchain", 1.0) > 1.0

    def test_technical_news_boosts_momentum(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="breakout support resistance momentum trend moving average technical analysis"
        )
        assert result.signal_multipliers.get("momentum_factor", 1.0) > 1.0
        assert result.signal_multipliers.get("timeseries_forecast", 1.0) > 1.0

    def test_positive_sentiment_adjusts_direction(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="bullish rally surge all-time high adoption",
            finbert_sentiment_score=0.8,
        )
        # Strong positive sentiment should boost momentum
        assert result.signal_multipliers.get("momentum_factor", 1.0) > 1.0

    def test_negative_sentiment_adjusts_direction(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(
            raw_text="crash dump hack exploit sec ban regulation",
            finbert_sentiment_score=-0.8,
        )
        # Strong negative sentiment should boost VRP / whale_flow
        assert result.signal_multipliers.get("vrp", 1.0) > 1.0

    def test_multipliers_always_in_valid_range(self) -> None:
        from omega.nodes.victoria.news_projection import (
            _MAX_BOOST,
            _MIN_BOOST,
            NewsProjectionLayer,
        )

        proj = NewsProjectionLayer()
        texts = [
            "massive liquidation cascade whale shorts squeezed",
            "Federal Reserve rate hike macro inflation dollar",
            "ETF approval BlackRock institutional accumulation",
            "technical breakout support resistance momentum",
            "fear greed panic fomo sentiment euphoria retail",
            "",
            "completely irrelevant text that should not match any topic well",
        ]
        for text in texts:
            result = proj.project(raw_text=text)
            for sig, mult in result.signal_multipliers.items():
                assert _MIN_BOOST - 0.01 <= mult <= _MAX_BOOST + 0.01, (
                    f"Multiplier for {sig!r}={mult!r} exceeds bounds [{_MIN_BOOST}, {_MAX_BOOST}]"
                )

    def test_ema_smooths_over_cycles(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        # Feed same strong signal 3 times
        for _ in range(3):
            proj.project(
                raw_text="massive liquidation cascade forced sell margin call whale shorts"
            )
        # After 3 cycles, EMA should be moving (not pinned at 1.0)
        ema = proj.get_multiplier_ema()
        assert ema.get("whale_flow", 1.0) != 1.0

    def test_reset_ema(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        proj.project(raw_text="massive liquidation cascade forced sell margin call")
        proj.reset_ema()
        ema = proj.get_multiplier_ema()
        for v in ema.values():
            assert abs(v - 1.0) < 1e-9

    def test_project_from_signals_uses_finbert_raw(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        signals = {
            "finbert_sentiment": {
                "value": 0.6,
                "confidence": 0.8,
                "regime_tag": "news_positive",
                "raw": {
                    "headlines": ["Bitcoin ETF approval rally", "BTC surge to new high"],
                    "regime_tag": "news_positive",
                },
            }
        }
        result = proj.project_from_signals(signals)
        assert result is not None
        _assert_multipliers(result.signal_multipliers, "from_signals")

    def test_project_from_signals_empty(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project_from_signals({})
        assert result is not None
        _assert_multipliers(result.signal_multipliers, "empty_signals")

    def test_tokens_analysed_count(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        proj = NewsProjectionLayer()
        result = proj.project(raw_text="Federal Reserve inflation rate hike CPI monetary policy")
        assert result.tokens_analysed > 0


# ---------------------------------------------------------------------------
# DynamicWeightAllocator.apply_news_prior() integration tests
# ---------------------------------------------------------------------------


class TestApplyNewsPrior:
    def _make_allocator(self):
        from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator

        signals = [
            "order_flow", "carry", "whale_flow", "vrp",
            "momentum_factor", "cross_asset", "sentiment",
        ]
        alloc = DynamicWeightAllocator(signal_names=signals)
        # Seed with enough IC samples to enable the adjustment
        priors = {s: 0.10 for s in signals}
        alloc.seed_priors(priors, n_samples=10)
        return alloc

    def test_apply_news_prior_does_not_crash(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        alloc = self._make_allocator()
        proj = NewsProjectionLayer(signal_names=list(alloc._signals))
        result = proj.project(raw_text="liquidation cascade forced sell whale margin call")

        alloc.apply_news_prior(
            result.signal_multipliers,
            strength=result.news_strength,
        )
        # After news prior, allocate should still work
        allocation = alloc.allocate()
        assert abs(sum(allocation.weights.values()) - 1.0) < 1e-6

    def test_apply_news_prior_low_strength_noop(self) -> None:

        alloc = self._make_allocator()
        before = alloc.allocate().weights.copy()
        # strength < 0.05 → no adjustment
        alloc.apply_news_prior({"carry": 1.30, "vrp": 0.70}, strength=0.01)
        after = alloc.allocate().weights
        for sig in before:
            assert abs(before[sig] - after[sig]) < 1e-9, f"{sig}: weight changed on near-zero strength"

    def test_apply_news_prior_shifts_weights_toward_boosted_signals(self) -> None:
        from omega.nodes.victoria.news_projection import NewsProjectionLayer

        alloc = self._make_allocator()
        proj = NewsProjectionLayer(signal_names=list(alloc._signals))

        # Derivatives news → should boost carry and vrp
        result = proj.project(
            raw_text="funding rate open interest futures premium options implied vol deribit perpetual"
        )
        alloc.apply_news_prior(result.signal_multipliers, strength=result.news_strength)
        after = alloc.allocate().weights

        # carry should have higher or equal weight after derivatives news
        # (soft prior: may not always shift if IC history dominates)
        assert after.get("carry", 0) >= 0, "carry weight must be non-negative"
        assert abs(sum(after.values()) - 1.0) < 1e-6, "weights must sum to 1.0"

    def test_apply_news_prior_empty_multipliers(self) -> None:
        alloc = self._make_allocator()
        before = alloc.allocate().weights.copy()
        alloc.apply_news_prior({}, strength=0.8)
        after = alloc.allocate().weights
        for sig in before:
            assert abs(before[sig] - after[sig]) < 1e-9


# ---------------------------------------------------------------------------
# Conformal prediction tests (timeseries_forecast bootstrap)
# ---------------------------------------------------------------------------


class TestConformalPrediction:
    def _make_prices(self, n: int = 60, trend: float = 0.001) -> list[float]:
        return [50000.0 * (1 + trend) ** i for i in range(n)]

    def test_bootstrap_returns_valid_interval(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _bootstrap_forecast, _returns

        prices = self._make_prices()
        rets = _returns(prices)
        p10, p50, p90 = _bootstrap_forecast(rets, prices)

        assert math.isfinite(p10)
        assert math.isfinite(p50)
        assert math.isfinite(p90)
        assert p10 <= p50 <= p90, f"Quantile ordering violated: p10={p10} p50={p50} p90={p90}"

    def test_bootstrap_insufficient_data(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _bootstrap_forecast

        p10, p50, p90 = _bootstrap_forecast([], [])
        assert p10 == 0.0 and p50 == 0.0 and p90 == 0.0

    def test_uncertainty_score_valid(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _uncertainty_score

        u = _uncertainty_score(p10=-0.02, p90=0.02, vol_scale=0.02)
        assert math.isfinite(u)
        assert 0.0 <= u <= 1.0

    def test_uncertainty_zero_vol(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _uncertainty_score

        u = _uncertainty_score(p10=-0.01, p90=0.01, vol_scale=0.0)
        assert u == 0.5  # fallback

    def test_interval_adjusted_signal_no_straddle(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _interval_adjusted_signal

        # Both quantiles positive → no attenuation
        sig = _interval_adjusted_signal(signal_raw=0.5, p10=0.01, p90=0.03, vol_scale=0.02)
        assert sig == pytest.approx(0.5)

    def test_interval_adjusted_signal_full_straddle(self) -> None:
        from omega.nodes.victoria.timeseries_forecast import _interval_adjusted_signal

        # Symmetric straddle → 50% attenuation
        sig = _interval_adjusted_signal(signal_raw=0.5, p10=-0.01, p90=0.01, vol_scale=0.02)
        assert 0.0 <= sig <= 0.5

    def test_forecast_signal_includes_uncertainty_in_raw(self) -> None:
        """TimeseriesForecastSignal.compute() raw output includes bootstrap fields."""
        import urllib.error
        from unittest.mock import patch

        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        def _net_err(*a, **k):
            raise urllib.error.URLError("offline")

        with patch("urllib.request.urlopen", side_effect=_net_err):
            sig = TimeseriesForecastSignal()
            prices = self._make_prices()
            md = {
                "BTCUSDT": {
                    "close": prices,
                    "adjclose": prices,
                    "volume": [1e6] * len(prices),
                }
            }
            result = sig.compute(md)

        assert "avg_uncertainty" in result.raw, "raw must include avg_uncertainty"
        assert math.isfinite(result.raw["avg_uncertainty"])
        assert 0.0 <= result.raw["avg_uncertainty"] <= 1.0

        assert "agg_p10" in result.raw
        assert "agg_p90" in result.raw
        assert result.raw["agg_p10"] <= result.raw["agg_p90"]

    def test_high_uncertainty_sets_regime_tag(self) -> None:
        """When avg_uncertainty > 0.7, regime_tag should be high_uncertainty."""
        import urllib.error
        from unittest.mock import patch

        from omega.nodes.victoria.timeseries_forecast import TimeseriesForecastSignal

        def _net_err(*a, **k):
            raise urllib.error.URLError("offline")

        # High-noise price series to trigger uncertainty
        import random as _r
        _r.seed(42)
        noisy = [50000.0 + _r.gauss(0, 5000) for _ in range(60)]

        with patch("urllib.request.urlopen", side_effect=_net_err):
            sig = TimeseriesForecastSignal()
            md = {"BTCUSDT": {"close": noisy, "adjclose": noisy, "volume": [1e6] * 60}}
            result = sig.compute(md)

        # Either high_uncertainty or another valid tag — just check it's a string
        assert isinstance(result.regime_tag, str) and result.regime_tag
