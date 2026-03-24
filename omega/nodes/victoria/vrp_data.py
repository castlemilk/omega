"""
omega.nodes.victoria.vrp_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
VRP (Variance Risk Premium) data collection.

Three components:
  1. DeribitVolFetcher     — fetch BTC/ETH implied vol from Deribit public API
  2. FundingRateVolProxy   — use perpetual funding rates as IV proxy
  3. RealizedVolCalculator — compute rolling realized vol from OHLCV

Deribit public endpoint (no auth required):
  https://www.deribit.com/api/v2/public/get_book_summary_by_currency
  ?currency=BTC&kind=option
"""

import json
import logging
import math
import time
import urllib.request
from typing import Any

from omega.core.credentials import credentials

credentials.register(
    "DERIBIT_CLIENT_ID",
    required=False,
    description="Deribit authenticated endpoints (optional, public API works without)",
)

logger = logging.getLogger("omega.nodes.victoria.vrp_data")

_DERIBIT_URL = (
    "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
    "?currency={currency}&kind=option"
)
_DERIBIT_DVOL_URL = (
    "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    "?currency={currency}&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=3600"
)

# ─────────────────────────────────────────────────────────────────────────────
# DeribitVolFetcher
# ─────────────────────────────────────────────────────────────────────────────


class DeribitVolFetcher:
    """
    Fetch implied volatility from Deribit's public API.

    Selects near-ATM options with ~30 days to expiry, OI-weighted.
    Returns annualised IV (e.g. 0.80 = 80%).
    Cache TTL: 5 minutes.
    """

    _CACHE_TTL = 300  # seconds

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        # currency → (iv: float, fetched_at: float)
        self._cache: dict[str, tuple[float, float]] = {}

    def fetch_iv(self, currency: str = "BTC") -> float | None:
        """
        Return implied vol (annualised) for *currency*.

        Priority: DVOL index → options book summary ATM IV.
        Returns None if all sources fail.
        """
        currency = currency.upper()
        cached = self._cache.get(currency)
        if cached is not None:
            iv, ts = cached
            if time.time() - ts < self._CACHE_TTL:
                return iv

        # 1. DVOL index (most reliable — single published index value)
        dvol = self.fetch_dvol(currency)
        if dvol is not None:
            self._cache[currency] = (dvol, time.time())
            return dvol

        # 2. Options book summary (fallback — requires expiration_timestamp field)
        try:
            url = _DERIBIT_URL.format(currency=currency)
            req = urllib.request.Request(url, headers={"User-Agent": "omega-vrp/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("Deribit options fetch failed for %s: %s", currency, exc)
            return None

        try:
            extracted = self._extract_atm_iv(data.get("result", []))
        except Exception as exc:
            logger.debug("Deribit IV extraction failed: %s", exc)
            return None

        if extracted is not None:
            self._cache[currency] = (extracted, time.time())
        return extracted

    def fetch_dvol(self, currency: str = "BTC") -> float | None:
        """
        Fetch the Deribit DVOL index (annualised IV) via get_volatility_index_data.

        Returns annualised IV as a decimal (e.g. 0.53 = 53%), or None on failure.
        DVOL is published as a percentage (e.g. 53.0), so we divide by 100.
        """
        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - 2 * 3600 * 1000  # 2 hours ago for recent data
            url = _DERIBIT_DVOL_URL.format(
                currency=currency.upper(),
                start_ms=start_ms,
                end_ms=now_ms,
            )
            req = urllib.request.Request(url, headers={"User-Agent": "omega-vrp/1.0"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
            rows = data.get("result", {}).get("data", [])
            if not rows:
                return None
            # Each row: [timestamp_ms, open, high, low, close]
            close_val = float(rows[-1][4])
            return close_val / 100.0  # percent → decimal
        except Exception as exc:
            logger.debug("Deribit DVOL fetch failed for %s: %s", currency, exc)
            return None

    def _extract_atm_iv(self, summaries: list[dict[str, Any]]) -> float | None:
        """
        Extract 30-day ATM IV from Deribit book summaries.

        Selects instruments with expiry closest to 30 days,
        OI-weighted across the 10 best candidates.
        mark_iv from Deribit is already annualised (percentage).
        """
        if not summaries:
            return None

        target_tte_ms = 30 * 24 * 3600 * 1000  # 30 days in milliseconds
        now_ms = time.time() * 1000

        # Filter: only options with positive mark_iv and open interest
        valid = [s for s in summaries if s.get("mark_iv", 0) > 0 and s.get("open_interest", 0) > 0]
        if not valid:
            return None

        # Score by absolute distance from 30-day target
        scored: list[tuple[float, float, float]] = []  # (dist, iv, oi)
        for s in valid:
            expiry_ts = s.get("expiration_timestamp", 0)
            if not expiry_ts:
                continue
            tte = expiry_ts - now_ms
            if tte < 0:
                continue
            dist = abs(tte - target_tte_ms)
            scored.append((dist, s["mark_iv"] / 100.0, float(s["open_interest"])))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0])
        top = scored[:10]
        total_oi = sum(x[2] for x in top)
        if total_oi == 0:
            return top[0][1]

        return sum(x[1] * x[2] for x in top) / total_oi

    def is_stale(self, currency: str) -> bool:
        cached = self._cache.get(currency.upper())
        if cached is None:
            return True
        _, ts = cached
        return time.time() - ts >= self._CACHE_TTL


# ─────────────────────────────────────────────────────────────────────────────
# FundingRateVolProxy
# ─────────────────────────────────────────────────────────────────────────────


class FundingRateVolProxy:
    """
    Derive an implied volatility proxy from perpetual funding rates.

    Rationale: extreme funding rates signal excessive leverage and
    directional bets — a proxy for the option market's vol expectations.

    Calibration (heuristic, crypto-specific):
      0.01% per 8h (0.0001) → ~30% annualised IV
      0.30% per 8h (0.0030) → ~164% annualised IV (square-root scaling)
    """

    def compute_iv_proxy(self, funding_rates: list[float]) -> float | None:
        """
        Compute an IV proxy from recent 8-hour funding rates.

        Args:
            funding_rates: list of 8h rates (e.g. [0.0001, 0.00015, ...])

        Returns:
            Annualised IV proxy (e.g. 0.75 = 75%), or None if < 3 samples.
        """
        if not funding_rates or len(funding_rates) < 3:
            return None

        recent = funding_rates[-8:]
        avg_abs = sum(abs(f) for f in recent) / len(recent)

        # Square-root scaling: IV ≈ 0.30 * sqrt(abs_funding / 0.0001)
        iv_proxy = 0.30 * math.sqrt(avg_abs / max(1e-8, 0.0001))
        return float(min(2.0, max(0.05, iv_proxy)))


# ─────────────────────────────────────────────────────────────────────────────
# RealizedVolCalculator
# ─────────────────────────────────────────────────────────────────────────────


class RealizedVolCalculator:
    """
    Compute rolling realized volatility from OHLCV data.

    Estimators:
      close_to_close : simple log-return std (baseline)
      parkinson      : high-low range (2x more efficient than c-t-c)
      garman_klass   : uses O, H, L, C (most efficient, ~7x c-t-c)

    All estimators return annualised vol (e.g. 0.75 = 75% annualised).
    """

    def compute(
        self,
        ohlcv: dict[str, list[float]],
        window: int = 30,
        estimator: str = "close_to_close",
    ) -> float | None:
        """
        Compute rolling realized vol over the last *window* periods.

        Args:
            ohlcv     : dict with "close", and optionally "high"/"low"/"open"
            window    : lookback in days
            estimator : "close_to_close" | "parkinson" | "garman_klass"

        Returns:
            Annualised realized vol, or None if insufficient data.
        """
        if estimator == "garman_klass":
            opens = _clean(ohlcv.get("open", []))
            highs = _clean(ohlcv.get("high", []))
            lows = _clean(ohlcv.get("low", []))
            closes = _clean(ohlcv.get("close", []))
            return self._garman_klass(opens, highs, lows, closes, window)

        if estimator == "parkinson":
            highs = _clean(ohlcv.get("high", []))
            lows = _clean(ohlcv.get("low", []))
            return self._parkinson(highs, lows, window)

        closes = _clean(ohlcv.get("close", []))
        return self._close_to_close(closes, window)

    # ── estimators ────────────────────────────────────────────────────────────

    def _close_to_close(self, closes: list[float], window: int) -> float | None:
        if len(closes) < window + 1:
            return None
        recent = closes[-(window + 1) :]
        rets = [
            math.log(recent[i] / recent[i - 1])
            for i in range(1, len(recent))
            if recent[i - 1] > 0 and recent[i] > 0
        ]
        if len(rets) < 5:
            return None
        mean = sum(rets) / len(rets)
        variance = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
        return float(math.sqrt(variance * 365))

    def _parkinson(self, highs: list[float], lows: list[float], window: int) -> float | None:
        """Parkinson estimator: sigma² = (1 / 4N·ln2) · Σ[ln(H/L)]²"""
        n = min(len(highs), len(lows))
        if n < window:
            return None
        h = highs[-window:]
        lo = lows[-window:]
        terms = [
            math.log(h[i] / lo[i]) ** 2
            for i in range(window)
            if h[i] > 0 and lo[i] > 0 and h[i] >= lo[i]
        ]
        if len(terms) < 5:
            return None
        variance = sum(terms) / (4 * len(terms) * math.log(2))
        return float(math.sqrt(variance * 365))

    def _garman_klass(
        self,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        window: int,
    ) -> float | None:
        """Garman-Klass estimator (most efficient, ~7x close-to-close)."""
        n = min(len(opens), len(highs), len(lows), len(closes))
        if n < window + 1:
            return None

        o = opens[-(window + 1) :]
        h = highs[-(window + 1) :]
        lo = lows[-(window + 1) :]
        c = closes[-(window + 1) :]

        terms = []
        for i in range(1, len(c)):
            if o[i] <= 0 or h[i] <= 0 or lo[i] <= 0 or c[i - 1] <= 0:
                continue
            log_hl = math.log(h[i] / lo[i])
            log_co = math.log(c[i] / o[i])
            log_oc = math.log(o[i] / c[i - 1])
            gk = 0.5 * log_hl**2 - (2 * math.log(2) - 1) * log_co**2 + log_oc**2
            terms.append(gk)

        if len(terms) < 5:
            return None
        variance = sum(terms) / len(terms)
        return float(math.sqrt(max(0.0, variance) * 365))


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────


def _clean(values: list) -> list[float]:
    result = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
            if math.isfinite(f):
                result.append(f)
        except (TypeError, ValueError):
            continue
    return result
