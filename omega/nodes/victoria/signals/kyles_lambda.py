"""Kyle's Lambda — market-impact-based informed-trader detector.

Kyle's λ is the regression slope of price change on signed order flow over
a rolling window: λ = Cov(ΔP, signed_volume) / Var(signed_volume). High λ
means the market is demanding a larger price concession per unit of order
flow, which is the textbook adverse-selection signature — informed traders
are active and market makers are pulling liquidity to compensate.

Complementary to VPIN:
    * VPIN measures imbalance per volume bucket → directional pressure
      magnitude.
    * Kyle's λ measures how steeply price moves per signed volume → market
      maker adverse-selection pricing.
Both rise during informed-flow episodes; together they triangulate the
same underlying phenomenon from different angles.

Compute model:
    Per-tick (ΔP_i, signed_vol_i) pairs where signed_vol = +size if buyer
    aggressor else -size. Maintain a rolling deque of the last N pairs
    (default 200). λ = sum(p*v) / sum(v*v) on demeaned series — the OLS
    slope. We also produce a z-score of λ against its own rolling history
    so the consumer can detect spikes without per-symbol calibration.

The signal is purely WS-derived — it reads aggressor-tagged trade ticks
from `ws_feeds.get_ticks(symbol)`. Inactive in backtest snapshots.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Final

_WINDOW: Final[int] = 200       # ticks per λ estimate
_HISTORY: Final[int] = 100      # λ values kept for z-score
_SPIKE_Z: Final[float] = 2.0    # z-score threshold for spike


@dataclass
class _SymState:
    pairs: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=_WINDOW))
    last_price: float | None = None
    lambda_history: deque[float] = field(default_factory=lambda: deque(maxlen=_HISTORY))


class KylesLambdaSignal:
    """Per-symbol rolling Kyle's λ + z-score.

    Args:
        ws_feeds: object with `get_ticks(symbol)` returning a list of Tick
            objects exposing `.price`, `.size`, `.side` ("buy" or "sell").
        window: number of ticks per λ estimate.
        spike_z: z-score threshold for `kyles_lambda_spike`.
    """

    def __init__(
        self,
        ws_feeds: Any,
        window: int = _WINDOW,
        history: int = _HISTORY,
        spike_z: float = _SPIKE_Z,
    ) -> None:
        self._ws = ws_feeds
        self._window = window
        self._history = history
        self._spike_z = spike_z
        self._states: dict[str, _SymState] = {}

    def _state(self, symbol: str) -> _SymState:
        sym = symbol.upper()
        st = self._states.get(sym)
        if st is None:
            st = _SymState(
                pairs=deque(maxlen=self._window),
                lambda_history=deque(maxlen=self._history),
            )
            self._states[sym] = st
        return st

    def compute(self, symbol: str) -> dict[str, float]:
        """Return {kyles_lambda, kyles_lambda_zscore, kyles_lambda_spike}."""
        zero = {"kyles_lambda": 0.0, "kyles_lambda_zscore": 0.0, "kyles_lambda_spike": 0.0}
        if self._ws is None:
            return zero

        try:
            ticks = self._ws.get_ticks(symbol) or []
        except Exception:
            return zero
        if not ticks:
            return zero

        st = self._state(symbol)
        # Append new pairs since last call. We use the most recent ticks
        # and assume monotonically increasing tick timestamps.
        for t in ticks[-self._window :]:
            try:
                price = float(t.price)
                size = float(t.size)
                side = str(t.side).lower()
            except (AttributeError, TypeError, ValueError):
                continue
            if st.last_price is None:
                st.last_price = price
                continue
            dp = price - st.last_price
            signed_vol = size if side == "buy" else -size
            st.pairs.append((dp, signed_vol))
            st.last_price = price

        if len(st.pairs) < max(20, self._window // 5):
            return zero

        dps = [p[0] for p in st.pairs]
        svs = [p[1] for p in st.pairs]
        mean_dp = sum(dps) / len(dps)
        mean_sv = sum(svs) / len(svs)
        cov = sum((dp - mean_dp) * (sv - mean_sv) for dp, sv in st.pairs)
        var = sum((sv - mean_sv) ** 2 for sv in svs)
        if var <= 0.0:
            return zero
        lam = cov / var
        st.lambda_history.append(lam)

        if len(st.lambda_history) < 10:
            return {
                "kyles_lambda": round(lam, 6),
                "kyles_lambda_zscore": 0.0,
                "kyles_lambda_spike": 0.0,
            }

        mu = mean(st.lambda_history)
        sigma = pstdev(st.lambda_history) or 1e-12
        z = (lam - mu) / sigma
        spike = 1.0 if z >= self._spike_z else 0.0
        return {
            "kyles_lambda": round(lam, 6),
            "kyles_lambda_zscore": round(z, 4),
            "kyles_lambda_spike": spike,
        }

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._states.clear()
        else:
            self._states.pop(symbol.upper(), None)
