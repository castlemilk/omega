"""
VIX Risk-Off Signal for Victoria.

## Rationale

The CBOE Volatility Index (VIX) — the "fear gauge" — measures the implied volatility
of S&P 500 options over the next 30 days. Despite being an equity volatility measure,
VIX has strong cross-asset predictive power for crypto:

  - Elevated VIX (> 25) signals macro risk-off: institutional investors reduce exposure
    across all risk assets, including BTC/ETH.
  - VIX > 35 for 3+ consecutive days often marks capitulation: the subsequent rebound
    frequently coincides with crypto recoveries (BTC bottoms in Mar 2020, May 2022,
    Nov 2022 all occurred near VIX spikes).
  - VIX Z-score > 2 (vol spike relative to 30-day baseline) is a reliable crisis marker
    even in low-absolute-level regimes.

## Signal modes

**Threshold mode** (primary):
  - VIX > 25: risk-off, scaled from -0.3 (VIX=25) to -0.7 (VIX=40+)
  - VIX > 35 for 3+ consecutive days: capitulation/reversal, +0.5

**Z-score mode** (secondary, fires when threshold mode is neutral):
  - Z > +2 (extreme spike): bearish, scaled from -0.3 (z=2) to -0.6 (z=3+)
  - Z < -1 (unusual calm/complacency): mild bearish -0.1

**Combination**: threshold_signal takes priority; z-score fires only when threshold neutral.
Final signal is clamped to [-0.7, +0.5].

## Data source

Yahoo Finance via yfinance (ticker "^VIX").
Stubs to VIX=20.0 (neutral baseline) if yfinance is not installed.

## Output

float in [-0.7, 0.5]:
  -0.7 = extreme risk-off (VIX spike)
  +0.5 = capitulation reversal (potential relief rally)
   0.0 = neutral (VIX within normal range)

Caching: 1-hour TTL (VIX updates every 15 min during US market hours).
"""

import logging
import math
import os
import time
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.vix_signal")

_VIX_CACHE_TTL = 3600  # 1 hour
_RISK_OFF_THRESHOLD = 25.0  # VIX level above which risk-off signal fires
_CAPITULATION_THRESHOLD = 35.0  # VIX level for capitulation signal
_CAPITULATION_DAYS = 3  # consecutive days above capitulation threshold for reversal
_WINDOW = 30  # days of VIX history for z-score baseline


try:
    import yfinance as yf

    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False
    logger.warning(
        "VIXSignal unavailable: yfinance not installed (returning 0.0). "
        "Run `pip install yfinance` to activate."
    )


class VIXSignal:
    """
    VIX risk-off signal for cross-asset macro overlay.

    Fires a bearish signal when VIX is elevated (risk-off environment) or a
    contrarian bullish signal when VIX has been extreme for 3+ days (capitulation).

    Combines threshold mode (primary) and 30-day z-score mode (secondary).
    Stubs to 0.0 if yfinance is not installed.
    """

    def __init__(self, window: int = _WINDOW, timeout: float = 10.0) -> None:
        self._window = window
        self._timeout = timeout
        self._vix_cache: list[float] = []
        self._vix_cache_ts: float = 0.0
        self._last_signal: float = 0.0

    def compute(self) -> float:
        """
        Compute the VIX risk-off signal.

        Returns:
            float in [-0.7, 0.5]:
              Negative = risk-off (elevated VIX → bearish for crypto)
              Positive = capitulation reversal signal
              0.0 = neutral or stale data
        """
        # V227 Track C: frozen-backtest determinism fence — dormant sibling of the
        # spy_signal channel. yfinance fetches via requests/curl_cffi, bypassing the
        # V215 urllib HTTP guard, so under a frozen backtest this would hit LIVE
        # Yahoo and leak wall-clock-dependent VIX data into the composite. Fenced
        # the same way; live trading (OMEGA_FROZEN_CACHE unset) is unchanged.
        if os.environ.get("OMEGA_FROZEN_CACHE") == "1":
            return 0.0

        if not _HAS_YFINANCE:
            return 0.0

        now = time.time()
        if now - self._vix_cache_ts < _VIX_CACHE_TTL and self._vix_cache:
            return self._last_signal

        vix_prices = self._get_vix()
        if not vix_prices:
            return self._last_signal  # stale on failure

        vix_level = vix_prices[-1]
        threshold_signal = self._threshold_signal(vix_prices)
        zscore_signal, vix_zscore = self._zscore_signal(vix_prices)

        # Threshold mode takes priority; z-score fires only when threshold is neutral
        if abs(threshold_signal) > 0.0:
            raw = threshold_signal
            mode_used = "threshold"
        else:
            raw = zscore_signal
            mode_used = "zscore"

        final = max(-0.7, min(0.5, raw))

        self._last_signal = final
        logger.info(
            "VIXSignal: vix=%.2f z=%.2f threshold_sig=%.3f zscore_sig=%.3f mode=%s final=%.3f",
            vix_level,
            vix_zscore,
            threshold_signal,
            zscore_signal,
            mode_used,
            final,
        )
        return final

    def compute_with_meta(self) -> dict[str, Any]:
        """
        Compute the signal and return metadata alongside the value.

        Returns dict with keys:
          - signal: float — the signal value
          - vix_level: float — latest VIX level
          - vix_zscore: float — 30-day z-score of current VIX
          - mode_used: str — "threshold" | "zscore" | "stub"
          - threshold_signal: float — raw threshold mode output
          - zscore_signal: float — raw z-score mode output
        """
        now = time.time()
        if now - self._vix_cache_ts < _VIX_CACHE_TTL and self._vix_cache:
            vix_level = self._vix_cache[-1] if self._vix_cache else 20.0
            _, vix_zscore = self._zscore_signal(self._vix_cache)
            return {
                "signal": self._last_signal,
                "vix_level": vix_level,
                "vix_zscore": vix_zscore,
                "mode_used": "cached",
                "threshold_signal": self._last_signal,
                "zscore_signal": 0.0,
            }

        if not _HAS_YFINANCE:
            return {
                "signal": 0.0,
                "vix_level": 20.0,
                "vix_zscore": 0.0,
                "mode_used": "stub",
                "threshold_signal": 0.0,
                "zscore_signal": 0.0,
            }

        vix_prices = self._get_vix()
        if not vix_prices:
            return {
                "signal": self._last_signal,
                "vix_level": 20.0,
                "vix_zscore": 0.0,
                "mode_used": "stale",
                "threshold_signal": 0.0,
                "zscore_signal": 0.0,
            }

        vix_level = vix_prices[-1]
        threshold_signal = self._threshold_signal(vix_prices)
        zscore_signal, vix_zscore = self._zscore_signal(vix_prices)

        if abs(threshold_signal) > 0.0:
            raw = threshold_signal
            mode_used = "threshold"
        else:
            raw = zscore_signal
            mode_used = "zscore"

        final = max(-0.7, min(0.5, raw))
        self._last_signal = final

        return {
            "signal": final,
            "vix_level": vix_level,
            "vix_zscore": vix_zscore,
            "mode_used": mode_used,
            "threshold_signal": threshold_signal,
            "zscore_signal": zscore_signal,
        }

    # ------------------------------------------------------------------

    def _get_vix(self) -> list[float]:
        """Fetch VIX prices via yfinance, with 1-hour cache. Returns stub on failure."""
        if not _HAS_YFINANCE:
            # Stub: return a neutral 30-day series centered at 20.0
            return [20.0] * self._window

        now = time.time()
        if now - self._vix_cache_ts < _VIX_CACHE_TTL and self._vix_cache:
            return self._vix_cache

        try:
            raw = yf.download(
                "^VIX",
                period="35d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if raw is None or (hasattr(raw, "empty") and raw.empty):
                logger.debug("VIXSignal: empty VIX data from yfinance")
                return self._vix_cache  # stale on failure

            # yfinance >= 1.x returns MultiIndex DataFrame from download();
            # ["Close"] yields a DataFrame (not Series). squeeze() to Series.
            if hasattr(raw, "columns"):
                try:
                    close_col = raw["Close"].squeeze()
                    prices = [float(p) for p in close_col.dropna().tolist() if p > 0]
                except (KeyError, TypeError):
                    prices = []
            else:
                prices = []

            if len(prices) < 5:
                logger.debug("VIXSignal: insufficient VIX data (n=%d)", len(prices))
                return self._vix_cache

            self._vix_cache = prices[-self._window :]
            self._vix_cache_ts = now
            logger.debug(
                "VIXSignal: fetched %d VIX prices (latest=%.2f)",
                len(self._vix_cache),
                self._vix_cache[-1],
            )
            return self._vix_cache

        except Exception as exc:
            logger.warning("VIXSignal: yfinance fetch failed: %s", exc)
            return self._vix_cache  # return stale cache on error

    def _threshold_signal(self, vix_prices: list[float]) -> float:
        """
        Threshold-based signal using absolute VIX level.

        - VIX > 25: risk-off, linearly scaled from -0.3 (VIX=25) to -0.7 (VIX=40+)
        - VIX > 35 for 3+ consecutive days: capitulation/reversal → +0.5
        - Otherwise: 0.0
        """
        if not vix_prices:
            return 0.0

        vix_level = vix_prices[-1]

        # Check capitulation: VIX > 35 for 3+ consecutive days → reversal signal
        if len(vix_prices) >= _CAPITULATION_DAYS:
            consecutive_extreme = all(
                v > _CAPITULATION_THRESHOLD for v in vix_prices[-_CAPITULATION_DAYS:]
            )
            if consecutive_extreme:
                logger.debug(
                    "VIXSignal: capitulation detected (VIX>%.0f for %d+ days)",
                    _CAPITULATION_THRESHOLD,
                    _CAPITULATION_DAYS,
                )
                return 0.5

        # Risk-off threshold signal
        if vix_level > _RISK_OFF_THRESHOLD:
            # Linear scale: VIX=25 → -0.3, VIX=40 → -0.7 (clamped)
            # slope = (-0.7 - (-0.3)) / (40 - 25) = -0.4 / 15 ≈ -0.0267 per VIX point
            excess = vix_level - _RISK_OFF_THRESHOLD
            raw = -0.3 - (excess / 15.0) * 0.4
            return max(-0.7, raw)

        return 0.0

    def _zscore_signal(self, vix_prices: list[float]) -> tuple[float, float]:
        """
        Z-score of current VIX relative to its 30-day rolling baseline.

        Returns:
            (signal, z_score) tuple.
            - z > +2 → extreme spike → bearish, scaled -0.3 (z=2) to -0.6 (z=3+)
            - z < -1 → unusual calm/complacency → mild bearish -0.1
            - Otherwise: (0.0, z)
        """
        if len(vix_prices) < 5:
            return 0.0, 0.0

        current = vix_prices[-1]
        history = vix_prices[:-1]

        if not history:
            return 0.0, 0.0

        mean = sum(history) / len(history)
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 1.0
        z = (current - mean) / std

        if z > 2.0:
            # Extreme vol spike: scale -0.3 (z=2) to -0.6 (z=3+)
            # slope = (-0.6 - (-0.3)) / (3 - 2) = -0.3 per z-unit beyond 2
            excess = z - 2.0
            signal = -0.3 - min(1.0, excess) * 0.3
            return max(-0.6, signal), z
        elif z < -1.0:
            # Unusual calm / complacency: mild bearish (VIX collapse often precedes vol event)
            return -0.1, z

        return 0.0, z
