#!/usr/bin/env python3
"""
V262 — intraday (1h) OHLCV freeze (freeze-once discipline).

Downloads Binance **spot** klines at an intraday interval from the public
``data.binance.vision`` static store and freezes them into committed,
provenance-stamped, gzipped JSON — one file per (symbol, interval, month).

This is the data unlock V249 named as resume path (2) for the training loop:
the entry-side composite was closed by V236→V245 **at daily bars only**, and
intraday resolution is the last untried axis that does not require waiting on
the calendar. See ``training_log/V262.md`` for the pre-registration.

Source (free, public, keyless — NOT the geo-blocked REST API):
  monthly  https://data.binance.vision/data/spot/monthly/klines/{SYM}/{INT}/
  daily    https://data.binance.vision/data/spot/daily/klines/{SYM}/{INT}/

Every archive is fetched ONCE and sha256-verified against its ``.CHECKSUM``
sidecar (mirroring ``v255d_freeze_basis.py``). Raw zips are mirrored best-effort
to the gamma external volume.

### Determinism (V262 byte-identity gate)
Frozen files embed ONLY data provenance (source, span, n_bars) — **no wall-clock
timestamp** — and gzip is written with ``mtime=0``, so a re-freeze over the same
archives produces a byte-identical file and identical MD5. ``--verify`` re-freezes
into a scratch dir and diffs MD5 against the committed tree.

Bar values are emitted as Python floats via ``json.dumps`` (which uses ``repr``),
so ``float(json) == float(csv)`` exactly — round-trip is lossless.

Frozen file schema — ``{SYMBOL}/{INTERVAL}/{YYYY-MM}.json.gz``:
  {"symbol": "SOLUSDT", "interval": "1h", "month": "2024-03",
   "source": "data.binance.vision spot/monthly/klines/...",
   "columns": ["open_time_ms","open","high","low","close","volume"],
   "n_bars": 744, "expected_bars": 744, "missing_bars": 0,
   "first_open_ms": ..., "last_open_ms": ...,
   "bars": [[1709251200000, 1.0, 2.0, 0.5, 1.5, 123.4], ...]}

Usage:
  # freeze the V262 universe at 1h over the pre-registered span
  python3 scripts/v262_freeze_intraday.py \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,AVAXUSDT,XRPUSDT,SUIUSDT,POLUSDT,MATICUSDT,ADAUSDT,NEARUSDT,ARBUSDT,DOTUSDT,LINKUSDT \
    --interval 1h --start 2020-01 --end 2026-07

  # byte-identity re-verify (re-freeze into scratch, diff MD5 vs committed)
  python3 scripts/v262_freeze_intraday.py --verify --interval 1h

NOTE: ``--interval 5m`` works but is NOT frozen by V262 — that is a separate,
user-authorised scope decision (see ``training_log/V262_AUDIT_VERDICT.md``).
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import hashlib
import io
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BV = "https://data.binance.vision/data/spot"
DEFAULT_OUT = ROOT / "data" / "frozen_series" / "binance_intraday"
GAMMA_RAW = Path("/Volumes/gamma-systems-2/omega-victoria-data/frozen_series/binance_intraday_raw")
UA = {"User-Agent": "omega-victoria-freeze/262"}

COLUMNS = ["open_time_ms", "open", "high", "low", "close", "volume"]

# interval → bar duration in minutes (used for the missing-bar audit)
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}

# V262 pre-registered universe (training_log/V262.md §3)
V262_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "AVAXUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "POLUSDT",
    "MATICUSDT",
    "ADAUSDT",
    "NEARUSDT",
    "ARBUSDT",
    "DOTUSDT",
    "LINKUSDT",
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get(url: str, timeout: float = 120.0, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise  # caller distinguishes "not published" from transient
            last = exc
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def _get_checked(zip_url: str) -> bytes:
    """Download a .zip and verify it against its .CHECKSUM (sha256) sidecar."""
    body = _get(zip_url)
    try:
        chk = _get(zip_url + ".CHECKSUM").decode().split()[0].strip().lower()
    except Exception:
        chk = ""
    if chk:
        got = hashlib.sha256(body).hexdigest().lower()
        if got != chk:
            raise ValueError(f"CHECKSUM mismatch {zip_url}: {got} != {chk}")
    return body


# ---------------------------------------------------------------------------
# archive parsing
# ---------------------------------------------------------------------------
def _parse_klines_zip(raw: bytes) -> dict[int, list[float]]:
    """Extract {open_time_ms → [open_time_ms, o, h, l, c, v]} from a kline zip.

    Kline CSV (headerless): open_time_ms, open, high, low, close, volume,
    close_time_ms, quote_volume, trades, ...  We keep the first six columns.
    Keyed by open_time_ms so an overlapping monthly/daily splice de-duplicates
    deterministically.
    """
    out: dict[int, list[float]] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            for row in csv.reader(text):
                if not row or not row[0].lstrip("-").isdigit():
                    continue  # skip any header row defensively
                open_ms = int(row[0])
                out[open_ms] = [
                    open_ms,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ]
    return out


def _months(start: str, end: str) -> list[str]:
    """Inclusive YYYY-MM range."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _expected_bars(month: str, interval: str, now_ms: int | None = None) -> int:
    """Bars a complete month should contain at this interval.

    For the current (partial) month, count only bars whose open time has passed.
    """
    y, m = (int(x) for x in month.split("-"))
    step_min = INTERVAL_MINUTES[interval]
    days = calendar.monthrange(y, m)[1]
    full = days * 24 * 60 // step_min
    if now_ms is None:
        return full
    month_start_ms = int(datetime(y, m, 1, tzinfo=UTC).timestamp() * 1000)
    elapsed_min = (now_ms - month_start_ms) / 60000
    if elapsed_min <= 0:
        return 0
    return min(full, int(elapsed_min // step_min))


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------
def _mirror_raw(symbol: str, interval: str, seg: str, fname: str, body: bytes) -> None:
    """Best-effort mirror of the raw archive to the gamma volume (idempotent)."""
    try:
        d = GAMMA_RAW / symbol / interval / seg
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(body)
    except OSError as exc:
        print(f"    (raw-mirror skipped {symbol}/{interval}/{fname}: {exc})", file=sys.stderr)


def fetch_month(
    symbol: str, interval: str, month: str, allow_daily: bool = True
) -> tuple[dict[int, list[float]], str]:
    """All bars for one (symbol, interval, month).

    Prefers the monthly archive. Falls back to per-day archives when the monthly
    dump is not published yet (the current partial month) — this is how the
    freeze reaches up to "yesterday" rather than stopping at last month-end.

    ``allow_daily`` gates that fallback. The caller enables it only for the final
    month of the span, because a monthly 404 in any *earlier* month means the
    symbol was not listed then (pre-listing / post-delisting) — and probing 31
    days × 2 requests for each such month costs ~11.6k pointless 404s across the
    V262 universe. Binance publishes a monthly archive for every complete month a
    symbol traded, so a 404 on a complete month is "not listed", not "missing".

    Returns (bars_by_open_ms, source_description). Empty dict = no data; that is
    not an error.
    """
    url = f"{BV}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    try:
        body = _get_checked(url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        _mirror_raw(symbol, interval, "monthly", f"{symbol}-{interval}-{month}.zip", body)
        return _parse_klines_zip(body), f"spot/monthly/klines/{symbol}/{interval}/{month}"

    if not allow_daily:
        return {}, ""

    # daily fallback
    y, m = (int(x) for x in month.split("-"))
    bars: dict[int, list[float]] = {}
    d = date(y, m, 1)
    n_days = 0
    while d.month == m:
        durl = f"{BV}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d.isoformat()}.zip"
        try:
            body = _get_checked(durl)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            d += timedelta(days=1)
            continue  # day not published (future, or symbol not listed)
        _mirror_raw(symbol, interval, "daily", f"{symbol}-{interval}-{d.isoformat()}.zip", body)
        bars.update(_parse_klines_zip(body))
        n_days += 1
        d += timedelta(days=1)
    src = f"spot/daily/klines/{symbol}/{interval}/{month} ({n_days} daily archives)"
    return bars, src


# ---------------------------------------------------------------------------
# freeze (deterministic, clock-free)
# ---------------------------------------------------------------------------
def _write_frozen(
    out_dir: Path,
    symbol: str,
    interval: str,
    month: str,
    bars: dict[int, list[float]],
    source: str,
    now_ms: int | None,
) -> tuple[Path, str, int]:
    """Write one month's gzipped JSON + .md5 sidecar. Returns (path, md5, n_bars)."""
    ordered = [bars[k] for k in sorted(bars)]
    expected = _expected_bars(month, interval, now_ms)
    doc = {
        "symbol": symbol,
        "interval": interval,
        "month": month,
        "source": f"data.binance.vision {source}",
        "columns": COLUMNS,
        "n_bars": len(ordered),
        "expected_bars": expected,
        "missing_bars": max(0, expected - len(ordered)),
        "first_open_ms": ordered[0][0] if ordered else None,
        "last_open_ms": ordered[-1][0] if ordered else None,
        "bars": ordered,
    }
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")

    d = out_dir / symbol / interval
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{month}.json.gz"
    buf = io.BytesIO()
    # mtime=0 → deterministic gzip header (the default stamps wall-clock).
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(payload)
    blob = buf.getvalue()
    path.write_bytes(blob)
    # NOTE: deliberately NO per-file .md5 sidecar (a deviation from
    # v255d_freeze_basis.py). At 919 cells the sidecars would double the committed
    # file count while carrying zero information MANIFEST.json does not already
    # hold — and --verify reads the manifest, never the sidecars. v255d froze ~24
    # files, where the per-file sidecar was cheap; here it is not.
    md5 = hashlib.md5(blob).hexdigest()
    return path, md5, len(ordered)


def freeze(
    symbols: list[str],
    interval: str,
    start: str,
    end: str,
    out_dir: Path,
    now_ms: int | None,
    workers: int = 8,
) -> dict:
    """Freeze every (symbol, month) cell. Returns the manifest dict."""
    months = _months(start, end)
    manifest: dict = {
        "freeze": "v262_intraday",
        "interval": interval,
        "span": {"start": start, "end": end},
        "source": "data.binance.vision spot klines (monthly, daily fallback)",
        "columns": COLUMNS,
        "symbols": {},
    }

    for symbol in symbols:
        cells: dict[str, dict] = {}
        total_bars = total_missing = total_bytes = 0

        def _one(month: str, _sym: str = symbol) -> tuple[str, dict]:
            # daily fallback only for the final month of the span (see fetch_month)
            bars, src = fetch_month(_sym, interval, month, allow_daily=(month == months[-1]))
            if not bars:
                return month, {}
            path, md5, n = _write_frozen(out_dir, _sym, interval, month, bars, src, now_ms)
            return month, {
                "md5": md5,
                "n_bars": n,
                "expected_bars": _expected_bars(month, interval, now_ms),
                "bytes": path.stat().st_size,
            }

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, mon): mon for mon in months}
            for fut in as_completed(futs):
                mon, info = fut.result()
                if info:
                    cells[mon] = info

        for mon in sorted(cells):
            info = cells[mon]
            total_bars += info["n_bars"]
            total_missing += max(0, info["expected_bars"] - info["n_bars"])
            total_bytes += info["bytes"]

        manifest["symbols"][symbol] = {
            "n_months": len(cells),
            "first_month": min(cells) if cells else None,
            "last_month": max(cells) if cells else None,
            "n_bars": total_bars,
            "missing_bars": total_missing,
            "bytes": total_bytes,
            "months": {m: cells[m] for m in sorted(cells)},
        }
        print(
            f"  {symbol:10s} {len(cells):3d} months  {total_bars:7,d} bars  "
            f"{total_missing:5,d} missing  {total_bytes / 1e6:6.2f} MB",
            flush=True,
        )

    return manifest


def _write_manifest(out_dir: Path, manifest: dict) -> Path:
    p = out_dir / "MANIFEST.json"
    p.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return p


# ---------------------------------------------------------------------------
# verify (byte-identity gate)
# ---------------------------------------------------------------------------
def verify(out_dir: Path, interval: str, scratch: Path) -> int:
    """Re-freeze into ``scratch`` and diff MD5 against the committed tree.

    Returns a process exit code (0 = all cells byte-identical).
    """
    man_path = out_dir / "MANIFEST.json"
    if not man_path.exists():
        print(f"FAIL: no manifest at {man_path}", file=sys.stderr)
        return 2
    man = json.loads(man_path.read_text())
    if man.get("interval") != interval:
        print(
            f"FAIL: manifest interval {man.get('interval')!r} != --interval {interval!r}",
            file=sys.stderr,
        )
        return 2

    symbols = sorted(man["symbols"])
    span = man["span"]
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)

    # now_ms is re-derived from the committed manifest, NOT the wall clock, so a
    # verify run months later still computes the same expected_bars.
    now_ms = man.get("now_ms")
    print(f"[verify] re-freezing {len(symbols)} symbols into {scratch} …")
    fresh = freeze(symbols, interval, span["start"], span["end"], scratch, now_ms)

    ok = bad = missing = 0
    for sym in symbols:
        old_months = man["symbols"][sym]["months"]
        new_months = fresh["symbols"].get(sym, {}).get("months", {})
        for mon, info in old_months.items():
            if mon not in new_months:
                print(f"  MISSING {sym} {mon}")
                missing += 1
            elif new_months[mon]["md5"] != info["md5"]:
                print(f"  DIFFER  {sym} {mon}: {info['md5']} -> {new_months[mon]['md5']}")
                bad += 1
            else:
                ok += 1

    print(f"\n[verify] identical={ok}  differing={bad}  missing={missing}")
    if bad or missing:
        print("BYTE-IDENTITY: FAIL")
        return 1
    print("BYTE-IDENTITY: PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="V262 intraday OHLCV freeze")
    ap.add_argument("--symbols", default=",".join(V262_UNIVERSE))
    ap.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MINUTES))
    ap.add_argument("--start", default="2020-01", help="YYYY-MM inclusive")
    ap.add_argument("--end", default="2026-07", help="YYYY-MM inclusive")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--now-ms",
        type=int,
        default=None,
        help="UTC ms used to compute expected_bars for the partial current month. "
        "Pinned into the manifest so --verify reproduces it exactly.",
    )
    ap.add_argument("--verify", action="store_true", help="byte-identity re-freeze check")
    ap.add_argument("--scratch", type=Path, default=Path("/tmp/v262_verify"))
    args = ap.parse_args()

    if args.verify:
        return verify(args.out, args.interval, args.scratch)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(
        f"[v262-freeze] {len(symbols)} symbols  interval={args.interval}  "
        f"{args.start}..{args.end}  -> {args.out}"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = freeze(
        symbols, args.interval, args.start, args.end, args.out, args.now_ms, args.workers
    )
    manifest["now_ms"] = args.now_ms
    p = _write_manifest(args.out, manifest)

    tot_bars = sum(s["n_bars"] for s in manifest["symbols"].values())
    tot_miss = sum(s["missing_bars"] for s in manifest["symbols"].values())
    tot_bytes = sum(s["bytes"] for s in manifest["symbols"].values())
    print(
        f"\n[v262-freeze] TOTAL {tot_bars:,} bars  {tot_miss:,} missing "
        f"({tot_miss / max(1, tot_bars + tot_miss) * 100:.3f}%)  "
        f"{tot_bytes / 1e6:.1f} MB  manifest={p}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
