"""Point-in-time panel assembly for the ASX engine.

The single most important property of this module is that a row dated ``D`` contains
only what was **knowable at D**. Everything else in the engine depends on it, and
getting it wrong produces backtests that are wrong in ways nobody can detect from the
outside (see `training_log/V289_PHASE0_ASX_SHORT_INTEREST.md` and upstream
castlemilk/shorted.com.au#550).

Three seams exist because three upstream gaps are open. Each is written so that landing
the upstream fix is a config change here, not a rewrite:

======================  ==================================  =========================
gap (upstream issue)    what we do TODAY                    what lands LATER
======================  ==================================  =========================
#550 publication lag    apply a fixed conservative lag      read ``published_at`` /
                        (``PUBLICATION_LAG_DAYS``)          pass ``as_of`` upstream
#549 no prices          join yfinance-derived frozen CSVs   swap ``PriceSource`` for
                                                            the API implementation
#541 delisted universe  survivor-only, and every panel      universe rows carry
                        carries ``survivorship_safe=False`` ``delisted_at``
======================  ==================================  =========================

The flags are not decoration. `PanelSpec.survivorship_safe` travels into every artifact
the engine writes, so a result computed on a biased universe cannot later be mistaken
for one that was not.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("omega.nodes.asx.panel")

ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "data" / "frozen_series" / "asx"

# ASIC publishes short positions T+4 business days. Until the API exposes
# `published_at` (#550) we lag by a calendar week, which covers T+4 plus a weekend.
# Deliberately conservative: an over-lag costs a little signal decay, an under-lag
# silently fabricates lookahead, and only one of those is detectable after the fact.
PUBLICATION_LAG_DAYS = 7


class PriceSource(Protocol):
    """Seam for #549. Today: frozen yfinance CSVs. Later: the API's own OHLCV."""

    def closes(self, code: str) -> dict[str, float]:
        """Adjusted closes keyed by ISO date."""
        ...


@dataclass(frozen=True)
class PanelSpec:
    """What a panel is, including the facts that decide whether to trust it."""

    label: str
    publication_lag_days: int = PUBLICATION_LAG_DAYS
    survivorship_safe: bool = False
    price_source: str = "yfinance-frozen"
    notes: str = ""

    def provenance(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "publication_lag_days": self.publication_lag_days,
            "survivorship_safe": self.survivorship_safe,
            "price_source": self.price_source,
            "notes": self.notes,
        }


@dataclass
class FrozenPriceSource:
    """Frozen adjusted closes written by the loader. Never touches the network."""

    root: Path = field(default_factory=lambda: FROZEN / "prices")

    def closes(self, code: str) -> dict[str, float]:
        path = self.root / f"{code}.csv"
        if not path.is_file():
            return {}
        out: dict[str, float] = {}
        with open(path) as fh:
            header = fh.readline()
            if "close" not in header.lower():
                return {}
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) < 2:
                    continue
                try:
                    out[parts[0][:10]] = float(parts[1])
                except ValueError:
                    continue
        return out


def load_short_series(root: Path | None = None) -> dict[str, list[tuple[str, float]]]:
    """Per-code short-interest observations, ascending by date.

    Reads the frozen MCP history. Note the series is DOWNSAMPLED upstream (#540): BHP's
    846 observations arrive as ~170 points, so this is adequate for multi-week horizons
    and must not be treated as daily.
    """
    src = (root or FROZEN / "short_history")
    out: dict[str, list[tuple[str, float]]] = {}
    for path in sorted(src.glob("*.json")):
        if path.stem == "MANIFEST":
            continue
        try:
            pts = json.loads(path.read_text())["structured"]["points"]
        except (KeyError, json.JSONDecodeError):
            logger.warning("unreadable short history: %s", path.name)
            continue
        rows = [
            (str(p["date"])[:10], float(p["short_percent"]))
            for p in pts
            if p.get("short_percent") is not None and p.get("date")
        ]
        if rows:
            out[path.stem] = sorted(rows)
    return out


def knowable_short(
    series: list[tuple[str, float]], as_of: str, lag_days: int = PUBLICATION_LAG_DAYS
) -> float | None:
    """The most recent short reading **publishable** on or before `as_of`.

    This is the function that makes the panel honest, and it is deliberately the
    smallest possible unit so it can be tested directly. An observation dated ``d`` is
    treated as knowable only from ``d + lag_days``.

    When #550 lands this becomes a passthrough of the upstream ``published_at`` rather
    than an assumed offset, and `lag_days` drops to 0.
    """
    from datetime import date

    try:
        cutoff = date.fromisoformat(as_of[:10]) - timedelta(days=lag_days)
    except ValueError:
        return None
    best: float | None = None
    for d, v in series:  # ascending
        try:
            if date.fromisoformat(d) <= cutoff:
                best = v
            else:
                break
        except ValueError:
            continue
    return best


def build_panel(
    dates: list[str],
    spec: PanelSpec,
    price_source: PriceSource | None = None,
    short_root: Path | None = None,
    min_names: int = 10,
) -> dict[str, Any]:
    """Assemble ``{date: {code: {short, price}}}`` under point-in-time rules.

    Rows are emitted only where BOTH a knowable short reading and a price exist, so a
    downstream signal never silently ranks a stock on a stale or absent input — the
    V279 lesson that an input which quietly evaluates to nothing is worse than one that
    errors.
    """
    prices = price_source or FrozenPriceSource()
    shorts = load_short_series(short_root)
    px_cache = {code: prices.closes(code) for code in shorts}

    rows: dict[str, dict[str, dict[str, float]]] = {}
    for d in dates:
        day: dict[str, dict[str, float]] = {}
        for code, series in shorts.items():
            s = knowable_short(series, d, spec.publication_lag_days)
            if s is None:
                continue
            p = px_cache.get(code, {}).get(d)
            if p is None or p <= 0:
                continue
            day[code] = {"short": s, "price": p}
        if len(day) >= min_names:
            rows[d] = day

    return {
        "provenance": spec.provenance(),
        "n_dates": len(rows),
        "n_codes": len({c for day in rows.values() for c in day}),
        "panel": rows,
    }
