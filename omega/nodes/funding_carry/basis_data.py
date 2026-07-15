"""V255.D — real perp-mark + spot-index basis loader (parallel book).

Reads the frozen basis series produced by ``scripts/v255d_freeze_basis.py``
(``data/frozen_series/binance_futures/{SYMBOL}/{mark_price,index_price}.json``)
and re-prices the two carry legs INDEPENDENTLY — perp on the mark, spot on the
index — so the price-leg residual (Δbasis over the hold) is a **measured**
number instead of the exact $0 the single-``close`` model produced by
construction.

Only symbols with a frozen mark+index pair get real basis; every other symbol
falls back to the zero-basis assumption (residual 0), so the pooled trade SET is
unchanged from V255.C and the comparison stays apples-to-apples. Never imports
Victoria code (parallel book, same rule as ``data.py``).
"""

from __future__ import annotations

import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Trade-symbol -> frozen-archive-symbol aliases. The funding-carry trade universe
# carries some names under a pre-rebrand ticker while Binance's futures basis
# archive lives under the post-rebrand ticker. Resolving the alias when locating
# the frozen mark/index pair lets those trades price on real basis instead of
# falling back to the zero-basis assumption.
_SYMBOL_ALIASES = {
    "MATICUSDT": "POLUSDT",  # V253 MATIC->POL rebrand 2024-09-10; futures archive at POLUSDT
    # Future aliases go here
}


class BasisLoader:
    """Loads frozen mark/index closes and computes measured hedge residuals."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        self._cache: dict[str, tuple[dict[str, float], dict[str, float]] | None] = {}

    def _base(self) -> str:
        return os.path.join(self.data_dir, "frozen_series", "binance_futures")

    def _load_one(self, symbol: str) -> tuple[dict[str, float], dict[str, float]] | None:
        if symbol in self._cache:
            return self._cache[symbol]
        archive_symbol = _SYMBOL_ALIASES.get(symbol, symbol)
        sym_dir = os.path.join(self._base(), archive_symbol)
        mark_p = os.path.join(sym_dir, "mark_price.json")
        index_p = os.path.join(sym_dir, "index_price.json")
        if not (os.path.exists(mark_p) and os.path.exists(index_p)):
            self._cache[symbol] = None
            return None
        with open(mark_p) as fh:
            mark = {str(k): float(v) for k, v in json.load(fh)["series"].items()}
        with open(index_p) as fh:
            index = {str(k): float(v) for k, v in json.load(fh)["series"].items()}
        self._cache[symbol] = (mark, index)
        return self._cache[symbol]

    def available(self, symbols: list[str]) -> set[str]:
        return {s for s in symbols if self._load_one(s) is not None}

    def residual_pnl(
        self,
        symbol: str,
        entry_date: str,
        exit_date: str,
        perp_side: str,
        notional_usd: float,
    ) -> tuple[float, float, float] | None:
        """Measured price-leg PnL for one trade, re-pricing legs on mark/index.

        Returns ``(spot_leg_pnl, perp_leg_pnl, residual_frac_of_notional)`` or
        ``None`` when the symbol has no frozen basis or a leg date is missing
        (→ caller keeps the zero-basis assumption for that trade).

        perp_side == "short"  (funding>0): LONG spot on index + SHORT perp on mark
        perp_side == "long"   (funding<0): SHORT spot on index + LONG  perp on mark
        The two legs sum to exactly $0 only if mark and index moved identically
        (zero Δbasis); ``residual_frac = spot_ret + perp_ret`` is the measured
        basis residual as a fraction of one leg's notional.
        """
        loaded = self._load_one(symbol)
        if loaded is None:
            return None
        mark, index = loaded
        for d in (entry_date, exit_date):
            if d not in mark or d not in index:
                return None
        mark_ret = (mark[exit_date] - mark[entry_date]) / mark[entry_date]
        index_ret = (index[exit_date] - index[entry_date]) / index[entry_date]
        if perp_side == "short":
            spot_ret = index_ret        # long spot
            perp_ret = -mark_ret        # short perp
        else:
            spot_ret = -index_ret       # short spot
            perp_ret = mark_ret         # long perp
        residual_frac = spot_ret + perp_ret
        return (notional_usd * spot_ret, notional_usd * perp_ret, residual_frac)
