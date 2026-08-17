#!/usr/bin/env python3
"""V269 Phase A QC report — DATA QUALITY ONLY.

This is NOT V267's impact scorer and NOT an alpha result. It reports what landed
and how complete it is, so V270 can decide under its own pre-registration whether
the artefact is fit to score. Per V269 §5 G-C, every spread figure printed here is
accompanied by the coverage caveat.

Usage: python3 scripts/v269_qc_report.py [--json data/v269_qc.json]
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import statistics

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "data", "frozen_series", "binance_bookticker")
LEDGER = os.path.join(REPO, "data", "v269_ledger", "v255c_trades.csv")
PLAN = os.path.join(REPO, "data", "v269_needed_days.json")

# V267 G2: the measured per-trade edge dies at this much extra round-trip slippage.
V267_SLIPPAGE_BUDGET_BPS = 1.6475


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(REPO, "data", "v269_qc.json"))
    args = ap.parse_args()

    plan = json.load(open(PLAN))["plan"] if os.path.exists(PLAN) else {}
    planned_days = {s: set(v) for s, v in plan.items()}

    per_symbol: dict[str, dict] = {}
    total_bytes = total_min = total_ticks = 0
    all_p50: list[float] = []

    for sym_dir in sorted(glob.glob(os.path.join(ROOT, "*"))):
        sym = os.path.basename(sym_dir)
        months, days, p50s, halves = [], set(), [], []
        sym_bytes = sym_min = sym_ticks = 0
        for p in sorted(glob.glob(os.path.join(sym_dir, "*.json.gz"))):
            with gzip.open(p) as fh:
                d = json.load(fh)
            prov = d["provenance"]
            months.append(d["month"])
            days.update(prov["days_retained"])
            sym_bytes += os.path.getsize(p)
            sym_min += prov["retained_minutes"]
            sym_ticks += prov["retained_ticks"]
            for r in d["rows"]:
                p50s.append(r["sp_bps_p50"])
        if not p50s:
            continue
        med = statistics.median(p50s)
        per_symbol[sym] = {
            "months": len(months),
            "days_landed": len(days),
            "days_planned": len(planned_days.get(sym, ())),
            "missing_days": sorted(planned_days.get(sym, set()) - days),
            "minutes": sym_min,
            "ticks": sym_ticks,
            "bytes": sym_bytes,
            "median_full_spread_bps": round(med, 4),
            "median_half_spread_bps": round(med / 2.0, 4),
            "half_spread_vs_v267_budget": round(med / 2.0 / V267_SLIPPAGE_BUDGET_BPS, 2),
        }
        all_p50 += p50s
        total_bytes += sym_bytes
        total_min += sym_min
        total_ticks += sym_ticks

    # Coverage restated from the ledger itself, not from memory.
    rows = list(csv.DictReader(open(LEDGER)))
    inwin = [r for r in rows
             if "2023-05" <= r["entry_date"][:7] <= "2024-04"
             and "2023-05" <= r["exit_date"][:7] <= "2024-04"]
    hv_total = sum(1 for r in rows if r["entry_regime"] == "high_vol")
    hv_inwin = sum(1 for r in inwin if r["entry_regime"] == "high_vol")

    print("=" * 72)
    print("V269 PHASE A — QC REPORT (data quality only; NOT an alpha result)")
    print("=" * 72)
    print(f"\nsymbols landed      : {len(per_symbol)}")
    print(f"symbol-months       : {sum(v['months'] for v in per_symbol.values())} / 84")
    print(f"symbol-days landed  : {sum(v['days_landed'] for v in per_symbol.values())} / 1135")
    print(f"minutes retained    : {total_min:,}")
    print(f"ticks aggregated    : {total_ticks:,}")
    print(f"retained artefact   : {total_bytes/1048576:.2f} MiB")

    print(f"\n{'symbol':<10} {'mo':>3} {'days':>9} {'minutes':>9} "
          f"{'ticks':>13} {'half-sp bps':>12} {'x budget':>9}")
    for s, v in sorted(per_symbol.items()):
        print(f"{s:<10} {v['months']:>3} {v['days_landed']:>4}/{v['days_planned']:<4} "
              f"{v['minutes']:>9,} {v['ticks']:>13,} "
              f"{v['median_half_spread_bps']:>12.3f} "
              f"{v['half_spread_vs_v267_budget']:>9.1f}")

    med_all = statistics.median(all_p50) if all_p50 else 0.0
    print(f"\npooled median full spread : {med_all:.4f} bps")
    print(f"pooled median half spread : {med_all/2:.4f} bps")
    print(f"V267 G2 slippage budget   : {V267_SLIPPAGE_BUDGET_BPS:.4f} bps")

    print("\n" + "-" * 72)
    print("G-C COVERAGE CAVEAT (binding on every number above)")
    print("-" * 72)
    print(f"  joinable trades      : {len(inwin)}/{len(rows)} = "
          f"{100*len(inwin)/len(rows):.1f}% of the V255.C ledger")
    print(f"  high_vol coverage    : {hv_inwin}/{hv_total} = 0.0%  <-- the regime "
          f"V255.B measured strongest is ABSENT")
    print( "  depth                : depth-1 (top of book). NO L2 ladder. A "
           "Sharpe(2k->2M)\n                         curve is NOT derivable from this "
           "artefact (V269 §2.4).")
    print( "  MATIC/POL            : historical=MATICUSDT only, forward=POLUSDT only, "
           "no overlap.")
    print( "\nThese spreads are a QUOTED-SPREAD measurement, not an impact model and "
           "not\na verdict. Scoring is V270's job under its own pre-registration.")

    missing = {s: v["missing_days"] for s, v in per_symbol.items() if v["missing_days"]}
    if missing:
        print(f"\nR4 PARTIAL — planned days absent from the archive:")
        for s, ds in sorted(missing.items()):
            print(f"  {s}: {len(ds)} day(s) {ds[:8]}")
    else:
        print("\nR4 PARTIAL — none: every planned symbol-day was present.")

    with open(args.json, "w") as fh:
        json.dump({
            "per_symbol": per_symbol,
            "totals": {"bytes": total_bytes, "minutes": total_min, "ticks": total_ticks},
            "pooled_median_full_spread_bps": round(med_all, 6),
            "pooled_median_half_spread_bps": round(med_all / 2, 6),
            "v267_slippage_budget_bps": V267_SLIPPAGE_BUDGET_BPS,
            "coverage": {
                "joinable_trades": len(inwin), "ledger_trades": len(rows),
                "joinable_pct": round(100 * len(inwin) / len(rows), 2),
                "high_vol_in_window": hv_inwin, "high_vol_total": hv_total,
                "depth": "depth-1 top-of-book; no L2 ladder",
            },
        }, fh, indent=2, sort_keys=True)
    print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
