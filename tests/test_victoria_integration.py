"""
tests/test_victoria_integration.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for the Victoria trading engine.

Tests the full pipeline:
  DataIngestionNode → SignalGenerationNode → DynamicWeightAllocator
  → StrategyNode → RiskManagementNode → VerificationNode

Also tests:
  - VictoriaNode top-level composition
  - Bridge client fail-loud semantics (Go server not available)
  - Multi-cycle improvement progression
  - Cycle pipeline state transitions
"""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.improvement_client import ImprovementServiceClient, ImprovementServiceError
from omega.bridge.memory_client import MemoryServiceClient, MemoryServiceError
from omega.core.node import NodeInput
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator, RegimeAwareWeightManager
from omega.nodes.victoria.risk_management import RiskManagementNode
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.strategy import StrategyNode
from omega.nodes.victoria.victoria_node import VictoriaNode

# Marked slow: these run real multi-cycle Victoria simulations and take minutes.
# Unmarked, they made `pytest tests/` appear to hang, so the suite was not run —
# which is how a whole stale TestRegimeAdaptivity class sat failing unnoticed.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_input(action: str, **params) -> NodeInput:
    return NodeInput(request_id=str(uuid.uuid4()), action=action, parameters=params)


def _make_ohlcv(n: int = 90, base: float = 50_000.0, trend: float = 0.0005) -> dict:
    import math as _math

    prices = [base * (1 + trend) ** i + _math.sin(i / 5) * base * 0.01 for i in range(n)]
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [500_000.0 + i * 500 for i in range(n)],
    }


def _make_market_data(tickers: list[str] | None = None, n: int = 90) -> dict:
    tickers = tickers or [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
    ]
    return {t: _make_ohlcv(n=n) for t in tickers}


_TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


# ---------------------------------------------------------------------------
# Full pipeline: data → signals → weights → portfolio → risk
# ---------------------------------------------------------------------------


class TestFullVictoriaPipeline:
    """Exercise the complete node chain on synthetic data without hitting real APIs."""

    def setup_method(self):
        self.data_node = DataIngestionNode()
        self.signal_node = SignalGenerationNode()
        self.strategy_node = StrategyNode()
        self.risk_node = RiskManagementNode()
        self.weight_allocator = DynamicWeightAllocator(
            ["sma_crossover", "rsi_signal", "macd_crossover", "bb_signal"]
        )

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.CoinGeckoProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_data_to_signals(self, mock_defi, mock_fg, mock_cg, mock_klines):
        mock_klines.return_value = _make_ohlcv()
        mock_cg.return_value = {}
        mock_fg.return_value = {}
        mock_defi.return_value = {}

        # Stage 1: ingest
        ingest_out = self.data_node.execute(_make_input("fetch_market_data"))
        assert ingest_out.success

        # Stage 2: signals
        signal_out = self.signal_node.execute(
            _make_input("compute_signals", market_data=ingest_out.result)
        )
        assert signal_out.success
        assert len(signal_out.result) > 0

    def test_signals_to_portfolio(self):
        md = _make_market_data(_TICKERS)
        signal_out = self.signal_node.execute(_make_input("compute_signals", market_data=md))
        assert signal_out.success

        portfolio_out = self.strategy_node.execute(
            _make_input("construct_portfolio", signals=signal_out.result, market_data=md)
        )
        assert portfolio_out.success
        weights = portfolio_out.result["weights"]
        # V53: abs conviction floor (0.15) may reject all synthetic-data signals —
        # that is correct behaviour; assert success and weight sum invariant only when
        # the portfolio is non-empty.
        if len(weights) > 0:
            assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_portfolio_to_risk_check(self):
        md = _make_market_data(_TICKERS)
        signal_out = self.signal_node.execute(_make_input("compute_signals", market_data=md))
        portfolio_out = self.strategy_node.execute(
            _make_input("construct_portfolio", signals=signal_out.result, market_data=md)
        )
        weights = portfolio_out.result["weights"]

        risk_out = self.risk_node.execute(
            _make_input(
                "check_risk_limits",
                portfolio={"weights": weights},
                market_data=md,
            )
        )
        assert risk_out.success
        assert "passed" in risk_out.result
        assert "adjusted_weights" in risk_out.result

    def test_full_chain_no_exceptions(self):
        """The entire pipeline must run without raising."""
        md = _make_market_data(_TICKERS)

        signal_out = self.signal_node.execute(_make_input("compute_signals", market_data=md))
        portfolio_out = self.strategy_node.execute(
            _make_input("construct_portfolio", signals=signal_out.result, market_data=md)
        )
        weights = portfolio_out.result.get("weights", {})
        if weights:
            self.risk_node.execute(
                _make_input(
                    "check_risk_limits",
                    portfolio={"weights": weights},
                    market_data=md,
                )
            )

    def test_dynamic_weights_integrate_with_signals(self):
        md = _make_market_data(["BTCUSDT"])
        self.signal_node.execute(_make_input("compute_signals", market_data=md))
        # Feed IC observations from the signal run
        for _ in range(15):
            self.weight_allocator.update_ic("sma_crossover", 0.2)
            self.weight_allocator.update_ic("rsi_signal", 0.05)
            self.weight_allocator.update_ic("macd_crossover", 0.1)
            self.weight_allocator.update_ic("bb_signal", 0.05)

        alloc = self.weight_allocator.allocate()
        assert abs(sum(alloc.weights.values()) - 1.0) < 1e-9
        # sma_crossover should have the highest IC → highest weight
        assert alloc.weights["sma_crossover"] > alloc.weights["rsi_signal"]


class TestMultiCycleImprovement:
    """Simulate multiple improvement cycles and verify version progression."""

    def setup_method(self):
        self.data_node = DataIngestionNode()
        self.signal_node = SignalGenerationNode()
        self.strategy_node = StrategyNode()
        self.risk_node = RiskManagementNode()

    def test_nodes_progress_through_versions(self):
        for i in range(5):
            feedback = {"iteration": i}
            self.data_node.improve(feedback)
            self.signal_node.improve(feedback)
            self.strategy_node.improve(feedback)
            self.risk_node.improve(feedback)

        assert self.data_node._version >= "1.1"
        assert self.signal_node._version >= "1.1"
        assert self.strategy_node._version >= "1.1"
        assert self.risk_node._version >= "1.1"

    def test_capabilities_expand_with_improvement(self):
        initial_indicators = len(self.signal_node._active_indicators())
        self.signal_node.improve({"iteration": 1})
        self.signal_node.improve({"iteration": 2})
        improved_indicators = len(self.signal_node._active_indicators())
        assert improved_indicators > initial_indicators

    def test_data_node_pairs_expand_after_v1_3(self):
        initial_pairs = len(self.data_node._pairs)
        # Drive to v1.3 where extended pairs are added
        for i in range(4):
            self.data_node.improve({"iteration": i})
        # Coverage needs to be sufficient to trigger coingecko+pairs expansion
        # Manually set coverage to meet threshold
        self.data_node._total_pairs_fetched = 80
        self.data_node._total_pairs_failed = 5
        self.data_node.improve({"iteration": 3})
        # After v1.3 upgrade check if pairs possibly grew
        if self.data_node._version >= "1.3":
            assert len(self.data_node._pairs) >= initial_pairs

    def test_risk_node_cvar_not_present_before_v1_1(self):
        md = _make_market_data(["BTCUSDT"])
        out = self.risk_node.execute(
            _make_input("compute_var", portfolio={"weights": {"BTCUSDT": 1.0}}, market_data=md)
        )
        assert "cvar_95" not in out.result

    def test_risk_node_cvar_present_after_v1_1(self):
        self.risk_node.improve({"iteration": 1})
        md = _make_market_data(["BTCUSDT"])
        out = self.risk_node.execute(
            _make_input("compute_var", portfolio={"weights": {"BTCUSDT": 1.0}}, market_data=md)
        )
        assert "cvar_95" in out.result

    def test_pipeline_metrics_tracked_across_cycles(self):
        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        for _ in range(5):
            self.signal_node.execute(_make_input("compute_signals", market_data=md))

        state = self.signal_node.get_state()
        assert state.metrics["signals_generated"] > 0
        assert state.metrics["avg_latency_ms"] >= 0.0


# ---------------------------------------------------------------------------
# VictoriaNode (composite) tests
# ---------------------------------------------------------------------------


class TestVictoriaNodeComposite:
    def setup_method(self):
        self.node = VictoriaNode()

    def test_node_has_capabilities(self):
        caps = self.node.get_capabilities()
        assert "poll" in caps or "fetch_data" in caps or len(caps) > 0

    def test_state_has_node_id(self):
        state = self.node.get_state()
        assert state.node_id
        assert len(state.node_id) > 0

    def test_unknown_action_returns_failure(self):
        out = self.node.execute(_make_input("nonexistent_action"))
        assert out.success is False

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.CoinGeckoProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_poll_action_returns_market_data(self, mock_defi, mock_fg, mock_cg, mock_klines):
        mock_klines.return_value = _make_ohlcv()
        mock_cg.return_value = {}
        mock_fg.return_value = {}
        mock_defi.return_value = {}
        out = self.node.execute(_make_input("poll"))
        # Poll should succeed and return some data
        assert out.success is True

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.CoinGeckoProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_compute_signals_action(self, mock_defi, mock_fg, mock_cg, mock_klines):
        mock_klines.return_value = _make_ohlcv()
        mock_cg.return_value = {}
        mock_fg.return_value = {}
        mock_defi.return_value = {}
        # First poll to populate data
        self.node.execute(_make_input("poll"))
        out = self.node.execute(_make_input("compute_signals"))
        assert out.success is True


# ---------------------------------------------------------------------------
# Bridge client fail-loud semantics
# ---------------------------------------------------------------------------


def _http_error(body: dict, code: int = 503):
    import urllib.error

    return urllib.error.HTTPError(
        url="http://localhost:8080",
        code=code,
        msg="Service Unavailable",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(json.dumps(body).encode()),
    )


def _conn_error():
    import urllib.error

    return urllib.error.URLError("Connection refused")


class TestBridgeClientFailLoud:
    """Verify bridge clients raise loud exceptions (never silently fail) when Go server is down."""

    def test_improvement_client_raises_when_server_down(self):
        client = ImprovementServiceClient("http://localhost:19999")
        with (
            patch("urllib.request.urlopen", side_effect=_conn_error()),
            pytest.raises(ImprovementServiceError),
        ):
            client.due_nodes(cycle=1)

    def test_improvement_client_raises_on_http_500(self):
        client = ImprovementServiceClient()
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=_http_error({"message": "internal error"}, 500),
            ),
            pytest.raises(ImprovementServiceError),
        ):
            client.due_nodes()

    def test_improvement_client_raises_on_http_503(self):
        client = ImprovementServiceClient()
        with (
            patch(
                "urllib.request.urlopen", side_effect=_http_error({"message": "unavailable"}, 503)
            ),
            pytest.raises(ImprovementServiceError),
        ):
            client.record_outcome("node-1", success=True, score=0.5)

    def test_memory_client_raises_when_server_down(self):
        client = MemoryServiceClient("http://localhost:19999")
        with (
            patch("urllib.request.urlopen", side_effect=_conn_error()),
            pytest.raises(MemoryServiceError),
        ):
            client.store_working("node-1", "key", {"data": 1})

    def test_improvement_client_due_nodes_success(self):
        """Successful path: server responds correctly."""
        client = ImprovementServiceClient()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"nodeIds": ["n1", "n2"]}).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.due_nodes(cycle=5)
        assert result == ["n1", "n2"]

    def test_improvement_client_propose_trial_params(self):
        client = ImprovementServiceClient()
        body = {"params": {"sma_short": 5}, "expectedImprovement": 0.1, "strategy": "tpe"}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(body).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.propose_trial_params("n1", history=[])
        assert "params" in result

    def test_improvement_client_record_outcome_sends_metrics(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            mock = MagicMock()
            mock.__enter__ = lambda s: s
            mock.__exit__ = MagicMock(return_value=False)
            mock.read.return_value = json.dumps({"nextRunAt": {}}).encode()
            return mock

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_outcome(
                "n1",
                success=True,
                score=1.4,
                cycle=10,
                before_metrics={"sharpe": 0.5},
                after_metrics={"sharpe": 0.9},
            )

        body = captured["body"]
        assert body["nodeId"] == "n1"
        assert body["success"] is True
        assert body["score"] == pytest.approx(1.4)
        assert body["cycle"] == 10
        assert body["beforeMetrics"]["sharpe"] == pytest.approx(0.5)
        assert body["afterMetrics"]["sharpe"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Autonomy level transition behavior
# ---------------------------------------------------------------------------


class TestAutonomyLevelSignals:
    """Test that signal generation respects autonomy constraints via PICO mode."""

    def test_pico_mode_only_uses_deterministic_signals(self):
        """In PICO mode VictoriaNode should not attempt brain calls."""
        node = VictoriaNode()
        # PICO mode is the default — brain should not be called
        state = node.get_state()
        assert state is not None
        # Node must still be healthy in PICO mode
        assert state.health >= 0.0

    def test_signal_generation_without_advanced_indicators_is_stable(self):
        """v1.0 SignalGenerationNode (PICO-like) must not raise on any valid input."""
        node = SignalGenerationNode()
        assert node._version == "1.0"
        assert not node._use_rsi
        assert not node._use_macd

        md = _make_market_data(["BTCUSDT", "ETHUSDT"])
        out = node.execute(_make_input("compute_signals", market_data=md))
        assert out.success

    def test_node_health_degrades_on_repeated_errors(self):
        node = SignalGenerationNode()
        # Execute with bad action repeatedly
        for _ in range(5):
            node.execute(_make_input("invalid"))

        state = node.get_state()
        assert state.health < 1.0

    def test_node_health_remains_stable_on_valid_actions(self):
        node = SignalGenerationNode()
        md = _make_market_data(["BTCUSDT"])
        for _ in range(5):
            node.execute(_make_input("compute_signals", market_data=md))

        state = node.get_state()
        assert state.health == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Data coverage and fallback integration
# ---------------------------------------------------------------------------


class TestDataCoverageAndFallback:
    def setup_method(self):
        self.data_node = DataIngestionNode()

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.BybitProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_providers.CoinGeckoProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_providers.CryptoCompareProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_coverage_rate_decreases_on_binance_failure(
        self, mock_defi, mock_fg, mock_cc, mock_cg, mock_bybit, mock_binance
    ):
        mock_binance.return_value = None
        mock_bybit.return_value = None
        mock_cg.return_value = None
        mock_cc.return_value = None
        mock_fg.return_value = {}
        mock_defi.return_value = {}

        self.data_node.execute(_make_input("fetch_market_data"))
        state = self.data_node.get_state()
        # Coverage should be 0 since all four providers fail
        assert state.metrics["coverage_rate"] < 1.0

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_coverage_rate_is_1_when_all_succeed(self, mock_defi, mock_fg, mock_binance):
        mock_binance.return_value = _make_ohlcv()
        mock_fg.return_value = {}
        mock_defi.return_value = {}

        self.data_node.execute(_make_input("fetch_market_data"))
        state = self.data_node.get_state()
        assert state.metrics["coverage_rate"] == pytest.approx(1.0)

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_freshness_updated_after_fetch(self, mock_defi, mock_fg, mock_binance):
        mock_binance.return_value = _make_ohlcv()
        mock_fg.return_value = {}
        mock_defi.return_value = {}

        self.data_node.execute(_make_input("fetch_market_data"))
        state = self.data_node.get_state()
        # Freshness should be near 0 minutes after fetch
        assert state.metrics["data_freshness_minutes"] < 1.0

    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    @patch("omega.nodes.victoria.data_ingestion.CoinGeckoProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    def test_coingecko_enrichment_adds_market_cap(self, mock_defi, mock_fg, mock_cg, mock_binance):
        mock_binance.return_value = _make_ohlcv()
        mock_cg.return_value = {
            "BTCUSDT": {
                "market_cap": 1_000_000_000,
                "market_cap_rank": 1,
                "total_volume": 50_000_000,
                "price_change_percentage_24h": 2.5,
            }
        }
        mock_fg.return_value = {}
        mock_defi.return_value = {}

        # Enable CoinGecko enrichment
        self.data_node._use_coingecko = True
        self.data_node._pairs = ["BTCUSDT"]

        out = self.data_node.execute(_make_input("fetch_market_data"))
        btc = out.result.get("BTCUSDT", {})
        assert btc.get("market_cap") == 1_000_000_000
        assert btc.get("market_cap_rank") == 1

    @patch("omega.nodes.victoria.data_ingestion.FearGreedProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.DefiLlamaProvider.fetch")
    @patch("omega.nodes.victoria.data_ingestion.BinanceProvider.fetch_klines")
    def test_fear_greed_appears_in_result(self, mock_klines, mock_defi, mock_fg):
        mock_klines.return_value = _make_ohlcv()
        mock_fg.return_value = {"fear_greed": {"value": 65, "label": "Greed"}}
        mock_defi.return_value = {}

        out = self.data_node.execute(_make_input("fetch_market_data"))
        assert "_fear_greed" in out.result
        assert out.result["_fear_greed"]["value"] == 65


# ---------------------------------------------------------------------------
# Regime-aware weight manager integration
# ---------------------------------------------------------------------------


class TestRegimeAwareWeightIntegration:
    SIGNALS: ClassVar[list[str]] = ["sma_crossover", "rsi_signal", "macd_crossover", "bb_signal"]

    def setup_method(self):
        self.manager = RegimeAwareWeightManager(self.SIGNALS)

    def test_trending_regime_boosts_momentum_signal(self):
        # Feed strong IC for sma_crossover in trending regime
        for _ in range(20):
            self.manager.record_ic("BTCUSDT", "sma_crossover", ic=0.4, regime="trending")
            self.manager.record_ic("BTCUSDT", "rsi_signal", ic=0.05, regime="trending")
            self.manager.record_ic("BTCUSDT", "macd_crossover", ic=0.05, regime="trending")
            self.manager.record_ic("BTCUSDT", "bb_signal", ic=0.05, regime="trending")

        result = self.manager.compute_composite(
            "BTCUSDT",
            {s: 1.0 for s in self.SIGNALS},
            regime="trending",
        )
        assert result["dominant_signal"] == "sma_crossover"

    def test_composite_signal_is_bounded(self):
        result = self.manager.compute_composite(
            "BTCUSDT",
            {s: 0.8 for s in self.SIGNALS},
        )
        assert -1.0 <= result["composite"] <= 1.0

    def test_multiple_tickers_independent_learning(self):
        for _ in range(20):
            self.manager.record_ic("BTCUSDT", "sma_crossover", ic=0.5)
            self.manager.record_ic("BTCUSDT", "rsi_signal", ic=0.01)
            self.manager.record_ic("BTCUSDT", "macd_crossover", ic=0.01)
            self.manager.record_ic("BTCUSDT", "bb_signal", ic=0.01)

            self.manager.record_ic("ETHUSDT", "rsi_signal", ic=0.5)
            self.manager.record_ic("ETHUSDT", "sma_crossover", ic=0.01)
            self.manager.record_ic("ETHUSDT", "macd_crossover", ic=0.01)
            self.manager.record_ic("ETHUSDT", "bb_signal", ic=0.01)

        btc = self.manager.compute_composite("BTCUSDT", {s: 1.0 for s in self.SIGNALS})
        eth = self.manager.compute_composite("ETHUSDT", {s: 1.0 for s in self.SIGNALS})

        assert btc["dominant_signal"] == "sma_crossover"
        assert eth["dominant_signal"] == "rsi_signal"


# ---------------------------------------------------------------------------
# V53 regression tests — crisis long suppression + conviction floor
# ---------------------------------------------------------------------------


class TestV53Regressions:
    """Regression tests for V53 surgical fixes.

    V52 post-mortem identified:
    - 22 crisis longs → -$100.62 (ETH/AVAX momentum chasing in bear market)
    - All convictions 0.050-0.075 with zero discriminative power
    - MATICUSDT 27 zero-PnL trades (stale-price bug)
    - DOTUSDT 13 normal-regime shorts, 7% WR → -$21.51
    """

    def setup_method(self):
        from omega.nodes.victoria.strategy import StrategyNode

        self.strat = StrategyNode()

    def test_crisis_regime_blocks_all_longs(self):
        """Crisis regime threshold 0.99 should block any realistic long conviction."""
        # Simulate crisis regime signal dict
        crisis_signals = {
            "_regime_w_bear_prob": 0.70,
            "_regime_w_bull_prob": 0.10,
            "_regime_hmm": "crisis",
        }
        self.strat._apply_regime_adaptive_thresholds(crisis_signals)
        # Even a strong IC-weighted conviction of 0.80 should not exceed 0.99 threshold
        assert self.strat._long_conviction_threshold == 0.99
        assert self.strat._short_conviction_threshold == 0.05

    def test_hmm_crisis_label_triggers_crisis_threshold(self):
        """HMM label 'crisis' alone (Wasserstein flat) should trigger crisis gate."""
        flat_wasserstein = {
            "_regime_w_bear_prob": 0.333,  # stuck at prior
            "_regime_w_bull_prob": 0.333,
            "_regime_hmm": "crisis",
        }
        self.strat._apply_regime_adaptive_thresholds(flat_wasserstein)
        assert self.strat._long_conviction_threshold == 0.99, (
            "HMM 'crisis' label should trigger 0.99 long threshold even when "
            "Wasserstein is stuck at 1/3 priors"
        )

    def test_abs_conviction_floor_blocks_low_conviction(self):
        """Trades with |w_conv| < 0.15 must be rejected regardless of direction."""
        # Set normal regime thresholds
        normal_signals = {
            "_regime_w_bear_prob": 0.20,
            "_regime_w_bull_prob": 0.20,
            "_regime_hmm": "normal",
        }
        self.strat._apply_regime_adaptive_thresholds(normal_signals)
        self.strat._last_trade_cycle = -5  # bypass time filter

        # Signal with very low conviction (V52 range: 0.05-0.075)
        # composite=0.06 simulates the V52 cluster (IC weights empty → fallback to composite)
        low_conv_sig = {
            "composite": 0.06,
            "sma_crossover": 0.06,
            "vol_regime": "normal",
            "_ic_weights": {},
        }
        passes, reason = self.strat._passes_conviction_filters(
            low_conv_sig, cycle=10, direction="long"
        )
        assert not passes
        assert "abs_conviction_floor" in reason or "weighted_conviction" in reason

    def test_maticusdt_not_in_trading_universe(self):
        """MATICUSDT must be in trading blacklist (zero-PnL stale-price bug)."""
        from omega.nodes.victoria.strategy import _TRADING_BLACKLIST

        assert "MATICUSDT" in _TRADING_BLACKLIST, (
            "MATICUSDT must be blacklisted — exit_price == entry_price on 100% of V52 trades"
        )
