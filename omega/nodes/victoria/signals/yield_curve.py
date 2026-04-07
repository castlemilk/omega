"""
Yield Curve Signal for Victoria.

## Rationale

The 2s10s yield curve spread (10Y Treasury minus 2Y Treasury) is one of the most
reliable leading indicators for macro regime shifts and risk-asset performance:

  - Inverted spread (spread < 0): 2Y yields higher than 10Y. Every US recession
    since 1970 has been preceded by an inversion, typically 6–18 months prior.
    During inversion, risk assets (including crypto) face sustained headwinds as
    tightening financial conditions suppress risk appetite.

  - Steepening from inversion (spread was < 0, now rising): Often signals the
    early phase of a rate-cutting cycle. Historically bullish for risk assets
    as the Fed pivots from tightening.

  - 10Y shock (rapid 15bp+ move in a single day): Signals a sudden re-pricing of
    long-duration risk. Large upward shocks (rate spike) are risk-off; large
    downward shocks (flight to quality / rate relief) are bullish.

## Signal modes

**Inversion mode** (primary):
  - Spread < -20bp: strongly inverted → bearish, scaled -0.3 (spread=-20bp) to
    -0.6 (spread <= -100bp)
  - Spread < 0 but > -20bp: mildly inverted → bearish, scaled -0.1 to -0.3
  - Spread > 0: upright → neutral to mildly bullish

**Steepening from inversion** (secondary, requires prior inversion):
  - spread crossing from negative to positive after >= 30 days inverted → +0.4

**10Y shock** (tertiary, overrides when large):
  - 1-day 10Y rate change > +15bp → risk-off, -0.3 (linear to -0.5 at +30bp)
  - 1-day 10Y rate change < -15bp → relief rally, +0.3

**Combination**: shock mode overrides when firing; steepening > inversion otherwise.
Final signal clamped to [-0.6, 0.4].

## Data source

FRED API — series `DGS2` (2Y constant maturity) and `DGS10` (10Y constant maturity).
Requires env var `FRED_API_KEY` or falls back to public `DEMO_KEY` (rate-limited).

## Output

float in [-0.6, 0.4]:
  -0.6 = deeply inverted / major rate shock (strongly bearish for crypto)
  +0.4 = steepening from inversion (early rate-cut cycle, bullish)
   0.0 = neutral (upright curve, no shock)

Caching: 4-hour TTL (FRED data updates daily; intraday re-fetches are wasted calls).
"""

import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.yield_curve")

_CACHE_TTL = 4 * 3600  # 4 hours
_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_2Y = "DGS2"
_SERIES_10Y = "DGS10"
_SHOCK_THRESHOLD_BP = 15.0  # 10Y day-over-day move (basis points) to trigger shock
_INVERSION_MILD_BP = -20.0  # above this: mild inversion
_STEEPEN_MIN_DAYS = 30  # minimum days inverted before steepening signal fires
_TIMEOUT = 10.0


def _fetch_fred(series_id: str, api_key: str, n_obs: int = 90) -> list[float]:
    """
    Fetch the last *n_obs* observations for a FRED series.

    Returns a list of floats (rate in percent, e.g. 4.23 means 4.23%).
    Missing / non-numeric values ("." placeholder) are skipped.
    Returns [] on any error.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(n_obs),
    }
    url = _FRED_BASE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omega-victoria/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            import json as _json

            data = _json.loads(resp.read().decode())
        observations = data.get("observations", [])
        values: list[float] = []
        for obs in observations:
            raw = obs.get("value", ".")
            if raw == ".":
                continue
            try:
                values.append(float(raw))
            except ValueError:
                continue
        # FRED returns desc order; reverse so index 0 = oldest
        values.reverse()
        return values
    except Exception as exc:
        logger.debug("YieldCurveSignal: FRED fetch failed (series=%s): %s", series_id, exc)
        return []


class YieldCurveSignal:
    """
    2s10s yield curve signal for macro overlay on Victoria.

    Fires bearish when the curve is inverted, bullish when steepening from
    inversion, and a shock signal on sudden large 10Y rate moves.

    Uses the FRED API (series DGS2 / DGS10). Requires FRED_API_KEY env var;
    falls back to DEMO_KEY (rate-limited to ~1 req/min per IP).

    Returns 0.0 if FRED is unavailable or no data can be fetched.
    """

    def __init__(self, timeout: float = _TIMEOUT) -> None:
        self._timeout = timeout
        self._api_key = os.environ.get("FRED_API_KEY", "DEMO_KEY")

        # Cache: (rates_2y, rates_10y, fetch_ts)
        self._rates_2y: list[float] = []
        self._rates_10y: list[float] = []
        self._cache_ts: float = 0.0

        # State for steepening detection
        self._days_inverted: int = 0
        self._was_inverted: bool = False

        self._last_signal: float = 0.0

    # ------------------------------------------------------------------ public

    def compute(self) -> float:
        """
        Compute the yield curve signal.

        Returns:
            float in [-0.6, 0.4].
            Negative = bearish (inversion or 10Y rate shock up).
            Positive = bullish (steepening from inversion or rate relief).
            0.0 = neutral / data unavailable.
        """
        now = time.time()
        if now - self._cache_ts < _CACHE_TTL and (self._rates_2y or self._rates_10y):
            return self._last_signal

        rates_2y = _fetch_fred(_SERIES_2Y, self._api_key)
        rates_10y = _fetch_fred(_SERIES_10Y, self._api_key)

        if not rates_2y or not rates_10y:
            logger.debug("YieldCurveSignal: no FRED data available, returning stale signal")
            return self._last_signal

        self._rates_2y = rates_2y
        self._rates_10y = rates_10y
        self._cache_ts = now

        signal = self._compute_signal()
        self._last_signal = signal
        return signal

    def compute_with_meta(self) -> dict[str, Any]:
        """
        Compute signal and return metadata.

        Returns dict with keys:
          - signal: float
          - spread_bp: float — 10Y minus 2Y in basis points
          - rate_10y: float — latest 10Y rate (%)
          - rate_2y: float — latest 2Y rate (%)
          - shock_bp: float — 1-day 10Y change (bp)
          - mode: str — "inversion" | "steepening" | "shock" | "neutral" | "stub"
          - days_inverted: int
        """
        signal = self.compute()

        if not self._rates_10y or not self._rates_2y:
            return {
                "signal": 0.0,
                "spread_bp": 0.0,
                "rate_10y": 0.0,
                "rate_2y": 0.0,
                "shock_bp": 0.0,
                "mode": "stub",
                "days_inverted": 0,
            }

        r10 = self._rates_10y[-1]
        r2 = self._rates_2y[-1]
        spread_bp = (r10 - r2) * 100.0
        shock_bp = 0.0
        if len(self._rates_10y) >= 2:
            shock_bp = (self._rates_10y[-1] - self._rates_10y[-2]) * 100.0

        shock_sig = self._shock_signal(shock_bp)
        mode = (
            "shock"
            if abs(shock_sig) > 0
            else ("steepening" if signal > 0 else ("inversion" if signal < 0 else "neutral"))
        )

        return {
            "signal": signal,
            "spread_bp": spread_bp,
            "rate_10y": r10,
            "rate_2y": r2,
            "shock_bp": shock_bp,
            "mode": mode,
            "days_inverted": self._days_inverted,
        }

    # ------------------------------------------------------------------ internals

    def _compute_signal(self) -> float:
        r10 = self._rates_10y[-1]
        r2 = self._rates_2y[-1]
        spread_bp = (r10 - r2) * 100.0  # basis points

        # 1-day 10Y shock (overrides inversion/steepening when large)
        shock_bp = 0.0
        if len(self._rates_10y) >= 2:
            shock_bp = (self._rates_10y[-1] - self._rates_10y[-2]) * 100.0
        shock_sig = self._shock_signal(shock_bp)

        # Update inversion streak counter
        currently_inverted = spread_bp < 0.0
        if currently_inverted:
            self._days_inverted += 1
        else:
            self._days_inverted = 0

        # Steepening from inversion
        steepen_sig = 0.0
        if (
            self._was_inverted
            and not currently_inverted
            and self._days_inverted >= _STEEPEN_MIN_DAYS
        ):
            steepen_sig = 0.4
            logger.info(
                "YieldCurveSignal: steepening from inversion after %d days (spread=%.1fbp)",
                self._days_inverted,
                spread_bp,
            )

        self._was_inverted = currently_inverted

        # Inversion signal
        inversion_sig = self._inversion_signal(spread_bp)

        # Priority: shock > steepening > inversion
        if abs(shock_sig) > 0.0:
            raw = shock_sig
        elif steepen_sig != 0.0:
            raw = steepen_sig
        else:
            raw = inversion_sig

        final = max(-0.6, min(0.4, raw))

        logger.info(
            "YieldCurveSignal: r10=%.3f r2=%.3f spread=%.1fbp shock=%.1fbp "
            "inv_sig=%.3f shock_sig=%.3f steep_sig=%.3f final=%.3f",
            r10,
            r2,
            spread_bp,
            shock_bp,
            inversion_sig,
            shock_sig,
            steepen_sig,
            final,
        )
        return final

    def _inversion_signal(self, spread_bp: float) -> float:
        """
        Bearish signal proportional to depth of inversion.

        - spread > 0: neutral (0.0)
        - -20 < spread <= 0: mild inversion, scale -0.1 to -0.3
        - spread <= -20: deep inversion, scale -0.3 to -0.6 (capped at -100bp)
        """
        if spread_bp >= 0.0:
            return 0.0
        if spread_bp > _INVERSION_MILD_BP:
            # Mild inversion: linear from 0 (spread=0) to -0.3 (spread=-20bp)
            return -0.3 * (-spread_bp / abs(_INVERSION_MILD_BP))
        # Deep inversion: linear from -0.3 (spread=-20bp) to -0.6 (spread=-100bp)
        excess = spread_bp - _INVERSION_MILD_BP  # negative
        slope = (-0.6 - (-0.3)) / (-100.0 - _INVERSION_MILD_BP)
        raw = -0.3 + slope * excess
        return max(-0.6, raw)

    def _shock_signal(self, shock_bp: float) -> float:
        """
        Signal from sudden large 1-day 10Y yield move.

        - shock > +15bp: rate spike → risk-off, scale -0.3 (15bp) to -0.5 (30bp+)
        - shock < -15bp: rate relief → bullish, scale +0.3 (15bp) to +0.4 (30bp+)
        """
        abs_shock = abs(shock_bp)
        if abs_shock < _SHOCK_THRESHOLD_BP:
            return 0.0
        excess = abs_shock - _SHOCK_THRESHOLD_BP
        # scale 0 (at threshold) to 0.2 (at threshold+15bp)
        magnitude = min(0.2, (excess / 15.0) * 0.2)
        if shock_bp > 0:
            return -(0.3 + magnitude)
        else:
            return 0.3 + magnitude

    def _normalize(self, value: float, lo: float, hi: float) -> float:
        """Linear normalize value from [lo, hi] to [-1, 1]."""
        if hi == lo:
            return 0.0
        mid = (hi + lo) / 2.0
        half = (hi - lo) / 2.0
        return max(-1.0, min(1.0, (value - mid) / half))
