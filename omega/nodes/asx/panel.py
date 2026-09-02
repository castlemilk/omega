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


@dataclass
class ApiPriceSource:
    """Adjusted closes AND volume from the upstream API freeze (#549 seam, now filled).

    Replaces the yfinance freeze for three reasons upstream states directly: the same
    ticker convention as the short series (BHP, not BHP.AX), ONE split/dividend
    adjustment methodology instead of two unauditable ones, and a universe that agrees
    with the short data by construction.

    It also carries ``volume``, which is what finally makes `PortfolioSpec.min_adv_aud`
    a real filter instead of a declared-and-inert one. Before this, the engine had no
    liquidity screen at all and loaded up on sub-cent stocks where a one-tick move is a
    +20% return — a single half-cent name (AEU, $0.0140 -> $0.3500) contributed +200%
    to one week and made the whole study unreadable.
    """

    root: Path = field(default_factory=lambda: FROZEN / "prices_api")

    def _rows(self, code: str) -> list[tuple[str, float, float]]:
        path = self.root / f"{code}.csv"
        if not path.is_file():
            return []
        out = []
        with open(path) as fh:
            fh.readline()
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                try:
                    out.append((parts[0][:10], float(parts[1]), float(parts[3] or 0)))
                except ValueError:
                    continue
        return out

    def closes(self, code: str) -> dict[str, float]:
        return {d: px for d, px, _ in self._rows(code)}

    def adv20(self, code: str) -> dict[str, float]:
        """Trailing 20-session average DOLLAR volume, point-in-time.

        Keyed by date and computed from sessions at or BEFORE that date only, so it
        never reveals future liquidity. A name with fewer than 20 prior sessions gets
        no value at all rather than a short-window average, because an ADV computed
        from three days is exactly the kind of number that quietly passes a filter it
        should not.
        """
        rows = self._rows(code)
        out: dict[str, float] = {}
        window: list[float] = []
        for d, px, vol in rows:
            window.append(px * vol)
            if len(window) > 20:
                window.pop(0)
            if len(window) == 20:
                out[d] = sum(window) / 20.0
        return out


def load_short_series_csv(root: Path) -> dict[str, list[tuple[str, float]]]:
    """Per-code short-interest observations from the v3 rebuild (CSV, `date,short_pct`).

    The v3 layout is the point-in-time universe (see `scripts/asx_build_universe.py`).
    Each series is dated, so a name's own file states the dates it was reported and
    therefore defines its universe membership — a delisted company simply has no rows
    after it delisted, which is exactly the point-in-time behaviour the old survivor
    freeze could not express.
    """
    out: dict[str, list[tuple[str, float]]] = {}
    for path in sorted(root.glob("*.csv")):
        rows: list[tuple[str, float]] = []
        with open(path) as fh:
            fh.readline()
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) < 2:
                    continue
                try:
                    rows.append((parts[0][:10], float(parts[1])))
                except ValueError:
                    continue
        if rows:
            out[path.stem] = sorted(rows)
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
    short_series: dict[str, list[tuple[str, float]]] | None = None,
) -> dict[str, Any]:
    """Assemble ``{date: {code: {short, price}}}`` under point-in-time rules.

    Rows are emitted only where BOTH a knowable short reading and a price exist, so a
    downstream signal never silently ranks a stock on a stale or absent input — the
    V279 lesson that an input which quietly evaluates to nothing is worse than one that
    errors.
    """
    prices = price_source or FrozenPriceSource()
    shorts = short_series if short_series is not None else load_short_series(short_root)
    px_cache = {code: prices.closes(code) for code in shorts}
    # adv20 is optional on the Protocol: only ApiPriceSource has volume. A source
    # without it yields no liquidity data, and PortfolioSpec then reports its ADV
    # filter as inert rather than silently passing every name.
    adv_fn = getattr(prices, "adv20", None)
    adv_cache = {code: adv_fn(code) for code in shorts} if adv_fn else {}

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
            row = {"short": s, "price": p}
            adv = adv_cache.get(code, {}).get(d)
            if adv is not None:
                row["adv20_aud"] = adv
            day[code] = row
        if len(day) >= min_names:
            rows[d] = day

    return {
        "provenance": spec.provenance(),
        "n_dates": len(rows),
        "n_codes": len({c for day in rows.values() for c in day}),
        "has_liquidity": bool(adv_cache),
        "panel": rows,
    }
