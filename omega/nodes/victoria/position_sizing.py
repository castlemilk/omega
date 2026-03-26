"""
omega.nodes.victoria.position_sizing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kelly Criterion + Risk Parity position sizing.

Kelly formula:  f* = (p·b - q) / b
  where p = win_rate, b = avg_win / avg_loss, q = 1 - p

Half-Kelly (KELLY_FRACTION = 0.5) is used for safety — Simons used fractional
Kelly in Medallion to manage model uncertainty.

Risk parity scales positions so each symbol contributes equal annualised
volatility.  The two methods are blended 50/50 in the default mode.

Hard cap: no symbol can exceed MAX_POSITION_FRACTION of portfolio capital.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.position_sizing")

MAX_POSITION_FRACTION = 0.20  # hard cap per symbol (20%)
KELLY_FRACTION = 0.50  # half-Kelly
TARGET_VOL = 0.15  # annualised target vol per position (risk parity)
MIN_TRADES_KELLY = 20  # minimum trades before trusting Kelly estimate
DEFAULT_KELLY = 0.10  # fallback Kelly before enough history


class KellyPositionSizer:
    """
    Hybrid position sizer: Half-Kelly + Risk Parity.

    Usage::
        sizer = KellyPositionSizer(initial_capital=100_000)
        sizer.record_trade_outcome("BTCUSDT", pnl=1234.0, size=10000.0)
        sizer.record_price("BTCUSDT", price=65000.0)

        sized = sizer.size_positions(proposals, market_data)
        # proposals updated with kelly_fraction, volatility, and new weight
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        self.initial_capital = initial_capital
        self._all_trades: deque[dict[str, Any]] = deque(maxlen=500)
        self._symbol_trades: dict[str, deque[dict[str, Any]]] = {}
        self._price_history: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------ public

    def record_trade_outcome(self, symbol: str, pnl: float, size: float) -> None:
        """Record a completed trade for Kelly estimation."""
        if size <= 0:
            return
        outcome = {
            "symbol": symbol,
            "pnl": float(pnl),
            "size": float(size),
            "win": pnl > 0,
            "return": pnl / size,
        }
        self._all_trades.append(outcome)
        if symbol not in self._symbol_trades:
            self._symbol_trades[symbol] = deque(maxlen=200)
        self._symbol_trades[symbol].append(outcome)

    def record_price(self, symbol: str, price: float) -> None:
        """Record latest price for volatility estimation."""
        if price <= 0:
            return
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=60)
        self._price_history[symbol].append(price)

    def compute_kelly_fraction(self, symbol: str | None = None) -> float:
        """
        Compute half-Kelly fraction for a symbol (or globally).

        Returns fraction of capital to risk, clipped to [0.01, MAX_POSITION_FRACTION].
        """
        trades: list[dict[str, Any]]
        if symbol and symbol in self._symbol_trades:
            trades = list(self._symbol_trades[symbol])
        else:
            trades = list(self._all_trades)

        if len(trades) < MIN_TRADES_KELLY:
            return DEFAULT_KELLY

        wins = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]

        p = len(wins) / len(trades)
        q = 1.0 - p

        if not wins or not losses:
            # Degenerate — use conservative default
            return 0.05

        avg_win = abs(np.mean([t["return"] for t in wins]))
        avg_loss = abs(np.mean([t["return"] for t in losses]))

        if avg_loss < 1e-8:
            return MAX_POSITION_FRACTION

        b = avg_win / avg_loss  # payoff ratio

        # Full Kelly
        full_kelly = (p * b - q) / b

        # Half-Kelly
        half_kelly = full_kelly * KELLY_FRACTION

        return float(max(0.01, min(half_kelly, MAX_POSITION_FRACTION)))

    def compute_annualised_vol(self, symbol: str, default: float = 0.5) -> float:
        """Estimate annualised volatility from price history."""
        prices = self._price_history.get(symbol)
        if prices is None or len(prices) < 5:
            return default

        arr = np.array(list(prices), dtype=float)
        arr = arr[arr > 0]
        if len(arr) < 2:
            return default

        log_rets = np.diff(np.log(arr))
        # Assume ~hourly prices → 24*365 bars per year
        vol = float(np.std(log_rets)) * math.sqrt(24 * 365)
        return max(0.01, vol)

    def size_proposals(
        self,
        proposals: list[dict[str, Any]],
        market_data: dict[str, Any] | None = None,
        method: str = "kelly_risk_parity",
    ) -> list[dict[str, Any]]:
        """
        Apply Kelly + Risk Parity sizing to a list of trade proposals.

        Parameters
        ----------
        proposals   : list of dicts with at least 'symbol' and 'weight' keys.
        market_data : optional price data for vol estimation.
        method      : one of 'kelly_risk_parity', 'kelly_only', 'risk_parity_only'.

        Returns
        -------
        Updated proposals with 'weight', 'kelly_fraction', 'volatility',
        and 'original_weight' fields added.
        """
        if not proposals:
            return proposals

        # Sync price history from market_data
        if market_data:
            for sym, data in market_data.items():
                if not isinstance(data, dict):
                    continue
                close = data.get("close")
                price: float = 0.0
                if isinstance(close, list) and close:
                    price = float(close[-1])
                elif isinstance(close, (int, float)):
                    price = float(close)
                if price > 0:
                    self.record_price(sym, price)

        sized: list[dict[str, Any]] = []
        for prop in proposals:
            symbol: str = prop.get("symbol") or prop.get("ticker", "")
            orig_w = float(prop.get("weight", 0.0))
            if abs(orig_w) < 0.005:
                sized.append(prop)
                continue

            kelly_f = self.compute_kelly_fraction(symbol)
            vol = self.compute_annualised_vol(symbol)

            direction = math.copysign(1.0, orig_w)

            if method == "kelly_only":
                new_w = direction * kelly_f

            elif method == "risk_parity_only":
                rp_scale = TARGET_VOL / max(vol, 0.01)
                new_w = direction * min(abs(orig_w) * rp_scale, MAX_POSITION_FRACTION)

            else:  # kelly_risk_parity (default)
                kelly_w = direction * kelly_f
                rp_scale = TARGET_VOL / max(vol, 0.01)
                rp_w = direction * min(abs(orig_w) * rp_scale, MAX_POSITION_FRACTION)
                # 50/50 blend
                new_w = 0.5 * kelly_w + 0.5 * rp_w

            # Hard cap
            new_w = math.copysign(min(abs(new_w), MAX_POSITION_FRACTION), new_w)

            updated = dict(prop)
            updated["weight"] = round(new_w, 6)
            updated["kelly_fraction"] = round(kelly_f, 6)
            updated["volatility"] = round(vol, 4)
            updated["original_weight"] = round(orig_w, 6)
            sized.append(updated)

        return sized
