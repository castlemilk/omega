"""
omega.nodes.victoria.carry_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FundingCarrySignal — harvest carry from perpetual futures funding rates.

Crypto perpetual futures pay/receive funding every 8 hours.  When funding is
positive (longs pay shorts) going short-perp + long-spot harvests carry.
Extreme positive funding is also a contrarian mean-reversion signal: crowded
longs predict reversals.

Source: Binance Futures public API (no auth required).
Cache TTL: 15 minutes (funding updates every 8h).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.carry_signals")

_BINANCE_FUTURES_BASE = "https://fapi.binance.com"
_CACHE_TTL = 900  # 15 minutes

# APY thresholds (annualised: funding_rate * 3 * 365)
_APY_STRONG = 0.20  # >20% APY — strong signal
_APY_MODERATE = 0.10  # >10% APY — moderate signal


class FundingCarrySignal:
    """
    Funding-rate carry signal for BTC perpetual futures.

    Annualised carry = funding_rate * 3 * 365  (3 payments per day × 365 days).

    Signal logic (mean-reversion / carry harvesting):
      carry > 20% APY  → SHORT  (-0.8): longs paying too much, crowded long
      carry > 10% APY  → SHORT  (-0.4)
      carry < -20% APY → LONG   (+0.8): shorts paying too much, crowded short
      carry < -10% APY → LONG   (+0.4)
      otherwise        → 0.0 (neutral)

    Confidence scales linearly with |annualised carry|, capped at 1.0.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """Return a SignalValue based on the current BTC funding rate."""
        funding_rate = self._get_funding_rate(market_data)

        if funding_rate is None:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_data",
                raw={"funding_rate": 0.0, "annualized": 0.0},
            )

        annualized = funding_rate * 3 * 365

        if annualized > _APY_STRONG:
            value = -0.8
            regime_tag = "crowded_long"
        elif annualized > _APY_MODERATE:
            value = -0.4
            regime_tag = "elevated_funding"
        elif annualized < -_APY_STRONG:
            value = 0.8
            regime_tag = "crowded_short"
        elif annualized < -_APY_MODERATE:
            value = 0.4
            regime_tag = "negative_funding"
        else:
            value = 0.0
            regime_tag = "carry_neutral"

        confidence = min(abs(annualized) * 5, 1.0)

        logger.debug(
            "carry_signal: funding=%.6f annualized=%.4f value=%.2f conf=%.2f regime=%s",
            funding_rate,
            annualized,
            value,
            confidence,
            regime_tag,
        )

        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw={"funding_rate": funding_rate, "annualized": annualized},
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_funding_rate(self, market_data: dict[str, Any] | None) -> float | None:
        """Return the latest BTC funding rate, preferring injected market_data."""
        if market_data:
            # Accept pre-fetched value from derivatives_signals / data_ingestion
            rate = market_data.get("funding_rate") or market_data.get("funding_rate_latest")
            if rate is not None:
                try:
                    return float(rate)
                except (TypeError, ValueError):
                    pass

        # Fall back to live Binance fetch
        data = self._fetch(
            "/fapi/v1/fundingRate",
            {"symbol": "BTCUSDT", "limit": "2"},
        )
        if not data or not isinstance(data, list):
            return None
        try:
            return float(data[-1].get("fundingRate", 0))
        except (IndexError, TypeError, ValueError):
            return None

    def _fetch(self, endpoint: str, params: dict[str, str]) -> Any:
        """Fetch from Binance Futures with 15-minute caching."""
        cache_key = endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
        now = time.time()

        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if now - ts < _CACHE_TTL:
                return cached

        url = _BINANCE_FUTURES_BASE + endpoint + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-signal/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                self._cache[cache_key] = (now, data)
                return data
        except Exception as exc:
            logger.debug("FundingCarrySignal fetch failed %s: %s", endpoint, exc)
            if cache_key in self._cache:
                _, stale = self._cache[cache_key]
                return stale
            return None
