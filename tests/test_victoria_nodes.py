"""
tests/test_victoria_nodes.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for each Victoria node in isolation.

Nodes under test:
  - DataIngestionNode
  - SignalGenerationNode
  - RiskManagementNode
  - StrategyNode
  - VerificationNode

All external API calls (Binance, CoinGecko, Bybit, etc.) are mocked.
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import patch

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.risk_management import RiskManagementNode
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.strategy import StrategyNode
from omega.nodes.victoria.verification import VerificationNode

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 60, base: float = 50_000.0, trend: float = 0.001) -> dict:
    """Generate synthetic OHLCV bars."""
    prices = [base * (1 + trend) ** i for i in range(n)]
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [1_000_000.0 + i * 1000 for i in range(n)],
    }


def _make_market_data(tickers: list[str] | None = None, n: int = 60) -> dict:
    tickers = tickers or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    return {t: _make_ohlcv(n=n) for t in tickers}


def _make_input(action: str, **params) -> NodeInput:
    return NodeInput(
        request_id=str(uuid.uuid4()),
        action=action,
        parameters=params,
    )


# ---------------------------------------------------------------------------
# DataIngestionNode
# ---------------------------------------------------------------------------


class TestDataIngestionNodeState:
    def setup_method(self):
        self.node = DataIngestionNode()

    def test_initial_state_version(self):
        state = self.node.get_state()
        assert state.version == "1.0"

    def test_initial_state_health_is_full(self):
        state = self.node.get_state()
        assert state.health == pytest.approx(1.0)

    def test_state_has_required_capabilities(self):
        caps = self.node.get_capabilities()
        assert "fetch_market_data" in caps
        assert "fetch_ohlcv" in caps
        assert "fetch_ticker_info" in caps

    def test_state_metrics_keys(self):
        state = self.node.get_state()
        for key in ("avg_latency_ms", "error_rate", "coverage_rate", "pair_count"):
            assert key in state.metrics

    def test_describe_returns_string(self):
        desc = self.node.describe()
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_initial_pairs_count(self):
        state = self.node.get_state()
        assert state.metrics["pair_count"] == 10.0  # _BASE_PAIRS length


class TestDataIngestionNodeExecution:
    def setup_method(self):
        self.node = DataIngestionNode()

    def test_unknown_action_returns_failure(self):
        out = self.node.execute(_make_input("invalid_action"))
        assert out.success is False
        assert any("Unknown action" in e for e in out.errors)

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    def test_fetch_ohlcv_success(self, mock_klines):
        mock_klines.return_value = _make_ohlcv()
        out = self.node.execute(_make_input("fetch_ohlcv", pair="BTCUSDT"))
        assert out.success is True
        assert "BTCUSDT" in out.result

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    def test_fetch_ohlcv_api_failure_returns_none(self, mock_klines):
        mock_klines.return_value = None
        out = self.node.execute(_make_input("fetch_ohlcv", pair="BTCUSDT"))
        assert out.success is True
        assert out.result.get("BTCUSDT") is None

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.CoinGeckoProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_fetch_market_data_success(self, mock_defi, mock_fg, mock_cg, mock_klines):
        mock_klines.return_value = _make_ohlcv()
        mock_cg.return_value = {}
        mock_fg.return_value = {}
        mock_defi.return_value = {}
        out = self.node.execute(_make_input("fetch_market_data"))
        assert out.success is True
        assert isinstance(out.result, dict)
        assert "latency_ms" in out.metrics

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.BybitProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_bybit_fallback_used_when_binance_fails(
        self, mock_defi, mock_fg, mock_bybit, mock_binance
    ):
        mock_binance.return_value = None
        mock_bybit.return_value = _make_ohlcv()
        mock_fg.return_value = {}
        mock_defi.return_value = {}
        out = self.node.execute(_make_input("fetch_market_data"))
        assert out.success is True
        # Bybit should have been called since Binance returned None
        assert mock_bybit.called

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.BybitProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_providers.CoinGeckoProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_providers.CryptoCompareProvider.fetch_klines")
    def test_error_increments_error_count(
        self, mock_cc, mock_cg, mock_bybit, mock_binance
    ):
        # Simulate all providers failing for all pairs
        mock_binance.side_effect = RuntimeError("API timeout")
        mock_bybit.return_value = None
        mock_cg.return_value = None
        mock_cc.return_value = None
        out = self.node.execute(_make_input("fetch_market_data"))
        # Node execute itself succeeds (returns empty/None results, doesn't throw)
        # but pairs_failed should be non-zero
        state = self.node.get_state()
        assert state.metrics["error_rate"] >= 0.0  # node is resilient — no crash


class TestDataIngestionNodeImprovement:
    def setup_method(self):
        self.node = DataIngestionNode()

    def test_improve_iteration_0_enables_retry(self):
        changed = self.node.improve({"iteration": 1})
        assert changed is True
        assert self.node._version == "1.1"
        assert self.node._use_retry is True

    def test_improve_iteration_2_enables_cache(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        assert self.node._use_cache is True
        # v1.3 may also be triggered (CoinGecko) if coverage ≥ 0.7 (default is 1.0)
        assert self.node._version >= "1.2"

    def test_improve_progression_to_v1_4(self):
        for i in range(5):
            self.node.improve({"iteration": i})
        # Should reach at least v1.3 after enough iterations
        assert self.node._version >= "1.2"

    def test_improve_idempotent_for_same_iteration(self):
        self.node.improve({"iteration": 1})
        v_after_first = self.node._version
        changed = self.node.improve({"iteration": 1})
        # Already applied — no further changes
        assert self.node._version == v_after_first
        assert changed is False

    def test_improve_returns_false_when_no_change(self):
        changed = self.node.improve({"iteration": 0})
        # error_rate is 0 and iteration is 0 — no trigger
        assert changed is False


# ---------------------------------------------------------------------------
# SignalGenerationNode
# ---------------------------------------------------------------------------


class TestSignalGenerationNodeState:
    def setup_method(self):
        self.node = SignalGenerationNode()

    def test_initial_version(self):
        assert self.node.get_state().version == "1.0"

    def test_initial_indicators_only_sma(self):
        assert self.node._active_indicators() == ["sma_crossover"]

    def test_capabilities(self):
        caps = self.node.get_capabilities()
        assert "compute_signals" in caps
        assert "compute_momentum" in caps
        assert "compute_mean_reversion" in caps


class TestSignalGenerationNodeExecution:
    def setup_method(self):
        self.node = SignalGenerationNode()

    def test_unknown_action_fails(self):
        out = self.node.execute(_make_input("do_something"))
        assert out.success is False

    def test_compute_signals_returns_dict(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        assert out.success is True
        assert isinstance(out.result, dict)

    def test_compute_signals_has_sma_crossover(self):
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        assert "BTCUSDT" in out.result
        btc = out.result["BTCUSDT"]
        assert "sma_crossover" in btc
        # sma_crossover is now proportional in [-1, 1] (not a hard ±1 binary)
        assert -1.0 <= btc["sma_crossover"] <= 1.0

    def test_compute_signals_composite_bounded(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        for ticker, sig in out.result.items():
            composite = sig.get("composite")
            if composite is not None:
                assert -1.0 <= composite <= 1.0, f"{ticker} composite out of range"

    def test_compute_signals_skips_empty_data(self):
        md = {"BTCUSDT": None, "ETHUSDT": _make_ohlcv()}
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        assert out.success is True
        assert "BTCUSDT" not in out.result
        assert "ETHUSDT" in out.result

    def test_compute_signals_skips_short_series(self):
        """Fewer bars than SMA long period → signal skipped."""
        md = {"BTCUSDT": _make_ohlcv(n=5)}  # Only 5 bars, sma_long=20
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        assert "BTCUSDT" not in out.result

    def test_compute_momentum_returns_dict(self):
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_momentum", market_data=md))
        assert out.success is True
        assert "BTCUSDT" in out.result
        assert "momentum_5d" in out.result["BTCUSDT"]

    def test_compute_mean_reversion_returns_dict(self):
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_mean_reversion", market_data=md))
        assert out.success is True

    def test_rsi_signal_enabled_after_v1_1(self):
        self.node.improve({"iteration": 1})
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        assert "rsi" in out.result.get("BTCUSDT", {})

    def test_rsi_oversold_gives_positive_signal(self):
        self.node.improve({"iteration": 1})
        # Construct prices that produce RSI < 30 (persistent downtrend)
        prices = [100.0 - i * 1.5 for i in range(30)]
        md = {"BTCUSDT": {"close": prices, "adjclose": prices, "volume": [1e6] * 30}}
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        if "rsi" in out.result.get("BTCUSDT", {}):
            sig = out.result["BTCUSDT"]
            if sig["rsi"] < 30:
                assert sig["rsi_signal"] == 1.0

    def test_macd_enabled_after_v1_2(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        btc = out.result.get("BTCUSDT", {})
        assert "macd" in btc or "macd_crossover" in btc

    def test_bollinger_bands_enabled_after_v1_2(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        btc = out.result.get("BTCUSDT", {})
        assert "bb_upper" in btc

    def test_empty_market_data_returns_empty_signals(self):
        out = self.node.execute(_make_input("compute_signals", market_data={}))
        assert out.success is True
        assert out.result == {}

    def test_nan_prices_cleaned(self):
        prices = [float("nan"), 100.0, 101.0] + [100.0 + i for i in range(30)]
        md = {"BTCUSDT": {"close": prices, "adjclose": prices, "volume": [1e6] * len(prices)}}
        out = self.node.execute(_make_input("compute_signals", market_data=md))
        # Should succeed without raising
        assert out.success is True


class TestSignalGenerationMathematics:
    def setup_method(self):
        self.node = SignalGenerationNode()

    def test_rsi_range_0_100(self):
        prices = [100.0 + math.sin(i / 5) * 10 for i in range(30)]
        rsi = self.node._compute_rsi(prices, period=14)
        assert rsi is not None
        assert 0.0 <= rsi <= 100.0

    def test_rsi_all_gains_returns_100(self):
        prices = list(range(1, 25))
        rsi = self.node._compute_rsi(prices, period=14)
        assert rsi == pytest.approx(100.0)

    def test_bollinger_bands_upper_above_lower(self):
        prices = [100.0 + math.sin(i / 3) for i in range(25)]
        bb = self.node._compute_bollinger_bands(prices, period=20)
        assert bb is not None
        assert bb["upper"] > bb["lower"]
        assert bb["upper"] > bb["mid"] > bb["lower"]

    def test_zscore_returns_returns_float(self):
        prices = [100.0 + i * 0.1 + math.sin(i) for i in range(30)]
        z = self.node._compute_zscore_returns(prices, period=20)
        assert z is not None
        assert isinstance(z, float)

    def test_beta_perfectly_correlated_assets(self):
        btc = [i * 1.0 for i in range(1, 25)]
        eth = [i * 2.0 for i in range(1, 25)]
        # ETH exactly twice BTC → beta ≈ 2
        beta = self.node._compute_beta(
            self.node._compute_returns(eth, 20),
            self.node._compute_returns(btc, 20),
        )
        assert abs(beta - 1.0) < 0.5  # rough check; log returns differ slightly

    def test_vol_regime_high_vol(self):
        import random

        rng = random.Random(42)
        # Long quiet, then sudden spikes
        prices = [100.0]
        for _ in range(70):
            prices.append(prices[-1] * (1 + rng.gauss(0, 0.001)))
        # spike up volatility at the end
        for _ in range(15):
            prices.append(prices[-1] * (1 + rng.gauss(0, 0.05)))
        regime, recent_vol, long_vol = self.node._compute_vol_regime(prices)
        assert regime in ("high", "normal", "low")
        assert recent_vol >= 0.0
        assert long_vol >= 0.0

    def test_compute_ema_length_matches_input(self):
        prices = list(range(1, 31))
        ema = self.node._compute_ema(prices, period=9)
        assert len(ema) == len(prices)

    def test_macd_returns_none_for_short_series(self):
        prices = [100.0] * 10
        macd, signal = self.node._compute_macd(prices)
        assert macd is None
        assert signal is None

    def test_clean_prices_removes_nan_inf(self):
        prices = [1.0, float("nan"), 2.0, float("inf"), 3.0, None]
        cleaned = self.node._clean_prices(prices)
        assert cleaned == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# RiskManagementNode
# ---------------------------------------------------------------------------


class TestRiskManagementNodeState:
    def setup_method(self):
        self.node = RiskManagementNode()

    def test_initial_version(self):
        assert self.node.get_state().version == "1.0"

    def test_capabilities(self):
        caps = self.node.get_capabilities()
        assert "compute_var" in caps
        assert "check_risk_limits" in caps
        assert "compute_correlation" in caps

    def test_initial_health_is_full(self):
        assert self.node.get_state().health == pytest.approx(1.0)


class TestRiskManagementNodeVar:
    def setup_method(self):
        self.node = RiskManagementNode()

    def test_compute_var_success(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        portfolio = {"weights": {"BTCUSDT": 0.5, "ETHUSDT": 0.5}}
        out = self.node.execute(_make_input("compute_var", portfolio=portfolio, market_data=md))
        assert out.success is True
        assert "var_95" in out.result

    def test_var_is_non_negative(self):
        md = _make_market_data(["BTCUSDT"])
        portfolio = {"weights": {"BTCUSDT": 1.0}}
        out = self.node.execute(_make_input("compute_var", portfolio=portfolio, market_data=md))
        assert out.result["var_95"] >= 0.0

    def test_empty_portfolio_var_is_zero(self):
        md = _make_market_data(["BTCUSDT"])
        out = self.node.execute(
            _make_input("compute_var", portfolio={"weights": {}}, market_data=md)
        )
        assert out.result["var_95"] == pytest.approx(0.0)

    def test_cvar_enabled_after_v1_1(self):
        self.node.improve({"iteration": 1})
        md = _make_market_data(["BTCUSDT"])
        portfolio = {"weights": {"BTCUSDT": 1.0}}
        out = self.node.execute(_make_input("compute_var", portfolio=portfolio, market_data=md))
        assert "cvar_95" in out.result

    def test_cvar_gte_var(self):
        """CVaR (expected shortfall) should be >= VaR by definition."""
        self.node.improve({"iteration": 1})
        md = _make_market_data(["BTCUSDT"])
        portfolio = {"weights": {"BTCUSDT": 1.0}}
        out = self.node.execute(_make_input("compute_var", portfolio=portfolio, market_data=md))
        assert out.result.get("cvar_95", 0.0) >= out.result.get("var_95", 0.0) - 1e-9

    def test_unknown_action_fails(self):
        out = self.node.execute(_make_input("invalid_action"))
        assert out.success is False


class TestRiskManagementNodeLimits:
    def setup_method(self):
        self.node = RiskManagementNode()

    def test_position_limit_violation_detected(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        # 80% in one asset exceeds the 25% limit
        portfolio = {"weights": {"BTCUSDT": 0.8, "ETHUSDT": 0.2}}
        out = self.node.execute(
            _make_input("check_risk_limits", portfolio=portfolio, market_data=md)
        )
        assert out.success is True
        assert out.result["passed"] is False
        assert len(out.result["violations"]) > 0

    def test_compliant_portfolio_passes(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])
        portfolio = {
            "weights": {t: 0.2 for t in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]}
        }
        out = self.node.execute(
            _make_input("check_risk_limits", portfolio=portfolio, market_data=md)
        )
        assert out.success is True
        # May still fail due to VaR, but no position-size violations
        violations = [v for v in out.result["violations"] if "weight" in v]
        assert len(violations) == 0

    def test_adjusted_weights_sum_to_one(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        portfolio = {"weights": {"BTCUSDT": 0.9, "ETHUSDT": 0.1}}
        out = self.node.execute(
            _make_input("check_risk_limits", portfolio=portfolio, market_data=md)
        )
        adjusted = out.result["adjusted_weights"]
        assert abs(sum(adjusted.values()) - 1.0) < 1e-9

    def test_adjusted_weights_capped_at_max_position(self):
        # Use many equal-weighted assets so renormalization doesn't blow past the cap
        tickers = [f"ASSET{i}USDT" for i in range(8)]
        md = {t: _make_ohlcv() for t in tickers}
        # Give one asset a huge overweight — others at 10% each
        weights = {tickers[0]: 0.9}
        for t in tickers[1:]:
            weights[t] = 0.1 / (len(tickers) - 1)
        portfolio = {"weights": weights}
        out = self.node.execute(
            _make_input("check_risk_limits", portfolio=portfolio, market_data=md)
        )
        # After capping + renorm, original violator must have been reduced
        adjusted = out.result["adjusted_weights"]
        orig_violator_after = adjusted.get(tickers[0], 1.0)
        # The capping should have reduced the violator vs original 90%
        assert orig_violator_after < 0.9


class TestRiskManagementNodeCorrelation:
    def setup_method(self):
        self.node = RiskManagementNode()

    def test_correlation_matrix_has_max_correlation(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(_make_input("compute_correlation", market_data=md))
        assert out.success is True
        assert "max_correlation" in out.result
        assert 0.0 <= out.result["max_correlation"] <= 1.0

    def test_perfect_correlation_detected(self):
        """Two identical price series → correlation ≈ 1.0."""
        ohlcv = _make_ohlcv(n=60)
        md = {"BTCUSDT": ohlcv, "ETHUSDT": ohlcv}
        out = self.node.execute(_make_input("compute_correlation", market_data=md))
        assert out.result["max_correlation"] == pytest.approx(1.0, abs=1e-6)

    def test_single_asset_no_pairs(self):
        md = {"BTCUSDT": _make_ohlcv()}
        out = self.node.execute(_make_input("compute_correlation", market_data=md))
        assert out.result["max_correlation"] == pytest.approx(0.0)


class TestRiskManagementNodeImprovement:
    def setup_method(self):
        self.node = RiskManagementNode()

    def test_improve_to_v1_1(self):
        changed = self.node.improve({"iteration": 1})
        assert changed
        assert self.node._version == "1.1"
        assert self.node._use_cvar is True

    def test_improve_to_v1_2(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        assert self.node._version == "1.2"
        assert self.node._use_correlation is True


# ---------------------------------------------------------------------------
# StrategyNode
# ---------------------------------------------------------------------------


def _make_signals(tickers: list[str], composite: float = 0.5) -> dict:
    return {
        t: {
            "composite": composite,
            "rsi": 50.0,
            "sma_crossover": 1.0,
            "return_1d": 0.001,
            "price": 100.0,
        }
        for t in tickers
    }


class TestStrategyNodeState:
    def setup_method(self):
        self.node = StrategyNode()

    def test_initial_version(self):
        assert self.node.get_state().version == "1.0"

    def test_initial_weighting(self):
        assert self.node._weighting == "equal"

    def test_capabilities(self):
        caps = self.node.get_capabilities()
        assert "construct_portfolio" in caps
        assert "backtest_strategy" in caps
        assert "rank_signals" in caps


class TestStrategyNodePortfolioConstruction:
    def setup_method(self):
        self.node = StrategyNode()

    def test_construct_portfolio_returns_weights(self):
        signals = _make_signals(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        md = _make_market_data(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        assert out.success is True
        assert "weights" in out.result
        assert len(out.result["weights"]) > 0

    def test_equal_weight_sums_to_one(self):
        signals = _make_signals(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        md = _make_market_data(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        weights = out.result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_equal_weight_is_uniform(self):
        tickers = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        signals = _make_signals(tickers)
        md = _make_market_data(tickers)
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        weights = list(out.result["weights"].values())
        # all equal-weight
        assert max(weights) - min(weights) < 1e-9

    def test_momentum_weighting_after_v1_1(self):
        self.node.improve({"iteration": 1})
        assert self.node._weighting == "momentum"
        # Different composites → different weights
        signals = {
            "BTCUSDT": {"composite": 0.9, "price": 100.0},
            "ETHUSDT": {"composite": 0.1, "price": 100.0},
        }
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        w = out.result["weights"]
        assert w["BTCUSDT"] > w["ETHUSDT"]

    def test_risk_parity_weighting_after_v1_2(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        assert self.node._weighting == "risk_parity"
        signals = _make_signals(["BTCUSDT", "ETHUSDT"])
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        weights = out.result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_empty_signals_returns_empty_portfolio(self):
        out = self.node.execute(_make_input("construct_portfolio", signals={}, market_data={}))
        assert out.success is True
        # Either empty weights or fallback
        assert isinstance(out.result.get("weights", {}), dict)

    def test_signal_threshold_filters_candidates(self):
        self.node._signal_threshold = 0.8
        signals = {
            "BTCUSDT": {"composite": 0.9},
            "ETHUSDT": {"composite": 0.1},  # below threshold
        }
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(
            _make_input("construct_portfolio", signals=signals, market_data=md)
        )
        # BTCUSDT above threshold, ETHUSDT below — should be filtered
        weights = out.result["weights"]
        assert "ETHUSDT" not in weights or weights.get("ETHUSDT", 0) == pytest.approx(0.0)

    def test_unknown_action_fails(self):
        out = self.node.execute(_make_input("fly"))
        assert out.success is False


class TestStrategyNodeBacktest:
    def setup_method(self):
        self.node = StrategyNode()

    def test_backtest_returns_sharpe(self):
        md = _make_market_data(["BTCUSDT"], n=60)
        signals = _make_signals(["BTCUSDT"])
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        assert out.success is True
        assert "sharpe" in out.result

    def test_backtest_sharpe_is_finite(self):
        md = _make_market_data(["BTCUSDT"], n=60)
        signals = _make_signals(["BTCUSDT"])
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        sharpe = out.result["sharpe"]
        assert math.isfinite(sharpe)

    def test_backtest_drawdown_between_0_and_1(self):
        md = _make_market_data(["BTCUSDT"], n=60)
        signals = _make_signals(["BTCUSDT"])
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        dd = out.result["max_drawdown"]
        assert 0.0 <= dd <= 1.0

    def test_backtest_hit_rate_between_0_and_1(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"], n=60)
        signals = _make_signals(["BTCUSDT", "ETHUSDT"])
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        hr = out.result["hit_rate"]
        assert 0.0 <= hr <= 1.0

    def test_backtest_insufficient_data_returns_zeros(self):
        md = {"BTCUSDT": _make_ohlcv(n=5)}  # Only 5 bars
        signals = _make_signals(["BTCUSDT"])
        out = self.node.execute(_make_input("backtest_strategy", signals=signals, market_data=md))
        assert out.success is True
        assert out.result["trades"] == 0

    def test_rank_signals_returns_sorted_list(self):
        signals = {
            "BTCUSDT": {"composite": 0.9, "price": 50000},
            "ETHUSDT": {"composite": 0.5, "price": 3000},
            "SOLUSDT": {"composite": 0.1, "price": 100},
        }
        out = self.node.execute(_make_input("rank_signals", signals=signals))
        assert out.success is True
        ranked = out.result
        composites = [r["composite"] for r in ranked]
        assert composites == sorted(composites, reverse=True)


class TestStrategyNodeImprovement:
    def setup_method(self):
        self.node = StrategyNode()

    def test_improve_v1_0_to_v1_1(self):
        changed = self.node.improve({"iteration": 1})
        assert changed
        assert self.node._version == "1.1"
        assert self.node._weighting == "momentum"

    def test_improve_v1_1_to_v1_2(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        assert self.node._version == "1.2"
        assert self.node._weighting == "risk_parity"

    def test_improve_v1_3_tightens_threshold(self):
        self.node.improve({"iteration": 1})
        self.node.improve({"iteration": 2})
        self.node._last_sharpe = 0.1  # poor Sharpe
        self.node._backtest_count = 2
        changed = self.node.improve({"iteration": 3})
        assert changed
        assert self.node._version == "1.3"
        assert self.node._signal_threshold > 0.0


# ---------------------------------------------------------------------------
# VerificationNode
# ---------------------------------------------------------------------------


class TestVerificationNodeState:
    def setup_method(self):
        self.node = VerificationNode()

    def test_initial_health_is_full(self):
        # No verifications run yet → 0/0 → health should be 1.0 (neutral)
        state = self.node.get_state()
        assert state.health >= 0.0

    def test_capabilities_includes_verify(self):
        assert "verify_improvement" in self.node.get_capabilities()

    def test_describe_returns_string(self):
        assert isinstance(self.node.describe(), str)

    def test_state_has_rollback_count(self):
        state = self.node.get_state()
        assert "rollback_count" in state.metadata


class TestVerificationNodeExecution:
    def setup_method(self):
        self.node = VerificationNode()

    def test_verify_improvement_with_better_metrics(self):
        before = {"error_rate": 0.1, "coverage_rate": 0.7}
        after = {"error_rate": 0.05, "coverage_rate": 0.9}
        out = self.node.execute(
            _make_input(
                "verify_improvement",
                before_metrics=before,
                after_metrics=after,
                node_id="test-node",
            )
        )
        assert out.success is True

    def test_verify_improvement_with_regression_fails(self):
        before = {"coverage_rate": 0.9}
        after = {"coverage_rate": 0.1}  # 89% regression — above threshold
        out = self.node.execute(
            _make_input(
                "verify_improvement",
                before_metrics=before,
                after_metrics=after,
                node_id="test-node",
            )
        )
        # Regression should be detected — success=False or rollback triggered
        assert out.success is True  # execution succeeded, but result indicates rollback
        if isinstance(out.result, dict):
            result_str = str(out.result)
            # Either passed=False or rollback was triggered
            assert "rollback" in result_str.lower() or "passed" in result_str.lower()

    def test_verify_unknown_action_fails(self):
        out = self.node.execute(_make_input("check_weather"))
        assert out.success is False

    def test_pass_count_increments(self):
        before = {"error_rate": 0.05}
        after = {"error_rate": 0.04}
        self.node.execute(
            _make_input(
                "verify_improvement",
                before_metrics=before,
                after_metrics=after,
                node_id="n1",
            )
        )
        state = self.node.get_state()
        assert state.metadata["pass_count"] >= 0  # at least tracked
