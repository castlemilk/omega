"""
omega.nodes.victoria.series_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
V238 — bar-aligned reader for the frozen historical series in
`data/frozen_series/` (built once by `scripts/v238_freeze_series.py`).

Contract (pre-registered in training_log/V238.md):

- **Never touches the network.** Files only; the V215 hermetic guard stays
  authoritative and this module never trips it.
- **Raises `SeriesOutOfRange`, never wraps** (the c244568 / V235 replay-seam
  lesson as a hard contract). A bar before the series' first observation,
  after its last observation + grace, or in an interior gap longer than the
  staleness cap is an error the CALLER must map to an honest missing value
  (NaN under OMEGA_FROZEN_CACHE=1 — never a silent 0.0).
- **As-of semantics** for daily series: `get(name, bar_ts)` returns the value
  at the latest observation date <= the bar's UTC date, at most
  `MAX_STALE_DAYS` old (FRED business-day series legitimately gap over
  weekends/holidays; anything longer is a data hole, not a lookup).
- All aggregation in this module and its consumers is `math.fsum`-fenced
  (V220/V221 summation-order discipline).
"""

from __future__ import annotations

import json
import logging
from bisect import bisect_right
from datetime import UTC, date
from datetime import datetime as _dt
from pathlib import Path

logger = logging.getLogger("omega.nodes.victoria.series_provider")

_UTC = UTC

SERIES_DIR = Path(__file__).resolve().parents[3] / "data" / "frozen_series"

# Longest tolerated as-of lookback. FRED business-day series gap 2-4 days over
# weekends/holidays; 7 keeps those honest while refusing multi-week holes.
MAX_STALE_DAYS = 7

# A bar may trail the last frozen observation by at most this much before the
# read is out of range (protects live-ish runs from silently consuming a
# months-stale freeze).
TRAILING_GRACE_DAYS = 7


class SeriesOutOfRange(Exception):  # noqa: N818 — name is the pre-registered V238 contract
    """Requested bar is outside the frozen series' honest coverage. NEVER wrap."""


class SeriesProvider:
    """Read-only, lazily-loading accessor over the frozen series files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = Path(base_dir) if base_dir is not None else SERIES_DIR
        # name -> (ordinals ascending, values, iso_dates)
        self._loaded: dict[str, tuple[list[int], list[float], list[str]]] = {}

    # ------------------------------------------------------------- public

    def available(self, name: str) -> bool:
        return name in self._loaded or (self._dir / f"{name}.json").is_file()

    def coverage(self, name: str) -> tuple[str, str] | None:
        """(first_date, last_date) of the frozen series, or None if absent."""
        if not self.available(name):
            return None
        ords, _vals, isos = self._load(name)
        return (isos[0], isos[-1]) if ords else None

    def get(self, name: str, bar_ts: float) -> float:
        """As-of value at the bar's UTC date. Raises SeriesOutOfRange."""
        ords, vals, isos = self._load(name)
        bar_ord = self._bar_ordinal(bar_ts)
        self._check_range(name, bar_ord, ords, isos)
        i = bisect_right(ords, bar_ord) - 1
        if bar_ord - ords[i] > MAX_STALE_DAYS:
            raise SeriesOutOfRange(
                f"{name}: nearest observation {isos[i]} is "
                f"{bar_ord - ords[i]}d before bar {date.fromordinal(bar_ord).isoformat()} "
                f"(> {MAX_STALE_DAYS}d staleness cap — interior gap)"
            )
        return vals[i]

    def get_window(self, name: str, bar_ts: float, n_days: int) -> list[float]:
        """Observed values with date in (bar_date - n_days, bar_date], oldest-first."""
        return [v for _, v in self.get_window_pairs(name, bar_ts, n_days)]

    def get_window_pairs(self, name: str, bar_ts: float, n_days: int) -> list[tuple[str, float]]:
        """(iso_date, value) observations in (bar_date - n_days, bar_date], oldest-first.

        The bar itself must be inside the series' honest coverage (same range
        checks as `get`); the window then contains whatever observations exist
        — business-day series legitimately yield ~5/7 of n_days points.
        """
        ords, vals, isos = self._load(name)
        bar_ord = self._bar_ordinal(bar_ts)
        self._check_range(name, bar_ord, ords, isos)
        hi = bisect_right(ords, bar_ord)
        lo = bisect_right(ords, bar_ord - n_days)
        return [(isos[i], vals[i]) for i in range(lo, hi)]

    # ---------------------------------------------------------- internals

    @staticmethod
    def _bar_ordinal(bar_ts: float) -> int:
        return _dt.fromtimestamp(float(bar_ts), tz=_UTC).date().toordinal()

    def _check_range(self, name: str, bar_ord: int, ords: list[int], isos: list[str]) -> None:
        if not ords:
            raise SeriesOutOfRange(f"{name}: frozen series is empty")
        bar_iso = date.fromordinal(bar_ord).isoformat()
        if bar_ord < ords[0]:
            raise SeriesOutOfRange(
                f"{name}: bar {bar_iso} predates first frozen observation {isos[0]}"
            )
        if bar_ord > ords[-1] + TRAILING_GRACE_DAYS:
            raise SeriesOutOfRange(
                f"{name}: bar {bar_iso} is past last frozen observation {isos[-1]} "
                f"+ {TRAILING_GRACE_DAYS}d grace — refusing to serve a stale freeze"
            )

    def _load(self, name: str) -> tuple[list[int], list[float], list[str]]:
        cached = self._loaded.get(name)
        if cached is not None:
            return cached
        path = self._dir / f"{name}.json"
        if not path.is_file():
            raise SeriesOutOfRange(f"{name}: no frozen series file at {path}")
        doc = json.loads(path.read_text())
        series = doc.get("series") or {}
        isos = sorted(series)
        ords = [date.fromisoformat(d).toordinal() for d in isos]
        vals = [float(series[d]) for d in isos]
        self._loaded[name] = (ords, vals, isos)
        logger.info(
            "SeriesProvider: loaded %s (%d obs, %s..%s)",
            name, len(isos), isos[0] if isos else "-", isos[-1] if isos else "-",
        )
        return self._loaded[name]


_provider: SeriesProvider | None = None


def get_series_provider() -> SeriesProvider:
    global _provider
    if _provider is None:
        _provider = SeriesProvider()
    return _provider
