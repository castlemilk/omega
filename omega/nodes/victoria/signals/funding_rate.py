"""
Funding rate signal for Victoria.

Computes a z-score signal from perpetual futures funding rates:
  - Positive funding (longs paying shorts) → overbought → bearish signal (negative output)
  - Negative funding (shorts paying longs) → oversold → bullish signal (positive output)

## Data sources (priority order)

1. **OKX** (primary): GET /api/v5/public/funding-rate?instId={symbol}-USDT-SWAP
   - Public API, no key required
   - Funding settles every 8 hours (00:00, 08:00, 16:00 UTC)
   - Reliable uptime, low latency

2. **MacroDataCache** (cached): rates are stored in SQLite (data/macro_cache.db)
   with an 8-hour TTL (matching the funding settlement cycle). Subsequent calls
   within the same settlement window read from local cache, zero API calls.

3. **CoinGecko** (fallback): derivatives endpoint, 429 rate-limited without key.

Falls back to 0.0 if all sources fail or < min_periods of history available.
"""

import logging
import math
from collections import deque

logger = logging.getLogger("omega.nodes.victoria.signals.funding_rate")


class FundingRateSignal:
    """
    Computes a z-score normalized funding rate signal per symbol.

    Reads from MacroDataCache which uses OKX as primary source and CoinGecko
    as fallback. Cache TTL is 8 hours (funding settlement cycle).

    Usage:
        sig = FundingRateSignal(window=30)
        signal_value = sig.compute("BTCUSDT")  # returns float in [-1, 1]
    """

    def __init__(self, window: int = 30) -> None:
        self._window = window
        # Rolling buffer of funding rates per symbol (for z-score history)
        self._history: dict[str, deque] = {}
        # Last raw rate per symbol (for inspection)
        self._last_rates: dict[str, float] = {}
        # Lazy-loaded cache
        self._cache = None

    def compute(self, symbol: str, rate: float | None = None) -> float:
        """
        Compute the funding rate signal for a symbol.

        If rate is provided, uses that directly (for testing/injection).
        Otherwise reads from MacroDataCache (OKX primary, CoinGecko fallback).

        Returns normalized signal in [-1, 1]:
          positive = bullish (negative funding = squeeze potential)
          negative = bearish (positive funding = dump risk)
        """
        if rate is None:
            rate = self._get_cached_rate(symbol)

        if rate is None:
            return 0.0

        if symbol not in self._history:
            self._history[symbol] = deque(maxlen=self._window)

        self._history[symbol].append(rate)
        self._last_rates[symbol] = rate

        return self._zscore_signal(symbol)

    def compute_all(self, symbols: list[str]) -> dict[str, float]:
        """Compute signals for all symbols. Returns {symbol: signal}."""
        result = {}
        for sym in symbols:
            result[sym] = self.compute(sym)
        return result

    def _fetch_all_rates(self, symbols: list[str]) -> dict[str, float | None]:
        """Fetch raw funding rates for all symbols, warn on any failure.

        Network or API errors are logged at WARNING level so they surface in
        training logs (not silently swallowed at DEBUG).
        """
        rates: dict[str, float | None] = {}
        for sym in symbols:
            try:
                rate = self._get_cached_rate(sym)
                if rate is None:
                    logger.warning(
                        "FundingRateSignal: failed to fetch funding rate for %s "
                        "(all sources exhausted or network error)",
                        sym,
                    )
                rates[sym] = rate
            except Exception as exc:
                logger.warning("FundingRateSignal: unexpected error fetching %s: %s", sym, exc)
                rates[sym] = None
        return rates

    def _get_cached_rate(self, symbol: str) -> float | None:
        """Read funding rate from MacroDataCache (OKX → CoinGecko → None)."""
        if self._cache is None:
            from omega.nodes.victoria.data_cache import get_cache

            self._cache = get_cache()
        return self._cache.get_funding_rate(symbol)

    def _zscore_signal(self, symbol: str) -> float:
        """Z-score of latest rate vs rolling window, normalized to [-1, 1]."""
        hist = list(self._history.get(symbol, []))
        if len(hist) < 2:
            return 0.0

        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / max(1, len(hist) - 1)
        std = math.sqrt(variance) if variance > 0 else 1e-8

        latest = hist[-1]
        zscore = (latest - mean) / std

        # Negate: positive funding rate → negative signal (bearish/dump risk)
        # Divide by 2 to map ±2σ → ±1
        signal = max(-1.0, min(1.0, -zscore / 2.0))
        return signal

    def get_last_rates(self) -> dict[str, float]:
        """Return the most recently fetched raw funding rates."""
        return dict(self._last_rates)
