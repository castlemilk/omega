"""
omega.nodes.victoria.macro_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
MacroSignalProvider — FRED-sourced macroeconomic regime signals.

Signals (all from St. Louis Federal Reserve FRED API):
  1. M2 Money Supply Rate of Change (M2SL)     — leads BTC ~84 days at r=0.77
  2. Fed Funds Rate Derivative (FEDFUNDS)       — hawkish/dovish regime
  3. Real Yields via TIPS Spread (DGS10-T10YIE) — opportunity cost
  4. Yield Curve 2s10s (T10Y2Y)                — recession / expansion signal
  5. DXY Proxy (DTWEXBGS)                      — USD strength inverse signal
  6. Global Net Liquidity (WALCL-WTREGEN-RRPONTSYD) — risk-on/off

Composite weights: M2 (0.25), FedFunds (0.15), RealYields (0.15),
                   YieldCurve (0.15), DXY (0.15), GlobalLiquidity (0.15)

Cache TTL: 6 hours (FRED data updates daily/weekly/monthly).
Graceful degradation: returns zero-confidence signal if FRED_API_KEY is missing
or if the FRED API is unreachable.

Requires: FRED_API_KEY environment variable (free from https://fred.stlouisfed.org/docs/api/api_key.html)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.macro_signals")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL = 21600  # 6 hours in seconds

# Sub-signal weights within the macro composite (must sum to 1.0)
_WEIGHTS: dict[str, float] = {
    "m2": 0.25,
    "fed_funds": 0.15,
    "real_yields": 0.15,
    "yield_curve": 0.15,
    "dxy": 0.15,
    "net_liquidity": 0.15,
}


class MacroSignalProvider:
    """
    Fetches macroeconomic series from the FRED REST API and computes a
    composite directional signal for BTC / crypto.

    Requires FRED_API_KEY env var (checked at construction; falls back to
    a credential-store lookup if available).  Returns a zero-confidence
    SignalValue when the key is absent or the API is down.

    Usage::
        provider = MacroSignalProvider()
        sig = provider.compute()
        # sig.value ∈ [-1, +1], sig.confidence ∈ [0, 1]
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[float]]] = {}
        self._api_key: str | None = self._resolve_api_key()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """Fetch FRED series and return composite macro SignalValue.

        The ``market_data`` argument is accepted for API uniformity but not used;
        macro data is fetched directly from FRED.
        """
        if not self._api_key:
            logger.debug("FRED_API_KEY not set — macro signals unavailable")
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_api_key",
                raw={"error": 0.0},  # sentinel: 0.0 indicates config error
            )

        sub_signals: dict[str, float] = {}
        raw: dict[str, float] = {}

        # 1. M2 Money Supply 3-month rate of change
        m2_raw, m2_score = self._m2_signal()
        raw["m2_roc_3mo"] = m2_raw if m2_raw is not None else 0.0
        if m2_score is not None:
            sub_signals["m2"] = m2_score
            raw["m2"] = m2_score

        # 2. Fed Funds Rate month-over-month derivative
        ff_raw, ff_score = self._fed_funds_signal()
        raw["fed_funds_mom"] = ff_raw if ff_raw is not None else 0.0
        if ff_score is not None:
            sub_signals["fed_funds"] = ff_score
            raw["fed_funds"] = ff_score

        # 3. Real yield (10yr nominal minus 10yr breakeven inflation)
        ry_raw, ry_score = self._real_yields_signal()
        raw["real_yield_level"] = ry_raw if ry_raw is not None else 0.0
        if ry_score is not None:
            sub_signals["real_yields"] = ry_score
            raw["real_yields"] = ry_score

        # 4. Yield curve 2s10s spread
        yc_raw, yc_score = self._yield_curve_signal()
        raw["yield_curve_2s10s"] = yc_raw if yc_raw is not None else 0.0
        if yc_score is not None:
            sub_signals["yield_curve"] = yc_score
            raw["yield_curve"] = yc_score

        # 5. DXY proxy 20-day momentum
        dxy_raw, dxy_score = self._dxy_signal()
        raw["dxy_momentum_20d"] = dxy_raw if dxy_raw is not None else 0.0
        if dxy_score is not None:
            sub_signals["dxy"] = dxy_score
            raw["dxy"] = dxy_score

        # 6. Fed net liquidity (WALCL - TGA - RRP)
        liq_raw, liq_score = self._net_liquidity_signal()
        raw["net_liquidity_change_bn"] = liq_raw if liq_raw is not None else 0.0
        if liq_score is not None:
            sub_signals["net_liquidity"] = liq_score
            raw["net_liquidity"] = liq_score

        if not sub_signals:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="data_unavailable",
                raw=raw,
            )

        # Weighted composite — normalize over active weights so partial data
        # degrades gracefully rather than biasing toward zero.
        active_weight = sum(_WEIGHTS[k] for k in sub_signals)
        composite = sum(_WEIGHTS[k] * v for k, v in sub_signals.items()) / active_weight
        composite = max(-1.0, min(1.0, composite))

        # Confidence: coverage fraction * signal agreement
        coverage = len(sub_signals) / len(_WEIGHTS)
        vals = list(sub_signals.values())
        mean_val = sum(vals) / len(vals)
        agreement = 1.0 - (sum(abs(v - mean_val) for v in vals) / (len(vals) * 2.0))
        confidence = min(1.0, coverage * 0.6 + agreement * 0.4)

        # Regime tag
        if composite > 0.3:
            regime = "macro_easing"
        elif composite < -0.3:
            regime = "macro_tightening"
        else:
            regime = "macro_neutral"

        raw["composite"] = composite
        raw["coverage"] = coverage
        raw["sub_signal_count"] = float(len(sub_signals))

        logger.debug(
            "macro_signals: composite=%.3f confidence=%.3f regime=%s active=%s",
            composite,
            confidence,
            regime,
            list(sub_signals.keys()),
        )
        return SignalValue(
            value=composite,
            confidence=confidence,
            regime_tag=regime,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Sub-signal computations
    # ------------------------------------------------------------------

    def _m2_signal(self) -> tuple[float | None, float | None]:
        """M2 3-month rate of change → (roc, score ∈ [-1, +1]).

        Rising M2 growth = more monetary liquidity = bullish for BTC.
        M2SL is monthly; 3 months back = index [-4] (current + 3 prior months).
        r=0.77 correlation with BTC at ~84-day lead.
        """
        obs = self._fetch("M2SL", limit=10)
        if len(obs) < 4:
            return None, None
        current = obs[-1]
        three_mo_ago = obs[-4]
        if three_mo_ago == 0.0:
            return None, None
        roc = (current - three_mo_ago) / three_mo_ago
        # Typical 3-month M2 ROC range: -1% to +3%; normalize around 0
        # +2.5% = +1.0 (strongly bullish), -1% = -0.4 (moderately bearish)
        score = max(-1.0, min(1.0, roc / 0.025))
        return roc, score

    def _fed_funds_signal(self) -> tuple[float | None, float | None]:
        """Fed Funds Rate month-over-month change → (change_pct_pts, score ∈ [-1, +1]).

        Rising rate = hawkish = bearish for crypto.  Score is negated so
        +0.25 hike → score = -1.0.
        """
        obs = self._fetch("FEDFUNDS", limit=5)
        if len(obs) < 2:
            return None, None
        change = obs[-1] - obs[-2]
        # One standard hike/cut = ±0.25 ppt → ±1.0 score
        score = max(-1.0, min(1.0, -change / 0.25))
        return change, score

    def _real_yields_signal(self) -> tuple[float | None, float | None]:
        """Real yield = DGS10 (nominal 10yr) - T10YIE (breakeven) → (level, score ∈ [-1, +1]).

        Rising real yields = higher opportunity cost of BTC = bearish.
        Score derived from month-over-month change in the real yield level.
        """
        t10y = self._fetch("DGS10", limit=30)  # daily nominal 10yr yield
        t10yie = self._fetch("T10YIE", limit=30)  # daily 10yr breakeven inflation

        if len(t10y) < 2 or len(t10yie) < 2:
            return None, None

        # Align lengths to shorter series
        n = min(len(t10y), len(t10yie))
        ry_current = t10y[-1] - t10yie[-1]
        # ~22 trading days ≈ 1 month; clamp to available history
        lookback = min(n - 1, 22)
        ry_prev = t10y[-(lookback + 1)] - t10yie[-(lookback + 1)]

        change = ry_current - ry_prev
        # Typical 1-month real yield change ±0.5 ppt
        score = max(-1.0, min(1.0, -change / 0.5))
        return ry_current, score

    def _yield_curve_signal(self) -> tuple[float | None, float | None]:
        """T10Y2Y yield curve spread → (spread_pct_pts, score ∈ [-1, +1]).

        Per spec: derivative matters more than level (60/40 blend).
        Inversion (negative level) = recession signal = bearish.
        Steepening (positive derivative) = expansion = bullish.
        """
        obs = self._fetch("T10Y2Y", limit=30)  # daily
        if len(obs) < 2:
            return None, None

        current = obs[-1]
        lookback = min(len(obs) - 1, 22)  # ~1 month
        prev = obs[-(lookback + 1)]

        # Level: inversion = bearish; ±1.5% normalizer covers typical range
        level_score = max(-1.0, min(1.0, current / 1.5))
        # Derivative: steepening = bullish; ±0.5 ppt/month normalizer
        deriv_score = max(-1.0, min(1.0, (current - prev) / 0.5))

        score = 0.4 * level_score + 0.6 * deriv_score
        return current, score

    def _dxy_signal(self) -> tuple[float | None, float | None]:
        """DXY proxy (DTWEXBGS) 20-day momentum → (momentum, score ∈ [-1, +1]).

        Inverse correlation with BTC: rising USD = bearish for crypto.
        Score is negated so positive momentum → negative score.
        """
        obs = self._fetch("DTWEXBGS", limit=25)  # daily
        if len(obs) < 21:
            return None, None
        current = obs[-1]
        twenty_d_ago = obs[-21]
        if twenty_d_ago == 0.0:
            return None, None
        momentum = (current - twenty_d_ago) / twenty_d_ago
        # Typical 20-day DXY momentum range ±3%
        score = max(-1.0, min(1.0, -momentum / 0.03))
        return momentum, score

    def _net_liquidity_signal(self) -> tuple[float | None, float | None]:
        """Fed net liquidity = WALCL - WTREGEN - RRPONTSYD → (weekly change $bn, score ∈ [-1, +1]).

        Rising net liquidity = more money in the real economy = bullish for risk assets.
        WALCL and WTREGEN are in millions of USD; RRPONTSYD is in billions.
        We convert all to billions before subtracting.
        """
        walcl = self._fetch("WALCL", limit=8)  # weekly, millions USD
        tga = self._fetch("WTREGEN", limit=8)  # weekly, millions USD
        rrp = self._fetch("RRPONTSYD", limit=8)  # daily, billions USD

        if len(walcl) < 2 or len(tga) < 2 or len(rrp) < 2:
            return None, None

        def net_liq(w: float, t: float, r: float) -> float:
            return (w / 1000.0) - (t / 1000.0) - r  # convert M→B then subtract B

        current = net_liq(walcl[-1], tga[-1], rrp[-1])
        prev = net_liq(walcl[-2], tga[-2], rrp[-2])

        change = current - prev
        # Typical weekly net liquidity swing ±$100B; normalize to ±1 at ±$100B
        score = max(-1.0, min(1.0, change / 100.0))
        return change, score

    # ------------------------------------------------------------------
    # FRED fetch + cache
    # ------------------------------------------------------------------

    def _fetch(self, series_id: str, limit: int = 100) -> list[float]:
        """Fetch FRED series observations, returning values chronologically.

        Results are cached for _CACHE_TTL seconds.  On API failure, stale
        cache is returned if available; otherwise an empty list is returned.
        """
        cache_key = f"{series_id}:{limit}"
        now = time.time()

        if cache_key in self._cache:
            cached_ts, cached_vals = self._cache[cache_key]
            if now - cached_ts < _CACHE_TTL:
                return cached_vals

        params = urllib.parse.urlencode(
            {
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
        )
        url = f"{_FRED_BASE}?{params}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-macro-signal/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            values = self._parse_observations(data)
            self._cache[cache_key] = (now, values)
            logger.debug("FRED %s: fetched %d observations", series_id, len(values))
            return values
        except Exception as exc:
            logger.debug("FRED fetch failed for %s: %s", series_id, exc)
            if cache_key in self._cache:
                _, stale = self._cache[cache_key]
                logger.debug("FRED %s: using stale cache (%d values)", series_id, len(stale))
                return stale
            return []

    @staticmethod
    def _parse_observations(data: dict[str, Any]) -> list[float]:
        """Parse FRED JSON → chronological list of floats.

        FRED returns observations in descending order (most recent first)
        when sort_order=desc; we reverse to ascending (oldest first).
        Missing values are represented by "." and are skipped.
        """
        import contextlib

        obs = data.get("observations", [])
        values: list[float] = []
        for o in reversed(obs):
            v = o.get("value", ".")
            if v == "." or v is None:
                continue
            with contextlib.suppress(ValueError, TypeError):
                values.append(float(v))
        return values

    @staticmethod
    def _resolve_api_key() -> str | None:
        """Resolve FRED API key from environment, falling back to credential store."""
        key = os.getenv("FRED_API_KEY")
        if key:
            return key
        # Attempt credential store lookup (omega.core.config) if available
        try:
            from omega.core.config import OmegaConfig

            cfg = OmegaConfig.from_env()
            stored: str | None = getattr(cfg, "fred_api_key", None)
            if stored:
                return stored
        except Exception:
            pass
        return None
