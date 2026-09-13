"""ASX intraday corpus: frozen-file encoding, session assembly, time-of-day buckets.

Pre-registered in `training_log/V307_ASX_INTRADAY.md`. Pure functions over frozen
JSON — nothing here downloads, trades or sizes. The freeze itself lives in
`scripts/v307_freeze_asx_intraday.py`; this module owns the parts that must be
testable offline: the byte-deterministic encoder, session/bucket assembly and the
small statistics the map is made of.

Three rules from the ASX line, applied without exception:

* **A missing bar is excluded, never defaulted** (V303). A bucket exists for a
  session only if BOTH prices it needs are present. Nothing is filled with 0.
* **Read the metadata about itself** (V302). Every stamp is checked against the
  seven the ASX session has; anything else is a reported defect, not a silent row.
* **An input that quietly evaluates to something is worse than one that errors**
  (V293). `ex_dividend_dates` is computed from the adjusted/unadjusted ratio; if a
  daily series is absent the caller gets ``None`` and must decide, not an empty set.

Sydney local time throughout. The 16:00 bar is the closing auction (16:00–16:10).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
FROZEN_INTRADAY = ROOT / "data" / "frozen_series" / "asx" / "intraday"

TZ = "Australia/Sydney"
STAMPS_1H: tuple[str, ...] = ("10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00")
BUCKETS: tuple[str, ...] = ("ON", "B10", "B11", "B12", "B13", "B14", "B15", "B16")
COLUMNS: tuple[str, ...] = ("ts_local", "open_ms", "open", "high", "low", "close", "volume")

# Column offsets inside a bar row.
_TS, _MS, _O, _H, _L, _C, _V = range(7)

# A dividend of $0.01 on a $200 stock moves the adjusted/close ratio by 5e-5; the
# threshold sits under that so no real dividend is missed, and above float noise.
EX_DIV_RATIO_TOL = 2e-5


# ---------------------------------------------------------------------------
# frozen-file encoding (byte-deterministic)
# ---------------------------------------------------------------------------
def encode_frozen(doc: dict[str, Any]) -> bytes:
    """gzip(JSON) with sorted keys, compact separators and ``mtime=0``.

    The same ``doc`` always encodes to the same bytes, so an md5 in the manifest
    is a statement about the data and nothing else (the V262 writer's property).
    """
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(payload)
    return buf.getvalue()


def md5_of(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()


def load_frozen(code: str, interval: str = "1h", root: Path | None = None) -> dict[str, Any]:
    path = (root or FROZEN_INTRADAY) / interval / f"{code}.json.gz"
    with gzip.open(path, "rb") as fh:
        doc: dict[str, Any] = json.load(fh)
    return doc


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    man: dict[str, Any] = json.loads(((root or FROZEN_INTRADAY) / "MANIFEST.json").read_text())
    return man


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionDefects:
    """What the corpus said about itself. Reported, never hidden."""

    off_stamp_bars: int  # bars whose local stamp is not one of STAMPS_1H
    nan_close_bars: int  # bars retained upstream with a non-finite close
    incomplete_sessions: int  # sessions missing ≥1 of the seven stamps
    sessions: int


def sessions(
    doc: dict[str, Any], stamps: tuple[str, ...] = STAMPS_1H
) -> tuple[dict[str, dict[str, list[float]]], SessionDefects]:
    """Group bars by local date → {stamp: [open, high, low, close, volume]}.

    Bars at an unexpected stamp are dropped AND counted; a session is kept even
    when incomplete (the bucket step decides, per bucket, what it can compute).
    """
    if tuple(doc.get("columns", ())) != COLUMNS:
        raise ValueError(f"unexpected columns {doc.get('columns')!r}")
    out: dict[str, dict[str, list[float]]] = {}
    off = nan = 0
    for row in doc["bars"]:
        ts = row[_TS]
        day, stamp = ts[:10], ts[11:16]
        if stamp not in stamps:
            off += 1
            continue
        close = row[_C]
        if close is None or not math.isfinite(close):
            nan += 1
            continue
        out.setdefault(day, {})[stamp] = [row[_O], row[_H], row[_L], row[_C], row[_V]]
    incomplete = sum(1 for s in out.values() if len(s) < len(stamps))
    return out, SessionDefects(off, nan, incomplete, len(out))


# ---------------------------------------------------------------------------
# ex-dividend detection from a daily adjusted/unadjusted pair
# ---------------------------------------------------------------------------
def ex_dividend_dates(
    daily: list[tuple[str, float, float]], tol: float = EX_DIV_RATIO_TOL
) -> set[str]:
    """Dates where adjusted_close/close changed versus the previous session.

    ``daily`` is ``[(date, close, adjusted_close), ...]`` in ascending date order.
    A change in the ratio is a corporate action (dividend or split) taking effect
    that day; the overnight return into such a day is not a pattern.
    """
    out: set[str] = set()
    prev: float | None = None
    for day, close, adj in daily:
        if not close or not adj or not math.isfinite(close) or not math.isfinite(adj):
            prev = None  # a gap in the daily series says nothing about the next day
            continue
        ratio = adj / close
        if prev is not None and abs(ratio / prev - 1.0) > tol:
            out.add(day)
        prev = ratio
    return out


# ---------------------------------------------------------------------------
# buckets
# ---------------------------------------------------------------------------
def bucket_returns(
    sess: dict[str, dict[str, list[float]]],
    ex_div: set[str] | None,
) -> dict[str, dict[str, float]]:
    """Per session → {bucket: simple return}. A bucket is absent when it cannot be
    computed from the bars that exist — never present as 0.0.

    ``ex_div=None`` means "no daily series was available": ``ON`` is then computed
    for no session at all, because a filter that silently applies to nothing is
    the V293 failure. Pass an empty set to assert there are no ex-div days.
    """
    days = sorted(sess)
    out: dict[str, dict[str, float]] = {}
    prev_close: float | None = None
    for day in days:
        s = sess[day]
        r: dict[str, float] = {}
        c10 = s.get("10:00")
        if c10 is not None:
            if prev_close and ex_div is not None and day not in ex_div and c10[0] > 0:
                r["ON"] = c10[0] / prev_close - 1.0
            if c10[0] > 0:
                r["B10"] = c10[3] / c10[0] - 1.0
        for i in range(1, len(STAMPS_1H)):
            a, b = s.get(STAMPS_1H[i - 1]), s.get(STAMPS_1H[i])
            if a is not None and b is not None and a[3] > 0:
                r[f"B{STAMPS_1H[i][:2]}"] = b[3] / a[3] - 1.0
        c16 = s.get("16:00")
        prev_close = c16[3] if c16 is not None and c16[3] > 0 else None
        if r:
            out[day] = r
    return out


def ew_daily(
    per_name: dict[str, dict[str, dict[str, float]]],
    min_names: int = 20,
) -> dict[str, list[tuple[str, float, int]]]:
    """Equal-weight cross-sectional mean per (bucket, date) → {bucket: [(date, mean, n)]}.

    A date with fewer than ``min_names`` contributing names is dropped for that
    bucket: an average of three names is not a cross-section.
    """
    acc: dict[str, dict[str, list[float]]] = {b: {} for b in BUCKETS}
    for _code, by_day in per_name.items():
        for day, r in by_day.items():
            for b, v in r.items():
                acc[b].setdefault(day, []).append(v)
    out: dict[str, list[tuple[str, float, int]]] = {}
    for b in BUCKETS:
        rows = [
            (day, statistics.fmean(vals), len(vals))
            for day, vals in sorted(acc[b].items())
            if len(vals) >= min_names
        ]
        out[b] = rows
    return out


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stat:
    n: int
    mean: float
    sd: float
    t: float  # nan when undefined (n < 2 or sd == 0)

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "n": self.n,
            "mean": self.mean,
            "mean_bps": self.mean * 1e4,
            "sd": self.sd,
            "t": None if math.isnan(self.t) else self.t,
        }


def tstat(xs: list[float]) -> Stat:
    n = len(xs)
    if n == 0:
        return Stat(0, math.nan, math.nan, math.nan)
    if n == 1:
        return Stat(1, xs[0], math.nan, math.nan)
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    t = mean / (sd / math.sqrt(n)) if sd > 0 else math.nan
    return Stat(n, mean, sd, t)


def split_halves(rows: list[tuple[str, float, int]], cut: str) -> tuple[list[float], list[float]]:
    """Values dated strictly before ``cut`` and on/after it."""
    return [m for d, m, _ in rows if d < cut], [m for d, m, _ in rows if d >= cut]


def volume_profile(sess: dict[str, dict[str, list[float]]]) -> dict[str, float]:
    """Median across complete sessions of each stamp's share of session volume."""
    shares: dict[str, list[float]] = {s: [] for s in STAMPS_1H}
    for s in sess.values():
        if len(s) < len(STAMPS_1H):
            continue
        tot = sum(s[k][4] for k in STAMPS_1H)
        if tot <= 0:
            continue
        for k in STAMPS_1H:
            shares[k].append(s[k][4] / tot)
    return {k: (statistics.median(v) if v else math.nan) for k, v in shares.items()}
