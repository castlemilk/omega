"""
omega.nodes.victoria.finbert_sentiment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Lightweight crypto news sentiment signal for Victoria.

Fetches recent crypto news headlines from public free endpoints:
  1. CoinGecko news API  (no key required)
  2. CryptoPanic free API (no key required, limited to 50 results)

Applies a keyword-based sentiment scorer — no ML/torch dependency.
Positive and negative financial/crypto keywords are counted, with
recency weighting (exponential decay so newer headlines matter more).

Signal semantics
----------------
  sentiment_score ∈ [-1.0, +1.0]
    +1.0 → strong positive sentiment across recent headlines
    -1.0 → strong negative sentiment
     0.0 → neutral / no data

  Per-ticker score is extracted when the headline mentions a tracked
  ticker name or symbol.  The composite is the weighted average across
  tracked tickers (falling back to global score if per-ticker is sparse).

Cache TTL: 10 minutes (news is slow-moving intraday).
Fallback: 0.0 / confidence=0.0 if all sources fail.
"""

from __future__ import annotations

import json as _json
import logging
import math
import time
import urllib.request
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.finbert_sentiment")

_CACHE_TTL = 600  # 10 minutes
_EPSILON = 1e-9

# CoinGecko public news endpoint
_COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"
# CryptoPanic public (no-auth) endpoint
_CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true&kind=news"

# Recency half-life in seconds: headlines lose half their weight every 2 hours
_RECENCY_HALF_LIFE = 7200.0

# ---------------------------------------------------------------------------
# Keyword lexicon
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS = frozenset(
    {
        "bullish",
        "rally",
        "surge",
        "soar",
        "gain",
        "gains",
        "rise",
        "rises",
        "moon",
        "breakout",
        "outperform",
        "upgrade",
        "adoption",
        "buy",
        "long",
        "support",
        "rebound",
        "recover",
        "recovery",
        "upside",
        "positive",
        "institutional",
        "approval",
        "approved",
        "partnership",
        "launch",
        "growth",
        "profit",
        "profits",
        "all-time high",
        "ath",
        "accumulation",
        "accumulate",
        "inflow",
        "inflows",
        "confidence",
        "optimistic",
        "optimism",
        "strong",
        "strength",
        "booming",
        "boom",
        "higher",
        "advance",
        "advances",
        "jumped",
        "jump",
        "climbed",
        "climb",
        "breakthrough",
        "milestone",
        "etf",
        "spot etf",
        "listing",
        "listed",
    }
)

_NEGATIVE_KEYWORDS = frozenset(
    {
        "bearish",
        "crash",
        "dump",
        "plunge",
        "fall",
        "falls",
        "drop",
        "drops",
        "decline",
        "declines",
        "sell",
        "short",
        "resistance",
        "correction",
        "selloff",
        "sell-off",
        "liquidation",
        "liquidations",
        "outflow",
        "outflows",
        "downgrade",
        "ban",
        "banned",
        "hack",
        "hacked",
        "exploit",
        "theft",
        "scam",
        "fraud",
        "lawsuit",
        "sec",
        "enforcement",
        "regulation",
        "crackdown",
        "negative",
        "pessimistic",
        "pessimism",
        "weak",
        "weakness",
        "lower",
        "retreat",
        "retreats",
        "collapsed",
        "collapse",
        "fear",
        "uncertainty",
        "fud",
        "concern",
        "concerns",
        "warning",
        "risk",
        "losses",
        "loss",
        "broke",
        "broken support",
        "death cross",
    }
)

# Ticker → name mappings for per-ticker attribution
_TICKER_KEYWORDS: dict[str, list[str]] = {
    "BTCUSDT": ["bitcoin", "btc", "xbt"],
    "ETHUSDT": ["ethereum", "eth", "ether"],
    "SOLUSDT": ["solana", "sol"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SignalValue:
    __slots__ = ("confidence", "raw", "regime_tag", "value")

    def __init__(
        self,
        value: float,
        confidence: float,
        regime_tag: str,
        raw: dict[str, float],
    ) -> None:
        self.value = value
        self.confidence = confidence
        self.regime_tag = regime_tag
        self.raw = raw


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _unavailable(reason: str) -> _SignalValue:
    return _SignalValue(
        value=0.0,
        confidence=0.0,
        regime_tag="unavailable",
        raw={"reason": 0.0, reason: 0.0},
    )


def _http_get(url: str, timeout: int = 8) -> Any:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "omega-victoria/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode())


def _recency_weight(published_ts: float, now: float) -> float:
    """Exponential decay weight based on age of article."""
    age_s = max(0.0, now - published_ts)
    return math.exp(-age_s * math.log(2) / _RECENCY_HALF_LIFE)


def _score_text(text: str) -> float:
    """
    Return a raw sentiment score for a headline/text snippet.

    Counts positive and negative keyword matches (case-insensitive,
    whole-word tolerant but not requiring exact boundaries — substring
    matching intentionally included for compound words like 'bullishness').

    score = (pos - neg) / (pos + neg + 1)  ∈ (-1, +1)
    """
    lower = text.lower()
    pos = sum(1 for kw in _POSITIVE_KEYWORDS if kw in lower)
    neg = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in lower)
    return (pos - neg) / (pos + neg + 1)


def _ticker_for_text(text: str) -> str | None:
    """Return the first tracked ticker whose keywords appear in the text."""
    lower = text.lower()
    for ticker, keywords in _TICKER_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return ticker
    return None


# ---------------------------------------------------------------------------
# Source 1: CoinGecko news
# ---------------------------------------------------------------------------


def _fetch_coingecko_news(now: float) -> list[tuple[str, float, float]]:
    """
    Fetch CoinGecko news and return list of (text, score, weight) tuples.
    """
    try:
        data = _http_get(_COINGECKO_NEWS_URL, timeout=8)
    except Exception as exc:
        logger.debug("CoinGecko news fetch failed: %s", exc)
        return []

    # CoinGecko returns {"data": [{"title":..., "updated_at":..., ...}, ...]}
    items = data.get("data", []) if isinstance(data, dict) else []
    results: list[tuple[str, float, float]] = []
    for item in items:
        title = str(item.get("title", "") or "")
        description = str(item.get("description", "") or "")
        text = f"{title} {description}"

        # updated_at is ISO string; fall back to now if missing/unparseable
        ts_raw = item.get("updated_at") or item.get("published_at") or ""
        try:
            import datetime

            ts = datetime.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = now

        score = _score_text(text)
        weight = _recency_weight(ts, now)
        if abs(score) > _EPSILON or weight > 0.01:
            results.append((text, score, weight))

    return results


# ---------------------------------------------------------------------------
# Source 2: CryptoPanic free API
# ---------------------------------------------------------------------------


def _fetch_cryptopanic_news(now: float) -> list[tuple[str, float, float]]:
    """
    Fetch CryptoPanic free posts and return list of (text, score, weight) tuples.
    """
    try:
        data = _http_get(_CRYPTOPANIC_URL, timeout=8)
    except Exception as exc:
        logger.debug("CryptoPanic news fetch failed: %s", exc)
        return []

    # CryptoPanic: {"results": [{"title":..., "published_at":..., "votes": {...}}, ...]}
    items = data.get("results", []) if isinstance(data, dict) else []
    results: list[tuple[str, float, float]] = []
    for item in items:
        title = str(item.get("title", "") or "")
        text = title  # CryptoPanic free tier only provides title

        ts_raw = item.get("published_at", "")
        try:
            import datetime

            ts = datetime.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = now

        # CryptoPanic also exposes vote signals: {positive, negative, important, liked, ...}
        votes = item.get("votes", {}) or {}
        vote_pos = int(votes.get("positive", 0) or 0)
        vote_neg = int(votes.get("negative", 0) or 0)
        vote_total = vote_pos + vote_neg
        vote_score = (vote_pos - vote_neg) / (vote_total + 1) if vote_total > 0 else 0.0

        # Blend keyword score + vote signal (60/40)
        kw_score = _score_text(text)
        blended = 0.6 * kw_score + 0.4 * vote_score

        weight = _recency_weight(ts, now)
        if weight > 0.01:
            results.append((text, _clamp(blended), weight))

    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(
    articles: list[tuple[str, float, float]],
) -> tuple[float, float, dict[str, float]]:
    """
    Compute composite and per-ticker weighted sentiment scores.

    Returns (composite_score, confidence, per_ticker_raw_dict).
    """
    if not articles:
        return 0.0, 0.0, {}

    # Global weighted score
    total_weight = sum(w for _, _, w in articles)
    weighted_sum = sum(s * w for _, s, w in articles)
    global_score = weighted_sum / (total_weight + _EPSILON)

    # Per-ticker scores
    ticker_weighted: dict[str, list[tuple[float, float]]] = {}
    for text, score, weight in articles:
        ticker = _ticker_for_text(text)
        if ticker is not None:
            ticker_weighted.setdefault(ticker, []).append((score, weight))

    raw: dict[str, float] = {
        "article_count": float(len(articles)),
        "total_weight": total_weight,
        "global_score": global_score,
    }

    per_ticker_scores: list[float] = []
    for ticker, sw_pairs in ticker_weighted.items():
        tw = sum(w for _, w in sw_pairs)
        ts = sum(s * w for s, w in sw_pairs) / (tw + _EPSILON)
        raw[f"{ticker.lower()}_sentiment"] = _clamp(ts)
        raw[f"{ticker.lower()}_article_count"] = float(len(sw_pairs))
        per_ticker_scores.append(_clamp(ts))

    # Composite: average of per-ticker scores if we have any, else global
    if per_ticker_scores:
        composite = sum(per_ticker_scores) / len(per_ticker_scores)
    else:
        composite = global_score

    composite = _clamp(composite)

    # Confidence: more recent, more articles → higher confidence
    recent_count = sum(1 for _, _, w in articles if w > 0.5)
    confidence = _clamp(
        0.3 + 0.4 * min(1.0, recent_count / 10) + 0.3 * min(1.0, total_weight / 5), 0.0, 1.0
    )

    return composite, confidence, raw


# ---------------------------------------------------------------------------
# Public signal class
# ---------------------------------------------------------------------------


class FinBertSentimentSignal:
    """
    Keyword-based crypto news sentiment signal (no torch/ML dependency).

    Fetches headlines from CoinGecko and CryptoPanic, scores them with a
    financial keyword lexicon, weights by recency, and returns a composite
    sentiment score.

    Usage::

        sig = FinBertSentimentSignal()
        sv = sig.compute()
        print(sv.value, sv.confidence, sv.raw)
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def compute(self, market_data: dict[str, Any] | None = None) -> _SignalValue:
        """Return cached result if still fresh, otherwise re-fetch."""
        now = time.time()
        if self._cached is not None and (now - self._cache_ts) < _CACHE_TTL:
            return self._cached

        result = self._fetch(now)
        self._cached = result
        self._cache_ts = now
        return result

    def _fetch(self, now: float) -> _SignalValue:
        articles: list[tuple[str, float, float]] = []

        cg_articles = _fetch_coingecko_news(now)
        articles.extend(cg_articles)
        logger.debug("FinBertSentimentSignal: CoinGecko returned %d articles", len(cg_articles))

        cp_articles = _fetch_cryptopanic_news(now)
        articles.extend(cp_articles)
        logger.debug("FinBertSentimentSignal: CryptoPanic returned %d articles", len(cp_articles))

        if not articles:
            logger.debug("FinBertSentimentSignal: no articles from any source")
            return _unavailable("no_articles")

        composite, confidence, raw = _aggregate(articles)

        if composite > 0.15:
            regime_tag = "positive_sentiment"
        elif composite < -0.15:
            regime_tag = "negative_sentiment"
        else:
            regime_tag = "neutral_sentiment"

        logger.debug(
            "FinBertSentimentSignal: value=%.3f confidence=%.2f regime=%s articles=%d",
            composite,
            confidence,
            regime_tag,
            len(articles),
        )

        return _SignalValue(
            value=composite,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )
