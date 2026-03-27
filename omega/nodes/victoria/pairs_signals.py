"""
omega.nodes.victoria.pairs_signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
PairsTradingSignal — cointegration-based spread mean-reversion.

Tests for statistical co-movement between crypto pairs (ETH/BTC, SOL/ETH)
and trades the log-price spread when it deviates significantly from its
rolling mean.

Pairs monitored:
  ETHUSDT / BTCUSDT  — ETH tracks BTC with lead-lag dynamics
  SOLUSDT / ETHUSDT  — SOL tracks ETH with higher beta

Z-score thresholds (configurable, default ±2):
  z > +2  → spread too wide  → short the outperformer  → signal = -0.7
  z < -2  → spread too narrow → long the underperformer → signal = +0.7

Signal is the mean of all active pair signals.
Confidence = min(|mean_signal| * 1.5, 1.0).
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

from omega.nodes.victoria.signals_advanced import SignalValue

logger = logging.getLogger("omega.nodes.victoria.pairs_signals")

_PAIRS: list[tuple[str, str]] = [
    ("ETHUSDT", "BTCUSDT"),
    ("SOLUSDT", "ETHUSDT"),
]
_ZSCORE_ENTRY = 2.0  # z-score threshold to enter
_SIGNAL_STRENGTH = 0.7


class PairsTradingSignal:
    """
    Log-price spread z-score signal across crypto pairs.

    Each call to compute() appends the current spread observation and
    emits a signal when the z-score crosses the entry threshold.

    Parameters
    ----------
    window : int
        Rolling window length for spread mean/std calculation.
        Default 60 (approximately 60 cycle observations).
    min_obs : int
        Minimum observations before emitting a signal. Default 30.
    """

    def __init__(self, window: int = 60, min_obs: int = 30) -> None:
        self._window = window
        self._min_obs = min_obs
        # Separate deque per pair
        self._spread_history: dict[tuple[str, str], deque[float]] = {
            pair: deque(maxlen=window) for pair in _PAIRS
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute(self, market_data: dict[str, Any] | None = None) -> SignalValue:
        """
        Compute pairs-trading signal from current market data.

        Expects market_data to contain keys like 'ETHUSDT_close', 'BTCUSDT_close',
        'SOLUSDT_close' (floats or single prices).  Falls back to looking for
        nested dicts keyed by ticker with a 'close' list or scalar.
        """
        if not market_data:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="no_data",
                raw={},
            )

        pair_signals: list[float] = []
        raw: dict[str, float] = {}

        for sym_a, sym_b in _PAIRS:
            price_a = self._extract_price(market_data, sym_a)
            price_b = self._extract_price(market_data, sym_b)

            if price_a is None or price_b is None or price_a <= 0 or price_b <= 0:
                logger.debug("pairs: missing price for %s or %s", sym_a, sym_b)
                continue

            spread = float(np.log(price_a / price_b))
            history = self._spread_history[(sym_a, sym_b)]
            history.append(spread)

            if len(history) < self._min_obs:
                logger.debug(
                    "pairs %s/%s: only %d obs, need %d",
                    sym_a,
                    sym_b,
                    len(history),
                    self._min_obs,
                )
                continue

            arr = np.array(history, dtype=np.float64)
            mu = float(arr.mean())
            sigma = float(arr.std())
            zscore = (spread - mu) / (sigma + 1e-10)

            pair_key = f"{sym_a}_{sym_b}"
            raw[f"{pair_key}_spread"] = spread
            raw[f"{pair_key}_zscore"] = round(zscore, 4)
            raw[f"{pair_key}_mu"] = round(mu, 6)
            raw[f"{pair_key}_sigma"] = round(sigma, 6)

            if zscore > _ZSCORE_ENTRY:
                # Spread too wide: expect reversion — short outperformer
                pair_signals.append(-_SIGNAL_STRENGTH)
                logger.debug(
                    "pairs %s/%s: z=%.2f → SHORT (spread contraction)", sym_a, sym_b, zscore
                )
            elif zscore < -_ZSCORE_ENTRY:
                # Spread too narrow: expect expansion — long underperformer
                pair_signals.append(_SIGNAL_STRENGTH)
                logger.debug("pairs %s/%s: z=%.2f → LONG (spread expansion)", sym_a, sym_b, zscore)
            else:
                pair_signals.append(0.0)

        if not pair_signals:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="pairs_insufficient_data",
                raw=raw,
            )

        value = float(np.mean(pair_signals))
        confidence = min(abs(value) * 1.5, 1.0)

        if abs(value) >= _SIGNAL_STRENGTH * 0.9:
            regime_tag = "pairs_divergence"
        else:
            regime_tag = "pairs_neutral"

        raw["pair_count"] = float(len(pair_signals))
        raw["active_signals"] = float(sum(1 for s in pair_signals if s != 0.0))

        logger.debug(
            "pairs_signal: value=%.3f conf=%.3f regime=%s pairs=%d",
            value,
            confidence,
            regime_tag,
            len(pair_signals),
        )

        return SignalValue(
            value=value,
            confidence=confidence,
            regime_tag=regime_tag,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_price(self, market_data: dict[str, Any], symbol: str) -> float | None:
        """
        Extract the latest close price for *symbol* from market_data.

        Looks for (in order):
          1. market_data['{SYMBOL}_close']      — flat scalar
          2. market_data['{SYMBOL}']['close']   — nested dict, scalar or list
        """
        # Flat key e.g. 'ETHUSDT_close'
        flat_key = f"{symbol}_close"
        if flat_key in market_data:
            try:
                return float(market_data[flat_key])
            except (TypeError, ValueError):
                pass

        # Nested dict e.g. market_data['ETHUSDT']['close']
        nested = market_data.get(symbol)
        if isinstance(nested, dict):
            close = nested.get("close")
            if isinstance(close, list) and close:
                try:
                    return float(close[-1])
                except (TypeError, ValueError):
                    pass
            elif close is not None and not isinstance(close, list):
                try:
                    return float(close)
                except (TypeError, ValueError):
                    pass

        return None
