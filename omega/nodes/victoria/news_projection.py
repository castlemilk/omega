"""
omega.nodes.victoria.news_projection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
News-projection layer for Victoria.

Translates current news/sentiment context into per-signal soft priors that
adjust the DynamicWeightAllocator's IC estimates.

Concept
-------
FinBERT embeddings (here approximated by keyword-category classification)
are projected onto a per-signal "news relevance" axis.  For each news topic
category, we maintain a learned mapping to which signals have historically
been IC-positive when that category dominates the news:

  news_topic → {signal_name: relevance_score}

A relevance_score > 1.0 means this signal is historically more predictive
when this topic is in the news.  A score < 1.0 means the signal is less
predictive (noise increases in this news environment).

This is used by VictoriaNode to adjust signal weights after the base IC
update, giving the system a news-aware signal relevance prior each cycle.

Algorithm
---------
1. Classify the current news context into topic categories.
   Input: FinBERT signal's raw output (sentiment_score, keyword_counts, etc.)
   or a raw news text dict.

2. For each active topic, look up the relevance mapping.

3. Blend topic relevances into per-signal multipliers using topic confidence
   weights.

4. Return NewsProjectionResult with per-signal multipliers and metadata.

Design Principles
-----------------
- No ML dependencies — pure Python + stdlib.
- Zero-shot: works before any labeled data is accumulated.
- Soft priors: multipliers ∈ [0.70, 1.30] so they never override the IC
  signal entirely.
- Composable: designed to feed into DynamicWeightAllocator.apply_news_prior()
  which must be called explicitly.
- Graceful degradation: returns all-ones on missing/empty input.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.news_projection")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum multiplier deviation from 1.0 (symmetric).
# 1.30 = 30% boost at maximum alignment; 0.70 = 30% reduction.
_MAX_BOOST = 1.30
_MIN_BOOST = 0.70

# Minimum topic confidence to apply the multiplier.
_MIN_TOPIC_CONFIDENCE = 0.10

# Blending: how much to mix news prior vs flat (1.0).
# Higher alpha = stronger news influence on weights.
_BLEND_ALPHA = 0.40  # 40% news prior, 60% flat

# Smoothing: EMA factor for the per-signal multiplier history.
_EMA_ALPHA = 0.30


# ---------------------------------------------------------------------------
# Topic categories
# ---------------------------------------------------------------------------

# Topic keywords → topic label mapping.
# These mirror the categories in finbert_sentiment.py but at a higher level.
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "macro": [
        "fed",
        "interest rate",
        "inflation",
        "cpi",
        "fomc",
        "treasury",
        "macro",
        "gdp",
        "recession",
        "yield curve",
        "dollar",
        "yen",
        "monetary policy",
        "quantitative",
        "easing",
        "tightening",
    ],
    "liquidation": [
        "liquidat",
        "long squeeze",
        "short squeeze",
        "margin call",
        "cascade",
        "forced sell",
        "deleverag",
        "stop hunt",
        "wipe out",
        "flush",
    ],
    "derivatives": [
        "funding rate",
        "open interest",
        "futures premium",
        "basis",
        "options",
        "implied vol",
        "put call",
        "deribit",
        "perp",
        "perpetual",
        "derivatives",
        "leverage",
        "liq price",
    ],
    "whale": [
        "whale",
        "large holder",
        "institutional",
        "etf",
        "spot etf",
        "custody",
        "blackrock",
        "fidelity",
        "accumulation",
        "distribution",
        "exchange flow",
        "outflow",
        "inflow",
        "coinbase premium",
    ],
    "sentiment": [
        "fear",
        "greed",
        "euphoria",
        "panic",
        "fomo",
        "retail",
        "social media",
        "twitter",
        "reddit",
        "sentiment",
        "narrative",
        "hype",
        "mania",
        "capitulation",
    ],
    "technical": [
        "support",
        "resistance",
        "breakout",
        "breakdown",
        "momentum",
        "trend",
        "rsi",
        "macd",
        "bollinger",
        "moving average",
        "pattern",
        "elliott wave",
        "fibonacci",
        "technical analysis",
    ],
    "onchain": [
        "on-chain",
        "onchain",
        "blockchain",
        "miners",
        "hashrate",
        "wallet",
        "address",
        "utxo",
        "stablecoin",
        "usdt",
        "usdc",
        "supply",
        "circulation",
        "inactive",
        "long-term holder",
        "nvt",
    ],
    "news_positive": [
        "bullish",
        "rally",
        "surge",
        "all-time high",
        "ath",
        "adoption",
        "partnership",
        "launch",
        "upgrade",
        "approval",
        "regulation positive",
    ],
    "news_negative": [
        "bearish",
        "crash",
        "dump",
        "hack",
        "exploit",
        "sec",
        "ban",
        "regulation negative",
        "collapse",
        "fraud",
        "bankruptcy",
    ],
}

# ---------------------------------------------------------------------------
# Topic → Signal relevance matrix
# ---------------------------------------------------------------------------
# Per-topic relevance scores for each signal type.
# Values > 1.0 = signal is more predictive when this topic dominates.
# Values < 1.0 = signal is less predictive (noisy) in this news context.
#
# Design rationale:
#   - "macro": cross_asset, sentiment, carry most relevant; momentum less so
#   - "liquidation": whale_flow, order_flow, long_short_ratio are leading
#   - "derivatives": carry, vrp, smart_money are most informative
#   - "whale": whale_flow, smart_money, onchain are directly on-topic
#   - "sentiment": sentiment, finbert_sentiment, market_data most relevant
#   - "technical": basic_signals, momentum_factor, timeseries_forecast
#   - "onchain": onchain, whale_flow, stablecoin most informative
# ---------------------------------------------------------------------------

_TOPIC_SIGNAL_RELEVANCE: dict[str, dict[str, float]] = {
    "macro": {
        "cross_asset": 1.25,
        "sentiment": 1.20,
        "carry": 1.15,
        "market_data": 1.10,
        "momentum_factor": 0.85,
        "timeseries_forecast": 0.90,
        "spectral_graph": 1.10,
    },
    "liquidation": {
        "whale_flow": 1.25,
        "order_flow": 1.25,
        "long_short_ratio": 1.20,
        "carry": 1.15,
        "smart_money": 1.10,
        "basic_signals": 0.85,
        "onchain": 1.10,
    },
    "derivatives": {
        "carry": 1.30,
        "vrp": 1.25,
        "smart_money": 1.20,
        "long_short_ratio": 1.15,
        "sentiment": 1.10,
        "momentum_factor": 0.85,
    },
    "whale": {
        "whale_flow": 1.30,
        "smart_money": 1.25,
        "onchain": 1.20,
        "order_flow": 1.10,
        "btc_dominance": 1.05,
    },
    "sentiment": {
        "sentiment": 1.25,
        "finbert_sentiment": 1.25,
        "market_data": 1.15,
        "btc_dominance": 1.10,
        "alt_data": 1.10,
        "basic_signals": 0.90,
        "timeseries_forecast": 0.95,
    },
    "technical": {
        "basic_signals": 1.20,
        "momentum_factor": 1.25,
        "timeseries_forecast": 1.20,
        "cross_asset": 1.10,
        "pairs": 1.10,
        "rmt_signal": 1.05,
    },
    "onchain": {
        "onchain": 1.30,
        "whale_flow": 1.20,
        "btc_dominance": 1.10,
        "smart_money": 1.10,
        "sentiment": 1.05,
        "market_data": 1.05,
    },
    "news_positive": {
        "momentum_factor": 1.15,
        "finbert_sentiment": 1.10,
        "timeseries_forecast": 1.10,
        "cross_asset": 1.05,
    },
    "news_negative": {
        "vrp": 1.15,
        "whale_flow": 1.10,
        "order_flow": 1.10,
        "carry": 1.05,
        "finbert_sentiment": 1.10,
    },
}

# All known signal names — used to fill in neutral (1.0) for unspecified signals.
_ALL_SIGNALS = [
    "basic_signals",
    "order_flow",
    "cross_asset",
    "microstructure",
    "sentiment",
    "vrp",
    "market_data",
    "onchain",
    "long_short_ratio",
    "btc_dominance",
    "rmt_signal",
    "alt_data",
    "spectral_graph",
    "carry",
    "pairs",
    "momentum_factor",
    "timeseries_forecast",
    "smart_money",
    "finbert_sentiment",
    "whale_flow",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TopicScore:
    """Score for a single news topic."""

    topic: str
    confidence: float  # 0.0–1.0
    keyword_hits: int  # number of matching keywords found


@dataclass
class NewsProjectionResult:
    """Output of the news-projection layer."""

    # Per-signal multipliers: {signal_name: multiplier} where 1.0 = neutral.
    signal_multipliers: dict[str, float]
    # Active topics sorted by confidence desc.
    active_topics: list[TopicScore]
    # Overall news informativeness — how strongly news context is driving multipliers.
    news_strength: float  # 0.0–1.0
    # Dominant topic label, or "none" if below threshold.
    dominant_topic: str
    # Number of text tokens that contributed to classification.
    tokens_analysed: int


# ---------------------------------------------------------------------------
# Text classification helpers
# ---------------------------------------------------------------------------


def _lowercase_tokens(text: str) -> list[str]:
    """Lower-case, split on whitespace and punctuation."""
    import re

    return re.findall(r"[a-z0-9\-]+", text.lower())


def _score_topic(tokens: list[str], keywords: list[str]) -> tuple[float, int]:
    """
    Score how well a list of tokens matches a keyword list.

    Returns (confidence, hit_count).
    confidence is sigmoid-scaled so a few hits → moderate confidence,
    many hits → high confidence.
    """
    text_joined = " ".join(tokens)
    hits = sum(1 for kw in keywords if kw in text_joined)
    if hits == 0:
        return 0.0, 0
    # sigmoid: 1 hit → ~0.27, 3 hits → ~0.69, 5+ → ~0.82
    conf = 1.0 / (1.0 + math.exp(-hits + 2.0))
    return min(1.0, conf), hits


def _classify_topics(text: str) -> list[TopicScore]:
    """Classify text into topic scores, sorted by confidence descending."""
    tokens = _lowercase_tokens(text)
    if not tokens:
        return []

    results: list[TopicScore] = []
    for topic, keywords in _TOPIC_KEYWORDS.items():
        conf, hits = _score_topic(tokens, keywords)
        if conf >= _MIN_TOPIC_CONFIDENCE:
            results.append(TopicScore(topic=topic, confidence=conf, keyword_hits=hits))

    results.sort(key=lambda t: t.confidence, reverse=True)
    return results


def _extract_text_from_finbert_raw(finbert_raw: dict[str, Any]) -> str:
    """
    Extract news text / keyword context from FinBERT signal's raw dict.

    Looks for:
      - "headlines": list of headline strings
      - "keywords": list of matched keyword strings
      - "topics": list of topic labels
      - "top_headline": string
    """
    parts: list[str] = []

    headlines = finbert_raw.get("headlines") or finbert_raw.get("headline_texts", [])
    if isinstance(headlines, list):
        for h in headlines[:20]:  # top 20 headlines
            if isinstance(h, str):
                parts.append(h)

    keywords = finbert_raw.get("keywords") or finbert_raw.get("matched_keywords", [])
    if isinstance(keywords, list):
        parts.extend(str(k) for k in keywords[:30])

    topics = finbert_raw.get("topics", [])
    if isinstance(topics, list):
        parts.extend(str(t) for t in topics)

    top = finbert_raw.get("top_headline") or finbert_raw.get("summary", "")
    if isinstance(top, str) and top:
        parts.append(top)

    # Fallback: stringify the regime_tag (e.g. "news_fearful" → useful keywords)
    regime = finbert_raw.get("regime_tag") or finbert_raw.get("news_regime", "")
    if isinstance(regime, str) and regime:
        parts.append(regime.replace("_", " "))

    return " ".join(parts)


# ---------------------------------------------------------------------------
# NewsProjectionLayer
# ---------------------------------------------------------------------------


class NewsProjectionLayer:
    """
    Projects news/FinBERT context onto per-signal IC relevance priors.

    Usage::
        proj = NewsProjectionLayer()
        result = proj.project(finbert_raw=signal_data["finbert_sentiment"]["raw"])
        # result.signal_multipliers: {signal_name: float}

        # Optionally feed custom news text:
        result = proj.project(raw_text="Bitcoin ETF inflows surge; macro fear drives deleveraging")

    Integration with DynamicWeightAllocator:
        Call ``allocator.apply_news_prior(result.signal_multipliers, strength=result.news_strength)``
        after the normal ``update_ic_batch()`` call each cycle.
    """

    def __init__(
        self,
        signal_names: list[str] | None = None,
        blend_alpha: float = _BLEND_ALPHA,
        ema_alpha: float = _EMA_ALPHA,
    ) -> None:
        self._signal_names = list(signal_names or _ALL_SIGNALS)
        self._blend_alpha = blend_alpha
        self._ema_alpha = ema_alpha

        # EMA of per-signal multipliers across cycles (smooths out noisy news)
        self._multiplier_ema: dict[str, float] = {s: 1.0 for s in self._signal_names}
        self._call_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def project(
        self,
        finbert_raw: dict[str, Any] | None = None,
        raw_text: str = "",
        finbert_sentiment_score: float | None = None,
    ) -> NewsProjectionResult:
        """
        Project current news context onto per-signal relevance multipliers.

        Parameters
        ----------
        finbert_raw            : raw dict from FinBertSentimentSignal output
        raw_text               : raw news text to classify (alternative to finbert_raw)
        finbert_sentiment_score: overall sentiment score [-1, +1] from FinBERT signal

        Returns
        -------
        NewsProjectionResult with per-signal multipliers ∈ [0.70, 1.30].
        """
        self._call_count += 1

        # --- Step 1: Build text for topic classification ---
        text = raw_text
        if not text and finbert_raw:
            text = _extract_text_from_finbert_raw(finbert_raw)

        if not text:
            logger.debug("news_projection: no text — returning neutral multipliers")
            return self._neutral_result()

        tokens = _lowercase_tokens(text)
        if len(tokens) < 3:
            return self._neutral_result()

        # --- Step 2: Classify into topic scores ---
        topics = _classify_topics(text)
        if not topics:
            return self._neutral_result(tokens_analysed=len(tokens))

        # --- Step 3: Blend topic relevance scores into per-signal multipliers ---
        raw_multipliers: dict[str, float] = {s: 0.0 for s in self._signal_names}
        total_topic_weight = 0.0

        for topic_score in topics:
            if topic_score.confidence < _MIN_TOPIC_CONFIDENCE:
                continue
            relevance_map = _TOPIC_SIGNAL_RELEVANCE.get(topic_score.topic, {})
            w = topic_score.confidence
            total_topic_weight += w
            for signal in self._signal_names:
                rel = relevance_map.get(signal, 1.0)
                raw_multipliers[signal] += w * (rel - 1.0)  # accumulate deviation from 1.0

        if total_topic_weight < 1e-8:
            return self._neutral_result(active_topics=topics, tokens_analysed=len(tokens))

        # Normalise deviations
        for signal in self._signal_names:
            raw_multipliers[signal] = raw_multipliers[signal] / total_topic_weight

        # --- Step 4: Apply sentiment score directional bias ---
        # When overall sentiment is very positive/negative, boost momentum-aligned
        # signals and suppress contrarian signals slightly.
        if finbert_sentiment_score is not None:
            sentiment = max(-1.0, min(1.0, float(finbert_sentiment_score)))
            sentiment_mag = abs(sentiment)
            if sentiment_mag > 0.2:
                # Positive sentiment: boost momentum/trend signals
                if sentiment > 0:
                    raw_multipliers["momentum_factor"] += 0.10 * sentiment_mag
                    raw_multipliers["timeseries_forecast"] += 0.08 * sentiment_mag
                    raw_multipliers["finbert_sentiment"] += 0.05 * sentiment_mag
                else:
                    # Negative sentiment: boost defensive/vol signals
                    raw_multipliers["vrp"] += 0.10 * sentiment_mag
                    raw_multipliers["whale_flow"] += 0.08 * sentiment_mag
                    raw_multipliers["carry"] += 0.05 * sentiment_mag

        # --- Step 5: Blend with flat prior (1.0) using blend_alpha ---
        final_multipliers: dict[str, float] = {}
        for signal in self._signal_names:
            deviation = raw_multipliers[signal]
            # blend: blend_alpha * (1 + deviation) + (1 - blend_alpha) * 1.0
            blended = 1.0 + self._blend_alpha * deviation
            # Hard clamp to [_MIN_BOOST, _MAX_BOOST]
            clamped = max(_MIN_BOOST, min(_MAX_BOOST, blended))
            final_multipliers[signal] = clamped

        # --- Step 6: EMA smoothing to reduce cycle-by-cycle noise ---
        smoothed: dict[str, float] = {}
        for signal in self._signal_names:
            prev = self._multiplier_ema.get(signal, 1.0)
            new = final_multipliers[signal]
            ema_val = self._ema_alpha * new + (1.0 - self._ema_alpha) * prev
            self._multiplier_ema[signal] = ema_val
            smoothed[signal] = ema_val

        # --- Step 7: Metadata ---
        news_strength = min(1.0, total_topic_weight / max(1.0, len(topics)))
        dominant = topics[0].topic if topics else "none"

        logger.debug(
            "news_projection: topics=%s strength=%.3f dominant=%s top_signal=%s mult=%.3f",
            [(t.topic, round(t.confidence, 2)) for t in topics[:3]],
            news_strength,
            dominant,
            max(smoothed, key=lambda k: abs(smoothed[k] - 1.0), default="none"),
            max(abs(v - 1.0) for v in smoothed.values()) if smoothed else 0.0,
        )

        return NewsProjectionResult(
            signal_multipliers=smoothed,
            active_topics=topics,
            news_strength=news_strength,
            dominant_topic=dominant,
            tokens_analysed=len(tokens),
        )

    def project_from_signals(self, signals: dict[str, Any]) -> NewsProjectionResult:
        """
        Convenience method: extract FinBERT context from the computed signals dict.

        Looks for:
          - signals["finbert_sentiment"]["raw"]  → primary source
          - signals["finbert_sentiment"]["value"] → sentiment score
          - signals["market_data"]["raw"]        → fallback text
        """
        finbert_raw: dict[str, Any] = {}
        finbert_score: float | None = None

        fb_sig = signals.get("finbert_sentiment")
        if isinstance(fb_sig, dict):
            finbert_raw = fb_sig.get("raw") or {}
            if "value" in fb_sig:
                finbert_score = float(fb_sig["value"])

        # Fallback: market_data raw may contain news fields
        if not finbert_raw:
            md_sig = signals.get("market_data")
            if isinstance(md_sig, dict):
                finbert_raw = md_sig.get("raw") or {}

        return self.project(
            finbert_raw=finbert_raw,
            finbert_sentiment_score=finbert_score,
        )

    def get_multiplier_ema(self) -> dict[str, float]:
        """Return the current EMA of per-signal multipliers (for inspection)."""
        return dict(self._multiplier_ema)

    def reset_ema(self) -> None:
        """Reset EMA to neutral (1.0) for all signals."""
        for signal in self._signal_names:
            self._multiplier_ema[signal] = 1.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _neutral_result(
        self,
        active_topics: list[TopicScore] | None = None,
        tokens_analysed: int = 0,
    ) -> NewsProjectionResult:
        return NewsProjectionResult(
            signal_multipliers={s: self._multiplier_ema.get(s, 1.0) for s in self._signal_names},
            active_topics=active_topics or [],
            news_strength=0.0,
            dominant_topic="none",
            tokens_analysed=tokens_analysed,
        )
