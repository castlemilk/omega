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

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.state_tensor import StateTensor, VictoriaStateTensorBuilder
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.dynamic_weights import DynamicWeightAllocator
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.signals_advanced import (
    CrossAssetSignal,
    MicrostructureSignal,
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
            "poll",
            "fetch_data",
            "compute_signals",
            "construct_portfolio",
            "backtest_strategy",
            "rank_signals",
            # Go pipeline step NodeType aliases (registered as DATA_INGESTION etc.)
            "data_ingestion",
            "signal_research",
            "strategy",
            "risk_management",
            "verification",
            "memory",
            "improvement",
            "adversarial",
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
            if action in ("poll", "fetch_data", "data_ingestion", "dataingestion"):
                result = self._do_poll(inp)
            elif action in ("compute_signals", "signal_research", "signalresearch"):
                result = self._do_compute_signals(inp)
            elif action in (
                "construct_portfolio",
                "strategy",
                "risk_management",
                "riskmanagement",
                "intelligencecoordination",
                "dynamicweights",
            ):
                result = self._do_construct_portfolio(inp)
            elif action in ("backtest_strategy", "rank_signals"):
                # Delegate to inner StrategyNode
                result_out = self._strategy.execute(inp)
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                return result_out
            elif action in (
                "verification",
                "debategate",
                "walkforward",
                "memory",
                "improvement",
                "improvementengine",
                "adversarial",
                "ring3adversarial",
            ):
                # These are handled internally by Python orchestrator; return success no-op
                result = {"status": "ok", "action": action}
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
        self.persist_signals(signals)
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
