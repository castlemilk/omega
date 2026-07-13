#!/usr/bin/env python3
"""
V251 — live-vs-backtest reconciliation harness (the Phase-2 go/no-go gate).

Comparison-only. Touches NO strategy code. Data-only.

Design (LIVE_PAPER_SCOPE.md §6, V250.md → V251 entry)
----------------------------------------------------
The standing-baseline eval consumes exactly two inputs from a walk-forward
snapshot: (a) per-symbol OHLCV arrays and (b) the ``_macro`` block. The V240
selective baseline runs ``frozen_series_enabled=OFF``, so the macro *series*
feeds (VIX/DXY/yield/GDELT/funding-series) are NOT consumed — only the snapshot's
``_macro`` block + OHLCV drive decisions. Per §6 the reconciliation **holds macro
(incl. funding) at its frozen value** so the only live-vs-frozen variable is the
OHLCV feed — precisely the thing V250's live pollers replace.

Two arms, ONE eval code path (``run_training.py --backtest-snapshot``):

  * **Arm A (backtest):** the committed frozen snapshot.
  * **Arm B (live-replay):** a snapshot rebuilt with OHLCV fetched **live** from
    Binance klines (every fetch through ``omega.live_paper.feeds.assert_live_source``
    → exercises the frozen-path guard, F5), macro copied verbatim from the frozen
    snapshot (§6).

Because the eval is hermetic (byte-identical output from byte-identical input —
the property V214–V221 established), if Arm B's OHLCV equals Arm A's OHLCV bar for
bar, the eval output is identical → per-regime PnL Δ = $0 < 2·SE trivially. So the
reconciliation reduces to an **OHLCV input diff across all 32 windows** (this
script, Layer 1), plus an **empirical output-equivalence** run on the sentinels
(driven separately, Layer 2) that closes the input→output chain on this code+config.

This script = Layer 1: build the live snapshots, diff OHLCV vs frozen, classify
each window, and write a machine-readable reconciliation report. It is fully
deterministic given a fixed set of live bars (past bars are immutable on Binance);
the N=2 feed-reproducibility check (F6) re-fetches and asserts byte-stability.

Usage:
  export OMEGA_AUDIT_OUTPUT_DIR=/Volumes/gamma-systems-2/omega-victoria-data
  python3 scripts/v251_reconcile.py build     # fetch+diff all 32 windows
  python3 scripts/v251_reconcile.py report    # aggregate + per-regime table
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Reuse the V250 live-feed guard so the frozen-path contract (F5) is genuinely
# exercised on every OHLCV fetch this harness makes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omega.live_paper.feeds import assert_live_source, verify_cache, write_cache  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "walk_forward_manifest.json"
AUDIT = Path(__import__("os").environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(ROOT / "data")))
OUT = AUDIT / "v251"
LIVE_SNAP_DIR = OUT / "live_snapshots"

_UA = {"User-Agent": "omega-victoria-v251-reconcile/1.0"}
# Relative-diff tolerance below which two bars are called identical. Binance
# serves the same immutable 1d klines from both api.binance.com (live) and the
# data.binance.vision archives (frozen); we expect exact equality (0.0).
IDENTICAL_TOL = 1e-12


def _klines(symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list[list]:
    url = "https://api.binance.com/api/v3/klines?" + urllib.parse.urlencode(
        {"symbol": symbol, "interval": "1d", "startTime": start_ms, "endTime": end_ms, "limit": limit}
    )
    assert_live_source(url)  # F5: refuse any frozen/file path — live http only
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _live_ohlcv_by_date(symbol: str, ts_seconds: list[int]) -> dict[str, tuple]:
    """Live OHLCV keyed by UTC iso-date, covering the frozen window's span."""
    start_ms = ts_seconds[0] * 1000
    end_ms = ts_seconds[-1] * 1000
    rows = _klines(symbol, start_ms, end_ms)
    out: dict[str, tuple] = {}
    for r in rows:
        d = datetime.fromtimestamp(r[0] / 1000, tz=UTC).date().isoformat()
        # open, high, low, close, volume
        out[d] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
    return out


def _frozen_ohlcv_by_date(sym_block: dict, ts_seconds: list[int]) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    for i, t in enumerate(ts_seconds):
        d = datetime.fromtimestamp(t, tz=UTC).date().isoformat()
        out[d] = (
            sym_block["open"][i],
            sym_block["high"][i],
            sym_block["low"][i],
            sym_block["close"][i],
            sym_block["volume"][i],
        )
    return out


def _rel(a: float, b: float) -> float:
    if b == 0.0:
        return 0.0 if a == 0.0 else abs(a - b)
    return abs(a - b) / abs(b)


def _diff_symbol(frozen: dict, sym: str, ts: list[int], live: dict[str, tuple]) -> dict:
    froz = _frozen_ohlcv_by_date(frozen[sym], ts)
    common = sorted(set(froz) & set(live))
    froz_only = sorted(set(froz) - set(live))   # frozen has a bar live doesn't (e.g. post-delisting)
    live_only = sorted(set(live) - set(froz))
    max_rel = 0.0
    worst = None
    for d in common:
        for field_i, (a, b) in enumerate(zip(froz[d], live[d], strict=False)):
            rr = _rel(a, b)
            if rr > max_rel:
                max_rel = rr
                worst = (d, ("open", "high", "low", "close", "volume")[field_i], a, b)
    return {
        "symbol": sym,
        "frozen_bars": len(froz),
        "live_bars": len(live),
        "common_bars": len(common),
        "frozen_only_bars": froz_only,   # bars the live feed CANNOT supply (delisting/gaps)
        "live_only_bars": live_only,
        "max_rel_diff": max_rel,
        "worst": worst,
        "identical": max_rel <= IDENTICAL_TOL and not froz_only and not live_only,
    }


def build_live_snapshot(frozen: dict, ts_map: dict[str, list[int]]) -> tuple[dict, list[dict]]:
    """Rebuild the snapshot with LIVE OHLCV; macro held frozen (§6). Returns (snap, per-symbol diffs)."""
    live_snap = {k: v for k, v in frozen.items() if k.startswith("_")}  # metadata + _macro verbatim (§6)
    diffs = []
    for sym in frozen["_symbols"]:
        ts = ts_map[sym]
        live = _live_ohlcv_by_date(sym, ts)
        diffs.append(_diff_symbol(frozen, sym, ts, live))
        # Rebuild arrays in the frozen bar order (by frozen timestamps). Missing
        # live bars → carry the frozen bar (so the delisting gap is recorded in the
        # diff, not silently zeroed); identical bars → live == frozen anyway.
        block = dict(frozen[sym])
        o, h, low_, c, v = [], [], [], [], []
        for t in ts:
            d = datetime.fromtimestamp(t, tz=UTC).date().isoformat()
            if d in live:
                lo, lh, ll, lc, lv = live[d]
            else:
                i = ts.index(t)
                lo, lh, ll, lc, lv = (
                    frozen[sym]["open"][i], frozen[sym]["high"][i], frozen[sym]["low"][i],
                    frozen[sym]["close"][i], frozen[sym]["volume"][i],
                )
            o.append(lo); h.append(lh); low_.append(ll); c.append(lc); v.append(lv)
        block["open"], block["high"], block["low"], block["close"], block["volume"] = o, h, low_, c, v
        live_snap[sym] = block
    return live_snap, diffs


def load_windows() -> list[dict]:
    return json.loads(MANIFEST.read_text())["windows"]


def cmd_build(refetch_check: bool = True) -> None:
    LIVE_SNAP_DIR.mkdir(parents=True, exist_ok=True)
    windows = load_windows()
    report = {"version": "v251", "identical_tol": IDENTICAL_TOL, "windows": []}
    print(f"[v251] building live snapshots for {len(windows)} windows → {LIVE_SNAP_DIR}")
    for w in windows:
        wid, regime, path = w["id"], w["regime"], ROOT / w["path"]
        frozen = json.loads(path.read_text())
        ts_map = {s: frozen[s]["timestamps"] for s in frozen["_symbols"]}
        t0 = time.perf_counter()
        live_snap, diffs = build_live_snapshot(frozen, ts_map)
        # F6 feed-reproducibility (N=2): re-fetch one symbol, assert byte-stable.
        repro_ok = True
        if refetch_check:
            s0 = frozen["_symbols"][0]
            a = _live_ohlcv_by_date(s0, ts_map[s0])
            b = _live_ohlcv_by_date(s0, ts_map[s0])
            repro_ok = a == b
        out_path = LIVE_SNAP_DIR / f"{wid}.json"
        write_cache(out_path, live_snap)  # F7 atomic + checksummed
        cache_ok = verify_cache(out_path)
        window_identical = all(d["identical"] for d in diffs)
        worst_sym = max(diffs, key=lambda d: d["max_rel_diff"])
        report["windows"].append({
            "window": wid,
            "regime": regime,
            "date_range": frozen.get("_date_range"),
            "symbols": frozen["_symbols"],
            "identical": window_identical,
            "worst_symbol": worst_sym["symbol"],
            "worst_max_rel_diff": worst_sym["max_rel_diff"],
            "symbols_with_frozen_only_bars": [d["symbol"] for d in diffs if d["frozen_only_bars"]],
            "diffs": diffs,
            "feed_reproducible_n2": repro_ok,
            "cache_atomic_checksum_ok": cache_ok,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        })
        flag = "IDENTICAL" if window_identical else "DIVERGENT"
        extra = "" if window_identical else f" worst={worst_sym['symbol']}:{worst_sym['max_rel_diff']:.2e}"
        print(f"  {wid} [{regime:6s}] {flag}{extra} repro={repro_ok} cache={cache_ok} ({report['windows'][-1]['elapsed_s']}s)")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reconcile_report.json").write_text(json.dumps(report, indent=1))
    print(f"[v251] report → {OUT / 'reconcile_report.json'}")


def cmd_report() -> None:
    rep = json.loads((OUT / "reconcile_report.json").read_text())
    rows = rep["windows"]
    n = len(rows)
    n_identical = sum(1 for r in rows if r["identical"])
    print(f"=== V251 OHLCV input reconciliation — {n} windows ===")
    print(f"IDENTICAL (live OHLCV == frozen, bit-exact, full coverage): {n_identical}/{n}")
    print(f"F5 frozen-path guard: exercised on every fetch (assert_live_source)")
    print(f"F6 feed-reproducibility N=2: {sum(1 for r in rows if r['feed_reproducible_n2'])}/{n} byte-stable")
    print(f"F7 cache atomic+checksum: {sum(1 for r in rows if r['cache_atomic_checksum_ok'])}/{n} verified")
    print()
    div = [r for r in rows if not r["identical"]]
    if div:
        print(f"--- {len(div)} DIVERGENT window(s) ---")
        for r in div:
            fob = r["symbols_with_frozen_only_bars"]
            print(f"  {r['window']} [{r['regime']}] worst={r['worst_symbol']} "
                  f"rel={r['worst_max_rel_diff']:.2e} frozen_only_bars_in={fob}")
    else:
        print("--- ZERO divergent windows: live feed reproduces frozen OHLCV exactly ---")
    print()
    # per-regime coverage
    from collections import defaultdict
    byreg = defaultdict(lambda: [0, 0])
    for r in rows:
        byreg[r["regime"]][0] += 1
        byreg[r["regime"]][1] += 1 if r["identical"] else 0
    print("per-regime IDENTICAL coverage:")
    for reg in ("crisis", "trend", "recent"):
        tot, ident = byreg[reg]
        print(f"  {reg:8s}: {ident}/{tot} identical")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        cmd_build()
    elif cmd == "report":
        cmd_report()
    else:
        print(__doc__)
        sys.exit(2)
