"""
omega.nodes.victoria.market_data_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
MarketDataSignal — on-chain / market-structure signals sourced from
ErcinDedeoglu/crypto-market-data (GitHub raw JSON files).

Metrics fetched:
  A. mvrv.json            — MVRV ratio (>3.7 overvalued/bear, <1.0 undervalued/bull)
  B. puell-multiple.json  — Mining profitability (>4 bear, <0.5 bull)
  C. exchange-netflow.json — Net BTC exchange flow (positive = bear, negative = bull)
  D. taker-buy-sell-ratio.json — Aggression ratio (>1.05 bull, <0.95 bear)
  E. coinbase-premium.json — US institutional demand (positive = bull, negative = bear)

Composite signal: weighted average of sub-signals with adaptive confidence.
Cache TTL: 15 minutes (repo updates every few hours).
"""

from __future__ import annotations

import logging
import time
import urllib.request
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.market_data_signals")

_BASE_URL = "https://raw.githubusercontent.com/ErcinDedeoglu/crypto-market-data/main/data/daily/"
_CACHE_TTL = 900  # 15 minutes


class MarketDataSignal:
    """
    Fetches on-chain / market-structure data from ErcinDedeoglu/crypto-market-data
    and computes a composite directional signal.

    Sub-signals:
      mvrv            : Market Value to Realized Value ratio
      puell_multiple  : Mining revenue / 365d MA of mining revenue
      exchange_netflow: Net BTC flowing to/from exchanges
      taker_ratio     : Taker buy volume / taker sell volume
      coinbase_premium: Coinbase price vs Binance price premium
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}  # metric_name -> (timestamp, data)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """Fetch metrics and return composite SignalValue."""
        sub_signals: dict[str, float] = {}
        raw: dict[str, float] = {}

        # A. MVRV
        mvrv_raw, mvrv_score = self._mvrv_signal()
        raw["mvrv_raw"] = mvrv_raw if mvrv_raw is not None else 0.0
        if mvrv_score is not None:
            sub_signals["mvrv"] = mvrv_score
            raw["mvrv"] = mvrv_score

        # B. Puell Multiple
        puell_raw, puell_score = self._puell_signal()
        raw["puell_raw"] = puell_raw if puell_raw is not None else 0.0
        if puell_score is not None:
            sub_signals["puell_multiple"] = puell_score
            raw["puell_multiple"] = puell_score

        # C. Exchange Net Flow
        netflow_raw, netflow_score = self._netflow_signal()
        raw["netflow_raw"] = netflow_raw if netflow_raw is not None else 0.0
        if netflow_score is not None:
            sub_signals["exchange_netflow"] = netflow_score
            raw["exchange_netflow"] = netflow_score

        # D. Taker Buy/Sell Ratio
        taker_raw, taker_score = self._taker_signal()
        raw["taker_raw"] = taker_raw if taker_raw is not None else 0.0
        if taker_score is not None:
            sub_signals["taker_ratio"] = taker_score
            raw["taker_ratio"] = taker_score

        # E. Coinbase Premium
        premium_raw, premium_score = self._coinbase_premium_signal()
        raw["coinbase_premium_raw"] = premium_raw if premium_raw is not None else 0.0
        if premium_score is not None:
            sub_signals["coinbase_premium"] = premium_score
            raw["coinbase_premium"] = premium_score

        if not sub_signals:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="data_unavailable",
                raw=raw,
            )

        # Composite: equal-weight average
        composite = sum(sub_signals.values()) / len(sub_signals)
        composite = max(-1.0, min(1.0, composite))

        # Confidence: fraction of sub-signals available x signal agreement
        coverage = len(sub_signals) / 5.0
        values = list(sub_signals.values())
        mean_val = sum(values) / len(values)
        agreement = 1.0 - (sum(abs(v - mean_val) for v in values) / (len(values) * 2.0))
        confidence = min(1.0, coverage * 0.6 + agreement * 0.4)

        # Regime tagging
        if composite > 0.3:
            regime = "on_chain_bullish"
        elif composite < -0.3:
            regime = "on_chain_bearish"
        else:
            regime = "on_chain_neutral"

        raw["composite"] = composite
        raw["coverage"] = coverage
        raw["agreement"] = agreement
        raw["sub_signal_count"] = float(len(sub_signals))

        logger.debug(
            "market_data_signal: composite=%.3f confidence=%.3f regime=%s sub_signals=%s",
            composite,
            confidence,
            regime,
            list(sub_signals.keys()),
        )
        return SignalValue(
            value=composite,
            confidence=confidence,
            regime_tag=regime,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Sub-signal computations
    # ------------------------------------------------------------------

    def _mvrv_signal(self) -> tuple[float | None, float | None]:
        """MVRV ratio → (raw_value, directional_score [-1, +1])."""
        data = self._fetch("btc_mvrv_ratio.json")
        if data is None:
            return None, None
        value = self._latest_value(data)
        if value is None:
            return None, None
        # >3.7 = overvalued/bearish, <1.0 = undervalued/bullish
        if value > 3.7:
            score = -1.0
        elif value < 1.0:
            score = 1.0
        else:
            score = 1.0 - 2.0 * (value - 1.0) / (3.7 - 1.0)
        return value, score

    def _puell_signal(self) -> tuple[float | None, float | None]:
        """Puell Multiple → (raw_value, directional_score [-1, +1])."""
        data = self._fetch("btc_puell_multiple.json")
        if data is None:
            return None, None
        value = self._latest_value(data)
        if value is None:
            return None, None
        # >4 = bearish (miners selling heavily), <0.5 = bullish (miner stress bottom)
        if value > 4.0:
            score = -1.0
        elif value < 0.5:
            score = 1.0
        else:
            score = 1.0 - 2.0 * (value - 0.5) / (4.0 - 0.5)
        return value, score

    def _netflow_signal(self) -> tuple[float | None, float | None]:
        """Exchange net flow → (raw_value, directional_score [-1, +1])."""
        data = self._fetch("btc_exchange_netflow.json")
        if data is None:
            return None, None
        value = self._latest_value(data)
        if value is None:
            return None, None
        # Positive = coins flowing TO exchanges (selling pressure) = bearish
        # Negative = coins leaving exchanges (accumulation) = bullish
        # Normalise around typical range of ±5000 BTC
        score = max(-1.0, min(1.0, -value / 5000.0))
        return value, score

    def _taker_signal(self) -> tuple[float | None, float | None]:
        """Taker buy/sell ratio → (raw_value, directional_score [-1, +1])."""
        data = self._fetch("btc_taker_buy_sell_ratio.json")
        if data is None:
            return None, None
        value = self._latest_value(data)
        if value is None:
            return None, None
        # >1.05 = bullish aggression, <0.95 = bearish aggression
        if value > 1.05:
            score = min(1.0, (value - 1.0) * 10.0)
        elif value < 0.95:
            score = max(-1.0, (value - 1.0) * 10.0)
        else:
            score = 0.0
        return value, score

    def _coinbase_premium_signal(self) -> tuple[float | None, float | None]:
        """Coinbase premium → (raw_value, directional_score [-1, +1])."""
        data = self._fetch("btc_coinbase_premium_index.json")
        if data is None:
            return None, None
        value = self._latest_value(data)
        if value is None:
            return None, None
        # Positive = US buyers paying premium = bullish institutional demand
        # Normalise around ±0.5% range
        score = max(-1.0, min(1.0, value / 0.5))
        return value, score

    # ------------------------------------------------------------------
    # Fetch + cache helpers
    # ------------------------------------------------------------------

    def _fetch(self, filename: str) -> Any:
        """Fetch a JSON file from the data repo with 15-minute caching."""
        now = time.time()
        if filename in self._cache:
            cached_ts, cached_data = self._cache[filename]
            if now - cached_ts < _CACHE_TTL:
                return cached_data

        url = _BASE_URL + filename
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-signal/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                import json

                data = json.loads(resp.read().decode())
                self._cache[filename] = (now, data)
                return data
        except Exception as exc:
            logger.debug("Failed to fetch %s: %s", filename, exc)
            # Return stale cache if available, even if expired
            if filename in self._cache:
                _, stale = self._cache[filename]
                return stale
            return None

    def _latest_value(self, data: Any) -> float | None:
        """Extract the most recent numeric value from various JSON shapes.

        ErcinDedeoglu format: {"data": [{"timestamp": ms, "value": float, ...}]}
        """
        if data is None:
            return None

        # Primary shape: top-level dict with "data" list of {timestamp, value}
        if isinstance(data, dict) and "data" in data:
            records = data["data"]
            if isinstance(records, list) and records:
                last = records[-1]
                if isinstance(last, dict) and "value" in last:
                    v = last["value"]
                    if isinstance(v, (int, float)):
                        return float(v)

        # Fallback: raw list
        if isinstance(data, list) and data:
            last = data[-1]
            if isinstance(last, dict):
                for key in ("value", "v", "price", "close"):
                    if key in last and isinstance(last[key], (int, float)):
                        return float(last[key])
            elif isinstance(last, (int, float)):
                return float(last)

        # Fallback: dict with direct value
        if isinstance(data, dict):
            for key in ("value", "current", "latest"):
                if key in data and isinstance(data[key], (int, float)):
                    return float(data[key])

        return None
