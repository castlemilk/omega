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

logger = logging.getLogger("omega.nodes.victoria.signal_generation")


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
                signals["_geometry_geo_dist_crash"] = round(float(_manifold_state_ref.geo_dist_crash), 4)
                signals["_geometry_geo_dist_rally"] = round(float(_manifold_state_ref.geo_dist_rally), 4)
                signals["_geometry_manifold_regime"] = _manifold_state_ref.regime
        _orc_state_ref = locals().get("_orc_state")
        if _orc_state_ref is not None and _orc_state_ref.confidence >= 0.3:
            with contextlib.suppress(Exception):
                signals["_geometry_orc_kappa"] = round(float(_orc_state_ref.mean_curvature), 4)
                signals["_geometry_orc_regime"] = _orc_state_ref.regime

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

            # Funding rate signal
            if self._funding_signal is not None:
                try:
                    fr_signal = self._funding_signal.compute(ticker)
                    if fr_signal != 0.0:
                        ts["funding_rate_signal"] = fr_signal
                except Exception:
                    pass

            # Cross-asset market-level signals (pre-computed above, applied to every ticker)
            if _fear_greed_val != 0.0:
                ts["fear_greed_signal"] = _fear_greed_val
            if _dxy_val != 0.0:
                ts["dxy_signal"] = _dxy_val
            if _vix_val != 0.0:
                ts["vix_signal"] = _vix_val
            if _yield_curve_val != 0.0:
                ts["yield_curve_signal"] = _yield_curve_val
            if _spy_val != 0.0:
                ts["spy_signal"] = _spy_val
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

            # IC-weighted composite — falls back to equal-weight when IC data is sparse.
            # Uses per-signal Information Coefficient from SignalDecayDetector to
            # up-weight historically predictive signals and exclude anti-predictive ones.
            directional = [
                v for k, v in ts.items() if k.endswith("_signal") or k == "sma_crossover"
            ]
            if directional:
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
