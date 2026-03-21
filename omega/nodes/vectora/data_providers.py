"""
omega.nodes.vectora.data_providers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pluggable data provider architecture for the Vectora domain.

Abstract DataProvider interface + concrete implementations:
  BinanceProvider   — OHLCV klines, 24h tickers (existing logic extracted)
  CoinGeckoProvider — market caps, ranks, 24h change (existing logic extracted)
  BybitProvider     — OHLCV klines (alternative to Binance, same pair format)
  FearGreedProvider — Alternative.me Fear & Greed Index (crypto sentiment)
  DefiLlamaProvider — DeFi protocol TVL rankings

All providers:
  - Zero external dependencies (urllib.request only)
  - Respectful rate limiting (time.sleep delays)
  - Return None gracefully on failure (never raise)
  - Include 5-minute TTL in-memory cache
"""

import json
import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("omega.nodes.vectora.data_providers")

_CACHE_TTL_SECONDS = 300  # 5 minutes

_HEADERS = {
    "User-Agent": "OmegaVectora/1.0 (quantitative research bot)",
    "Accept": "application/json",
}

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
    """Abstract base for all Vectora data providers."""

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

    @property
    def name(self) -> str:
        return "binance"

    @property
    def description(self) -> str:
        return "Binance public API — OHLCV klines, 24h tickers"

    def fetch_klines(
        self, pair: str, interval: str = "1d", limit: int = 90
    ) -> dict[str, Any] | None:
        """Fetch OHLCV klines from Binance for a single pair."""
        cache_key = f"{pair}:{interval}:{limit}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

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
                    return None

            except Exception as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1)
                else:
                    logger.warning("Failed to fetch %s from Binance: %s", pair, exc)
                    self._total_failed += 1
                    return None

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

    @property
    def name(self) -> str:
        return "coingecko"

    @property
    def description(self) -> str:
        return "CoinGecko — market caps, rankings, 24h price change"

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch CoinGecko market data for given pairs."""
        cache_key = "bulk_markets"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                # Filter to only the requested pairs
                return {p: data[p] for p in pairs if p in data}

        ids_needed = [_COINGECKO_IDS[p] for p in pairs if p in _COINGECKO_IDS]
        if not ids_needed:
            return {}

        ids_str = ",".join(ids_needed[:20])
        url = (
            f"{_COINGECKO_API}/coins/markets"
            f"?vs_currency=usd&ids={ids_str}"
            f"&order=market_cap_desc&per_page=50&page=1"
        )
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            id_to_pair = {v: k for k, v in _COINGECKO_IDS.items()}
            result: dict[str, Any] = {}
            for coin in raw:
                cg_id = coin.get("id", "")
                pair = id_to_pair.get(cg_id)
                if pair:
                    result[pair] = coin

            self._cache[cache_key] = (time.time(), result)
            logger.debug("CoinGecko: %d coins enriched", len(result))
            return {p: result[p] for p in pairs if p in result}

        except Exception as exc:
            logger.warning("CoinGecko fetch failed: %s", exc)
            return {}

    def is_available(self) -> bool:
        """Check if CoinGecko API is reachable."""
        try:
            url = f"{_COINGECKO_API}/ping"
            req = urllib.request.Request(url, headers=_HEADERS)
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

    @property
    def name(self) -> str:
        return "fear_greed"

    @property
    def description(self) -> str:
        return "Alternative.me Fear & Greed Index — crypto market sentiment (0-100)"

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch the Fear & Greed Index (pairs is ignored — market-wide index)."""
        cache_key = "fear_greed_30d"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        url = f"{_FEARGREED_API}/?limit=30&format=json"
        try:
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
            self._cache[cache_key] = (time.time(), result)
            logger.debug(
                "FearGreed: current=%d (%s)",
                result["fear_greed"]["current_value"],
                result["fear_greed"]["current_label"],
            )
            return result

        except Exception as exc:
            logger.warning("FearGreed fetch failed: %s", exc)
            return {}

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

    @property
    def name(self) -> str:
        return "defillama"

    @property
    def description(self) -> str:
        return "DefiLlama — DeFi protocol TVL rankings (top 20 by TVL)"

    def fetch(self, pairs: list[str], **kwargs) -> dict[str, Any]:
        """Fetch top 20 DeFi protocols by TVL (pairs is ignored)."""
        cache_key = "defi_protocols"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return data

        url = f"{_DEFILLAMA_API}/protocols"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            if not isinstance(raw, list):
                return {}

            # Sort by TVL descending, take top 20
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
            self._cache[cache_key] = (time.time(), result)
            logger.debug("DefiLlama: top 20 protocols, total TVL $%,.0f", total_tvl)
            return result

        except Exception as exc:
            logger.warning("DefiLlama fetch failed: %s", exc)
            return {}

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
