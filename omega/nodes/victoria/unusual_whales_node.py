"""
omega.nodes.victoria.unusual_whales_node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
NodeAdapter wrappers for Unusual Whales data — plugs UW signals into the
Omega node network via the @omega_node decorator.

Three adapters registered:
  "unusual_whales.flow"        — put/call ratio + alert-volume signal
  "unusual_whales.dark_pool"   — dark pool accumulation/distribution signal
  "unusual_whales.congress"    — congressional alpha signal (slow, 30-90d)

Signal conventions (all adapters return the same envelope):
  {
    "signals": {
      "<signal_name>": {
        "direction":   "bullish" | "bearish" | "neutral",
        "confidence":  float (0.0–1.0),
        "value":       float | None,   # raw numeric if applicable
        "description": str,
      }
    },
    "source":    "unusual_whales",
    "available": bool,   # False when UW_API_KEY absent or API down
    "timestamp": float,
  }

When available=False the adapter returns neutral signals with confidence=0.0
so the meta-model router can degrade gracefully without raising.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from omega.core.node_adapter import NodeAdapter, NodeMetadata, omega_node

from .unusual_whales_provider import get_provider

logger = logging.getLogger("omega.nodes.victoria.unusual_whales_node")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _neutral_signal(name: str, reason: str) -> dict[str, Any]:
    return {
        "direction": "neutral",
        "confidence": 0.0,
        "value": None,
        "description": reason,
    }


def _signal_envelope(signals: dict[str, Any], available: bool) -> dict[str, Any]:
    return {
        "signals": signals,
        "source": "unusual_whales",
        "available": available,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Options flow adapter
# ---------------------------------------------------------------------------


@omega_node("unusual_whales.flow", tags=["signal", "options", "microstructure"])
class OptionsFlowAdapter(NodeAdapter):
    """
    Options flow signal — net call/put ratio + unusual alert clusters.

    Signal: "uw_options_flow"
      Bullish  (confidence ~0.7–0.9): net call premium dominates (ratio > 1.5)
               AND alerts show call-side unusual activity
      Bearish  (confidence ~0.7–0.9): put premium dominates (ratio < 0.67)
               AND alerts show put-side unusual activity
      Neutral  (confidence < 0.4):   ratio is balanced (0.67–1.5) or data unavailable

    Inputs (all optional):
      tickers: list[str]   — filter alerts to these tickers (default: all)

    Outputs:
      signals.uw_options_flow: signal dict
      signals.uw_sector_flow:  per-sector bias dict (tech, finance, energy, ...)
    """

    def __init__(self) -> None:
        super().__init__(name="unusual_whales.flow", version="1.0.0")

    async def _on_startup(self) -> None:
        provider = get_provider()
        if not provider.is_configured:
            logger.warning(
                "unusual_whales.flow: UW_API_KEY not set — signals will be neutral. "
                "Set UW_API_KEY to enable options flow signals."
            )

    async def _on_shutdown(self) -> None:
        pass

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        provider = get_provider()

        if not provider.is_configured:
            return _signal_envelope(
                {"uw_options_flow": _neutral_signal("uw_options_flow", "UW_API_KEY not configured")},
                available=False,
            )

        flow = provider.get_flow_summary()
        if flow is None or not flow.get("signal_available"):
            return _signal_envelope(
                {"uw_options_flow": _neutral_signal("uw_options_flow", "API unavailable")},
                available=False,
            )

        signals: dict[str, Any] = {}

        # ── Net flow ratio signal ─────────────────────────────────────────
        net_flow = flow.get("net_flow")
        if net_flow and "overall_ratio" in net_flow:
            ratio = float(net_flow["overall_ratio"])
            if ratio > 1.5:
                # Strong call dominance
                confidence = min(0.9, 0.5 + (ratio - 1.5) * 0.2)
                signals["uw_options_flow"] = {
                    "direction": "bullish",
                    "confidence": round(confidence, 3),
                    "value": ratio,
                    "description": f"Net call/put ratio {ratio:.2f} — call premium dominant",
                }
            elif ratio < 0.67:
                # Strong put dominance
                confidence = min(0.9, 0.5 + (0.67 - ratio) * 0.3)
                signals["uw_options_flow"] = {
                    "direction": "bearish",
                    "confidence": round(confidence, 3),
                    "value": ratio,
                    "description": f"Net call/put ratio {ratio:.2f} — put premium dominant",
                }
            else:
                signals["uw_options_flow"] = {
                    "direction": "neutral",
                    "confidence": 0.3,
                    "value": ratio,
                    "description": f"Balanced flow ratio {ratio:.2f}",
                }
        else:
            signals["uw_options_flow"] = _neutral_signal("uw_options_flow", "Net flow data unavailable")

        # ── Sector flow signal ────────────────────────────────────────────
        sector_flow = flow.get("sector_flow")
        if sector_flow and isinstance(sector_flow, list):
            sector_biases: dict[str, str] = {}
            for entry in sector_flow:
                sector = entry.get("sector", "unknown")
                ratio_val = entry.get("ratio")
                if ratio_val is not None:
                    sector_biases[sector] = "bullish" if float(ratio_val) > 1.2 else (
                        "bearish" if float(ratio_val) < 0.8 else "neutral"
                    )
            signals["uw_sector_flow"] = {
                "direction": "neutral",
                "confidence": 0.5,
                "value": None,
                "description": "Sector-level flow bias",
                "sector_biases": sector_biases,
            }

        # ── Alert cluster signal ──────────────────────────────────────────
        alerts = flow.get("alerts") or []
        if alerts:
            call_count = sum(1 for a in alerts if a.get("type") == "call")
            put_count = sum(1 for a in alerts if a.get("type") == "put")
            total = call_count + put_count
            if total > 0:
                call_ratio = call_count / total
                if call_ratio > 0.65:
                    signals["uw_alert_cluster"] = {
                        "direction": "bullish",
                        "confidence": round(0.4 + call_ratio * 0.4, 3),
                        "value": call_ratio,
                        "description": f"Alert cluster: {call_count} calls vs {put_count} puts",
                    }
                elif call_ratio < 0.35:
                    signals["uw_alert_cluster"] = {
                        "direction": "bearish",
                        "confidence": round(0.4 + (1 - call_ratio) * 0.4, 3),
                        "value": call_ratio,
                        "description": f"Alert cluster: {put_count} puts vs {call_count} calls",
                    }

        return _signal_envelope(signals, available=True)

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name="unusual_whales.flow",
            node_type="signal_generator",
            version="1.0.0",
            inputs=["tickers"],
            outputs=["signals"],
            description="Unusual Whales options flow signal — net call/put ratio + alert clusters",
            tags=["signal", "options", "microstructure", "unusual_whales"],
        )


# ---------------------------------------------------------------------------
# Dark pool adapter
# ---------------------------------------------------------------------------


@omega_node("unusual_whales.dark_pool", tags=["signal", "dark_pool", "microstructure"])
class DarkPoolAdapter(NodeAdapter):
    """
    Dark pool accumulation/distribution signal.

    Detects institutional accumulation (bullish) or distribution (bearish)
    via off-exchange prints in crypto-proxy equities (MSTR, COIN, IBIT, GBTC).

    Signal: "uw_dark_pool"
      Bullish: large dark pool prints below 20d average price (accumulation)
      Bearish: large dark pool prints above recent high (distribution)
      Neutral: prints near mid-range or data unavailable

    Inputs:
      tickers: list[str]  — crypto-proxy tickers to check (default: MSTR, COIN, IBIT, GBTC)
    """

    def __init__(self) -> None:
        super().__init__(name="unusual_whales.dark_pool", version="1.0.0")

    async def _on_startup(self) -> None:
        provider = get_provider()
        if not provider.is_configured:
            logger.warning(
                "unusual_whales.dark_pool: UW_API_KEY not set — signals will be neutral."
            )

    async def _on_shutdown(self) -> None:
        pass

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        provider = get_provider()

        if not provider.is_configured:
            return _signal_envelope(
                {"uw_dark_pool": _neutral_signal("uw_dark_pool", "UW_API_KEY not configured")},
                available=False,
            )

        tickers = inputs.get("tickers")
        dp = provider.get_dark_pool_summary(tickers=tickers)

        if dp is None or not dp.get("signal_available"):
            return _signal_envelope(
                {"uw_dark_pool": _neutral_signal("uw_dark_pool", "Dark pool API unavailable")},
                available=False,
            )

        signals: dict[str, Any] = {}

        # ── Aggregate prints across proxy tickers ──────────────────────────
        ticker_prints = dp.get("ticker_prints") or {}
        total_notional = 0.0
        premium_prints = 0
        discount_prints = 0

        for ticker, prints in ticker_prints.items():
            if not isinstance(prints, list):
                continue
            for p in prints:
                notional = p.get("notional_value") or 0
                total_notional += float(notional)
                # Premium vs discount to NBBO mid
                nbbo_bid = p.get("nbbo_bid") or 0
                nbbo_ask = p.get("nbbo_ask") or 0
                price = p.get("price") or 0
                if nbbo_bid and nbbo_ask and price:
                    nbbo_mid = (float(nbbo_bid) + float(nbbo_ask)) / 2
                    if float(price) > nbbo_mid * 1.001:
                        premium_prints += 1  # buyer paying up = bullish
                    elif float(price) < nbbo_mid * 0.999:
                        discount_prints += 1  # seller accepting discount = bearish

        total_prints = premium_prints + discount_prints
        if total_prints > 0:
            premium_ratio = premium_prints / total_prints
            if premium_ratio > 0.6:
                confidence = round(0.4 + premium_ratio * 0.4, 3)
                signals["uw_dark_pool"] = {
                    "direction": "bullish",
                    "confidence": confidence,
                    "value": premium_ratio,
                    "description": (
                        f"Dark pool: {premium_prints}/{total_prints} prints at premium "
                        f"(${total_notional/1e6:.1f}M notional)"
                    ),
                }
            elif premium_ratio < 0.4:
                confidence = round(0.4 + (1 - premium_ratio) * 0.4, 3)
                signals["uw_dark_pool"] = {
                    "direction": "bearish",
                    "confidence": confidence,
                    "value": premium_ratio,
                    "description": (
                        f"Dark pool: {discount_prints}/{total_prints} prints at discount "
                        f"(${total_notional/1e6:.1f}M notional)"
                    ),
                }
            else:
                signals["uw_dark_pool"] = {
                    "direction": "neutral",
                    "confidence": 0.3,
                    "value": premium_ratio,
                    "description": f"Balanced dark pool activity (${total_notional/1e6:.1f}M notional)",
                }
        else:
            signals["uw_dark_pool"] = _neutral_signal(
                "uw_dark_pool", "Insufficient dark pool prints for signal"
            )

        return _signal_envelope(signals, available=True)

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name="unusual_whales.dark_pool",
            node_type="signal_generator",
            version="1.0.0",
            inputs=["tickers"],
            outputs=["signals"],
            description="Dark pool accumulation/distribution signal for crypto-proxy equities",
            tags=["signal", "dark_pool", "microstructure", "unusual_whales"],
        )


# ---------------------------------------------------------------------------
# Congressional alpha adapter
# ---------------------------------------------------------------------------


@omega_node("unusual_whales.congress", tags=["signal", "alternative_data", "congress"])
class CongressAdapter(NodeAdapter):
    """
    Congressional trading alpha signal (slow, 30-90d holding horizon).

    Congressional members historically outperform the market by ~14% annually
    (Unusual Whales 2021 report). Trades are disclosed within 45 days of execution.

    Signal: "uw_congress"
      Bullish: net buy ratio > 0.6 in recent disclosures (members net buying)
      Bearish: net sell ratio > 0.6 (members net selling / covering)
      Neutral: balanced or data unavailable

    Note: This is a slow signal. Weight it low in the meta-model router
    and combine with fast signals (options flow, dark pool) for timing.
    """

    def __init__(self) -> None:
        super().__init__(name="unusual_whales.congress", version="1.0.0")

    async def _on_startup(self) -> None:
        provider = get_provider()
        if not provider.is_configured:
            logger.warning(
                "unusual_whales.congress: UW_API_KEY not set — signals will be neutral."
            )

    async def _on_shutdown(self) -> None:
        pass

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        provider = get_provider()

        if not provider.is_configured:
            return _signal_envelope(
                {"uw_congress": _neutral_signal("uw_congress", "UW_API_KEY not configured")},
                available=False,
            )

        congress = provider.get_congress_summary()
        if congress is None or not congress.get("signal_available"):
            return _signal_envelope(
                {"uw_congress": _neutral_signal("uw_congress", "Congress API unavailable")},
                available=False,
            )

        signals: dict[str, Any] = {}
        trades = congress.get("recent_trades") or []

        if not trades:
            signals["uw_congress"] = _neutral_signal("uw_congress", "No recent trades disclosed")
            return _signal_envelope(signals, available=True)

        buy_count = sum(1 for t in trades if str(t.get("action", "")).lower() == "buy")
        sell_count = sum(1 for t in trades if str(t.get("action", "")).lower() == "sell")
        total = buy_count + sell_count

        if total > 0:
            buy_ratio = buy_count / total
            if buy_ratio > 0.6:
                signals["uw_congress"] = {
                    "direction": "bullish",
                    "confidence": round(0.3 + buy_ratio * 0.35, 3),  # slow signal, cap confidence
                    "value": buy_ratio,
                    "description": (
                        f"Congressional net buying: {buy_count} buys vs {sell_count} sells "
                        f"(last {len(trades)} disclosures)"
                    ),
                }
            elif buy_ratio < 0.4:
                signals["uw_congress"] = {
                    "direction": "bearish",
                    "confidence": round(0.3 + (1 - buy_ratio) * 0.35, 3),
                    "value": buy_ratio,
                    "description": (
                        f"Congressional net selling: {sell_count} sells vs {buy_count} buys "
                        f"(last {len(trades)} disclosures)"
                    ),
                }
            else:
                signals["uw_congress"] = {
                    "direction": "neutral",
                    "confidence": 0.2,
                    "value": buy_ratio,
                    "description": f"Balanced congressional activity ({buy_count} buys, {sell_count} sells)",
                }
        else:
            signals["uw_congress"] = _neutral_signal("uw_congress", "No buy/sell actions in recent trades")

        # Surface any late filers (possible signal of upcoming undisclosed activity)
        late = congress.get("late_filings") or []
        if late:
            signals["uw_congress_late_filings"] = {
                "direction": "neutral",
                "confidence": 0.1,
                "value": len(late),
                "description": f"{len(late)} congressional member(s) with overdue trade disclosures",
            }

        return _signal_envelope(signals, available=True)

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name="unusual_whales.congress",
            node_type="signal_generator",
            version="1.0.0",
            inputs=[],
            outputs=["signals"],
            description="Congressional trading alpha signal (slow, alternative data)",
            tags=["signal", "alternative_data", "congress", "unusual_whales"],
        )
