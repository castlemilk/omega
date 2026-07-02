#!/usr/bin/env python3
"""
V235 — walk-forward distribution aggregator.

Reads every v235wf_<window>_<config>_<gate>_determinism/summary.json produced by
scripts/walk_forward_grid.sh, joins against data/walk_forward_manifest.json, and
emits per-regime distributions for the standing main and the V229 trend-IC stack
plus the pre-registered V235 decision reads:

  - trend-IC ship gate (feeds V236): mean-Δ_trend > +$500 AND min-Δ_trend > -$200
  - recent reproduction: mean of recent-labeled windows under `main` vs the
    standing single-window +$4,901 (refuted if mean < +$1,000 or p25 < 0)

Exit codes: 0 = ok, 5 = any cell's determinism verdict FAIL (blocks all verdicts).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SHIP_MEAN_BAR = 500.0
SHIP_MIN_BAR = -200.0
RECENT_MEAN_BAR = 1000.0


def pctl(vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]) — no numpy dependency."""
    s = sorted(vals)
    if not s:
        return float("nan")
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def dist_stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": round(math.fsum(vals) / len(vals), 2),
        "p25": round(pctl(vals, 0.25), 2),
        "median": round(pctl(vals, 0.50), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "spread": round(max(vals) - min(vals), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data", help="audit output root (OMEGA_AUDIT_OUTPUT_DIR)")
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    root = Path(args.root)

    rows = []          # one per (window, config)
    det_fail = []
    missing = []
    for w in manifest["windows"]:
        for cfg in ("main", "trendic"):
            sp = root / f"v235wf_{w['id']}_{cfg}_{w['regime']}_determinism" / "summary.json"
            if not sp.exists():
                missing.append(f"{w['id']}/{cfg}")
                continue
            s = json.loads(sp.read_text())
            pnls = [float(x) for x in s.get("pnls", [])]
            trades = [int(x) for x in s.get("trades", [])]
            if s.get("verdict") != "PASS":
                det_fail.append(f"{w['id']}/{cfg} spread=${s.get('pnl_spread')}")
            rows.append({
                "window": w["id"],
                "regime": w["regime"],
                "high_vol": w.get("high_vol", False),
                "config": cfg,
                "pnl": pnls[0] if pnls else None,   # N=1, or replicate-identical when PASS
                "trades": trades[0] if trades else None,
                "n_replicates": s.get("n"),
                "determinism": s.get("verdict"),
                "pnl_spread": s.get("pnl_spread"),
            })

    by = {}
    for r in rows:
        if r["pnl"] is not None:
            by.setdefault((r["regime"], r["config"]), []).append(r)

    regimes = sorted({r["regime"] for r in rows})
    dist = {}
    for reg in regimes:
        dist[reg] = {}
        for cfg in ("main", "trendic"):
            cells = by.get((reg, cfg), [])
            dist[reg][cfg] = dist_stats([c["pnl"] for c in cells])
        # Per-window deltas (trendic - main), paired on window id.
        main_map = {c["window"]: c["pnl"] for c in by.get((reg, "main"), [])}
        ti_map = {c["window"]: c["pnl"] for c in by.get((reg, "trendic"), [])}
        deltas = {wid: round(ti_map[wid] - main_map[wid], 2)
                  for wid in main_map if wid in ti_map}
        dist[reg]["delta"] = dist_stats(list(deltas.values()))
        dist[reg]["delta_per_window"] = deltas

    # --- Pre-registered decision reads -------------------------------------
    verdicts = {}
    td = dist.get("trend", {}).get("delta", {})
    if td.get("n", 0) >= 5:
        ship = td["mean"] > SHIP_MEAN_BAR and td["min"] > SHIP_MIN_BAR
        verdicts["trend_ic_ship"] = {
            "bar": f"mean-D > +${SHIP_MEAN_BAR:.0f} AND min-D > -${abs(SHIP_MIN_BAR):.0f} (N>=5)",
            "measured": {"mean": td.get("mean"), "min": td.get("min"), "n": td.get("n")},
            "verdict": "SHIP" if ship else "DO NOT SHIP",
        }
    else:
        verdicts["trend_ic_ship"] = {"verdict": "INSUFFICIENT WINDOWS", "n": td.get("n", 0)}

    rm = dist.get("recent", {}).get("main", {})
    if rm.get("n", 0) >= 5:
        reproduced = rm["mean"] >= RECENT_MEAN_BAR and rm["p25"] >= 0
        verdicts["recent_reproduction"] = {
            "bar": f"mean >= +${RECENT_MEAN_BAR:.0f} AND p25 >= 0 vs the single-window +$4,901",
            "measured": {"mean": rm.get("mean"), "p25": rm.get("p25"), "n": rm.get("n")},
            "verdict": "REPRODUCES" if reproduced else "DOES NOT REPRODUCE",
        }
    else:
        verdicts["recent_reproduction"] = {"verdict": "INSUFFICIENT WINDOWS", "n": rm.get("n", 0)}

    out = {
        "version": "v235_walkforward",
        "rows": rows,
        "distributions": dist,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    # --- Markdown -----------------------------------------------------------
    md = ["# V235 walk-forward distribution results (auto-generated)", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — all verdicts BLOCKED until bisected/fenced.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    for reg in regimes:
        md += [f"## {reg}", "",
               "| config | n | mean | p25 | median | min | max |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        for cfg in ("main", "trendic", "delta"):
            s = dist[reg].get(cfg, {})
            if s.get("n"):
                md.append(f"| {cfg} | {s['n']} | {s['mean']:,.2f} | {s['p25']:,.2f} | "
                          f"{s['median']:,.2f} | {s['min']:,.2f} | {s['max']:,.2f} |")
        md += ["", "Per-window Δ (trendic − main): " +
               json.dumps(dist[reg].get("delta_per_window", {})), ""]
    md += ["## Pre-registered verdicts", "", "```json",
           json.dumps(verdicts, indent=2), "```", ""]
    md += ["## Per-window detail", "",
           "| window | regime | config | pnl | trades | det | N |",
           "|---|---|---|---:|---:|---|---:|"]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
                  f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |")
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"walk_forward_aggregate: {len(rows)} cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    for k, v in verdicts.items():
        print(f"  {k}: {v.get('verdict')}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
