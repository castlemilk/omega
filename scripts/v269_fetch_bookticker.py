#!/usr/bin/env python3
"""V269 Phase A (reduced) — stream-and-aggregate Binance futures bookTicker.

Downloads one daily ``bookTicker`` archive at a time, aggregates it to per-minute
top-of-book statistics, then DELETES the raw archive. Raw tick data is never
retained, so peak disk stays ~one archive (<300 MB) while ~41 GB flows through.

Reads NOTHING that a running strategy daemon writes. Writes only under
``data/frozen_series/binance_bookticker/``.

Determinism (V269 §5 G-D): rows sorted by minute, ``gzip`` written with
``mtime=0``, provenance computed from RETAINED rows only — never from a
fetched-archive count and never from a wall-clock read (the V262 defect).

Usage:
    python3 scripts/v269_fetch_bookticker.py --plan            # derive + show plan
    python3 scripts/v269_fetch_bookticker.py --symbol BTCUSDT --month 2023-10
    python3 scripts/v269_fetch_bookticker.py --all
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict

BASE = "https://data.binance.vision/data/futures/um/daily/bookTicker"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(REPO, "data", "frozen_series", "binance_bookticker")
TMP_ROOT = os.path.join(REPO, "data", ".v269_tmp")
LEDGER = os.path.join(REPO, "data", "v269_ledger", "v255c_trades.csv")
PLAN_PATH = os.path.join(REPO, "data", "v269_needed_days.json")

# Archive extent established by V269 §2.2 — probed, not assumed.
WINDOW_LO, WINDOW_HI = "2023-05", "2024-04"

# G-S: refuse to write if free bytes fall under retained-estimate + 20% headroom.
MIN_FREE_BYTES = 2 * 1024**3  # absolute floor: 2 GiB
SPREAD_BUCKET = 100.0  # histogram resolution: 1/100 bps


# ---------------------------------------------------------------- plan


def needed_symbol_days(ledger: str) -> dict[str, list[str]]:
    """Symbol -> sorted ISO dates the 154 in-window V255.C trades actually touch."""
    with open(ledger) as fh:
        rows = list(csv.DictReader(fh))
    out: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        e, x = r["entry_date"][:10], r["exit_date"][:10]
        if not (WINDOW_LO <= e[:7] <= WINDOW_HI and WINDOW_LO <= x[:7] <= WINDOW_HI):
            continue
        a, b = dt.date.fromisoformat(e), dt.date.fromisoformat(x)
        d = a
        while d <= b:
            if WINDOW_LO <= d.strftime("%Y-%m") <= WINDOW_HI:
                out[r["symbol"]].add(d.isoformat())
            d += dt.timedelta(days=1)
    return {s: sorted(v) for s, v in sorted(out.items())}


# ---------------------------------------------------------------- aggregation


class MinuteAgg:
    """O(1)-memory-per-minute accumulator. Deterministic: fsum + integer histogram."""

    __slots__ = ("n", "mid", "sp", "bq", "aq", "hist", "sp_min", "sp_max")

    def __init__(self) -> None:
        self.n = 0
        self.mid: list[float] = []
        self.sp: list[float] = []
        self.bq: list[float] = []
        self.aq: list[float] = []
        self.hist: dict[int, int] = defaultdict(int)
        self.sp_min = math.inf
        self.sp_max = -math.inf

    def add(self, mid: float, sp_bps: float, bq: float, aq: float) -> None:
        self.n += 1
        # Keep running sums as compensated lists flushed periodically to bound memory.
        self.mid.append(mid)
        self.sp.append(sp_bps)
        self.bq.append(bq)
        self.aq.append(aq)
        if len(self.mid) > 4096:
            self._flush()
        self.hist[int(sp_bps * SPREAD_BUCKET)] += 1
        if sp_bps < self.sp_min:
            self.sp_min = sp_bps
        if sp_bps > self.sp_max:
            self.sp_max = sp_bps

    def _flush(self) -> None:
        for lst in (self.mid, self.sp, self.bq, self.aq):
            s = math.fsum(lst)
            lst.clear()
            lst.append(s)

    def _mean(self, lst: list[float]) -> float:
        return math.fsum(lst) / self.n if self.n else 0.0

    def p50_bps(self) -> float:
        """Exact median from the integer histogram (no full-sample retention)."""
        if not self.n:
            return 0.0
        target = self.n // 2
        cum = 0
        for k in sorted(self.hist):
            cum += self.hist[k]
            if cum > target:
                return k / SPREAD_BUCKET
        return max(self.hist) / SPREAD_BUCKET

    def row(self, minute: int) -> dict:
        return {
            "t": minute,
            "n": self.n,
            "mid": round(self._mean(self.mid), 8),
            "sp_bps_mean": round(self._mean(self.sp), 6),
            "sp_bps_p50": round(self.p50_bps(), 6),
            "sp_bps_min": round(self.sp_min, 6),
            "sp_bps_max": round(self.sp_max, 6),
            "bid_qty_mean": round(self._mean(self.bq), 8),
            "ask_qty_mean": round(self._mean(self.aq), 8),
        }


def aggregate_zip(path: str) -> tuple[dict[int, MinuteAgg], int, int]:
    """Stream one daily zip -> {minute: MinuteAgg}. Returns (agg, data_rows, bad)."""
    agg: dict[int, MinuteAgg] = {}
    rows = bad = 0
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"expected 1 csv in {path}, got {names}")
        with zf.open(names[0]) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            header = stream.readline().strip().split(",")
            idx = {c: i for i, c in enumerate(header)}
            for c in ("best_bid_price", "best_bid_qty", "best_ask_price",
                      "best_ask_qty", "transaction_time"):
                if c not in idx:
                    raise RuntimeError(f"missing column {c!r} in {path}: {header}")
            ibp, ibq = idx["best_bid_price"], idx["best_bid_qty"]
            iap, iaq = idx["best_ask_price"], idx["best_ask_qty"]
            itt = idx["transaction_time"]
            for line in stream:
                f = line.rstrip("\n").split(",")
                if len(f) < len(header):
                    continue
                rows += 1
                try:
                    bp, ap = float(f[ibp]), float(f[iap])
                    ts = int(f[itt])
                except ValueError:
                    bad += 1
                    continue
                if bp <= 0.0 or ap <= 0.0 or ap < bp:
                    bad += 1
                    continue
                mid = (bp + ap) / 2.0
                sp = (ap - bp) / mid * 10_000.0
                minute = (ts // 1000) // 60 * 60
                a = agg.get(minute)
                if a is None:
                    a = agg[minute] = MinuteAgg()
                a.add(mid, sp, float(f[ibq]), float(f[iaq]))
    return agg, rows, bad


# ---------------------------------------------------------------- io helpers


def free_bytes(path: str) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def assert_storage(need: int) -> None:
    """G-S — abort before any write if free disk lacks need + 20% headroom."""
    free = free_bytes(REPO)
    required = int(need * 1.2) + MIN_FREE_BYTES
    if free < required:
        raise SystemExit(
            f"G-S STORAGE GATE FIRED: free={free/1024**3:.2f} GiB < "
            f"required={required/1024**3:.2f} GiB (need {need/1024**2:.0f} MiB +20% "
            f"+2 GiB floor). Halting per V269 §5."
        )


def download(url: str, dest: str, retries: int = 6) -> int:
    """Fetch with exponential backoff on 429/5xx. Returns bytes written."""
    delay = 2.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-v269/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
                shutil.copyfileobj(r, fh, length=1 << 20)
            return os.path.getsize(dest)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 60.0)
    raise RuntimeError(f"unreachable: {url}")


def _assert_symbol_matches_partition(symbol: str, path: str) -> None:
    """G-P — partition path must encode the symbol it holds."""
    parts = os.path.normpath(path).split(os.sep)
    if symbol not in parts:
        raise RuntimeError(f"G-P: symbol {symbol!r} absent from partition {path!r}")


def write_partition(symbol: str, month: str, rows: list[dict], prov: dict) -> str:
    """Deterministic gzip write: sorted rows, mtime=0, provenance from RETAINED rows."""
    out_dir = os.path.join(OUT_ROOT, symbol)
    path = os.path.join(out_dir, f"{month}.json.gz")
    _assert_symbol_matches_partition(symbol, path)

    rows = sorted(rows, key=lambda r: r["t"])
    # G-P: strictly monotonic minutes, no cross-month spill.
    seen: set[int] = set()
    prev = -1
    for r in rows:
        if r["t"] <= prev:
            raise RuntimeError(f"G-P: non-monotonic minute {r['t']} in {path}")
        if r["t"] in seen:
            raise RuntimeError(f"G-P: duplicate minute {r['t']} in {path}")
        seen.add(r["t"])
        prev = r["t"]
        m = dt.datetime.fromtimestamp(r["t"], dt.timezone.utc).strftime("%Y-%m")
        if m != month:
            raise RuntimeError(f"G-P: cross-month spill {m} != {month} in {path}")

    # Provenance derived from RETAINED rows only.
    payload = {
        "dataset": "binance_futures_um_bookTicker_perminute",
        "symbol": symbol,
        "month": month,
        "schema": ["t", "n", "mid", "sp_bps_mean", "sp_bps_p50", "sp_bps_min",
                   "sp_bps_max", "bid_qty_mean", "ask_qty_mean"],
        "depth": "depth-1 (top-of-book only; NO L2 ladder — see V269 §2.4)",
        "provenance": {
            "source": BASE,
            "retained_minutes": len(rows),
            "retained_ticks": sum(r["n"] for r in rows),
            "days_retained": prov["days"],
            "n_days_retained": len(prov["days"]),
            "source_data_rows": prov["source_rows"],
            "rejected_rows": prov["bad"],
            "coverage_note": (
                "PARTIAL MONTH BY DESIGN: only the symbol-days touched by the 154 "
                "in-window V255.C trades (12.6% of the 1,225-trade ledger; "
                "high_vol regime coverage 0/340). See V269 §2.3 / §5 G-C."
            ),
        },
        "rows": rows,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    os.makedirs(out_dir, exist_ok=True)
    assert_storage(len(blob))
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
            gz.write(blob)
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- driver


def already_landed(symbol: str, month: str, days: list[str]) -> bool:
    """Idempotent resume: skip only if the partition holds exactly this day set."""
    path = os.path.join(OUT_ROOT, symbol, f"{month}.json.gz")
    if not os.path.exists(path):
        return False
    try:
        with gzip.open(path) as fh:
            prov = json.load(fh)["provenance"]
    except (OSError, ValueError, KeyError):
        return False
    return list(prov.get("days_retained", [])) == sorted(days)


def do_symbol_month(symbol: str, month: str, days: list[str], prefetch: int = 3) -> dict:
    """Download days with a bounded lookahead, aggregate in order, delete raw."""
    os.makedirs(TMP_ROOT, exist_ok=True)
    agg: dict[int, MinuteAgg] = {}
    src_rows = bad = xfer = 0
    got: list[str] = []
    missing: list[str] = []

    def fetch(day: str) -> tuple[str, str | None, int]:
        url = f"{BASE}/{symbol}/{symbol}-bookTicker-{day}.zip"
        tmp = os.path.join(TMP_ROOT, f"{symbol}-{day}.zip")
        try:
            assert_storage((prefetch + 1) * 300 * 1024**2)
            return day, tmp, download(url, tmp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return day, None, 0
            raise

    with cf.ThreadPoolExecutor(max_workers=prefetch) as pool:
        pending: dict[str, cf.Future] = {}
        queue = list(days)
        for day in queue[:prefetch]:
            pending[day] = pool.submit(fetch, day)
        nxt = prefetch

        for day in queue:
            _, tmp, n = pending.pop(day).result()
            if nxt < len(queue):  # keep the pipe full
                pending[queue[nxt]] = pool.submit(fetch, queue[nxt])
                nxt += 1
            if tmp is None:
                missing.append(day)
                print(f"    {day}  404 MISSING (R4 partial)", flush=True)
                continue
            try:
                xfer += n
                a, rows, b = aggregate_zip(tmp)
                src_rows += rows
                bad += b
                for minute, m in a.items():
                    if minute in agg:
                        raise RuntimeError(f"G-P: minute {minute} spans two days")
                    agg[minute] = m
                got.append(day)
                print(f"    {day}  {n/1048576:7.1f} MB  {rows:>9,} ticks", flush=True)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    got.sort()
    missing.sort()

    if not got:
        return {"symbol": symbol, "month": month, "skipped": True, "missing": missing}

    rows = [agg[m].row(m) for m in sorted(agg)]
    path = write_partition(symbol, month, rows,
                           {"days": got, "source_rows": src_rows, "bad": bad})

    retained_ticks = sum(r["n"] for r in rows)
    # G-R: aggregation must conserve ticks exactly (stronger than the ±5% bar).
    drift = abs(retained_ticks - (src_rows - bad))
    if drift:
        raise RuntimeError(
            f"G-R FALSIFIER: tick conservation broken for {symbol} {month}: "
            f"retained={retained_ticks} vs src-bad={src_rows - bad} (drift={drift})"
        )
    return {
        "symbol": symbol, "month": month, "path": path,
        "bytes": os.path.getsize(path), "minutes": len(rows),
        "ticks": retained_ticks, "days": got, "missing": missing,
        "rejected": bad, "transferred": xfer, "skipped": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=LEDGER)
    ap.add_argument("--symbol")
    ap.add_argument("--month")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    plan = needed_symbol_days(args.ledger)
    by_sm: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sym, days in plan.items():
        for d in days:
            by_sm[(sym, d[:7])].append(d)

    if args.plan:
        tot = sum(len(v) for v in plan.values())
        print(json.dumps({"symbols": len(plan), "symbol_days": tot,
                          "symbol_months": len(by_sm),
                          "per_symbol": {k: len(v) for k, v in plan.items()}}, indent=2))
        with open(PLAN_PATH, "w") as fh:
            json.dump({"window": [WINDOW_LO, WINDOW_HI], "plan": plan}, fh,
                      indent=2, sort_keys=True)
        print(f"wrote {PLAN_PATH}")
        return 0

    if args.symbol and args.month:
        targets = [((args.symbol, args.month), by_sm[(args.symbol, args.month)])]
    elif args.symbol:
        targets = [(k, v) for k, v in sorted(by_sm.items()) if k[0] == args.symbol]
    elif args.all:
        targets = sorted(by_sm.items())
    else:
        ap.error("need --plan, --symbol, or --all")

    results = []
    for (sym, month), days in targets:
        if not args.force and already_landed(sym, month, days):
            print(f"[{sym} {month}] already landed ({len(days)} day(s)) — skip", flush=True)
            continue
        print(f"[{sym} {month}] {len(days)} day(s)", flush=True)
        results.append(do_symbol_month(sym, month, days))

    done = [r for r in results if not r.get("skipped")]
    print("\n=== SUMMARY ===")
    print(f"partitions written : {len(done)}")
    print(f"symbol-days landed : {sum(len(r['days']) for r in done)}")
    print(f"minutes retained   : {sum(r['minutes'] for r in done):,}")
    print(f"ticks aggregated   : {sum(r['ticks'] for r in done):,}")
    print(f"bytes transferred  : {sum(r['transferred'] for r in done)/1024**3:.2f} GiB")
    print(f"bytes retained     : {sum(r['bytes'] for r in done)/1024**2:.2f} MiB")
    miss = sorted({d for r in results for d in r.get("missing", [])})
    if miss:
        print(f"R4 PARTIAL — missing days ({len(miss)}): {miss[:20]}")
    if os.path.isdir(TMP_ROOT) and not os.listdir(TMP_ROOT):
        os.rmdir(TMP_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
