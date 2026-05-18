"""
omega.nodes.victoria.signal_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SignalGenerationNode — computes quantitative trading signals from market data.

Crypto-specific signals included:
  - BTC beta (correlation of each asset to BTC)
  - Volume z-score (volume spike as sentiment/momentum proxy)
  - Volatility regime (annualised vol vs 90-day average)
  - Funding rate proxy (price/volume divergence)

Improvement arc:
  v1.0 — SMA crossover (5/20) only
  v1.1 — RSI (14-day) + volume z-score added
  v1.2 — MACD, Bollinger Bands, Z-score momentum, BTC beta added
  v1.3 — Parameter tuning based on signal quality feedback
"""

from __future__ import annotations

import contextlib
import logging
import math
import time
import uuid
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

try:
    from omega.nodes.victoria.ml_combiner import SignalCombiner
except ImportError:
    SignalCombiner = None  # type: ignore[assignment,misc]

try:
    from omega.nodes.victoria.signals.funding_rate import FundingRateSignal as _FundingRateSignal

    _HAS_FUNDING_RATE = True
except ImportError:
    _HAS_FUNDING_RATE = False

try:
    from omega.nodes.victoria.signals.fear_greed import FearGreedSignal as _FearGreedSignal

    _HAS_FEAR_GREED = True
except ImportError:
    _HAS_FEAR_GREED = False

try:
    from omega.nodes.victoria.signals.dxy_signal import DXYSignal as _DXYSignal

    _HAS_DXY = True
except ImportError:
    _HAS_DXY = False

try:
    from omega.nodes.victoria.signals.vix_signal import VIXSignal as _VIXSignal

    _HAS_VIX = True
except ImportError:
    _HAS_VIX = False

try:
    from omega.nodes.victoria.signals.yield_curve import YieldCurveSignal as _YieldCurveSignal

    _HAS_YIELD_CURVE = True
except ImportError:
    _HAS_YIELD_CURVE = False

try:
    from omega.nodes.victoria.signals.spy_signal import SPYSignal as _SPYSignal

    _HAS_SPY = True
except ImportError:
    _HAS_SPY = False

try:
    from omega.nodes.victoria.geometry.market_manifold import MarketManifold as _MarketManifold

    _HAS_MANIFOLD = True
except ImportError:
    _HAS_MANIFOLD = False

try:
    from omega.nodes.victoria.geometry.ollivier_ricci import (
        OllivierRicciCurvature as _OllivierRicci,
    )

    _HAS_ORC = True
except ImportError:
    _HAS_ORC = False

try:
    from omega.nodes.victoria.signals.wasserstein_regime import (
        WassersteinRegimeSignal as _WassersteinRegimeSignal,
    )

    _HAS_WASSERSTEIN_REGIME = True
except ImportError:
    _HAS_WASSERSTEIN_REGIME = False

try:
    from omega.nodes.victoria.signals.tda_signal import TDASignal as _TDASignal

    _HAS_TDA_SIGNAL = True
except ImportError:
    _HAS_TDA_SIGNAL = False

logger = logging.getLogger("omega.nodes.victoria.signal_generation")

# V103: optional new-architecture modules — import lazily to preserve V93 baseline
try:
    from omega.nodes.victoria.features import VictoriaFeatures as _VictoriaFeatures

    _HAS_FEATURES = True
except ImportError:
    _HAS_FEATURES = False

try:
    from omega.nodes.victoria.trade_reinforcement import TradeReinforcer as _TradeReinforcer

    _HAS_TRADE_REINFORCER = True
except ImportError:
    _HAS_TRADE_REINFORCER = False
    _TradeReinforcer = None

try:
    from omega.nodes.victoria.activation_trace import ActivationTracer as _ActivationTracer

    _HAS_ACTIVATION_TRACER = True
except ImportError:
    _HAS_ACTIVATION_TRACER = False
    _ActivationTracer = None

try:
    from omega.nodes.victoria.ws_feeds import create_feed_manager as _create_feed_manager

    _HAS_WS_FEEDS = True
except ImportError:
    _HAS_WS_FEEDS = False

try:
    from omega.nodes.victoria.signal_memory import SignalMemory as _SignalMemory

    _HAS_SIGNAL_MEMORY = True
except ImportError:
    _HAS_SIGNAL_MEMORY = False

try:
    from omega.nodes.victoria.adaptive_combiner import AdaptiveCombiner as _AdaptiveCombiner

    _HAS_ADAPTIVE_COMBINER = True
except ImportError:
    _HAS_ADAPTIVE_COMBINER = False

try:
    from omega.nodes.victoria.signals.whale_flow import WhaleFlowSignals as _WhaleFlowSignals

    _HAS_WHALE_FLOW = True
except ImportError:
    _HAS_WHALE_FLOW = False

try:
    from omega.nodes.victoria.signals.geopolitical import GeopoliticalSignal as _GeopoliticalSignal

    _HAS_GEOPOLITICAL = True
except ImportError:
    _HAS_GEOPOLITICAL = False

try:
    from omega.nodes.victoria.signals.vpin import VPINSignal as _VPINSignal
    _HAS_VPIN = True
except ImportError:
    _HAS_VPIN = False

try:
    from omega.nodes.victoria.signals.kyles_lambda import KylesLambdaSignal as _KylesLambdaSignal
    _HAS_KYLES_LAMBDA = True
except ImportError:
    _HAS_KYLES_LAMBDA = False

try:
    from omega.nodes.victoria.signals.lob_features import LOBFeaturesSignal as _LOBFeaturesSignal
    _HAS_LOB_FEATURES = True
except ImportError:
    _HAS_LOB_FEATURES = False

try:
    from omega.nodes.victoria.signals.dynamic_graph import DynamicGraphSignal as _DynamicGraphSignal
    _HAS_DYNAMIC_GRAPH = True
except ImportError:
    _HAS_DYNAMIC_GRAPH = False

try:
    from omega.nodes.victoria.signals.range_trading import RangeTradingSignal as _RangeTradingSignal
    _HAS_RANGE_TRADING = True
except ImportError:
    _HAS_RANGE_TRADING = False

try:
    from omega.nodes.victoria.signals.funding_carry import FundingCarrySignal as _FundingCarrySignal
    _HAS_FUNDING_CARRY = True
except ImportError:
    _HAS_FUNDING_CARRY = False

# V157: trend-following signals (price-only, no external deps — always importable)
try:
    from omega.nodes.victoria.signals import breakout as _breakout_mod
    from omega.nodes.victoria.signals import trend_strength as _trend_strength_mod
    from omega.nodes.victoria.signals import multi_timeframe as _mtf_mod

    _HAS_TREND_SIGNALS = True
except ImportError:
    _HAS_TREND_SIGNALS = False

# V162: volatility shock detector (price-only, no external deps).
try:
    from omega.nodes.victoria.signals import vol_shock as _vol_shock_mod

    _HAS_VOL_SHOCK = True
except ImportError:
    _HAS_VOL_SHOCK = False


def _safe_mean(values: list[float | None], n: int) -> float | None:
    clean = [v for v in values[-n:] if v is not None]
    return sum(clean) / len(clean) if clean else None


def _balanced_composite(directional: list[float]) -> float:
    """
    Balanced composite signal using a trimmed mean.

    Equal treatment of all sub-signals regardless of recent price direction.
    Trimming the top/bottom 20% removes outlier signals that would skew the
    composite without adding directional information.

    Previous approach (momentum-weighted 2x/1x) created a structural bias:
    in a bear market, bearish signals got 2x weight, pushing all composites
    negative and preventing long trades regardless of per-ticker oversold
    conditions. A symmetric aggregation lets each ticker's signal mix determine
    direction independently.
    """
    if not directional:
        return 0.0
    if len(directional) < 4:
        return sum(directional) / len(directional)
    n_trim = max(1, len(directional) // 5)
    trimmed = sorted(directional)[n_trim:-n_trim]
    return sum(trimmed) / len(trimmed) if trimmed else sum(directional) / len(directional)


_ANTI_PRED_IC_THRESHOLD = -0.05
_ACTIVE_IC_THRESHOLD = 0.05
_IC_WEIGHTED_MIN_SIGNALS = 3


def _ic_weighted_composite(
    signals_dict: dict,
    decay_detector: Any,  # SignalDecayDetector | None — lazy-typed to avoid circular import
) -> tuple[float, str]:
    """
    IC-weighted composite signal.

    Uses per-signal Information Coefficient values from SignalDecayDetector to
    assign weights proportional to each signal's historical predictive power.

    Weight rules:
      - IC is None (no history): weight = 0.5 (neutral/uncertain)
      - IC < -0.05 (anti-predictive): weight = 0.0 (excluded)
      - 0 <= IC < 0.05 (weak): weight = max(0.1, IC / 0.05)
      - IC >= 0.05 (active): weight = IC / 0.05 (scale proportionally)

    Falls back to _balanced_composite (equal-weight) when:
      - decay_detector is None, or
      - fewer than 3 signals have IC data
    """
    if decay_detector is None:
        signal_vals = [
            v for k, v in signals_dict.items() if k.endswith("_signal") or k == "sma_crossover"
        ]
        return _balanced_composite(signal_vals), "equal_weight"

    weights: list[float] = []
    values: list[float] = []
    n_with_ic = 0

    for key, val in signals_dict.items():
        if not (key.endswith("_signal") or key == "sma_crossover"):
            continue
        ic = decay_detector.ic_for(key)
        if ic is not None:
            n_with_ic += 1
            if ic < _ANTI_PRED_IC_THRESHOLD:
                w = 0.0
            elif ic < _ACTIVE_IC_THRESHOLD:
                w = max(0.1, ic / _ACTIVE_IC_THRESHOLD)
            else:
                w = ic / _ACTIVE_IC_THRESHOLD
        else:
            w = 0.5  # neutral weight for signals without IC history
        weights.append(w)
        values.append(float(val))

    if n_with_ic < _IC_WEIGHTED_MIN_SIGNALS:
        signal_vals = [
            v for k, v in signals_dict.items() if k.endswith("_signal") or k == "sma_crossover"
        ]
        return _balanced_composite(signal_vals), "equal_weight"

    total_w = sum(weights)
    if total_w == 0.0:
        signal_vals = [
            v for k, v in signals_dict.items() if k.endswith("_signal") or k == "sma_crossover"
        ]
        return _balanced_composite(signal_vals), "equal_weight"

    weighted_mean = sum(w * v for w, v in zip(weights, values, strict=False)) / total_w
    clamped = max(-1.0, min(1.0, weighted_mean))
    return clamped, "ic_weighted"


class SignalGenerationNode(Node):
    """
    Computes quantitative trading signals from OHLCV market data.

    Capabilities : compute_signals, compute_momentum, compute_mean_reversion
    Improves via : adding indicator types (RSI → MACD/BB → parameter tuning)
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._sma_short = 5
        self._sma_long = 20
        self._rsi_period = 14
        self._bb_period = 20
        self._bb_std = 2.0
        self._zscore_period = 20
        self._macd_fast = 12
        self._macd_slow = 26
        self._macd_signal_period = 9
        self._use_rsi = False
        self._use_macd = False
        self._use_bb = False
        self._use_zscore = False
        self._use_btc_beta = False
        self._use_volume_zscore = False
        self._use_vol_regime = False
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._signals_generated = 0
        self._last_signal_coverage = 0.0

        # ML signal combiner — replaces equal-weight composite when trained
        self._combiner: SignalCombiner | None = None
        try:
            if SignalCombiner is not None:
                self._combiner = SignalCombiner()
                self._combiner.load("data/signal_weights.json")
        except Exception:
            pass

        # IC-weighted composite: decay detector loaded lazily on first use
        self._decay_detector: Any | None = None

        # Funding rate signal
        self._funding_signal: Any | None = None
        if _HAS_FUNDING_RATE:
            with contextlib.suppress(Exception):
                self._funding_signal = _FundingRateSignal(window=30)

        # Fear & Greed contrarian signal (market-level, applied to all tickers)
        self._fear_greed_signal: Any | None = None
        if _HAS_FEAR_GREED:
            with contextlib.suppress(Exception):
                self._fear_greed_signal = _FearGreedSignal(window=30)

        # DXY/BTC correlation signal (market-level, applied to all tickers)
        self._dxy_signal: Any | None = None
        if _HAS_DXY:
            with contextlib.suppress(Exception):
                self._dxy_signal = _DXYSignal(window=20)

        # VIX risk-off signal (market-level, applied to all tickers)
        self._vix_signal: Any | None = None
        if _HAS_VIX:
            with contextlib.suppress(Exception):
                self._vix_signal = _VIXSignal(window=30)

        # Yield curve signal — 2s10s spread via FRED (market-level)
        self._yield_curve_signal: Any | None = None
        if _HAS_YIELD_CURVE:
            with contextlib.suppress(Exception):
                self._yield_curve_signal = _YieldCurveSignal()

        # SPY/BTC co-movement signal — risk-on/off overlay (market-level)
        self._spy_signal: Any | None = None
        if _HAS_SPY:
            with contextlib.suppress(Exception):
                self._spy_signal = _SPYSignal(window=20)

        # Information geometry: market manifold (Ricci curvature signal)
        self._market_manifold: Any | None = None
        if _HAS_MANIFOLD:
            with contextlib.suppress(Exception):
                self._market_manifold = _MarketManifold(window=30, min_samples=10)

        # Graph geometry: Ollivier-Ricci curvature on correlation network
        self._orc: Any | None = None
        if _HAS_ORC:
            with contextlib.suppress(Exception):
                self._orc = _OllivierRicci(window=30, corr_threshold=0.4)

        # V103: load feature flags + optional new-architecture components
        self._features: Any = _VictoriaFeatures.from_env() if _HAS_FEATURES else None

        # V103 ws_microstructure: background WS feeds for microstructure signals
        self._ws_feeds: Any = None
        if (
            _HAS_WS_FEEDS
            and self._features
            and getattr(self._features, "ws_microstructure", False)
        ):
            with contextlib.suppress(Exception):
                from omega.nodes.victoria.strategy import _TRADING_BLACKLIST

                _ws_symbols = [
                    s
                    for s in ["ETHUSDT", "NEARUSDT", "ARBUSDT", "ADAUSDT", "BTCUSDT"]
                    if s not in _TRADING_BLACKLIST
                ]
                self._ws_feeds = _create_feed_manager(_ws_symbols)
                self._ws_feeds.start()
                logger.info("WSFeedManager started for %s", _ws_symbols)

        # V103 temporal_memory: 20-cycle signal history per ticker
        self._signal_memory: Any = None
        if (
            _HAS_SIGNAL_MEMORY
            and self._features
            and getattr(self._features, "temporal_memory", False)
        ):
            with contextlib.suppress(Exception):
                _imd = bool(getattr(self._features, "improved_momentum_derivative", False))
                self._signal_memory = _SignalMemory(lookback=20, improved_momentum_derivative=_imd)
                logger.info("SignalMemory initialized (lookback=20, imd=%s)", _imd)

        # V103 adaptive_combiner: IC-weighted combiner with signal flipping
        self._adaptive_combiner: Any = None
        if (
            _HAS_ADAPTIVE_COMBINER
            and self._features
            and getattr(self._features, "adaptive_combiner", False)
        ):
            with contextlib.suppress(Exception):
                self._adaptive_combiner = _AdaptiveCombiner()
                logger.info("AdaptiveCombiner initialized")

        # V115 whale_flow: DefiLlama bridge + stablecoin + OKX OI signals
        self._whale_flow: Any = None
        if _HAS_WHALE_FLOW and self._features and getattr(self._features, "whale_flow", False):
            with contextlib.suppress(Exception):
                self._whale_flow = _WhaleFlowSignals()
                logger.info("WhaleFlowSignals initialized")

        # V185 VPIN wrapper: z-score + spike features over raw VPIN.
        self._vpin_signal: Any = None
        if _HAS_VPIN and self._features and getattr(self._features, "vpin_signal", False):
            with contextlib.suppress(Exception):
                self._vpin_signal = _VPINSignal()
                logger.info("VPINSignal initialized")

        # V185 Kyle's lambda: market-impact-based informed-trader detector.
        self._kyles_lambda: Any = None
        if _HAS_KYLES_LAMBDA and self._features and getattr(self._features, "kyles_lambda_signal", False):
            with contextlib.suppress(Exception):
                self._kyles_lambda = _KylesLambdaSignal(ws_feeds=self._ws_feeds)
                logger.info("KylesLambdaSignal initialized")

        # V185 LOB features: multi-level OFI, arrival rate z, adverse selection.
        self._lob_features: Any = None
        if _HAS_LOB_FEATURES and self._features and getattr(self._features, "lob_features", False):
            with contextlib.suppress(Exception):
                self._lob_features = _LOBFeaturesSignal(ws_feeds=self._ws_feeds)
                logger.info("LOBFeaturesSignal initialized")

        # V187 dynamic correlation graph: EMGNN-lite, works in backtest + live.
        self._dynamic_graph: Any = None
        if _HAS_DYNAMIC_GRAPH and self._features and getattr(self._features, "dynamic_graph_signal", False):
            with contextlib.suppress(Exception):
                self._dynamic_graph = _DynamicGraphSignal()
                logger.info("DynamicGraphSignal initialized")

        # V191 range-trading + funding-carry signals — fire in flat/low-vol.
        self._range_trading: Any = None
        if _HAS_RANGE_TRADING and self._features and getattr(self._features, "range_trading_enabled", False):
            with contextlib.suppress(Exception):
                self._range_trading = _RangeTradingSignal()
                logger.info("RangeTradingSignal initialized")
        self._funding_carry: Any = None
        if _HAS_FUNDING_CARRY and self._features and getattr(self._features, "funding_carry_signal", False):
            with contextlib.suppress(Exception):
                self._funding_carry = _FundingCarrySignal()
                logger.info("FundingCarrySignal initialized")

        # V138 geopolitical_signals: GDELT DOC 2.0 event signals
        self._geo_signal: Any = None
        if (
            _HAS_GEOPOLITICAL
            and self._features
            and getattr(self._features, "geopolitical_signals", False)
        ):
            with contextlib.suppress(Exception):
                self._geo_signal = _GeopoliticalSignal()
                logger.info("GeopoliticalSignal initialized")

        # V152 wasserstein_regime: W₁ distance to return distribution archetypes
        self._wasserstein_regime_sig: Any = None
        if (
            _HAS_WASSERSTEIN_REGIME
            and self._features
            and getattr(self._features, "wasserstein_regime_enabled", False)
        ):
            with contextlib.suppress(Exception):
                _w_win = int(getattr(self._features, "wasserstein_window", 60))
                self._wasserstein_regime_sig = _WassersteinRegimeSignal(window=_w_win, min_obs=20)
                logger.info("WassersteinRegimeSignal initialized (window=%d)", _w_win)

        # V152 tda_signal: persistent homology crash-prediction signal
        self._tda_signal_inst: Any = None
        if (
            _HAS_TDA_SIGNAL
            and self._features
            and getattr(self._features, "tda_signal_enabled", False)
        ):
            with contextlib.suppress(Exception):
                _tda_win = int(getattr(self._features, "tda_window", 60))
                self._tda_signal_inst = _TDASignal(window=_tda_win, min_obs=30)
                logger.info("TDASignal initialized (window=%d)", _tda_win)

        # V153 regime_transition_signal: tracks prev regime to detect label changes
        self._prev_regime_for_transition: str | None = None

        # V106 trade_reinforcement: EMA-based per-signal weight adjustments
        self._reinforcer: Any = None
        if (
            _HAS_TRADE_REINFORCER
            and self._features
            and getattr(self._features, "trade_reinforcement", False)
        ):
            with contextlib.suppress(Exception):
                self._reinforcer = _TradeReinforcer()
                self._reinforcer.load()
                logger.info("TradeReinforcer loaded (n_trades=%d)", self._reinforcer._n_trades)

        # V107 activation_tracing: lazily initialized on first execute() call so that
        # run_training.py has time to set _version (e.g. "v107") before the tracer
        # file path is determined. Eager init here would always produce "1.0.jsonl".
        self._tracer: Any = None
        self._tracer_ready: bool = False

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="SignalGenerationNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "signal_coverage": self._last_signal_coverage,
                "signals_generated": float(self._signals_generated),
                "indicator_count": float(self._indicator_count()),
            },
            metadata={
                "indicators": self._active_indicators(),
                "sma_short": self._sma_short,
                "sma_long": self._sma_long,
            },
        )

    def get_capabilities(self) -> list[str]:
        return [NodeAction.COMPUTE_SIGNALS.value, "compute_momentum", "compute_mean_reversion"]

    def describe(self) -> str:
        return (
            "Computes quantitative trading signals from OHLCV market data. "
            "Supports SMA crossover, RSI, MACD, Bollinger Bands, and z-score "
            "momentum. Self-improves by adding new indicator types and tuning "
            "parameters based on signal quality feedback."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        # V107: lazy-init activation tracer on first execute so _version has been
        # set to the training version (e.g. "v107") by run_training.py before the
        # file path is determined. Eager __init__ always produced "1.0.jsonl".
        if (
            not self._tracer_ready
            and _HAS_ACTIVATION_TRACER
            and self._features
            and getattr(self._features, "activation_tracing", False)
        ):
            self._tracer_ready = True
            with contextlib.suppress(Exception):
                self._tracer = _ActivationTracer(version=self._version)
                self._tracer.open()
                logger.info("ActivationTracer lazy-init: writing to %s", self._tracer._path)

        t0 = time.perf_counter()
        action = input.action
        params = input.parameters
        market_data = params.get("market_data", {})

        try:
            if action == NodeAction.COMPUTE_SIGNALS.value:
                result = self._compute_all_signals(market_data)
            elif action == "compute_momentum":
                result = self._compute_momentum_signals(market_data)
            elif action == "compute_mean_reversion":
                result = self._compute_mean_reversion_signals(market_data)
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed

            valid_data = {k: v for k, v in market_data.items() if v}
            coverage = len(result) / max(1, len(valid_data))
            self._last_signal_coverage = coverage
            self._signals_generated += len(result)

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": elapsed,
                    "signal_coverage": coverage,
                    "indicator_count": float(self._indicator_count()),
                    "tickers_with_signals": float(len(result)),
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("SignalGenerationNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "signal_coverage": self._last_signal_coverage,
            "signals_generated": float(self._signals_generated),
            "indicator_count": float(self._indicator_count()),
        }

    def update_combiner(self, signals_dict: dict[str, Any], realized_pnl: float) -> None:
        """
        Update the ML signal combiner with a realized PnL observation.

        Call this after a trade closes with the per-ticker signals dict that
        generated the trade and the actual PnL.  The combiner refits its Ridge
        weights online and persists the updated model to data/signal_weights.json.
        """
        if self._combiner is None:
            return
        try:
            self._combiner.update(signals_dict, realized_pnl)
            self._combiner.persist("data/signal_weights.json")
        except Exception as exc:
            logger.warning("update_combiner: failed to update or persist: %s", exc)

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        iteration = feedback.get("iteration", 0)

        # v1.1: Add RSI + volume z-score after first iteration
        if not self._use_rsi and iteration >= 1:
            self._use_rsi = True
            self._use_volume_zscore = True
            self._version = "1.1"
            logger.info("SignalGenerationNode → v1.1: RSI(14) + volume z-score added")
            changed = True

        # v1.2: Add MACD, Bollinger Bands, Z-score, BTC beta, vol regime
        if self._use_rsi and not self._use_macd and iteration >= 2:
            self._use_macd = True
            self._use_bb = True
            self._use_zscore = True
            self._use_btc_beta = True
            self._use_vol_regime = True
            self._version = "1.2"
            logger.info(
                "SignalGenerationNode → v1.2: MACD, BB, Z-score, BTC-beta, vol-regime added"
            )
            changed = True

        # v1.3: Parameter tuning when coverage is low
        if (
            self._use_macd
            and self._version == "1.2"
            and self._last_signal_coverage < 0.7
            and self._execution_count >= 3
        ):
            self._sma_short = max(3, self._sma_short - 1)
            self._sma_long = max(10, self._sma_long - 2)
            self._version = "1.3"
            logger.info(
                "SignalGenerationNode → v1.3: SMA tuned to %d/%d for better coverage",
                self._sma_short,
                self._sma_long,
            )
            changed = True

        return changed

    # ------------------------------------------------------------------ signal computation

    def load_decay_detector(self) -> None:
        """Lazily load SignalDecayDetector for IC-weighted composite computation.

        Uses a deferred import to avoid circular imports. Silently skips if the
        IC history file does not exist or the import fails.
        """
        try:
            from omega.nodes.victoria.signal_decay import SignalDecayDetector

            self._decay_detector = SignalDecayDetector()
            self._decay_detector.load()
        except Exception:
            pass

    def warm_start_signals(self, pre_signal_dicts: list[dict[str, Any]]) -> None:
        """Pre-seed SignalMemory with signal history before trading begins.

        Called from run_training.py before the main loop when signal_memory_warm_start
        feature flag is ON. Feeds silent replay cycles into the memory without recording
        traces or advancing the trading cursor.

        Args:
            pre_signal_dicts: List of {ticker: {signal: value}} dicts, one per warm cycle.
        """
        if self._signal_memory is None:
            return
        try:
            self._signal_memory.warm_start(pre_signal_dicts)
            logger.info("SignalMemory warm-started with %d cycles", len(pre_signal_dicts))
        except Exception as exc:
            logger.warning("SignalMemory warm_start failed: %s", exc)

    def warm_start_geometry(self, pre_bars: list[dict[str, Any]]) -> None:
        """Pre-seed MarketManifold and OllivierRicciCurvature from snapshot pre-bars.

        Called from run_training.py before the main loop when geometry_warm_start
        feature flag is ON. Feeds the last 30 bars before the trading window into
        geometry objects so their correlation matrices are non-degenerate from cycle 1.

        Args:
            pre_bars: List of market_data dicts (from ReplayIngestionNode.get_pre_bars()),
                ordered oldest-first.
        """
        warmed = 0
        for bar in pre_bars:
            if self._market_manifold is not None:
                try:
                    self._market_manifold.update(bar)
                    warmed += 1
                except Exception as exc:
                    logger.debug("geometry_warm_start manifold bar failed: %s", exc)
            if self._orc is not None:
                try:
                    self._orc.update(bar)
                except Exception as exc:
                    logger.debug("geometry_warm_start orc bar failed: %s", exc)
        logger.info("Geometry warm-started with %d bars", warmed)

    def _compute_all_signals(self, market_data: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {}

        # Ensure IC-weighted composite has decay detector loaded (no-op if already set)
        if self._decay_detector is None:
            self.load_decay_detector()

        # Market-level cross-asset signals — computed once and applied to all tickers.
        _fear_greed_val: float = 0.0
        if self._fear_greed_signal is not None:
            try:
                _fear_greed_val = self._fear_greed_signal.compute()
            except Exception as _exc:
                logger.warning("FearGreedSignal compute error: %s", _exc)

        _dxy_val: float = 0.0
        if self._dxy_signal is not None:
            try:
                _dxy_val = self._dxy_signal.compute(market_data)
            except Exception as _exc:
                logger.warning("DXYSignal compute error: %s", _exc)

        _vix_val: float = 0.0
        if self._vix_signal is not None:
            try:
                _vix_val = self._vix_signal.compute()
            except Exception as _exc:
                logger.warning("VIXSignal compute error: %s", _exc)

        # V166: surface macro values at top-level so the per-cycle metrics
        # writer can read them without depending on whether they made it into
        # any per-ticker dict (the prior `if val != 0.0` gate dropped them).
        signals["_fear_greed_val"] = float(_fear_greed_val)
        signals["_dxy_val"] = float(_dxy_val)
        signals["_vix_val"] = float(_vix_val)

        # V173 market-level signals: mempool, google_trends, coinglass, coinmetrics.
        # All gated by per-source feature flags. Lazy-import per call to avoid
        # importing heavy deps when disabled.
        _f = self._features
        if getattr(_f, "mempool_signal_enabled", False):
            try:
                from omega.nodes.victoria.signals.mempool import MempoolSignal
                if not hasattr(self, "_mempool_inst"):
                    self._mempool_inst = MempoolSignal()
                _mp = self._mempool_inst.compute()
                for _k, _v in _mp.items():
                    signals[f"_{_k}"] = float(_v)
            except Exception as _mp_exc:
                logger.debug("mempool signal: %s", _mp_exc)
        if getattr(_f, "google_trends_signal_enabled", False):
            try:
                from omega.nodes.victoria.signals.google_trends import GoogleTrendsSignal
                if not hasattr(self, "_gtrends_inst"):
                    self._gtrends_inst = GoogleTrendsSignal()
                _gt = self._gtrends_inst.compute()
                for _k, _v in _gt.items():
                    signals[f"_{_k}"] = float(_v)
            except Exception as _gt_exc:
                logger.debug("google_trends signal: %s", _gt_exc)
        if getattr(_f, "coinglass_signal_enabled", False):
            try:
                from omega.nodes.victoria.signals.coinglass import CoinglassSignal
                if not hasattr(self, "_cg_inst"):
                    self._cg_inst = CoinglassSignal()
                _cg = self._cg_inst.compute()
                for _k, _v in _cg.items():
                    signals[f"_{_k}"] = float(_v)
            except Exception as _cg_exc:
                logger.debug("coinglass signal: %s", _cg_exc)
        if getattr(_f, "coinmetrics_signal_enabled", False):
            try:
                from omega.nodes.victoria.signals.coinmetrics import CoinMetricsSignal
                if not hasattr(self, "_cm_inst"):
                    self._cm_inst = CoinMetricsSignal()
                _cm = self._cm_inst.compute()
                for _k, _v in _cm.items():
                    signals[f"_{_k}"] = float(_v)
            except Exception as _cm_exc:
                logger.debug("coinmetrics signal: %s", _cm_exc)

        _yield_curve_val: float = 0.0
        if self._yield_curve_signal is not None:
            try:
                _yield_curve_val = self._yield_curve_signal.compute()
            except Exception as _exc:
                logger.warning("YieldCurveSignal compute error: %s", _exc)

        _spy_val: float = 0.0
        if self._spy_signal is not None:
            try:
                _spy_val = self._spy_signal.compute(market_data)
            except Exception as _exc:
                logger.warning("SPYSignal compute error: %s", _exc)

        # V138: geopolitical signals (market-level, applied to all tickers)
        _geo_signals: dict[str, float] = {}
        if self._geo_signal is not None:
            try:
                import datetime as _dt_mod
                _is_hist = self._features is not None and getattr(
                    self._features, "backtest_mode", False
                )
                _geo_signals = self._geo_signal.compute(
                    timestamp=_dt_mod.datetime.now(_dt_mod.timezone.utc),
                    is_historical=_is_hist,
                )
            except Exception as _geo_exc:
                logger.debug("GeopoliticalSignal compute error: %s", _geo_exc)

        _ricci_val: float = 0.0
        _ricci_regime: str = "transitional"
        if self._market_manifold is not None:
            try:
                _manifold_state = self._market_manifold.update(market_data)
                if _manifold_state is not None and _manifold_state.confidence >= 0.3:
                    _ricci_val = _manifold_state.signal
                    _ricci_regime = _manifold_state.regime
                    # V75: suppress false mean-reversion buy signals when the manifold calls
                    # "mean_reversion" but actual basket mean return is negative (downtrend).
                    # V74 post-mortem: ricci generated +0.78 (mean-reversion BUY) during the
                    # April 2026 crash, overriding fear_greed(-0.43) and VIX(-0.32) sell signals.
                    # The geo_dist gate is unreliable (FIM flattening at high variance makes
                    # crash/rally distances similar). Direct check is more robust:
                    # when regime="mean_reversion" but theta[0] (mean log-return) < 0, the
                    # manifold is calling "buy the dip" in an actual downtrend — dampen it.
                    # Gate: scale = max(0, 1 + theta_mu / 0.02), fully suppressed at mu ≤ -0.02.
                    if _ricci_val > 0.0 and _ricci_regime == "mean_reversion":
                        _theta_mu = (
                            float(_manifold_state.theta[0])
                            if _manifold_state.theta is not None
                            else 0.0
                        )
                        if _theta_mu < 0.0:
                            _scale = max(0.0, 1.0 + _theta_mu / 0.02)
                            _ricci_val *= _scale
                            logger.info(
                                "V75: ricci dampened (mean_reversion in downtrend "
                                "theta_mu=%.4f scale=%.2f → ricci=%.3f)",
                                _theta_mu,
                                _scale,
                                _ricci_val,
                            )
                    logger.debug(
                        "MarketManifold: ricci=%.3f regime=%s signal=%.3f conf=%.2f",
                        _manifold_state.ricci,
                        _ricci_regime,
                        _ricci_val,
                        _manifold_state.confidence,
                    )
            except Exception as _exc:
                logger.warning("MarketManifold compute error: %s", _exc)

        # Ollivier-Ricci curvature on the asset correlation network (basket-level signal)
        _orc_val: float = 0.0
        if self._orc is not None:
            try:
                _orc_state = self._orc.update(market_data)
                if _orc_state is not None and _orc_state.confidence >= 0.3:
                    _orc_val = _orc_state.signal
                    logger.debug(
                        "ORC: mean_kappa=%.3f regime=%s signal=%.3f n_edges=%d conf=%.2f",
                        _orc_state.mean_curvature,
                        _orc_state.regime,
                        _orc_val,
                        _orc_state.n_edges,
                        _orc_state.confidence,
                    )
            except Exception as _exc:
                logger.warning("ORC compute error: %s", _exc)

        # Expose geometry state to strategy.py for Ricci-weighted sizing, ORC stress
        # gating, and geodesic crash proximity modulation.  Injected as _geometry_*
        # top-level keys so strategy._construct_portfolio can read them alongside
        # regime metadata without needing ticker context.
        _manifold_state_ref = locals().get("_manifold_state")
        if _manifold_state_ref is not None:
            with contextlib.suppress(Exception):
                signals["_geometry_ricci_raw"] = round(float(_manifold_state_ref.ricci), 4)
                signals["_geometry_geo_dist_crash"] = round(
                    float(_manifold_state_ref.geo_dist_crash), 4
                )
                signals["_geometry_geo_dist_rally"] = round(
                    float(_manifold_state_ref.geo_dist_rally), 4
                )
                signals["_geometry_manifold_regime"] = _manifold_state_ref.regime
        _orc_state_ref = locals().get("_orc_state")
        if _orc_state_ref is not None and _orc_state_ref.confidence >= 0.3:
            with contextlib.suppress(Exception):
                signals["_geometry_orc_kappa"] = round(float(_orc_state_ref.mean_curvature), 4)
                signals["_geometry_orc_regime"] = _orc_state_ref.regime

        # V187 dynamic graph: push latest close per symbol then compute graph
        # features once for the whole basket. The same dict is then injected
        # into each ticker's signals_dict inside the loop below.
        _dg_features: dict[str, float] = {}
        if self._dynamic_graph is not None:
            try:
                for _dg_ticker, _dg_data in market_data.items():
                    if not _dg_data or not isinstance(_dg_data, dict):
                        continue
                    _dg_closes = _dg_data.get("adjclose") or _dg_data.get("close") or []
                    if _dg_closes:
                        try:
                            self._dynamic_graph.push_close(_dg_ticker, float(_dg_closes[-1]))
                        except (TypeError, ValueError, IndexError):
                            continue
                _dg_features = self._dynamic_graph.compute() or {}
            except Exception as _dg_exc:
                logger.debug("dynamic_graph compute error: %s", _dg_exc)

        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < self._sma_long + 1:
                continue

            ts: dict[str, Any] = {}

            # SMA crossover (always active)
            # Proportional: (short - long) / long, clipped to [-1, 1].
            # This avoids the hard binary ±1 that systematically inflates composite
            # magnitude relative to other signal types (root cause of chronic
            # adversarial-gate divergence).
            sma_short = _safe_mean(prices, self._sma_short)  # type: ignore[arg-type]
            sma_long = _safe_mean(prices, self._sma_long)  # type: ignore[arg-type]
            if sma_short is not None and sma_long is not None and sma_long != 0:
                raw_ratio = (sma_short - sma_long) / sma_long
                # Scale so a 2% deviation → signal ≈ 0.5; clip to [-1, 1]
                ts["sma_crossover"] = max(-1.0, min(1.0, raw_ratio * 10.0))
                ts["sma_short"] = sma_short
                ts["sma_long"] = sma_long

            # RSI
            if self._use_rsi:
                rsi = self._compute_rsi(prices, self._rsi_period)
                if rsi is not None:
                    ts["rsi"] = rsi
                    # Continuous: (50 - rsi) / 50 maps RSI=0 → +1, RSI=100 → -1,
                    # RSI=50 → 0.  More proportional than a hard ±1 threshold.
                    ts["rsi_signal"] = max(-1.0, min(1.0, (50.0 - rsi) / 50.0))

            # MACD
            if self._use_macd:
                macd_line, sig_line = self._compute_macd(prices)
                if macd_line is not None and sig_line is not None:
                    ts["macd"] = macd_line
                    ts["macd_signal_line"] = sig_line
                    # Proportional: histogram normalised by price (×100 → ~% scale),
                    # then scaled so a 0.1% histogram → signal ≈ 0.5.  Clip ±1.
                    price_ref = prices[-1] if prices else 1.0
                    if price_ref != 0:
                        histogram = macd_line - sig_line
                        ts["macd_crossover"] = max(-1.0, min(1.0, histogram / price_ref * 500.0))
                    else:
                        ts["macd_crossover"] = 1.0 if macd_line > sig_line else -1.0

            # Bollinger Bands
            if self._use_bb:
                bb = self._compute_bollinger_bands(prices, self._bb_period, self._bb_std)
                if bb:
                    ts["bb_upper"] = bb["upper"]
                    ts["bb_lower"] = bb["lower"]
                    ts["bb_mid"] = bb["mid"]
                    price = prices[-1]
                    band_half = bb["upper"] - bb["mid"]
                    if band_half > 0:
                        # Continuous: how far price deviates from mid as fraction of half-band.
                        # price at upper band → -1 (overbought); at lower band → +1 (oversold).
                        ts["bb_signal"] = max(-1.0, min(1.0, (bb["mid"] - price) / band_half))
                    else:
                        ts["bb_signal"] = 0.0

            # Z-score momentum
            if self._use_zscore:
                zscore = self._compute_zscore_returns(prices, self._zscore_period)
                if zscore is not None:
                    ts["zscore"] = zscore
                    ts["zscore_signal"] = max(-1.0, min(1.0, zscore / 2.0))

            # Volume z-score (crypto-specific: volume spike = sentiment proxy)
            if self._use_volume_zscore:
                vols = self._clean_prices(data.get("volume", []))
                vol_z = self._compute_zscore_series(vols, 20)
                if vol_z is not None:
                    ts["volume_zscore"] = vol_z
                    # Volume z-score as a standalone mean-reversion signal:
                    # unusually high volume → price likely to revert → bearish bias
                    # unusually low volume → low conviction move → mild bullish bias
                    # NOT tied to SMA direction; that coupling amplified any existing
                    # directional bias (in a down-SMA market, high vol became doubly
                    # bearish, in an up-SMA market, low vol became doubly bullish).
                    ts["volume_signal"] = max(-1.0, min(1.0, -vol_z / 2.0))

            # V173: VWAP deviation signal (price vs volume-weighted avg).
            if getattr(self._features, "vwap_signal_enabled", False):
                try:
                    from omega.nodes.victoria.signals.vwap_deviation import compute_vwap_deviation
                    _vols = self._clean_prices(data.get("volume", []))
                    _vwap_v = compute_vwap_deviation(prices, _vols, window=60)
                    if _vwap_v != 0.0:
                        ts["vwap_signal"] = _vwap_v
                except Exception as _vwap_exc:
                    logger.debug("vwap_signal %s: %s", ticker, _vwap_exc)

            # V173: RSI divergence signal (price/RSI divergence as reversal indicator).
            if getattr(self._features, "rsi_divergence_enabled", False):
                try:
                    from omega.nodes.victoria.signals.rsi_divergence import compute_divergence
                    _rsi_div = compute_divergence(prices, lookback=20, period=14)
                    if _rsi_div != 0.0:
                        ts["rsi_divergence_signal"] = _rsi_div
                except Exception as _rd_exc:
                    logger.debug("rsi_divergence %s: %s", ticker, _rd_exc)

            # V157: breakout detection — Donchian channel breakout signal
            if (
                _HAS_TREND_SIGNALS
                and self._features
                and getattr(self._features, "breakout_signal_enabled", False)
            ):
                try:
                    _bk_window = int(getattr(self._features, "breakout_window", 20))
                    _bk = _breakout_mod.compute(prices, window=_bk_window)
                    ts.update(_bk)
                except Exception as _bk_exc:
                    logger.debug("breakout %s: %s", ticker, _bk_exc)

            # V157: trend strength — ADX-based trend confirmation
            if (
                _HAS_TREND_SIGNALS
                and self._features
                and getattr(self._features, "trend_strength_signal_enabled", False)
            ):
                try:
                    _adx_period = int(getattr(self._features, "trend_strength_period", 14))
                    _adx_min = float(getattr(self._features, "trend_strength_adx_min", 20.0))
                    _adx = _trend_strength_mod.compute(prices, period=_adx_period, adx_min=_adx_min)
                    ts.update(_adx)
                except Exception as _adx_exc:
                    logger.debug("trend_strength %s: %s", ticker, _adx_exc)

            # V157: multi-timeframe alignment — short/long momentum agreement
            if (
                _HAS_TREND_SIGNALS
                and self._features
                and getattr(self._features, "multi_timeframe_alignment", False)
            ):
                try:
                    _mtf_short = int(getattr(self._features, "mtf_short_window", 4))
                    _mtf_long = int(getattr(self._features, "mtf_long_window", 24))
                    _mtf = _mtf_mod.compute(prices, short_window=_mtf_short, long_window=_mtf_long)
                    ts.update(_mtf)
                except Exception as _mtf_exc:
                    logger.debug("multi_timeframe %s: %s", ticker, _mtf_exc)

            # Funding rate signal
            if self._funding_signal is not None:
                try:
                    fr_signal = self._funding_signal.compute(ticker)
                    if fr_signal != 0.0:
                        ts["funding_rate_signal"] = fr_signal
                    # V166: surface BTC funding at top level for metrics observability
                    if ticker == "BTCUSDT":
                        signals["_funding_rate_btc"] = float(fr_signal)
                except Exception:
                    pass

            # Cross-asset market-level signals (pre-computed above, applied to every ticker)
            # V166: gated by *_in_composite feature flags. Values are still surfaced
            # at signals["_xxx_val"] for metrics; the flags control whether they
            # enter the per-ticker composite. Defaults match v161_live behaviour
            # (fear_greed only) even when FRED_API_KEY/yfinance are now present.
            _f = self._features
            if _fear_greed_val != 0.0 and getattr(_f, "fear_greed_in_composite", True):
                ts["fear_greed_signal"] = _fear_greed_val
            if _dxy_val != 0.0 and getattr(_f, "dxy_signal_in_composite", False):
                ts["dxy_signal"] = _dxy_val
            if _vix_val != 0.0 and getattr(_f, "vix_signal_in_composite", False):
                ts["vix_signal"] = _vix_val
            if _yield_curve_val != 0.0 and getattr(_f, "yield_curve_in_composite", False):
                ts["yield_curve_signal"] = _yield_curve_val
            if _spy_val != 0.0 and getattr(_f, "spy_signal_in_composite", False):
                ts["spy_signal"] = _spy_val
            for _geo_k, _geo_v in _geo_signals.items():
                if _geo_v != 0.0:
                    ts[_geo_k] = _geo_v
            if _ricci_val != 0.0:
                ts["ricci_curvature_signal"] = _ricci_val
            if _orc_val != 0.0:
                ts["ollivier_ricci_signal"] = _orc_val

            # Volatility regime (annualised vs long-run average)
            if self._use_vol_regime:
                regime, recent_vol, long_vol = self._compute_vol_regime(prices)
                ts["vol_regime"] = regime  # "high" | "normal" | "low"
                ts["recent_vol_ann"] = recent_vol
                ts["long_vol_ann"] = long_vol
                # Vol regime signal: only fire in low-vol (mean-reversion opportunity).
                # High vol does NOT produce a directional signal — it's a risk
                # management cue handled by the sit-out filter, not a bearish signal.
                # Adding -0.2 for every high-vol period created a structural bearish
                # tilt since crypto is almost always in "high vol".
                if regime == "low":
                    ts["vol_regime_signal"] = 0.1
                # "high" and "normal": no directional signal (sit-out handles risk)

            # V103: ws_microstructure — inject real-time microstructure signals per ticker
            if self._ws_feeds is not None:
                try:
                    _ms = self._ws_feeds.get_microstructure(ticker)
                    # Only inject non-zero signals (WS may not have data yet)
                    for _ms_key, _ms_val in _ms.items():
                        if _ms_val != 0.0:
                            ts[_ms_key] = _ms_val
                except Exception as _ms_exc:
                    logger.debug("ws_microstructure %s: %s", ticker, _ms_exc)

            # V185 VPIN signal: enrich raw vpin with zscore + spike features.
            # Uses breakout_signal as the directional hint so a spike inherits
            # the direction the trend-following sub-strategies already see.
            if self._vpin_signal is not None:
                _raw_vpin = float(ts.get("vpin", 0.0))
                if _raw_vpin > 0.0:
                    try:
                        _vpin_feats = self._vpin_signal.compute(
                            symbol=ticker,
                            vpin_value=_raw_vpin,
                            directional_hint=float(ts.get("breakout_signal", 0.0)),
                        )
                        for _k, _v in _vpin_feats.items():
                            if _v != 0.0:
                                ts[_k] = _v
                    except Exception as _vpin_exc:
                        logger.debug("vpin_signal %s: %s", ticker, _vpin_exc)

            # V185 Kyle's Lambda: market-impact slope of price on signed flow.
            if self._kyles_lambda is not None:
                try:
                    _kl = self._kyles_lambda.compute(ticker)
                    for _k, _v in _kl.items():
                        if _v != 0.0:
                            ts[_k] = _v
                except Exception as _kl_exc:
                    logger.debug("kyles_lambda %s: %s", ticker, _kl_exc)

            # V185 LOB features: multi-level OFI, arrival-rate z, adverse selection.
            if self._lob_features is not None:
                try:
                    _lf = self._lob_features.compute(ticker)
                    for _k, _v in _lf.items():
                        if _v != 0.0:
                            ts[_k] = _v
                except Exception as _lf_exc:
                    logger.debug("lob_features %s: %s", ticker, _lf_exc)

            # V187 dynamic graph features: same dict on every ticker (basket-level).
            for _dg_k, _dg_v in _dg_features.items():
                if _dg_v != 0.0:
                    ts[_dg_k] = _dg_v

            # V191 range-trading: feed OHLC bars and emit per-ticker features.
            if self._range_trading is not None:
                try:
                    _highs = data.get("high") or []
                    _lows = data.get("low") or []
                    _closes_ohlc = data.get("close") or data.get("adjclose") or []
                    if _highs and _lows and _closes_ohlc:
                        self._range_trading.push_bar(
                            ticker,
                            float(_highs[-1]),
                            float(_lows[-1]),
                            float(_closes_ohlc[-1]),
                        )
                    _rt = self._range_trading.compute(ticker)
                    for _k, _v in _rt.items():
                        if _v != 0.0 or _k == "bb_position":
                            ts[_k] = _v
                except Exception as _rt_exc:
                    logger.debug("range_trading %s: %s", ticker, _rt_exc)

            # V191 funding carry: depends on existing funding_rate_signal value.
            if self._funding_carry is not None:
                try:
                    _fc = self._funding_carry.compute(ts)
                    for _k, _v in _fc.items():
                        if _v != 0.0:
                            ts[_k] = _v
                except Exception as _fc_exc:
                    logger.debug("funding_carry %s: %s", ticker, _fc_exc)

            # V166: cross-exchange divergence — Binance WS price vs REST close.
            # Compute always when feeds available so the value can be surfaced
            # for metrics; only inject into composite when the flag is on.
            if self._ws_feeds is not None and getattr(
                self._features, "cross_exchange_divergence_enabled", False
            ):
                try:
                    from omega.nodes.victoria.signals.cross_exchange_divergence import (
                        compute_divergence,
                    )
                    _ws_p = self._ws_feeds.get_latest_price(ticker)
                    _rest_p = None
                    _prices = data.get("close") or data.get("adjclose")
                    if isinstance(_prices, list) and _prices:
                        try:
                            _rest_p = float(_prices[-1])
                        except (TypeError, ValueError):
                            _rest_p = None
                    _thr = float(getattr(self._features, "cross_exchange_divergence_threshold_pct", 0.001))
                    _ced = compute_divergence(_ws_p, _rest_p, _thr)
                    if _ced != 0.0 and getattr(self._features, "cross_exchange_divergence_in_composite", False):
                        ts["cross_exchange_divergence_signal"] = _ced
                    # Always surface for observability
                    ts["_cross_exchange_divergence"] = _ced
                except Exception as _ced_exc:
                    logger.debug("cross_exchange_divergence %s: %s", ticker, _ced_exc)

            # V115 Phase 1: whale_prints — sub-second informed-flow WS signals
            if (
                self._ws_feeds is not None
                and self._features
                and getattr(self._features, "whale_prints", False)
            ):
                try:
                    _wp = self._ws_feeds.get_whale_signals(ticker)
                    for _wp_key, _wp_val in _wp.items():
                        if _wp_val != 0.0:
                            ts[_wp_key] = _wp_val
                except Exception as _wp_exc:
                    logger.debug("whale_prints %s: %s", ticker, _wp_exc)

            # V115 Phase 2: whale_flow — DefiLlama + OKX smart-money signals
            if self._whale_flow is not None:
                try:
                    _wf = self._whale_flow.compute_all(ticker)
                    for _wf_key, _wf_val in _wf.items():
                        if _wf_val != 0.0:
                            ts[_wf_key] = _wf_val
                except Exception as _wf_exc:
                    logger.debug("whale_flow %s: %s", ticker, _wf_exc)

            # V115 Phase 2: funding_velocity — derivative of funding rate over 3 readings
            if (
                self._funding_signal is not None
                and self._features
                and getattr(self._features, "funding_velocity", False)
            ):
                try:
                    _fv = self._funding_signal.compute_velocity(ticker)
                    if _fv != 0.0:
                        ts["funding_rate_velocity"] = _fv
                except Exception as _fv_exc:
                    logger.debug("funding_velocity %s: %s", ticker, _fv_exc)

            # V103: temporal_memory — inject 8 temporal features from signal history
            if self._signal_memory is not None:
                try:
                    self._signal_memory.update(ticker, ts)
                    _manifold_regime_for_mem = locals().get("_ricci_regime", "transitional")
                    _temporal = self._signal_memory.get_temporal_features(
                        ticker, manifold_regime=_manifold_regime_for_mem
                    )
                    ts.update(_temporal)
                except Exception as _tm_exc:
                    logger.debug("temporal_memory %s: %s", ticker, _tm_exc)

            # IC-weighted composite — falls back to equal-weight when IC data is sparse.
            # V103: adaptive_combiner replaces _ic_weighted_composite when ON.
            # V172_pruned: drop named signals entirely from the per-ticker
            # signal dict before composite computation. Calibrated ICs say
            # sma_crossover is a -0.27 anti-predictor on 11k pairs; pruning is
            # simpler and more robust than weight-flipping (which keeps
            # regressing across V165-V172 attempts).
            _excluded_in_basket = set(getattr(self._features, "excluded_signals", None) or [])
            for _ek in list(_excluded_in_basket):
                if _ek in ts:
                    del ts[_ek]

            # Uses per-signal Information Coefficient from SignalDecayDetector to
            # up-weight historically predictive signals and exclude anti-predictive ones.
            directional = [
                v for k, v in ts.items() if k.endswith("_signal") or k == "sma_crossover"
            ]
            if directional:
                if self._adaptive_combiner is not None:
                    # V103: adaptive IC combiner with signal flipping
                    ic_composite, ic_method = self._adaptive_combiner.compute_composite(
                        ts, self._decay_detector
                    )
                else:
                    ic_composite, ic_method = _ic_weighted_composite(ts, self._decay_detector)
                ts["composite"] = ic_composite
                ts["composite_method"] = ic_method

            # ML combiner: replace IC-weighted composite when trained (ML wins)
            if self._combiner is not None:
                ml_score = self._combiner.predict(ts)
                if ml_score is not None:
                    ts["composite"] = ml_score
                    ts["composite_method"] = "ml"

            ts["price"] = prices[-1] if prices else None
            ts["ticker"] = ticker

            # 1-day return
            if len(prices) >= 2 and prices[-2] != 0:
                ts["return_1d"] = (prices[-1] - prices[-2]) / prices[-2]

            # V106: trade_reinforcement — snapshot signals and apply EMA weight adjustments.
            # Snapshot is stored keyed by ticker so TradeReinforcer can retrieve entry signals
            # at trade close time (called from orchestrator_v2).
            # Weight adjustments are applied BEFORE composite so the IC/ML combiner sees them.
            # _reinf_weights injected into ts so strategy.py + activation tracer can read them.
            # V112: postmortem_signal_filter — zero out signals proven consistently wrong
            # across 124+ trades in V107-V110. Zeroing happens before snapshot so the
            # reinforcer and composite both see the cleansed signal values.
            if self._features and getattr(self._features, "postmortem_signal_filter", False):
                _dead_signals = {
                    # V107-V110 cross-version analysis (124+ trades): accuracy 37-44%
                    "sma_long",
                    "sma_short",
                    "price",
                    "return_1d",
                    "sma_crossover",
                    "fear_greed_signal",
                    "liquidation_proximity",
                    # V115 postmortem (44 trades): flip confirmed in V116 cross-version
                    "vpin",  # 37.5% → 51.4% after flip (V116 confirmed)
                    "ricci_curvature_signal",  # 38.1% → 56.8% after flip (V116 confirmed)
                    "trade_flow_direction",  # 39.5% → 63.2% after flip (V116 confirmed)
                    # NOTE: whale_print removed — V122 fix: was 61% positive-biased in V116
                    # (n=28, below 50-trade policy). Negating it created systematic short push.
                    # VPIN is bounded [0,1]: negated value is always in [-1,0] (permanently
                    # bearish regardless of market). Keep vpin flipped — its raw value was
                    # always negative (pos%=0%) so the flip just makes the sign consistent.
                    # NOTE: momentum_derivative, volume_profile, funding_derivative,
                    # momentum_persistence were NOT added — they were >55% across 130 trades
                    # (V114-V116). V117-V118 had only 14-26 trades — below minimum evidence
                    # threshold of 50 trades required to flip a signal.
                }
                for _dead in _dead_signals:
                    if _dead in ts and isinstance(ts[_dead], (int, float)):
                        ts[_dead] = -float(ts[_dead])  # flip: anti-predictive → predictive

            if self._reinforcer is not None:
                self._reinforcer.snapshot(ticker, ts)
                _reinf_adjs = self._reinforcer.get_weight_adjustments()
                ts["_reinf_weights"] = dict(_reinf_adjs)  # empty until 5+ trades
                if _reinf_adjs:
                    for _sig_k, _mult in _reinf_adjs.items():
                        if _sig_k in ts and isinstance(ts[_sig_k], (int, float)):
                            ts[_sig_k] = float(ts[_sig_k]) * _mult
                    # Recompute composite with adjusted signal values
                    _adj_directional = [
                        v for k, v in ts.items() if k.endswith("_signal") or k == "sma_crossover"
                    ]
                    if _adj_directional and self._adaptive_combiner is not None:
                        _adj_ic, _adj_method = self._adaptive_combiner.compute_composite(
                            ts, self._decay_detector
                        )
                        ts["composite"] = _adj_ic
                        ts["composite_method"] = _adj_method + "+reinforced"
                    elif _adj_directional and self._decay_detector is not None:
                        _adj_ic, _adj_method = _ic_weighted_composite(ts, self._decay_detector)
                        ts["composite"] = _adj_ic
                        ts["composite_method"] = _adj_method + "+reinforced"

            signals[ticker] = ts

        # BTC beta for all assets (requires BTC in market_data)
        if self._use_btc_beta and "BTCUSDT" in market_data and market_data["BTCUSDT"]:
            btc_prices = self._clean_prices(
                market_data["BTCUSDT"].get("adjclose") or market_data["BTCUSDT"].get("close", [])
            )
            btc_rets = self._compute_returns(btc_prices, 20)
            for ticker, ts in signals.items():
                if ticker == "BTCUSDT":
                    ts["btc_beta"] = 1.0
                    continue
                data = market_data.get(ticker)
                if not data:
                    continue
                asset_prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
                asset_rets = self._compute_returns(asset_prices, 20)
                if btc_rets and asset_rets:
                    beta = self._compute_beta(asset_rets, btc_rets)
                    ts["btc_beta"] = beta
                    # High beta assets amplify BTC signal
                    btc_sig = signals.get("BTCUSDT", {}).get("composite", 0.0)
                    if btc_sig != 0 and beta > 0:
                        ts["btc_beta_signal"] = min(1.0, max(-1.0, btc_sig * min(beta, 2.0) / 2.0))
                        # Recompute composite with BTC beta signal (IC-weighted)
                        dir_vals = [
                            v
                            for k, v in ts.items()
                            if k.endswith("_signal") or k == "sma_crossover"
                        ]
                        if dir_vals:
                            btc_ic_composite, btc_ic_method = _ic_weighted_composite(
                                ts, self._decay_detector
                            )
                            ts["composite"] = btc_ic_composite
                            ts["composite_method"] = btc_ic_method

        # Cross-sectional demeaning: subtract the basket mean from every composite so
        # each ticker's score reflects its RELATIVE position within the basket, not the
        # absolute market direction.
        #
        # Why this matters: when MACD or SMA are structurally negative for all tickers
        # (e.g. a sustained bear trend), the untreated mean composite can be -0.3 across
        # all 10 assets.  Every ticker then gets SELL conviction and the system produces
        # 0 longs / N shorts — it can never buy relative outperformers.  Demeaning shifts
        # the best performer to composite > 0 (long candidate) and the worst to composite
        # < 0 (short candidate), making the strategy market-neutral by construction and
        # guaranteeing directional balance across any basket of ≥ 3 tickers.
        _cs_raw = [
            (t, s)
            for t, s in signals.items()
            if isinstance(s, dict) and "composite" in s and not t.startswith("_")
        ]
        if len(_cs_raw) >= 3:
            _cs_vals = [s["composite"] for _, s in _cs_raw]
            _basket_mean = sum(_cs_vals) / len(_cs_vals)
            for _t, _ts in _cs_raw:
                _ts["_raw_composite"] = _ts["composite"]  # preserve pre-demean value
                _ts["_basket_mean"] = _basket_mean
                _ts["composite"] = _ts["composite"] - _basket_mean
            _demeaned = [s["composite"] for _, s in _cs_raw]
            logger.debug(
                "cross-sectional demean: basket_mean=%.3f → demeaned range=[%.3f, %.3f]",
                _basket_mean,
                min(_demeaned),
                max(_demeaned),
            )
            # Per-ticker demean breakdown (info level so it shows in training logs)
            for _t, _ts in sorted(_cs_raw, key=lambda x: -abs(x[1]["composite"])):
                logger.info(
                    "demean[%s]: raw=%.4f → demean=%.4f (basket_mean=%.3f)",
                    _t,
                    _ts["_raw_composite"],
                    _ts["composite"],
                    _basket_mean,
                )

        # Log composite spread for monitoring
        _composites = [
            (t, s.get("composite", 0.0))
            for t, s in signals.items()
            if isinstance(s, dict) and s.get("composite") is not None and not t.startswith("_")
        ]
        if len(_composites) >= 3:
            _vals = [v for _, v in _composites]
            _mu = sum(_vals) / len(_vals)
            _std = math.sqrt(sum((v - _mu) ** 2 for v in _vals) / len(_vals))
            logger.debug(
                "composite spread: n=%d mean=%.3f std=%.3f min=%.3f max=%.3f",
                len(_vals),
                _mu,
                _std,
                min(_vals),
                max(_vals),
            )

        # V152: Wasserstein regime distance — W₁ to return distribution archetypes
        # Uses BTC log-returns as market-level input; outputs _w2_crisis/_w2_normal/_w2_trend.
        if self._wasserstein_regime_sig is not None:
            try:
                _btc_data = market_data.get("BTCUSDT") or {}
                _btc_prices = self._clean_prices(
                    _btc_data.get("adjclose") or _btc_data.get("close", [])
                )
                if len(_btc_prices) >= 10:
                    import math as _m
                    _btc_rets = [
                        _m.log(_btc_prices[i] / _btc_prices[i - 1])
                        for i in range(1, len(_btc_prices))
                        if _btc_prices[i - 1] > 0 and _btc_prices[i] > 0
                    ]
                    self._wasserstein_regime_sig.update_returns(_btc_rets)
                    _w_sv = self._wasserstein_regime_sig.compute()
                    signals["_w2_crisis"] = _w_sv.raw.get("w2_crisis", 0.0)
                    signals["_w2_normal"] = _w_sv.raw.get("w2_normal", 0.0)
                    signals["_w2_trend"] = _w_sv.raw.get("w2_trend", 0.0)
                    signals["_w2_closest_regime"] = _w_sv.regime_tag
                    logger.debug(
                        "wasserstein_regime: closest=%s w2_crisis=%.5f w2_normal=%.5f w2_trend=%.5f",
                        _w_sv.regime_tag,
                        _w_sv.raw.get("w2_crisis", 0.0),
                        _w_sv.raw.get("w2_normal", 0.0),
                        _w_sv.raw.get("w2_trend", 0.0),
                    )
            except Exception as _w2_exc:
                logger.debug("WassersteinRegimeSignal compute error: %s", _w2_exc)

        # V152: TDA crash-prediction signal — persistent homology on BTC returns.
        # Outputs _tda_fragmentation (< 0 = crash precursor topology).
        if self._tda_signal_inst is not None:
            try:
                _btc_data = market_data.get("BTCUSDT") or {}
                _btc_prices = self._clean_prices(
                    _btc_data.get("adjclose") or _btc_data.get("close", [])
                )
                if len(_btc_prices) >= 10:
                    import math as _m2
                    _btc_rets = [
                        _m2.log(_btc_prices[i] / _btc_prices[i - 1])
                        for i in range(1, len(_btc_prices))
                        if _btc_prices[i - 1] > 0 and _btc_prices[i] > 0
                    ]
                    self._tda_signal_inst.update_returns(_btc_rets)
                    _tda_sv = self._tda_signal_inst.compute()
                    signals["_tda_fragmentation"] = _tda_sv.value
                    signals["_tda_regime"] = _tda_sv.regime_tag
                    signals["_tda_betti0"] = _tda_sv.raw.get("betti0", 0)
                    signals["_tda_betti1"] = _tda_sv.raw.get("betti1", 0)
                    signals["_tda_pers_entropy"] = _tda_sv.raw.get("persistence_entropy", 0.0)
                    logger.debug(
                        "tda_signal: regime=%s value=%.3f β0=%d β1=%d pers_entropy=%.4f",
                        _tda_sv.regime_tag,
                        _tda_sv.value,
                        _tda_sv.raw.get("betti0", 0),
                        _tda_sv.raw.get("betti1", 0),
                        _tda_sv.raw.get("persistence_entropy", 0.0),
                    )
            except Exception as _tda_exc:
                logger.debug("TDASignal compute error: %s", _tda_exc)

        # V153: Regime transition signal — high-alpha moments when the regime label changes.
        # Transitions are where the market hasn't yet priced the new regime; the signal
        # value encodes direction and magnitude of the regime shift.
        if self._features and getattr(self._features, "regime_transition_signal", False):
            _curr_regime = str(signals.get("_regime", "default"))
            _prev = self._prev_regime_for_transition
            _transition_value = 0.0
            if _prev is not None and _prev != _curr_regime:
                _transition_map = {
                    ("normal", "trending"):  0.8,   # confirmed bull breakout — strong long
                    ("default", "trending"): 0.6,
                    ("high_vol", "trending"): 0.5,
                    ("high_vol", "normal"):   0.4,   # vol compression → recovery
                    ("crisis", "normal"):     0.3,   # recovery — moderate long
                    ("crisis", "high_vol"):   0.1,
                    ("trending", "normal"):  -0.2,   # trend fade — mild bearish
                    ("normal", "high_vol"):  -0.5,   # vol spike — risk-off
                    ("normal", "crisis"):    -0.8,   # regime breakdown — strong short/exit
                    ("trending", "high_vol"): -0.6,  # trend disruption
                    ("trending", "crisis"):  -0.9,   # trend collapse — strongest bearish
                    ("high_vol", "crisis"):  -0.7,   # vol spike into bear
                }
                _transition_value = _transition_map.get((_prev, _curr_regime), 0.0)
                if _transition_value != 0.0:
                    logger.info(
                        "Regime transition %s→%s value=%.1f",
                        _prev, _curr_regime, _transition_value,
                    )
            self._prev_regime_for_transition = _curr_regime
            signals["_regime_transition"] = _transition_value
            signals["_regime_transition_from"] = _prev or ""

        # V158: basket-level breakout summary — mean breakout_signal across all
        # tickers. Injected as _basket_breakout so strategy_selector can use
        # actual price momentum (not just regime labels) for TREND mode detection.
        _bk_vals = [
            float(ts.get("breakout_signal", 0.0))
            for ts in signals.values()
            if isinstance(ts, dict) and "breakout_signal" in ts
        ]
        if _bk_vals:
            signals["_basket_breakout"] = round(sum(_bk_vals) / len(_bk_vals), 4)

        # V158: basket-level MTF alignment — fraction of tickers with aligned timeframes.
        _mtf_aligns = [
            float(ts.get("timeframe_alignment", 0.0))
            for ts in signals.values()
            if isinstance(ts, dict) and "timeframe_alignment" in ts
        ]
        if _mtf_aligns:
            signals["_basket_mtf_alignment"] = round(sum(_mtf_aligns) / len(_mtf_aligns), 4)

        # V162: basket-level volatility shock detector.  Stateless; hysteresis and
        # size/stop adjustments live in ResilienceState.  Keys injected:
        #   vol_shock_max_z, vol_shock_ratio, vol_shock_flag, vol_shock_worst_ticker
        if (
            _HAS_VOL_SHOCK
            and self._features
            and getattr(self._features, "vol_shock_detector_enabled", False)
        ):
            try:
                _prices_by_ticker: dict[str, list[float]] = {}
                for _tkr, _data in market_data.items():
                    if not isinstance(_data, dict):
                        continue
                    _p = self._clean_prices(_data.get("adjclose") or _data.get("close", []))
                    if _p:
                        _prices_by_ticker[_tkr] = _p
                _vs_z = float(getattr(self._features, "vol_shock_z_threshold", 3.0))
                _vs = _vol_shock_mod.compute(_prices_by_ticker, shock_z=_vs_z)
                signals.update(_vs)
            except Exception as _vs_exc:
                logger.debug("vol_shock basket: %s", _vs_exc)

        return signals

    def _compute_momentum_signals(self, market_data: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < 6:
                continue
            momentum = (prices[-1] - prices[-6]) / prices[-6] if prices[-6] != 0 else 0.0
            signals[ticker] = {
                "momentum_5d": momentum,
                "signal": 1.0 if momentum > 0 else -1.0,
                "price": prices[-1],
            }
        return signals

    def _compute_mean_reversion_signals(self, market_data: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < self._zscore_period + 1:
                continue
            zscore = self._compute_zscore_returns(prices, self._zscore_period)
            if zscore is not None:
                signals[ticker] = {
                    "zscore": zscore,
                    "signal": -1.0 if zscore > 2.0 else (1.0 if zscore < -2.0 else 0.0),
                    "price": prices[-1],
                }
        return signals

    # ------------------------------------------------------------------ indicators

    def _compute_rsi(self, prices: list[float], period: int = 14) -> float | None:
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(0.0, d) for d in deltas[-period:]]
        losses = [max(0.0, -d) for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _compute_ema(self, prices: list[float], period: int) -> list[float]:
        if not prices:
            return []
        k = 2.0 / (period + 1)
        ema = [prices[0]]
        for price in prices[1:]:
            ema.append(price * k + ema[-1] * (1 - k))
        return ema

    def _compute_macd(self, prices: list[float]) -> tuple[float | None, float | None]:
        if len(prices) < self._macd_slow + self._macd_signal_period:
            return None, None
        ema_fast = self._compute_ema(prices, self._macd_fast)
        ema_slow = self._compute_ema(prices, self._macd_slow)
        # align by taking the slow EMA's starting index
        offset = self._macd_slow - 1
        macd_series = [f - s for f, s in zip(ema_fast[offset:], ema_slow[offset:], strict=False)]
        if len(macd_series) < self._macd_signal_period:
            return None, None
        signal_series = self._compute_ema(macd_series, self._macd_signal_period)
        return macd_series[-1], signal_series[-1]

    def _compute_bollinger_bands(
        self, prices: list[float], period: int = 20, num_std: float = 2.0
    ) -> dict[str, float] | None:
        if len(prices) < period:
            return None
        recent = prices[-period:]
        mean = sum(recent) / period
        variance = sum((x - mean) ** 2 for x in recent) / (period - 1)
        std = math.sqrt(variance)
        return {
            "upper": mean + num_std * std,
            "mid": mean,
            "lower": mean - num_std * std,
        }

    def _compute_zscore_returns(self, prices: list[float], period: int = 20) -> float | None:
        if len(prices) < period + 1:
            return None
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] != 0
        ]
        if len(returns) < period:
            return None
        recent = returns[-period:]
        mean = sum(recent) / period
        variance = sum((x - mean) ** 2 for x in recent) / max(1, period - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        return (returns[-1] - mean) / std

    def _compute_zscore_series(self, values: list[float], period: int) -> float | None:
        """Z-score of the last value relative to the recent period."""
        if len(values) < period + 1:
            return None
        recent = [v for v in values[-period:] if v is not None]
        if len(recent) < 2:
            return None
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / max(1, len(recent) - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        return (recent[-1] - mean) / std

    def _compute_returns(self, prices: list[float], period: int = 20) -> list[float]:
        """Compute recent daily returns."""
        if len(prices) < 2:
            return []
        rets = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(max(1, len(prices) - period), len(prices))
            if prices[i - 1] != 0
        ]
        return rets

    def _compute_beta(self, asset_rets: list[float], btc_rets: list[float]) -> float:
        """OLS beta of asset returns against BTC returns."""
        n = min(len(asset_rets), len(btc_rets))
        if n < 5:
            return 1.0
        x = btc_rets[-n:]
        y = asset_rets[-n:]
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        var_x = sum((v - mean_x) ** 2 for v in x)
        return cov / var_x if var_x > 0 else 1.0

    def _compute_vol_regime(
        self, prices: list[float], short_window: int = 10, long_window: int = 60
    ) -> tuple[str, float, float]:
        """Detect volatility regime: 'high', 'normal', or 'low'."""
        if len(prices) < long_window + 1:
            return "normal", 0.0, 0.0

        rets = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] != 0
        ]

        def annualised_vol(ret_window: list[float]) -> float:
            if len(ret_window) < 2:
                return 0.0
            mean = sum(ret_window) / len(ret_window)
            variance = sum((r - mean) ** 2 for r in ret_window) / (len(ret_window) - 1)
            return math.sqrt(variance) * math.sqrt(365)

        recent_vol = annualised_vol(rets[-short_window:])
        long_vol = annualised_vol(rets[-long_window:]) if len(rets) >= long_window else recent_vol

        if long_vol == 0:
            return "normal", recent_vol, long_vol

        ratio = recent_vol / long_vol
        if ratio > 1.5:
            return "high", recent_vol, long_vol
        elif ratio < 0.7:
            return "low", recent_vol, long_vol
        return "normal", recent_vol, long_vol

    def _clean_prices(self, prices: list) -> list[float]:
        result = []
        for p in prices:
            if p is None:
                continue
            try:
                f = float(p)
                if not math.isnan(f) and not math.isinf(f):
                    result.append(f)
            except (TypeError, ValueError):
                continue
        return result

    # ------------------------------------------------------------------ helpers

    def _active_indicators(self) -> list[str]:
        indicators = ["sma_crossover"]
        if self._use_rsi:
            indicators.append("rsi")
        if self._use_volume_zscore:
            indicators.append("volume_zscore")
        if self._use_macd:
            indicators.append("macd")
        if self._use_bb:
            indicators.append("bollinger_bands")
        if self._use_zscore:
            indicators.append("zscore_momentum")
        if self._use_btc_beta:
            indicators.append("btc_beta")
        if self._use_vol_regime:
            indicators.append("vol_regime")
        return indicators

    def _indicator_count(self) -> int:
        return len(self._active_indicators())

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
