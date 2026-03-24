"""
omega.nodes.victoria.vrp_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
VRPSignalNode — Variance Risk Premium signal for Victoria.

Based on Christensen & Prabhala (1998): implied vol consistently
overestimates realized vol, generating a tradeable risk premium.

VRP = IV - RV  (both annualised)
  VRP > 0 : market overpays for protection → vol sellers rewarded
  VRP < 0 : realized vol exceeds implied → crisis / trend regime

Regime classification (VRP z-score):
  FEAR        : zscore > +1.5  (IV >> RV, vol overpriced — sell vol)
  NEUTRAL     : -1.0 <= zscore <= +1.5
  COMPLACENCY : zscore < -1.0  (IV << RV, danger ahead — reduce exposure)

Capabilities: ["compute_vrp", "vrp_regime"]
"""

import logging
import math
import time
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.nodes.victoria.vrp_data import (
    DeribitVolFetcher,
    FundingRateVolProxy,
    RealizedVolCalculator,
)

logger = logging.getLogger("omega.nodes.victoria.vrp_signal")

_FEAR_THRESHOLD = 1.5
_COMPLACENCY_THRESHOLD = -1.0
_CIRCUIT_BREAKER_THRESHOLD = -2.0


class VRPSignalNode(Node):
    """
    Computes the Variance Risk Premium (IV - RV) signal.

    IV source priority: Deribit API → funding-rate proxy → None
    RV estimator priority: Garman-Klass → Parkinson → close-to-close

    Output (from ``compute_vrp`` action):
      vrp_raw      : IV - RV (annualised spread, e.g. 0.30 = 30%)
      vrp_zscore   : (VRP - 30d_mean) / 30d_std
      vrp_regime   : "FEAR" | "NEUTRAL" | "COMPLACENCY"
      vrp_signal   : -1.0 to +1.0 (positive = sell vol / mean-revert)
      confidence   : 0.0-1.0 (data quality x sample size x signal strength)
      implied_vol  : IV used (float or None)
      realized_vol : RV used (float or None)
      circuit_breaker : bool (True when zscore < -2sigma)
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"

        self._deribit = DeribitVolFetcher()
        self._funding_proxy = FundingRateVolProxy()
        self._rv_calc = RealizedVolCalculator()

        # Rolling VRP history for z-score computation
        self._vrp_history: list[float] = []
        self._zscore_window = 30

        # Runtime state
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_vrp = 0.0
        self._last_zscore = 0.0
        self._last_regime = "NEUTRAL"
        self._circuit_breaker_triggered = False

    # ─────────────────────────────────────────────────────────── Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="VRPSignalNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "last_vrp": self._last_vrp,
                "last_zscore": self._last_zscore,
                "vrp_history_len": float(len(self._vrp_history)),
            },
            metadata={
                "last_regime": self._last_regime,
                "circuit_breaker_triggered": self._circuit_breaker_triggered,
                "zscore_window": self._zscore_window,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["compute_vrp", "vrp_regime"]

    def describe(self) -> str:
        return (
            "VRPSignalNode: computes the Variance Risk Premium (IV - RV) for BTC/ETH. "
            "Uses Deribit ~30-day ATM implied vol and Garman-Klass realized vol from OHLCV. "
            "Classifies regime as FEAR (IV >> RV, sell vol) or COMPLACENCY (IV << RV, "
            "reduce exposure). Circuit breaker triggers when zscore < -2sigma."
        )

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = inp.action
        params = inp.parameters

        try:
            if action == "compute_vrp":
                result = self._compute_vrp(params)
            elif action == "vrp_regime":
                result = {
                    "regime": self._last_regime,
                    "zscore": self._last_zscore,
                    "circuit_breaker": self._circuit_breaker_triggered,
                }
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=inp.request_id,
                    success=False,
                    errors=[f"VRPSignalNode: unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": elapsed,
                    "vrp_raw": self._last_vrp,
                    "vrp_zscore": self._last_zscore,
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("VRPSignalNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "last_vrp": self._last_vrp,
            "last_zscore": self._last_zscore,
            "vrp_history_len": float(len(self._vrp_history)),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        # Future: tune zscore window or regime thresholds via TPE
        return False

    # ─────────────────────────────────────────────────────────── VRP computation

    def _compute_vrp(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Compute the full VRP signal.

        Params:
          market_data : dict[ticker → ohlcv_dict]
          currency    : "BTC" or "ETH" (default "BTC")
          iv_override : float | None — bypass Deribit fetch (useful in tests)
        """
        market_data: dict[str, Any] = params.get("market_data", {})
        currency: str = params.get("currency", "BTC")
        iv_override: float | None = params.get("iv_override")
        ticker = f"{currency}USDT"

        # ── 1. Implied Volatility ──────────────────────────────────────────────
        if iv_override is not None:
            iv: float | None = float(iv_override)
            iv_source = "override"
        else:
            iv, iv_source = self._get_implied_vol(currency, market_data, ticker)

        # ── 2. Realized Volatility ────────────────────────────────────────────
        rv, rv_source = self._get_realized_vol(market_data, ticker)

        # ── 3. Early-out when data is missing ────────────────────────────────
        if iv is None or rv is None:
            logger.debug("VRP: incomplete data — iv=%s rv=%s", iv, rv)
            data_quality = 0.3 if (iv is not None or rv is not None) else 0.0
            return self._make_result(0.0, 0.0, "NEUTRAL", data_quality, iv, rv, False)

        # ── 4. VRP and history ────────────────────────────────────────────────
        vrp = iv - rv
        self._vrp_history.append(vrp)
        # Trim to 3x window to bound memory
        if len(self._vrp_history) > self._zscore_window * 3:
            self._vrp_history = self._vrp_history[-self._zscore_window * 2 :]

        vrp_zscore = self._zscore(vrp)
        sample_quality = min(1.0, len(self._vrp_history) / self._zscore_window)

        # ── 5. Regime and signal ──────────────────────────────────────────────
        regime = self._classify(vrp_zscore)
        vrp_signal = self._signal_value(vrp_zscore, regime, vrp)

        # ── 6. Confidence ─────────────────────────────────────────────────────
        signal_strength = min(1.0, abs(vrp_zscore) / 3.0)
        confidence = min(1.0, sample_quality * (0.5 + 0.5 * signal_strength))

        # ── 7. Circuit breaker ────────────────────────────────────────────────
        circuit = vrp_zscore < _CIRCUIT_BREAKER_THRESHOLD
        if circuit and not self._circuit_breaker_triggered:
            logger.warning(
                "VRP circuit breaker: zscore=%.2f < %.1fsigma — extreme COMPLACENCY; "
                "flagging for manual review (iv=%.2f rv=%.2f)",
                vrp_zscore,
                _CIRCUIT_BREAKER_THRESHOLD,
                iv,
                rv,
            )
        self._circuit_breaker_triggered = circuit

        # ── 8. Update cached state ────────────────────────────────────────────
        self._last_vrp = vrp
        self._last_zscore = vrp_zscore
        self._last_regime = regime

        logger.debug(
            "VRP: iv=%.3f(%s) rv=%.3f(%s) vrp=%.3f zscore=%.2f regime=%s signal=%.2f",
            iv,
            iv_source,
            rv,
            rv_source,
            vrp,
            vrp_zscore,
            regime,
            vrp_signal,
        )

        return self._make_result(vrp, vrp_zscore, regime, confidence, iv, rv, circuit)

    # ─────────────────────────────────────────────────────────── data helpers

    def _get_implied_vol(
        self, currency: str, market_data: dict[str, Any], ticker: str
    ) -> tuple[float | None, str]:
        """Return (iv, source_label). Priority: Deribit > funding proxy."""
        # 1. Deribit real-time
        iv = self._deribit.fetch_iv(currency)
        if iv is not None:
            return iv, "deribit"

        # 2. Funding rate proxy from this ticker
        data = market_data.get(ticker, {})
        funding = data.get("funding_rates", [])
        if funding:
            iv = self._funding_proxy.compute_iv_proxy(funding)
            if iv is not None:
                return iv, "funding_proxy"

        # 3. Funding rate proxy from BTC as cross-asset fallback
        if currency != "BTC":
            btc_data = market_data.get("BTCUSDT", {})
            funding_btc = btc_data.get("funding_rates", [])
            if funding_btc:
                iv = self._funding_proxy.compute_iv_proxy(funding_btc)
                if iv is not None:
                    return iv, "funding_proxy_btc"

        # 4. RV-based estimate: IV ~= RV * 1.15 (typical crypto VRP premium).
        # Fires only when Deribit is unreachable AND no funding data exists.
        # Keeps the VRP signal alive (non-zero) rather than returning 0.
        rv_estimate, _ = self._get_realized_vol(market_data, f"{currency}USDT")
        if rv_estimate is not None:
            iv = rv_estimate * 1.15
            logger.debug(
                "VRP IV fallback: rv_estimate=%.3f -> iv_estimate=%.3f (rv*1.15)", rv_estimate, iv
            )
            return iv, "rv_estimate"

        return None, "none"

    def _get_realized_vol(
        self, market_data: dict[str, Any], ticker: str
    ) -> tuple[float | None, str]:
        """Return (rv, estimator_label). Priority: Garman-Klass > Parkinson > c-t-c."""
        data = market_data.get(ticker, {})
        if not data:
            data = market_data.get("BTCUSDT", {})
        if not data:
            return None, "none"

        if all(k in data for k in ("open", "high", "low", "close")):
            rv = self._rv_calc.compute(data, estimator="garman_klass")
            if rv is not None:
                return rv, "garman_klass"

        if "high" in data and "low" in data:
            rv = self._rv_calc.compute(data, estimator="parkinson")
            if rv is not None:
                return rv, "parkinson"

        closes = data.get("close") or data.get("adjclose", [])
        if closes:
            rv = self._rv_calc.compute({"close": closes}, estimator="close_to_close")
            if rv is not None:
                return rv, "close_to_close"

        return None, "none"

    # ─────────────────────────────────────────────────────────── maths

    def _zscore(self, current_vrp: float) -> float:
        if len(self._vrp_history) < 5:
            return 0.0
        window = min(self._zscore_window, len(self._vrp_history))
        recent = self._vrp_history[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((v - mean) ** 2 for v in recent) / max(1, len(recent) - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        return (current_vrp - mean) / std

    def _classify(self, zscore: float) -> str:
        if zscore > _FEAR_THRESHOLD:
            return "FEAR"
        if zscore < _COMPLACENCY_THRESHOLD:
            return "COMPLACENCY"
        return "NEUTRAL"

    def _signal_value(self, zscore: float, regime: str, vrp_raw: float = 0.0) -> float:
        """
        Map VRP z-score to directional signal [-1, +1].

        FEAR         → positive (sell vol / mean revert)
        COMPLACENCY  → negative (reduce longs / trend follow)
        NEUTRAL      → blend zscore tilt with raw VRP level so the signal is
                        non-zero even when zscore ≈ 0 (stable VRP regime).

        Level interpretation: positive VRP (IV > RV) is the normal crypto
        premium — mildly bullish for spot. Negative VRP (IV < RV) is a danger
        signal. We scale by 0.20 (20% VRP = full signal), capped at ±0.5.
        """
        if regime == "FEAR":
            return min(1.0, zscore / 3.0)
        elif regime == "COMPLACENCY":
            return max(-1.0, zscore / 3.0)
        else:
            # In NEUTRAL, blend zscore direction with raw VRP level
            zscore_component = max(-0.5, min(0.5, zscore / 4.0))
            level_component = max(-0.5, min(0.5, vrp_raw / 0.20))
            return max(-1.0, min(1.0, zscore_component * 0.6 + level_component * 0.4))

    def _make_result(
        self,
        vrp_raw: float,
        vrp_zscore: float,
        regime: str,
        confidence: float,
        iv: float | None,
        rv: float | None,
        circuit: bool,
    ) -> dict[str, Any]:
        return {
            "vrp_raw": vrp_raw,
            "vrp_zscore": vrp_zscore,
            "vrp_regime": regime,
            "vrp_signal": self._signal_value(vrp_zscore, regime, vrp_raw),
            "confidence": confidence,
            "implied_vol": iv,
            "realized_vol": rv,
            "circuit_breaker": circuit,
            "history_len": len(self._vrp_history),
        }

    # ─────────────────────────────────────────────────────────── helpers

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
