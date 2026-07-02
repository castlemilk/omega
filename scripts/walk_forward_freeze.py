#!/usr/bin/env python3
"""
V235 — walk-forward window builder.

Freezes ~26 rolling 60-day OHLCV windows across 2020-01→2026-06 via the V215
freeze recipe (`freeze_snapshot.fetch_ohlcv_historical`, ccxt/Binance daily,
13-symbol universe), assigns each window a mechanical ex-post regime label, and
writes a manifest. This is the instrument the DEEP_REVIEW_2026-06_FABLE ranked
#1: it turns every gate from an N=1 window into a regime-tagged distribution.

Design notes (pre-registered in training_log/V235.md):
- WINDOW_DAYS=90, STRIDE_DAYS=90 → 26 contiguous non-overlapping windows
  spanning the whole 2020→2026 range at walk-forward cost ~50 grid cells.
  90 days (not 60) because ReplayIngestionNode provides series_len - 30 honest
  steps and then WRAPS (replaying data across a fictitious price seam — the
  V235 wrap forensic); 91 bars → ~60 honest cycles per window. The grid caps
  --cycles at min_bars - 31 so the replay never wraps.
- `_macro` block is COPIED from the committed snap_crisis_2024aug.json rather
  than fetched live: every prior snapshot's _macro is live-at-build-time scalars
  (never historically backfilled — see V231_SOURCING_MANIFEST.md), so copying a
  committed block is semantically identical, byte-reproducible, and avoids the
  freeze_snapshot macro_cache.db mutation trap (victoria_snapshot_build_trap).
- Regime labels are MECHANICAL (no discretion): computed from the equal-weight
  basket of available symbols' closes over the window.
      crisis : max_dd >= 0.30 OR basket_ret <= -0.15
               (drawdown-first: a window containing crash+recovery ends flat/up
               but is a crisis experience for anything trading through it —
               the 2020q1 anchor ends +37% with a 61% max drawdown)
      trend  : basket_ret >= +0.20 (and not crisis)
      recent : otherwise (normal/chop bucket; named for gate continuity)
  plus an independent high_vol tag when annualized basket vol >= 0.90.
  Sanity anchors: 2020q1 must label crisis, 2024q1 must label trend.

Usage:
    python3 scripts/walk_forward_freeze.py                # build all missing
    python3 scripts/walk_forward_freeze.py --manifest-only  # relabel/rewrite manifest from existing files
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_snapshot import ALL_SYMBOLS, fetch_ohlcv_historical  # noqa: E402

OUT_DIR = ROOT / "data" / "snapshots" / "walk_forward"
MANIFEST = ROOT / "data" / "walk_forward_manifest.json"
MACRO_SOURCE = ROOT / "data" / "snapshots" / "snap_crisis_2024aug.json"

WINDOW_DAYS = 90
STRIDE_DAYS = 90
# ReplayIngestionNode truncates the WHOLE window to the shortest symbol series
# and requires >= window+1 = 31 bars (providers/replay.py:110); the shortest
# series also sets the honest (pre-wrap) step count. A symbol that lists or
# delists mid-window (DOT 2020-08, ARB 2023-03, MATIC->POL 2024-09) would
# otherwise poison the entire window — drop any symbol below 80% of the
# window's max bars (floor 32) and record it in the manifest.
MIN_SYMBOL_BARS = 32
MIN_COVERAGE_FRAC = 0.80
SPAN_START = date(2020, 1, 1)
SPAN_END = date(2026, 6, 30)

VOL_HIGH = 0.90  # annualized basket vol tag threshold


def window_starts() -> list[date]:
    starts = []
    d = SPAN_START
    while d + timedelta(days=WINDOW_DAYS) <= SPAN_END:
        starts.append(d)
        d = d + timedelta(days=STRIDE_DAYS)
    return starts


def basket_metrics(snap: dict) -> dict:
    """Equal-weight basket metrics over available symbols (mechanical, fsum-fenced)."""
    series = []
    for sym in snap.get("_symbols", []):
        closes = snap.get(sym, {}).get("close") or []
        if len(closes) >= 30:  # require a usable series
            series.append(closes)
    if not series:
        return {"basket_ret": 0.0, "ann_vol": 0.0, "max_dd": 0.0, "n_series": 0}

    n_bars = min(len(c) for c in series)
    # Per-symbol normalized paths -> equal-weight basket path.
    basket = []
    for i in range(n_bars):
        basket.append(math.fsum(c[i] / c[0] for c in series) / len(series))

    basket_ret = basket[-1] / basket[0] - 1.0
    rets = [basket[i] / basket[i - 1] - 1.0 for i in range(1, len(basket))]
    mean_r = math.fsum(rets) / len(rets)
    var = math.fsum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    ann_vol = math.sqrt(var) * math.sqrt(365.0)
    peak, max_dd = basket[0], 0.0
    for v in basket:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    return {
        "basket_ret": round(basket_ret, 6),
        "ann_vol": round(ann_vol, 6),
        "max_dd": round(max_dd, 6),
        "n_series": len(series),
    }


def regime_label(m: dict) -> str:
    if m["max_dd"] >= 0.30 or m["basket_ret"] <= -0.15:
        return "crisis"
    if m["basket_ret"] >= 0.20:
        return "trend"
    return "recent"


def build_window(start: date, macro: dict, force: bool = False) -> Path | None:
    end = start + timedelta(days=WINDOW_DAYS)
    wid = f"snap_wf_{start.isoformat().replace('-', '')}"
    out = OUT_DIR / f"{wid}.json"
    if out.exists() and not force:
        print(f"  {wid}: exists, skipping fetch")
        return out

    ohlcv = fetch_ohlcv_historical(ALL_SYMBOLS, start.isoformat(), end.isoformat())
    if not ohlcv:
        print(f"  {wid}: NO DATA — skipped")
        return None
    max_bars = max(len(d.get("close", [])) for d in ohlcv.values())
    floor_bars = max(MIN_SYMBOL_BARS, int(MIN_COVERAGE_FRAC * max_bars))
    dropped = {s: len(d.get("close", [])) for s, d in ohlcv.items()
               if len(d.get("close", [])) < floor_bars}
    for s in dropped:
        del ohlcv[s]
    if not ohlcv:
        print(f"  {wid}: all symbols below {MIN_SYMBOL_BARS} bars — skipped")
        return None
    snap = {
        "_dropped_symbols": dropped,
        "_snapshot_id": wid,
        "_created_at": int(time.time()),
        "_date_range": [start.isoformat(), end.isoformat()],
        "_symbols": list(ohlcv.keys()),
        "_lookback": WINDOW_DAYS,
        **ohlcv,
        "_macro": macro,
    }
    out.write_text(json.dumps(snap, default=str))
    print(f"  {wid}: {len(ohlcv)}/13 symbols → {out.name} ({out.stat().st_size/1024:.0f} KB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-only", action="store_true",
                    help="skip fetching; (re)build the manifest from existing window files")
    ap.add_argument("--force", action="store_true", help="re-fetch existing windows")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    macro = json.loads(MACRO_SOURCE.read_text()).get("_macro", {})

    paths: list[Path] = []
    if args.manifest_only:
        paths = sorted(OUT_DIR.glob("snap_wf_*.json"))
    else:
        for start in window_starts():
            p = build_window(start, macro, force=args.force)
            if p is not None:
                paths.append(p)

    windows = []
    counts: dict[str, int] = {}
    for p in paths:
        snap = json.loads(p.read_text())
        m = basket_metrics(snap)
        label = regime_label(m)
        counts[label] = counts.get(label, 0) + 1
        bars = {s: len(snap.get(s, {}).get("close", [])) for s in snap.get("_symbols", [])}
        windows.append({
            "id": snap["_snapshot_id"],
            "path": str(p.relative_to(ROOT)),
            "date_range": snap["_date_range"],
            "regime": label,
            "high_vol": m["ann_vol"] >= VOL_HIGH,
            "metrics": m,
            "symbols": len(bars),
            "min_bars": min(bars.values()) if bars else 0,
            "max_bars": max(bars.values()) if bars else 0,
            "dropped_symbols": snap.get("_dropped_symbols", {}),
        })

    manifest = {
        "_built_by": "scripts/walk_forward_freeze.py (V235)",
        "_recipe": "V215 freeze (ccxt/Binance 1d) + mechanical ex-post regime labels; "
                   "_macro copied from snap_crisis_2024aug.json (see script docstring)",
        "window_days": WINDOW_DAYS,
        "stride_days": STRIDE_DAYS,
        "span": [SPAN_START.isoformat(), SPAN_END.isoformat()],
        "label_rules": {
            "crisis": "max_dd >= 0.30 OR basket_ret <= -0.15 (drawdown-first)",
            "trend": "basket_ret >= +0.20 AND not crisis",
            "recent": "otherwise",
            "high_vol_tag": f"ann_vol >= {VOL_HIGH}",
        },
        "regime_counts": counts,
        "n_windows": len(windows),
        "windows": windows,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nManifest → {MANIFEST}  ({len(windows)} windows, regimes: {counts})")

    # Sanity anchors against the known hand-labeled windows.
    for anchor, want in (
        ("snap_crisis_2020q1", "crisis"),
        ("snap_crisis_2022h1", "crisis"),
        ("snap_crisis_2024aug", "crisis"),
        ("snap_trending_2023q4", "trend"),
        ("snap_trending_2024q1", "trend"),
        # V235 FINDING: the standing "recent" GATE window mechanically labels
        # crisis (basket_ret -34.7%, max_dd 40.7% — it contains the April 2026
        # crash). "recent" was always a temporal name, not a regime; the
        # +$4,901 standing number was earned on a crisis-shaped window.
        ("snap_20260414", "crisis"),
    ):
        f = ROOT / "data" / "snapshots" / f"{anchor}.json"
        if f.exists():
            m = basket_metrics(json.loads(f.read_text()))
            got = regime_label(m)
            flag = "OK" if got == want else "MISMATCH"
            print(f"  anchor {anchor}: labeled {got} (want {want}) [{flag}]  {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
