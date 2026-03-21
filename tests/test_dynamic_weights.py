"""Tests for omega.nodes.vectora.dynamic_weights"""

from omega.nodes.vectora.dynamic_weights import (
    MAX_SINGLE_WEIGHT,
    MIN_IC_SAMPLES,
    AllocationResult,
    DynamicWeightAllocator,
    RegimeAwareWeightManager,
)

SIGNALS = ["order_flow", "cross_asset", "microstructure", "sentiment"]


# ---------------------------------------------------------------------------
# DynamicWeightAllocator — basic contract
# ---------------------------------------------------------------------------


class TestDynamicWeightAllocatorBasic:
    def setup_method(self):
        self.alloc = DynamicWeightAllocator(SIGNALS)

    def test_equal_weights_before_any_ic(self):
        result = self.alloc.allocate()
        assert result.is_fallback
        weights = result.weights
        assert abs(sum(weights.values()) - 1.0) < 1e-9
        for w in weights.values():
            assert abs(w - 0.25) < 1e-9

    def test_allocate_returns_allocation_result(self):
        result = self.alloc.allocate()
        assert isinstance(result, AllocationResult)
        assert isinstance(result.weights, dict)
        assert isinstance(result.dominant_signal, str)
        assert isinstance(result.capped_signals, list)

    def test_weights_sum_to_one(self):
        # Feed IC for all signals
        for _ in range(MIN_IC_SAMPLES + 2):
            for s in SIGNALS:
                self.alloc.update_ic(s, 0.1)
        result = self.alloc.allocate()
        assert abs(sum(result.weights.values()) - 1.0) < 1e-9

    def test_weights_non_negative(self):
        for _ in range(MIN_IC_SAMPLES + 2):
            for s in SIGNALS:
                self.alloc.update_ic(s, 0.1)
        result = self.alloc.allocate()
        for w in result.weights.values():
            assert w >= 0.0


# ---------------------------------------------------------------------------
# IC learning — weights shift toward better signals
# ---------------------------------------------------------------------------


class TestICLearning:
    def setup_method(self):
        self.alloc = DynamicWeightAllocator(SIGNALS)

    def _fill_ic(self, ic_map: dict[str, float], n: int = MIN_IC_SAMPLES + 3) -> None:
        for _ in range(n):
            for s in SIGNALS:
                self.alloc.update_ic(s, ic_map.get(s, 0.0))

    def test_higher_ic_signal_gets_more_weight(self):
        self._fill_ic(
            {"order_flow": 0.3, "cross_asset": 0.1, "microstructure": 0.1, "sentiment": 0.1}
        )
        result = self.alloc.allocate()
        assert not result.is_fallback
        assert result.weights["order_flow"] > result.weights["cross_asset"]

    def test_equal_ic_produces_equal_weights(self):
        self._fill_ic({s: 0.1 for s in SIGNALS})
        result = self.alloc.allocate()
        weights = list(result.weights.values())
        assert max(weights) - min(weights) < 0.02  # near-equal

    def test_single_good_signal_caps_at_max_weight(self):
        # One signal with very high IC
        self._fill_ic(
            {"order_flow": 0.9, "cross_asset": 0.01, "microstructure": 0.01, "sentiment": 0.01}
        )
        result = self.alloc.allocate()
        assert result.weights["order_flow"] <= MAX_SINGLE_WEIGHT + 1e-9
        assert (
            "order_flow" in result.capped_signals
            or result.weights["order_flow"] <= MAX_SINGLE_WEIGHT
        )

    def test_cap_enforced_strictly(self):
        self._fill_ic(
            {"order_flow": 1.0, "cross_asset": 0.0, "microstructure": 0.0, "sentiment": 0.0}
        )
        result = self.alloc.allocate()
        for w in result.weights.values():
            assert w <= MAX_SINGLE_WEIGHT + 1e-9

    def test_negative_ic_signal_gets_low_weight(self):
        # Negative IC — we use abs(IC) so it still gets weight, but if zero, gets equal
        self._fill_ic(
            {"order_flow": 0.0, "cross_asset": 0.2, "microstructure": 0.2, "sentiment": 0.2}
        )
        result = self.alloc.allocate()
        assert result.weights["cross_asset"] > result.weights["order_flow"]


# ---------------------------------------------------------------------------
# Regime-aware weighting
# ---------------------------------------------------------------------------


class TestRegimeAwareWeighting:
    def setup_method(self):
        self.alloc = DynamicWeightAllocator(SIGNALS)

    def _fill_regime(self, regime: str, ic_map: dict[str, float]) -> None:
        for _ in range(MIN_IC_SAMPLES + 3):
            for s in SIGNALS:
                self.alloc.update_ic(s, ic_map.get(s, 0.05), regime=regime)

    def test_different_regimes_produce_different_weights(self):
        self._fill_regime(
            "trending",
            {"order_flow": 0.4, "cross_asset": 0.1, "microstructure": 0.1, "sentiment": 0.1},
        )
        self._fill_regime(
            "ranging",
            {"order_flow": 0.1, "cross_asset": 0.1, "microstructure": 0.4, "sentiment": 0.1},
        )

        trending = self.alloc.allocate(regime="trending")
        ranging = self.alloc.allocate(regime="ranging")

        assert trending.weights["order_flow"] > trending.weights["microstructure"]
        assert ranging.weights["microstructure"] > ranging.weights["order_flow"]

    def test_unknown_regime_falls_back_to_default(self):
        result = self.alloc.allocate(regime="unknown_xyz")
        assert result.regime == "default"

    def test_regime_profile_snapshot(self):
        self._fill_regime("trending", {s: 0.1 for s in SIGNALS})
        profile = self.alloc.get_profile("trending")
        assert "weights" in profile
        assert "ic_ema" in profile
        assert "sample_counts" in profile
        assert profile["is_data_sufficient"]

    def test_all_profiles_returns_all_regimes(self):
        profiles = self.alloc.get_all_profiles()
        assert "default" in profiles
        assert "trending" in profiles
        assert "ranging" in profiles


# ---------------------------------------------------------------------------
# blend_signals
# ---------------------------------------------------------------------------


class TestBlendSignals:
    def setup_method(self):
        self.alloc = DynamicWeightAllocator(SIGNALS)

    def test_blend_returns_float_in_range(self):
        signal_values = {s: 0.5 for s in SIGNALS}
        result = self.alloc.blend_signals(signal_values)
        assert -1.0 <= result <= 1.0

    def test_all_positive_signals_produce_positive_composite(self):
        signal_values = {s: 1.0 for s in SIGNALS}
        result = self.alloc.blend_signals(signal_values)
        assert result > 0

    def test_all_negative_signals_produce_negative_composite(self):
        signal_values = {s: -1.0 for s in SIGNALS}
        result = self.alloc.blend_signals(signal_values)
        assert result < 0

    def test_blend_mixed_signals(self):
        signal_values = {
            "order_flow": 1.0,
            "cross_asset": -1.0,
            "microstructure": 0.0,
            "sentiment": 0.0,
        }
        result = self.alloc.blend_signals(signal_values)
        assert -1.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# RegimeAwareWeightManager
# ---------------------------------------------------------------------------


class TestRegimeAwareWeightManager:
    def setup_method(self):
        self.manager = RegimeAwareWeightManager(SIGNALS)

    def test_compute_composite_returns_dict(self):
        result = self.manager.compute_composite(
            "BTCUSDT", {s: 0.5 for s in SIGNALS}, regime="trending"
        )
        assert "composite" in result
        assert "weights" in result
        assert "regime" in result
        assert "source" in result

    def test_composite_in_valid_range(self):
        result = self.manager.compute_composite("BTCUSDT", {s: 0.8 for s in SIGNALS})
        assert -1.0 <= result["composite"] <= 1.0

    def test_record_ic_shifts_weights(self):
        for _ in range(MIN_IC_SAMPLES + 3):
            self.manager.record_ic("BTCUSDT", "order_flow", ic=0.5, regime="trending")
            self.manager.record_ic("BTCUSDT", "cross_asset", ic=0.05, regime="trending")
            self.manager.record_ic("BTCUSDT", "microstructure", ic=0.05, regime="trending")
            self.manager.record_ic("BTCUSDT", "sentiment", ic=0.05, regime="trending")

        result = self.manager.compute_composite(
            "BTCUSDT", {s: 1.0 for s in SIGNALS}, regime="trending"
        )
        # order_flow should dominate
        assert result["dominant_signal"] == "order_flow"

    def test_unknown_ticker_returns_global_blended(self):
        result = self.manager.compute_composite("NEWTOKEN", {s: 0.5 for s in SIGNALS})
        assert result["source"] == "global_blended"

    def test_get_summary_structure(self):
        summary = self.manager.get_summary()
        assert "tickers_tracked" in summary
        assert "signals" in summary
        assert "global_profile" in summary

    def test_multiple_tickers_independent(self):
        for _ in range(MIN_IC_SAMPLES + 3):
            self.manager.record_ic("BTC", "order_flow", ic=0.5)
            self.manager.record_ic("BTC", "cross_asset", ic=0.05)
            self.manager.record_ic("BTC", "microstructure", ic=0.05)
            self.manager.record_ic("BTC", "sentiment", ic=0.05)

            self.manager.record_ic("ETH", "order_flow", ic=0.05)
            self.manager.record_ic("ETH", "cross_asset", ic=0.5)
            self.manager.record_ic("ETH", "microstructure", ic=0.05)
            self.manager.record_ic("ETH", "sentiment", ic=0.05)

        btc_result = self.manager.compute_composite("BTC", {s: 1.0 for s in SIGNALS})
        eth_result = self.manager.compute_composite("ETH", {s: 1.0 for s in SIGNALS})

        assert btc_result["dominant_signal"] == "order_flow"
        assert eth_result["dominant_signal"] == "cross_asset"


# ---------------------------------------------------------------------------
# EMA update behavior
# ---------------------------------------------------------------------------


class TestEMAUpdate:
    def test_ema_converges_toward_ic_value(self):
        alloc = DynamicWeightAllocator(["a", "b"])
        target_ic = 0.5
        for _ in range(30):
            alloc.update_ic("a", target_ic)
            alloc.update_ic("b", 0.1)

        profile = alloc.get_profile("default")
        assert abs(profile["ic_ema"]["a"] - target_ic) < 0.05

    def test_ema_reacts_to_regime_change(self):
        alloc = DynamicWeightAllocator(SIGNALS)
        # Build history in trending
        for _ in range(MIN_IC_SAMPLES + 3):
            for s in SIGNALS:
                alloc.update_ic(s, 0.1, regime="trending")

        # Now one signal suddenly performs better
        for _ in range(5):
            alloc.update_ic("sentiment", 0.8, regime="trending")

        profile = alloc.get_profile("trending")
        assert profile["ic_ema"]["sentiment"] > profile["ic_ema"]["order_flow"]

    def test_batch_update_equivalent_to_individual(self):
        alloc1 = DynamicWeightAllocator(SIGNALS)
        alloc2 = DynamicWeightAllocator(SIGNALS)

        ic_map = {s: 0.1 * (i + 1) for i, s in enumerate(SIGNALS)}

        for _ in range(MIN_IC_SAMPLES + 2):
            alloc1.update_ic_batch(ic_map)
            for s, ic in ic_map.items():
                alloc2.update_ic(s, ic)

        r1 = alloc1.allocate()
        r2 = alloc2.allocate()
        for s in SIGNALS:
            assert abs(r1.weights[s] - r2.weights[s]) < 1e-9
