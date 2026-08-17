#!/usr/bin/env python3
"""V269 Phase B — forward L2 depth-snapshot collector.

Polls Binance's public ``/fapi/v1/depth?limit=100`` for the 13 V255.C ledger
symbols on a fixed cadence and lands one file per symbol per UTC day.

This is the ONLY source of true L2 ladder data available at $0 — the historical
``bookTicker`` archive is depth-1 and cannot be walked (V269 §2.4). It therefore
accrues **forward only, one day per day**: the same calendar constraint that
produced V268's STOP verdict. Nothing here back-fills history.

ISOLATION (V269 §6): stdlib only, imports no ``omega`` module, reads no file the
live-paper strategy daemon writes, and runs under launchd label
``com.omega.depth_collector`` — distinct from ``com.omega.live_paper``.

Durability: snapshots append to an uncompressed ``.ndjson`` spool (the append IS
the checkpoint). At UTC-day rollover the spool is finalized into a deterministic
``{YYYY-MM-DD}.json.gz`` (sorted, ``mtime=0``, provenance from RETAINED rows).
A launchd restart resumes by appending to the current day's spool and finalizing
any stale spool it finds.

Never places an order. Read-only public market data endpoint.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(REPO, "data", "frozen_series", "binance_depth_forward")
SPOOL_ROOT = os.path.join(REPO, "data", ".v269_depth_spool")
ENDPOINT = "https://fapi.binance.com/fapi/v1/depth"

# The 13 V255.C ledger symbols, with V253's MATIC->POL **forward-only** remap.
#
# Verified 2026-08-17: /fapi/v1/depth?symbol=MATICUSDT returns HTTP 200 with an
# EMPTY book and no T/E timestamp — the contract is delisted. POLUSDT returns a
# full 100-level ladder. Forward collection therefore uses POLUSDT.
#
# The historical side (v269_fetch_bookticker.py) keeps MATICUSDT, because that is
# the key the 2023-05..2024-04 archive actually carries and POLUSDT has ZERO
# bookTicker months (V269 §2.2). The two tickers do not overlap in either source,
# so the MATIC/POL lane has no continuous depth history — the same data-era gap
# V255.D-EXT recorded. Flagged as an R4 partial, not papered over.
SYMBOLS = [
    "ADAUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT",
    "LINKUSDT", "POLUSDT", "NEARUSDT", "SOLUSDT", "SUIUSDT", "XRPUSDT",
]

DEPTH_LIMIT = 100          # request weight 5 per call
CADENCE_SEC = 300          # 5 min -> 13 syms * 5 weight = 65/cycle vs 2400/min cap
MIN_FREE_BYTES = 2 * 1024**3

_STOP = False


def _on_signal(signum, _frame) -> None:
    global _STOP
    _STOP = True
    print(f"[{_utcnow().isoformat()}] signal {signum} — finishing cycle then exiting",
          flush=True)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def free_bytes() -> int:
    st = os.statvfs(REPO)
    return st.f_bavail * st.f_frsize


# ---------------------------------------------------------------- fetch


def fetch_depth(symbol: str, retries: int = 5) -> dict | None:
    """GET one L2 snapshot. Exponential backoff on 429/418/5xx. None on give-up."""
    url = f"{ENDPOINT}?symbol={symbol}&limit={DEPTH_LIMIT}"
    delay = 2.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omega-v269/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # 429 = rate limited, 418 = banned for ignoring 429. Respect Retry-After.
            if e.code in (418, 429):
                wait = float(e.headers.get("Retry-After") or delay)
                print(f"  {symbol}: HTTP {e.code}, backing off {wait:.0f}s", flush=True)
                time.sleep(wait)
                delay = min(delay * 2, 120.0)
                continue
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            print(f"  {symbol}: HTTP {e.code} — skip", flush=True)
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            if attempt == retries - 1:
                print(f"  {symbol}: {type(e).__name__} — skip", flush=True)
                return None
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return None


# ---------------------------------------------------------------- spool / finalize


def spool_path(symbol: str, day: str) -> str:
    return os.path.join(SPOOL_ROOT, symbol, f"{day}.ndjson")


def out_path(symbol: str, day: str) -> str:
    return os.path.join(OUT_ROOT, symbol, f"{day}.json.gz")


def append_snapshot(symbol: str, day: str, snap: dict) -> None:
    """Checkpoint-on-write: one fsync'd NDJSON line per snapshot."""
    p = spool_path(symbol, day)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    line = json.dumps(snap, sort_keys=True, separators=(",", ":"))
    with open(p, "a") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _assert_symbol_matches_partition(symbol: str, path: str) -> None:
    if symbol not in os.path.normpath(path).split(os.sep):
        raise RuntimeError(f"G-P: symbol {symbol!r} absent from partition {path!r}")


def finalize(symbol: str, day: str) -> str | None:
    """Spool -> deterministic gzip. Idempotent; removes the spool on success."""
    sp = spool_path(symbol, day)
    if not os.path.exists(sp):
        return None
    rows: list[dict] = []
    seen: set[int] = set()
    with open(sp) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue  # torn final line from a hard kill — drop, do not guess
            if r.get("t") in seen:
                continue
            seen.add(r["t"])
            rows.append(r)
    if not rows:
        os.remove(sp)
        return None

    rows.sort(key=lambda r: r["t"])
    # G-P: strictly monotonic, no cross-day spill.
    prev = -1
    for r in rows:
        if r["t"] <= prev:
            raise RuntimeError(f"G-P: non-monotonic snapshot {r['t']} in {sp}")
        prev = r["t"]
        d = dt.datetime.fromtimestamp(r["t"] / 1000.0, dt.timezone.utc).strftime("%Y-%m-%d")
        if d != day:
            raise RuntimeError(f"G-P: cross-day spill {d} != {day} in {sp}")

    path = out_path(symbol, day)
    _assert_symbol_matches_partition(symbol, path)
    payload = {
        "dataset": "binance_futures_um_depth_l2_forward",
        "symbol": symbol,
        "day": day,
        "depth_limit": DEPTH_LIMIT,
        "cadence_sec": CADENCE_SEC,
        "schema": {"t": "snapshot transaction_time ms (UTC)",
                   "u": "lastUpdateId",
                   "b": "bids [[price, qty], ...] best-first",
                   "a": "asks [[price, qty], ...] best-first"},
        "provenance": {
            "source": ENDPOINT,
            "retained_snapshots": len(rows),
            "expected_snapshots_full_day": 86400 // CADENCE_SEC,
            "coverage_note": (
                "FORWARD-ONLY ACCRUAL: true L2 begins at collector activation and "
                "accrues one day per day. It does NOT back-fill the V255.C ledger "
                "(2020-01-31..2026-05-14). See V269 §2.4 and V268's calendar verdict."
            ),
        },
        "rows": rows,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    if free_bytes() < len(blob) * 1.2 + MIN_FREE_BYTES:
        print(f"  G-S: refusing to finalize {symbol} {day} — low disk", flush=True)
        return None

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
            gz.write(blob)
    os.replace(tmp, path)
    os.remove(sp)
    print(f"  finalized {path} ({len(rows)} snapshots, {os.path.getsize(path)} B)",
          flush=True)
    return path


def finalize_stale(today: str) -> None:
    """On startup / rollover, finalize every spool that is not today's."""
    if not os.path.isdir(SPOOL_ROOT):
        return
    for symbol in sorted(os.listdir(SPOOL_ROOT)):
        d = os.path.join(SPOOL_ROOT, symbol)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".ndjson"):
                continue
            day = fn[:-len(".ndjson")]
            if day != today:
                finalize(symbol, day)


# ---------------------------------------------------------------- loop


def cycle(day: str) -> int:
    ok = 0
    for symbol in SYMBOLS:
        if _STOP:
            break
        d = fetch_depth(symbol)
        if not d or "bids" not in d or "asks" not in d:
            continue
        ts = int(d.get("T") or d.get("E") or 0)
        if ts <= 0:
            continue
        snap = {"t": ts, "u": d.get("lastUpdateId"),
                "b": d["bids"], "a": d["asks"]}
        snap_day = dt.datetime.fromtimestamp(ts / 1000.0, dt.timezone.utc).strftime("%Y-%m-%d")
        append_snapshot(symbol, snap_day, snap)
        ok += 1
    print(f"[{_utcnow().isoformat()}] cycle day={day} ok={ok}/{len(SYMBOLS)} "
          f"free={free_bytes()/1024**3:.1f}GiB", flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one cycle then exit")
    ap.add_argument("--finalize-now", action="store_true",
                    help="finalize all spools including today's, then exit")
    ap.add_argument("--cycles", type=int, default=0, help="stop after N cycles (0=forever)")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    os.makedirs(SPOOL_ROOT, exist_ok=True)
    today = _utcnow().strftime("%Y-%m-%d")

    if args.finalize_now:
        for symbol in sorted(os.listdir(SPOOL_ROOT)):
            for fn in sorted(os.listdir(os.path.join(SPOOL_ROOT, symbol))):
                if fn.endswith(".ndjson"):
                    finalize(symbol, fn[:-len(".ndjson")])
        return 0

    finalize_stale(today)
    print(f"[{_utcnow().isoformat()}] depth collector up — {len(SYMBOLS)} symbols, "
          f"limit={DEPTH_LIMIT}, cadence={CADENCE_SEC}s", flush=True)

    n = 0
    while not _STOP:
        now = _utcnow()
        day = now.strftime("%Y-%m-%d")
        if day != today:  # UTC rollover
            print(f"[{now.isoformat()}] UTC rollover {today} -> {day}", flush=True)
            finalize_stale(day)
            today = day
        cycle(day)
        n += 1
        if args.once or (args.cycles and n >= args.cycles):
            break
        # Sleep to the next cadence boundary, in short hops so SIGTERM lands fast.
        target = time.time() + CADENCE_SEC - (time.time() % CADENCE_SEC)
        while not _STOP and time.time() < target:
            time.sleep(min(2.0, target - time.time()))

    print(f"[{_utcnow().isoformat()}] exiting after {n} cycle(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
