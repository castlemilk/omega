"""
omega.nodes.victoria.onchain_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OnChainDataNode — fetches on-chain metrics from DefiLlama (free API).

DefiLlama provides open, free access to:
  - Total crypto TVL (protocol-level + chain-level)
  - Historical TVL for trend computation
  - Protocol-level flows and DeFi health indicators

TVL trend model:
  7d TVL change > +5%   → BULLISH  (capital flowing into DeFi)
  7d TVL change < -5%   → BEARISH  (capital fleeing DeFi)
  otherwise             → NEUTRAL

Capabilities: on_chain_metrics, tvl_trend, ONCHAIN_DATA
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.onchain_data")

# DefiLlama public endpoints (free, no auth required)
_DEFILLAMA_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl"
_DEFILLAMA_GLOBAL_URL = "https://api.llama.fi/v2/chains"

# Cache TTL: TVL updates hourly, refresh every 10 min is fine
_CACHE_TTL = 600  # seconds

# TVL trend signal thresholds
_BULLISH_TVL_CHANGE = 0.05  # +5% 7-day change
_BEARISH_TVL_CHANGE = -0.05  # -5% 7-day change


class DefiLlamaTVLFetcher:
    """
    Fetch total crypto TVL history from DefiLlama.

    Returns a list of (timestamp, tvl_usd) daily data points, sorted ascending.
    Cache TTL: 10 minutes.
    """

    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._cache: tuple[list[dict[str, Any]], float] | None = None

    def fetch_history(self) -> list[dict[str, Any]] | None:
        """
        Returns list of {"date": unix_ts, "tvl": float} dicts, ascending.
        Returns None on failure.
        """
        if self._cache is not None:
            data, ts = self._cache
            if time.time() - ts < _CACHE_TTL:
                return data

        try:
            req = urllib.request.Request(
                _DEFILLAMA_TVL_URL,
                headers={"User-Agent": "omega-onchain/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("DefiLlama TVL fetch failed: %s", exc)
            return None

        try:
            # API returns list of {"date": int, "tvl": float}
            if not isinstance(raw, list) or not raw:
                return None
            # Sort ascending by date
            data = sorted(raw, key=lambda x: x.get("date", 0))
            self._cache = (data, time.time())
            return data
        except Exception as exc:
            logger.debug("DefiLlama TVL parse failed: %s", exc)
            return None


def _compute_tvl_trend(history: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute TVL trend metrics from history.

    Returns:
      current_tvl       : float (latest TVL in USD)
      tvl_7d_change     : float (fractional change, e.g. 0.05 = +5%)
      tvl_30d_change    : float
      signal            : "BULLISH" | "BEARISH" | "NEUTRAL"
      confidence        : float 0-1
    """
    if not history or len(history) < 2:
        return {
            "current_tvl": None,
            "tvl_7d_change": None,
            "tvl_30d_change": None,
            "signal": "NEUTRAL",
            "confidence": 0.0,
        }

    current_tvl = float(history[-1].get("tvl", 0))

    def _find_tvl_n_days_ago(n_days: int) -> float | None:
        cutoff = history[-1].get("date", 0) - n_days * 86400
        # Walk backward to find the closest entry before cutoff
        for entry in reversed(history[:-1]):
            if entry.get("date", 0) <= cutoff:
                return float(entry.get("tvl", 0))
        # Fallback: use oldest available
        return float(history[0].get("tvl", 0)) if history else None

    tvl_7d_ago = _find_tvl_n_days_ago(7)
    tvl_30d_ago = _find_tvl_n_days_ago(30)

    tvl_7d_change: float | None = None
    tvl_30d_change: float | None = None

    if tvl_7d_ago and tvl_7d_ago > 0:
        tvl_7d_change = (current_tvl - tvl_7d_ago) / tvl_7d_ago

    if tvl_30d_ago and tvl_30d_ago > 0:
        tvl_30d_change = (current_tvl - tvl_30d_ago) / tvl_30d_ago

    # Signal from 7d change (most actionable)
    if tvl_7d_change is None:
        signal = "NEUTRAL"
        confidence = 0.3
    elif tvl_7d_change > _BULLISH_TVL_CHANGE:
        signal = "BULLISH"
        # Confidence scales with magnitude
        confidence = min(0.9, 0.6 + tvl_7d_change * 2.0)
    elif tvl_7d_change < _BEARISH_TVL_CHANGE:
        signal = "BEARISH"
        confidence = min(0.9, 0.6 + abs(tvl_7d_change) * 2.0)
    else:
        signal = "NEUTRAL"
        # Confidence inversely related to distance from zero
        confidence = 0.5 - abs(tvl_7d_change) * 2.0

    return {
        "current_tvl": round(current_tvl, 0),
        "tvl_7d_change": round(tvl_7d_change, 4) if tvl_7d_change is not None else None,
        "tvl_30d_change": round(tvl_30d_change, 4) if tvl_30d_change is not None else None,
        "signal": signal,
        "confidence": round(max(0.0, confidence), 3),
    }


class OnChainDataNode(Node):
    """
    Fetches on-chain metrics from DefiLlama (free API).

    Provides:
      - Total crypto TVL (current + historical)
      - 7-day and 30-day TVL trend
      - DeFi health signal: BULLISH | BEARISH | NEUTRAL

    TVL declining → bearish (capital exiting DeFi)
    TVL rising    → bullish (capital entering DeFi, risk-on)

    Capabilities
    ------------
    on_chain_metrics  → fetch full TVL metrics
    tvl_trend         → get trend signal only
    ONCHAIN_DATA      → bridge-routing alias

    Action: ``fetch_onchain`` or ``tvl_trend``

    Output keys (fetch_onchain)
    ---------------------------
    current_tvl         : float  (USD, e.g. 95_000_000_000)
    tvl_7d_change       : float  (fraction, e.g. 0.03 = +3%)
    tvl_30d_change      : float
    signal              : str    BULLISH | BEARISH | NEUTRAL
    signal_value        : float  -1.0 to +1.0  (for weighting)
    confidence          : float  0-1
    data_source         : str    "defillama"
    data_points         : int    (history length)
    """

    def __init__(self, timeout: float = 8.0) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._tvl_fetcher = DefiLlamaTVLFetcher(timeout=timeout)

        # Runtime state
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_signal = "NEUTRAL"
        self._last_tvl: float | None = None

    # ── Node interface ────────────────────────────────────────────────────────

    def get_state(self) -> NodeState:
        error_rate = self._error_count / max(1, self._execution_count)
        avg_lat = self._total_latency_ms / max(1, self._execution_count)
        return NodeState(
            node_id=self._node_id,
            name="OnChainDataNode",
            version=self._version,
            health=max(0.0, 1.0 - error_rate),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": avg_lat,
                "error_rate": error_rate,
                "execution_count": float(self._execution_count),
                "last_tvl_usd": float(self._last_tvl) if self._last_tvl else 0.0,
            },
            metadata={
                "data_source": "defillama",
                "last_signal": self._last_signal,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["on_chain_metrics", "tvl_trend", "ONCHAIN_DATA"]

    def describe(self) -> str:
        return (
            "OnChainDataNode: fetches total crypto TVL from DefiLlama (free API). "
            "Computes 7-day and 30-day TVL trends as DeFi health signals. "
            "Rising TVL indicates capital inflow (bullish); declining TVL indicates "
            "capital flight (bearish). No API key required."
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._total_latency_ms / max(1, self._execution_count),
            "error_rate": self._error_count / max(1, self._execution_count),
            "execution_count": float(self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        return False

    def execute(self, inp: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1

        action = inp.action
        if action not in ("fetch_onchain", "on_chain_metrics", "tvl_trend", "ONCHAIN_DATA"):
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._error_count += 1
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[f"OnChainDataNode: unknown action '{action}'"],
                metrics={"latency_ms": elapsed},
            )

        try:
            result = self._fetch_metrics(inp.parameters)
            elapsed = (time.perf_counter() - t0) * 1000
            self._total_latency_ms += elapsed
            self._last_signal = result.get("signal", "NEUTRAL")
            self._last_tvl = result.get("current_tvl")
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
            logger.error("OnChainDataNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=inp.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    # ── Internal logic ────────────────────────────────────────────────────────

    def _fetch_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch TVL history and compute trend metrics."""
        # Support history injection for testing
        history_override: list[dict[str, Any]] | None = params.get("history_override")

        raw_history: list[dict[str, Any]] | None
        if history_override is not None:
            raw_history = history_override
            data_source = "override"
        else:
            raw_history = self._tvl_fetcher.fetch_history()
            data_source = "defillama"
        history: list[dict[str, Any]] = raw_history or []

        if not history:
            logger.warning("OnChainDataNode: no TVL data available")
            return {
                "current_tvl": None,
                "tvl_7d_change": None,
                "tvl_30d_change": None,
                "signal": "NEUTRAL",
                "signal_value": 0.0,
                "confidence": 0.0,
                "data_source": data_source,
                "data_points": 0,
            }

        trend = _compute_tvl_trend(history)

        # Map signal to a numeric value for weighting (-1 to +1)
        signal_map = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
        signal_value = signal_map.get(trend["signal"], 0.0)
        # Scale by confidence
        signal_value *= trend["confidence"]

        logger.debug(
            "OnChainData: tvl=%.1fB 7d=%.2f%% signal=%s confidence=%.3f",
            (trend["current_tvl"] or 0) / 1e9,
            (trend["tvl_7d_change"] or 0) * 100,
            trend["signal"],
            trend["confidence"],
        )

        return {
            **trend,
            "signal_value": round(signal_value, 4),
            "data_source": data_source,
            "data_points": len(history),
        }
