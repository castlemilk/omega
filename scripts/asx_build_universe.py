#!/usr/bin/env python3
"""Rebuild the ASX panel from the upstream point-in-time universe.

Replaces the frozen 69-name survivor universe with the real one. Three stages, each
resumable — a 429 or a Ctrl-C costs the current request, never the work already done.

Why this shape:

* **Membership comes from the per-name series, not from dense snapshots.** Every
  observation in `GetStockData` is dated, so a name's own series states the dates it
  was reported. Quarterly `GetMarketByDate` calls are used only to ENUMERATE codes
  (including delisted ones), which is ~30 requests instead of ~1,900.

* **The universe is taken with `include_zero_short_positions`.** Upstream's own proto
  warns that the default filters out names with no short interest that day, and
  "excluding exactly the names with no short interest biases any study that sorts on
  short interest" — which is this study.

* **`ordinary_only`.** ETFs, debt lines and warrants are not the cross-section; a
  warrant at 132% short is a unit artifact, not a signal.

Known hole, measured, not worked around: roughly half the delisted tail has no price
history upstream (castlemilk/shorted.com.au#576). Stage 3 records which codes have
none, so the survivorship hole is a number in the manifest rather than a silent drop.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.shorted.com.au/shorts.v1alpha1"

# Study window floor: XJT (the only total-return benchmark) begins 2019-04-29
# upstream and cannot be backfilled (#573), so nothing earlier is measurable.
START = "2019-04-01"
UA = "omega-asx-research/0.1"

# Anonymous callers get 30/min and 500/month (docs/rate-limiting.md §2.1), which is
# far below the ~3,300 requests a full rebuild needs. A bearer token moves the caller
# into its account's tier. The value is read from the environment and passed straight
# to the transport — never logged, never written to any artifact.
TOKEN_ENV = "OMEGA_SHORTED_API_KEY"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "frozen_series" / "asx" / "v3"

PAGE = 200
MAX_RETRIES = 7


def api(svc: str, body: dict) -> tuple[int, dict]:
    """POST with 429 backoff. Honours Retry-After; caps a single sleep at 30s."""
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            f"{BASE}.{svc}", data=json.dumps(body).encode(), method="POST"
        )
        for k, v in (
            ("Content-Type", "application/json"),
            ("Connect-Protocol-Version", "1"),
            ("User-Agent", UA),
        ):
            req.add_header(k, v)
        tok = os.environ.get(TOKEN_ENV)
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = e.headers.get("Retry-After")
                time.sleep(min(float(wait) if wait else 2.0 ** attempt, 30.0))
                continue
            return e.code, {}
        except Exception:
            time.sleep(1.5)
    # Retries exhausted. Returning 429 here is load-bearing: stage 3 must not record
    # a throttled code as "no price history", which would fabricate a survivorship
    # hole out of a rate limit and land it in the manifest as if it were data.
    return 429, {}


def stage1_enumerate(dates: list[str]) -> dict:
    """Union of every code present on the sampled dates, with first/last seen."""
    d = OUT / "universe"
    d.mkdir(parents=True, exist_ok=True)
    codes: dict[str, dict] = {}
    for date in dates:
        f = d / f"{date}.json"
        if f.is_file():
            rows = json.loads(f.read_text())
        else:
            rows, off = [], 0
            while True:
                st, body = api(
                    "MarketService/GetMarketByDate",
                    {
                        "date": date,
                        "limit": PAGE,
                        "offset": off,
                        "includeZeroShortPositions": True,
                        "ordinaryOnly": True,
                    },
                )
                page = body.get("stocks") or []
                if st != 200 or not page:
                    break
                rows.extend(page)
                off += PAGE
                if off >= int(body.get("totalCount") or 0):
                    break
                time.sleep(0.35)
            if not rows:
                print(f"  [1] {date}: EMPTY", flush=True)
                continue
            f.write_text(json.dumps(rows))
            time.sleep(0.35)
        for r in rows:
            c = r.get("productCode")
            if not c:
                continue
            e = codes.setdefault(c, {"name": r.get("name"), "first": date, "last": date})
            e["first"] = min(e["first"], date)
            e["last"] = max(e["last"], date)
        print(f"  [1] {date}: {len(rows)} rows, union={len(codes)}", flush=True)
    return codes


def stage2_shorts(codes: list[str]) -> dict:
    """Per-code short-interest history. Dated, so it defines PIT membership."""
    d = OUT / "shorts"
    d.mkdir(parents=True, exist_ok=True)
    stat = {}
    for i, c in enumerate(codes):
        f = d / f"{c}.csv"
        if f.is_file():
            stat[c] = "cached"
            continue
        st, body = api(
            "ShortedStocksService/GetStockData",
            {"productCode": c, "period": "max"},
        )
        pts = [
            p for p in (body.get("points") or [])
            if p.get("timestamp") and p.get("shortPosition") is not None
        ]
        if st == 429:
            stat[c] = "throttled"
            continue
        if st != 200 or not pts:
            stat[c] = "none"
            continue
        pts.sort(key=lambda p: p["timestamp"])
        f.write_text(
            "date,short_pct\n"
            + "".join(f"{p['timestamp'][:10]},{p['shortPosition']}\n" for p in pts)
        )
        stat[c] = len(pts)
        if i % 25 == 0:
            print(f"  [2] {i}/{len(codes)} {c}: {len(pts)} obs", flush=True)
        time.sleep(0.45)
    return stat


def stage3_prices(codes: list[str]) -> dict:
    """Adjusted closes + volume. Missing codes are RECORDED (#576), not skipped."""
    d = OUT / "prices"
    d.mkdir(parents=True, exist_ok=True)
    stat = {}
    for i, c in enumerate(codes):
        f = d / f"{c}.csv"
        if f.is_file():
            stat[c] = "cached"
            continue
        st, body = api(
            "ShortedStocksService/GetStockPrices",
            {"productCode": c, "period": "MAX", "maxPoints": 0},
        )
        pts = [
            p for p in (body.get("points") or [])
            if p.get("date") and p.get("adjustedClose")
        ]
        if st == 429:
            stat[c] = "throttled"      # NOT a survivorship hole — a rate limit
            continue
        if st != 200 or not pts:
            stat[c] = "no_price_history"
            continue
        pts.sort(key=lambda p: p["date"])
        f.write_text(
            "date,adjusted_close,close,volume\n"
            + "".join(
                f"{p['date'][:10]},{p['adjustedClose']},{p.get('close','')},{p.get('volume',0)}\n"
                for p in pts
            )
        )
        stat[c] = len(pts)
        if i % 25 == 0:
            print(f"  [3] {i}/{len(codes)} {c}: {len(pts)} sessions", flush=True)
        time.sleep(0.45)
    return stat


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # GetAvailableDates caps `limit` at 1000 (2000 -> HTTP 400) and returns the most
    # recent page, so walk backwards with `before` until the window is covered.
    avail: set[str] = set()
    before = ""
    while True:
        req = {"limit": 1000}
        if before:
            req["before"] = before
        st, body = api("MarketService/GetAvailableDates", req)
        page = sorted(str(x)[:10] for x in (body.get("dates") or []))
        if st != 200 or not page:
            break
        avail |= set(page)
        if page[0] <= START:
            break
        before = page[0]          # strictly older next time
        time.sleep(0.3)
    avail = sorted(d for d in avail if d >= START)
    if not avail:
        print("no available dates from upstream", file=sys.stderr)
        return 1
    # Quarterly sampling is enough to ENUMERATE; membership comes from the series.
    sample = sorted({avail[i] for i in range(0, len(avail), max(1, len(avail) // 32))})
    sample = sorted(set(sample) | {avail[0], avail[-1]})
    print(f"stage 1: enumerating over {len(sample)} snapshots ({avail[0]} .. {avail[-1]})", flush=True)
    codes = stage1_enumerate(sample)
    (OUT / "codes.json").write_text(json.dumps(codes, indent=1, sort_keys=True))
    names = sorted(codes)
    print(f"stage 1 done: {len(names)} distinct codes", flush=True)

    print("stage 2: short histories", flush=True)
    s2 = stage2_shorts(names)
    print("stage 3: prices", flush=True)
    s3 = stage3_prices(names)

    nopx = sorted(c for c, v in s3.items() if v == "no_price_history")
    throttled = sorted(
        set(c for c, v in s3.items() if v == "throttled")
        | set(c for c, v in s2.items() if v == "throttled")
    )
    (OUT / "MANIFEST.json").write_text(
        json.dumps(
            {
                "built_on": "2026-09-01",
                "source": "GetMarketByDate (ordinary_only, include_zero_short_positions) "
                          "+ GetStockData + GetStockPrices",
                "snapshots": sample,
                "codes": len(names),
                "with_shorts": sum(1 for v in s2.values() if v not in ("none",)),
                "with_prices": len(names) - len(nopx),
                "no_price_history": nopx,
                "throttled": throttled,
                "complete": not throttled,
                "auth": "bearer" if os.environ.get(TOKEN_ENV) else "anonymous",
                "survivorship_note": (
                    f"{len(nopx)}/{len(names)} codes have no upstream price history "
                    "(castlemilk/shorted.com.au#576). They are IN the universe and "
                    "cannot be priced, so any run must report them rather than drop them."
                ),
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        f"done: {len(names)} codes, {len(names)-len(nopx)-len(throttled)} priced, "
        f"{len(nopx)} genuinely unpriceable, {len(throttled)} THROTTLED",
        flush=True,
    )
    if throttled:
        print(
            f"  INCOMPLETE: {len(throttled)} codes hit the rate limit. Re-run to resume; "
            f"set ${TOKEN_ENV} to raise the ceiling above the anonymous 30/min.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
