"""
omega.nodes.victoria.news_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
News & sentiment signal provider for Victoria.

Sources:
  1. Fear & Greed Index (alternative.me) — free, historical, no auth required
  2. CryptoPanic API — free tier, crypto news aggregator with vote-based sentiment
  3. RSS feed sentiment — CoinDesk / CoinTelegraph keyword scoring

Signal output: SignalValue with value in [-1.0, +1.0] where:
  +1.0 = strongly bullish news environment
  -1.0 = strongly bearish news environment

Regime tags:
  "news_euphoria"      — F&G >= 80 and positive news flow
  "news_fearful"       — F&G <= 20 and negative news flow
  "fg_extreme_greed"   — F&G >= 75 (caution: possibly overheated)
  "fg_extreme_fear"    — F&G <= 25 (potential buying opportunity)
  "news_positive"      — mildly positive news environment
  "news_negative"      — mildly negative news environment
  "news_neutral"       — balanced / no clear directional bias
  "news_no_data"       — all sources unavailable

Note on F&G interpretation:
  SentimentSignal (signals_advanced.py) uses F&G CONTRARIANLY (greed → bearish).
  This signal uses it DIRECTIONALLY as a news sentiment indicator. The two
  complement each other: sentiment = crowded positioning, news = media narrative.

Historical data (for backtesting):
  NewsSignalProvider.fetch_historical_fear_greed(limit=365)
  → list of {value, classification, timestamp, date_str}, newest-first
  alternative.me endpoint supports up to ~2000 days of history.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
import urllib.request
from typing import Any, ClassVar, cast

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.news_signals")

# Cache TTL in seconds (15 minutes — same as MarketDataSignal)
_CACHE_TTL = 900


# ---------------------------------------------------------------------------
# Fear & Greed Index
# ---------------------------------------------------------------------------


class FearGreedIndex:
    """
    Fetches the Crypto Fear & Greed Index from alternative.me.

    Free endpoint, no authentication required. Supports historical data back
    to 2018. Cache keyed per request type to avoid stale cross-contamination.

    API: https://api.alternative.me/fng/
    """

    BASE_URL = "https://api.alternative.me/fng/"

    # Per-key cache: {cache_key: (data, timestamp)}
    _cache: ClassVar[dict[str, tuple[Any, float]]] = {}

    @classmethod
    def _get_cached(cls, key: str) -> Any | None:
        if key in cls._cache:
            data, ts = cls._cache[key]
            if time.time() - ts < _CACHE_TTL:
                return data
        return None

    @classmethod
    def _set_cached(cls, key: str, data: Any) -> None:
        cls._cache[key] = (data, time.time())

    @classmethod
    def fetch_current(cls) -> dict[str, Any] | None:
        """Fetch current F&G value. Returns None on failure."""
        cached = cls._get_cached("current")
        if cached is not None:
            return cast("dict[str, Any]", cached)

        try:
            url = f"{cls.BASE_URL}?limit=1&format=json"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            if data.get("data"):
                entry = data["data"][0]
                result = {
                    "value": int(entry["value"]),
                    "classification": entry["value_classification"],
                    "timestamp": entry.get("timestamp", ""),
                }
                cls._set_cached("current", result)
                return result
        except Exception as exc:
            logger.debug("FearGreedIndex.fetch_current failed: %s", exc)
        return None

    @classmethod
    def fetch_trend(cls, days: int = 7) -> list[dict[str, Any]]:
        """
        Fetch recent F&G values for trend analysis.

        Returns list of {value, classification, timestamp} dicts, newest first.
        """
        cache_key = f"trend_{days}"
        cached = cls._get_cached(cache_key)
        if cached is not None:
            return cast("list[dict[str, Any]]", cached)

        try:
            url = f"{cls.BASE_URL}?limit={days}&format=json"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            if "data" in data:
                result = [
                    {
                        "value": int(e["value"]),
                        "classification": e["value_classification"],
                        "timestamp": e.get("timestamp", ""),
                    }
                    for e in data["data"]
                ]
                cls._set_cached(cache_key, result)
                return result
        except Exception as exc:
            logger.debug("FearGreedIndex.fetch_trend(%d) failed: %s", days, exc)
        return []

    @classmethod
    def fetch_historical(cls, limit: int = 365) -> list[dict[str, Any]]:
        """
        Fetch historical F&G data for backtesting.

        Parameters
        ----------
        limit : int
            Number of days to fetch. alternative.me supports ~2000 days.
            Practical maximum for crypto history is ~2500 (since 2018).

        Returns
        -------
        list of dicts, newest-first:
            {value: int, classification: str, timestamp: str, date_str: str}

        Usage for backtesting (oldest→newest):
            history = NewsSignalProvider.fetch_historical_fear_greed(365)
            for entry in reversed(history):
                fg_val = entry["value"]
                date = entry["date_str"]
                signal = (fg_val - 50.0) / 50.0  # directional: fear→bearish
        """
        try:
            url = f"{cls.BASE_URL}?limit={limit}&format=json"
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            if "data" in data:
                result = []
                for e in data["data"]:
                    ts_raw = e.get("timestamp", "")
                    # Convert unix timestamp → human-readable date
                    try:
                        ts_int = int(ts_raw)
                        import datetime

                        date_str = datetime.datetime.fromtimestamp(
                            ts_int, tz=datetime.UTC
                        ).strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        date_str = ts_raw
                    result.append(
                        {
                            "value": int(e["value"]),
                            "classification": e["value_classification"],
                            "timestamp": ts_raw,
                            "date_str": date_str,
                        }
                    )
                return result
        except Exception as exc:
            logger.warning("FearGreedIndex.fetch_historical(%d) failed: %s", limit, exc)
        return []


# ---------------------------------------------------------------------------
# CryptoPanic Signal
# ---------------------------------------------------------------------------


class CryptoPanicSignal:
    """
    News sentiment from CryptoPanic API (free tier).

    Uses vote-based sentiment: posts with more positive votes produce a
    bullish signal. Requires CRYPTOPANIC_API_KEY environment variable.
    If not set, all methods gracefully return empty/None.

    API: https://cryptopanic.com/api/free/v1/posts/
    """

    BASE_URL = "https://cryptopanic.com/api/free/v1/posts/"
    _cache: ClassVar[dict[str, tuple[Any, float]]] = {}

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < _CACHE_TTL:
                return data
        return None

    def fetch(
        self,
        currencies: str = "BTC,ETH",
        filter_type: str = "rising",
        api_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch recent CryptoPanic posts for sentiment analysis.

        Returns list of post dicts with vote data. Empty list if unavailable.
        """
        import os

        key = api_key or os.getenv("CRYPTOPANIC_API_KEY")
        if not key:
            logger.debug("CryptoPanicSignal: CRYPTOPANIC_API_KEY not set, skipping")
            return []

        cache_key = f"{currencies}_{filter_type}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cast("list[dict[str, Any]]", cached)

        try:
            params = f"?auth_token={key}&currencies={currencies}&filter={filter_type}&public=true"
            url = self.BASE_URL + params
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            results: list[dict[str, Any]] = data.get("results", [])
            self._cache[cache_key] = (results, time.time())
            return results
        except Exception as exc:
            logger.debug("CryptoPanicSignal.fetch failed: %s", exc)
        return []

    def compute_sentiment(self, posts: list[dict[str, Any]]) -> float | None:
        """
        Compute directional sentiment from CryptoPanic vote aggregation.

        Aggregates positive/negative votes across all posts.
        Returns [-1.0, +1.0] or None if insufficient data.
        """
        if not posts:
            return None

        total_positive = 0
        total_negative = 0

        for post in posts:
            votes = post.get("votes") or {}
            total_positive += int(votes.get("positive", 0) or 0)
            total_negative += int(votes.get("negative", 0) or 0)
            # "liked" as half-weight positive, "disliked" as half-weight negative
            total_positive += int(votes.get("liked", 0) or 0) // 2
            total_negative += int(votes.get("disliked", 0) or 0) // 2

        total = total_positive + total_negative
        if total < 3:
            return None  # insufficient vote data

        # Directional: (positive - negative) / total, scaled slightly
        raw = (total_positive - total_negative) / total
        return max(-1.0, min(1.0, raw * 1.2))


# ---------------------------------------------------------------------------
# RSS Feed Sentiment
# ---------------------------------------------------------------------------

_BULLISH_KEYWORDS: frozenset[str] = frozenset(
    {
        "rally",
        "surge",
        "bull",
        "bullish",
        "adoption",
        "ath",
        "record",
        "gain",
        "gains",
        "rise",
        "rises",
        "rising",
        "pump",
        "moon",
        "breakout",
        "accumulate",
        "buy",
        "institutional",
        "etf",
        "approval",
        "partnership",
        "launch",
        "upgrade",
        "positive",
        "growth",
        "milestone",
        "support",
        "recovery",
        "rebound",
        "demand",
        "inflow",
        "accumulation",
        "soar",
        "soars",
        "soaring",
        "outperform",
        "strong",
        "optimism",
    }
)

_BEARISH_KEYWORDS: frozenset[str] = frozenset(
    {
        "crash",
        "bear",
        "bearish",
        "drop",
        "drops",
        "sell",
        "selloff",
        "decline",
        "hack",
        "hacked",
        "ban",
        "banned",
        "regulation",
        "dump",
        "collapse",
        "fear",
        "liquidation",
        "outflow",
        "fraud",
        "scam",
        "lawsuit",
        "fine",
        "warning",
        "risk",
        "loss",
        "loses",
        "probe",
        "investigation",
        "concern",
        "correction",
        "plunge",
        "plunges",
        "slump",
        "tumble",
        "tumbles",
        "weakness",
        "pessimism",
        "suspend",
        "suspended",
        "exploit",
        "stolen",
    }
)


class RSSNewsSentiment:
    """
    Parses RSS feeds from major crypto outlets and scores headlines via keyword
    sentiment analysis. No API key required. Uses stdlib urllib + regex only
    (no feedparser dependency).
    """

    FEEDS: ClassVar[list[str]] = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ]

    _cache: ClassVar[dict[str, tuple[Any, float]]] = {}

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < _CACHE_TTL:
                return data
        return None

    def fetch_headlines(self, max_items_per_feed: int = 20) -> list[str]:
        """
        Fetch and parse headlines from all configured RSS feeds.

        Returns combined list of headline strings.
        """
        cached = self._get_cached("headlines")
        if cached is not None:
            return cast("list[str]", cached)

        headlines: list[str] = []
        for feed_url in self.FEEDS:
            try:
                req = urllib.request.Request(
                    feed_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; omega-victoria/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    content = resp.read().decode("utf-8", errors="ignore")
                # Extract titles — handles both plain and CDATA-wrapped
                titles = re.findall(
                    r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                    content,
                    re.DOTALL,
                )
                # Skip first entry (feed title itself), take up to max_items_per_feed
                feed_headlines = [
                    t.strip() for t in titles[1 : max_items_per_feed + 1] if t.strip()
                ]
                headlines.extend(feed_headlines)
                logger.debug(
                    "RSSNewsSentiment: fetched %d headlines from %s",
                    len(feed_headlines),
                    feed_url,
                )
            except Exception as exc:
                logger.debug("RSSNewsSentiment: failed to fetch %s: %s", feed_url, exc)

        self._cache["headlines"] = (headlines, time.time())
        return headlines

    def score_headlines(self, headlines: list[str]) -> dict[str, float]:
        """
        Score headlines using bullish/bearish keyword matching.

        Returns dict with:
            bullish_count, bearish_count, neutral_count, sentiment_score [-1, +1]
        """
        bullish = 0
        bearish = 0
        neutral = 0

        for headline in headlines:
            words = frozenset(re.findall(r"\b[a-z]+\b", headline.lower()))
            b_hits = len(words & _BULLISH_KEYWORDS)
            br_hits = len(words & _BEARISH_KEYWORDS)

            if b_hits > br_hits:
                bullish += 1
            elif br_hits > b_hits:
                bearish += 1
            else:
                neutral += 1

        total = bullish + bearish + neutral
        if total == 0:
            return {
                "bullish_count": 0.0,
                "bearish_count": 0.0,
                "neutral_count": 0.0,
                "sentiment_score": 0.0,
            }

        # Directional: (bullish - bearish) / (bullish + bearish + 1)
        # Dampened by 0.7 — keyword scoring is noisy
        raw = (bullish - bearish) / (bullish + bearish + 1)
        sentiment_score = max(-1.0, min(1.0, raw * 0.7))

        return {
            "bullish_count": float(bullish),
            "bearish_count": float(bearish),
            "neutral_count": float(neutral),
            "sentiment_score": sentiment_score,
        }


# ---------------------------------------------------------------------------
# Composite NewsSignalProvider
# ---------------------------------------------------------------------------


class NewsSignalProvider:
    """
    Composite news & sentiment signal provider for Victoria.

    Combines three free data sources into a single SignalValue:
      1. Fear & Greed Index  — 50% weight (directional sentiment gauge)
      2. CryptoPanic votes   — 30% weight (if CRYPTOPANIC_API_KEY is set)
      3. RSS keyword scoring — 20% weight (CoinDesk + CoinTelegraph)

    Component weights are renormalized if a source is unavailable, ensuring
    the composite always sums to 1.0 across present sources.

    Directional convention (differs from SentimentSignal's contrarian F&G):
      Fear  (low F&G)  → negative signal  → bearish news environment
      Greed (high F&G) → positive signal  → bullish news environment

    The SentimentSignal in signals_advanced.py already handles the contrarian
    interpretation (extreme greed = reversal risk). This signal captures the
    directional narrative / media sentiment layer.
    """

    def __init__(self) -> None:
        self._fear_greed = FearGreedIndex()
        self._cryptopanic = CryptoPanicSignal()
        self._rss = RSSNewsSentiment()

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        """
        Compute composite news sentiment signal.

        The market_data parameter is accepted for interface compatibility with
        other signal classes. News data is always fetched externally (RSS, APIs).

        Returns
        -------
        SignalValue
            value      : [-1.0, +1.0] directional news sentiment
            confidence : [0.0, 1.0] based on source coverage + agreement
            regime_tag : descriptive regime string (see module docstring)
            raw        : {fear_greed_value, fg_signal, rss_signal, ...}
        """
        raw: dict[str, float] = {}
        component_signals: list[tuple[float, float]] = []  # (signal, weight)

        # ── 1. Fear & Greed Index ─────────────────────────────────────
        fg_val_int: int | None = None
        fg_data = FearGreedIndex.fetch_current()
        if fg_data is not None:
            fg_val_int = fg_data["value"]
            raw["fear_greed_value"] = float(fg_val_int)

            # Directional mapping: 0 → -1.0, 50 → 0.0, 100 → +1.0
            fg_signal = (fg_val_int - 50.0) / 50.0

            # 7-day trend boost: if sentiment improving/worsening, amplify
            fg_trend = FearGreedIndex.fetch_trend(days=7)
            if len(fg_trend) >= 4:
                recent_avg = statistics.mean(e["value"] for e in fg_trend[:3])
                older_avg = statistics.mean(e["value"] for e in fg_trend[3:7])
                trend_delta = recent_avg - older_avg
                raw["fear_greed_trend_delta"] = float(trend_delta)
                # Small trend amplifier: max ±0.15 boost
                fg_signal += (trend_delta / 100.0) * 0.3
            else:
                raw["fear_greed_trend_delta"] = 0.0

            fg_signal = max(-1.0, min(1.0, fg_signal))
            raw["fear_greed_signal"] = fg_signal
            component_signals.append((fg_signal, 0.50))
            logger.debug("F&G: value=%d signal=%.3f", fg_val_int, fg_signal)

        # ── 2. CryptoPanic ────────────────────────────────────────────
        posts = self._cryptopanic.fetch()
        if posts:
            cp_raw = self._cryptopanic.compute_sentiment(posts)
            if cp_raw is not None:
                raw["cryptopanic_sentiment"] = cp_raw
                raw["cryptopanic_post_count"] = float(len(posts))
                component_signals.append((cp_raw, 0.30))
                logger.debug("CryptoPanic: sentiment=%.3f posts=%d", cp_raw, len(posts))

        # ── 3. RSS Feed Sentiment ─────────────────────────────────────
        headlines = self._rss.fetch_headlines()
        if headlines:
            rss_scores = self._rss.score_headlines(headlines)
            rss_signal = rss_scores["sentiment_score"]
            raw["rss_bullish_count"] = rss_scores["bullish_count"]
            raw["rss_bearish_count"] = rss_scores["bearish_count"]
            raw["rss_headline_count"] = float(len(headlines))
            raw["rss_signal"] = rss_signal
            component_signals.append((rss_signal, 0.20))
            logger.debug(
                "RSS: signal=%.3f bull=%d bear=%d headlines=%d",
                rss_signal,
                int(rss_scores["bullish_count"]),
                int(rss_scores["bearish_count"]),
                len(headlines),
            )

        # ── No data ───────────────────────────────────────────────────
        if not component_signals:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="news_no_data",
                raw=raw,
            )

        # ── Composite ─────────────────────────────────────────────────
        total_w = sum(w for _, w in component_signals)
        value = sum(s * w for s, w in component_signals) / total_w

        # Confidence: source coverage + directional agreement between sources
        coverage = len(component_signals) / 3.0
        if len(component_signals) > 1:
            sign_vals = [s for s, _ in component_signals]
            pos = sum(1 for s in sign_vals if s > 0.05)
            neg = sum(1 for s in sign_vals if s < -0.05)
            agreement = max(pos, neg) / len(sign_vals)
        else:
            agreement = 0.6  # single source — moderate confidence

        confidence = min(1.0, coverage * 0.5 + agreement * 0.5)

        # ── Regime tag ────────────────────────────────────────────────
        fg_int = fg_val_int if fg_val_int is not None else 50
        if fg_int >= 80 and value > 0.3:
            regime_tag = "news_euphoria"
        elif fg_int <= 20 and value < -0.3:
            regime_tag = "news_fearful"
        elif fg_int >= 75:
            regime_tag = "fg_extreme_greed"
        elif fg_int <= 25:
            regime_tag = "fg_extreme_fear"
        elif value > 0.1:
            regime_tag = "news_positive"
        elif value < -0.1:
            regime_tag = "news_negative"
        else:
            regime_tag = "news_neutral"

        raw["source_count"] = float(len(component_signals))
        raw["has_fear_greed"] = float(fg_val_int is not None)
        raw["has_cryptopanic"] = float(bool(posts))
        raw["has_rss"] = float(bool(headlines))

        return SignalValue(
            value=max(-1.0, min(1.0, value)),
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )

    @staticmethod
    def fetch_historical_fear_greed(limit: int = 365) -> list[dict[str, Any]]:
        """
        Fetch historical Fear & Greed data for backtesting.

        Parameters
        ----------
        limit : int
            Number of historical days (up to ~2500, typically 365 or 730).

        Returns
        -------
        list of dicts, newest-first:
            {value: int, classification: str, timestamp: str, date_str: str}

        Example (backtesting oldest→newest):
            history = NewsSignalProvider.fetch_historical_fear_greed(365)
            for entry in reversed(history):
                fg_val = entry["value"]
                date = entry["date_str"]
                signal = (fg_val - 50.0) / 50.0  # directional

        Notes
        -----
        alternative.me has data from 2018-02-01 onward.
        For GDELT-backed general news history, use the GDELT project API
        (https://api.gdeltproject.org) as a complementary data source.
        """
        return FearGreedIndex.fetch_historical(limit=limit)
