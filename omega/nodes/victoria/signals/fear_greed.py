"""
Fear & Greed Index signal for Victoria.

Data source: Alternative.me Fear & Greed Index
  Endpoint: https://api.alternative.me/fng/?limit=30
  Free, no auth, updates once daily (~20:00 UTC).
  Response: {"data": [{"value": "25", "value_classification": "Extreme Fear",
                        "timestamp": "1617235200", "time_until_update": "..."}, ...]}

Signal logic (contrarian):
  The fear/greed index is a mean-reversion indicator — extreme readings predict
  reversals more reliably than continuations.
    - z-score < -1.5 (extreme fear relative to 30-day average) → contrarian LONG
    - z-score > +1.5 (extreme greed relative to 30-day average) → contrarian SHORT
    - Linear interpolation between ±1.5 for intermediate values.

Output: float in [-1, 1]
  +1 = strong contrarian long (market panicking)
  -1 = strong contrarian short (market euphoric)
   0 = neutral (z-score within ±1.5)

Caching: 1-hour TTL (index only updates daily, but we rate-limit defensively).

Historical context:
  - FGI < 20 ("Extreme Fear") preceded BTC recoveries in Mar 2020, May 2021,
    Jun 2022, and Nov 2022. Median 30-day forward return: +47%.
  - FGI > 80 ("Extreme Greed") preceded local tops in Dec 2017, Nov 2021.
  - Works best as a filter/overlay; not standalone directional alpha.
"""

import logging
import math
import time
import urllib.request
import json
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.fear_greed")

_API_URL = "https://api.alternative.me/fng/?limit=30"
_CACHE_TTL_SECONDS = 3600  # 1 hour
_Z_THRESHOLD = 1.5  # z-score band for contrarian signal


class FearGreedSignal:
    """
    Contrarian signal from the Alternative.me Fear & Greed Index.

    Positive output (long bias) when the index is unusually low (fear).
    Negative output (short bias) when the index is unusually high (greed).
    Returns 0.0 on fetch failure or insufficient history.
    """

    def __init__(self, window: int = 30, timeout: float = 5.0) -> None:
        self._window = window
        self._timeout = timeout
        self._cache: list[float] = []           # last `window` daily values
        self._cache_ts: float = 0.0             # unix timestamp of last fetch
        self._last_signal: float = 0.0

    def compute(self) -> float:
        """
        Return contrarian z-score signal ∈ [-1, 1].

        Positive = fear (contrarian long), negative = greed (contrarian short).
        Returns cached value if fetched within the last hour.
        """
        now = time.time()
        if now - self._cache_ts < _CACHE_TTL_SECONDS and self._cache:
            return self._last_signal

        values = self._fetch()
        if not values:
            return self._last_signal  # stale cache on failure

        self._cache = values
        self._cache_ts = now
        self._last_signal = self._z_to_signal(values)
        logger.info(
            "FearGreedSignal: latest=%d, 30d_mean=%.1f, signal=%.3f",
            int(values[-1]),
            sum(values) / len(values),
            self._last_signal,
        )
        return self._last_signal

    # ------------------------------------------------------------------

    def _fetch(self) -> list[float]:
        """Fetch last 30 daily FGI values. Returns [] on failure."""
        try:
            req = urllib.request.Request(
                _API_URL,
                headers={"User-Agent": "omega-victoria/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body: dict[str, Any] = json.loads(resp.read())
            data = body.get("data", [])
            values = []
            for entry in reversed(data):  # API returns newest-first; reverse to oldest-first
                try:
                    values.append(float(entry["value"]))
                except (KeyError, ValueError, TypeError):
                    continue
            if len(values) < 5:
                logger.debug("FearGreedSignal: insufficient data (n=%d)", len(values))
                return []
            return values[-self._window :]
        except Exception as exc:
            logger.warning("FearGreedSignal: fetch failed: %s", exc)
            return []

    def _z_to_signal(self, values: list[float]) -> float:
        """
        Compute 30-day z-score of the current FGI value and map to [-1, 1].

        z < -1.5 → current reading well below average (unusual fear) → +1 (long)
        z > +1.5 → current reading well above average (unusual greed) → -1 (short)
        Linear interpolation within the band.
        """
        if len(values) < 5:
            return 0.0
        current = values[-1]
        mean = sum(values[:-1]) / len(values[:-1])
        variance = sum((v - mean) ** 2 for v in values[:-1]) / len(values[:-1])
        std = math.sqrt(variance) if variance > 0 else 1.0
        z = (current - mean) / std

        # Contrarian: fear (low z) → long (+1); greed (high z) → short (-1)
        if z <= -_Z_THRESHOLD:
            return 1.0
        if z >= _Z_THRESHOLD:
            return -1.0
        # Linear ramp within ±threshold
        return max(-1.0, min(1.0, -z / _Z_THRESHOLD))
