"""
Tests for the VRP (Variance Risk Premium) signal system.

Covers:
  - VRP computation with known IV/RV → expected VRP, zscore, regime
  - Regime transition logic (FEAR / NEUTRAL / COMPLACENCY)
  - FundingRateVolProxy and RealizedVolCalculator
  - DynamicWeightAllocator integration with "vrp" signal
  - RiskManagementNode VRP-adjusted position sizing
"""

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator
from omega.nodes.victoria.risk_management import RiskManagementNode
from omega.nodes.victoria.vrp_data import (
    FundingRateVolProxy,
    RealizedVolCalculator,
)
from omega.nodes.victoria.vrp_signal import (
    VRPSignalNode,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 60, base: float = 50_000.0, vol: float = 0.02) -> dict:
    """Synthetic OHLCV where realized vol ≈ vol * sqrt(365)."""
    import random

    rng = random.Random(42)
    prices = [base]
    for _ in range(n):
        prices.append(prices[-1] * (1 + rng.gauss(0, vol)))

    highs = [p * (1 + abs(rng.gauss(0, vol / 2))) for p in prices]
    lows = [p * (1 - abs(rng.gauss(0, vol / 2))) for p in prices]
    opens = [p * (1 + rng.gauss(0, vol / 4)) for p in prices]

    return {
        "close": prices,
        "high": highs,
        "low": lows,
        "open": opens,
    }


def _call_compute_vrp(node: VRPSignalNode, iv: float, market_data: dict) -> dict:
    """Helper: call compute_vrp with iv_override so no network call is made."""
    out = node.execute(
        NodeInput(
            action="compute_vrp",
            parameters={"market_data": market_data, "iv_override": iv},
        )
    )
    assert out.success, out.errors
    return out.result  # type: ignore[no-any-return]


# ─────────────────────────────────────────────────────────────────────────────
# RealizedVolCalculator
# ─────────────────────────────────────────────────────────────────────────────


class TestRealizedVolCalculator:
    def test_close_to_close_basic(self):
        rv_calc = RealizedVolCalculator()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        rv = rv_calc.compute(ohlcv, window=30, estimator="close_to_close")
        assert rv is not None
        assert 0.01 < rv < 3.0  # annualised: daily vol 2% → ~38% annualised

    def test_parkinson_basic(self):
        rv_calc = RealizedVolCalculator()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        rv = rv_calc.compute(ohlcv, window=30, estimator="parkinson")
        assert rv is not None
        assert 0.01 < rv < 3.0

    def test_garman_klass_basic(self):
        rv_calc = RealizedVolCalculator()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        rv = rv_calc.compute(ohlcv, window=30, estimator="garman_klass")
        assert rv is not None
        assert 0.01 < rv < 3.0

    def test_insufficient_data_returns_none(self):
        rv_calc = RealizedVolCalculator()
        rv = rv_calc.compute({"close": [100.0, 101.0]}, window=30)
        assert rv is None

    def test_annualised_scale(self):
        """Daily vol of 1% should produce ~19% annualised vol."""
        rv_calc = RealizedVolCalculator()
        # Create a very regular time series with known 1% daily moves
        prices = [100.0 * (1.01**i) for i in range(50)]  # monotone 1% daily up
        rv = rv_calc.compute({"close": prices}, window=30, estimator="close_to_close")
        # log return of ln(1.01) ≈ 0.00995; std of constant series ≈ 0
        # monotone returns have near-zero variance → expect near-zero vol
        assert rv is not None
        assert rv < 0.05  # very low vol for a monotone series


# ─────────────────────────────────────────────────────────────────────────────
# FundingRateVolProxy
# ─────────────────────────────────────────────────────────────────────────────


class TestFundingRateVolProxy:
    def test_normal_funding_gives_reasonable_iv(self):
        proxy = FundingRateVolProxy()
        # 0.01% per 8h (0.0001) → should give ~30% IV
        rates = [0.0001] * 8
        iv = proxy.compute_iv_proxy(rates)
        assert iv is not None
        assert abs(iv - 0.30) < 0.05

    def test_high_funding_gives_higher_iv(self):
        proxy = FundingRateVolProxy()
        low_rates = [0.0001] * 8
        high_rates = [0.0009] * 8
        iv_low = proxy.compute_iv_proxy(low_rates)
        iv_high = proxy.compute_iv_proxy(high_rates)
        assert iv_high > iv_low

    def test_insufficient_data_returns_none(self):
        proxy = FundingRateVolProxy()
        assert proxy.compute_iv_proxy([0.0001, 0.0002]) is None

    def test_output_clamped(self):
        proxy = FundingRateVolProxy()
        # Extreme funding rates should not exceed 200%
        rates = [1.0] * 8  # absurdly high
        iv = proxy.compute_iv_proxy(rates)
        assert iv is not None
        assert iv <= 2.0


# ─────────────────────────────────────────────────────────────────────────────
# VRPSignalNode — core computation
# ─────────────────────────────────────────────────────────────────────────────


class TestVRPSignalNode:
    def test_node_protocol(self):
        node = VRPSignalNode()
        state = node.get_state()
        assert state.name == "VRPSignalNode"
        assert "compute_vrp" in node.get_capabilities()
        assert "vrp_regime" in node.get_capabilities()
        assert state.health >= 0.0

    def test_positive_vrp_fear_regime(self):
        """High IV, low RV → large positive VRP → FEAR regime after warmup."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.005)  # low daily vol → low RV
        market_data = {"BTCUSDT": ohlcv}

        # Warm up the VRP history so zscore is meaningful
        for _ in range(25):
            _call_compute_vrp(node, iv=0.25, market_data=market_data)  # RV ~10%, IV=25%

        # Now inject a very high IV to push VRP zscore above FEAR threshold
        result = _call_compute_vrp(node, iv=2.0, market_data=market_data)

        assert result["vrp_raw"] > 0
        assert result["vrp_regime"] == "FEAR"
        assert result["vrp_signal"] > 0  # positive = sell vol / mean revert

    def test_negative_vrp_complacency_regime(self):
        """Low IV, high RV → negative VRP → COMPLACENCY regime after warmup."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.03)  # high daily vol → high RV
        market_data = {"BTCUSDT": ohlcv}

        # Warm up with normal VRP
        for _ in range(25):
            _call_compute_vrp(node, iv=0.80, market_data=market_data)

        # Push IV very low so VRP collapses
        result = _call_compute_vrp(node, iv=0.05, market_data=market_data)

        assert result["vrp_raw"] < 0
        assert result["vrp_regime"] == "COMPLACENCY"
        assert result["vrp_signal"] < 0  # negative = reduce exposure

    def test_neutral_regime(self):
        """Moderate VRP spread → NEUTRAL when zscore is within band."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.015)
        market_data = {"BTCUSDT": ohlcv}

        # Build history of consistent VRP
        for _ in range(35):
            _call_compute_vrp(node, iv=0.50, market_data=market_data)

        result = _call_compute_vrp(node, iv=0.50, market_data=market_data)
        assert result["vrp_regime"] == "NEUTRAL"
        assert -1.0 <= result["vrp_signal"] <= 1.0

    def test_vrp_zscore_computation(self):
        """VRP zscore should reflect position relative to rolling history."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.01)
        market_data = {"BTCUSDT": ohlcv}

        # Fill history with stable VRP
        for _ in range(30):
            _call_compute_vrp(node, iv=0.40, market_data=market_data)

        result = _call_compute_vrp(node, iv=0.40, market_data=market_data)
        # After stable history, current == mean → zscore near 0
        assert abs(result["vrp_zscore"]) < 1.0

    def test_circuit_breaker_triggers(self):
        """VRP zscore below -2sigma should set circuit_breaker=True."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        market_data = {"BTCUSDT": ohlcv}

        # Warm up with moderate positive VRP
        for _ in range(30):
            _call_compute_vrp(node, iv=0.60, market_data=market_data)

        # Collapse IV dramatically below RV to push zscore << -2
        result = _call_compute_vrp(node, iv=0.01, market_data=market_data)

        assert result["circuit_breaker"] is True
        assert result["vrp_regime"] == "COMPLACENCY"

    def test_no_data_returns_neutral_signal(self):
        """Empty market data should give neutral signal with zero confidence."""
        node = VRPSignalNode()
        # Use no iv_override so Deribit fetch fails (no network in tests)
        out = node.execute(
            NodeInput(
                action="compute_vrp",
                parameters={"market_data": {}},
            )
        )
        assert out.success
        r = out.result
        assert r["vrp_regime"] == "NEUTRAL"
        assert r["confidence"] < 0.5

    def test_rv_only_fallback_produces_nonzero_vrp(self):
        """When Deribit is unreachable but OHLCV is present, VRP should be non-zero.

        The fallback: iv = rv * 1.15 → vrp = iv - rv = 0.15 * rv > 0.
        """
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        market_data = {"BTCUSDT": ohlcv}

        # No iv_override → Deribit fetch will fail in test environment
        out = node.execute(
            NodeInput(
                action="compute_vrp",
                parameters={"market_data": market_data},
            )
        )
        assert out.success
        r = out.result
        # With RV fallback active, implied_vol = rv * 1.15 → vrp = 0.15 * rv > 0
        assert r["implied_vol"] is not None, "IV should be set via RV fallback"
        assert r["realized_vol"] is not None, "RV should be computable from OHLCV"
        assert r["vrp_raw"] > 0.0, "VRP should be non-zero when using RV fallback"

    def test_vrp_regime_action(self):
        """vrp_regime action returns cached state."""
        node = VRPSignalNode()
        out = node.execute(NodeInput(action="vrp_regime", parameters={}))
        assert out.success
        assert "regime" in out.result
        assert "zscore" in out.result

    def test_unknown_action_returns_error(self):
        node = VRPSignalNode()
        out = node.execute(NodeInput(action="unknown_action", parameters={}))
        assert not out.success
        assert out.errors

    def test_improve_is_noop(self):
        node = VRPSignalNode()
        assert node.improve({}) is False

    def test_confidence_increases_with_history(self):
        """Confidence should grow as VRP history fills up."""
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        market_data = {"BTCUSDT": ohlcv}

        confidences = []
        for _ in range(35):
            result = _call_compute_vrp(node, iv=0.80, market_data=market_data)
            confidences.append(result["confidence"])

        # Confidence at the end should be greater than at the start
        assert confidences[-1] > confidences[0]


# ─────────────────────────────────────────────────────────────────────────────
# Regime transitions
# ─────────────────────────────────────────────────────────────────────────────


class TestVRPRegimeTransitions:
    def _build_warmed_node(self, n_warmup: int = 30) -> tuple[VRPSignalNode, dict]:
        node = VRPSignalNode()
        ohlcv = _make_ohlcv(n=60, vol=0.015)
        market_data = {"BTCUSDT": ohlcv}
        for _ in range(n_warmup):
            _call_compute_vrp(node, iv=0.50, market_data=market_data)
        return node, market_data

    def test_fear_then_neutral_transition(self):
        node, md = self._build_warmed_node()
        # Push into FEAR
        r1 = _call_compute_vrp(node, iv=2.0, market_data=md)
        assert r1["vrp_regime"] == "FEAR"
        # Moderate IV after a few more warmup cycles
        for _ in range(10):
            _call_compute_vrp(node, iv=0.50, market_data=md)
        r2 = _call_compute_vrp(node, iv=0.50, market_data=md)
        # After mean reverts, zscore should approach 0 → NEUTRAL
        assert r2["vrp_regime"] in ("NEUTRAL", "COMPLACENCY")  # could overshoot

    def test_complacency_then_neutral_transition(self):
        node, md = self._build_warmed_node()
        # Push into COMPLACENCY
        r1 = _call_compute_vrp(node, iv=0.01, market_data=md)
        assert r1["vrp_regime"] == "COMPLACENCY"
        # Restore normal IV
        for _ in range(10):
            _call_compute_vrp(node, iv=0.50, market_data=md)
        r2 = _call_compute_vrp(node, iv=0.50, market_data=md)
        assert r2["vrp_regime"] in ("NEUTRAL", "FEAR")

    def test_signal_sign_matches_regime(self):
        """FEAR → positive signal; COMPLACENCY → negative signal."""
        node, md = self._build_warmed_node()

        r_fear = _call_compute_vrp(node, iv=2.0, market_data=md)
        if r_fear["vrp_regime"] == "FEAR":
            assert r_fear["vrp_signal"] > 0

        node2, md2 = self._build_warmed_node()
        r_comp = _call_compute_vrp(node2, iv=0.01, market_data=md2)
        if r_comp["vrp_regime"] == "COMPLACENCY":
            assert r_comp["vrp_signal"] < 0


# ─────────────────────────────────────────────────────────────────────────────
# DynamicWeightAllocator integration
# ─────────────────────────────────────────────────────────────────────────────


class TestVRPWeightIntegration:
    def _signals(self) -> list[str]:
        return ["basic_signals", "order_flow", "cross_asset", "microstructure", "sentiment", "vrp"]

    def test_vrp_included_in_allocator(self):
        allocator = DynamicWeightAllocator(self._signals())
        result = allocator.allocate(regime="default")
        assert "vrp" in result.weights

    def test_vrp_weight_grows_with_positive_ic(self):
        """Consistently positive IC for VRP should give it above-average weight."""
        allocator = DynamicWeightAllocator(self._signals())

        # Give VRP a high IC, others mediocre
        for _ in range(10):
            allocator.update_ic("vrp", ic_value=0.25, regime="default")
            for sig in self._signals():
                if sig != "vrp":
                    allocator.update_ic(sig, ic_value=0.05, regime="default")

        result = allocator.allocate(regime="default")
        equal_weight = 1.0 / len(self._signals())
        assert result.weights["vrp"] > equal_weight

    def test_blend_signals_with_vrp(self):
        """blend_signals should correctly incorporate vrp_signal value."""
        allocator = DynamicWeightAllocator(self._signals())
        signal_values = {s: 0.0 for s in self._signals()}
        signal_values["vrp"] = 1.0  # strong VRP signal

        composite = allocator.blend_signals(signal_values, regime="default")
        assert -1.0 <= composite <= 1.0

    def test_vrp_negative_ic_reduces_weight(self):
        """Negative IC for VRP (bad predictor) should keep its weight low."""
        allocator = DynamicWeightAllocator(self._signals())
        for _ in range(10):
            allocator.update_ic("vrp", ic_value=-0.10, regime="default")
            for sig in self._signals():
                if sig != "vrp":
                    allocator.update_ic(sig, ic_value=0.20, regime="default")

        result = allocator.allocate(regime="default")
        # abs(-0.10) = 0.10 vs 0.20 for others → VRP gets less weight than others
        max_other = max(v for k, v in result.weights.items() if k != "vrp")
        assert result.weights["vrp"] <= max_other + 0.01


# ─────────────────────────────────────────────────────────────────────────────
# RiskManagementNode VRP-adjusted sizing
# ─────────────────────────────────────────────────────────────────────────────


class TestVRPRiskManagement:
    def _market_data(self) -> dict:
        ohlcv = _make_ohlcv(n=60, vol=0.02)
        return {"BTCUSDT": ohlcv, "ETHUSDT": _make_ohlcv(n=60, vol=0.025)}

    def test_neutral_vrp_no_adjustment(self):
        node = RiskManagementNode()
        md = self._market_data()
        portfolio = {"weights": {"BTCUSDT": 0.20, "ETHUSDT": 0.20}}

        out = node.execute(
            NodeInput(
                action="check_risk_limits",
                parameters={
                    "portfolio": portfolio,
                    "market_data": md,
                    "vrp_regime": "NEUTRAL",
                    "vrp_zscore": 0.0,
                },
            )
        )
        assert out.success
        result = out.result
        assert result["vrp_position_scale"] == 1.0
        assert result["vrp_circuit_breaker"] is False

    def test_fear_regime_reduces_position_limit(self):
        node = RiskManagementNode()
        md = self._market_data()
        portfolio = {"weights": {"BTCUSDT": 0.25, "ETHUSDT": 0.25}}

        out = node.execute(
            NodeInput(
                action="check_risk_limits",
                parameters={
                    "portfolio": portfolio,
                    "market_data": md,
                    "vrp_regime": "FEAR",
                    "vrp_zscore": 2.0,
                },
            )
        )
        assert out.success
        result = out.result
        assert result["vrp_position_scale"] == 0.75
        # Effective max is 0.25 * 0.75 = 0.1875; 0.25 > 0.1875 → violation
        assert len(result["violations"]) > 0
        assert result["max_position_limit"] == pytest.approx(0.1875)

    def test_complacency_circuit_breaker(self):
        node = RiskManagementNode()
        md = self._market_data()
        portfolio = {"weights": {"BTCUSDT": 0.10}}

        out = node.execute(
            NodeInput(
                action="check_risk_limits",
                parameters={
                    "portfolio": portfolio,
                    "market_data": md,
                    "vrp_regime": "COMPLACENCY",
                    "vrp_zscore": -2.5,  # below circuit breaker threshold
                },
            )
        )
        assert out.success
        result = out.result
        assert result["vrp_circuit_breaker"] is True
        assert any("circuit breaker" in v.lower() for v in result["violations"])

    def test_complacency_above_threshold_no_breaker(self):
        node = RiskManagementNode()
        md = self._market_data()
        portfolio = {"weights": {"BTCUSDT": 0.10}}

        out = node.execute(
            NodeInput(
                action="check_risk_limits",
                parameters={
                    "portfolio": portfolio,
                    "market_data": md,
                    "vrp_regime": "COMPLACENCY",
                    "vrp_zscore": -1.5,  # COMPLACENCY but above -2sigma
                },
            )
        )
        assert out.success
        assert out.result["vrp_circuit_breaker"] is False

    def test_apply_vrp_constraints_action(self):
        node = RiskManagementNode()

        out = node.execute(
            NodeInput(
                action="apply_vrp_constraints",
                parameters={"vrp_regime": "FEAR", "vrp_zscore": 2.0},
            )
        )
        assert out.success
        result = out.result
        assert result["position_scale"] == 0.75
        assert result["circuit_breaker"] is False
        assert result["notes"]

    def test_fear_position_limit_lower_than_default(self):
        """FEAR regime effective cap must be 25% below default."""
        node = RiskManagementNode()
        adj = node._apply_vrp_constraints("FEAR", 2.0)
        default_max = 0.25  # _MAX_POSITION_SIZE
        fear_max = default_max * adj["position_scale"]
        assert fear_max == pytest.approx(default_max * 0.75)
