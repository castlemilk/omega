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

import logging
import math
import time
import uuid
from typing import Any

from omega.core.actions import NodeAction
from omega.core.decision_snapshot import SignalTrace
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.signal_generation")


def _safe_mean(values: list[float | None], n: int) -> float | None:
    clean = [v for v in values[-n:] if v is not None]
    return sum(clean) / len(clean) if clean else None


def _momentum_composite(directional: list[float], prices: list[float]) -> float:
    """
    Momentum-weighted composite signal.

    Signals that agree with the recent 5-day price direction receive 2x weight;
    counter-trend signals receive 1x weight.  This prevents mean-reversion
    signals (RSI, BB) from fully cancelling trend signals (SMA, MACD) in
    ranging or weakly-trending markets, producing near-zero composites that
    never escape the HOLD zone.

    In truly flat markets (recent_dir=0 or zero net price change) falls back
    to a simple mean — the market should correctly be HOLD in that case.
    """
    if not directional:
        return 0.0
    if len(prices) >= 6 and prices[-6] != 0:
        recent_dir = 1.0 if prices[-1] > prices[-6] else -1.0
    else:
        recent_dir = 0.0
    if recent_dir == 0.0:
        return sum(directional) / len(directional)
    wsum = sum(v * (2.0 if v * recent_dir > 0.0 else 1.0) for v in directional)
    wtotal = sum(2.0 if v * recent_dir > 0.0 else 1.0 for v in directional)
    return wsum / wtotal if wtotal > 0 else 0.0


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
        # V39: SMA-only. Multi-signal ensemble (V37/V38) pulled composites into
        # HOLD zone (77-83% HOLD) because MACD/btc_beta/zscore offset SMA in a
        # mixed-signal environment. V36 SMA-only had PF=1.62, WR=26.5%, +$76 with
        # 50% trades blocked by time_filter. V39 restores SMA-only to recover that
        # signal quality while the time_filter is now fully disabled (< 0).
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
        # Populated each call to _compute_all_signals; keyed by ticker
        self._last_signal_traces: dict[str, list[SignalTrace]] = {}

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

    @staticmethod
    def _build_traces_from_ts(ts: dict[str, Any]) -> list[SignalTrace]:
        """
        Build SignalTrace records from an already-computed ticker signal dict.

        Called after all signals are computed for a ticker so the raw indicator
        values (rsi, macd, bb_upper, etc.) are available alongside the signal values.
        """
        traces: list[SignalTrace] = []

        # SMA crossover
        if "sma_crossover" in ts:
            sma_s = ts.get("sma_short")
            sma_l = ts.get("sma_long")
            v = ts["sma_crossover"]
            direction = "bullish" if v > 0 else ("bearish" if v < 0 else "neutral")
            if sma_s is not None and sma_l is not None:
                ratio = (sma_s - sma_l) / sma_l if sma_l != 0 else 0.0
                rationale = (
                    f"SMA_short={sma_s:.4f} vs SMA_long={sma_l:.4f} "
                    f"ratio={ratio:+.4f} → {direction} {v:+.3f}"
                )
                inputs: dict[str, Any] = {"sma_short": sma_s, "sma_long": sma_l, "ratio": ratio}
            else:
                rationale = f"SMA crossover → {direction} {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("sma_crossover", v, rationale, inputs))

        # RSI
        if "rsi_signal" in ts:
            rsi = ts.get("rsi")
            v = ts["rsi_signal"]
            if rsi is not None:
                if rsi < 30:
                    condition = f"oversold (RSI={rsi:.1f} < 30)"
                elif rsi > 70:
                    condition = f"overbought (RSI={rsi:.1f} > 70)"
                else:
                    condition = f"neutral (RSI={rsi:.1f})"
                rationale = f"RSI={rsi:.1f} {condition} → {v:+.3f}"
                inputs = {"rsi": rsi, "oversold_threshold": 30, "overbought_threshold": 70}
            else:
                rationale = f"RSI signal → {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("rsi_signal", v, rationale, inputs))

        # MACD
        if "macd_crossover" in ts:
            macd = ts.get("macd")
            sig_line = ts.get("macd_signal_line")
            v = ts["macd_crossover"]
            if macd is not None and sig_line is not None:
                hist = macd - sig_line
                direction = "bullish" if hist > 0 else "bearish"
                rationale = (
                    f"MACD={macd:.5f} vs signal={sig_line:.5f} "
                    f"hist={hist:+.5f} → {direction} {v:+.3f}"
                )
                inputs = {"macd": macd, "signal_line": sig_line, "histogram": hist}
            else:
                rationale = f"MACD crossover → {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("macd_crossover", v, rationale, inputs))

        # Bollinger Bands
        if "bb_signal" in ts:
            price = ts.get("price")
            bb_mid = ts.get("bb_mid")
            bb_upper = ts.get("bb_upper")
            bb_lower = ts.get("bb_lower")
            v = ts["bb_signal"]
            if price is not None and bb_mid is not None and bb_upper is not None:
                band_half = bb_upper - bb_mid
                bb_pos = (price - bb_mid) / band_half if band_half != 0 else 0.0
                if bb_pos < -0.5:
                    position_desc = f"near lower band (bb_pos={bb_pos:.2f})"
                elif bb_pos > 0.5:
                    position_desc = f"near upper band (bb_pos={bb_pos:.2f})"
                else:
                    position_desc = f"mid-band (bb_pos={bb_pos:.2f})"
                rationale = f"Price={price:.4f} {position_desc} mid={bb_mid:.4f} → {v:+.3f}"
                inputs = {
                    "price": price,
                    "bb_mid": bb_mid,
                    "bb_upper": bb_upper,
                    "bb_lower": bb_lower,
                    "bb_pos": bb_pos,
                }
            else:
                rationale = f"BB position → {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("bb_signal", v, rationale, inputs))

        # Z-score momentum
        if "zscore_signal" in ts:
            zscore = ts.get("zscore")
            v = ts["zscore_signal"]
            if zscore is not None:
                direction = "momentum" if zscore > 0 else "mean-reversion"
                rationale = f"Z-score={zscore:.2f} ({direction}) → {v:+.3f}"
                inputs = {"zscore": zscore}
            else:
                rationale = f"Z-score signal → {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("zscore_signal", v, rationale, inputs))

        # Volume signal
        if "volume_signal" in ts:
            vol_z = ts.get("volume_zscore")
            sma_dir = ts.get("sma_crossover", 0.0)
            v = ts["volume_signal"]
            if vol_z is not None:
                price_dir = "up" if sma_dir > 0 else "down"
                rationale = f"Volume_z={vol_z:.2f} with price trending {price_dir} → {v:+.3f}"
                inputs = {"volume_zscore": vol_z, "price_direction": sma_dir}
            else:
                rationale = f"Volume signal → {v:+.3f}"
                inputs = {}
            traces.append(SignalTrace("volume_signal", v, rationale, inputs))

        # Volatility regime
        if "vol_regime_signal" in ts:
            regime = ts.get("vol_regime", "unknown")
            recent_vol = ts.get("recent_vol_ann", 0.0)
            long_vol = ts.get("long_vol_ann", 0.0)
            v = ts["vol_regime_signal"]
            rationale = (
                f"Vol_regime={regime} (recent_ann={recent_vol:.3f} "
                f"long_ann={long_vol:.3f}) → {v:+.3f}"
            )
            inputs = {"vol_regime": regime, "recent_vol_ann": recent_vol, "long_vol_ann": long_vol}
            traces.append(SignalTrace("vol_regime_signal", v, rationale, inputs))

        # BTC beta signal
        if "btc_beta_signal" in ts:
            beta = ts.get("btc_beta", 0.0)
            v = ts["btc_beta_signal"]
            rationale = f"BTC_beta={beta:.2f} x BTC_composite → amplified_signal {v:+.3f}"
            inputs = {"btc_beta": beta}
            traces.append(SignalTrace("btc_beta_signal", v, rationale, inputs))

        return traces

    def _compute_all_signals(self, market_data: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        self._last_signal_traces = {}

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
                    # High volume z-score in direction of price = momentum confirmation
                    price_dir = 1.0 if ts.get("sma_crossover", 0) > 0 else -1.0
                    ts["volume_signal"] = min(1.0, max(-1.0, vol_z / 2.0)) * price_dir

            # Volatility regime (annualised vs long-run average)
            if self._use_vol_regime:
                regime, recent_vol, long_vol = self._compute_vol_regime(prices)
                ts["vol_regime"] = regime  # "high" | "normal" | "low"
                ts["recent_vol_ann"] = recent_vol
                ts["long_vol_ann"] = long_vol
                # Vol regime signal: high-vol is bearish (IC -0.389), low-vol slightly bullish.
                # Symmetric so it does not create a directional bias by itself.
                if regime == "high":
                    ts["vol_regime_signal"] = -0.2
                elif regime == "low":
                    ts["vol_regime_signal"] = 0.1
                # "normal": no signal added (neutral, does not shift composite)

            # Composite signal: momentum-weighted mean of all directional signals.
            # Direction-aligned signals get 2x weight; counter-trend signals get 1x.
            directional = [
                v for k, v in ts.items() if k.endswith("_signal") or k == "sma_crossover"
            ]
            if directional:
                ts["composite"] = _momentum_composite(directional, prices)

            # Trend-adaptive dampening: in strong directional trends, mean-reversion
            # signals (RSI, BB) become deeply oversold/overbought but the trend persists.
            # Dampening prevents them from cancelling trend signals and collapsing the
            # composite toward HOLD when there is a clear directional opportunity.
            _sma_dir = ts.get("sma_crossover", 0.0)
            _trend_str = abs(_sma_dir)
            if _trend_str > 0.5:
                # Dampen factor: 1.0 at strength=0.5 → 0.3 at strength=1.0.
                # Floor at 0.3 (not 0.0) so mean-reversion signals are reduced
                # but never eliminated.  RSI/BB differ between tickers even in
                # a uniform downtrend (some are more oversold than others), and
                # zeroing them out collapses all composites to the same value,
                # which is the root cause of the rank-staircase pattern.
                _dampen = max(0.3, 1.0 - (_trend_str - 0.5) * 2.0)
                _changed = False
                if _sma_dir < 0:  # downtrend: dampen bullish (positive) mean-reversion
                    for _mr in ("rsi_signal", "bb_signal"):
                        if ts.get(_mr, 0.0) > 0:
                            ts[_mr] = ts[_mr] * _dampen
                            _changed = True
                else:  # uptrend: dampen bearish (negative) mean-reversion
                    for _mr in ("rsi_signal", "bb_signal"):
                        if ts.get(_mr, 0.0) < 0:
                            ts[_mr] = ts[_mr] * _dampen
                            _changed = True
                if _changed:
                    _dir2 = [
                        v for k, v in ts.items() if k.endswith("_signal") or k == "sma_crossover"
                    ]
                    if _dir2:
                        ts["composite"] = _momentum_composite(_dir2, prices)

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
                        # Recompute composite with BTC beta signal (momentum-weighted)
                        dir_vals = [
                            v
                            for k, v in ts.items()
                            if k.endswith("_signal") or k == "sma_crossover"
                        ]
                        if dir_vals:
                            ts["composite"] = _momentum_composite(dir_vals, asset_prices)

        # Debug: log composite spread so we can verify cross-ticker differentiation
        _composites = [
            (t, s.get("composite", 0.0))
            for t, s in signals.items()
            if s.get("composite") is not None and not t.startswith("_")
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

        # Build signal traces after all signals (including BTC beta) are finalised.
        # Store both in self._last_signal_traces (for external access) and as
        # ts["_traces"] so strategy.py can embed them in TickerDecision objects
        # without needing a reference back to this node.
        for ticker, ts in signals.items():
            if not ticker.startswith("_"):
                traces = self._build_traces_from_ts(ts)
                self._last_signal_traces[ticker] = traces
                ts["_traces"] = traces  # embedded for strategy.py

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
