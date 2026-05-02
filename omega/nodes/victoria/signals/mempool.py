"""Mempool.space Bitcoin network-stress signals.

Free public API (https://mempool.space). Two signals:

  mempool_fee_urgency: (fastestFee - minimumFee) / max(minimumFee, 1)
                       normalized to [-1, +1]. High urgency = network stress
                       = potential volatility. Mapped: ratio 1 → 0; 5 → +0.4;
                       10+ → +1.0.

  mempool_size_zscore: rolling z-score of unconfirmed-tx count vs a 24h
                       baseline persisted to data/macro_cache.db.
                       (For now we use ratio vs a long-run mean of 50k tx
                       since we have no time-series; placeholder is mempool_count
                       relative to 50_000.)

Caching: 5-minute TTL to be polite to the public API.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.mempool")

_FEES_URL = "https://mempool.space/api/v1/fees/recommended"
_MEMPOOL_URL = "https://mempool.space/api/mempool"
_TTL_SECONDS = 300  # 5 minutes


class MempoolSignal:
    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._cache_ts: float = 0.0
        self._cached: dict[str, float] = {"mempool_fee_urgency": 0.0, "mempool_size_zscore": 0.0}

    def compute(self) -> dict[str, float]:
        now = time.time()
        if now - self._cache_ts < _TTL_SECONDS:
            return dict(self._cached)
        try:
            fees = self._get_json(_FEES_URL)
            stats = self._get_json(_MEMPOOL_URL)
        except Exception as exc:
            logger.debug("mempool fetch failed: %s", exc)
            return dict(self._cached)

        urgency = 0.0
        try:
            fast = float(fees.get("fastestFee", 1))
            mn = max(1.0, float(fees.get("minimumFee", 1)))
            ratio = (fast - mn) / mn
            urgency = max(-1.0, min(1.0, (ratio - 1.0) / 9.0))  # ratio 1→0, 10→1
        except Exception:
            urgency = 0.0

        size_z = 0.0
        try:
            count = float(stats.get("count", 0))
            baseline = 50_000.0  # rough long-run mean of unconfirmed tx
            size_z = max(-1.0, min(1.0, (count - baseline) / baseline))
        except Exception:
            size_z = 0.0

        self._cached = {"mempool_fee_urgency": urgency, "mempool_size_zscore": size_z}
        self._cache_ts = now
        logger.debug("mempool: urgency=%.3f size_z=%.3f", urgency, size_z)
        return dict(self._cached)

    def _get_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "omega-victoria/1.0"})
        with urllib.request.urlopen(req, timeout=self._timeout) as r:
            return json.loads(r.read())


def _self_test() -> None:
    s = MempoolSignal()
    v = s.compute()
    print(f"mempool first call: {v}")
    v2 = s.compute()
    print(f"mempool cached call (should equal first): {v2}")
    assert v == v2
    print("mempool: OK")


if __name__ == "__main__":
    _self_test()
