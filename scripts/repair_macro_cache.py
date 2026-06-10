#!/usr/bin/env python3
"""
V219 — one-shot repair of data/macro_cache.db with REAL macro values.

The committed macro_cache.db was all-`__failed__`/0.0 for every series (VIX,
DGS2, DGS10, dollar index) because FRED's DEMO_KEY returns HTTP 400 and no
FRED_API_KEY is set — so the entire V207->V217 eval ran with macro signals = 0
(VIX/yields/dollar inert). This script fetches real, current values from Yahoo
Finance (which works from this environment where FRED + Stooq do not) and writes
them into the cache under the FRED series IDs the signals read.

Source map (documented in V219.md):
    VIXCLS   <- ^VIX     (exact: CBOE VIX index)
    DGS10    <- ^TNX     (exact: 10Y Treasury yield, percent-scale)
    DGS2     <- 2YY=F    (close proxy: CME 2Y yield future, percent-scale)
    DTWEXBGS <- DX-Y.NYB (level proxy: ICE DXY; dxy_signal uses returns only)

This is a DELIBERATE, committed baseline change (like freeze_advanced_snapshot.py).
Re-run only to refresh the frozen macro snapshot, then rebuild the manifest:
    python3 scripts/repair_macro_cache.py
    python3 scripts/build_cache_manifest.py

After running, the DB is WAL-checkpointed (TRUNCATE) so the committed .db is
self-contained and its md5 is stable.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Ensure UNFENCED: this tool WANTS the live fetch.
os.environ.pop("OMEGA_FROZEN_CACHE", None)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "macro_cache.db"

# FRED series id -> (Yahoo ticker, exact|proxy note, sane-range check)
# range check guards against a future Yahoo convention change (e.g. ^TNX
# reverting to x10 scale, which would silently invert the 2s10s slope).
_SOURCES: dict[str, dict] = {
    "VIXCLS": {"yahoo": "^VIX", "lo": 5.0, "hi": 120.0, "kind": "exact"},
    "DGS10": {"yahoo": "^TNX", "lo": 0.0, "hi": 25.0, "kind": "exact (%)"},
    "DGS2": {"yahoo": "2YY=F", "lo": 0.0, "hi": 25.0, "kind": "proxy (%, CME 2Y fut)"},
    "DTWEXBGS": {"yahoo": "DX-Y.NYB", "lo": 50.0, "hi": 200.0, "kind": "proxy (ICE DXY)"},
}


def _fetch_yahoo(ticker: str, rng: str = "6mo") -> list[dict]:
    """Return [{date: 'YYYY-MM-DD', value: float}, ...] oldest-first from Yahoo chart API."""
    enc = urllib.parse.quote(ticker, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        d = json.loads(resp.read().decode())
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out: list[dict] = []
    for t, c in zip(ts, closes, strict=False):
        if c is None:
            continue
        date = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")
        out.append({"date": date, "value": round(float(c), 6)})
    # de-dup by date (Yahoo can repeat the last bar), keep last
    by_date = {row["date"]: row["value"] for row in out}
    return [{"date": k, "value": v} for k, v in sorted(by_date.items())]


def main() -> int:
    if not DB_PATH.exists():
        print(f"FATAL: {DB_PATH} does not exist", file=sys.stderr)
        return 1

    fetched: dict[str, list[dict]] = {}
    for series_id, spec in _SOURCES.items():
        try:
            obs = _fetch_yahoo(spec["yahoo"])
        except Exception as exc:
            print(f"FATAL: fetch failed for {series_id} <- {spec['yahoo']}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if not obs:
            print(f"FATAL: no observations for {series_id} <- {spec['yahoo']}", file=sys.stderr)
            return 1
        latest = obs[-1]["value"]
        if not (spec["lo"] <= latest <= spec["hi"]):
            print(f"FATAL: {series_id} latest {latest} outside sane range "
                  f"[{spec['lo']}, {spec['hi']}] — Yahoo convention change? "
                  f"(guards ^TNX x10 regression)", file=sys.stderr)
            return 1
        fetched[series_id] = obs
        print(f"  {series_id:9s} <- {spec['yahoo']:10s} {spec['kind']:24s} "
              f"{len(obs)} obs, latest {obs[-1]['date']}={latest}")

    # Cross-check: 2s10s slope sane (both percent-scale).
    dgs2 = fetched["DGS2"][-1]["value"]
    dgs10 = fetched["DGS10"][-1]["value"]
    print(f"  2s10s slope check: DGS10 {dgs10} - DGS2 {dgs2} = {dgs10 - dgs2:+.3f}")

    now_iso = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # Clear failed sentinels + any stale rows for the repaired series, then insert.
        for series_id, obs in fetched.items():
            conn.execute("DELETE FROM macro_cache WHERE series_id = ?", (series_id,))
            conn.executemany(
                "INSERT INTO macro_cache (series_id, date, value, fetched_at) "
                "VALUES (?, ?, ?, ?)",
                [(series_id, o["date"], o["value"], now_iso) for o in obs],
            )
        conn.commit()
        # Make the committed .db self-contained + md5-stable: fold WAL into main file.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()

    # Report final state.
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT series_id, COUNT(*), MIN(date), MAX(date) FROM macro_cache "
        "WHERE date != '__failed__' GROUP BY series_id"
    ).fetchall()
    conn.close()
    print("\nRepaired macro_cache.db:")
    for r in rows:
        print(f"  {r[0]:9s} {r[1]:3d} rows  {r[2]} .. {r[3]}")
    print("\nOK — now run: python3 scripts/build_cache_manifest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
