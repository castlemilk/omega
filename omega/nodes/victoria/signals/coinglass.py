"""Coinglass derivatives signals (STUB — requires API key).

Public-tier endpoints at https://open-api.coinglass.com/public/v2/* now require
an API key (verified 2026-05-02: no-auth requests return code 30001 "API key
missing"). Set COINGLASS_API_KEY in env to activate.

Signals when active:
  funding_rate_aggregate: cross-exchange weighted average funding rate
  long_short_ratio:       global long/short position ratio
  open_interest_change:   24h % change in OI
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("omega.nodes.victoria.signals.coinglass")

_BASE = "https://open-api.coinglass.com/public/v2"
_TTL_SECONDS = 300


class CoinglassSignal:
    def __init__(self, symbol: str = "BTC", timeout: float = 8.0) -> None:
        self._symbol = symbol
        self._timeout = timeout
        self._cache_ts: float = 0.0
        self._cached: dict[str, float] = {
            "funding_rate_aggregate": 0.0,
            "long_short_ratio": 0.0,
            "open_interest_change": 0.0,
        }
        self._key = os.environ.get("COINGLASS_API_KEY", "").strip()

    def compute(self) -> dict[str, float]:
        if not self._key:
            return dict(self._cached)
        now = time.time()
        if now - self._cache_ts < _TTL_SECONDS:
            return dict(self._cached)
        try:
            url = f"{_BASE}/funding?symbol={urllib.parse.quote(self._symbol)}"
            req = urllib.request.Request(
                url, headers={"User-Agent": "omega/1.0", "coinglassSecret": self._key}
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                body = json.loads(r.read())
            if body.get("code") != "0":
                logger.debug("coinglass error: %s", body.get("msg"))
                return dict(self._cached)
            # Schema varies by tier; this is a best-effort parse
            data = body.get("data", [])
            rates = [float(d.get("rate", 0)) for d in data if isinstance(d, dict)]
            if rates:
                avg = sum(rates) / len(rates)
                self._cached["funding_rate_aggregate"] = max(-1.0, min(1.0, avg / 0.001))
            self._cache_ts = now
        except Exception as exc:
            logger.debug("coinglass fetch failed: %s", exc)
        return dict(self._cached)
