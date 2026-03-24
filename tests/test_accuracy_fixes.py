"""
tests/test_accuracy_fixes.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the three accuracy-gap wiring fixes:

  Fix 1 — quality_score from SIGNAL_RESEARCH → Prometheus health gauge
  Fix 2 — construct_portfolio → PaperTradingEngine.execute_proposals()
  Fix 3 — DebateGate → real risk_debate() instead of stub
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signals(
    n_positive: int = 3,
    n_negative: int = 1,
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Return a synthetic signals dict matching VictoriaNode output format."""
    signals: dict[str, Any] = {}
    signal_names = [
        "basic_signals",
        "order_flow",
        "cross_asset",
        "microstructure",
        "sentiment",
        "vrp",
    ]
    for i in range(n_positive):
        name = signal_names[i % len(signal_names)]
        signals[name] = {
            "value": 0.5,
            "confidence": confidence,
            "regime_tag": "neutral",
            "raw": {},
        }
    for j in range(n_negative):
        name = f"neg_signal_{j}"
        signals[name] = {"value": -0.4, "confidence": 0.6, "regime_tag": "neutral", "raw": {}}
    # Private keys should be ignored
    signals["_weights"] = {"basic_signals": 0.3}
    signals["_quality_score"] = 0.72
    signals["_signal_count"] = float(n_positive + n_negative)
    signals["_avg_confidence"] = confidence
    return signals


def _make_market_data(tickers: list[str] | None = None, n: int = 30) -> dict[str, Any]:
    tickers = tickers or ["BTCUSDT", "ETHUSDT"]
    base = 50_000.0
    prices = [base * (1.001**i) for i in range(n)]
    bar = {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [1_000_000.0] * n,
    }
    return {t: bar for t in tickers}


# ===========================================================================
# Fix 1 — quality_score wiring in orchestrator_v2 pipeline handler
# ===========================================================================


class TestFix1QualityScoreSurfaced:
    """quality_score from SIGNAL_RESEARCH result is promoted into resp_metrics."""

    def test_quality_score_in_resp_metrics(self):
        """_quality_score in out.result must appear as quality_score in resp_metrics."""
        from omega.core.orchestrator_v2 import OmegaOrchestrator
        from omega.nodes.victoria.victoria_node import VictoriaNode

        orch = OmegaOrchestrator(name="test-qs")
        node = VictoriaNode()
        orch.register_node(node)

        # Inject synthetic _last_market_data so compute_signals doesn't need live data
        node._last_market_data = _make_market_data()

        from omega.core.node import NodeInput

        out = node.execute(
            NodeInput(
                action="signal_research",
                parameters={"pico_mode": True},
                context={"cycle": 1},
            )
        )
        assert out.success, f"signal_research failed: {out.errors}"
        assert isinstance(out.result, dict)
        # The pipeline server handler extracts _quality_score → quality_score
        assert "_quality_score" in out.result, "VictoriaNode must emit _quality_score"
        assert isinstance(out.result["_quality_score"], float)
        assert 0.0 <= out.result["_quality_score"] <= 1.0

    def test_orchestrator_surfaces_quality_keys(self):
        """OmegaOrchestrator pipeline handler promotes _quality_score to resp_metrics."""
        from omega.core.node import NodeInput, NodeOutput
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        # Stub node that returns known _quality_score
        class StubNode:
            def get_state(self):
                from omega.core.node import NodeState

                return NodeState(
                    node_id="stub-1",
                    name="Stub",
                    version="1",
                    health=1.0,
                    capabilities=["signal_research"],
                    metrics={},
                    metadata={},
                )

            def get_capabilities(self):
                return ["signal_research"]

            def get_param_space(self):
                return []

            def execute(self, inp: NodeInput) -> NodeOutput:
                return NodeOutput(
                    request_id=inp.request_id,
                    success=True,
                    result={
                        "basic_signals": {"value": 0.4, "confidence": 0.75},
                        "_quality_score": 0.55,
                        "_signal_count": 1.0,
                        "_avg_confidence": 0.75,
                    },
                    metrics={"latency_ms": 10.0},
                )

        orch = OmegaOrchestrator(name="test-surface")
        orch.register_node(StubNode())

        import socket as _sock

        with _sock.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server, _thread = orch.start_pipeline_server(port=port)
        try:
            import json
            import urllib.request

            body = {
                "stepId": "s1",
                "stepName": "SignalResearch",
                "nodeType": "SIGNAL_RESEARCH",
                "cycle": 1,
                "projectId": "",
            }
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                f"http://localhost:{port}/omega.v1.PipelineService/ExecuteStep",
                data=data,
                headers={"Content-Type": "application/json", "Connect-Protocol-Version": "1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
            metrics = result.get("metrics", {})
            assert "quality_score" in metrics, f"quality_score missing from metrics: {metrics}"
            assert abs(metrics["quality_score"] - 0.55) < 1e-6
            assert "signal_count" in metrics
            assert "avg_confidence" in metrics
        finally:
            server.shutdown()


# ===========================================================================
# Fix 2 — construct_portfolio → PaperTradingEngine.execute_proposals()
# ===========================================================================


class TestFix2PaperTradingWired:
    """After a STRATEGY step, PaperTradingEngine.execute_proposals() is called."""

    def test_execute_proposals_called_on_strategy(self):
        """execute_proposals is invoked when the pipeline handler runs a STRATEGY step."""
        import json
        import socket
        import urllib.request

        from omega.core.node import NodeInput, NodeOutput
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        class StrategyStub:
            def get_state(self):
                from omega.core.node import NodeState

                return NodeState(
                    node_id="strat-1",
                    name="Strategy",
                    version="1",
                    health=1.0,
                    capabilities=["strategy"],
                    metrics={},
                    metadata={},
                )

            def get_capabilities(self):
                return ["strategy"]

            def get_param_space(self):
                return []

            def execute(self, inp: NodeInput) -> NodeOutput:
                return NodeOutput(
                    request_id=inp.request_id,
                    success=True,
                    result=[{"symbol": "BTCUSDT", "weight": 0.6}],
                    metrics={"latency_ms": 5.0},
                )

        mock_engine = MagicMock()
        mock_engine.execute_proposals.return_value = [
            {
                "trade_id": "t1",
                "sym": "BTCUSDT",
                "side": "long",
                "size": 60_000.0,
                "entry": 50_000.0,
                "pnl": 0.0,
            }
        ]
        mock_engine.realised_pnl = 0.0

        orch = OmegaOrchestrator(name="test-paper", paper_trading=mock_engine)
        stub = StrategyStub()
        orch.register_node(stub)

        with socket.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server, _thread = orch.start_pipeline_server(port=port)
        try:
            body = {
                "stepId": "s1",
                "stepName": "Strategy",
                "nodeType": "STRATEGY",
                "cycle": 2,
                "projectId": "",
            }
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                f"http://localhost:{port}/omega.v1.PipelineService/ExecuteStep",
                data=data,
                headers={"Content-Type": "application/json", "Connect-Protocol-Version": "1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())

            assert result.get("success") is True, result
            mock_engine.execute_proposals.assert_called_once()
            call_kwargs = mock_engine.execute_proposals.call_args
            proposals_arg = call_kwargs[0][0]
            assert isinstance(proposals_arg, list)
            assert proposals_arg[0]["symbol"] == "BTCUSDT"

            metrics = result.get("metrics", {})
            assert "paper_trades_executed" in metrics, f"paper_trades_executed missing: {metrics}"
            assert metrics["paper_trades_executed"] == 1.0
        finally:
            server.shutdown()

    def test_no_paper_trading_no_crash(self):
        """Strategy step succeeds silently when no PaperTradingEngine is wired."""
        import json
        import socket
        import urllib.request

        from omega.core.node import NodeInput, NodeOutput
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        class StrategyStub:
            def get_state(self):
                from omega.core.node import NodeState

                return NodeState(
                    node_id="strat-2",
                    name="Strategy2",
                    version="1",
                    health=1.0,
                    capabilities=["strategy"],
                    metrics={},
                    metadata={},
                )

            def get_capabilities(self):
                return ["strategy"]

            def get_param_space(self):
                return []

            def execute(self, inp: NodeInput) -> NodeOutput:
                return NodeOutput(
                    request_id=inp.request_id,
                    success=True,
                    result=[{"symbol": "ETHUSDT", "weight": 0.4}],
                    metrics={"latency_ms": 3.0},
                )

        orch = OmegaOrchestrator(name="test-no-paper")  # no paper_trading
        orch.register_node(StrategyStub())

        with socket.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        server, _thread = orch.start_pipeline_server(port=port)
        try:
            body = {
                "stepId": "s1",
                "stepName": "Strategy",
                "nodeType": "STRATEGY",
                "cycle": 3,
                "projectId": "",
            }
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                f"http://localhost:{port}/omega.v1.PipelineService/ExecuteStep",
                data=data,
                headers={"Content-Type": "application/json", "Connect-Protocol-Version": "1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
            assert result.get("success") is True
        finally:
            server.shutdown()


# ===========================================================================
# Fix 3 — DebateGate → real risk_debate()
# ===========================================================================


class TestFix3DebateGate:
    """DebateGate action calls risk_debate() and returns consensus fields."""

    def test_debategate_returns_consensus(self):
        """debategate action returns bull_score, bear_score, recommendation, violations."""
        from omega.core.node import NodeInput
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        node._last_market_data = _make_market_data()
        node._last_signals = _make_signals(n_positive=3, n_negative=1, confidence=0.8)

        out = node.execute(NodeInput(action="debategate", parameters={}, context={"cycle": 5}))
        assert out.success, f"debategate failed: {out.errors}"
        result = out.result
        assert isinstance(result, dict)
        assert "bull_score" in result
        assert "bear_score" in result
        assert "recommendation" in result
        assert "violations" in result
        assert result["recommendation"] in ("go", "hold", "abort")
        assert 0.0 <= result["bull_score"] <= 1.0
        assert 0.0 <= result["bear_score"] <= 1.0

    def test_debategate_not_stub(self):
        """debategate must NOT return the old stub {status: ok, action: debategate}."""
        from omega.core.node import NodeInput
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        node._last_signals = _make_signals()
        node._last_market_data = {}

        out = node.execute(NodeInput(action="debategate", parameters={}, context={"cycle": 1}))
        assert out.success
        # Old stub returned {"status": "ok", "action": "debategate"}
        assert out.result.get("status") != "ok" or "bull_score" in out.result, (
            "debategate still returning stub response"
        )
        assert "bull_score" in out.result

    def test_debategate_metrics_promoted(self):
        """bull_score and bear_score are exposed in NodeOutput.metrics."""
        from omega.core.node import NodeInput
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        node._last_signals = _make_signals()
        node._last_market_data = {}

        out = node.execute(NodeInput(action="debategate", parameters={}, context={"cycle": 1}))
        assert "bull_score" in out.metrics
        assert "bear_score" in out.metrics
        assert "edge" in out.metrics

    def test_debategate_aborts_on_negative_signals(self):
        """When bear signals dominate, recommendation should be abort."""
        from omega.core.node import NodeInput
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        # More negative than positive
        node._last_signals = _make_signals(n_positive=1, n_negative=5, confidence=0.9)
        node._last_market_data = {}

        out = node.execute(NodeInput(action="debategate", parameters={}, context={"cycle": 1}))
        assert out.success
        assert out.result["recommendation"] in ("hold", "abort")

    def test_verification_still_stub(self):
        """Non-debategate verification actions still return the no-op stub."""
        from omega.core.node import NodeInput
        from omega.nodes.victoria.victoria_node import VictoriaNode

        node = VictoriaNode()
        out = node.execute(NodeInput(action="verification", parameters={}, context={"cycle": 1}))
        assert out.success
        assert out.result == {"status": "ok", "action": "verification"}


# ===========================================================================
# Fix 3 — RiskManagementNode.risk_debate() unit tests
# ===========================================================================


class TestRiskDebateUnit:
    """Direct unit tests for RiskManagementNode.risk_debate()."""

    def test_bull_dominant_recommends_go(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        signals = {
            "s1": {"value": 0.9, "confidence": 0.9},
            "s2": {"value": 0.7, "confidence": 0.8},
        }
        result = node.risk_debate(signals=signals)
        assert result["bull_score"] > result["bear_score"]
        assert result["recommendation"] == "go"

    def test_bear_dominant_recommends_abort(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        signals = {
            "s1": {"value": -0.8, "confidence": 0.9},
            "s2": {"value": -0.6, "confidence": 0.85},
        }
        result = node.risk_debate(signals=signals)
        assert result["bear_score"] > result["bull_score"]
        assert result["recommendation"] == "abort"

    def test_private_keys_ignored(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        signals = {
            "_weights": {"s1": 0.5},  # must be ignored
            "s1": {"value": 0.5, "confidence": 0.7},
        }
        result = node.risk_debate(signals=signals)
        assert result["bull_score"] > 0
        assert 0.0 <= result["bull_score"] <= 1.0

    def test_empty_signals_returns_hold(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        result = node.risk_debate(signals={})
        assert result["bull_score"] == 0.0
        assert result["bear_score"] == 0.0
        assert result["recommendation"] == "hold"

    def test_violations_cause_abort(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        # Positive signals but portfolio weight exceeds 25% limit
        signals = {"s1": {"value": 0.8, "confidence": 0.9}}
        weights = {"BTCUSDT": 0.9, "ETHUSDT": 0.1}  # 90% concentration → violation
        result = node.risk_debate(signals=signals, portfolio_weights=weights)
        # Should abort due to position limit violation
        assert len(result["violations"]) > 0
        assert result["recommendation"] == "abort"

    def test_result_schema(self):
        from omega.nodes.victoria.risk_management import RiskManagementNode

        node = RiskManagementNode()
        result = node.risk_debate(
            signals={"s": {"value": 0.3, "confidence": 0.6}},
            portfolio_weights={"BTC": 0.2},
            market_data={},
        )
        required = {"bull_score", "bear_score", "recommendation", "violations", "edge"}
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"
        assert isinstance(result["violations"], list)
