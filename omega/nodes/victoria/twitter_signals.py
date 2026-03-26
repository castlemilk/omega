"""
omega.nodes.victoria.twitter_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Twitter/X crypto sentiment signal for Victoria.

Signal sources (tried in priority order):
  1. X API v2 — if TWITTER_BEARER_TOKEN is set. Searches recent tweets for
     $BTC, $ETH, $SOL, crypto keywords from key influencer accounts.
  2. CryptoPanic public API — free tier, filters Twitter-sourced posts
     with bullish/bearish/hot classifications for BTC/ETH/SOL.
  3. Graceful degradation — returns zero-confidence signal if all sources fail.

Sentiment scoring:
  - Keyword bullish/bearish ratio → raw sentiment [-1, +1]
  - Engagement weight: posts with more votes/interactions weight more
  - Volume signal: spike in mentions → conviction boost

Output: SignalValue compatible with signals_advanced.SignalValue schema.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.twitter_signals")

# ---------------------------------------------------------------------------
# Sentiment keyword sets
# ---------------------------------------------------------------------------

_BULLISH_KEYWORDS = frozenset(
    [
        "moon",
        "bull",
        "bullish",
        "long",
        "buy",
        "breakout",
        "rally",
        "pump",
        "ath",
        "accumulate",
        "uptrend",
        "higher",
        "rip",
        "fomo",
        "green",
        "bottom",
        "rebound",
        "recovery",
        "squeeze",
        "reversal",
        "🚀",
        "📈",
    ]
)
_BEARISH_KEYWORDS = frozenset(
    [
        "dump",
        "crash",
        "bear",
        "bearish",
        "short",
        "sell",
        "breakdown",
        "correction",
        "rekt",
        "panic",
        "capitulate",
        "lower",
        "downtrend",
        "resistance",
        "rejection",
        "distribution",
        "red",
        "🔴",
        "📉",
        "💀",
    ]
)

# Key crypto influencer X account IDs (for X API v2 if token is available)
# Listed by approximate follower reach; used in `from:` query filter
_INFLUENCER_HANDLES = [
    "100trillionUSD",  # PlanB — stock-to-flow model author
    "woonomic",  # Willy Woo — on-chain analyst
    "APompliano",  # Anthony Pompliano — Bitcoin advocate
    "CryptoCobain",  # Crypto trader / analyst
    "RaoulGMI",  # Raoul Pal — macro + crypto
    "michael_saylor",  # MicroStrategy BTC advocate
    "CryptoKaleo",  # Technical trader
    "inversebrah",  # Crypto trader / sentiment
    "AltcoinSherpa",  # Alt-season analyst
    "scott_lew_is",  # Scott Lewis — DeFi / crypto VC
    "CryptoGodJohn",  # BTC / macro trader
    "KoroushAK",  # Technical analyst
    "CryptoCapo_",  # Technical / macro analyst
    "PeterLBrandt",  # Veteran commodities / BTC chartist
    "VentureCoinist",  # Crypto venture / trader
]

_CACHE_TTL_SEC = 900  # 15 minutes — respect rate limits
_CRYPTOPANIC_URL = (
    "https://cryptopanic.com/api/v1/posts/"
    "?public=true&currencies=BTC,ETH,SOL&kind=twitter&filter=hot"
)
_CRYPTOPANIC_SENTIMENT_URL = (
    "https://cryptopanic.com/api/v1/posts/?public=true&currencies=BTC,ETH,SOL&filter=bullish"
)
_TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"


@dataclass
class SignalValue:
    """Output of a signal computation (mirrors signals_advanced.SignalValue)."""

    value: float  # -1.0 (bear) to +1.0 (bull)
    confidence: float  # 0.0 to 1.0
    regime_tag: str
    raw: dict[str, float]


class TwitterSentimentSignal:
    """
    Twitter/X crypto sentiment signal.

    Aggregates public social sentiment from Twitter via:
      1. X API v2 bearer token (if configured)
      2. CryptoPanic public API (Twitter-sourced posts)

    Produces a SignalValue in the range [-1, +1].
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}  # key → (timestamp, data)
        self._bearer_token: str | None = os.getenv("TWITTER_BEARER_TOKEN")
        self._cryptopanic_token: str | None = os.getenv("CRYPTOPANIC_API_TOKEN")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        """
        Compute Twitter/X sentiment signal.

        market_data may contain:
          _twitter_sentiment : pre-fetched sentiment dict (from DataIngestionNode)

        Falls back to live API calls if not pre-fetched.
        """
        # Accept pre-injected data from DataIngestionNode
        injected = market_data.get("_twitter_sentiment")
        if isinstance(injected, dict) and injected:
            return self._score_from_posts(injected.get("posts", []), injected)

        # Try live sources in priority order
        posts, meta = self._fetch_sentiment()
        return self._score_from_posts(posts, meta)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_sentiment(self) -> tuple[list[dict], dict[str, Any]]:
        """Fetch posts from the best available source. Returns (posts, meta)."""
        # Source 1: X API v2 (requires TWITTER_BEARER_TOKEN)
        if self._bearer_token:
            try:
                result = self._fetch_twitter_v2()
                if result:
                    return result, {"source": "twitter_v2", "post_count": len(result)}
            except Exception as exc:
                logger.debug("Twitter v2 fetch failed: %s", exc)

        # Source 2: CryptoPanic (requires CRYPTOPANIC_API_TOKEN or public tier)
        try:
            result = self._fetch_cryptopanic()
            if result:
                return result, {"source": "cryptopanic", "post_count": len(result)}
        except Exception as exc:
            logger.debug("CryptoPanic fetch failed: %s", exc)

        # Source 3: Alternative.me Fear & Greed as social proxy (always free)
        # Maps aggregate crowd sentiment to synthetic tweet-like posts so the
        # signal produces a non-zero value even without social API keys.
        try:
            result = self._fetch_fear_greed_proxy()
            if result:
                return result, {"source": "fear_greed_proxy", "post_count": len(result)}
        except Exception as exc:
            logger.debug("Fear&Greed proxy fetch failed: %s", exc)

        return [], {"source": "none", "post_count": 0}

    def _fetch_twitter_v2(self) -> list[dict]:
        """Fetch recent tweets via X API v2 Bearer token."""
        cache_key = "twitter_v2"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL_SEC:
            return list(cached[1])

        # Build query: crypto keywords + cashtags from influencer accounts
        influencer_query = " OR ".join(f"from:{h}" for h in _INFLUENCER_HANDLES[:8])
        query = (
            f"($BTC OR $ETH OR $SOL OR bitcoin OR crypto) ({influencer_query}) -is:retweet lang:en"
        )
        params = urllib.parse.urlencode(
            {
                "query": query,
                "max_results": 50,
                "tweet.fields": "public_metrics,created_at,author_id",
            }
        )
        url = f"{_TWITTER_SEARCH_URL}?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._bearer_token}",
                "User-Agent": "omega-victoria/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tweets = data.get("data", [])
        posts = []
        for t in tweets:
            metrics = t.get("public_metrics", {})
            posts.append(
                {
                    "text": t.get("text", ""),
                    "votes_up": metrics.get("like_count", 0),
                    "votes_down": 0,
                    "retweets": metrics.get("retweet_count", 0),
                    "source": "twitter_v2",
                }
            )

        self._cache[cache_key] = (time.time(), posts)
        return posts

    def _fetch_cryptopanic(self) -> list[dict]:
        """Fetch Twitter-sourced posts from CryptoPanic public API."""
        cache_key = "cryptopanic_twitter"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL_SEC:
            return list(cached[1])

        # Build URL — append auth token if available for higher rate limit
        url = _CRYPTOPANIC_URL
        if self._cryptopanic_token:
            url += f"&auth_token={self._cryptopanic_token}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; omega-victoria/1.0)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        posts = []
        for item in results:
            votes = item.get("votes", {}) or {}
            posts.append(
                {
                    "text": item.get("title", ""),
                    "votes_up": int(votes.get("positive", 0) or 0),
                    "votes_down": int(votes.get("negative", 0) or 0),
                    "retweets": int(votes.get("saved", 0) or 0),
                    "kind": item.get("kind", ""),
                    "source": "cryptopanic",
                    # CryptoPanic pre-labels some posts as bullish/bearish
                    "is_bullish": bool(
                        item.get("kind") == "bullish"
                        or votes.get("positive", 0) > votes.get("negative", 0) * 2
                    ),
                    "is_bearish": bool(
                        item.get("kind") == "bearish"
                        or votes.get("negative", 0) > votes.get("positive", 0) * 2
                    ),
                }
            )

        self._cache[cache_key] = (time.time(), posts)
        logger.debug("CryptoPanic: fetched %d Twitter posts", len(posts))
        return posts

    def _fetch_fear_greed_proxy(self) -> list[dict]:
        """
        Fallback: synthesise tweet-like posts from Alternative.me Fear & Greed Index.

        This gives the signal a non-zero value when no social API keys are set.
        The F&G index is a crowd-sentiment composite (survey + social + momentum),
        so it partially proxies Twitter crowd mood.  Confidence is capped at 0.45
        to reflect that it is not direct Twitter data.
        """
        cache_key = "fear_greed_proxy"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL_SEC:
            return list(cached[1])

        url = "https://api.alternative.me/fng/?limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        entries = data.get("data", [])
        if not entries:
            return []

        posts = []
        for entry in entries:
            value = int(entry.get("value", 50))
            label = entry.get("value_classification", "Neutral").lower()

            # Translate F&G score to directional text + keyword weight
            if value >= 75:
                text = "crypto bull greed rally moon ath pump buy accumulate"
                is_bullish, is_bearish = True, False
                votes_up = value
            elif value >= 55:
                text = "bitcoin bullish uptrend buy"
                is_bullish, is_bearish = True, False
                votes_up = value // 2
            elif value <= 25:
                text = "crypto panic fear crash dump sell correction rekt bear"
                is_bullish, is_bearish = False, True
                votes_up = 100 - value
            elif value <= 45:
                text = "bitcoin bearish downtrend correction"
                is_bullish, is_bearish = False, True
                votes_up = (100 - value) // 2
            else:
                text = "bitcoin neutral market"
                is_bullish, is_bearish = False, False
                votes_up = 10

            posts.append(
                {
                    "text": text,
                    "votes_up": votes_up,
                    "votes_down": 0,
                    "retweets": votes_up // 3,
                    "is_bullish": is_bullish,
                    "is_bearish": is_bearish,
                    "source": "fear_greed_proxy",
                    "_fg_value": value,
                    "_fg_label": label,
                }
            )

        self._cache[cache_key] = (time.time(), posts)
        logger.debug(
            "F&G proxy: fg=%d (%s) → %d synthetic posts",
            entries[0].get("value", 50),
            entries[0].get("value_classification", "?"),
            len(posts),
        )
        return posts

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_from_posts(self, posts: list[dict], meta: dict[str, Any]) -> SignalValue:
        """Compute sentiment signal from a list of post dicts."""
        raw: dict[str, float] = {}

        if not posts:
            raw["post_count"] = 0.0
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_data",
                raw=raw,
            )

        raw["post_count"] = float(len(posts))
        raw["source_type"] = 1.0 if meta.get("source") == "twitter_v2" else 0.5

        # Score each post for bullish/bearish keywords
        bull_weight = 0.0
        bear_weight = 0.0
        total_weight = 0.0
        pre_labeled_bull = 0
        pre_labeled_bear = 0

        for post in posts:
            text = post.get("text", "").lower()
            votes_up = float(post.get("votes_up", 0) or 0)
            votes_down = float(post.get("votes_down", 0) or 0)
            retweets = float(post.get("retweets", 0) or 0)

            # Engagement weight: log-scaled to prevent single viral tweet domination
            engagement = 1.0 + math.log1p(votes_up + retweets * 1.5)

            # Keyword scoring
            words = set(text.split())
            bull_hits = len(words & _BULLISH_KEYWORDS)
            bear_hits = len(words & _BEARISH_KEYWORDS)

            # Pre-labeled (CryptoPanic kind field or vote ratio)
            if post.get("is_bullish"):
                bull_hits = max(bull_hits, 1)
                pre_labeled_bull += 1
            if post.get("is_bearish"):
                bear_hits = max(bear_hits, 1)
                pre_labeled_bear += 1

            # Penalise posts that are clearly downvoted
            if votes_down > votes_up * 2:
                engagement *= 0.3

            if bull_hits > 0 or bear_hits > 0:
                net = bull_hits - bear_hits
                bull_weight += max(0.0, net) * engagement
                bear_weight += max(0.0, -net) * engagement
                total_weight += abs(net) * engagement

        # Aggregate sentiment score
        if total_weight > 0:
            raw_sentiment = (bull_weight - bear_weight) / total_weight
        else:
            # Fall back to pre-labeled ratio if available
            total_labeled = pre_labeled_bull + pre_labeled_bear
            if total_labeled > 0:
                raw_sentiment = (pre_labeled_bull - pre_labeled_bear) / total_labeled
            else:
                raw_sentiment = 0.0

        raw["bull_weight"] = round(bull_weight, 2)
        raw["bear_weight"] = round(bear_weight, 2)
        raw["pre_labeled_bull"] = float(pre_labeled_bull)
        raw["pre_labeled_bear"] = float(pre_labeled_bear)
        raw["raw_sentiment"] = round(raw_sentiment, 4)

        # Clamp to [-1, +1]
        value = max(-1.0, min(1.0, raw_sentiment))

        # Confidence: more posts + clear signal = higher confidence
        n = len(posts)
        volume_conf = min(1.0, n / 30.0)  # full confidence at 30+ posts
        signal_strength = abs(value)
        confidence = 0.2 + volume_conf * 0.5 + signal_strength * 0.3
        # F&G proxy is indirect — cap lower than real social data
        if meta.get("source") == "fear_greed_proxy":
            confidence = min(0.45, confidence)
        else:
            confidence = min(0.85, confidence)  # cap at 0.85 — social is noisy

        # Regime tag
        if value >= 0.5:
            regime_tag = "twitter_euphoric"
        elif value >= 0.2:
            regime_tag = "twitter_bullish"
        elif value <= -0.5:
            regime_tag = "twitter_panic"
        elif value <= -0.2:
            regime_tag = "twitter_bearish"
        else:
            regime_tag = "twitter_neutral"

        raw["confidence"] = round(confidence, 3)
        logger.debug(
            "TwitterSentiment: posts=%d value=%.3f confidence=%.3f regime=%s source=%s",
            n,
            value,
            confidence,
            regime_tag,
            meta.get("source", "?"),
        )
        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )
