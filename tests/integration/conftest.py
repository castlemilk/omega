"""
Shared fixtures for Omega end-to-end integration tests.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

import pytest

from omega.core.adversarial_v2 import AdversarialPressureV2
from omega.core.backtest_evaluator import BacktestEvaluator
from omega.core.bayesian_optimizer import ContinuousParam, Param
from omega.core.improvement_engine import ImprovementEngine
from omega.core.improvement_scheduler import ImprovementScheduler
from omega.core.memory_consolidation import ConsolidationPipeline
from omega.core.metrics_exporter import MetricsExporter
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.orchestrator_v2 import OmegaOrchestrator

# ---------------------------------------------------------------------------
# Synthetic OHLCV data
# ---------------------------------------------------------------------------


def synthetic_market_data(n_bars: int = 500, seed: int = 42) -> list[dict]:
    """
    Generate n_bars of synthetic BTC/USDT OHLCV with two regime changes:
      bars   0-199 : trending   (smooth upward drift, low volatility)
      bars 200-349 : volatile   (high volatility, near-zero drift)
      bars 350-499 : trending   (smooth upward drift resumes)
    """
    rng = random.Random(seed)
    bars: list[dict] = []
    price = 50_000.0
    base_ts = 1_700_000_000

    for i in range(n_bars):
        if i < 200:
            mu, sigma = 0.0015, 0.005
        elif i < 350:
            mu, sigma = 0.0, 0.030
        else:
            mu, sigma = 0.0010, 0.005

        ret = rng.gauss(mu, sigma)
        open_p = price
        close_p = price * (1 + ret)
        wick = abs(rng.gauss(0, sigma / 2))
        high_p = max(open_p, close_p) * (1 + wick)
        low_p = min(open_p, close_p) * (1 - wick)

        bars.append(
            {
                "timestamp": base_ts + i * 3600,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": round(rng.uniform(100.0, 1000.0), 2),
                "bar_index": i,
            }
        )
        price = close_p

    return bars


# ---------------------------------------------------------------------------
# SyntheticMarketNode
# ---------------------------------------------------------------------------


class SyntheticMarketNode(Node):
    """
    Replays synthetic OHLCV bars one-per-cycle.

    Capabilities: poll, compute_signals, construct_portfolio

    Regime detection mirrors the synthetic_market_data() phases:
      - bars   0-199 → regime_label="trending",  changepoint_prob=0.05
      - bars 200-349 → regime_label="volatile",  changepoint_prob=0.90
      - bars 350+    → regime_label="trending",  changepoint_prob=0.05

    bad_signal_after: if set, signals become noisy after this bar index
    (used by feedback-loop tests to inject degradation).
    """

    def __init__(
        self,
        bars: list[dict],
        bad_signal_after: int | None = None,
        seed: int = 123,
    ) -> None:
        from omega.core.brain import NoBrain

        # Bypass super().__init__() to avoid spawning a real brain
        object.__setattr__(self, "brain", NoBrain())

        self._node_id = str(uuid.uuid4())
        self._bars = bars
        self._index = 0
        self._health = 1.0
        self._bad_signal_after = bad_signal_after
        self._rng = random.Random(seed)
        self._last_bar: dict = {}
        self._last_signals: dict = {}

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="SyntheticMarketNode",
            version="1.0",
            health=self._health,
            capabilities=self.get_capabilities(),
            metrics={"bars_consumed": float(self._index)},
        )

    def get_capabilities(self) -> list[str]:
        return ["poll", "compute_signals", "construct_portfolio"]

    def describe(self) -> str:
        return "Synthetic BTC/USDT OHLCV replay node for integration testing."

    def execute(self, inp: NodeInput) -> NodeOutput:
        if inp.action == "poll":
            return self._poll(inp)
        if inp.action == "compute_signals":
            return self._compute_signals(inp)
        if inp.action == "construct_portfolio":
            return self._construct_portfolio(inp)
        return NodeOutput(
            request_id=inp.request_id,
            success=False,
            errors=[f"Unknown action: {inp.action!r}"],
        )

    def _poll(self, inp: NodeInput) -> NodeOutput:
        if self._index >= len(self._bars):
            self._index = 0  # wrap around
        bar = self._bars[self._index]
        self._index += 1
        self._last_bar = bar
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=bar,
            metrics={"latency_ms": 0.1},
        )

    def _compute_signals(self, inp: NodeInput) -> NodeOutput:
        bar = inp.parameters.get("market_data") or self._last_bar
        bar_idx = bar.get("bar_index", self._index - 1)

        # Regime phase
        if 200 <= bar_idx < 350:
            regime_label = "volatile"
            changepoint_prob = 0.90
        else:
            regime_label = "trending"
            changepoint_prob = 0.05

        # Simple momentum: alternating buy/sell signal
        if self._bad_signal_after is not None and bar_idx >= self._bad_signal_after:
            # Inject degraded signal: large random noise
            momentum = self._rng.uniform(-5.0, 5.0)
        else:
            momentum = 1.0 if (bar_idx % 10) < 7 else -1.0

        signals = {
            "btc_momentum": momentum,
            "close": bar.get("close", 50_000.0),
            "regime_label": regime_label,
            "changepoint_prob": changepoint_prob,
        }
        self._last_signals = signals
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=signals,
            metrics={"latency_ms": 0.2},
        )

    def _construct_portfolio(self, inp: NodeInput) -> NodeOutput:
        signals_map = inp.parameters.get("signals", {})
        node_signals = signals_map.get(self._node_id, self._last_signals)
        momentum = (
            float(node_signals.get("btc_momentum", 0.0)) if isinstance(node_signals, dict) else 0.0
        )
        proposal = {
            "symbol": "BTC/USDT",
            "side": "buy" if momentum >= 0 else "sell",
            "size": 0.01,
            "confidence": min(abs(momentum), 1.0),
            "node_id": self._node_id,
        }
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=[proposal],
            metrics={"latency_ms": 0.1},
        )

    def evaluate(self) -> dict[str, float]:
        return {"bars_consumed": float(self._index), "health": self._health}

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False


# ---------------------------------------------------------------------------
# Minimal state-store stub for MetricsExporter
# ---------------------------------------------------------------------------


class _AlwaysDueScheduler(ImprovementScheduler):
    """
    Scheduler subclass that always returns all registered nodes as due.
    Bypasses ImprovementScheduler's heap/timing so TPE fires every
    IMPROVEMENT_INTERVAL cycles without needing record_outcome() calls.
    """

    def __init__(self) -> None:
        super().__init__()
        self._due_nodes: set[str] = set()

    def due_nodes(self) -> list[str]:
        return list(self._due_nodes)

    def register(  # noqa: override
        self, node_id: str, *args: Any, **kwargs: Any
    ) -> None:
        self._due_nodes.add(node_id)

    def record_outcome(self, *args: Any, **kwargs: Any) -> None:
        pass


class _StubStore:
    """Minimal stub so MetricsExporter doesn't error on construction."""

    def get_node_execution_count(self, *a, **kw) -> int:
        return 0

    def get_improvement_count(self, *a, **kw) -> int:
        return 0

    def get_brain_request_count(self, *a, **kw) -> int:
        return 0

    def get_issue_count(self, *a, **kw) -> int:
        return 0

    def get_memory_count(self, *a, **kw) -> int:
        return 0

    # Catch-all so attribute access never raises
    def __getattr__(self, name: str) -> Any:
        return lambda *a, **kw: 0


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def market_bars() -> list[dict]:
    return synthetic_market_data(n_bars=500)


@pytest.fixture
def synthetic_node(market_bars: list[dict]) -> SyntheticMarketNode:
    return SyntheticMarketNode(market_bars)


@pytest.fixture
def configured_orchestrator(market_bars: list[dict]) -> OmegaOrchestrator:
    """
    Fully wired OmegaOrchestrator with:
    - SyntheticMarketNode
    - ImprovementEngine (TPE, node pre-registered, scheduler due immediately)
    - ConsolidationPipeline (min_age=0 for fast promotion in tests)
    - AdversarialPressureV2 (active)
    - MetricsExporter (stub store, no HTTP server started)
    """
    node = SyntheticMarketNode(market_bars)

    # Improvement engine — register node so TPE can propose
    # allow_synthetic=True: integration fixture uses synthetic market data
    engine = ImprovementEngine(store=None, evaluator=BacktestEvaluator(allow_synthetic=True))
    param_space: list[Param] = [
        ContinuousParam(name="momentum_threshold", low=0.1, high=2.0),
        ContinuousParam(name="position_size", low=0.001, high=0.1),
    ]
    engine.register_node(node._node_id, param_space=param_space)

    # Scheduler — always returns node as due so TPE runs every IMPROVEMENT_INTERVAL cycles
    scheduler = _AlwaysDueScheduler()
    scheduler.register(node._node_id)

    # Memory consolidation — min_age=0 so memories promote instantly
    consolidation = ConsolidationPipeline(min_age_seconds=0.0, promotion_threshold=0.1)

    # Metrics exporter — stub store, don't start HTTP server
    metrics = MetricsExporter(state_store=_StubStore())

    # Adversarial layer
    adversarial = AdversarialPressureV2()

    orch = OmegaOrchestrator(
        name="test-omega",
        improvement_engine=engine,
        improvement_scheduler=scheduler,
        memory_consolidation=consolidation,
        metrics_exporter=metrics,
        adversarial=adversarial,
    )
    orch.register_node(node)

    # Lower intervals so tests exercise the code in fewer cycles
    orch.IMPROVEMENT_INTERVAL = 10
    orch.CONSOLIDATION_INTERVAL = 25

    return orch
