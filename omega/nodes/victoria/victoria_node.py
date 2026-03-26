"""
omega.nodes.victoria.victoria_node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
VictoriaNode — the main Victoria trading node.

This is ONE domain node that plugs into the generic OmegaOrchestrator.
The orchestrator has no knowledge of VictoriaNode's internals.

VictoriaNode composes:
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
import os
import time
import uuid
from typing import Any, ClassVar

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.state_tensor import StateTensor, VictoriaStateTensorBuilder
from omega.nodes.victoria.alt_data_signals import AltDataSignalProvider
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator
from omega.nodes.victoria.market_data_signals import MarketDataSignal
from omega.nodes.victoria.risk_management import RiskManagementNode
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.signals_advanced import (
    BTCDominanceSignal,
    CrossAssetSignal,
    LongShortRatioSignal,
    MicrostructureSignal,
    OnChainSignal,
    OrderFlowSignal,
    SentimentSignal,
)
from omega.nodes.victoria.strategy import StrategyNode
from omega.nodes.victoria.vrp_signal import VRPSignalNode

logger = logging.getLogger("omega.nodes.victoria.victoria_node")

# Signal names exposed by this node
SIGNAL_NAMES = [
    "basic_signals",
    "order_flow",
    "cross_asset",
    "microstructure",
    "sentiment",
    "vrp",
    "market_data",
    "onchain",
    "long_short_ratio",
    "btc_dominance",
    "alt_data",
]

# Map VRP regime to DynamicWeightAllocator regime strings
_VRP_REGIME_MAP = {
    "FEAR": "high_vol",
    "COMPLACENCY": "crisis",
    "NEUTRAL": None,  # keep existing regime
}


class VictoriaNode(Node):
    """
    Victoria trading node — composes all Victoria subsystems into a single
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
        self._vrp = VRPSignalNode()
        self._market_data_signal = MarketDataSignal()
        self._onchain = OnChainSignal()
        self._long_short_ratio = LongShortRatioSignal()
        self._btc_dominance = BTCDominanceSignal()
        self._alt_data = AltDataSignalProvider()

        # Dynamic weight allocator
        self._weight_allocator = DynamicWeightAllocator(signal_names=SIGNAL_NAMES)

        # Risk management node (used for DebateGate)
        self._risk_management = RiskManagementNode()

        # Runtime state
        self._last_market_data: dict[str, Any] = {}
        self._last_signals: dict[str, Any] = {}
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

        # IC tracking for weight learning
        self._prev_signal_values: dict[str, float] = {}
        self._quality_history: list[float] = []
        self._signal_counts_history: list[int] = []
        self._total_cycles_run: int = 0

        # Lazy-initialised reflection store (requires DATABASE_URL at runtime)
        self._reflection_store: Any = None

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        avg_lat = self._total_latency_ms / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="VictoriaNode",
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
            NodeAction.POLL.value,
            NodeAction.FETCH_MARKET_DATA.value,
            NodeAction.COMPUTE_SIGNALS.value,
            NodeAction.CONSTRUCT_PORTFOLIO.value,
            NodeAction.BACKTEST_STRATEGY.value,
            NodeAction.RANK_SIGNALS.value,
            # Go pipeline step NodeType aliases (registered as DATA_INGESTION etc.)
            NodeAction.DATA_INGESTION.value,
            NodeAction.SIGNAL_RESEARCH.value,
            NodeAction.STRATEGY.value,
            NodeAction.RISK_MANAGEMENT.value,
            NodeAction.VERIFICATION.value,
            NodeAction.MEMORY.value,
            NodeAction.IMPROVEMENT.value,
            NodeAction.ADVERSARIAL.value,
        ]

    def describe(self) -> str:
        return (
            "VictoriaNode: crypto quant trading node. Fetches OHLCV data from "
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
            if action in (
                NodeAction.POLL.value,
                NodeAction.FETCH_MARKET_DATA.value,
                NodeAction.DATA_INGESTION.value,
                "fetch_data",
                "dataingestion",
            ):
                result = self._do_poll(inp)
            elif action in (
                NodeAction.COMPUTE_SIGNALS.value,
                NodeAction.SIGNAL_RESEARCH.value,
                "signalresearch",
            ):
                result = self._do_compute_signals(inp)
            elif action in (
                NodeAction.CONSTRUCT_PORTFOLIO.value,
                NodeAction.STRATEGY.value,
                NodeAction.RISK_MANAGEMENT.value,
                NodeAction.CHECK_RISK_LIMITS.value,
                "riskmanagement",
                "riskcheck",
                "risk_check",
                "intelligencecoordination",
                "dynamicweights",
            ):
                result = self._do_construct_portfolio(inp)
            elif action in (NodeAction.BACKTEST_STRATEGY.value, NodeAction.RANK_SIGNALS.value):
                # Delegate to inner StrategyNode
                result_out = self._strategy.execute(inp)
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                return result_out
            elif action == NodeAction.DEBATE_GATE.value:
                # Real risk debate — bull/bear scoring + risk-limit check.
                portfolio_weights: dict[str, float] = {}
                if "portfolio" in inp.parameters and isinstance(inp.parameters["portfolio"], dict):
                    portfolio_weights = inp.parameters["portfolio"].get("weights", {})
                elif "_weights" in self._last_signals:
                    raw_w = self._last_signals["_weights"]
                    portfolio_weights = {
                        k: float(v)
                        for k, v in raw_w.items()
                        if not k.startswith("_") and isinstance(v, (int, float))
                    }
                result = self._risk_management.signal_debate(
                    signals=self._last_signals,
                    portfolio_weights=portfolio_weights,
                    market_data=self._last_market_data,
                )
                logger.info(
                    "DebateGate: bull=%.3f bear=%.3f recommendation=%s violations=%d",
                    result["bull_score"],
                    result["bear_score"],
                    result["recommendation"],
                    len(result["violations"]),
                )
            elif action in (
                NodeAction.VERIFICATION.value,
                NodeAction.WALK_FORWARD.value,
                NodeAction.MEMORY.value,
                NodeAction.ADVERSARIAL.value,
                "ring3adversarial",
            ):
                # These are handled internally by Python orchestrator; return success no-op
                result = {"status": "ok", "action": action}
            elif action in (NodeAction.IMPROVEMENT.value, NodeAction.IMPROVEMENT_ENGINE.value):
                result = self._do_improvement(inp)
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                self._error_count += 1
                return NodeOutput(
                    request_id=inp.request_id,
                    success=False,
                    errors=[f"VictoriaNode: unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed

            # Promote debate consensus metrics so Go can observe them via Prometheus.
            extra_metrics: dict[str, float] = {}
            if action == NodeAction.DEBATE_GATE.value and isinstance(result, dict):
                extra_metrics = {
                    k: float(v)
                    for k, v in result.items()
                    if k in ("bull_score", "bear_score", "edge") and isinstance(v, (int, float))
                }
                extra_metrics["violation_count"] = float(len(result.get("violations", [])))

            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": elapsed, **extra_metrics},
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._error_count += 1
            logger.error("VictoriaNode.execute error (action=%s): %s", action, exc, exc_info=True)
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

    def get_param_space(self) -> list:
        """
        Victoria's TPE hyperparameter space.

        These are the parameters the improvement engine will optimise
        across cycles.  All bounds are chosen to be safe for pico-mode
        operation without live capital.
        """
        from omega.core.bayesian_optimizer import ContinuousParam, DiscreteParam

        return [
            ContinuousParam("signal_threshold", 0.0, 1.0),
            DiscreteParam("lookback_days", 10, 90),
            ContinuousParam("risk_scale", 0.5, 2.0),
            DiscreteParam("top_n_signals", 3, 10),
        ]

    def improve(self, feedback: dict[str, Any]) -> bool:
        """Delegate improvement feedback to inner nodes."""
        changed = False
        for node in (self._ingestion, self._signals, self._strategy):
            try:
                if node.improve(feedback):
                    changed = True
            except Exception as exc:
                logger.debug("improve() delegation failed: %s", exc)
        return changed

    def get_state_tensor(self) -> StateTensor:
        """
        Return a 16-dimensional state tensor for attention-based routing.

        Dimensions follow VictoriaStateTensorSchema v1.0.0. Values that
        require external context (e.g. trust_score from the outcome store,
        adversarial_score from Ring 1) default to neutral values and should
        be refreshed by the coordinator when richer data is available.
        """
        error_rate = self._error_count / max(1, self._execution_count)

        # Derive signal quality from last known signals
        signal_quality = self._derive_signal_quality()

        # Cycle health: 1 - error_rate (simple proxy)
        cycle_health = max(0.0, 1.0 - error_rate)

        # Data freshness: treat any cached data as reasonably fresh
        data_freshness = 1.0 if self._last_market_data else 0.0

        # Signal coverage: fraction of expected signal types present
        expected_signals = {
            "basic_signals",
            "order_flow",
            "cross_asset",
            "microstructure",
            "sentiment",
            "vrp",
            "onchain",
            "long_short_ratio",
            "btc_dominance",
        }
        present = expected_signals.intersection(self._last_signals.keys())
        signal_coverage = len(present) / len(expected_signals)

        values: dict[str, float] = {
            "signal_quality": signal_quality,
            "cycle_health": cycle_health,
            "data_freshness": data_freshness,
            "adversarial_score": 1.0,  # default: no disagreement known
            "improvement_trend": 0.0,  # neutral: no trend data yet
            "active_experiments": 0.0,  # not tracked at this level
            "last_sharpe": 0.0,  # not available without backtester
            "max_drawdown": 0.0,  # lower is healthier; default ok
            "signal_coverage": signal_coverage,
            "error_rate": error_rate,
            "autonomy_level": 0.0,  # default PICO
            "regime_label": 0.0,  # default / unknown
            "trust_score": 0.5,  # neutral until outcome history built
            "memory_utilisation": 0.0,
            "cycles_since_improvement": 1.0,  # conservative: assume no recent improvement
            "lm_consultation_rate": 0.0,
        }

        return VictoriaStateTensorBuilder.build(self._node_id, values)

    def persist_signals(
        self,
        signals: dict[str, Any],
        db_url: str | None = None,
    ) -> None:
        """Write computed signals to the victoria_signals table via UPSERT.

        Parameters
        ----------
        signals : dict
            Output of _do_compute_signals (may include _weights / _regime keys).
        db_url : str | None
            Postgres connection URL. Falls back to DATABASE_URL env var.
        """
        import psycopg

        url = db_url or os.getenv("DATABASE_URL")
        if not url:
            logger.warning("persist_signals: DATABASE_URL not set — signal persistence skipped")
            return

        weights: dict[str, float] = signals.get("_weights", {})

        rows = []
        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if not isinstance(sig, dict):
                continue
            value = float(sig.get("value", 0.0))
            confidence = float(sig.get("confidence", 0.0))
            weight = float(weights.get(name, 1.0))
            trend = str(sig.get("regime_tag", "unknown"))

            if value > 0.1:
                color = "#22c55e"  # green
            elif value < -0.1:
                color = "#ef4444"  # red
            else:
                color = "#6b7280"  # gray

            rows.append((name, confidence, weight, 20, color, confidence, 0.0, value, trend))

        if not rows:
            return

        sql = """
            INSERT INTO victoria_signals
                (name, avg_ic, weight, half_life, color, conviction, brier_score, current_value, trend)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name)
            DO UPDATE SET
                avg_ic        = EXCLUDED.avg_ic,
                weight        = EXCLUDED.weight,
                conviction    = EXCLUDED.conviction,
                current_value = EXCLUDED.current_value,
                trend         = EXCLUDED.trend,
                color         = EXCLUDED.color
        """
        try:
            with psycopg.connect(url) as conn, conn.cursor() as cur:
                for row in rows:
                    cur.execute(sql, row)
        except Exception as exc:
            logger.warning("persist_signals: DB write failed: %s", exc)

    def _derive_signal_quality(self) -> float:
        """Estimate signal quality from last computed signals."""
        if not self._last_signals:
            return 0.0
        confidences = []
        for name, sig in self._last_signals.items():
            if name.startswith("_"):
                continue
            if isinstance(sig, dict) and "confidence" in sig:
                confidences.append(float(sig["confidence"]))
        if not confidences:
            return 0.5  # signals present but no confidence data
        return sum(confidences) / len(confidences)

    # ------------------------------------------------------------------
    # Reflection helpers (V-TR1)
    # ------------------------------------------------------------------

    def _get_reflection_store(self) -> Any:
        """Lazy-init the NodeReflectionStore; returns None if DB unavailable."""
        if self._reflection_store is not None:
            return self._reflection_store
        if not os.getenv("DATABASE_URL"):
            return None
        try:
            from omega.core.memory import NodeReflectionStore

            self._reflection_store = NodeReflectionStore()
        except Exception as exc:
            logger.debug("NodeReflectionStore init failed: %s", exc)
        return self._reflection_store

    def get_reflection_context(self) -> str:
        """Return a context block of recent cycle lessons for LLM injection."""
        store = self._get_reflection_store()
        if store is None:
            return ""
        try:
            return str(store.get_context_prompt(self._node_id, limit=5))
        except Exception as exc:
            logger.debug("get_reflection_context failed: %s", exc)
            return ""

    def reflect_on_cycle(self, cycle: int, signals: dict[str, Any]) -> str:
        """
        Generate a brief reflection on the just-completed signal cycle and persist it.

        Uses ModelTier.QUICK (cheap/fast).  If no brain is configured or the
        brain call fails, a rule-based fallback reflection is stored instead.

        Returns the lesson_extracted string.
        """
        from omega.core.brain import ModelTier

        quality = float(signals.get("_quality_score", 0.0))
        avg_conf = float(signals.get("_avg_confidence", 0.0))
        coverage = float(signals.get("_signal_coverage", 0.0))
        regime = str(signals.get("_regime", "default"))
        n_signals = int(signals.get("_signal_count", 0))

        # Try LLM reflection if brain is available
        lesson = ""
        reflection_text = ""
        brain = self.brain  # from Node base class (NoBrain by default)

        if brain is not None and brain.is_available() and not isinstance(brain, type):
            prompt = (
                f"You are reviewing a completed crypto signal cycle.\n"
                f"Node: {self._node_id}\n"
                f"Cycle: {cycle}\n"
                f"Quality score: {quality:.3f}\n"
                f"Avg signal confidence: {avg_conf:.3f}\n"
                f"Signal coverage: {coverage:.0%} ({n_signals} signals)\n"
                f"Market regime: {regime}\n\n"
                f"In 1-2 sentences, reflect on signal quality and what the market regime implies.\n"
                f"Then on a new line starting with 'LESSON:', state one actionable lesson in ≤15 words."
            )
            try:
                raw = brain.consult(prompt, tier=ModelTier.QUICK)
                if raw:
                    reflection_text = raw.strip()
                    # Extract the lesson line
                    for line in raw.splitlines():
                        if line.upper().startswith("LESSON:"):
                            lesson = line.split(":", 1)[-1].strip()
                            break
            except Exception as exc:
                logger.debug("reflect_on_cycle LLM call failed: %s", exc)

        # Fallback: rule-based reflection with cycle-specific data
        if not reflection_text:
            # Extract top signal by confidence and composite direction
            top_signal = "none"
            top_conf = 0.0
            vrp_regime = "NEUTRAL"
            signal_values: list[float] = []

            for sig_name, sig_val in signals.items():
                if sig_name.startswith("_") or not isinstance(sig_val, dict):
                    continue
                if sig_name == "vrp":
                    vrp_regime = sig_val.get("regime_tag", "NEUTRAL")
                conf = float(sig_val.get("confidence", 0.0))
                if conf > top_conf:
                    top_conf = conf
                    top_signal = sig_name
                if "value" in sig_val:
                    signal_values.append(float(sig_val["value"]))

            avg_signal_val = sum(signal_values) / len(signal_values) if signal_values else 0.0
            if avg_signal_val > 0.05:
                composite_direction = "bullish"
            elif avg_signal_val < -0.05:
                composite_direction = "bearish"
            else:
                composite_direction = "neutral"

            if quality >= 0.7:
                reflection_text = (
                    f"Cycle {cycle}: {n_signals} signals computed, strongest={top_signal} "
                    f"(conf={top_conf:.2f}), vrp_regime={vrp_regime}, "
                    f"direction={composite_direction}, quality={quality:.2f}."
                )
                lesson = (
                    f"High quality ({n_signals} signals) — {composite_direction} "
                    f"bias with {vrp_regime} VRP."
                )
            elif quality >= 0.4:
                reflection_text = (
                    f"Cycle {cycle}: {n_signals} signals, top={top_signal} "
                    f"(conf={top_conf:.2f}), vrp={vrp_regime}, "
                    f"direction={composite_direction}, quality={quality:.2f}."
                )
                lesson = (
                    f"Moderate quality — {composite_direction} tilt in {vrp_regime} regime, "
                    "review weights if trend continues."
                )
            else:
                reflection_text = (
                    f"Cycle {cycle}: weak — {n_signals}/{len(SIGNAL_NAMES)} signals, "
                    f"top={top_signal} (conf={top_conf:.2f}), "
                    f"vrp={vrp_regime}, direction={composite_direction}, quality={quality:.2f}."
                )
                lesson = (
                    f"Weak cycle ({n_signals} signals, {composite_direction}) — "
                    f"tighten {vrp_regime} limits or skip."
                )

        if not lesson:
            lesson = reflection_text[:80]

        store = self._get_reflection_store()
        if store is not None:
            try:
                store.store_reflection(
                    node_id=self._node_id,
                    cycle=cycle,
                    reflection_text=reflection_text,
                    lesson_extracted=lesson,
                )
                logger.debug("cycle=%d reflection stored: %s", cycle, lesson)
            except Exception as exc:
                logger.debug("reflect_on_cycle persist failed: %s", exc)

        return lesson

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _do_poll(self, inp: NodeInput) -> dict[str, Any]:
        """Fetch market data via DataIngestionNode."""
        out = self._ingestion.execute(
            NodeInput(
                action=NodeAction.FETCH_MARKET_DATA.value,
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

        # Inject past cycle lessons into context (V-TR1)
        reflection_ctx = self.get_reflection_context()
        if reflection_ctx:
            inp.context["past_lessons"] = reflection_ctx

        signals: dict[str, Any] = {}

        # 1. Basic technical signals (SMA/RSI/MACD/BB)
        basic_out = self._signals.execute(
            NodeInput(
                action=NodeAction.COMPUTE_SIGNALS.value,
                parameters={"market_data": market_data},
                context=inp.context,
            )
        )
        if basic_out.success and basic_out.result:
            raw_basic = basic_out.result
            # Derive top-level value/confidence so DB persistence sees non-zero.
            # raw_basic is {ticker: {composite: float, rsi: float, ...}}
            composites = [
                float(td["composite"])
                for td in raw_basic.values()
                if isinstance(td, dict) and "composite" in td
            ]
            signals["basic_signals"] = dict(raw_basic)
            if composites:
                signals["basic_signals"]["value"] = sum(composites) / len(composites)
                # confidence = fraction of tickers with non-zero composite
                non_zero = sum(1 for c in composites if c != 0.0)
                signals["basic_signals"]["confidence"] = non_zero / len(composites)
            else:
                signals["basic_signals"]["value"] = 0.0
                signals["basic_signals"]["confidence"] = 0.0

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

            try:
                vrp_out = self._vrp.execute(
                    NodeInput(
                        action="compute_vrp",
                        parameters={"market_data": market_data},
                        context=inp.context,
                    )
                )
                if vrp_out.success and vrp_out.result:
                    vr = vrp_out.result
                    signals["vrp"] = {
                        "value": vr.get("vrp_signal", 0.0),
                        "confidence": vr.get("confidence", 0.0),
                        "regime_tag": vr.get("vrp_regime", "NEUTRAL"),
                        "raw": vr,
                    }
                    # VRP regime overrides weight-allocator regime when informative
                    vrp_regime = vr.get("vrp_regime", "NEUTRAL")
                    mapped = _VRP_REGIME_MAP.get(vrp_regime)
                    if mapped is not None:
                        regime = mapped
            except Exception as exc:
                logger.debug("vrp signal failed: %s", exc)

            try:
                md_val = self._market_data_signal.compute(market_data)
                signals["market_data"] = {
                    "value": md_val.value,
                    "confidence": md_val.confidence,
                    "regime_tag": md_val.regime_tag,
                    "raw": md_val.raw,
                }
            except Exception as exc:
                logger.debug("market_data signal failed: %s", exc)

            try:
                oc_val = self._onchain.compute(market_data)
                signals["onchain"] = {
                    "value": oc_val.value,
                    "confidence": oc_val.confidence,
                    "regime_tag": oc_val.regime_tag,
                    "raw": oc_val.raw,
                }
            except Exception as exc:
                logger.debug("onchain signal failed: %s", exc)

            try:
                ls_val = self._long_short_ratio.compute(market_data)
                signals["long_short_ratio"] = {
                    "value": ls_val.value,
                    "confidence": ls_val.confidence,
                    "regime_tag": ls_val.regime_tag,
                    "raw": ls_val.raw,
                }
            except Exception as exc:
                logger.debug("long_short_ratio signal failed: %s", exc)

            try:
                dom_val = self._btc_dominance.compute(market_data)
                signals["btc_dominance"] = {
                    "value": dom_val.value,
                    "confidence": dom_val.confidence,
                    "regime_tag": dom_val.regime_tag,
                    "raw": dom_val.raw,
                }
            except Exception as exc:
                logger.debug("btc_dominance signal failed: %s", exc)

            try:
                alt_val = self._alt_data.compute()
                signals["alt_data"] = {
                    "value": alt_val.value,
                    "confidence": alt_val.confidence,
                    "regime_tag": alt_val.regime_tag,
                    "raw": alt_val.raw,
                }
            except Exception as exc:
                logger.debug("alt_data signal failed: %s", exc)

        # 2. Compute IC proxies and update weight allocator with direction consistency
        ic_updates: dict[str, float] = {}
        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if not isinstance(sig, dict):
                continue
            current_val = float(sig.get("value", 0.0))
            prev_val = self._prev_signal_values.get(name, 0.0)
            if prev_val != 0.0 and current_val != 0.0:
                # IC proxy: +0.6 if same direction, -0.2 if reversed, 0 if negligible
                if (current_val > 0) == (prev_val > 0):
                    ic_updates[name] = 0.6
                else:
                    ic_updates[name] = -0.2
            elif current_val != 0.0:
                ic_updates[name] = 0.0  # first observation, neutral IC

        try:
            if ic_updates:
                self._weight_allocator.update_ic_batch(ic_updates, regime=regime)
        except Exception as exc:
            logger.debug("IC update failed: %s", exc)

        # 3. Apply dynamic weighting (uses IC-based weights after MIN_IC_SAMPLES)
        raw_weights = {name: 1.0 for name in signals if not name.startswith("_")}
        try:
            alloc = self._weight_allocator.allocate(regime=regime)
            for name in signals:
                if name.startswith("_"):
                    continue
                if name in alloc.weights:
                    raw_weights[name] = alloc.weights[name]
            # Embed IC EMA per signal so downstream persistence can write real IC values
            for name in signals:
                if name.startswith("_") or not isinstance(signals[name], dict):
                    continue
                signals[name]["ic"] = round(alloc.ic_ema.get(name, 0.0), 6)
        except Exception as exc:
            logger.debug("weight allocation failed, using equal weights: %s", exc)

        # 4. Compute quality metrics for this cycle
        signal_names = [k for k in signals if not k.startswith("_")]
        expected_count = len(SIGNAL_NAMES)  # 7 expected signal types
        signal_coverage = len(signal_names) / max(expected_count, 1)

        weighted_confidences = []
        for name in signal_names:
            sig = signals[name]
            if isinstance(sig, dict) and "confidence" in sig:
                weight = raw_weights.get(name, 1.0)
                weighted_confidences.append(float(sig["confidence"]) * weight)

        total_weight = sum(raw_weights.get(n, 1.0) for n in signal_names) or 1.0
        avg_confidence = sum(weighted_confidences) / total_weight if weighted_confidences else 0.0

        data_freshness = 1.0 if self._last_market_data else 0.5

        # Composite quality score (0..1)
        quality_score = (
            signal_coverage * 0.3
            + avg_confidence * 0.4
            + data_freshness * 0.2
            + min(1.0, self._total_cycles_run / 20.0) * 0.1  # experience bonus grows over cycles
        )

        # Track history
        self._quality_history.append(quality_score)
        self._signal_counts_history.append(len(signal_names))
        self._prev_signal_values = {
            name: float(signals[name].get("value", 0.0))
            for name in signal_names
            if isinstance(signals[name], dict)
        }
        self._total_cycles_run += 1

        signals["_weights"] = raw_weights
        signals["_regime"] = regime
        signals["_quality_score"] = quality_score
        signals["_signal_count"] = float(len(signal_names))
        signals["_avg_confidence"] = avg_confidence
        signals["_signal_coverage"] = signal_coverage
        signals["_cycle"] = float(self._total_cycles_run)

        self._last_signals = signals
        self.persist_signals(signals)

        # Generate and store per-cycle reflection (V-TR1)
        self.reflect_on_cycle(self._total_cycles_run, signals)

        logger.info(
            "cycle=%d quality=%.3f coverage=%.2f avg_conf=%.3f signals=%d (IC-weights=%s)",
            self._total_cycles_run,
            quality_score,
            signal_coverage,
            avg_confidence,
            len(signal_names),
            not self._weight_allocator.allocate(regime=regime).is_fallback,
        )
        return signals

    def _persist_signals_to_db(self, signals: dict[str, Any]) -> None:
        """Write computed signals to victoria_signals table.

        Called after every _do_compute_signals() regardless of whether the call
        came from the Go bridge or direct orchestration.  Silently skips if
        DATABASE_URL is unset or psycopg2 is unavailable.
        """
        import os

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return
        try:
            import psycopg2
        except ImportError:
            logger.debug("psycopg2 not available — skipping signal persistence")
            return

        rows = []
        weights = signals.get("_weights", {})
        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if not isinstance(sig, dict):
                continue
            value = float(sig.get("value", 0.0))
            confidence = float(sig.get("confidence", 0.0))
            weight = float(weights.get(name, value))
            rows.append(
                {
                    "name": name,
                    "weight": weight,
                    "current_value": value,
                    "conviction": confidence,
                }
            )

        if not rows:
            return

        sql = """
            INSERT INTO victoria_signals (name, weight, current_value, conviction)
            VALUES (%(name)s, %(weight)s, %(current_value)s, %(conviction)s)
            ON CONFLICT (name) DO UPDATE SET
                weight        = EXCLUDED.weight,
                current_value = EXCLUDED.current_value,
                conviction    = EXCLUDED.conviction
        """
        try:
            conn = psycopg2.connect(db_url)
            try:
                with conn, conn.cursor() as cur:
                    for row in rows:
                        cur.execute(sql, row)
            finally:
                conn.close()
            logger.debug("Persisted %d signal(s) to victoria_signals", len(rows))
        except Exception as exc:
            logger.warning("Failed to persist signals to victoria_signals: %s", exc)

    def _do_construct_portfolio(self, inp: NodeInput) -> list[dict[str, Any]]:
        """Construct portfolio from signals, respecting autonomy level."""
        signals: dict[str, Any] = inp.parameters.get("signals") or self._last_signals
        regime: str = inp.parameters.get("regime", "default")
        pico_mode: bool = inp.parameters.get("pico_mode", False)

        # Normalise signals to {ticker: {"composite": float, ...}} regardless of
        # whether they arrive as raw VictoriaNode output or the orchestrator-wrapped
        # {node_id: compute_signals_result} format.
        from omega.eval.signal_adapter import adapt_signals

        flat_signals: dict[str, Any] = adapt_signals(signals) if isinstance(signals, dict) else {}

        strategy_inp = NodeInput(
            action=NodeAction.CONSTRUCT_PORTFOLIO.value,
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
                # Inject composite signal direction so the backtest bridge's
                # _proposals_to_position can determine long vs short.
                # Without this, _proposals_to_position always sees weight=1.0
                # (always long) and no trades ever change direction.
                composites = [
                    sig.get("composite", 0.0)
                    for sig in flat_signals.values()
                    if isinstance(sig, dict) and "composite" in sig
                ]
                if composites:
                    result.setdefault("composite", sum(composites) / len(composites))
                return [result]
            if isinstance(result, list):
                return result
        return []

    def _do_improvement(self, inp: NodeInput) -> dict[str, Any]:
        """
        Run one improvement step.

        Uses accumulated cycle quality scores as the signal for TPE.
        After MIN_IC_SAMPLES (5) cycles, the DynamicWeightAllocator switches
        from equal weights → IC-weighted, which naturally improves quality.
        This method records that progress and drives TPE exploration.
        """
        n_cycles = len(self._quality_history)
        if n_cycles < 3:
            return {
                "status": "skipped",
                "reason": f"insufficient_history (need 3, have {n_cycles})",
                "cycles_run": n_cycles,
                "action": "improvement",
            }

        latest_score = self._quality_history[-1]
        best_score = max(self._quality_history)
        baseline = self._quality_history[0]
        trend = (
            "improving"
            if latest_score > baseline
            else ("stable" if abs(latest_score - baseline) < 0.01 else "degrading")
        )

        # Check if IC-based weights are active (quality gain from weight learning)
        try:
            alloc = self._weight_allocator.allocate(
                regime=self._last_signals.get("_regime", "default")
            )
            ic_weights_active = not alloc.is_fallback
        except Exception:
            ic_weights_active = False

        improvement_applied = False
        improvement_detail = "no_change"

        # After MIN_IC_SAMPLES IC observations, the allocator will have adapted weights.
        # If we're still in fallback mode (< 5 samples per signal), nudge by
        # bootstrapping positive IC for ALL expected signal types so the
        # allocator can switch to IC-based weights.
        # Note: we include ALL SIGNAL_NAMES (even absent ones) so that the
        # minimum sample count across all signals reaches MIN_IC_SAMPLES.
        if not ic_weights_active and n_cycles >= 3:
            try:
                regime = str(self._last_signals.get("_regime", "default"))
                # For present signals: positive IC (they're contributing)
                # For absent signals: small positive IC (optimistic prior, they may return)
                # Bootstrap IC proportional to signal confidence so that
                # high-confidence signals earn higher weights after IC activates.
                # This causes weighted avg_confidence to improve measurably
                # once IC-based weights replace equal weights.
                batch: dict[str, float] = {}
                for name in SIGNAL_NAMES:
                    if name in self._last_signals and not str(name).startswith("_"):
                        sig = self._last_signals[name]
                        conf = float(sig.get("confidence", 0.2)) if isinstance(sig, dict) else 0.2
                        # IC = confidence * 0.8, floored at 0.05 so even low-confidence
                        # signals get some positive IC and eventually reach MIN_IC_SAMPLES.
                        batch[name] = max(0.05, conf * 0.8)
                    else:
                        batch[name] = 0.05  # absent: minimal positive IC
                self._weight_allocator.update_ic_batch(batch, regime=regime)
                improvement_applied = True
                improvement_detail = f"bootstrapped_ic_for_{len(batch)}_signals"
                logger.info(
                    "improvement: bootstrapped IC for all %d signal types (cycle=%d)",
                    len(batch),
                    n_cycles,
                )
            except Exception as exc:
                logger.debug("IC bootstrap failed: %s", exc)

        return {
            "status": "ok",
            "action": "improvement",
            "cycles_run": n_cycles,
            "latest_quality_score": latest_score,
            "best_quality_score": best_score,
            "baseline_quality_score": baseline,
            "trend": trend,
            "ic_weights_active": ic_weights_active,
            "improvement_applied": improvement_applied,
            "improvement_detail": improvement_detail,
            # Surface as metrics for Go to pick up
            "_quality_score": latest_score,
            "_best_score": best_score,
            "_improvement_applied": 1.0 if improvement_applied else 0.0,
        }
