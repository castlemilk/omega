"""
omega.core.data_resilience
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Multi-provider failover with exponential backoff circuit breakers and stale
data detection for Victoria market data.

Provider priority for OHLCV price data (per pair):
    1. Binance       — primary exchange, most liquidity
    2. Bybit         — tier-1 fallback, same pair format
    3. CoinGecko     — public API fallback, slower rate limits
    4. Coinbase      — Coinbase Exchange public candles API
    5. Kraken        — Kraken public OHLC API
    6. CryptoCompare — last-resort fallback, daily-only

Circuit breaker schedule (per provider):
    3 consecutive failures → open for 30s  (trip 1)
    6 consecutive failures → open for 60s  (trip 2)
    9+ consecutive failures → open for 120s (trip 3+)

Stale data detection:
    If latest price ``fetched_at`` is older than 5 minutes → confidence = 0.0
    Stale signals are excluded from Ring 1 evaluation and strategy execution.

Health dashboard:
    ``DataResilienceLayer.get_health_status()`` returns per-provider status dict
    suitable for the /api/v1/provider-health dashboard endpoint.

Usage::

    layer = DataResilienceLayer()
    data = layer.fetch_with_failover(pairs, interval="1d", limit=90)
    signals = compute_signals(data)
    signals = layer.apply_staleness_filter(signals, data)
    health = layer.get_health_status()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.core.data_resilience")

# Stale data threshold: 5 minutes
_STALE_THRESHOLD_SECONDS = 300.0

# Exponential backoff schedule (seconds) indexed by trip count (0-based)
_BACKOFF_SCHEDULE = [30.0, 60.0, 120.0]

# Minimum consecutive failures to open a circuit
_FAILURE_THRESHOLD = 3


# ─── Circuit Breaker with Exponential Backoff ──────────────────────────────────


@dataclass
class _ProviderHealth:
    """Mutable health state tracked per provider."""

    name: str
    state: str = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
    failure_count: int = 0  # consecutive failures in current window
    trip_count: int = 0  # how many times circuit has opened
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    error_count: int = 0  # total lifetime errors
    success_count: int = 0  # total lifetime successes
    last_error: str = ""

    def backoff_seconds(self) -> float:
        idx = min(self.trip_count - 1, len(_BACKOFF_SCHEDULE) - 1)
        return _BACKOFF_SCHEDULE[max(0, idx)]

    def is_callable(self) -> bool:
        """Return True if the circuit allows a call right now."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.backoff_seconds():
                self.state = "HALF_OPEN"
                logger.info(
                    "DataResilience[%s]: OPEN → HALF_OPEN (backoff=%.0fs elapsed)",
                    self.name,
                    self.backoff_seconds(),
                )
                return True
            return False
        # HALF_OPEN: allow one probe call
        return True

    def record_success(self) -> None:
        self.success_count += 1
        self.last_success_time = time.time()
        if self.state in ("HALF_OPEN", "OPEN"):
            logger.info("DataResilience[%s]: recovered → CLOSED", self.name)
            self.state = "CLOSED"
            self.failure_count = 0

    def record_failure(self, error: str) -> None:
        self.error_count += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.last_error = error[:120]
        if self.failure_count >= _FAILURE_THRESHOLD:
            was_open = self.state == "OPEN"
            if not was_open:
                self.trip_count += 1
                logger.warning(
                    "DataResilience[%s]: OPENED (trip=%d, backoff=%.0fs, failures=%d, err=%s)",
                    self.name,
                    self.trip_count,
                    self.backoff_seconds(),
                    self.failure_count,
                    error[:60],
                )
            self.state = "OPEN"

    def status_dict(self) -> dict[str, Any]:
        now = time.time()
        return {
            "name": self.name,
            "state": self.state,
            "trip_count": self.trip_count,
            "failure_count": self.failure_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "last_error": self.last_error,
            "last_success_ago_s": (
                round(now - self.last_success_time, 1) if self.last_success_time else None
            ),
            "last_failure_ago_s": (
                round(now - self.last_failure_time, 1) if self.last_failure_time else None
            ),
            "backoff_s": self.backoff_seconds() if self.state == "OPEN" else None,
            "remaining_backoff_s": (
                round(
                    max(0.0, self.backoff_seconds() - (now - self.last_failure_time)),
                    1,
                )
                if self.state == "OPEN"
                else None
            ),
        }


# ─── DataResilienceLayer ───────────────────────────────────────────────────────


class DataResilienceLayer:
    """
    Orchestrates multi-provider failover with exponential-backoff circuit breakers.

    Providers are tried in priority order (Binance → Bybit → CoinGecko →
    CryptoCompare) for each pair.  A provider that is OPEN is skipped instantly;
    a partial result from a higher-priority provider is kept even when the
    lower-priority provider would have succeeded.

    Thread-safety: not thread-safe by design — Victoria runs single-threaded.
    """

    def __init__(self) -> None:
        # Lazy imports to avoid circular deps; providers live in data_providers
        from omega.nodes.victoria.data_providers import (
            BinanceProvider,
            BybitProvider,
            CoinbaseProvider,
            CoinGeckoProvider,
            CryptoCompareProvider,
            KrakenProvider,
        )

        self._binance = BinanceProvider()
        self._bybit = BybitProvider()
        self._coingecko = CoinGeckoProvider()
        self._coinbase = CoinbaseProvider()
        self._kraken = KrakenProvider()
        self._cryptocompare = CryptoCompareProvider()

        # Health state per provider (ordered priority)
        self._health: dict[str, _ProviderHealth] = {
            "binance": _ProviderHealth("binance"),
            "bybit": _ProviderHealth("bybit"),
            "coingecko": _ProviderHealth("coingecko"),
            "coinbase": _ProviderHealth("coinbase"),
            "kraken": _ProviderHealth("kraken"),
            "cryptocompare": _ProviderHealth("cryptocompare"),
        }

        # Track per-pair last successful fetch timestamp for staleness detection
        self._last_fetched_at: dict[str, float] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def fetch_with_failover(
        self,
        pairs: list[str],
        interval: str = "1d",
        limit: int = 90,
    ) -> dict[str, Any]:
        """
        Fetch OHLCV for all pairs with sequential provider failover.

        For each pair: Binance → Bybit → CoinGecko → Coinbase → Kraken → CryptoCompare.
        Returns a dict mapping pair → data (or None if all providers failed).
        Updates per-pair ``_last_fetched_at`` for staleness tracking.
        """
        result: dict[str, Any] = {}

        for pair in pairs:
            data = self._fetch_pair_with_failover(pair, interval, limit)
            result[pair] = data
            if data is not None:
                self._last_fetched_at[pair] = data.get("fetched_at", time.time())
            time.sleep(0.05)

        return result

    def apply_staleness_filter(
        self,
        signals: dict[str, Any],
        market_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Zero-out confidence for signals derived from stale market data.

        A signal is stale if ALL its underlying pairs have data older than
        ``_STALE_THRESHOLD_SECONDS``.  If any pair is fresh the signal keeps
        its confidence (partial data is better than nothing).

        Modifies *signals* in-place and returns it.
        """
        stale_pairs = self._detect_stale_pairs(market_data)
        if not stale_pairs:
            return signals

        # Determine which pairs have fresh data
        all_pairs = {k for k in market_data if not k.startswith("_") and market_data[k]}
        fresh_pairs = all_pairs - stale_pairs

        if fresh_pairs:
            # At least one fresh pair — keep signals but log a warning
            logger.warning(
                "DataResilience: %d/%d pairs are stale (>%.0fs): %s",
                len(stale_pairs),
                len(all_pairs),
                _STALE_THRESHOLD_SECONDS,
                sorted(stale_pairs),
            )
            return signals

        # All pairs stale — zero out confidence across all signals
        logger.error(
            "DataResilience: ALL %d pairs stale — zeroing signal confidence",
            len(all_pairs),
        )
        for _sig_name, sig_val in signals.items():
            if (isinstance(sig_val, dict) and "confidence" in sig_val) or isinstance(
                sig_val, dict
            ):
                sig_val["confidence"] = 0.0
                sig_val["stale"] = True

        return signals

    def is_data_stale(self, market_data: dict[str, Any]) -> bool:
        """
        Return True if ALL non-supplementary pairs in market_data are stale.

        Use this to gate strategy execution: if True, skip order generation.
        """
        pairs = {k for k in market_data if not k.startswith("_") and market_data[k]}
        if not pairs:
            return True
        stale = self._detect_stale_pairs(market_data)
        return len(stale) >= len(pairs)

    def get_health_status(self) -> dict[str, Any]:
        """
        Return provider health status suitable for the dashboard endpoint.

        Structure::

            {
                "providers": {
                    "binance":       { state, trip_count, ... },
                    "bybit":         { ... },
                    "coingecko":     { ... },
                    "coinbase":      { ... },
                    "kraken":        { ... },
                    "cryptocompare": { ... },
                },
                "stale_pairs": ["BTCUSDT", ...],
                "overall": "healthy" | "degraded" | "down",
                "timestamp": 1712345678.9,
            }
        """
        provider_statuses = {name: h.status_dict() for name, h in self._health.items()}

        open_count = sum(1 for h in self._health.values() if h.state == "OPEN")
        if open_count == 0:
            overall = "healthy"
        elif open_count < len(self._health):
            overall = "degraded"
        else:
            overall = "down"

        stale_pairs = [
            pair
            for pair, ts in self._last_fetched_at.items()
            if time.time() - ts > _STALE_THRESHOLD_SECONDS
        ]

        return {
            "providers": provider_statuses,
            "stale_pairs": sorted(stale_pairs),
            "overall": overall,
            "timestamp": time.time(),
        }

    def get_provider_health_summary(self) -> dict[str, Any]:
        """
        Return a dashboard-optimised provider health summary.

        Designed for direct consumption by the React dashboard's
        ``/api/v1/provider-health`` endpoint.

        Structure::

            {
                "binance": {
                    "status": "healthy" | "degraded" | "down",
                    "last_success": "2m ago" | None,
                    "failure_count": 0,
                    "circuit": "CLOSED" | "OPEN" | "HALF_OPEN",
                },
                ...
                "timestamp": 1712345678.9,
            }

        Status mapping:
            CLOSED    → "healthy"
            HALF_OPEN → "degraded"
            OPEN      → "down"
        """
        _state_to_status = {
            "CLOSED": "healthy",
            "HALF_OPEN": "degraded",
            "OPEN": "down",
        }

        now = time.time()
        summary: dict[str, Any] = {}
        for name, h in self._health.items():
            if h.last_success_time:
                ago_s = now - h.last_success_time
                if ago_s < 60:
                    last_success: str | None = f"{int(ago_s)}s ago"
                elif ago_s < 3600:
                    last_success = f"{int(ago_s // 60)}m ago"
                else:
                    last_success = f"{int(ago_s // 3600)}h ago"
            else:
                last_success = None

            summary[name] = {
                "status": _state_to_status.get(h.state, "unknown"),
                "last_success": last_success,
                "failure_count": h.failure_count,
                "circuit": h.state,
            }

        summary["timestamp"] = now
        return summary

    def provider_health(self, name: str) -> _ProviderHealth | None:
        """Return the _ProviderHealth object for a named provider (for testing)."""
        return self._health.get(name)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _fetch_pair_with_failover(
        self,
        pair: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any] | None:
        """Try each provider in priority order and return the first success."""
        providers = [
            ("binance", self._binance),
            ("bybit", self._bybit),
            ("coingecko", self._coingecko),
            ("coinbase", self._coinbase),
            ("kraken", self._kraken),
            ("cryptocompare", self._cryptocompare),
        ]

        for provider_name, provider in providers:
            health = self._health[provider_name]
            if not health.is_callable():
                logger.debug(
                    "DataResilience[%s]: circuit OPEN, skipping for %s (%.0fs remaining)",
                    provider_name,
                    pair,
                    health.remaining_backoff_s() if hasattr(health, "remaining_backoff_s") else 0,
                )
                continue

            data = self._call_provider(provider_name, provider, pair, interval, limit)
            if data is not None:
                health.record_success()
                logger.debug(
                    "DataResilience: %s ← %s (%.2f)",
                    pair,
                    provider_name,
                    data.get("meta", {}).get("regularMarketPrice") or 0,
                )
                return data

        logger.error("DataResilience: ALL providers failed for %s — no price data", pair)
        return None

    def _call_provider(
        self,
        provider_name: str,
        provider: Any,
        pair: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any] | None:
        """Call a provider's fetch_klines, recording health outcomes."""
        from typing import cast

        health = self._health[provider_name]
        try:
            # All OHLCV providers expose fetch_klines(pair, interval, limit)
            data = provider.fetch_klines(pair, interval=interval, limit=limit)
            if data is not None:
                return cast(dict[str, Any], data)
            # None return = soft failure (no exception)
            health.record_failure(f"fetch_klines returned None for {pair}")
            return None
        except Exception as exc:
            health.record_failure(str(exc))
            logger.warning(
                "DataResilience[%s]: exception for %s: %s",
                provider_name,
                pair,
                exc,
            )
            return None

    def _detect_stale_pairs(self, market_data: dict[str, Any]) -> set[str]:
        """Return the set of pair keys whose data is older than the stale threshold."""
        now = time.time()
        stale: set[str] = set()
        for pair, data in market_data.items():
            if pair.startswith("_") or data is None:
                continue
            if not isinstance(data, dict):
                continue
            fetched_at = data.get("fetched_at")
            if fetched_at is None:
                # No timestamp — check our internal tracker
                fetched_at = self._last_fetched_at.get(pair)
            # No timestamp at all → assume fresh (synthetic/historic data)
            if fetched_at is not None and (now - fetched_at) > _STALE_THRESHOLD_SECONDS:
                stale.add(pair)
        return stale


# ─── Module-level singleton ────────────────────────────────────────────────────

_resilience_layer: DataResilienceLayer | None = None


def get_resilience_layer() -> DataResilienceLayer:
    """Return the module-level singleton DataResilienceLayer (lazy init)."""
    global _resilience_layer
    if _resilience_layer is None:
        _resilience_layer = DataResilienceLayer()
    return _resilience_layer
