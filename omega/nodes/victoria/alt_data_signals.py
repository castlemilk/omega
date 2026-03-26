"""
omega.nodes.victoria.alt_data_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Alternative data signal provider for Victoria.

Signals:
  - GoogleTrendsSignal    : retail sentiment via search volume z-scores
  - GitHubActivitySignal  : developer activity via commit velocity MAs
  - AppStoreProxySignal   : app store rank proxy via Google Trends

All signals cache results to avoid hammering rate-limited external APIs.
Composite weighting: Google Trends (0.4), GitHub (0.3), App Store proxy (0.3).
"""

from __future__ import annotations

import logging
import math
import statistics
import time

logger = logging.getLogger("omega.nodes.victoria.alt_data_signals")

_EPSILON = 1e-9

# Cache TTLs
_TRENDS_CACHE_TTL = 4 * 3600  # 4 hours
_GITHUB_CACHE_TTL = 6 * 3600  # 6 hours

# Composite weights
_W_TRENDS = 0.4
_W_GITHUB = 0.3
_W_APPSTORE = 0.3

# Z-score threshold for FOMO/panic detection
_ZSCORE_FOMO_THRESHOLD = 2.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _zscore_latest(values: list[float]) -> float | None:
    """Z-score of the last value vs. the full window."""
    if len(values) < 4:
        return None
    mu = statistics.mean(values)
    sigma = statistics.pstdev(values)
    if sigma < _EPSILON:
        return 0.0
    return (values[-1] - mu) / sigma


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# SignalValue (mirrors signals_advanced.SignalValue to avoid circular import)
# ---------------------------------------------------------------------------


class _SignalValue:
    """Lightweight signal value container."""

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


def _unavailable(reason: str) -> _SignalValue:
    return _SignalValue(value=0.0, confidence=0.0, regime_tag="unavailable", raw={reason: 0.0})


# ---------------------------------------------------------------------------
# GoogleTrendsSignal
# ---------------------------------------------------------------------------

_TRENDS_KEYWORDS = ["buy bitcoin", "bitcoin crash", "crypto", "bitcoin price"]


class GoogleTrendsSignal:
    """
    Contrarian sentiment signal derived from Google Trends search volume.

    Logic:
      - High z-score on "buy bitcoin" (> 2.0) → retail FOMO → contrarian SELL (-1)
      - High z-score on "bitcoin crash" (> 2.0) → retail panic → contrarian BUY (+1)
      - Sentiment oscillator = log("buy bitcoin" avg / ("bitcoin crash" avg + ε))
        maps to a mild [-0.3, +0.3] directional bias when no extreme z-score fires
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _TRENDS_CACHE_TTL and self._cached is not None:
            return self._cached

        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pytrends.build_payload(_TRENDS_KEYWORDS, timeframe="today 3-m", geo="")
            df = pytrends.interest_over_time()

            if df.empty:
                result = _unavailable("empty_response")
                self._cached = result
                self._cache_ts = now
                return result

            buy_series = [float(v) for v in df["buy bitcoin"].tolist()]
            crash_series = [float(v) for v in df["bitcoin crash"].tolist()]

            buy_z = _zscore_latest(buy_series)
            crash_z = _zscore_latest(crash_series)

            buy_avg = statistics.mean(buy_series) if buy_series else 1.0
            crash_avg = statistics.mean(crash_series) if crash_series else 1.0
            oscillator = _clamp(math.log(buy_avg / (crash_avg + _EPSILON)) / 2.0)

            raw: dict[str, float] = {
                "buy_bitcoin_latest": buy_series[-1] if buy_series else 0.0,
                "bitcoin_crash_latest": crash_series[-1] if crash_series else 0.0,
                "buy_bitcoin_zscore": float(buy_z) if buy_z is not None else 0.0,
                "bitcoin_crash_zscore": float(crash_z) if crash_z is not None else 0.0,
                "sentiment_oscillator": oscillator,
            }

            value = 0.0
            confidence = 0.3
            regime_tag = "neutral"

            if buy_z is not None and buy_z > _ZSCORE_FOMO_THRESHOLD:
                # Retail FOMO → contrarian sell
                magnitude = min(1.0, (buy_z - _ZSCORE_FOMO_THRESHOLD) / 2.0)
                value = -magnitude
                confidence = min(0.9, 0.5 + magnitude * 0.4)
                regime_tag = "fomo_sell"
            elif crash_z is not None and crash_z > _ZSCORE_FOMO_THRESHOLD:
                # Retail panic → contrarian buy
                magnitude = min(1.0, (crash_z - _ZSCORE_FOMO_THRESHOLD) / 2.0)
                value = magnitude
                confidence = min(0.9, 0.5 + magnitude * 0.4)
                regime_tag = "panic_buy"
            else:
                # Mild contrarian bias from oscillator (inverted: high "buy" → sell)
                value = _clamp(-oscillator * 0.3)
                confidence = 0.3
                regime_tag = "mild_contrarian"

            result = _SignalValue(
                value=value, confidence=confidence, regime_tag=regime_tag, raw=raw
            )
            self._cached = result
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("GoogleTrendsSignal fetch failed: %s", exc)
            if self._cached is not None:
                logger.debug("GoogleTrendsSignal: returning stale cache")
                return self._cached
            return _unavailable("fetch_error")


# ---------------------------------------------------------------------------
# GitHubActivitySignal
# ---------------------------------------------------------------------------

_GITHUB_REPOS = [
    ("bitcoin", "bitcoin"),
    ("ethereum", "go-ethereum"),
]
_GITHUB_API = "https://api.github.com"


class GitHubActivitySignal:
    """
    Developer activity signal based on commit velocity.

    Logic:
      - Fetch 52-week commit counts via GitHub stats API (unauthenticated)
      - 4-week MA vs. 12-week MA of weekly commits per repo
      - 4w > 12w (rising activity) → bullish (+)
      - 4w < 12w (declining activity) → bearish (-)
      - Magnitude = log(4w_MA / (12w_MA + ε)) * 2, clamped to [-1, +1]
      - Composite = mean across repos
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _GITHUB_CACHE_TTL and self._cached is not None:
            return self._cached

        try:
            import json as _json
            import urllib.request

            repo_signals: list[float] = []
            raw: dict[str, float] = {}

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "omega-victoria-node/1.0",
            }

            for owner, repo in _GITHUB_REPOS:
                url = f"{_GITHUB_API}/repos/{owner}/{repo}/stats/commit_activity"
                req = urllib.request.Request(url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        if resp.status == 202:
                            # GitHub is still computing stats — skip this repo
                            logger.debug("GitHub stats for %s/%s not ready (202)", owner, repo)
                            continue
                        data = _json.loads(resp.read().decode())
                except Exception as repo_exc:
                    logger.debug("GitHub fetch failed for %s/%s: %s", owner, repo, repo_exc)
                    continue

                # data = list of 52 weekly objects {week, total, days}
                weekly_counts = [int(w.get("total", 0)) for w in data]
                if len(weekly_counts) < 12:
                    continue

                ma4 = statistics.mean(weekly_counts[-4:])
                ma12 = statistics.mean(weekly_counts[-12:])

                key = f"{owner}_{repo}"
                raw[f"{key}_ma4"] = round(ma4, 2)
                raw[f"{key}_ma12"] = round(ma12, 2)

                if ma12 < _EPSILON:
                    repo_signal = 0.0
                else:
                    repo_signal = _clamp(math.log(ma4 / (ma12 + _EPSILON)) * 2.0)

                raw[f"{key}_signal"] = repo_signal
                repo_signals.append(repo_signal)

            if not repo_signals:
                result = _unavailable("no_repo_data")
                self._cached = result
                self._cache_ts = now
                return result

            composite = sum(repo_signals) / len(repo_signals)
            confidence = min(0.8, 0.4 + len(repo_signals) * 0.2)
            regime_tag = (
                "rising_dev"
                if composite > 0.1
                else ("declining_dev" if composite < -0.1 else "stable_dev")
            )

            result = _SignalValue(
                value=_clamp(composite),
                confidence=confidence,
                regime_tag=regime_tag,
                raw=raw,
            )
            self._cached = result
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("GitHubActivitySignal fetch failed: %s", exc)
            if self._cached is not None:
                logger.debug("GitHubActivitySignal: returning stale cache")
                return self._cached
            return _unavailable("fetch_error")


# ---------------------------------------------------------------------------
# AppStoreProxySignal
# ---------------------------------------------------------------------------

_APPSTORE_KEYWORDS = ["coinbase app", "crypto app", "bitcoin wallet"]


class AppStoreProxySignal:
    """
    App store ranking proxy using Google Trends for crypto app search volume.

    Logic:
      - High z-score on "coinbase app" (> 2.0) = peak retail FOMO → contrarian sell
      - Low z-score (< -2.0) = app abandonment → potential recovery buy signal
      - Shares the 4-hour cache TTL
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _TRENDS_CACHE_TTL and self._cached is not None:
            return self._cached

        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pytrends.build_payload(_APPSTORE_KEYWORDS, timeframe="today 3-m", geo="")
            df = pytrends.interest_over_time()

            if df.empty:
                result = _unavailable("empty_response")
                self._cached = result
                self._cache_ts = now
                return result

            coinbase_series = [float(v) for v in df["coinbase app"].tolist()]
            coinbase_z = _zscore_latest(coinbase_series)

            raw: dict[str, float] = {
                "coinbase_app_latest": coinbase_series[-1] if coinbase_series else 0.0,
                "coinbase_app_zscore": float(coinbase_z) if coinbase_z is not None else 0.0,
            }

            if "bitcoin wallet" in df.columns:
                wallet_series = [float(v) for v in df["bitcoin wallet"].tolist()]
                wallet_z = _zscore_latest(wallet_series)
                raw["bitcoin_wallet_zscore"] = float(wallet_z) if wallet_z is not None else 0.0

            value = 0.0
            confidence = 0.3
            regime_tag = "neutral_app"

            if coinbase_z is not None and coinbase_z > _ZSCORE_FOMO_THRESHOLD:
                magnitude = min(1.0, (coinbase_z - _ZSCORE_FOMO_THRESHOLD) / 2.0)
                value = -magnitude  # contrarian sell
                confidence = min(0.85, 0.4 + magnitude * 0.45)
                regime_tag = "app_fomo_sell"
            elif coinbase_z is not None and coinbase_z < -_ZSCORE_FOMO_THRESHOLD:
                magnitude = min(1.0, (-coinbase_z - _ZSCORE_FOMO_THRESHOLD) / 2.0)
                value = magnitude  # apps being abandoned → potential recovery
                confidence = min(0.6, 0.3 + magnitude * 0.3)
                regime_tag = "app_abandonment_buy"

            result = _SignalValue(
                value=value, confidence=confidence, regime_tag=regime_tag, raw=raw
            )
            self._cached = result
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("AppStoreProxySignal fetch failed: %s", exc)
            if self._cached is not None:
                logger.debug("AppStoreProxySignal: returning stale cache")
                return self._cached
            return _unavailable("fetch_error")


# ---------------------------------------------------------------------------
# AltDataSignalProvider — composite
# ---------------------------------------------------------------------------


class AltDataSignalProvider:
    """
    Composite alternative data signal for Victoria.

    Blends:
      - GoogleTrendsSignal   (weight 0.4) — retail FOMO/panic contrarian
      - GitHubActivitySignal (weight 0.3) — developer ecosystem health
      - AppStoreProxySignal  (weight 0.3) — app download proxy via Trends

    Returns a single _SignalValue with value ∈ [-1, +1].
    Unavailable sub-signals are excluded and weights renormalized.

    Usage::
        provider = AltDataSignalProvider()
        sv = provider.compute()
        # sv.value       : composite conviction ∈ [-1, +1]
        # sv.confidence  : blended confidence
        # sv.regime_tag  : dominant sub-signal's regime
        # sv.raw         : per-subsignal breakdown
    """

    def __init__(self) -> None:
        self._trends = GoogleTrendsSignal()
        self._github = GitHubActivitySignal()
        self._appstore = AppStoreProxySignal()

    def compute(self) -> _SignalValue:
        """Fetch all sub-signals and return blended composite."""
        sub_signals: list[tuple[float, _SignalValue]] = [
            (_W_TRENDS, self._trends.fetch()),
            (_W_GITHUB, self._github.fetch()),
            (_W_APPSTORE, self._appstore.fetch()),
        ]

        available = [(w, sv) for w, sv in sub_signals if sv.confidence > 0.0]

        if not available:
            return _unavailable("all_sources_unavailable")

        total_w = sum(w for w, _ in available)
        composite_value = sum(w * sv.value for w, sv in available) / total_w
        composite_confidence = sum(w * sv.confidence for w, sv in available) / total_w

        dominant = max(available, key=lambda x: x[1].confidence)
        regime_tag = dominant[1].regime_tag

        raw: dict[str, float] = {
            "trends_value": sub_signals[0][1].value,
            "trends_confidence": sub_signals[0][1].confidence,
            "github_value": sub_signals[1][1].value,
            "github_confidence": sub_signals[1][1].confidence,
            "appstore_value": sub_signals[2][1].value,
            "appstore_confidence": sub_signals[2][1].confidence,
            "available_sources": float(len(available)),
        }

        return _SignalValue(
            value=_clamp(composite_value),
            confidence=min(1.0, composite_confidence),
            regime_tag=regime_tag,
            raw=raw,
        )
