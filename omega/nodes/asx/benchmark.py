"""The real ASX benchmark, and an explicit account of where it does not reach.

Until 2026-09-01 the engine had no index at all, so `engine.benchmark_relative`
proxied "the market" with an equal-weight average of the *surviving* names in its
own universe. castlemilk/shorted.com.au#556 landed `MarketService/GetIndexSeries`
and #573 (closing #572) gave it real depth plus an explicit truncation signal.

Two facts decide how this module behaves, and they are in tension:

1. **Total-return, not price-return.** The engine's prices are *adjusted* closes,
   i.e. dividends reinvested. A price-only index excludes them, so measuring an
   adjusted-close strategy against one credits the strategy with the market's
   entire dividend yield. Upstream measured this on their own data: XJO returned
   24.2% over a window in which XJT — the same index, dividends reinvested —
   returned 37.6%. Thirteen points of pure artifact.

2. **The honest index is the short one.** Coverage is not uniform, and the
   deepest series are exactly the ones that are price-only::

       XAO  price  2006-09-01   XJO  price  2006-09-01
       XKO  price  2013-03-05   XJT  TOTAL  2019-04-29

   XJT begins 2019-04-29 upstream and #573 is explicit that no backfill can move
   that date. So a longer study is available only by giving up the dividend
   adjustment, which is not a trade this module will make silently: XJT is the
   default, and selecting a price-only index logs a warning naming the bias.

`return_type` is read from the frozen MANIFEST rather than hardcoded — the first
version of this file guessed the classification from a code list, and a guess
about which benchmark is honest is precisely the thing that should come from the
data. `PRICE_ONLY` survives only as a fallback for a manifest-less tree.

Periods outside coverage return ``None``, never ``0.0``. A silent zero reads
downstream as "the market was flat that week", which turns an ABSENT benchmark
into a FABRICATED one and hands the strategy the market's whole return as excess.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("omega.nodes.asx.benchmark")

ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "data" / "frozen_series" / "asx" / "benchmark"

# Total-return, because the engine's prices are dividend-adjusted. See §1 above.
DEFAULT_INDEX = "XJT"

# Fallback only, for a tree with no MANIFEST. The manifest's `return_type` wins.
PRICE_ONLY = {"XJO", "XKO", "XAO"}


def _manifest(root: Path) -> dict:
    path = root / "MANIFEST.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text()).get("series", {})
    except json.JSONDecodeError:
        logger.warning("unreadable benchmark manifest at %s", path)
        return {}


@dataclass
class IndexBenchmark:
    """Frozen index closes. Never touches the network."""

    code: str = DEFAULT_INDEX
    root: Path = field(default_factory=lambda: FROZEN)
    _closes: dict[str, float] = field(default_factory=dict, init=False)
    _return_type: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        meta = _manifest(self.root).get(self.code, {})
        self._return_type = meta.get("return_type")

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
        if not self.is_total_return:
            logger.warning(
                "index %s is PRICE-ONLY (return_type=%s); the engine's prices are "
                "dividend-adjusted, so excess return is overstated by the market's yield "
                "(~13pp on upstream's measured window). Prefer XJT.",
                self.code,
                self._return_type or "unknown",
            )

    @property
    def is_total_return(self) -> bool:
        """Manifest first; the hardcoded set only when there is no manifest."""
        if self._return_type is not None:
            return self._return_type == "total"
        return self.code not in PRICE_ONLY

    @property
    def covered(self) -> tuple[str, str] | None:
        if not self._closes:
            return None
        ks = sorted(self._closes)
        return ks[0], ks[-1]

    def total_return(self, start: str, end: str) -> float | None:
        """Index return between two dates, or ``None`` if either lies outside coverage."""
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
            "total_return_index": self.is_total_return,
            "return_type": self._return_type,
            "coverage": list(cov) if cov else None,
            "sessions": len(self._closes),
            "source": "shorted.com.au MarketService/GetIndexSeries (frozen)",
            "limitation": (
                "XJT (the only total-return series) begins 2019-04-29 upstream and cannot "
                "be backfilled; deeper series (XJO/XAO to 2006) are price-only. Periods "
                "outside coverage are reported as uncovered, never as zero."
            ),
        }
