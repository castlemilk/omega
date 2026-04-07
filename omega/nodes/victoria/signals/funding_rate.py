"""
Funding rate signal for Victoria.

Fetches perpetual futures funding rates from CoinGecko derivatives API
and computes a z-score signal:
  - Positive funding (longs paying shorts) → overbought → bearish signal (negative output)
  - Negative funding (shorts paying longs) → oversold → bullish signal (positive output)

Endpoint: GET https://api.coingecko.com/api/v3/derivatives (list of all derivatives)
Filter by ticker symbol (e.g. BTCUSDT → BTC) and funding_rate field.

Falls back to 0.0 if:
  - Network unavailable
  - < min_periods of history
  - Symbol not found in response
"""

import logging
import math
from collections import deque
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.funding_rate")

# Map from trading symbol to CoinGecko base currency name pattern
_SYMBOL_TO_BASE = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "LINKUSDT": "chainlink",
    "AVAXUSDT": "avalanche",
}


class FundingRateSignal:
    """
    Computes a z-score normalized funding rate signal per symbol.

    Usage:
        sig = FundingRateSignal(window=30)
        signal_value = sig.compute("BTCUSDT")  # returns float in [-1, 1]
    """

    def __init__(self, window: int = 30) -> None:
        self._window = window
        # Rolling buffer of funding rates per symbol
        self._history: dict[str, deque] = {}
        # Cache of latest fetched raw rates {symbol: float}
        self._last_rates: dict[str, float] = {}

    def compute(self, symbol: str, rate: float | None = None) -> float:
        """
        Compute the funding rate signal for a symbol.

        If rate is provided, uses that directly (for testing/injection).
        Otherwise, attempts to fetch from CoinGecko.

        Returns normalized signal in [-1, 1]:
          positive = bullish (negative funding = squeeze potential)
          negative = bearish (positive funding = dump risk)
        """
        if rate is None:
            rate = self._fetch_rate(symbol)

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
        rates = self._fetch_all_rates(symbols)
        for sym in symbols:
            r = rates.get(sym)
            result[sym] = self.compute(sym, rate=r)
        return result

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

    def _fetch_rate(self, symbol: str) -> float | None:
        """Fetch current funding rate for a single symbol from CoinGecko."""
        rates = self._fetch_all_rates([symbol])
        return rates.get(symbol)

    def _fetch_all_rates(self, symbols: list[str]) -> dict[str, float]:
        """
        Fetch funding rates for multiple symbols from CoinGecko derivatives endpoint.
        Returns {symbol: funding_rate_float}.
        """
        try:
            import json
            import urllib.request

            url = "https://api.coingecko.com/api/v3/derivatives"
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "omega-victoria/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data: list[dict] = json.loads(resp.read().decode())

            return self._parse_rates(data, symbols)

        except Exception as exc:
            logger.debug("FundingRateSignal fetch failed: %s", exc)
            return {}

    def _parse_rates(self, data: list[dict], symbols: list[str]) -> dict[str, float]:
        """Parse CoinGecko derivatives response to extract funding rates per symbol."""
        result: dict[str, float] = {}

        # Build lookup: base_currency → [funding_rate entries]
        # CoinGecko derivatives: each entry has "market", "symbol", "funding_rate"
        # symbol format is like "BTC-PERP" or "BTC/USD" or "BTCUSDT"
        # We match by checking if the symbol field contains the base currency

        for sym in symbols:
            base = sym.replace("USDT", "").replace("BUSD", "")

            candidates: list[float] = []
            for entry in data:
                entry_sym: str = str(entry.get("symbol", "")).upper()
                fr = entry.get("funding_rate")
                if fr is None:
                    continue
                try:
                    fr_f = float(fr)
                except (TypeError, ValueError):
                    continue

                # Match if base currency appears at start of derivatives symbol
                if entry_sym.startswith(base) or f"/{base}" in entry_sym:
                    candidates.append(fr_f)

            if candidates:
                # Use median to filter outliers across exchanges
                candidates.sort()
                mid = len(candidates) // 2
                result[sym] = candidates[mid]

        return result

    def get_last_rates(self) -> dict[str, float]:
        """Return the most recently fetched raw funding rates."""
        return dict(self._last_rates)
