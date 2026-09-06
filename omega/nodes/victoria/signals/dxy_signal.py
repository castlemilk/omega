"""
DXY / BTC correlation signal for Victoria.

## Rationale

The US Dollar Index (DXY) is historically inversely correlated with risk assets
including BTC. The relationship is regime-dependent:
  - Strong negative correlation (DXY ↑ → BTC ↓) is common in macro-driven regimes
    (Fed tightening, flight to safety, USD liquidity crunch).
  - Correlation weakens or inverts during idiosyncratic crypto events (FTX, halving).

This signal fires only when the correlation is strong AND directional — i.e. when
DXY is actively rising AND the rolling BTC/DXY correlation is below -0.5:
  → DXY rising + corr < -0.5 → BTC likely to fall → bearish signal (negative output)
  → DXY falling + corr < -0.5 → BTC likely to rise → bullish signal (positive output)
  → |corr| >= -0.5 → correlation too weak → return 0.0

## Data source

Dollar index: FRED series DTWEXBGS (Broad Trade-Weighted US Dollar Index, daily).
Fetched via MacroDataCache (SQLite, data/macro_cache.db, 4-hour TTL).
This replaces yfinance DX-Y.NYB which had 1-3 day gaps and unreliable updates.

DTWEXBGS vs DX-Y.NYB:
  - DTWEXBGS covers ~26 currencies (broader basket) — Fed's official measure
  - DX-Y.NYB covers 6 currencies (EUR-heavy) — the "DXY" futures contract
  - Both move directionally in sync; signal logic is identical
  - DTWEXBGS has no gaps: Fed publishes every business day

BTC: price history passed through market_data (fetched by victoria_node).

## Output

float in [-1, 1]:
  -1.0 = strong bearish signal (dollar rising fast, corr very negative)
  +1.0 = strong bullish signal (dollar falling fast, corr very negative)
   0.0 = neutral (correlation above threshold, or dollar direction unclear)

Signal magnitude is scaled by how much stronger the correlation is beyond -0.5.
"""

import logging
import math
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omega.nodes.victoria.data_cache import MacroDataCache

logger = logging.getLogger("omega.nodes.victoria.signals.dxy_signal")

_CORR_THRESHOLD = -0.5  # only fire when 20d rolling correlation is below this
_WINDOW = 20  # days of dollar/BTC price history for correlation


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length lists. Returns None if insufficient data."""
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    xs, ys = xs[-n:], ys[-n:]
    # fsum: exact-rounded, permutation-invariant (V220/V221 discipline) —
    # this helper is now also on the frozen replay path.
    mx = math.fsum(xs) / n
    my = math.fsum(ys) / n
    num = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    denom_x = math.sqrt(math.fsum((x - mx) ** 2 for x in xs))
    denom_y = math.sqrt(math.fsum((y - my) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return num / (denom_x * denom_y)


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


class DXYSignal:
    """
    Broad dollar index / BTC correlation signal.

    Returns a directional signal when the rolling 20-day BTC/dollar correlation
    is below -0.5 (strong inverse relationship), scaled by the direction and
    magnitude of the dollar's recent move.

    Data source: FRED DTWEXBGS via MacroDataCache (replaces yfinance DX-Y.NYB).
    """

    def __init__(self, window: int = _WINDOW) -> None:
        self._window = window
        # Quoted on purpose: MacroDataCache is a TYPE_CHECKING-only import, and an
        # attribute-target annotation is evaluated at runtime before py314 (PEP 649).
        self._cache: "MacroDataCache | None" = None  # lazy-loaded  # noqa: UP037

    def compute(self, market_data: dict[str, Any]) -> float:
        """
        Compute dollar/BTC correlation signal.

        Args:
            market_data: Dict keyed by ticker symbol. Expects "BTCUSDT" to contain
                         a "close" or "adjclose" price list.

        Returns:
            float in [-1, 1]. Negative = bearish (dollar up, inverse corr active).
            Positive = bullish (dollar down, inverse corr active). 0 = no signal.
        """
        dollar_prices = self._get_dollar_prices()
        if len(dollar_prices) < self._window:
            return 0.0
        return self._signal_from_prices(dollar_prices, market_data)

    def compute_from_series(self, dollar_prices: list[float], market_data: dict[str, Any]) -> float:
        """V238 frozen-series path: same correlation logic on a provided
        DTWEXBGS window (oldest-first, from SeriesProvider) — no macro_cache.db.
        Returns NaN when the window is too short — callers skip non-finite
        values rather than reading 0.0 as "correlation checked, neutral".
        """
        if len(dollar_prices) < self._window:
            return float("nan")
        return self._signal_from_prices(dollar_prices, market_data)

    def _signal_from_prices(self, dollar_prices: list[float], market_data: dict[str, Any]) -> float:
        btc_data = market_data.get("BTCUSDT") or {}
        btc_prices_raw = btc_data.get("adjclose") or btc_data.get("close") or []
        btc_prices = [float(p) for p in btc_prices_raw if p is not None and float(p) > 0]
        if len(btc_prices) < self._window:
            return 0.0

        # 20-day returns for both series
        dollar_rets = [
            (dollar_prices[i] - dollar_prices[i - 1]) / dollar_prices[i - 1]
            for i in range(1, len(dollar_prices))
            if dollar_prices[i - 1] != 0
        ][-self._window :]
        btc_rets = [
            (btc_prices[i] - btc_prices[i - 1]) / btc_prices[i - 1]
            for i in range(1, len(btc_prices))
            if btc_prices[i - 1] != 0
        ][-self._window :]

        corr = _pearson(dollar_rets, btc_rets)
        if corr is None or corr >= _CORR_THRESHOLD:
            logger.debug(
                "DXYSignal: corr=%.3f above threshold %.2f — neutral",
                corr or 0.0,
                _CORR_THRESHOLD,
            )
            return 0.0

        # Dollar direction: 5-day return (recent momentum)
        if len(dollar_prices) < 5:
            return 0.0
        dollar_5d_ret = (
            (dollar_prices[-1] - dollar_prices[-5]) / dollar_prices[-5]
            if dollar_prices[-5] != 0
            else 0.0
        )

        # Signal strength scales with how far correlation exceeds threshold and dollar move size
        corr_excess = abs(corr - _CORR_THRESHOLD)  # positive, larger = stronger relationship
        # Dollar rising (positive ret) + negative corr → BTC bearish → negative signal
        # Dollar falling (negative ret) + negative corr → BTC bullish → positive signal
        raw = -dollar_5d_ret * corr_excess * 20.0  # scale: 1% move + full excess → ~0.4 signal
        signal = max(-1.0, min(1.0, raw))

        logger.info(
            "DXYSignal (DTWEXBGS): corr=%.3f dollar_5d_ret=%.4f → signal=%.3f",
            corr,
            dollar_5d_ret,
            signal,
        )
        return signal

    def _get_dollar_prices(self) -> list[float]:
        """Load FRED DTWEXBGS prices from the macro data cache."""
        if _macro_fence_active():
            # V278 H2 arm: empty => compute() returns 0.0 via its own length guard.
            return []
        if self._cache is None:
            from omega.nodes.victoria.data_cache import get_cache

            self._cache = get_cache()
        # DTWEXBGS: Broad Trade-Weighted US Dollar Index (index value, not percent)
        return self._cache.get_values("DTWEXBGS", lookback_days=self._window + 10)
