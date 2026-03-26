"""
omega.nodes.victoria.liquidation_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Liquidation Cascade Risk Filter.

NOT a directional signal — outputs a risk_score 0..1 and a position_scale
multiplier.  When risk > 0.7: reduce positions 50%.  When risk > 0.9: no new
positions are opened.

Computation:
  a) Cluster proximity — how close is the current price to common leverage
     liquidation levels (5x, 10x, 25x, 50x, 100x)?
  b) Recent liquidation volume spike — USD vol in last 1h vs 24h average;
     a spike means a cascade is in progress (avoid entering).
  c) Long/short liquidation ratio — imbalance signals directional momentum.

Data sources (free, no auth required):
  - Binance futures: https://fapi.binance.com/fapi/v1/allForceOrders
  - Coinglass API (optional, requires COINGLASS_API_KEY env var):
    https://open-api.coinglass.com/public/v2/liquidation/info
  - Pre-fetched: market_data["_liquidation_data"] (list of order dicts)

Integration:
  LiquidationRisk.position_scale is wired into _do_construct_portfolio as
  a multiplier on all proposed position sizes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.liquidation_signals")

# Risk thresholds
_RISK_HIGH_THRESHOLD = 0.7  # risk > 0.7 → 50% position reduction
_RISK_EXTREME_THRESHOLD = 0.9  # risk > 0.9 → no new positions

_HIGH_SCALE = 0.5
_EXTREME_SCALE = 0.0

# Common leverage levels modeled (determines cluster distances)
_LEVERAGE_LEVELS = (5, 10, 25, 50, 100)

# Binance fstream public endpoint — no auth required
_BINANCE_FORCE_ORDERS_URL = (
    "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=200"
)
# Coinglass (optional — requires COINGLASS_API_KEY)
_COINGLASS_URL = "https://open-api.coinglass.com/public/v2/liquidation/info"


@dataclass
class LiquidationRisk:
    """Output of LiquidationCascadeSignal.compute().

    This is a RISK object, not a directional signal.

    position_scale : multiplier to apply to proposed position sizes.
                     1.0 = unchanged  |  0.5 = halved  |  0.0 = no new positions.
    risk_score     : raw composite risk 0 (safe) … 1 (extreme cascade risk).
    regime_tag     : human-readable description of current risk state.
    raw            : sub-scores for inspection and logging.
    """

    risk_score: float
    position_scale: float
    regime_tag: str
    raw: dict[str, float] = field(default_factory=dict)


class LiquidationCascadeSignal:
    """
    Liquidation cascade risk filter for Victoria.

    Returns a LiquidationRisk with position_scale ∈ {0.0, 0.5, 1.0}.

    Usage::
        signal = LiquidationCascadeSignal()
        risk = signal.compute(market_data)
        # Apply scale in position sizing:
        adjusted_size = raw_size * risk.position_scale
    """

    def compute(self, market_data: dict[str, Any]) -> LiquidationRisk:
        raw: dict[str, float] = {}

        # ── 1. Current price ────────────────────────────────────────────────
        _btc = market_data.get("BTCUSDT") or {}
        prices = _btc.get("close") or market_data.get("close", [])
        current_price = float(prices[-1]) if prices else None

        # ── 2. Liquidation data ─────────────────────────────────────────────
        liq_data: list[dict] | None = market_data.get("_liquidation_data")
        if liq_data is None:
            liq_data = self._fetch_liquidations()

        # ── 3. Sub-signals ──────────────────────────────────────────────────
        cluster_risk = self._compute_cluster_proximity(current_price, raw)
        vol_risk, ls_ratio = self._compute_liquidation_volume(liq_data, raw)

        if cluster_risk is None and vol_risk is None:
            return LiquidationRisk(
                risk_score=0.0,
                position_scale=1.0,
                regime_tag="no_data",
                raw=raw,
            )

        # ── 4. Composite risk score ─────────────────────────────────────────
        # Weights: volume spike 50%, cluster proximity 40%, ls imbalance 10%
        components: list[tuple[float, float]] = []
        if cluster_risk is not None:
            components.append((cluster_risk, 0.4))
        if vol_risk is not None:
            components.append((vol_risk, 0.5))
        if ls_ratio is not None:
            # Extreme long/short imbalance → higher cascade risk regardless of direction
            ls_imbalance = abs(ls_ratio - 0.5) * 2.0  # 0 = balanced, 1 = all one side
            components.append((ls_imbalance, 0.1))

        total_w = sum(w for _, w in components)
        risk_score = sum(v * w for v, w in components) / total_w if total_w else 0.0
        risk_score = max(0.0, min(1.0, risk_score))
        raw["risk_score"] = round(risk_score, 4)

        # ── 5. Position scale ───────────────────────────────────────────────
        if risk_score > _RISK_EXTREME_THRESHOLD:
            position_scale = _EXTREME_SCALE
            regime_tag = "cascade_extreme"
        elif risk_score > _RISK_HIGH_THRESHOLD:
            position_scale = _HIGH_SCALE
            regime_tag = "cascade_high"
        elif risk_score > 0.4:
            position_scale = 1.0
            regime_tag = "cascade_moderate"
        else:
            position_scale = 1.0
            regime_tag = "cascade_low"

        raw["position_scale"] = position_scale

        logger.debug(
            "liquidation_cascade: risk=%.3f scale=%.1f regime=%s",
            risk_score,
            position_scale,
            regime_tag,
        )
        return LiquidationRisk(
            risk_score=risk_score,
            position_scale=position_scale,
            regime_tag=regime_tag,
            raw=raw,
        )

    # ── Sub-signal helpers ───────────────────────────────────────────────────

    def _compute_cluster_proximity(
        self, current_price: float | None, raw: dict[str, float]
    ) -> float | None:
        """
        Estimate cluster density near the current price.

        For each leverage level L:
          Long cluster  = price x (1 - 1/L)  <- longs get liquidated here
          Short cluster = price x (1 + 1/L)  <- shorts get liquidated here

        Distance = 1/L (fraction of price).  Higher L -> closer cluster.

        Cluster density = sum(exp(-dist x 20)), summed across all leverage levels.
        Normalised to [0, 1] by dividing by the number of levels.
        """
        if not current_price or current_price <= 0:
            return None

        density = sum(math.exp(-1.0 / lev * 20) for lev in _LEVERAGE_LEVELS)
        cluster_score = min(1.0, density / len(_LEVERAGE_LEVELS))

        raw["cluster_density"] = round(density, 4)
        raw["cluster_score"] = round(cluster_score, 4)
        raw["closest_cluster_pct"] = round(100.0 / max(_LEVERAGE_LEVELS), 2)
        return cluster_score

    def _compute_liquidation_volume(
        self,
        liq_data: list[dict] | None,
        raw: dict[str, float],
    ) -> tuple[float | None, float | None]:
        """
        Compute USD liquidation volume spike and long/short liquidation ratio.

        Returns:
          vol_risk : 0..1  — 0 = calm, 1 = heavy cascade in progress
          ls_ratio : 0..1  — fraction of liquidated USD that were long positions
        """
        if not liq_data:
            return None, None

        now_ms = int(time.time() * 1000)
        hour_ms = 3_600_000  # 1 hour in ms

        vol_1h = vol_4h = vol_24h = 0.0
        long_usd = short_usd = 0.0

        for order in liq_data:
            try:
                # Binance allForceOrders fields: time, origQty, averagePrice, side
                ts = int(order.get("time", order.get("T", 0)))
                qty = float(order.get("origQty", order.get("q", 0)))
                avg_price = float(order.get("averagePrice", order.get("ap", 0)))
                usd_val = qty * avg_price
                side = str(order.get("side", order.get("S", ""))).upper()
                age_ms = now_ms - ts

                if age_ms <= hour_ms:
                    vol_1h += usd_val
                if age_ms <= 4 * hour_ms:
                    vol_4h += usd_val
                if age_ms <= 24 * hour_ms:
                    vol_24h += usd_val

                # SELL side = long position force-closed (longs get liquidated by selling)
                if side in ("SELL", "S"):
                    long_usd += usd_val
                else:
                    short_usd += usd_val

            except (TypeError, ValueError, KeyError):
                continue

        raw["liq_vol_1h_usd"] = round(vol_1h, 0)
        raw["liq_vol_4h_usd"] = round(vol_4h, 0)
        raw["liq_vol_24h_usd"] = round(vol_24h, 0)

        # Long/short liquidation ratio
        ls_ratio: float | None = None
        total_liq = long_usd + short_usd
        if total_liq > 0:
            ls_ratio = long_usd / total_liq
            raw["long_liq_ratio"] = round(ls_ratio, 4)

        # Volume spike risk
        vol_risk: float | None = None
        if vol_24h > 0:
            hourly_avg = vol_24h / 24.0
            # Spike ratio: current 1h vol vs average hourly over 24h.
            # Normal ~1.0; moderate cascade ~3-5; extreme > 5.
            spike_ratio = vol_1h / max(hourly_avg, 1_000_000)  # $1M floor
            # log-scale normalisation so spike=1→0, spike=5→~0.9
            vol_risk = min(1.0, math.log1p(max(0.0, spike_ratio - 1.0)) / math.log1p(4.0))
            raw["liq_spike_ratio"] = round(spike_ratio, 3)
            raw["vol_risk"] = round(vol_risk, 4)
        elif vol_1h > 0:
            # No 24h context: use absolute threshold ($50M/h ≈ cascade)
            vol_risk = min(1.0, vol_1h / 50_000_000)
            raw["vol_risk"] = round(vol_risk, 4)

        return vol_risk, ls_ratio

    # ── Data fetchers ────────────────────────────────────────────────────────

    def _fetch_liquidations(self) -> list[dict] | None:
        """Try Coinglass first (if key present), fall back to Binance."""
        api_key = os.getenv("COINGLASS_API_KEY")
        if api_key:
            result = self._fetch_coinglass(api_key)
            if result:
                return result
        return self._fetch_binance()

    def _fetch_binance(self) -> list[dict] | None:
        """Fetch recent BTC forced orders from Binance fstream (no auth)."""
        try:
            req = urllib.request.Request(
                _BINANCE_FORCE_ORDERS_URL,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
                return data
        except Exception as exc:
            logger.debug("Binance liquidation fetch failed: %s", exc)
            return None

    def _fetch_coinglass(self, api_key: str) -> list[dict] | None:
        """Fetch liquidation info from Coinglass (requires API key)."""
        try:
            req = urllib.request.Request(
                _COINGLASS_URL,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "coinglassSecret": api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Coinglass returns nested data — flatten to list of order-like dicts
            orders: list[dict] = []
            for item in data.get("data", []):
                orders.append(
                    {
                        "time": int(time.time() * 1000),
                        "origQty": float(item.get("volUsd", 0))
                        / max(float(item.get("price", 1)), 1),
                        "averagePrice": float(item.get("price", 0)),
                        "side": "SELL" if item.get("side", "").lower() == "buy" else "BUY",
                    }
                )
            return orders if orders else None
        except Exception as exc:
            logger.debug("Coinglass liquidation fetch failed: %s", exc)
            return None
