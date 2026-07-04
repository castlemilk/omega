#!/usr/bin/env python3
"""
V238 — freeze-gap validator (REFLECTION_V237 §6.3 / observability queue #20).

Preflight for frozen-series runs: for every walk-forward window in
`data/walk_forward_manifest.json`, verify each frozen series in
`data/frozen_series/` covers the window's date range, and verify every frozen
file still matches its MANIFEST.json md5 (freeze-once integrity).

Statuses per (window, series):
  FULL     series spans the whole window
  PARTIAL  series starts/ends inside the window (e.g. DVOL pre-2021-03)
  ABSENT   no frozen file, or window entirely outside coverage

ABSENT/PARTIAL are honest states (the SeriesProvider raises → signal NaN →
skipped); this report exists so nobody reads "signal contributed nothing" as
"signal had data and said neutral". FAIL modes (--strict / exit 1) are only:
md5 mismatch, unreadable file, or empty series — i.e. a corrupted freeze.
Fix the FREEZE, never patch the replay (V238 pre-registration).

Usage:
    python3 scripts/check_frozen_series_coverage.py            # report
    python3 scripts/check_frozen_series_coverage.py --strict   # exit 1 on integrity FAIL
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "frozen_series"
MANIFEST = SERIES_DIR / "MANIFEST.json"
WF_MANIFEST = ROOT / "data" / "walk_forward_manifest.json"

# Series the V238 wiring actually consumes (per-symbol OI is probed generically).
WIRED = [
    "fng",
    "fred_vixcls",
    "fred_dtwexbgs",
    "fred_dgs10",
    "fred_dgs2",
    "stablecoin_total_usd",
    "dvol_btc",
    "dvol_eth",
]


def series_range(path: Path) -> tuple[date, date, int] | None:
    doc = json.loads(path.read_text())
    if not doc.get("first_date") or not doc.get("last_date"):
        return None
    return (
        date.fromisoformat(doc["first_date"]),
        date.fromisoformat(doc["last_date"]),
        int(doc.get("n_obs") or 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit 1 on integrity failure")
    args = ap.parse_args()

    integrity_fail = False

    # ── freeze integrity: md5 vs MANIFEST.json ───────────────────────────
    if not MANIFEST.exists():
        print("frozen_series/MANIFEST.json missing — no freeze to validate")
        return 1 if args.strict else 0
    man = json.loads(MANIFEST.read_text())
    files = man.get("files", {})
    n_ok = 0
    for fname, meta in sorted(files.items()):
        p = SERIES_DIR / fname
        if not p.exists():
            print(f"INTEGRITY FAIL: {fname} in MANIFEST but missing on disk")
            integrity_fail = True
            continue
        md5 = hashlib.md5(p.read_bytes()).hexdigest()
        if md5 != meta.get("md5"):
            print(f"INTEGRITY FAIL: {fname} md5 {md5} != manifest {meta.get('md5')}")
            integrity_fail = True
        else:
            n_ok += 1
    unmanifested = sorted(
        p.name for p in SERIES_DIR.glob("*.json")
        if p.name != "MANIFEST.json" and p.name not in files
    )
    for name in unmanifested:
        print(f"INTEGRITY WARN: {name} on disk but not in MANIFEST.json")
    print(f"integrity: {n_ok}/{len(files)} files md5-verified")

    # ── coverage per walk-forward window ─────────────────────────────────
    wf = json.loads(WF_MANIFEST.read_text())
    windows = wf.get("windows", [])

    # every wired series + every binance per-symbol series present on disk
    names = list(WIRED) + sorted(
        p.stem for p in SERIES_DIR.glob("binance_*.json")
    )
    ranges: dict[str, tuple[date, date, int] | None] = {}
    for n in names:
        p = SERIES_DIR / f"{n}.json"
        if not p.exists():
            ranges[n] = None
            continue
        try:
            ranges[n] = series_range(p)
            if ranges[n] is None or ranges[n][2] == 0:
                print(f"INTEGRITY FAIL: {n} frozen but empty")
                integrity_fail = True
        except Exception as exc:
            print(f"INTEGRITY FAIL: {n} unreadable ({exc})")
            ranges[n] = None
            integrity_fail = True

    counts = {"FULL": 0, "PARTIAL": 0, "ABSENT": 0}
    gaps: list[str] = []
    for w in windows:
        w_start = date.fromisoformat(w["date_range"][0])
        w_end = date.fromisoformat(w["date_range"][1])
        row: dict[str, str] = {}
        for n in names:
            r = ranges.get(n)
            if r is None or r[1] < w_start or r[0] > w_end:
                row[n] = "ABSENT"
            elif r[0] <= w_start and r[1] >= w_end:
                row[n] = "FULL"
            else:
                row[n] = "PARTIAL"
            counts[row[n]] += 1
        not_full = {n: s for n, s in row.items() if s != "FULL"}
        if not_full:
            gaps.append(f"  {w['id']} ({w['regime']}): " + ", ".join(
                f"{n}={s}" for n, s in sorted(not_full.items())
            ))

    print(f"\ncoverage over {len(windows)} windows × {len(names)} series: "
          f"FULL={counts['FULL']} PARTIAL={counts['PARTIAL']} ABSENT={counts['ABSENT']}")
    if gaps:
        print("windows with non-FULL series (honest NaN → signal skipped):")
        print("\n".join(gaps))
    else:
        print("all series FULL over all windows")

    if integrity_fail:
        print("\nVERDICT: INTEGRITY FAIL — fix the freeze, never patch the replay")
        return 1 if args.strict else 0
    print("\nVERDICT: freeze integrity OK; gaps above are declared-honest coverage limits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
