"""LOB feature engineering — multi-level OFI, arrival rate, adverse selection.

Existing `ws_feeds.py` exposes `order_book_imbalance` (top-of-book only)
and `book_depth_velocity` (top-10 aggregate). This module adds three
features shown to have cross-asset predictive stability in the CatBoost-
on-LOB literature:

    1. **multi_level_imbalance** — depth-weighted imbalance across N levels:
       ``sum_{i<N} (bid_size_i - ask_size_i) * decay^i / sum(|...|)``.
       Captures structural pressure that top-of-book alone misses when
       hidden liquidity sits behind the best quote.

    2. **trade_arrival_rate_z** — z-score of trades-per-second over the
       last `window_sec` against a longer rolling baseline. High z means
       activity is bursting → impending move.

    3. **adverse_selection** — average signed |mid_change_after_trade| /
       half_spread over recent trades. Positive = trades systematically
       move the mid in the aggressor direction (info leakage); near zero
       = noise trading.

All three are WS-derived. Inactive in backtest snapshots.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Final

_OFI_LEVELS: Final[int] = 5
_OFI_DECAY: Final[float] = 0.5
_ARRIVAL_WINDOW_SEC: Final[float] = 30.0
_ARRIVAL_BASELINE_SEC: Final[float] = 300.0
_ADV_SEL_TICKS: Final[int] = 50


@dataclass
class _SymState:
    arrival_short: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    arrival_baseline: deque[float] = field(default_factory=lambda: deque(maxlen=20000))
    last_mids: deque[tuple[float, float, str]] = field(default_factory=lambda: deque(maxlen=_ADV_SEL_TICKS))


class LOBFeaturesSignal:
    """Multi-level OFI, arrival rate, adverse-selection features per symbol.

    Args:
        ws_feeds: object exposing `get_book(symbol)` → (bids, asks) where
            each side is a list of (price, size); and `get_ticks(symbol)`
            for the trade tape (.price, .size, .side, .ts).
        levels: number of book levels in the multi-level imbalance sum.
        decay: geometric decay factor across book levels (0.5 → level i
            contributes 0.5^i of its raw imbalance).
    """

    def __init__(
        self,
        ws_feeds: Any,
        levels: int = _OFI_LEVELS,
        decay: float = _OFI_DECAY,
        arrival_window_sec: float = _ARRIVAL_WINDOW_SEC,
        arrival_baseline_sec: float = _ARRIVAL_BASELINE_SEC,
    ) -> None:
        self._ws = ws_feeds
        self._levels = levels
        self._decay = decay
        self._window_sec = arrival_window_sec
        self._baseline_sec = arrival_baseline_sec
        self._states: dict[str, _SymState] = {}

    def _state(self, symbol: str) -> _SymState:
        sym = symbol.upper()
        st = self._states.get(sym)
        if st is None:
            st = _SymState()
            self._states[sym] = st
        return st

    def compute(self, symbol: str) -> dict[str, float]:
        zero = {
            "multi_level_imbalance": 0.0,
            "trade_arrival_rate_z": 0.0,
            "adverse_selection": 0.0,
        }
        if self._ws is None:
            return zero

        # Multi-level OFI
        try:
            book = self._ws.get_book(symbol)
        except Exception:
            book = None
        ofi = self._multi_level_ofi(book) if book else 0.0

        # Trade arrival rate + adverse selection
        try:
            ticks = self._ws.get_ticks(symbol) or []
        except Exception:
            ticks = []
        if not ticks:
            return {"multi_level_imbalance": ofi, "trade_arrival_rate_z": 0.0, "adverse_selection": 0.0}

        st = self._state(symbol)
        latest_ts = self._ts(ticks[-1])
        for t in ticks:
            ts = self._ts(t)
            if ts == 0.0:
                continue
            st.arrival_short.append(ts)
            st.arrival_baseline.append(ts)
            try:
                st.last_mids.append((ts, float(t.price), str(t.side)))
            except (AttributeError, TypeError, ValueError):
                continue

        arrival_z = self._arrival_z(st, latest_ts)
        adv = self._adverse_selection(st, book)
        return {
            "multi_level_imbalance": round(ofi, 6),
            "trade_arrival_rate_z": round(arrival_z, 4),
            "adverse_selection": round(adv, 4),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _multi_level_ofi(self, book: Any) -> float:
        try:
            bids, asks = book
        except (TypeError, ValueError):
            return 0.0
        if not bids or not asks:
            return 0.0
        num = 0.0
        denom = 0.0
        for i in range(min(self._levels, len(bids), len(asks))):
            bsize = self._size(bids[i])
            asize = self._size(asks[i])
            w = self._decay ** i
            num += (bsize - asize) * w
            denom += (abs(bsize) + abs(asize)) * w
        return num / denom if denom > 0 else 0.0

    def _arrival_z(self, st: _SymState, now_ts: float) -> float:
        if now_ts <= 0.0 or not st.arrival_baseline:
            return 0.0
        win_cut = now_ts - self._window_sec
        base_cut = now_ts - self._baseline_sec
        recent = sum(1 for t in st.arrival_short if t >= win_cut)
        baseline = [t for t in st.arrival_baseline if t >= base_cut]
        if len(baseline) < 10 or self._baseline_sec <= 0.0:
            return 0.0
        recent_rate = recent / self._window_sec
        baseline_rate = len(baseline) / self._baseline_sec
        # Approximate Poisson std as sqrt(rate); z = (recent_rate - baseline) / sqrt(baseline)
        sigma = max(1e-9, (baseline_rate / self._window_sec) ** 0.5)
        return (recent_rate - baseline_rate) / sigma

    def _adverse_selection(self, st: _SymState, book: Any) -> float:
        if len(st.last_mids) < 5:
            return 0.0
        if book is None:
            return 0.0
        try:
            bids, asks = book
            best_bid = self._price(bids[0]) if bids else None
            best_ask = self._price(asks[0]) if asks else None
        except (TypeError, IndexError):
            return 0.0
        if best_bid is None or best_ask is None or best_ask <= best_bid:
            return 0.0
        mid = 0.5 * (best_bid + best_ask)
        half_spread = max(1e-12, (best_ask - best_bid) / 2.0)
        # For each historic trade, signed mid-move relative to half spread.
        # We use the LATEST mid as the "after-trade" mid for all recent ticks —
        # this is an approximation; a proper compute needs per-tick book snapshots.
        signed_moves: list[float] = []
        for _ts, price, side in list(st.last_mids)[-_ADV_SEL_TICKS:]:
            direction = 1.0 if side == "buy" else -1.0
            signed_move = direction * (mid - price) / half_spread
            signed_moves.append(signed_move)
        if not signed_moves:
            return 0.0
        return sum(signed_moves) / len(signed_moves)

    @staticmethod
    def _size(level: Any) -> float:
        try:
            return float(getattr(level, "size", level[1]))
        except (TypeError, IndexError, ValueError):
            return 0.0

    @staticmethod
    def _price(level: Any) -> float | None:
        try:
            return float(getattr(level, "price", level[0]))
        except (TypeError, IndexError, ValueError, AttributeError):
            return None

    @staticmethod
    def _ts(tick: Any) -> float:
        try:
            return float(getattr(tick, "ts", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._states.clear()
        else:
            self._states.pop(symbol.upper(), None)
