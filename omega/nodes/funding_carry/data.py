"""Frozen-data loader for the funding-carry strategy.

Two aligned daily series per symbol, both read-only from ``data/``:

* **funding** — ``data/frozen_series/binance_funding_{sym}.json`` (daily mean
  of Binance perp funding settlements, 2020→2026).
* **close** — stitched from the 32 walk-forward OHLCV snapshots in
  ``data/snapshots/walk_forward/`` (each a 90d window; de-duplicated by UTC
  date they tile the 2020→2026 span with zero gaps for the majors).

The loader mirrors the ``ReplayIngestionNode`` pattern (read a frozen
snapshot, never hit the network) but is deliberately standalone so the
funding strategy never imports Victoria code.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import math
import os
from dataclasses import dataclass, field

# Repo-root-relative default. Callers may override for tests.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")

# Binance settles perp funding 3x/day (every 8h). The frozen series stores the
# daily MEAN of settlements, so total daily funding = 3 x stored value.
SETTLEMENTS_PER_DAY = 3


def _utc_date(ts: int) -> str:
    return _dt.datetime.fromtimestamp(int(ts), _dt.timezone.utc).strftime("%Y-%m-%d")


@dataclass
class SymbolSeries:
    """Aligned daily funding + close for one symbol, sorted by date ascending."""

    symbol: str
    dates: list[str] = field(default_factory=list)  # 'YYYY-MM-DD', canonical sorted
    funding: list[float] = field(default_factory=list)  # daily mean settlement rate
    close: list[float] = field(default_factory=list)  # daily close price (USDT)

    def __len__(self) -> int:
        return len(self.dates)

    def rolling_stats(self, end_idx: int, lookback: int) -> tuple[float, float]:
        """(mean, std) of funding over ``[end_idx-lookback, end_idx)``.

        Uses ``math.fsum`` for permutation-invariant exact-rounded reductions
        (Victoria determinism rule). Returns (0.0, 0.0) if the window is
        degenerate (constant) — never a smaller epsilon (V221 lesson: an
        epsilon guard amplifies sub-ulp residue into an O(1) signal).
        """
        lo = end_idx - lookback
        if lo < 0:
            return (0.0, 0.0)
        window = self.funding[lo:end_idx]
        n = len(window)
        if n == 0:
            return (0.0, 0.0)
        if max(window) == min(window):
            return (window[0], 0.0)
        mean = math.fsum(window) / n
        var = math.fsum((x - mean) ** 2 for x in window) / n
        return (mean, math.sqrt(var))


class FundingDataLoader:
    """Loads aligned funding + close series for the funding-carry universe."""

    # V240 selective universe (BTC/DOT/LINK blacklisted for SPOT Victoria) is
    # NOT inherited — funding carry is a different mechanism with its own
    # universe question, answered empirically in Phase 0. Start with the full
    # set of symbols that have frozen funding data.
    DEFAULT_UNIVERSE = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
        "SUIUSDT", "ARBUSDT",
    ]

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        self._close_cache: dict[str, dict[str, float]] | None = None

    # -- funding -----------------------------------------------------------
    def _load_funding(self, symbol: str) -> dict[str, float]:
        path = os.path.join(
            self.data_dir, "frozen_series", f"binance_funding_{symbol.lower()}.json"
        )
        with open(path) as fh:
            doc = json.load(fh)
        # series is a {date: rate} dict.
        return {str(k): float(v) for k, v in doc["series"].items()}

    # -- close (stitched from walk-forward snapshots) ----------------------
    def _load_all_closes(self) -> dict[str, dict[str, float]]:
        if self._close_cache is not None:
            return self._close_cache
        pattern = os.path.join(self.data_dir, "snapshots", "walk_forward", "snap_wf_*.json")
        out: dict[str, dict[str, float]] = {}
        for path in sorted(glob.glob(pattern)):
            with open(path) as fh:
                snap = json.load(fh)
            for sym, blob in snap.items():
                if sym.startswith("_"):
                    continue
                if not isinstance(blob, dict) or "close" not in blob:
                    continue
                bucket = out.setdefault(sym, {})
                for ts, c in zip(blob["timestamps"], blob["close"]):
                    # De-dup by date; overlapping snapshots agree on shared days.
                    bucket[_utc_date(ts)] = float(c)
        self._close_cache = out
        return out

    # -- combined ----------------------------------------------------------
    def load_symbol(self, symbol: str) -> SymbolSeries | None:
        """Return date-aligned funding+close for ``symbol`` (intersection of dates)."""
        try:
            funding = self._load_funding(symbol)
        except FileNotFoundError:
            return None
        closes = self._load_all_closes().get(symbol, {})
        common = sorted(set(funding) & set(closes))  # canonical sorted
        if not common:
            return None
        return SymbolSeries(
            symbol=symbol,
            dates=common,
            funding=[funding[d] for d in common],
            close=[closes[d] for d in common],
        )

    def load_universe(self, universe: list[str] | None = None) -> dict[str, SymbolSeries]:
        syms = universe or self.DEFAULT_UNIVERSE
        out: dict[str, SymbolSeries] = {}
        for sym in syms:  # already a deterministic list order
            s = self.load_symbol(sym)
            if s is not None and len(s) > 0:
                out[sym] = s
        return out
