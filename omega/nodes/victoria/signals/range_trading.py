"""Range-trading sub-strategy — fires in flat / low-vol regimes.

Companion to the existing momentum / mean-reversion / macro ensemble votes.
This module computes per-cycle features (`bb_position`, `range_bound`,
`range_fade_signal`) and exposes a `range_vote()` function shaped like
`ensemble_strategy.momentum_vote` / `mean_reversion_vote` so it can be
folded into the existing aggregate flow.

Why a fourth vote:
    The existing three sub-strategies each need directional conviction to
    fire. In low-vol regimes (TDA fragmentation > 0.9, tight wasserstein
    distances, composite_score near zero) none of them vote, so the system
    sits out 60-70% of market time. This vote inverts the asymmetry — it
    ONLY fires when range conditions are present, and it abstains in any
    other regime.

Inputs (read from signals_dict):
    * close prices history (per-symbol caller-supplied via push_close)
    * `tda_fragmentation` (already in signals_dict; must be > 0.9 to vote)

Outputs (per-symbol feature dict, then aggregated per-vote):
    * `range_bound`           — 1.0 when ATR < 0.7 × median(ATR_hist) AND
                                price is inside Bollinger band envelope
    * `bb_position`           — (price - lower) / (upper - lower), clipped
                                to [0, 1]. 0 = at lower band (buy zone),
                                1 = at upper band (sell zone)
    * `mean_reversion_score`  — -(price - sma_20) / std_20. Far below mean
                                = positive (buy). Far above = negative.
    * `range_fade_signal`     — +1 at lower band + rsi < 30 (long fade),
                                -1 at upper band + rsi > 70 (short fade)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev, median
from typing import Any, Final, Literal

Vote = Literal["long", "short", "abstain"]

_BB_PERIOD: Final[int] = 20
_BB_SIGMA: Final[float] = 2.0
_ATR_PERIOD: Final[int] = 14
_ATR_HISTORY: Final[int] = 100
_ATR_LOW_VOL_RATIO: Final[float] = 1.0  # V191b: loosened 0.7→1.0 — current ATR below median = range
_RSI_PERIOD: Final[int] = 14


@dataclass
class _SymRangeState:
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=_BB_PERIOD * 4))
    highs: deque[float] = field(default_factory=lambda: deque(maxlen=_ATR_PERIOD * 4))
    lows: deque[float] = field(default_factory=lambda: deque(maxlen=_ATR_PERIOD * 4))
    atr_history: deque[float] = field(default_factory=lambda: deque(maxlen=_ATR_HISTORY))


@dataclass
class SubVote:
    """Mirror of ensemble_strategy.SubVote so we don't depend on it at import."""
    direction: Vote
    conviction: float
    name: str


def _rsi(closes: list[float], period: int = _RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(len(closes) - period, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs: list[float] = []
    for i in range(n - period, n):
        if i == 0:
            continue
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


class RangeTradingSignal:
    """Per-symbol range-trading feature compute + vote."""

    def __init__(
        self,
        bb_period: int = _BB_PERIOD,
        bb_sigma: float = _BB_SIGMA,
        atr_period: int = _ATR_PERIOD,
        atr_low_vol_ratio: float = _ATR_LOW_VOL_RATIO,
    ) -> None:
        self._bb_period = bb_period
        self._bb_sigma = bb_sigma
        self._atr_period = atr_period
        self._atr_low_vol_ratio = atr_low_vol_ratio
        self._states: dict[str, _SymRangeState] = {}

    def _state(self, symbol: str) -> _SymRangeState:
        sym = symbol.upper()
        st = self._states.get(sym)
        if st is None:
            st = _SymRangeState()
            self._states[sym] = st
        return st

    def push_bar(self, symbol: str, high: float, low: float, close: float) -> None:
        st = self._state(symbol)
        try:
            st.highs.append(float(high))
            st.lows.append(float(low))
            st.closes.append(float(close))
            atr = _atr(list(st.highs), list(st.lows), list(st.closes), self._atr_period)
            if atr is not None and atr > 0.0:
                st.atr_history.append(atr)
        except (TypeError, ValueError):
            return

    def compute(self, symbol: str) -> dict[str, float]:
        zero = {
            "range_bound": 0.0,
            "bb_position": 0.5,
            "mean_reversion_score": 0.0,
            "range_fade_signal": 0.0,
            "range_atr_ratio": 0.0,
        }
        st = self._state(symbol)
        if len(st.closes) < self._bb_period + 1 or len(st.atr_history) < 10:
            return zero

        closes = list(st.closes)
        recent = closes[-self._bb_period :]
        sma = sum(recent) / self._bb_period
        std = pstdev(recent) or 1e-9
        upper = sma + self._bb_sigma * std
        lower = sma - self._bb_sigma * std
        price = closes[-1]
        bb_pos = (price - lower) / max(1e-9, upper - lower)
        bb_pos = max(0.0, min(1.0, bb_pos))

        atr_now = _atr(list(st.highs), list(st.lows), closes, self._atr_period) or 0.0
        atr_med = median(st.atr_history) or 1e-9
        atr_ratio = atr_now / atr_med
        # Range-bound when current ATR is below 70% of median. Price can be
        # touching either band — that's actually the SIGNAL we want to fade.
        # We don't require price strictly inside; ATR contraction alone marks
        # the regime.
        range_bound = 1.0 if atr_ratio < self._atr_low_vol_ratio else 0.0

        mean_rev = -(price - sma) / std

        rsi = _rsi(closes)
        fade = 0.0
        if rsi is not None:
            if bb_pos < 0.15 and rsi < 30.0:
                fade = 1.0  # long fade (oversold at lower band)
            elif bb_pos > 0.85 and rsi > 70.0:
                fade = -1.0  # short fade (overbought at upper band)

        return {
            "range_bound": range_bound,
            "bb_position": round(bb_pos, 4),
            "mean_reversion_score": round(max(-3.0, min(3.0, mean_rev)), 4),
            "range_fade_signal": fade,
            "range_atr_ratio": round(atr_ratio, 4),
        }

    def reset(self) -> None:
        self._states.clear()


def range_vote(signals: dict[str, Any]) -> SubVote:
    """Vote function for the ensemble.

    Abstains unless:
        * range_bound == 1.0 (low vol confirmed by ATR ratio)
        * tda_fragmentation > 0.9 (market structure is smooth)

    Direction is fade-based: bb_position < 0.15 with mean_reversion_score > 0
    = LONG. bb_position > 0.85 with mean_reversion_score < 0 = SHORT.
    Conviction = product of |fade| and |mean_reversion_score| / 2, clipped.
    """

    def _f(k: str, d: float = 0.0) -> float:
        v = signals.get(k)
        if v is None:
            return d
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    # V191c: funding-carry override fires INDEPENDENTLY of range_bound.
    # Extreme funding (|z| >= 1.0) is itself enough signal — represents
    # crowded positioning and pays carry. Doesn't require BB extremes or
    # ATR contraction.
    carry = _f("funding_carry_signal", 0.0)
    if abs(carry) >= 1.0:
        direction: Vote = "short" if carry > 0 else "long"
        return SubVote(direction, 0.6, "range")

    if _f("range_bound") < 1.0:
        return SubVote("abstain", 0.0, "range")
    # V191b: TDA check removed. ATR-based range_bound already excludes vol
    # spikes; the TDA gate was redundant and blocking valid range setups.

    bb_pos = _f("bb_position", 0.5)
    mr_score = _f("mean_reversion_score", 0.0)
    fade = _f("range_fade_signal", 0.0)

    # Funding carry override: when funding is extreme and market is flat,
    # take the carry direction even if bb_position is mid-range.
    carry = _f("funding_carry_signal", 0.0)
    if abs(carry) >= 1.0:
        direction: Vote = "short" if carry > 0 else "long"
        return SubVote(direction, round(min(1.0, 0.6 * abs(carry) / 2.0 + 0.4), 4), "range")

    if bb_pos < 0.15 and mr_score > 0:
        conviction = min(1.0, abs(mr_score) / 2.0 + (0.3 if fade > 0 else 0.0))
        return SubVote("long", round(conviction, 4), "range")
    if bb_pos > 0.85 and mr_score < 0:
        conviction = min(1.0, abs(mr_score) / 2.0 + (0.3 if fade < 0 else 0.0))
        return SubVote("short", round(conviction, 4), "range")
    return SubVote("abstain", 0.0, "range")
