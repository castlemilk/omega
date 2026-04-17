"""
omega.nodes.victoria.signals.geopolitical
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GDELT DOC 2.0 geopolitical event signals for Victoria.

Produces four market-level signals from GDELT article data:
  - geo_event_intensity  : rolling 24h article count / 7-day mean (0–3 clamped)
  - geo_sentiment        : mean avg_tone across matching articles (-10 to +10)
  - geo_regime_shift     : 1.0 if event_intensity > 2σ above 7-day mean, else 0.0
  - sanctions_signal     : sanctions-query count / baseline, smoothed EMA (0–1)

Feature flag: geopolitical_signals (V138)
Cache: data/cache/gdelt/{query_name}_{YYYYMMDD_HHmm}.json (15-min TTL live;
       immutable for historical dates in backtest mode)
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GDELT query definitions
# ---------------------------------------------------------------------------

_QUERIES: dict[str, str] = {
    "crypto_regulation": "cryptocurrency regulation SEC CFTC ban",
    "sanctions": "financial sanctions SWIFT blockchain",
    "financial_crisis": "bank failure systemic risk contagion",
    "central_bank": "federal reserve interest rate quantitative easing",
    "geopolitical": "military conflict trade war sanctions embargo",
}

_GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_CACHE_TTL_SECONDS = 900  # 15 minutes for live mode
_HISTORY_DAYS = 7

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_CACHE_ROOT = Path(__file__).resolve().parents[5] / "data" / "cache" / "gdelt"


def _cache_key(query_name: str, dt: datetime) -> str:
    """15-minute-truncated cache key."""
    bucket = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
    return f"{query_name}_{bucket.strftime('%Y%m%d_%H%M')}"


def _cache_path(key: str) -> Path:
    return _CACHE_ROOT / f"{key}.json"


def _cache_load(key: str, is_historical: bool) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if is_historical:
        # Historical data never expires
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    # Live: check TTL
    age = time.time() - path.stat().st_mtime
    if age > _CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _cache_store(key: str, data: dict) -> None:
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(data))
    except Exception as exc:
        logger.debug("gdelt cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# GDELT client
# ---------------------------------------------------------------------------


class GDELTClient:
    """Thin GDELT DOC 2.0 client with TTL cache."""

    def query(
        self,
        query_name: str,
        query_text: str,
        start_dt: datetime,
        end_dt: datetime,
        is_historical: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch articles matching *query_text* in [start_dt, end_dt].

        Returns list of article dicts with keys: url, title, seendate, tone (avg_tone).
        Falls back to [] on any error.
        """
        key = _cache_key(query_name, end_dt)
        cached = _cache_load(key, is_historical)
        if cached is not None:
            return cached.get("articles", [])

        fmt = "%Y%m%d%H%M%S"
        params = (
            f"?query={urllib.parse.quote(query_text)}"
            f"&mode=artlist"
            f"&maxrecords=250"
            f"&startdatetime={start_dt.strftime(fmt)}"
            f"&enddatetime={end_dt.strftime(fmt)}"
            f"&format=json"
        )
        url = _GDELT_BASE + params
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-victoria/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode())
            articles = raw.get("articles", []) or []
            _cache_store(key, {"articles": articles})
            return articles
        except Exception as exc:
            logger.debug("GDELT query %r failed: %s", query_name, exc)
            return []


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


class GeopoliticalSignal:
    """Computes 4 market-level geopolitical signals from GDELT DOC 2.0."""

    def __init__(self) -> None:
        self._client = GDELTClient()
        self._ema_sanctions: float = 0.0
        self._alpha_sanctions: float = 0.3

    def compute(
        self,
        timestamp: datetime | None = None,
        is_historical: bool = False,
    ) -> dict[str, float]:
        """Fetch GDELT data and return 4 signals.

        Args:
            timestamp: Reference time (end of query window). Defaults to now (UTC).
            is_historical: If True, skip TTL on cached results (backtest mode).

        Returns:
            Dict with keys: geo_event_intensity, geo_sentiment, geo_regime_shift,
            sanctions_signal. All default to 0.0 on fetch failure.
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        end_dt = timestamp
        start_24h = end_dt - timedelta(hours=24)
        start_7d = end_dt - timedelta(days=_HISTORY_DAYS)

        # Fetch all queries
        articles_24h: list[dict] = []
        articles_7d: list[dict] = []
        sanctions_24h: list[dict] = []

        for q_name, q_text in _QUERIES.items():
            a24 = self._client.query(q_name, q_text, start_24h, end_dt, is_historical)
            a7d = self._client.query(q_name, q_text, start_7d, end_dt, is_historical)
            articles_24h.extend(a24)
            articles_7d.extend(a7d)
            if q_name == "sanctions":
                sanctions_24h = a24

        return {
            "geo_event_intensity": self._compute_intensity(articles_24h, articles_7d),
            "geo_sentiment": self._compute_sentiment(articles_24h),
            "geo_regime_shift": self._compute_regime_shift(articles_24h, articles_7d),
            "sanctions_signal": self._compute_sanctions(sanctions_24h, articles_7d),
        }

    def _compute_intensity(self, a24: list[dict], a7d: list[dict]) -> float:
        """Rolling 24h count / (7-day mean daily count), clamped to [0, 3]."""
        count_24h = len(a24)
        count_7d = len(a7d)
        daily_mean = count_7d / _HISTORY_DAYS if count_7d > 0 else 1.0
        return min(3.0, count_24h / max(daily_mean, 1.0))

    def _compute_sentiment(self, a24: list[dict]) -> float:
        """Mean avg_tone across 24h articles, clamped to [-10, 10]."""
        tones = []
        for art in a24:
            tone = art.get("tone") or art.get("avg_tone")
            if tone is not None:
                with contextlib.suppress(ValueError, TypeError):
                    tones.append(float(tone))
        if not tones:
            return 0.0
        return max(-10.0, min(10.0, sum(tones) / len(tones)))

    def _compute_regime_shift(self, a24: list[dict], a7d: list[dict]) -> float:
        """1.0 if 24h intensity > 2σ above 7-day daily distribution, else 0.0."""
        if not a7d:
            return 0.0
        count_24h = float(len(a24))
        daily_mean = len(a7d) / _HISTORY_DAYS
        daily_std = math.sqrt(max(daily_mean, 1.0))
        return 1.0 if count_24h > daily_mean + 2.0 * daily_std else 0.0

    def _compute_sanctions(self, sanctions_24h: list[dict], a7d: list[dict]) -> float:
        """Sanctions 24h count / 7-day daily baseline, EMA-smoothed, clamped [0, 1]."""
        sanctions_count = float(len(sanctions_24h))
        baseline = max(len(a7d) / _HISTORY_DAYS / len(_QUERIES), 1.0)
        raw = min(1.0, sanctions_count / baseline)
        self._ema_sanctions = (
            self._alpha_sanctions * raw + (1.0 - self._alpha_sanctions) * self._ema_sanctions
        )
        return self._ema_sanctions
