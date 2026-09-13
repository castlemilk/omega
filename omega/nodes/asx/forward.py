"""The forward ASX lane: an append-only store and one honest observation a week.

Pre-registered in `training_log/V309_ASX_FORWARD.md`. A PROJECT module: it may use
the platform's live-paper harness (scheduler, checkpoint, runner) and the ASX
project's own panel rules; nothing here places an order, holds capital, or claims
a PnL.

What it owns:

* ``ForwardStore`` — write-ONCE documents under a root, md5s in one manifest. A
  stored key is never rewritten: ASIC short positions are revisable, so re-fetching
  a date would be a different observation, not a refresh.
* ``PriceHistory`` — the frozen v3 prices overlaid with the forward store's daily
  sessions, so point-in-time ADV and prices exist from the first forward day.
* The weekly mark — the realised Q1−Q5 spread and Q1's excess over the
  equal-weight eligible universe, computed under the same rules the backtests use
  (`panel.knowable_short`'s lag, V304's screens, V303's gap exclusion), with the
  comparator's definition written into the record.

Returns are computed on the **unadjusted close** at both ends. The frozen v3
prices are adjusted by the API and the forward prices by yfinance, two bases that
disagree across the seam; the printed close is the one number both sources agree
on. An ex-dividend week therefore carries the dividend as a small negative on every
book alike. Recorded as ``price_basis`` in every mark.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from omega.nodes.asx.panel import PUBLICATION_LAG_DAYS

logger = logging.getLogger("omega.nodes.asx.forward")

ROOT = Path(__file__).resolve().parents[3]
V3 = ROOT / "data" / "frozen_series" / "asx" / "v3"
FROZEN_SHORT_PANEL = ROOT / "data" / "frozen_series" / "asx" / "short_panel"


def default_root() -> Path:
    env = os.environ.get("OMEGA_ASX_FORWARD_DIR", "").strip()
    return Path(env) if env else ROOT / "data" / "asx_forward"


KINDS = ("short_panel", "prices", "intraday_1h")

# V304/V308 screens, unchanged.
MIN_PRICE_AUD = 0.20
MIN_ADV_AUD = 500_000.0
MIN_NAMES = 50
QUINTILE = 0.20
CALENDAR_CODE = "BHP"

COMPARATOR = (
    "equal-weight eligible universe (unadjusted close >= 0.20 AUD and point-in-time "
    "ADV20 >= 500k AUD at the formed date); names priced at both ends only, a missing "
    "price is excluded not charged 0%"
)
PRICE_BASIS = "close_unadjusted"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------
def _md5(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()


class ForwardStore:
    """Append-only JSON documents. ``write_once`` refuses to overwrite."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        for k in KINDS:
            (self.root / k).mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "MANIFEST.json"
        self.marks_path = self.root / "marks.jsonl"

    def _path(self, kind: str, key: str) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown store kind {kind!r}")
        return self.root / kind / f"{key}.json"

    def has(self, kind: str, key: str) -> bool:
        return self._path(kind, key).is_file()

    def keys(self, kind: str) -> list[str]:
        return sorted(p.stem for p in (self.root / kind).glob("*.json"))

    def read(self, kind: str, key: str) -> dict[str, Any]:
        doc: dict[str, Any] = json.loads(self._path(kind, key).read_text())
        return doc

    def manifest(self) -> dict[str, Any]:
        if self.manifest_path.is_file():
            man: dict[str, Any] = json.loads(self.manifest_path.read_text())
            return man
        return {"_note": "md5 of every write-once document in this store", "files": {}}

    def write_once(self, kind: str, key: str, doc: dict[str, Any]) -> str | None:
        """Write ``doc`` unless ``key`` exists. Returns the md5 written, or None."""
        path = self._path(kind, key)
        if path.exists():
            return None
        blob = (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, path)
        md5 = _md5(blob)
        man = self.manifest()
        man["files"][f"{kind}/{key}.json"] = md5
        self.manifest_path.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
        return md5

    def lane_start(self) -> str | None:
        """The lane's first cycle date. A mark formed before it is a BACKFILL over the
        frozen window, not a forward observation, and is flagged as such."""
        v = self.manifest().get("lane_start")
        return str(v) if v else None

    def ensure_lane_start(self, d: str) -> str:
        man = self.manifest()
        if not man.get("lane_start"):
            man["lane_start"] = d
            self.manifest_path.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
        return str(man["lane_start"])

    def marks(self) -> list[dict[str, Any]]:
        if not self.marks_path.is_file():
            return []
        out = []
        with open(self.marks_path) as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def append_mark(self, rec: dict[str, Any]) -> bool:
        """Append unless a mark for the same ``mark_date`` exists. Returns whether written."""
        if any(m.get("mark_date") == rec["mark_date"] for m in self.marks()):
            return False
        with open(self.marks_path, "a") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return True


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------
def panel_doc(d: str, stocks: list[dict[str, Any]], tier: str, total_count: Any) -> dict[str, Any]:
    """Same shape as the frozen `short_panel/` files, so one reader serves both."""
    from datetime import UTC, datetime

    return {
        "date": d,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": "shorts.v1alpha1.MarketService/GetMarketByDate",
        "tier": tier,
        "total_count": total_count,
        "n_returned": len(stocks),
        "stocks": stocks,
    }


def panel_shorts(doc: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in doc.get("stocks", []):
        c = s.get("productCode")
        p = s.get("percentageShorted")
        if c and p is not None:
            out[str(c)] = float(p)
    return out


def prices_doc(session: str, rows: dict[str, list[float]]) -> dict[str, Any]:
    return {
        "session": session,
        "source": "yfinance 1d auto_adjust=False",
        "columns": ["close", "adjusted_close", "volume"],
        "n": len(rows),
        "rows": rows,
    }


def intraday_doc(session: str, bars: dict[str, list[list[Any]]]) -> dict[str, Any]:
    return {
        "session": session,
        "source": "yfinance 1h auto_adjust=False",
        "tz": "Australia/Sydney",
        "columns": ["ts_local", "open_ms", "open", "high", "low", "close", "volume"],
        "n_codes": len(bars),
        "bars": bars,
    }


# ---------------------------------------------------------------------------
# panels: frozen dir + forward store, one view
# ---------------------------------------------------------------------------
def panel_dates(
    store: ForwardStore | None, frozen_dir: Path | None = FROZEN_SHORT_PANEL
) -> list[str]:
    dates: set[str] = set()
    if frozen_dir is not None and frozen_dir.is_dir():
        dates |= {p.stem for p in frozen_dir.glob("*.json") if p.stem != "MANIFEST"}
    if store is not None:
        dates |= set(store.keys("short_panel"))
    return sorted(dates)


def load_panel(
    d: str, store: ForwardStore | None, frozen_dir: Path | None = FROZEN_SHORT_PANEL
) -> dict[str, float]:
    if store is not None and store.has("short_panel", d):
        return panel_shorts(store.read("short_panel", d))
    if frozen_dir is not None and (frozen_dir / f"{d}.json").is_file():
        return panel_shorts(json.loads((frozen_dir / f"{d}.json").read_text()))
    raise FileNotFoundError(d)


def knowable_panel_date(
    dates: list[str], as_of: str, lag_days: int = PUBLICATION_LAG_DAYS
) -> str | None:
    """Latest panel date publishable on or before ``as_of``: exactly `knowable_short`'s rule."""
    cutoff = (date.fromisoformat(as_of) - timedelta(days=lag_days)).isoformat()
    best = None
    for d in sorted(dates):
        if d <= cutoff:
            best = d
        else:
            break
    return best


# ---------------------------------------------------------------------------
# prices: v3 history overlaid with the forward store
# ---------------------------------------------------------------------------
@dataclass
class PriceHistory:
    """Per-code ``{date: (close, adjusted_close, volume)}`` from v3 + forward sessions."""

    series: dict[str, dict[str, tuple[float, float, float]]]

    @classmethod
    def load(
        cls, store: ForwardStore | None, v3_root: Path | None = V3, codes: set[str] | None = None
    ) -> PriceHistory:
        series: dict[str, dict[str, tuple[float, float, float]]] = {}
        if v3_root is not None and (v3_root / "prices").is_dir():
            for f in (v3_root / "prices").glob("*.csv"):
                code = f.stem
                if codes is not None and code not in codes:
                    continue
                with f.open() as fh:
                    rd = csv.DictReader(fh)
                    s: dict[str, tuple[float, float, float]] = {}
                    for r in rd:
                        try:
                            s[r["date"][:10]] = (
                                float(r["close"]),
                                float(r["adjusted_close"]),
                                float(r["volume"] or 0),
                            )
                        except (ValueError, KeyError):
                            continue
                if s:
                    series[code] = s
        if store is not None:
            for sess in store.keys("prices"):
                doc = store.read("prices", sess)
                for code, row in doc["rows"].items():
                    if codes is not None and code not in codes:
                        continue
                    series.setdefault(code, {})[sess] = (
                        float(row[0]),
                        float(row[1]),
                        float(row[2]),
                    )
        return cls(series)

    def sessions(self) -> list[str]:
        return sorted(self.series.get(CALENDAR_CODE, {}))

    def close(self, code: str, d: str) -> float | None:
        row = self.series.get(code, {}).get(d)
        return row[0] if row and row[0] > 0 else None

    def adv20(self, code: str, d: str) -> float | None:
        """Trailing 20-session dollar volume ending at or before ``d``. None if < 20."""
        s = self.series.get(code)
        if not s:
            return None
        days = sorted(k for k in s if k <= d)[-20:]
        if len(days) < 20:
            return None
        return sum(s[k][0] * s[k][2] for k in days) / 20.0

    def closes_on(self, d: str) -> dict[str, float]:
        return {c: s[d][0] for c, s in self.series.items() if d in s and s[d][0] > 0}


def eligible_at(hist: PriceHistory, codes: set[str], d: str) -> set[str]:
    out = set()
    for c in codes:
        px = hist.close(c, d)
        if px is None or px < MIN_PRICE_AUD:
            continue
        adv = hist.adv20(c, d)
        if adv is None or adv < MIN_ADV_AUD:
            continue
        out.add(c)
    return out


# ---------------------------------------------------------------------------
# the mark
# ---------------------------------------------------------------------------
def quintile_books(
    shorts: dict[str, float], eligible: set[str], min_names: int = MIN_NAMES
) -> dict[str, list[str]] | None:
    names = sorted(c for c in shorts if c in eligible)
    if len(names) < min_names:
        return None
    ranked = sorted(names, key=lambda c: (shorts[c], c))  # least shorted first; ties by code
    k = max(1, int(len(ranked) * QUINTILE))
    return {"Q1": ranked[:k], "Q5": ranked[-k:], "universe": names}


def realise(codes: list[str], p0: dict[str, float], p1: dict[str, float]) -> dict[str, Any]:
    rets = []
    gap = 0
    for c in codes:
        a, b = p0.get(c), p1.get(c)
        if a and b and a > 0:
            rets.append(b / a - 1.0)
        else:
            gap += 1
    return {"ret": (sum(rets) / len(rets)) if rets else None, "n": len(rets), "n_gap": gap}


def complete_weeks(sessions: list[str]) -> list[tuple[str, list[str]]]:
    """(last session, sessions) per ISO week that is complete: ends on a Friday, or a
    later week's session exists."""
    by_week: dict[tuple[int, int], list[str]] = {}
    for s in sorted(sessions):
        y, w, _ = date.fromisoformat(s).isocalendar()
        by_week.setdefault((y, w), []).append(s)
    weeks = sorted(by_week)
    out = []
    for i, wk in enumerate(weeks):
        ss = by_week[wk]
        last = ss[-1]
        if date.fromisoformat(last).weekday() == 4 or i + 1 < len(weeks):
            out.append((last, ss))
    return out


def weekly_mark_from(
    *,
    formed_date: str,
    mark_date: str,
    panel_date: str,
    shorts: dict[str, float],
    eligible: set[str],
    p0: dict[str, float],
    p1: dict[str, float],
    lag_days: int = PUBLICATION_LAG_DAYS,
    lane_start: str | None = None,
    min_names: int = MIN_NAMES,
) -> dict[str, Any] | None:
    books = quintile_books(shorts, eligible, min_names=min_names)
    if books is None:
        return None
    q1, q5, un = (
        realise(books["Q1"], p0, p1),
        realise(books["Q5"], p0, p1),
        realise(books["universe"], p0, p1),
    )
    if q1["ret"] is None or q5["ret"] is None or un["ret"] is None:
        return None
    return {
        "mark_date": mark_date,
        "formed_date": formed_date,
        "panel_date": panel_date,
        "lag_days": lag_days,
        "eligible_n": len(books["universe"]),
        "q1": q1,
        "q5": q5,
        "universe": un,
        "spread_q1_q5": q1["ret"] - q5["ret"],
        "excess_q1_vs_ew": q1["ret"] - un["ret"],
        "comparator": COMPARATOR,
        "price_basis": PRICE_BASIS,
        # True only when the book was formed on or after the lane's first cycle:
        # a forward observation nobody could have tuned to. Everything else is a
        # backfill over the frozen window and never counts toward the 52.
        "forward": bool(lane_start) and formed_date >= str(lane_start),
    }


def due_marks(
    store: ForwardStore | None,
    hist: PriceHistory,
    already: set[str],
    frozen_dir: Path | None = FROZEN_SHORT_PANEL,
    lag_days: int = PUBLICATION_LAG_DAYS,
    lane_start: str | None = None,
) -> list[dict[str, Any]]:
    """Every complete week not yet marked whose previous week's last session exists."""
    pdates = panel_dates(store, frozen_dir)
    if not pdates:
        return []
    weeks = complete_weeks(hist.sessions())
    out: list[dict[str, Any]] = []
    for i in range(1, len(weeks)):
        formed, mark = weeks[i - 1][0], weeks[i][0]
        if mark in already:
            continue
        pd = knowable_panel_date(pdates, formed, lag_days)
        if pd is None:
            continue
        shorts = load_panel(pd, store, frozen_dir)
        p0, p1 = hist.closes_on(formed), hist.closes_on(mark)
        elig = eligible_at(hist, set(shorts) & set(p0), formed)
        rec = weekly_mark_from(
            formed_date=formed,
            mark_date=mark,
            panel_date=pd,
            shorts=shorts,
            eligible=elig,
            p0=p0,
            p1=p1,
            lag_days=lag_days,
            lane_start=lane_start,
        )
        if rec is not None:
            out.append(rec)
    return out
