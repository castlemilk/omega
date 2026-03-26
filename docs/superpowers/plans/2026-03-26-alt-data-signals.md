# Alt Data Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `AltDataSignalProvider` (Google Trends + GitHub Activity + App Store proxy) as a new composite signal wired into Victoria's `_do_compute_signals` pipeline with equal-weight IC initialization.

**Architecture:** Three sub-signals (GoogleTrendsSignal, GitHubActivitySignal, AppStoreProxySignal) composed inside AltDataSignalProvider, each returning a `SignalValue` and cached independently. AltDataSignalProvider exposes a single `compute() -> SignalValue` (no `market_data` arg) that blends them 0.4/0.3/0.3. Wired into victoria_node.py identically to the existing advanced signals.

**Tech Stack:** Python 3.11+, pytrends (Google Trends), GitHub REST API (unauthenticated), statistics stdlib, time-based in-memory cache.

---

### Task 1: Install pytrends

**Files:**
- No file changes, just pip install

- [ ] **Step 1: Install pytrends**

```bash
pip install pytrends --break-system-packages
```

Expected: `Successfully installed pytrends-...`

- [ ] **Step 2: Verify import**

```bash
python -c "from pytrends.request import TrendReq; print('ok')"
```

Expected: `ok`

---

### Task 2: Create alt_data_signals.py

**Files:**
- Create: `omega/nodes/victoria/alt_data_signals.py`

- [ ] **Step 1: Create the file**

```python
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
import statistics
import time
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.alt_data_signals")

_EPSILON = 1e-9

# Cache TTLs
_TRENDS_CACHE_TTL = 4 * 3600   # 4 hours
_GITHUB_CACHE_TTL = 6 * 3600   # 6 hours

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
    """Lightweight stand-in for SignalValue used internally."""

    __slots__ = ("value", "confidence", "regime_tag", "raw")

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
    return _SignalValue(value=0.0, confidence=0.0, regime_tag="unavailable", raw={"reason": 0.0})


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
      - Sentiment oscillator = "buy bitcoin" / ("bitcoin crash" + ε) maps to [-1, +1]
    """

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _TRENDS_CACHE_TTL and self._cache:
            return self._cache["result"]

        try:
            from pytrends.request import TrendReq  # type: ignore[import]

            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pytrends.build_payload(_TRENDS_KEYWORDS, timeframe="today 3-m", geo="")
            df = pytrends.interest_over_time()

            if df.empty:
                result = _unavailable("empty_response")
                self._cache = {"result": result}
                self._cache_ts = now
                return result

            buy_series = df["buy bitcoin"].tolist()
            crash_series = df["bitcoin crash"].tolist()

            buy_z = _zscore_latest(buy_series)
            crash_z = _zscore_latest(crash_series)

            raw: dict[str, float] = {
                "buy_bitcoin_latest": float(buy_series[-1]) if buy_series else 0.0,
                "bitcoin_crash_latest": float(crash_series[-1]) if crash_series else 0.0,
                "buy_bitcoin_zscore": float(buy_z) if buy_z is not None else 0.0,
                "bitcoin_crash_zscore": float(crash_z) if crash_z is not None else 0.0,
            }

            # Sentiment oscillator: maps ratio to [-1, +1]
            buy_avg = statistics.mean(buy_series) if buy_series else 1.0
            crash_avg = statistics.mean(crash_series) if crash_series else 1.0
            ratio = buy_avg / (crash_avg + _EPSILON)
            # ratio > 1 = more "buy" searches = contrarian sell; ratio < 1 = contrarian buy
            # Map: log(ratio) / 2 clamped to [-1, +1] gives smooth oscillator
            import math
            oscillator = _clamp(math.log(ratio + _EPSILON) / 2.0)
            raw["sentiment_oscillator"] = oscillator

            # Determine value and confidence
            value = 0.0
            confidence = 0.5
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
                # Use oscillator as mild signal
                value = _clamp(-oscillator * 0.3)  # inverted: high "buy" search → sell signal
                confidence = 0.3
                regime_tag = "mild_contrarian"

            result = _SignalValue(value=value, confidence=confidence, regime_tag=regime_tag, raw=raw)
            self._cache = {"result": result}
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("GoogleTrendsSignal fetch failed: %s", exc)
            # Return last cached result if available, else unavailable
            if self._cache:
                logger.debug("GoogleTrendsSignal: returning stale cache")
                return self._cache["result"]
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
    Developer activity signal based on commit velocity and repo health.

    Logic:
      - Fetch weekly commit counts for the last 52 weeks (GitHub stats API)
      - 4-week MA vs. 12-week MA of commits
      - 4w > 12w (rising activity) → bullish (+), declining → bearish (-)
      - Combine across both repos; also factor in open PRs / issues trend
    """

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _GITHUB_CACHE_TTL and self._cache:
            return self._cache["result"]

        try:
            import urllib.request
            import json as _json

            repo_signals: list[float] = []
            raw: dict[str, float] = {}

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "omega-victoria-node/1.0",
            }

            for owner, repo in _GITHUB_REPOS:
                url = f"{_GITHUB_API}/repos/{owner}/{repo}/stats/commit_activity"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 202:
                        # GitHub is computing stats; return stale or unavailable
                        logger.debug("GitHub stats for %s/%s not ready (202)", owner, repo)
                        continue
                    data = _json.loads(resp.read().decode())

                # data is list of 52 weekly objects: {week, total, days}
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
                    # ratio > 1 = rising, < 1 = declining; map to [-1, +1]
                    ratio = ma4 / ma12
                    import math
                    repo_signal = _clamp(math.log(ratio + _EPSILON) * 2.0)

                raw[f"{key}_signal"] = repo_signal
                repo_signals.append(repo_signal)

                # Supplemental: open PRs and issues (lower is healthier backlog, rising = active)
                try:
                    pr_url = f"{_GITHUB_API}/repos/{owner}/{repo}?per_page=1"
                    pr_req = urllib.request.Request(pr_url, headers=headers)
                    with urllib.request.urlopen(pr_req, timeout=10) as pr_resp:
                        repo_info = _json.loads(pr_resp.read().decode())
                        raw[f"{key}_open_issues"] = float(repo_info.get("open_issues_count", 0))
                except Exception:
                    pass

            if not repo_signals:
                result = _unavailable("no_repo_data")
                self._cache = {"result": result}
                self._cache_ts = now
                return result

            composite = sum(repo_signals) / len(repo_signals)
            confidence = min(0.8, 0.4 + len(repo_signals) * 0.2)  # more repos = more confidence
            regime_tag = "rising_dev" if composite > 0.1 else ("declining_dev" if composite < -0.1 else "stable_dev")

            result = _SignalValue(
                value=_clamp(composite),
                confidence=confidence,
                regime_tag=regime_tag,
                raw=raw,
            )
            self._cache = {"result": result}
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("GitHubActivitySignal fetch failed: %s", exc)
            if self._cache:
                logger.debug("GitHubActivitySignal: returning stale cache")
                return self._cache["result"]
            return _unavailable("fetch_error")


# ---------------------------------------------------------------------------
# AppStoreProxySignal
# ---------------------------------------------------------------------------

_APPSTORE_KEYWORDS = ["coinbase app", "crypto app", "bitcoin wallet"]


class AppStoreProxySignal:
    """
    App store ranking proxy using Google Trends for crypto app search volume.

    Logic:
      - High search volume for "coinbase app" = peak retail FOMO → contrarian sell
      - Uses same z-score / contrarian logic as GoogleTrendsSignal
      - Shares the 4-hour cache TTL
    """

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def fetch(self) -> _SignalValue:
        now = time.time()
        if now - self._cache_ts < _TRENDS_CACHE_TTL and self._cache:
            return self._cache["result"]

        try:
            from pytrends.request import TrendReq  # type: ignore[import]

            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pytrends.build_payload(_APPSTORE_KEYWORDS, timeframe="today 3-m", geo="")
            df = pytrends.interest_over_time()

            if df.empty:
                result = _unavailable("empty_response")
                self._cache = {"result": result}
                self._cache_ts = now
                return result

            coinbase_series = df["coinbase app"].tolist()
            coinbase_z = _zscore_latest(coinbase_series)

            raw: dict[str, float] = {
                "coinbase_app_latest": float(coinbase_series[-1]) if coinbase_series else 0.0,
                "coinbase_app_zscore": float(coinbase_z) if coinbase_z is not None else 0.0,
            }

            # Crypto wallet app as additional signal
            if "bitcoin wallet" in df.columns:
                wallet_series = df["bitcoin wallet"].tolist()
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

            result = _SignalValue(value=value, confidence=confidence, regime_tag=regime_tag, raw=raw)
            self._cache = {"result": result}
            self._cache_ts = now
            return result

        except Exception as exc:
            logger.debug("AppStoreProxySignal fetch failed: %s", exc)
            if self._cache:
                logger.debug("AppStoreProxySignal: returning stale cache")
                return self._cache["result"]
            return _unavailable("fetch_error")


# ---------------------------------------------------------------------------
# AltDataSignalProvider — composite
# ---------------------------------------------------------------------------


class AltDataSignalProvider:
    """
    Composite alternative data signal for Victoria.

    Blends:
      - GoogleTrendsSignal  (weight 0.4) — retail FOMO/panic contrarian
      - GitHubActivitySignal (weight 0.3) — developer ecosystem health
      - AppStoreProxySignal  (weight 0.3) — app download proxy via Trends

    Returns a single SignalValue with value ∈ [-1, +1].
    All sub-signals degrade gracefully: unavailable signals are excluded
    from the weighted average (weights renormalized).

    Usage::
        provider = AltDataSignalProvider()
        sv = provider.compute()
        # sv.value: composite conviction ∈ [-1, +1]
        # sv.confidence: blended confidence
        # sv.regime_tag: dominant sub-signal's regime
    """

    def __init__(self) -> None:
        self._trends = GoogleTrendsSignal()
        self._github = GitHubActivitySignal()
        self._appstore = AppStoreProxySignal()

    def compute(self) -> _SignalValue:
        """Fetch all sub-signals and return blended composite."""
        sub_signals = [
            (_W_TRENDS, self._trends.fetch()),
            (_W_GITHUB, self._github.fetch()),
            (_W_APPSTORE, self._appstore.fetch()),
        ]

        available = [(w, sv) for w, sv in sub_signals if sv.confidence > 0.0]

        if not available:
            return _unavailable("all_sources_unavailable")

        # Renormalize weights for available signals
        total_w = sum(w for w, _ in available)
        composite_value = sum(w * sv.value for w, sv in available) / total_w
        composite_confidence = sum(w * sv.confidence for w, sv in available) / total_w

        # Dominant regime = sub-signal with highest confidence
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
```

- [ ] **Step 2: Verify the file parses cleanly**

```bash
python -c "from omega.nodes.victoria.alt_data_signals import AltDataSignalProvider; print('import ok')"
```

Expected: `import ok`

---

### Task 3: Add NodeAction enum entry

**Files:**
- Modify: `omega/core/actions.py`

- [ ] **Step 1: Add `FETCH_ALT_DATA` to NodeAction**

In `omega/core/actions.py`, add after `IMPROVEMENT = "improvement"`:

```python
FETCH_ALT_DATA = "fetch_alt_data"
```

- [ ] **Step 2: Verify**

```bash
python -c "from omega.core.actions import NodeAction; print(NodeAction.FETCH_ALT_DATA)"
```

Expected: `fetch_alt_data`

---

### Task 4: Wire into victoria_node.py

**Files:**
- Modify: `omega/nodes/victoria/victoria_node.py`

- [ ] **Step 1: Add `"alt_data"` to SIGNAL_NAMES**

In `victoria_node.py`, change:

```python
SIGNAL_NAMES = [
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
]
```

to:

```python
SIGNAL_NAMES = [
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
    "alt_data",
]
```

- [ ] **Step 2: Add import**

Add to the import block at top of `victoria_node.py`:

```python
from omega.nodes.victoria.alt_data_signals import AltDataSignalProvider
```

- [ ] **Step 3: Instantiate in __init__**

In `VictoriaNode.__init__`, after `self._btc_dominance = BTCDominanceSignal()`, add:

```python
self._alt_data = AltDataSignalProvider()
```

- [ ] **Step 4: Call in _do_compute_signals**

In `_do_compute_signals`, after the `btc_dominance` try/except block, add:

```python
            try:
                alt_val = self._alt_data.compute()
                signals["alt_data"] = {
                    "value": alt_val.value,
                    "confidence": alt_val.confidence,
                    "regime_tag": alt_val.regime_tag,
                    "raw": alt_val.raw,
                }
            except Exception as exc:
                logger.debug("alt_data signal failed: %s", exc)
```

- [ ] **Step 5: Verify import + instantiation**

```bash
python -c "from omega.nodes.victoria.victoria_node import VictoriaNode; v = VictoriaNode(); print('alt_data' in v._weight_allocator._signals)"
```

Expected: `True`

---

### Task 5: Run 20 cycles and verify

**Files:**
- No file changes — just verification

- [ ] **Step 1: Run 20 cycles**

```bash
cd /path/to/omega && python -c "
from omega.nodes.victoria.victoria_node import VictoriaNode
from omega.core.node import NodeInput
from omega.core.actions import NodeAction

node = VictoriaNode()
for i in range(20):
    out = node.execute(NodeInput(action=NodeAction.COMPUTE_SIGNALS.value, parameters={}, context={}))
    signals = out.result or {}
    alt = signals.get('alt_data', {})
    print(f'cycle {i+1:02d}: alt_data value={alt.get(\"value\", \"missing\"):.3f} conf={alt.get(\"confidence\", 0):.3f} regime={alt.get(\"regime_tag\", \"missing\")}')
print('Done - 20 cycles complete')
"
```

Expected: 20 lines of `cycle NN: alt_data value=X.XXX conf=X.XXX regime=...`

- [ ] **Step 2: Verify weight allocator includes alt_data**

```bash
python -c "
from omega.nodes.victoria.victoria_node import VictoriaNode
from omega.core.node import NodeInput
from omega.core.actions import NodeAction

node = VictoriaNode()
for _ in range(20):
    node.execute(NodeInput(action=NodeAction.COMPUTE_SIGNALS.value, parameters={}, context={}))

profile = node._weight_allocator.get_profile('default')
print('weights:', profile['weights'])
print('alt_data weight:', profile['weights'].get('alt_data', 0))
"
```

Expected: `alt_data` present in weights dict

---

### Task 6: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add omega/nodes/victoria/alt_data_signals.py omega/nodes/victoria/victoria_node.py omega/core/actions.py docs/superpowers/plans/2026-03-26-alt-data-signals.md
git commit -m "feat: add AltDataSignalProvider (Google Trends + GitHub + App Store proxy) as alt_data signal"
```
