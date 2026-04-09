"""
omega.nodes.victoria.data_providers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pluggable data provider architecture for the Victoria domain.

Abstract DataProvider interface + concrete implementations:
  BinanceProvider   — OHLCV klines, 24h tickers (existing logic extracted)
  CoinGeckoProvider — market caps, ranks, 24h change (existing logic extracted)
  BybitProvider     — OHLCV klines (alternative to Binance, same pair format)
  FearGreedProvider — Alternative.me Fear & Greed Index (crypto sentiment)
  DefiLlamaProvider — DeFi protocol TVL rankings
  CoinbaseProvider  — OHLCV candles via Coinbase Advanced Trade public API (4th-priority fallback)

All providers:
  - Zero external dependencies (urllib.request only)
  - Respectful rate limiting (time.sleep delays)
  - Return None gracefully on failure (never raise)
  - Include 1-minute TTL in-memory cache
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from omega.core.circuit_breaker import CircuitBreaker
from omega.core.degradation import get_registry as _get_registry

logger = logging.getLogger("omega.nodes.victoria.data_providers")

_CG_API_KEY = os.environ.get("CG_API_KEY")

_CACHE_TTL_SECONDS = 60  # 1 minute — fresher prices for training runs

_HEADERS = {
    "User-Agent": "OmegaVictoria/1.0 (quantitative research bot)",
    "Accept": "application/json",
}

# CoinGecko headers — includes API key when CG_API_KEY is set
_CG_HEADERS: dict[str, str] = {**_HEADERS}
if _CG_API_KEY:
    _CG_HEADERS["x-cg-demo-api-key"] = _CG_API_KEY

_BINANCE_API = "https://api.binance.com/api/v3"
_COINGECKO_API = "https://api.coingecko.com/api/v3"
_BYBIT_API = "https://api.bybit.com/v5/market"
_FEARGREED_API = "https://api.alternative.me/fng"
_DEFILLAMA_API = "https://api.llama.fi"

_COINGECKO_IDS = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
    "ADAUSDT": "cardano",
    "DOTUSDT": "polkadot",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "MATICUSDT": "matic-network",
}

_BYBIT_INTERVAL_MAP = {"1d": "D", "1h": "60", "4h": "240", "1w": "W"}


# ─── Abstract Base ─────────────────────────────────────────────────────────────


class DataProvider(ABC):
    """Abstract base for all Victoria data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g. 'binance', 'bybit')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this provider fetches."""

    @abstractmethod
    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """
        Fetch data for the given list of pairs.
        Returns dict mapping pair → data (or None for failed pairs).
        Never raises — returns empty dict on total failure.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Quick connectivity check. Returns True if provider is reachable."""

    def get_status(self) -> dict[str, Any]:
        """Return provider status for monitoring."""
        return {"name": self.name, "available": self.is_available()}


# ─── Binance Provider ──────────────────────────────────────────────────────────


class BinanceProvider(DataProvider):
    """Fetches OHLCV klines from Binance public API (no auth required)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._total_fetched = 0
        self._total_failed = 0
        self._cb = CircuitBreaker("binance", failure_threshold=3, recovery_timeout=300)

    @property
    def name(self) -> str:
        return "binance"

    @property
    def description(self) -> str:
        return "Binance public API — OHLCV klines, 24h tickers"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLCV klines from Binance (circuit-breaker guarded)."""
        cache_key = f"{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(self._fetch_klines_raw, pair, interval, limit)
            if result is not None:
                _get_registry().mark_healthy("binance")
            else:
                _get_registry().mark_degraded("binance", reason="circuit open", fallback="bybit")
            return result
        except Exception as exc:
            _get_registry().mark_degraded("binance", reason=str(exc)[:80], fallback="bybit")
            return None

    def _fetch_klines_raw(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Raw kline fetch — called by fetch_klines via circuit breaker."""
        url = f"{_BINANCE_API}/klines?symbol={pair}&interval={interval}&limit={limit}"
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))

                if not raw or not isinstance(raw, list):
                    self._total_failed += 1
                    return None

                timestamps = [int(k[0]) // 1000 for k in raw]
                opens = [float(k[1]) for k in raw]
                highs = [float(k[2]) for k in raw]
                lows = [float(k[3]) for k in raw]
                closes = [float(k[4]) for k in raw]
                volumes = [float(k[5]) for k in raw]
                quote_vols = [float(k[7]) for k in raw]

                data = {
                    "meta": {
                        "symbol": pair,
                        "interval": interval,
                        "source": "binance",
                        "regularMarketPrice": closes[-1] if closes else None,
                    },
                    "timestamps": timestamps,
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes,
                    "adjclose": closes,
                    "volume": volumes,
                    "quote_volume": quote_vols,
                    "pair": pair,
                    "fetched_at": time.time(),
                }
                self._total_fetched += 1
                cache_key = f"{pair}:{interval}:{limit}"
                self._cache[cache_key] = (time.time(), data)
                logger.debug(
                    "Binance: %s → %d bars, last=%.2f",
                    pair,
                    len(closes),
                    closes[-1] if closes else 0,
                )
                return data

            except urllib.error.HTTPError as e:
                if attempt < max_attempts - 1:
                    wait = 2**attempt
                    logger.warning("Binance HTTP %d for %s, retry in %ds", e.code, pair, wait)
                    time.sleep(wait)
                else:
                    logger.warning("Failed to fetch %s from Binance: HTTP %d", pair, e.code)
                    self._total_failed += 1
                    raise

            except Exception as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1)
                else:
                    logger.warning("Failed to fetch %s from Binance: %s", pair, exc)
                    self._total_failed += 1
                    raise

        return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch OHLCV for all given pairs."""
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 90))
        result: dict[str, Any] = {}
        for pair in pairs:
            data = self.fetch_klines(pair, interval=interval, limit=limit)
            result[pair] = data
            time.sleep(0.05)
        return result

    def is_available(self) -> bool:
        """Check if Binance API is reachable."""
        try:
            url = f"{_BINANCE_API}/ticker/price?symbol=BTCUSDT"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return "price" in data
        except Exception:
            return False


# ─── CoinGecko Provider ────────────────────────────────────────────────────────


class CoinGeckoProvider(DataProvider):
    """Fetches market data enrichment from CoinGecko public API."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker("coingecko", failure_threshold=3, recovery_timeout=300)

    @property
    def name(self) -> str:
        return "coingecko"

    @property
    def description(self) -> str:
        return "CoinGecko — market caps, rankings, 24h price change; OHLC fallback"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLC from CoinGecko /coins/{id}/ohlc (3rd-priority OHLCV fallback)."""
        cg_id = _COINGECKO_IDS.get(pair)
        if not cg_id:
            return None

        cache_key = f"cg_ohlc:{pair}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        # CoinGecko days parameter — map limit to nearest supported value
        days = 90 if limit >= 90 else (30 if limit >= 30 else 7)
        url = f"{_COINGECKO_API}/coins/{cg_id}/ohlc?vs_currency=usd&days={days}"
        try:
            req = urllib.request.Request(url, headers=_CG_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            if not raw or not isinstance(raw, list):
                return None

            # CoinGecko OHLC format: [[timestamp_ms, open, high, low, close], ...]
            # Keep only the most recent `limit` candles
            raw = raw[-limit:] if len(raw) > limit else raw

            timestamps = [int(k[0]) // 1000 for k in raw]
            opens = [float(k[1]) for k in raw]
            highs = [float(k[2]) for k in raw]
            lows = [float(k[3]) for k in raw]
            closes = [float(k[4]) for k in raw]

            data = {
                "meta": {
                    "symbol": pair,
                    "interval": interval,
                    "source": "coingecko",
                    "regularMarketPrice": closes[-1] if closes else None,
                },
                "timestamps": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "adjclose": closes,
                "volume": [0.0] * len(closes),  # CoinGecko OHLC has no volume
                "quote_volume": [0.0] * len(closes),
                "pair": pair,
                "fetched_at": time.time(),
            }
            self._cache[cache_key] = (time.time(), data)
            logger.debug(
                "CoinGecko OHLC: %s → %d bars, last=%.2f",
                pair,
                len(closes),
                closes[-1] if closes else 0,
            )
            return data

        except Exception as exc:
            logger.warning("Failed to fetch OHLC for %s from CoinGecko: %s", pair, exc)
            return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch CoinGecko market data (circuit-breaker guarded)."""
        cache_key = "bulk_markets"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return {p: data[p] for p in pairs if p in data}
        try:
            result = self._cb.call(self._fetch_raw, pairs)
            if result is not None:
                _get_registry().mark_healthy("coingecko")
                return {p: result[p] for p in pairs if p in result}
            else:
                _get_registry().mark_degraded(
                    "coingecko", reason="circuit open", fallback="cached_data"
                )
                return {}
        except Exception as exc:
            _get_registry().mark_degraded(
                "coingecko", reason=str(exc)[:80], fallback="cached_data"
            )
            return {}

    def _fetch_raw(self, pairs: list[str]) -> dict[str, Any] | None:
        """Raw CoinGecko fetch — called by fetch() via circuit breaker."""
        ids_needed = [_COINGECKO_IDS[p] for p in pairs if p in _COINGECKO_IDS]
        if not ids_needed:
            return {}

        ids_str = ",".join(ids_needed[:20])
        url = (
            f"{_COINGECKO_API}/coins/markets"
            f"?vs_currency=usd&ids={ids_str}"
            f"&order=market_cap_desc&per_page=50&page=1"
        )
        req = urllib.request.Request(url, headers=_CG_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        id_to_pair = {v: k for k, v in _COINGECKO_IDS.items()}
        result: dict[str, Any] = {}
        for coin in raw:
            cg_id = coin.get("id", "")
            pair = id_to_pair.get(cg_id)
            if pair:
                result[pair] = coin

        self._cache["bulk_markets"] = (time.time(), result)
        logger.debug("CoinGecko: %d coins enriched", len(result))
        return result

    def is_available(self) -> bool:
        """Check if CoinGecko API is reachable."""
        try:
            url = f"{_COINGECKO_API}/ping"
            req = urllib.request.Request(url, headers=_CG_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return "gecko_says" in data
        except Exception:
            return False


# ─── Bybit Provider ────────────────────────────────────────────────────────────


class BybitProvider(DataProvider):
    """Fetches OHLCV klines from Bybit public API (fallback to Binance)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._total_fetched = 0
        self._total_failed = 0

    @property
    def name(self) -> str:
        return "bybit"

    @property
    def description(self) -> str:
        return "Bybit public API — OHLCV klines (alternative exchange source)"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLCV klines from Bybit for a single pair."""
        cache_key = f"bybit:{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        bybit_interval = _BYBIT_INTERVAL_MAP.get(interval, "D")
        url = (
            f"{_BYBIT_API}/kline"
            f"?category=spot&symbol={pair}&interval={bybit_interval}&limit={limit}"
        )

        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            if raw.get("retCode") != 0:
                logger.warning("Bybit non-zero retCode for %s: %s", pair, raw.get("retMsg"))
                self._total_failed += 1
                return None

            klines = raw.get("result", {}).get("list", [])
            if not klines:
                self._total_failed += 1
                return None

            # Bybit returns newest first — reverse to chronological order
            klines = list(reversed(klines))

            # Bybit format: [timestamp_ms, open, high, low, close, volume, quote_volume]
            timestamps = [int(k[0]) // 1000 for k in klines]
            opens = [float(k[1]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            quote_vols = [float(k[6]) for k in klines]

            data = {
                "meta": {
                    "symbol": pair,
                    "interval": interval,
                    "source": "bybit",
                    "regularMarketPrice": closes[-1] if closes else None,
                },
                "timestamps": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "adjclose": closes,
                "volume": volumes,
                "quote_volume": quote_vols,
                "pair": pair,
                "fetched_at": time.time(),
            }
            self._total_fetched += 1
            self._cache[cache_key] = (time.time(), data)
            logger.debug(
                "Bybit: %s → %d bars, last=%.2f",
                pair,
                len(closes),
                closes[-1] if closes else 0,
            )
            return data

        except Exception as exc:
            logger.warning("Failed to fetch %s from Bybit: %s", pair, exc)
            self._total_failed += 1
            return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch OHLCV for all given pairs from Bybit."""
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 90))
        result: dict[str, Any] = {}
        for pair in pairs:
            data = self.fetch_klines(pair, interval=interval, limit=limit)
            result[pair] = data
            time.sleep(0.05)
        return result

    def is_available(self) -> bool:
        """Check if Bybit API is reachable."""
        try:
            url = f"{_BYBIT_API}/time"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("retCode") == 0
        except Exception:
            return False


# ─── Fear & Greed Provider ─────────────────────────────────────────────────────


class FearGreedProvider(DataProvider):
    """Fetches the Alternative.me Crypto Fear & Greed Index."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker("fear_greed", failure_threshold=3, recovery_timeout=300)

    @property
    def name(self) -> str:
        return "fear_greed"

    @property
    def description(self) -> str:
        return "Alternative.me Fear & Greed Index — crypto market sentiment (0-100)"

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch Fear & Greed Index (circuit-breaker guarded; pairs ignored)."""
        cache_key = "fear_greed_30d"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(self._fetch_raw)
            if result is not None:
                _get_registry().mark_healthy("fear_greed")
                return result
            else:
                _get_registry().mark_degraded(
                    "fear_greed", reason="circuit open", fallback="neutral_0.5"
                )
                return {}
        except Exception as exc:
            _get_registry().mark_degraded(
                "fear_greed", reason=str(exc)[:80], fallback="neutral_0.5"
            )
            return {}

    def _fetch_raw(self) -> dict[str, Any]:
        """Raw Fear & Greed fetch — called by fetch() via circuit breaker."""
        url = f"{_FEARGREED_API}/?limit=30&format=json"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        entries = raw.get("data", [])
        if not entries:
            return {}

        history = [
            {
                "value": int(e["value"]),
                "label": e["value_classification"],
                "timestamp": int(e["timestamp"]),
            }
            for e in entries
        ]

        result = {
            "fear_greed": {
                "current_value": history[0]["value"],
                "current_label": history[0]["label"],
                "history": history,
                "fetched_at": time.time(),
            }
        }
        self._cache["fear_greed_30d"] = (time.time(), result)
        logger.debug(
            "FearGreed: current=%d (%s)",
            result["fear_greed"]["current_value"],
            result["fear_greed"]["current_label"],
        )
        return result

    def is_available(self) -> bool:
        """Check if the Fear & Greed endpoint is reachable."""
        try:
            url = f"{_FEARGREED_API}/?limit=1&format=json"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("data"))
        except Exception:
            return False


# ─── DefiLlama Provider ────────────────────────────────────────────────────────


class DefiLlamaProvider(DataProvider):
    """Fetches DeFi protocol TVL rankings from DefiLlama."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cb = CircuitBreaker("defillama", failure_threshold=3, recovery_timeout=300)

    @property
    def name(self) -> str:
        return "defillama"

    @property
    def description(self) -> str:
        return "DefiLlama — DeFi protocol TVL rankings (top 20 by TVL)"

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch top 20 DeFi protocols by TVL (circuit-breaker guarded; pairs ignored)."""
        cache_key = "defi_protocols"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data
        try:
            result = self._cb.call(self._fetch_raw)
            if result is not None:
                _get_registry().mark_healthy("defillama")
                return result
            else:
                _get_registry().mark_degraded("defillama", reason="circuit open", fallback="skip")
                return {}
        except Exception as exc:
            _get_registry().mark_degraded("defillama", reason=str(exc)[:80], fallback="skip")
            return {}

    def _fetch_raw(self) -> dict[str, Any]:
        """Raw DefiLlama fetch — called by fetch() via circuit breaker."""
        url = f"{_DEFILLAMA_API}/protocols"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        if not isinstance(raw, list):
            return {}

        sorted_protocols = sorted(
            raw,
            key=lambda p: p.get("tvl") or 0,
            reverse=True,
        )[:20]

        top_protocols = [
            {
                "name": p.get("name", ""),
                "symbol": p.get("symbol", ""),
                "tvl": float(p.get("tvl") or 0),
                "chain": p.get("chain", ""),
                "category": p.get("category", ""),
            }
            for p in sorted_protocols
        ]

        total_tvl = sum(p["tvl"] for p in top_protocols)

        result = {
            "defi_tvl": {
                "top_protocols": top_protocols,
                "total_tvl": total_tvl,
                "fetched_at": time.time(),
            }
        }
        self._cache["defi_protocols"] = (time.time(), result)
        logger.debug("DefiLlama: top 20 protocols, total TVL $%,.0f", total_tvl)
        return result

    def is_available(self) -> bool:
        """Check if DefiLlama endpoint is reachable."""
        try:
            url = f"{_DEFILLAMA_API}/protocols"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return isinstance(data, list) and len(data) > 0
        except Exception:
            return False


# ─── Coinbase Provider ─────────────────────────────────────────────────────────


class CoinbaseProvider(DataProvider):
    """Fetches OHLCV candles from Coinbase Advanced Trade public API (4th-priority fallback)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._total_fetched = 0
        self._total_failed = 0

    @property
    def name(self) -> str:
        return "coinbase"

    @property
    def description(self) -> str:
        return "Coinbase Advanced Trade public candles API — OHLCV (4th-priority fallback)"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLCV candles from Coinbase Advanced Trade API for a single pair."""
        cache_key = f"cb:{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        product_id = _COINBASE_PAIRS.get(pair)
        if not product_id:
            return None

        granularity = _COINBASE_GRANULARITY.get(interval, "ONE_DAY")
        end = int(time.time())
        # Advanced Trade API accepts start/end as Unix timestamps; max 300 candles
        gran_seconds = {"ONE_DAY": 86400, "ONE_HOUR": 3600, "SIX_HOUR": 21600}.get(
            granularity, 86400
        )
        start = end - limit * gran_seconds

        url = (
            f"{_COINBASE_AT_API}/{product_id}/candles"
            f"?granularity={granularity}&start={start}&end={end}"
        )
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            # Response: {"candles": [{"start", "low", "high", "open", "close", "volume"}]}
            # Candles are newest-first; parse and reverse to oldest-first
            raw = payload.get("candles", [])
            if not raw:
                self._total_failed += 1
                return None

            raw = list(reversed(raw))[-limit:]

            timestamps = [int(k["start"]) for k in raw]
            lows = [float(k["low"]) for k in raw]
            highs = [float(k["high"]) for k in raw]
            opens = [float(k["open"]) for k in raw]
            closes = [float(k["close"]) for k in raw]
            volumes = [float(k["volume"]) for k in raw]

            data = {
                "meta": {
                    "symbol": pair,
                    "interval": interval,
                    "source": "coinbase",
                    "regularMarketPrice": closes[-1] if closes else None,
                },
                "timestamps": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "adjclose": closes,
                "volume": volumes,
                "quote_volume": [c * v for c, v in zip(closes, volumes, strict=False)],
                "pair": pair,
                "fetched_at": time.time(),
            }
            self._total_fetched += 1
            self._cache[cache_key] = (time.time(), data)
            logger.debug(
                "Coinbase: %s → %d bars, last=%.2f",
                pair,
                len(closes),
                closes[-1] if closes else 0,
            )
            return data

        except Exception as exc:
            logger.warning("Failed to fetch %s from Coinbase: %s", pair, exc)
            self._total_failed += 1
            return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 90))
        result: dict[str, Any] = {}
        for pair in pairs:
            data = self.fetch_klines(pair, interval=interval, limit=limit)
            result[pair] = data
            time.sleep(0.1)  # Coinbase public API: be gentle
        return result

    def is_available(self) -> bool:
        try:
            url = f"{_COINBASE_AT_API}/BTC-USD"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return "product_id" in data
        except Exception:
            return False


# ─── Kraken Provider ───────────────────────────────────────────────────────────


class KrakenProvider(DataProvider):
    """Fetches OHLCV klines from Kraken public API (5th-priority fallback)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._total_fetched = 0
        self._total_failed = 0

    @property
    def name(self) -> str:
        return "kraken"

    @property
    def description(self) -> str:
        return "Kraken public API — OHLCV klines (5th-priority fallback)"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLCV klines from Kraken for a single pair."""
        cache_key = f"kraken:{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        kraken_pair = _KRAKEN_PAIRS.get(pair)
        if not kraken_pair:
            return None

        kraken_interval = _KRAKEN_INTERVAL.get(interval, 1440)
        url = f"{_KRAKEN_API}/OHLC?pair={kraken_pair}&interval={kraken_interval}"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            if raw.get("error"):
                logger.warning("Kraken error for %s: %s", pair, raw["error"])
                self._total_failed += 1
                return None

            result_data = raw.get("result", {})
            # Kraken returns data under the pair key (sometimes prefixed with X/Z)
            klines = None
            for key in result_data:
                if key != "last":
                    klines = result_data[key]
                    break

            if not klines:
                self._total_failed += 1
                return None

            # Kraken format: [time, open, high, low, close, vwap, volume, count]
            klines = klines[-limit:]
            timestamps = [int(k[0]) for k in klines]
            opens = [float(k[1]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[6]) for k in klines]

            data = {
                "meta": {
                    "symbol": pair,
                    "interval": interval,
                    "source": "kraken",
                    "regularMarketPrice": closes[-1] if closes else None,
                },
                "timestamps": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "adjclose": closes,
                "volume": volumes,
                "quote_volume": [c * v for c, v in zip(closes, volumes, strict=False)],
                "pair": pair,
                "fetched_at": time.time(),
            }
            self._total_fetched += 1
            self._cache[cache_key] = (time.time(), data)
            logger.debug(
                "Kraken: %s → %d bars, last=%.2f",
                pair,
                len(closes),
                closes[-1] if closes else 0,
            )
            return data

        except Exception as exc:
            logger.warning("Failed to fetch %s from Kraken: %s", pair, exc)
            self._total_failed += 1
            return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 90))
        result: dict[str, Any] = {}
        for pair in pairs:
            data = self.fetch_klines(pair, interval=interval, limit=limit)
            result[pair] = data
            time.sleep(0.1)
        return result

    def is_available(self) -> bool:
        try:
            url = f"{_KRAKEN_API}/Time"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return not data.get("error")
        except Exception:
            return False


# ─── CryptoCompare Provider ────────────────────────────────────────────────────

# Coinbase Advanced Trade API (public market data — no auth required for candles/products)
_COINBASE_AT_API = "https://api.coinbase.com/api/v3/brokerage/market/products"
_COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")  # loaded for future auth use

_KRAKEN_API = "https://api.kraken.com/0/public"

_COINBASE_PAIRS = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
    "BNBUSDT": "BNB-USD",
    "XRPUSDT": "XRP-USD",
    "ADAUSDT": "ADA-USD",
    "DOTUSDT": "DOT-USD",
    "AVAXUSDT": "AVAX-USD",
    "LINKUSDT": "LINK-USD",
    "MATICUSDT": "MATIC-USD",
    "ATOMUSDT": "ATOM-USD",
    "NEARUSDT": "NEAR-USD",
    "LTCUSDT": "LTC-USD",
    "UNIUSDT": "UNI-USD",
    "AAVEUSDT": "AAVE-USD",
    "DOGEUSDT": "DOGE-USD",
    "TRXUSDT": "TRX-USD",
}

# Advanced Trade API uses string granularity names
_COINBASE_GRANULARITY = {"1d": "ONE_DAY", "1h": "ONE_HOUR", "4h": "SIX_HOUR", "1w": "ONE_DAY"}

_KRAKEN_PAIRS = {
    "BTCUSDT": "XBTUSD",
    "ETHUSDT": "ETHUSD",
    "SOLUSDT": "SOLUSD",
    "XRPUSDT": "XRPUSD",
    "ADAUSDT": "ADAUSD",
    "DOTUSDT": "DOTUSD",
    "AVAXUSDT": "AVAXUSD",
    "LINKUSDT": "LINKUSD",
    "ATOMUSDT": "ATOMUSD",
    "LTCUSDT": "LTCUSD",
    "UNIUSDT": "UNIUSD",
    "DOGEUSDT": "XDGUSD",
    "TRXUSDT": "TRXUSD",
    "NEARUSDT": "NEARUSD",
}

_KRAKEN_INTERVAL = {"1d": 1440, "1h": 60, "4h": 240, "1w": 10080}

_CRYPTOCOMPARE_API = "https://min-api.cryptocompare.com/data/v2"

_CRYPTOCOMPARE_SYMBOLS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "BNBUSDT": "BNB",
    "XRPUSDT": "XRP",
    "ADAUSDT": "ADA",
    "DOTUSDT": "DOT",
    "AVAXUSDT": "AVAX",
    "LINKUSDT": "LINK",
    "MATICUSDT": "MATIC",
    "ATOMUSDT": "ATOM",
    "NEARUSDT": "NEAR",
    "ALGOUSDT": "ALGO",
    "FILUSDT": "FIL",
    "LTCUSDT": "LTC",
    "UNIUSDT": "UNI",
    "AAVEUSDT": "AAVE",
    "SHIBUSDT": "SHIB",
    "TRXUSDT": "TRX",
    "DOGEUSDT": "DOGE",
}


class CryptoCompareProvider(DataProvider):
    """Fetches OHLCV daily klines from CryptoCompare public API (4th-priority fallback)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._total_fetched = 0
        self._total_failed = 0

    @property
    def name(self) -> str:
        return "cryptocompare"

    @property
    def description(self) -> str:
        return "CryptoCompare public API — daily OHLCV (4th-priority fallback)"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch daily OHLCV from CryptoCompare for a single pair."""
        cache_key = f"cc:{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        fsym = _CRYPTOCOMPARE_SYMBOLS.get(pair)
        if not fsym:
            return None

        url = f"{_CRYPTOCOMPARE_API}/histoday?fsym={fsym}&tsym=USD&limit={limit}"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            if raw.get("Response") != "Success":
                logger.warning("CryptoCompare non-success for %s: %s", pair, raw.get("Message"))
                self._total_failed += 1
                return None

            klines = raw.get("Data", {}).get("Data", [])
            if not klines:
                self._total_failed += 1
                return None

            timestamps = [int(k["time"]) for k in klines]
            opens = [float(k["open"]) for k in klines]
            highs = [float(k["high"]) for k in klines]
            lows = [float(k["low"]) for k in klines]
            closes = [float(k["close"]) for k in klines]
            volumes = [float(k["volumefrom"]) for k in klines]
            quote_vols = [float(k["volumeto"]) for k in klines]

            # Skip zero-price entries (CryptoCompare pads with zeros)
            valid = [i for i, c in enumerate(closes) if c > 0]
            if not valid:
                self._total_failed += 1
                return None
            timestamps = [timestamps[i] for i in valid]
            opens = [opens[i] for i in valid]
            highs = [highs[i] for i in valid]
            lows = [lows[i] for i in valid]
            closes = [closes[i] for i in valid]
            volumes = [volumes[i] for i in valid]
            quote_vols = [quote_vols[i] for i in valid]

            data = {
                "meta": {
                    "symbol": pair,
                    "interval": interval,
                    "source": "cryptocompare",
                    "regularMarketPrice": closes[-1] if closes else None,
                },
                "timestamps": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "adjclose": closes,
                "volume": volumes,
                "quote_volume": quote_vols,
                "pair": pair,
                "fetched_at": time.time(),
            }
            self._total_fetched += 1
            self._cache[cache_key] = (time.time(), data)
            logger.debug(
                "CryptoCompare: %s → %d bars, last=%.2f",
                pair,
                len(closes),
                closes[-1] if closes else 0,
            )
            return data

        except Exception as exc:
            logger.warning("Failed to fetch %s from CryptoCompare: %s", pair, exc)
            self._total_failed += 1
            return None

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        interval = kwargs.get("interval", "1d")
        limit = int(kwargs.get("limit", 90))
        result: dict[str, Any] = {}
        for pair in pairs:
            data = self.fetch_klines(pair, interval=interval, limit=limit)
            result[pair] = data
            time.sleep(0.1)  # CryptoCompare free tier: be gentle
        return result

    def is_available(self) -> bool:
        try:
            url = f"{_CRYPTOCOMPARE_API}/histoday?fsym=BTC&tsym=USD&limit=1"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("Response") == "Success"
        except Exception:
            return False


# ─── Provider Registry ─────────────────────────────────────────────────────────


class ProviderRegistry:
    """Registry of all available data providers."""

    def __init__(self) -> None:
        self._providers: dict[str, DataProvider] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, provider: DataProvider, enabled: bool = True) -> None:
        self._providers[provider.name] = provider
        self._enabled[provider.name] = enabled

    def get(self, name: str) -> DataProvider | None:
        return self._providers.get(name)

    def enabled_providers(self) -> list[DataProvider]:
        return [p for n, p in self._providers.items() if self._enabled.get(n, True)]

    def disable(self, name: str) -> None:
        self._enabled[name] = False

    def enable(self, name: str) -> None:
        self._enabled[name] = True

    def status(self) -> dict[str, Any]:
        return {name: {"enabled": self._enabled.get(name, True)} for name in self._providers}
