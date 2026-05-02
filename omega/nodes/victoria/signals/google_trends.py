"""Google Trends retail-sentiment signals via pytrends.

Two signals:

  google_trend_momentum: rate of change of "bitcoin" search interest over
                         the last 7 days (hourly). Mapped to [-1, +1] with
                         saturation at ±50% rate of change.

  retail_fomo_signal:    +1 when latest interest is >2σ above 7-day mean
                         (extreme retail attention → contrarian short signal,
                         so we negate). 0 otherwise.

Caching: 1-hour TTL (Google Trends rate-limits aggressively; pytrends has its
own session backoff but we cache at the application layer too).

Output: dict with both signals. Returns zeros on fetch failure.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.google_trends")

_TTL_SECONDS = 3600  # 1 hour


class GoogleTrendsSignal:
    def __init__(self, query: str = "bitcoin") -> None:
        self._query = query
        self._cache_ts: float = 0.0
        self._cached: dict[str, float] = {
            "google_trend_momentum": 0.0,
            "retail_fomo_signal": 0.0,
        }

    def compute(self) -> dict[str, float]:
        now = time.time()
        if now - self._cache_ts < _TTL_SECONDS and self._cached:
            return dict(self._cached)
        try:
            from pytrends.request import TrendReq  # type: ignore[import]
        except ImportError:
            logger.debug("pytrends not installed — returning zeros")
            return dict(self._cached)
        try:
            pt = TrendReq(hl="en-US", tz=0, timeout=(8, 12))
            pt.build_payload([self._query], cat=0, timeframe="now 7-d", gprop="")
            df = pt.interest_over_time()
            if df.empty:
                logger.debug("pytrends empty df")
                return dict(self._cached)
            vals = df[self._query].astype(float).tolist()
            if len(vals) < 6:
                return dict(self._cached)
            latest = vals[-1]
            window = vals[-24:] if len(vals) >= 24 else vals
            # Momentum: latest vs mean of window
            mean = sum(window) / len(window)
            roc = (latest - mean) / max(1.0, mean)
            momentum = max(-1.0, min(1.0, roc / 0.5))  # ±50% → ±1
            # FOMO: 2σ above 7-day mean? (use full vals)
            full_mean = sum(vals) / len(vals)
            var = sum((v - full_mean) ** 2 for v in vals) / max(1, len(vals) - 1)
            std = max(1.0, var ** 0.5)
            z = (latest - full_mean) / std
            fomo = -1.0 if z > 2.0 else 0.0  # contrarian: extreme attention → short
        except Exception as exc:
            logger.debug("google_trends fetch failed: %s", exc)
            return dict(self._cached)

        self._cached = {
            "google_trend_momentum": round(momentum, 4),
            "retail_fomo_signal": round(fomo, 4),
        }
        self._cache_ts = now
        logger.debug("google_trends: momentum=%.3f fomo=%.3f", momentum, fomo)
        return dict(self._cached)


def _self_test() -> None:
    s = GoogleTrendsSignal()
    v = s.compute()
    print(f"google_trends first: {v}")
    v2 = s.compute()
    assert v == v2, "cached call should match"
    print("google_trends: OK")


if __name__ == "__main__":
    _self_test()
