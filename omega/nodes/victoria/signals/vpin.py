"""VPIN (Volume-synchronized Probability of Informed Trading) signal wrapper.

Background:
    VPIN measures order-flow imbalance within volume-sized buckets. The 2026
    paper "VPIN as a Predictor of Bitcoin Price Jumps" shows VPIN spikes
    precede significant price moves (magnitude predicted, direction agnostic).

This module is a wrapper, not the compute path. The raw VPIN value is computed
in `ws_feeds.py` (currently as 50-trade buckets, exposed via `get_microstructure`).
This module adds:
    * `vpin_zscore`  — z-score of current VPIN vs the rolling N-bucket mean/std
    * `vpin_spike`   — binary: 1.0 when |zscore| >= spike_threshold else 0.0
    * `vpin_signal`  — composite directional signal: equals the sign of the
                      sum of recent breakout/momentum signals when spike fires,
                      0 otherwise. Lets the ensemble treat a VPIN spike as a
                      conviction multiplier on whatever direction the other
                      sub-strategies agree on.

Usage:
    sig = VPINSignal()
    feats = sig.compute(symbol="BTCUSDT", vpin_value=0.62,
                        directional_hint=0.15)  # sum of breakout/momentum
    # feats = {"vpin": 0.62, "vpin_zscore": 1.8, "vpin_spike": 0.0,
    #          "vpin_directional": 0.0}

The ensemble's `macro_signals` reads these from the per-ticker signals_dict.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Final

# Rolling window size for z-score baseline. The underlying ws_feeds VPIN
# already keeps the last 20 buckets — we keep our own buffer in case the
# underlying compute is replaced (e.g. with volume-bucketed VPIN later).
_HISTORY_SIZE: Final[int] = 50
_SPIKE_THRESHOLD: Final[float] = 2.0  # z-score threshold for "spike"


@dataclass
class _SymState:
    history: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY_SIZE))


class VPINSignal:
    """Wraps the raw VPIN value with z-score and spike features per symbol."""

    def __init__(self, history_size: int = _HISTORY_SIZE, spike_z: float = _SPIKE_THRESHOLD) -> None:
        self._states: dict[str, _SymState] = {}
        self._history_size = history_size
        self._spike_z = spike_z

    def _state(self, symbol: str) -> _SymState:
        sym = symbol.upper()
        st = self._states.get(sym)
        if st is None:
            st = _SymState(history=deque(maxlen=self._history_size))
            self._states[sym] = st
        return st

    def compute(
        self,
        symbol: str,
        vpin_value: float,
        directional_hint: float = 0.0,
    ) -> dict[str, float]:
        """Return VPIN feature dict for one symbol.

        Args:
            symbol: trading pair (e.g. "BTCUSDT")
            vpin_value: raw VPIN in [0, 1] from ws_feeds.get_microstructure()
            directional_hint: sum (or mean) of momentum/breakout signals at this
                cycle, used to give the spike a direction. Sign matters; magnitude
                is rescaled.

        Returns: dict with keys vpin, vpin_zscore, vpin_spike, vpin_directional.
        Returns all zeros when vpin_value is 0 (no WS data) or history is empty.
        """
        if vpin_value <= 0.0:
            return {"vpin": 0.0, "vpin_zscore": 0.0, "vpin_spike": 0.0, "vpin_directional": 0.0}

        st = self._state(symbol)
        st.history.append(float(vpin_value))

        if len(st.history) < 5:
            # not enough history for a meaningful z-score yet
            return {"vpin": float(vpin_value), "vpin_zscore": 0.0, "vpin_spike": 0.0, "vpin_directional": 0.0}

        mu = mean(st.history)
        sigma = pstdev(st.history) or 1e-9
        z = (float(vpin_value) - mu) / sigma
        spike = 1.0 if z >= self._spike_z else 0.0

        # Directional: spike × sign(hint). Magnitude in [-1, +1].
        directional = 0.0
        if spike > 0.0 and directional_hint != 0.0:
            directional = 1.0 if directional_hint > 0 else -1.0

        return {
            "vpin": float(vpin_value),
            "vpin_zscore": round(z, 4),
            "vpin_spike": spike,
            "vpin_directional": directional,
        }

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._states.clear()
        else:
            self._states.pop(symbol.upper(), None)
