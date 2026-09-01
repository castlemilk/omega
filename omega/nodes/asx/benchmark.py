"""The real ASX benchmark, and an explicit account of where it does not reach.

Until 2026-09-01 the engine had no index at all, so `engine.benchmark_relative`
proxied "the market" with an equal-weight average of the *surviving* names in its
own universe. That proxy is biased in the direction that flatters the strategy
twice over: it is survivor-only, and it is drawn from the same 68 names the
signal ranks. castlemilk/shorted.com.au#556 landed `MarketService/GetIndexSeries`,
which replaces it — but only over the window the API actually serves.

Two facts decide how this module behaves:

1. **XJT, not XJO.** The engine's prices are *adjusted* closes, i.e. dividends
   reinvested. XJO is a price-only index and excludes them; on the ASX that is
   roughly 4%/yr of dividend yield handed to the strategy for free. XJT (S&P/ASX
   200 Gross Total Return) is the like-for-like comparator, so it is the default
   and choosing a price index requires saying so.

2. **The index starts 2024-09-02.** `period=MAX`, `period=10Y` and an explicit
   `from=2010-01-01` all return the same 506 sessions, so this is the API's
   ceiling and not a query mistake (castlemilk/shorted.com.au#572). It covers 11%
   of the frozen price history. Outside that window there is no benchmark, and
   this module returns ``None`` rather than reaching for the flattering proxy —
   V279's lesson is that an input which quietly evaluates to something is worse
   than one that refuses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("omega.nodes.asx.benchmark")

ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "data" / "frozen_series" / "asx" / "benchmark"

# Total-return, because the engine's prices are dividend-adjusted. See §1 above.
DEFAULT_INDEX = "XJT"

# Price-only indices. Comparing an adjusted-close strategy against one of these
# credits the strategy with the market's dividends; named here so the choice is
# visible rather than implicit.
PRICE_ONLY = {"XJO", "XKO", "XAO"}


@dataclass
class IndexBenchmark:
    """Frozen index closes. Never touches the network."""

    code: str = DEFAULT_INDEX
    root: Path = field(default_factory=lambda: FROZEN)
    _closes: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        path = self.root / f"{self.code}.csv"
        if not path.is_file():
            logger.warning("no frozen index %s at %s — benchmark inert", self.code, path)
            return
        with open(path) as fh:
            if "close" not in fh.readline().lower():
                return
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    try:
                        self._closes[parts[0][:10]] = float(parts[1])
                    except ValueError:
                        continue
        if self.code in PRICE_ONLY:
            logger.warning(
                "index %s is PRICE-ONLY; the engine's prices are dividend-adjusted, so "
                "excess return is overstated by the market's yield. Prefer XJT.",
                self.code,
            )

    @property
    def covered(self) -> tuple[str, str] | None:
        if not self._closes:
            return None
        ks = sorted(self._closes)
        return ks[0], ks[-1]

    def total_return(self, start: str, end: str) -> float | None:
        """Index return between two dates, or ``None`` if either lies outside coverage.

        Both endpoints must resolve to a session at or before the requested date and
        at or after the coverage floor. A missing endpoint is ``None``, never 0.0 —
        a silent zero would read as "the market was flat", which is a fabricated
        benchmark rather than an absent one.
        """
        p0, p1 = self._asof(start), self._asof(end)
        if p0 is None or p1 is None or p0 <= 0:
            return None
        return p1 / p0 - 1.0

    def _asof(self, date: str) -> float | None:
        """Most recent close on or before `date`, within coverage."""
        if not self._closes:
            return None
        d = date[:10]
        ks = sorted(self._closes)
        if d < ks[0]:
            return None  # before coverage: no benchmark exists, do not extrapolate
        best = None
        for k in ks:
            if k <= d:
                best = self._closes[k]
            else:
                break
        return best

    def provenance(self) -> dict[str, object]:
        cov = self.covered
        return {
            "index": self.code,
            "total_return_index": self.code not in PRICE_ONLY,
            "coverage": list(cov) if cov else None,
            "sessions": len(self._closes),
            "source": "shorted.com.au MarketService/GetIndexSeries (frozen)",
            "limitation": (
                "API serves ~2y only (2024-09-02 onward); periods before that have "
                "no benchmark and are reported as uncovered, not as zero."
            ),
        }
