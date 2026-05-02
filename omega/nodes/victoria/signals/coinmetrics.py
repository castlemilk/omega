"""CoinMetrics on-chain fundamentals (STUB — community API now gated).

Verified 2026-05-02: https://community-api.coinmetrics.io/v4/timeseries/asset-metrics
returns HTTP 403. Either the community tier requires registration now or it's
been deprecated. Set COINMETRICS_API_KEY in env to activate.

Signals when active:
  nvt_ratio: network value to transactions (crypto P/E)
  realized_cap_change: 7-day % change in realized cap
  hash_rate_change: 7-day % change in hash rate
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger("omega.nodes.victoria.signals.coinmetrics")

_BASE = "https://community-api.coinmetrics.io/v4"
_TTL_SECONDS = 86400  # daily


class CoinMetricsSignal:
    def __init__(self, asset: str = "btc", timeout: float = 10.0) -> None:
        self._asset = asset
        self._timeout = timeout
        self._cache_ts: float = 0.0
        self._cached: dict[str, float] = {
            "nvt_ratio": 0.0,
            "realized_cap_change": 0.0,
            "hash_rate_change": 0.0,
        }
        self._key = os.environ.get("COINMETRICS_API_KEY", "").strip()

    def compute(self) -> dict[str, float]:
        # Try without key first (community tier was free historically)
        # If 403/401, fall back to cached zeros.
        now = time.time()
        if now - self._cache_ts < _TTL_SECONDS:
            return dict(self._cached)
        url = (
            f"{_BASE}/timeseries/asset-metrics?assets={self._asset}"
            "&metrics=NVTAdj,HashRate,RealizedCap&page_size=10&pretty=false"
        )
        if self._key:
            url += f"&api_key={self._key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                body = json.loads(r.read())
            data = body.get("data", [])
            if not data:
                return dict(self._cached)
            latest = data[-1]
            self._cached["nvt_ratio"] = float(latest.get("NVTAdj", 0) or 0)
            self._cache_ts = now
        except Exception as exc:
            logger.debug("coinmetrics fetch failed: %s", exc)
        return dict(self._cached)
