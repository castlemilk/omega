"""
omega.nodes.victoria.signals.whale_flow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Whale and smart-money flow signals sourced from free public APIs.

Three signals are computed per call:

exchange_net_flow:
    DefiLlama bridges API → net USD value flowing to/from centralised exchanges
    in the last 24h.  Inflow spike = sell pressure (bearish); outflow = bullish.
    Cache TTL: 15 minutes.

stablecoin_velocity:
    DefiLlama stablecoins API → 24h change in total stablecoin supply across
    chains.  Minting = new buying power entering crypto (bullish); burning = exit.
    Cache TTL: 15 minutes.

oi_rate_of_change:
    OKX /api/v5/public/open-interest (no key required) → percentage change in
    open interest since last reading.  Rising OI + flat price = squeeze setup.
    Tracked as 3-reading derivative.

All three signals are normalised to [-1, +1] and degrade to 0.0 on any API
failure (network unavailable, rate-limited, malformed response).

DefiLlama endpoints (no auth required):
    https://bridges.llama.fi/bridges            # bridge volume list
    https://stablecoins.llama.fi/stablecoins    # stablecoin supply list

OKX open interest (no auth required):
    https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={sym}-USDT-SWAP
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger("omega.nodes.victoria.signals.whale_flow")

_DEFILLAMA_BRIDGES_URL = "https://bridges.llama.fi/bridgevolume/all?id=1"
_DEFILLAMA_STABLES_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"
_OKX_OI_URL = "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={sym}-SWAP"

_CACHE_TTL = 900.0   # 15 minutes
_HTTP_TIMEOUT = 8.0  # seconds


# ---------------------------------------------------------------------------
# Small JSON-fetch helper (no extra deps)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> Any | None:
    """GET *url*, parse JSON, return parsed object or None on any error."""
    try:
        import json
        with urlopen(url, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, ValueError, Exception) as exc:
        logger.debug("whale_flow: fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# WhaleFlowSignals
# ---------------------------------------------------------------------------

class WhaleFlowSignals:
    """
    Whale and smart-money flow signals from DefiLlama + OKX.

    Usage::

        wfs = WhaleFlowSignals()
        exchange_flow = wfs.get_exchange_net_flow("BTCUSDT")
        stable_vel    = wfs.get_stablecoin_velocity()
        oi_roc        = wfs.get_oi_rate_of_change("ETHUSDT")
    """

    def __init__(self) -> None:
        # Bridge-volume cache
        self._bridge_cache: tuple[float, float] | None = None  # (timestamp, net_flow_signal)
        self._bridge_cache_ts: float = 0.0
        # Stablecoin cache
        self._stable_cache_ts: float = 0.0
        self._stable_signal: float = 0.0
        self._stable_prev_supply: float | None = None
        # OI per symbol: deque of (timestamp, oi_value) for derivative
        self._oi_history: dict[str, deque] = {}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_exchange_net_flow(self, symbol: str = "BTCUSDT") -> float:
        """
        Net exchange flow signal in [-1, +1].

        Positive = net outflow (coins leaving exchanges = bullish).
        Negative = net inflow (coins being deposited = bearish sell pressure).

        Uses DefiLlama bridge-volume endpoint as a proxy for exchange net flow.
        The 24h USD volume of inbound vs outbound bridges across major CEX-
        connected chains is the most accessible free approximation of on-chain
        flow data.  Symbol parameter is accepted for API compatibility but the
        signal is cross-chain (all-asset) so it applies to any crypto.
        """
        now = time.time()
        if now - self._bridge_cache_ts < _CACHE_TTL and self._bridge_cache is not None:
            return self._bridge_cache[1]

        signal = self._fetch_bridge_signal()
        self._bridge_cache = (now, signal)
        self._bridge_cache_ts = now
        return signal

    def get_stablecoin_velocity(self) -> float:
        """
        Stablecoin supply velocity signal in [-1, +1].

        Positive = stablecoin supply growing (new fiat entering crypto = bullish).
        Negative = stablecoin supply shrinking (fiat leaving crypto = bearish).

        Computed as a z-score of the 24h supply change vs recent history.
        """
        now = time.time()
        if now - self._stable_cache_ts < _CACHE_TTL:
            return self._stable_signal

        signal = self._fetch_stable_signal()
        self._stable_signal = signal
        self._stable_cache_ts = now
        return signal

    def get_oi_rate_of_change(self, symbol: str) -> float:
        """
        Open interest rate of change in [-1, +1] for *symbol*.

        Positive = OI rising (new positions being added = directional conviction).
        Negative = OI falling (positions being closed = trend exhaustion).

        OI rising while price is flat → squeeze setup.
        OI rising while price rises → confirmed trend.
        OI falling while price rises → divergence / caution.

        Uses OKX public SWAP open interest (no API key required).
        Tracks the last 3 readings and returns the derivative (pct change/reading).
        """
        sym = symbol.upper().replace("USDT", "")
        history = self._oi_history.setdefault(sym, deque(maxlen=3))

        raw_oi = self._fetch_okx_oi(sym)
        if raw_oi is None:
            return 0.0

        history.append((time.time(), raw_oi))
        if len(history) < 2:
            return 0.0

        vals = [v for _, v in history]
        pct_changes = [
            (vals[i] - vals[i - 1]) / vals[i - 1]
            for i in range(1, len(vals))
            if vals[i - 1] != 0
        ]
        if not pct_changes:
            return 0.0

        avg_pct = sum(pct_changes) / len(pct_changes)
        # Scale: ±2% per-reading → ±1 signal
        return max(-1.0, min(1.0, avg_pct / 0.02))

    def compute_all(self, symbol: str) -> dict[str, float]:
        """Return all three whale-flow signals for *symbol*."""
        return {
            "exchange_net_flow": self.get_exchange_net_flow(symbol),
            "stablecoin_velocity": self.get_stablecoin_velocity(),
            "oi_rate_of_change": self.get_oi_rate_of_change(symbol),
        }

    # ------------------------------------------------------------------
    # Private fetch helpers
    # ------------------------------------------------------------------

    def _fetch_bridge_signal(self) -> float:
        """
        DefiLlama bridgevolume endpoint → net flow signal.

        The endpoint returns daily inbound/outbound USD volumes.  We use the
        most recent data point's (volumeIn - volumeOut) / (volumeIn + volumeOut)
        as a proxy for exchange net flow direction.
        """
        data = _fetch_json(_DEFILLAMA_BRIDGES_URL)
        if not data or not isinstance(data, list):
            return 0.0

        try:
            # Each entry: {"date": "YYYY-MM-DD", "depositUSD": ..., "withdrawUSD": ...}
            # or {"date": <unix_ts>, "totalTokensDepositedUsd": ..., "totalTokensWithdrawnUsd": ...}
            recent = sorted(data, key=lambda x: x.get("date", 0), reverse=True)
            for entry in recent[:3]:
                in_usd = float(
                    entry.get("depositUSD")
                    or entry.get("totalTokensDepositedUsd")
                    or entry.get("volumeIn", 0)
                    or 0
                )
                out_usd = float(
                    entry.get("withdrawUSD")
                    or entry.get("totalTokensWithdrawnUsd")
                    or entry.get("volumeOut", 0)
                    or 0
                )
                total = in_usd + out_usd
                if total <= 0:
                    continue
                # Net outflow (more withdrawals than deposits) = bullish (+)
                # Net inflow (more deposits than withdrawals) = bearish (-)
                net = (out_usd - in_usd) / total
                return max(-1.0, min(1.0, net * 3.0))  # scale: typical imbalance is ~10-30%
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("whale_flow: bridge parse error: %s", exc)
        return 0.0

    def _fetch_stable_signal(self) -> float:
        """
        DefiLlama stablecoins → 24h supply change signal.

        Sums circulatingUSD across all stablecoins and computes the % change
        vs the previous reading.  Result is clamped to [-1, +1].
        """
        data = _fetch_json(_DEFILLAMA_STABLES_URL)
        if not data:
            return 0.0

        try:
            stables = data.get("peggedAssets") if isinstance(data, dict) else data
            if not isinstance(stables, list):
                return 0.0

            total = 0.0
            for s in stables:
                circ = s.get("circulating") or s.get("circulatingPeggedUSD") or {}
                if isinstance(circ, dict):
                    val = circ.get("peggedUSD") or circ.get("peggedEUR") or 0
                elif isinstance(circ, (int, float)):
                    val = circ
                else:
                    val = 0
                total += float(val or 0)

            if total == 0.0:
                return 0.0

            prev = self._stable_prev_supply
            self._stable_prev_supply = total
            if prev is None or prev == 0.0:
                return 0.0

            pct = (total - prev) / prev
            # Scale: ±0.5% change in total stablecoin supply = ±1 signal
            return max(-1.0, min(1.0, pct / 0.005))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("whale_flow: stablecoin parse error: %s", exc)
        return 0.0

    def _fetch_okx_oi(self, base_sym: str) -> float | None:
        """
        Fetch OKX perpetual swap open interest (USD-denominated) for *base_sym*.

        OKX instId format: BTC-USDT-SWAP, ETH-USDT-SWAP, etc.
        """
        inst_id = f"{base_sym}-USDT-SWAP"
        url = f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst_id}"
        data = _fetch_json(url)
        if not data:
            return None
        try:
            items = data.get("data", [])
            if not items:
                return None
            oi_usd = float(items[0].get("oiCcy") or items[0].get("oi") or 0)
            return oi_usd if oi_usd > 0 else None
        except (KeyError, ValueError, TypeError, IndexError):
            return None
