"""
omega.nodes.vectora.vectora_node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
VectoraNode — the main Vectora trading node.

This is ONE domain node that plugs into the generic OmegaOrchestrator.
The orchestrator has no knowledge of VectoraNode's internals.

VectoraNode composes:
  - DataIngestionNode   → fetches OHLCV market data
  - SignalGenerationNode → computes basic technical signals
  - OrderFlowSignal     → advanced order-flow / VPIN signals
  - CrossAssetSignal    → BTC/ETH/SOL correlation signals
  - MicrostructureSignal → spread / tick pattern signals
  - SentimentSignal     → funding rate / open interest signals
  - DynamicWeightAllocator → IC-based signal weighting
  - StrategyNode        → constructs portfolios from weighted signals

Autonomy modes
--------------
PICO        → deterministic strategy only; no brain calls allowed.
SUPERVISED  → brain may propose, human must approve (gate in caller).
AUTONOMOUS  → brain operates freely.

Capabilities exposed to orchestrator
--------------------------------------
  "poll"              → fetch_data via DataIngestionNode
  "compute_signals"   → run all signal types
  "construct_portfolio" → StrategyNode portfolio construction
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, ClassVar

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.nodes.vectora.data_ingestion import DataIngestionNode
from omega.nodes.vectora.dynamic_weights import DynamicWeightAllocator
from omega.nodes.vectora.signal_generation import SignalGenerationNode
from omega.nodes.vectora.signals_advanced import (
    CrossAssetSignal,
    MicrostructureSignal,
    OrderFlowSignal,
    SentimentSignal,
)
from omega.nodes.vectora.strategy import StrategyNode

logger = logging.getLogger("omega.nodes.vectora.vectora_node")

# Signal names exposed by this node
SIGNAL_NAMES = [
    "basic_signals",
    "order_flow",
    "cross_asset",
    "microstructure",
    "sentiment",
]


class VectoraNode(Node):
    """
    Vectora trading node — composes all Vectora subsystems into a single
    pluggable Node that the OmegaOrchestrator can register and activate.

    Parameters
    ----------
    node_id       : Optional fixed ID (useful for tests / persistence).
    brain_config  : BrainConfig to use for brain consultation.
    """

    skill_tags: ClassVar[list[str]] = ["quant", "crypto", "trading"]

    def __init__(
        self,
        node_id: str | None = None,
        brain_config: Any = None,
    ) -> None:
        super().__init__(brain_config=brain_config)

        self._node_id = node_id or str(uuid.uuid4())
        self._version = "1.0"

        # Compose subsystems
        self._ingestion = DataIngestionNode()
        self._signals = SignalGenerationNode()
        self._strategy = StrategyNode()

        # Advanced signal generators (stateless, just compute methods)
        self._order_flow = OrderFlowSignal()
        self._cross_asset = CrossAssetSignal()
        self._microstructure = MicrostructureSignal()
        self._sentiment = SentimentSignal()

        # Dynamic weight allocator
        self._weight_allocator = DynamicWeightAllocator(signal_names=SIGNAL_NAMES)

        # Runtime state
        self._last_market_data: dict[str, Any] = {}
        self._last_signals: dict[str, Any] = {}
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        avg_lat = self._total_latency_ms / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="VectoraNode",
            version=self._version,
            health=max(0.0, 1.0 - error_rate),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": avg_lat,
                "error_rate": error_rate,
                "execution_count": float(self._execution_count),
            },
            metadata={
                "signal_names": SIGNAL_NAMES,
                "version": self._version,
            },
        )

    def get_capabilities(self) -> list[str]:
        return [
            "poll",
            "fetch_data",
            "compute_signals",
            "construct_portfolio",
            "backtest_strategy",
            "rank_signals",
        ]

    def describe(self) -> str:
        return (
            "VectoraNode: crypto quant trading node. Fetches OHLCV data from "
            "Binance/CoinGecko/Bybit, computes basic technical signals (SMA/RSI/MACD), "
            "advanced signals (order flow, cross-asset, microstructure, sentiment), "
            "applies dynamic IC-based weighting, and constructs portfolios via the "
            "StrategyNode. Respects graduated autonomy (PICO = deterministic only)."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1
        action = inp.action

        try:
            result: Any
            if action in ("poll", "fetch_data"):
                result = self._do_poll(inp)
            elif action == "compute_signals":
                result = self._do_compute_signals(inp)
            elif action == "construct_portfolio":
                result = self._do_construct_portfolio(inp)
            elif action in ("backtest_strategy", "rank_signals"):
                # Delegate to inner StrategyNode
                result_out = self._strategy.execute(inp)
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                return result_out
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                self._error_count += 1
                return NodeOutput(
                    request_id=inp.request_id,
                    success=False,
                    errors=[f"VectoraNode: unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": elapsed},
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._error_count += 1
            logger.error("VectoraNode.execute error (action=%s): %s", action, exc, exc_info=True)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        """Delegate improvement to inner nodes."""
        changed = False
        for node in (self._ingestion, self._signals, self._strategy):
            try:
                if node.improve(feedback):
                    changed = True
            except Exception as exc:
                logger.debug("improve() delegation failed: %s", exc)
        return changed

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _do_poll(self, inp: NodeInput) -> dict[str, Any]:
        """Fetch market data via DataIngestionNode."""
        out = self._ingestion.execute(
            NodeInput(
                action="fetch_data",
                parameters=inp.parameters,
                context=inp.context,
            )
        )
        if out.success and out.result:
            self._last_market_data = out.result if isinstance(out.result, dict) else {}
        return self._last_market_data

    def _do_compute_signals(self, inp: NodeInput) -> dict[str, Any]:
        """Compute all signal types and apply dynamic weighting."""
        market_data: dict[str, Any] = inp.parameters.get("market_data") or self._last_market_data
        regime: str = inp.context.get("regime", "default")
        pico_mode: bool = inp.parameters.get("pico_mode", False)

        signals: dict[str, Any] = {}

        # 1. Basic technical signals (SMA/RSI/MACD/BB)
        basic_out = self._signals.execute(
            NodeInput(
                action="compute_signals",
                parameters={"market_data": market_data},
                context=inp.context,
            )
        )
        if basic_out.success and basic_out.result:
            signals["basic_signals"] = basic_out.result

        # Advanced signals are only computed outside PICO mode
        # (they may use more complex / probabilistic computations)
        if not pico_mode:
            try:
                of_val = self._order_flow.compute(market_data)
                signals["order_flow"] = {
                    "value": of_val.value,
                    "confidence": of_val.confidence,
                    "regime_tag": of_val.regime_tag,
                    "raw": of_val.raw,
                }
            except Exception as exc:
                logger.debug("order_flow signal failed: %s", exc)

            try:
                ca_val = self._cross_asset.compute(market_data)
                signals["cross_asset"] = {
                    "value": ca_val.value,
                    "confidence": ca_val.confidence,
                    "regime_tag": ca_val.regime_tag,
                    "raw": ca_val.raw,
                }
            except Exception as exc:
                logger.debug("cross_asset signal failed: %s", exc)

            try:
                ms_val = self._microstructure.compute(market_data)
                signals["microstructure"] = {
                    "value": ms_val.value,
                    "confidence": ms_val.confidence,
                    "regime_tag": ms_val.regime_tag,
                    "raw": ms_val.raw,
                }
            except Exception as exc:
                logger.debug("microstructure signal failed: %s", exc)

            try:
                sent_val = self._sentiment.compute(market_data)
                signals["sentiment"] = {
                    "value": sent_val.value,
                    "confidence": sent_val.confidence,
                    "regime_tag": sent_val.regime_tag,
                    "raw": sent_val.raw,
                }
            except Exception as exc:
                logger.debug("sentiment signal failed: %s", exc)

        # 2. Apply dynamic weighting
        raw_weights = {name: 1.0 for name in signals}
        try:
            alloc = self._weight_allocator.allocate(regime=regime)
            for name in signals:
                if name in alloc.weights:
                    raw_weights[name] = alloc.weights[name]
        except Exception as exc:
            logger.debug("weight allocation failed, using equal weights: %s", exc)

        signals["_weights"] = raw_weights
        signals["_regime"] = regime
        self._last_signals = signals
        return signals

    def _do_construct_portfolio(self, inp: NodeInput) -> list[dict[str, Any]]:
        """Construct portfolio from signals, respecting autonomy level."""
        signals: dict[str, Any] = inp.parameters.get("signals") or self._last_signals
        regime: str = inp.parameters.get("regime", "default")
        pico_mode: bool = inp.parameters.get("pico_mode", False)

        # Flatten signal values for StrategyNode
        flat_signals: dict[str, float] = {}

        for node_signals in signals.values() if isinstance(signals, dict) else []:
            if isinstance(node_signals, dict) and "value" in node_signals:
                continue  # single signal dict — handled below
            if isinstance(node_signals, dict):
                for pair, sig in node_signals.items():
                    if isinstance(sig, dict) and "composite_signal" in sig:
                        flat_signals[pair] = sig["composite_signal"]

        # Also grab advanced signal values
        for name, sig in signals.items() if isinstance(signals, dict) else []:
            if name.startswith("_"):
                continue
            if isinstance(sig, dict) and "value" in sig:
                flat_signals[f"adv_{name}"] = sig["value"]

        strategy_inp = NodeInput(
            action="construct_portfolio",
            parameters={
                "signals": flat_signals,
                "market_data": self._last_market_data,
                "pico_mode": pico_mode,
                "regime": regime,
            },
            context=inp.context,
        )
        out = self._strategy.execute(strategy_inp)
        if out.success and out.result:
            result = out.result
            if isinstance(result, dict):
                return [result]
            if isinstance(result, list):
                return result
        return []
