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

MacroDataCache → FRED series `DGS2` (2Y constant maturity) and `DGS10` (10Y).
Data is fetched once and cached in SQLite (data/macro_cache.db) with a 4-hour TTL,
eliminating per-cycle FRED API calls.

## Output

float in [-0.6, 0.4]:
  -0.6 = deeply inverted / major rate shock (strongly bearish for crypto)
  +0.4 = steepening from inversion (early rate-cut cycle, bullish)
   0.0 = neutral (upright curve, no shock)
"""

import logging
import os
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.yield_curve")

_SHOCK_THRESHOLD_BP = 15.0  # 10Y day-over-day move (basis points) to trigger shock
_INVERSION_MILD_BP = -20.0  # above this: mild inversion
_STEEPEN_MIN_DAYS = 30  # minimum days inverted before steepening signal fires


# V278 — H2 arm: the macro-cache lookahead fence.
#
# Under OMEGA_FROZEN_CACHE=1, MacroDataCache._read_macro anchors its lookback to the
# cache's own newest row (data_cache.py:298, SELECT MAX(date)) rather than to the
# replayed bar. The committed cache spans 2025-12-09 -> 2026-06-10, and every
# walk-forward window predates its EARLIEST row, so this consumer reads years of the
# replayed bar's future. vix_signal.py:106 and spy_signal.py:116 already fence exactly
# this class of leak; these two macro consumers never did (V273 §6 H2).
#
# OMEGA_MACRO_BAR_FENCE=1 turns the arm ON. Default OFF => byte-identical to pre-V278.
# The fence returns an EMPTY series, routing through each signal's existing
# "data unavailable" path, which is the causally honest state: no macro row from this
# cache is legitimately visible at the replayed bar.
# See training_log/V278.md.
def _macro_fence_active() -> bool:
    return (
        os.environ.get("OMEGA_FROZEN_CACHE") == "1"
        and os.environ.get("OMEGA_MACRO_BAR_FENCE") == "1"
    )


class YieldCurveSignal:
    """
    2s10s yield curve signal for macro overlay on Victoria.

    Fires bearish when the curve is inverted, bullish when steepening from
    inversion, and a shock signal on sudden large 10Y rate moves.

    Reads from MacroDataCache (SQLite, data/macro_cache.db) — FRED series
    DGS2 and DGS10. Cache has a 4-hour TTL, so FRED is called at most once
    per 4 hours regardless of how many training cycles run.

    Returns 0.0 if no data is available in the cache.
    """

    def __init__(self) -> None:
        # Lazy-imported to avoid circular imports at module load
        self._cache = None

        # State for steepening detection (maintained across calls)
        self._days_inverted: int = 0
        self._was_inverted: bool = False
        self._last_signal: float = 0.0

        # Last loaded rates (from cache)
        self._rates_2y: list[float] = []
        self._rates_10y: list[float] = []

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
        rates_2y = self._load_rates("DGS2")
        rates_10y = self._load_rates("DGS10")

        if not rates_2y or not rates_10y:
            logger.debug("YieldCurveSignal: no data in cache, returning stale signal")
            return self._last_signal

        self._rates_2y = rates_2y
        self._rates_10y = rates_10y

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

    def compute_from_series(
        self,
        pairs_10y: list[tuple[str, float]],
        pairs_2y: list[tuple[str, float]],
    ) -> float:
        """V238 frozen-series path: same three modes on provided FRED windows.

        `pairs_*` are (iso_date, rate) observations oldest-first (SeriesProvider
        `get_window_pairs`, ~90 calendar days). Unlike the live path this is
        STATELESS: the inversion streak is derived from the window itself (the
        live `_days_inverted` counter is per-process call-count state — a
        determinism hazard in replay). Steepening fires when the latest spread
        is positive after >= _STEEPEN_MIN_DAYS consecutive inverted
        observations immediately before it. Returns NaN when the aligned
        window is too short — callers skip non-finite values.
        """
        by_date_2y = dict(pairs_2y)
        spreads_bp = [
            (r10 - by_date_2y[d]) * 100.0 for d, r10 in pairs_10y if d in by_date_2y
        ]
        rates_10y = [r10 for d, r10 in pairs_10y if d in by_date_2y]
        if len(spreads_bp) < 5:
            return float("nan")

        shock_bp = (rates_10y[-1] - rates_10y[-2]) * 100.0 if len(rates_10y) >= 2 else 0.0
        shock_sig = self._shock_signal(shock_bp)

        # Trailing inversion streak ending at the second-to-last observation
        # (mirrors the live counter's state *before* today's reading).
        streak = 0
        for s in reversed(spreads_bp[:-1]):
            if s < 0.0:
                streak += 1
            else:
                break
        steepen_sig = 0.4 if (spreads_bp[-1] >= 0.0 and streak >= _STEEPEN_MIN_DAYS) else 0.0

        inversion_sig = self._inversion_signal(spreads_bp[-1])

        if abs(shock_sig) > 0.0:
            raw = shock_sig
        elif steepen_sig != 0.0:
            raw = steepen_sig
        else:
            raw = inversion_sig
        return max(-0.6, min(0.4, raw))

    # ------------------------------------------------------------------ internals

    def _load_rates(self, series_id: str) -> list[float]:
        """Read rate values from the macro data cache."""
        if _macro_fence_active():
            # V278 H2 arm: empty => compute() returns _last_signal (0.0) and
            # compute_with_meta() returns the existing "stub" dict.
            return []
        if self._cache is None:
            from omega.nodes.victoria.data_cache import get_cache

            self._cache = get_cache()
        return self._cache.get_values(series_id, lookback_days=90)

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
