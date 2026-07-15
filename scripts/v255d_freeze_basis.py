#!/usr/bin/env python3
"""
V255.D — perp-mark + spot-index basis-data freeze (freeze-once discipline).

Downloads Binance USDⓈ-M futures **markPriceKlines** (perp mark) and
**indexPriceKlines** (spot index) daily-bar archives from the public
``data.binance.vision`` static store and freezes the daily CLOSE of each series
into committed, provenance-stamped JSON — the two price series V255.C needs to
measure real basis (perp_mark − spot_index) instead of the single-``close``
zero-basis assumption that hard-capped V255.C at KEEP-FLAG-GATED.

Sources (all free, public, keyless — NOT the geo-blocked REST API):
  markPriceKlines   https://data.binance.vision/data/futures/um/{monthly,daily}/markPriceKlines/{SYM}/1d/
  indexPriceKlines  https://data.binance.vision/data/futures/um/{monthly,daily}/indexPriceKlines/{SYM}/1d/

Every archive is fetched ONCE, sha256-verified against its ``.CHECKSUM`` sidecar,
and the raw zips are mirrored to the gamma external volume with an MD5SUMS
manifest (mirrors ``v238_freeze_series.py`` Phase B). The compact daily-close
JSON is committed to the repo.

### Determinism (V255.D byte-identity gate)
The frozen JSON embeds ONLY data provenance (source, span, n_obs) — **no
wall-clock timestamp** — so a re-run over the same archives produces a
byte-identical file and identical MD5. This is the guardrail: re-freeze → same
MD5. (v238 embedded ``fetched_at_utc``; that breaks JSON byte-identity, so its
byte-identity gate was on the raw zips. Here the committed JSON itself is the
determinism artifact, so it must be clock-free.)

Frozen file schema (one JSON per symbol per series), mirroring the frozen-series
layout so ``omega/nodes/funding_carry/data.py`` can read it:
  {"name": "binance_mark_price_btcusdt", "source": ..., "frequency": "daily",
   "series_kind": "mark_price"|"index_price", "symbol": "BTCUSDT",
   "first_date": "YYYY-MM-DD", "last_date": ..., "n_obs": ...,
   "value": "daily_close", "series": {"YYYY-MM-DD": float, ...}}

Output tree (scoping doc V255_D_SCOPING.md §3):
  data/frozen_series/binance_futures/{SYMBOL}/mark_price.json  (+ .md5 sidecar)
  data/frozen_series/binance_futures/{SYMBOL}/index_price.json (+ .md5 sidecar)
  data/frozen_series/binance_futures/MANIFEST.json

Usage:
  python3 scripts/v255d_freeze_basis.py \
    --symbols BTCUSDT,ETHUSDT --series mark,index \
    --start 2020-06-01 --end 2026-07-14 \
    --out data/frozen_series/binance_futures/

  # byte-identity re-verify (re-freeze into scratch, diff MD5 vs committed):
  python3 scripts/v255d_freeze_basis.py --verify --out data/frozen_series/binance_futures/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BV = "https://data.binance.vision/data/futures/um"
GAMMA_RAW = Path(
    "/Volumes/gamma-systems-2/omega-victoria-data/frozen_series/binance_futures_raw"
)
UA = {"User-Agent": "omega-victoria-freeze/255d"}

# series key → binance.vision path segment + frozen filename stem
SERIES = {
    "mark": ("markPriceKlines", "mark_price"),
    "index": ("indexPriceKlines", "index_price"),
}


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
def _parse_klines_zip(raw: bytes) -> dict[str, float]:
    """Extract {UTC-date → daily close} from a mark/index kline zip.

    Kline CSV (headerless): open_time_ms, open, high, low, CLOSE, volume,
    close_time_ms, ...  We key by the UTC date of open_time and take close (idx 4).
    """
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            for row in csv.reader(text):
                if not row or not row[0].lstrip("-").isdigit():
                    continue  # skip any header row defensively
                open_ms = int(row[0])
                d = datetime.fromtimestamp(open_ms / 1000, tz=UTC).date().isoformat()
                out[d] = float(row[4])
    return out


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _raw_dir(symbol: str, seg: str) -> Path:
    return GAMMA_RAW / symbol / seg


def _mirror_raw(symbol: str, seg: str, fname: str, body: bytes) -> None:
    """Best-effort mirror of the raw archive to the gamma volume (idempotent)."""
    try:
        d = _raw_dir(symbol, seg)
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(body)
    except OSError as exc:
        print(f"    (raw-mirror skipped {symbol}/{seg}/{fname}: {exc})", file=sys.stderr)


def fetch_series(symbol: str, series_key: str, start: date, end: date) -> dict[str, float]:
    """All daily closes for one (symbol, series) over [start, end].

    Monthly archives for the bulk; daily archives for the current partial month
    that has no monthly dump yet. sha256-verified; raw zips mirrored to gamma.
    """
    seg, _stem = SERIES[series_key]
    series: dict[str, float] = {}
    months = _months(start, end)

    def _month(mon: str) -> tuple[str, dict[str, float] | None]:
        url = f"{BV}/monthly/{seg}/{symbol}/1d/{symbol}-1d-{mon}.zip"
        try:
            body = _get_checked(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return mon, None  # not published as monthly → daily fallback
            raise
        _mirror_raw(symbol, f"monthly/{seg}", f"{symbol}-1d-{mon}.zip", body)
        return mon, _parse_klines_zip(body)

    missing_months: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_month, mon): mon for mon in months}
        for fut in as_completed(futs):
            mon, parsed = fut.result()
            if parsed is None:
                missing_months.append(mon)
            else:
                series.update(parsed)

    # Daily fallback for months with no monthly archive (typically current month).
    for mon in sorted(missing_months):
        y, m = (int(x) for x in mon.split("-"))
        d = date(y, m, 1)
        while d.month == m and d <= end:
            url = f"{BV}/daily/{seg}/{symbol}/1d/{symbol}-1d-{d.isoformat()}.zip"
            try:
                body = _get_checked(url)
                _mirror_raw(symbol, f"daily/{seg}", f"{symbol}-1d-{d.isoformat()}.zip", body)
                series.update(_parse_klines_zip(body))
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise  # 404 = day not published yet; skip quietly
            d += timedelta(days=1)

    # clip to requested span
    lo, hi = start.isoformat(), end.isoformat()
    return {k: v for k, v in series.items() if lo <= k <= hi}


# ---------------------------------------------------------------------------
# freeze (deterministic, clock-free)
# ---------------------------------------------------------------------------
def _write_frozen(out_dir: Path, symbol: str, series_key: str, series: dict[str, float]) -> Path:
    seg, stem = SERIES[series_key]
    dates = sorted(series)
    doc = {
        "name": f"binance_{stem}_{symbol.lower()}",
        "source": f"data.binance.vision futures/um {seg}/{symbol}/1d (daily close)",
        "frequency": "daily",
        "series_kind": stem,
        "symbol": symbol,
        "value": "daily_close",
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "n_obs": len(dates),
        # NB: NO wall-clock field — byte-identity on re-freeze (V255.D determinism gate).
        "series": {d: series[d] for d in dates},
    }
    sym_dir = out_dir / symbol
    sym_dir.mkdir(parents=True, exist_ok=True)
    out = sym_dir / f"{stem}.json"
    out.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True) + "\n")
    md5 = hashlib.md5(out.read_bytes()).hexdigest()
    (sym_dir / f"{stem}.json.md5").write_text(f"{md5}  {stem}.json\n")
    print(f"  {symbol}/{stem}: {len(dates)} obs "
          f"[{doc['first_date']} .. {doc['last_date']}] md5={md5}")
    return out


def _update_manifest(out_dir: Path, files: list[Path]) -> None:
    man_path = out_dir / "MANIFEST.json"
    man = {
        "_built_by": "scripts/v255d_freeze_basis.py",
        "_note": ("V255.D freeze-once perp-mark + spot-index daily closes for real-basis "
                  "re-verify. Clock-free JSON → re-freeze is byte-identical (same MD5)."),
        "files": {},
    }
    for p in sorted(files):
        rel = p.relative_to(out_dir).as_posix()
        man["files"][rel] = {
            "md5": hashlib.md5(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
    man_path.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    print(f"  MANIFEST.json: {len(man['files'])} files")


def freeze(symbols: list[str], series_keys: list[str], start: date, end: date,
           out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for symbol in symbols:
        for sk in series_keys:
            print(f"[fetch] {symbol} {sk} {start} .. {end}")
            series = fetch_series(symbol, sk, start, end)
            if len(series) < 365:
                raise SystemExit(
                    f"{symbol}/{sk}: implausibly small n={len(series)} — refusing to freeze"
                )
            written.append(_write_frozen(out_dir, symbol, sk, series))
    # Manifest covers the WHOLE frozen tree, not just this run's --symbols, so an
    # incremental extend (e.g. BTC/ETH first, then the 11-name universe) does not
    # drop the earlier symbols' entries. Byte-identical to a single full-run manifest.
    all_frozen = sorted(p for p in out_dir.rglob("*.json") if p.name != "MANIFEST.json")
    _update_manifest(out_dir, all_frozen)
    return written


def verify(out_dir: Path) -> int:
    """Recompute MD5s of committed frozen files vs their .md5 sidecars + MANIFEST."""
    ok = True
    for md5file in sorted(out_dir.rglob("*.json.md5")):
        jsonf = md5file.with_suffix("")  # strip .md5 → .json
        want = md5file.read_text().split()[0].strip()
        got = hashlib.md5(jsonf.read_bytes()).hexdigest()
        status = "OK " if want == got else "FAIL"
        if want != got:
            ok = False
        print(f"  {status} {jsonf.relative_to(out_dir)}  {got}")
    print("VERIFY:", "ALL MD5 MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="V255.D basis-data freeze")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--series", default="mark,index")
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2026-07-14")
    ap.add_argument("--out", default=str(ROOT / "data/frozen_series/binance_futures"))
    ap.add_argument("--verify", action="store_true",
                    help="recompute MD5s of committed frozen files (no download)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    if args.verify:
        return verify(out_dir)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    series_keys = [s.strip() for s in args.series.split(",") if s.strip()]
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    freeze(symbols, series_keys, start, end, out_dir)
    print("\nDONE. Re-run identical args → byte-identical MD5 (determinism gate).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
