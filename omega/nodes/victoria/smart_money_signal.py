"""
omega.nodes.victoria.smart_money_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Binance Futures top-trader position tracker for Victoria.

Fetches the weekly top-20 traders by ROI from the Binance leaderboard,
then retrieves each trader's current open perpetual positions.  Computes
a per-ticker *smart-money consensus* score: the fraction of top traders
that are net long minus the fraction that are net short, normalised to
[-1.0, +1.0].

Endpoints used (both public, no API key required)
--------------------------------------------------
  POST https://www.binance.com/bapi/futures/v3/public/future/leaderboard/searchLeaderboard
       body: {"isShared":true,"isTrader":true,"periodType":"WEEKLY",
               "statisticsType":"ROI","tradeType":"PERPETUAL","limit":20}

  GET  https://www.binance.com/bapi/futures/v2/public/future/leaderboard/getOtherPosition
       params: encryptedUid=<trader_uid>

Signal semantics
----------------
  smart_money_score ∈ [-1.0, +1.0]
    +1.0 → all top traders long the ticker  (bullish consensus)
    -1.0 → all top traders short the ticker (bearish consensus)
     0.0 → equal split or no data

  composite (cross-ticker average) is the top-level signal value.
  per-ticker scores are exposed in .raw.

Cache TTL: 5 minutes (leaderboard updates slowly).
Fallback: 0.0 / confidence=0.0 if all requests fail.
"""

from __future__ import annotations

import json as _json
import logging
import math
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.smart_money_signal")

_CACHE_TTL = 300  # 5 minutes
_EPSILON = 1e-9

_LEADERBOARD_URL = (
    "https://www.binance.com/bapi/futures/v3/public/future/leaderboard/searchLeaderboard"
)
_POSITION_URL = (
    "https://www.binance.com/bapi/futures/v2/public/future/leaderboard/getOtherPosition"
)
_LEADERBOARD_LIMIT = 20

# Tickers of primary interest; also accept any ticker appearing in positions
_TRACKED_TICKERS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


# ---------------------------------------------------------------------------
# Lightweight helpers
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


def _http_post(url: str, payload: dict[str, Any], timeout: int = 10) -> Any:
    data = _json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "omega-victoria/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Leaderboard fetch
# ---------------------------------------------------------------------------


def _fetch_leaderboard() -> list[dict[str, Any]]:
    """Return list of top-trader dicts from Binance leaderboard."""
    payload = {
        "isShared": True,
        "isTrader": True,
        "periodType": "WEEKLY",
        "statisticsType": "ROI",
        "tradeType": "PERPETUAL",
        "limit": _LEADERBOARD_LIMIT,
    }
    resp = _http_post(_LEADERBOARD_URL, payload)
    # Expected: {"code": "000000", "data": [{"encryptedUid": ..., ...}, ...]}
    if resp.get("code") != "000000":
        raise ValueError(f"Leaderboard API error: {resp.get('code')} {resp.get('message')}")
    traders = resp.get("data", [])
    if not isinstance(traders, list):
        raise ValueError("Unexpected leaderboard response format")
    return traders


# ---------------------------------------------------------------------------
# Position fetch
# ---------------------------------------------------------------------------


def _fetch_positions(encrypted_uid: str) -> list[dict[str, Any]]:
    """Return the open positions for a given trader UID, or empty list on error."""
    url = f"{_POSITION_URL}?encryptedUid={urllib.parse.quote(encrypted_uid)}"
    try:
        resp = _http_get(url, timeout=8)
        if resp.get("code") != "000000":
            return []
        data = resp.get("data", {})
        # Binance wraps positions under "otherPositionRetList" or "perpetualPositions"
        positions = data.get("otherPositionRetList") or data.get("perpetualPositions") or []
        return positions if isinstance(positions, list) else []
    except Exception as exc:
        logger.debug("Position fetch for %s failed: %s", encrypted_uid, exc)
        return []


# ---------------------------------------------------------------------------
# Consensus computation
# ---------------------------------------------------------------------------


def _compute_consensus(
    trader_positions: list[list[dict[str, Any]]],
) -> dict[str, float]:
    """
    For each ticker, compute (n_long - n_short) / n_total ∈ [-1.0, +1.0].

    A trader is counted as 'long' for a ticker if their net notional on that
    ticker is positive; 'short' if negative.  Only traders who have a position
    in the ticker are included in that ticker's denominator.
    """
    long_counts: dict[str, int] = {}
    short_counts: dict[str, int] = {}

    for positions in trader_positions:
        seen: set[str] = set()
        for pos in positions:
            symbol = str(pos.get("symbol", "")).upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)

            # amount or positionAmt — positive = long, negative = short
            amount_raw = pos.get("positionAmt") or pos.get("amount") or pos.get("quantity") or 0
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                continue

            if abs(amount) < _EPSILON:
                continue  # closed / zero position

            if amount > 0:
                long_counts[symbol] = long_counts.get(symbol, 0) + 1
            else:
                short_counts[symbol] = short_counts.get(symbol, 0) + 1

    all_tickers = set(long_counts) | set(short_counts)
    consensus: dict[str, float] = {}
    for ticker in all_tickers:
        n_long = long_counts.get(ticker, 0)
        n_short = short_counts.get(ticker, 0)
        n_total = n_long + n_short
        if n_total == 0:
            continue
        consensus[ticker] = _clamp((n_long - n_short) / n_total)

    return consensus


# ---------------------------------------------------------------------------
# Public signal class
# ---------------------------------------------------------------------------


class SmartMoneySignal:
    """
    Binance top-trader position consensus signal.

    Fetches the weekly top-20 Futures ROI leaderboard, retrieves each
    trader's open perpetual positions, and computes a consensus score
    per ticker.

    The composite signal value is the mean score across tracked tickers
    that have at least one top-trader position.

    Usage::

        sig = SmartMoneySignal()
        sv = sig.compute()
        print(sv.value, sv.confidence, sv.raw)
    """

    def __init__(self) -> None:
        self._cached: _SignalValue | None = None
        self._cache_ts: float = 0.0

    def compute(self, market_data: dict[str, Any] | None = None) -> _SignalValue:
        """Return cached result if fresh, otherwise re-fetch."""
        now = time.time()
        if self._cached is not None and (now - self._cache_ts) < _CACHE_TTL:
            return self._cached

        result = self._fetch()
        self._cached = result
        self._cache_ts = now
        return result

    def _fetch(self) -> _SignalValue:
        try:
            traders = _fetch_leaderboard()
        except Exception as exc:
            logger.debug("SmartMoneySignal: leaderboard fetch failed: %s", exc)
            return _unavailable("leaderboard_failed")

        if not traders:
            return _unavailable("empty_leaderboard")

        # Collect positions for each trader (best-effort, skip failures)
        all_positions: list[list[dict[str, Any]]] = []
        for trader in traders:
            uid = trader.get("encryptedUid", "")
            if not uid:
                continue
            positions = _fetch_positions(uid)
            if positions:
                all_positions.append(positions)

        if not all_positions:
            logger.debug("SmartMoneySignal: no trader positions available")
            return _unavailable("no_positions")

        consensus = _compute_consensus(all_positions)
        if not consensus:
            return _unavailable("empty_consensus")

        # Build raw output — include all tickers but focus on tracked set
        raw: dict[str, float] = {"trader_count": float(len(all_positions))}
        for ticker, score in consensus.items():
            raw[f"{ticker.lower()}_score"] = score

        # Composite: average over tracked tickers present in consensus,
        # fall back to all tickers if none of the tracked ones appear.
        tracked_scores = [
            consensus[t] for t in _TRACKED_TICKERS if t in consensus
        ]
        if not tracked_scores:
            tracked_scores = list(consensus.values())

        composite = sum(tracked_scores) / len(tracked_scores)
        composite = _clamp(composite)

        # Confidence scales with coverage (fraction of tracked tickers seen)
        coverage = len([t for t in _TRACKED_TICKERS if t in consensus]) / max(
            1, len(_TRACKED_TICKERS)
        )
        confidence = _clamp(0.4 + 0.5 * coverage + 0.1 * min(1.0, len(all_positions) / 10), 0.0, 1.0)

        if composite > 0.2:
            regime_tag = "smart_money_long"
        elif composite < -0.2:
            regime_tag = "smart_money_short"
        else:
            regime_tag = "smart_money_neutral"

        raw["composite"] = composite
        raw["coverage"] = coverage

        logger.debug(
            "SmartMoneySignal: value=%.3f confidence=%.2f regime=%s traders=%d tickers=%d",
            composite, confidence, regime_tag, len(all_positions), len(consensus),
        )

        return _SignalValue(
            value=composite,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )
