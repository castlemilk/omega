"""
omega.nodes.victoria.momentum_factor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Cross-sectional momentum factor (Jegadeesh-Titman approach).

Ranks all tracked assets by recent returns, goes long the top performers
and short the bottom performers.  The cross-sectional spread is the
primary signal value.

Reference: Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling
Losers: Implications for Stock Market Efficiency", Journal of Finance.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.momentum_factor")

_NEUTRAL = SignalValue(value=0.0, confidence=0.0, regime_tag="momentum_neutral", raw={})

_UNIVERSE = [
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "BNBUSDT",
]


class CrossSectionalMomentumSignal:
    """
    Cross-sectional momentum factor.

    Parameters
    ----------
    lookback : int
        Number of bars used to compute each asset's return (default 20).
    top_n    : int
        Number of top-performing assets that form the long side.
    bottom_n : int
        Number of bottom-performing assets that form the short side.
    """

    def __init__(
        self,
        lookback: int = 20,
        top_n: int = 3,
        bottom_n: int = 3,
    ) -> None:
        self._lookback = lookback
        self._top_n = top_n
        self._bottom_n = bottom_n
        # Rolling price buffers keyed by symbol
        self._price_history: dict[str, deque[float]] = {
            sym: deque(maxlen=lookback + 1) for sym in _UNIVERSE
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_prices(self, market_data: dict[str, Any]) -> None:
        """Push the latest close prices from *market_data* into the buffers."""
        for sym in _UNIVERSE:
            # Accept both list-of-prices and a scalar last-close
            raw = market_data.get(f"{sym}_close")
            if raw is None:
                continue
            if isinstance(raw, (list, tuple)) and raw:
                self._price_history[sym].append(float(raw[-1]))
            elif isinstance(raw, (int, float)):
                self._price_history[sym].append(float(raw))

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        """
        Compute the cross-sectional momentum signal.

        The signal value is the normalised cross-sectional spread:
            (mean return of top_n) - (mean return of bottom_n)
        clipped to [-1, 1].  Positive = momentum regime; negative = mean-
        reversion regime.
        """
        self.update_prices(market_data)

        # 1. Compute lookback returns for each symbol
        returns: dict[str, float] = {}
        for sym in _UNIVERSE:
            buf = self._price_history[sym]
            # Also accept a direct list in market_data for the first call
            prices_list = market_data.get(f"{sym}_close")
            if isinstance(prices_list, (list, tuple)) and len(prices_list) >= self._lookback:
                start = float(prices_list[-self._lookback])
                end = float(prices_list[-1])
                if start != 0:
                    returns[sym] = (end - start) / start
            elif len(buf) >= self._lookback:
                prices = list(buf)
                start = prices[-self._lookback]
                end = prices[-1]
                if start != 0:
                    returns[sym] = (end - start) / start

        if len(returns) < 4:
            logger.debug(
                "momentum_factor: insufficient assets with data (%d < 4), returning neutral",
                len(returns),
            )
            return _NEUTRAL

        # 2. Rank by return (descending)
        sorted_symbols = sorted(returns.items(), key=lambda x: x[1], reverse=True)

        # 3. Long the top_n, short the bottom_n
        top = [s for s, _ in sorted_symbols[: self._top_n]]
        bottom = [s for s, _ in sorted_symbols[-self._bottom_n :]]

        # 4. Cross-sectional spread
        top_avg = sum(returns[s] for s in top) / len(top)
        bottom_avg = sum(returns[s] for s in bottom) / len(bottom)
        spread = top_avg - bottom_avg

        # Scale to [-1, 1] — a spread of ±10 % maps to ±1
        value = float(np.clip(spread * 10.0, -1.0, 1.0))
        confidence = float(min(abs(value), 1.0))

        # Regime tag
        if spread > 0.02:
            regime_tag = "momentum_strong"
        elif spread > 0:
            regime_tag = "momentum_weak"
        elif spread > -0.02:
            regime_tag = "mean_reversion_weak"
        else:
            regime_tag = "mean_reversion_strong"

        logger.debug(
            "momentum_factor: spread=%.4f value=%.3f top=%s bottom=%s",
            spread,
            value,
            top,
            bottom,
        )

        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw={
                "top": top,
                "bottom": bottom,
                "spread": round(spread, 6),
                "top_avg_return": round(top_avg, 6),
                "bottom_avg_return": round(bottom_avg, 6),
                "n_assets": len(returns),
                **{f"return_{s}": round(v, 6) for s, v in returns.items()},
            },
        )
