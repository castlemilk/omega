#!/usr/bin/env python3
"""
V240 Track B — per-signal forensics aggregator.

Joins each solo-signal arm from the V240 signal grid
(v240sig_<window>_<config>_<gate>_determinism/summary.json, produced by
scripts/v240_signal_grid.sh; configs series_fng/series_vix/series_dxy/
series_yc/series_whale) against the V238 grid's `main` cells
(v238wf_<window>_main_<gate>_determinism/summary.json — byte-identical to
V235; NOT re-run), and reports per-signal per-regime Δ distributions.

Question answered: which of the 5 wired feeds carries V238 series-ON's
trend −$2,693 / recent −$1,161 floor breach, and which (if any) delivers the
crisis +$3,148 benefit without the tax. Reference read: a signal is a
SHIP CANDIDATE if its solo arm has no regime mean-Δ < −$500 and pooled
mean-Δ > −$300 (the V238/V239 acceptance shape); it is a DRAGGER if trend or
recent mean-Δ < −$500.

Exit codes: 0 = ok, 5 = any solo cell's determinism verdict FAIL.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

POOLED_MEAN_BAR = -300.0
REGIME_REGRESS_BAR = -500.0

SOLO_CONFIGS = ("series_fng", "series_vix", "series_dxy", "series_yc", "series_whale")
SIGNAL_NAME = {
    "series_fng": "fear_greed", "series_vix": "vix", "series_dxy": "dxy",
    "series_yc": "yield_curve", "series_whale": "whale_flow",
}
BASELINE = "main"  # from the V238 grid


def pctl(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if not s:
        return float("nan")
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
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


def read_cell(root: Path, prefix: str, wid: str, cfg: str, regime: str):
    sp = root / f"{prefix}_{wid}_{cfg}_{regime}_determinism" / "summary.json"
    if not sp.exists():
        return None
    s = json.loads(sp.read_text())
    pnls = [float(x) for x in s.get("pnls", [])]
    trades = [int(x) for x in s.get("trades", [])]
    return {
        "pnl": pnls[0] if pnls else None,
        "trades": trades[0] if trades else None,
        "n_replicates": s.get("n"),
        "determinism": s.get("verdict"),
        "pnl_spread": s.get("pnl_spread"),
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

    rows = []
    det_fail = []
    missing = []
    base_pnl: dict[str, float] = {}   # window -> main pnl
    for w in manifest["windows"]:
        cell = read_cell(root, "v238wf", w["id"], BASELINE, w["regime"])
        if cell is None or cell["pnl"] is None:
            missing.append(f"{w['id']}/main(v238)")
            continue
        base_pnl[w["id"]] = cell["pnl"]

    for w in manifest["windows"]:
        for cfg in SOLO_CONFIGS:
            cell = read_cell(root, "v240sig", w["id"], cfg, w["regime"])
            if cell is None:
                missing.append(f"{w['id']}/{cfg}")
                continue
            if cell["determinism"] != "PASS":
                det_fail.append(f"{w['id']}/{cfg} spread=${cell['pnl_spread']}")
            rows.append({
                "window": w["id"], "regime": w["regime"],
                "high_vol": w.get("high_vol", False), "config": cfg, **cell,
            })

    regimes = sorted({w["regime"] for w in manifest["windows"]})
    per_signal = {}
    for cfg in SOLO_CONFIGS:
        cells = [r for r in rows if r["config"] == cfg and r["pnl"] is not None
                 and r["window"] in base_pnl]
        deltas_by_regime: dict[str, list[float]] = {}
        delta_per_window = {}
        for c in cells:
            d = round(c["pnl"] - base_pnl[c["window"]], 2)
            deltas_by_regime.setdefault(c["regime"], []).append(d)
            delta_per_window[c["window"]] = d
        pooled_vals = [d for v in deltas_by_regime.values() for d in v]
        regime_means = {reg: dist_stats(v)["mean"] for reg, v in deltas_by_regime.items()}
        pooled = dist_stats(pooled_vals)
        if pooled.get("n", 0) >= 10:
            dragger = any(regime_means.get(r, 0) < REGIME_REGRESS_BAR
                          for r in ("trend", "recent"))
            ship_shape = (pooled["mean"] > POOLED_MEAN_BAR
                          and all(m > REGIME_REGRESS_BAR for m in regime_means.values()))
            read = ("SHIP CANDIDATE" if ship_shape
                    else ("DRAGGER (trend/recent)" if dragger else "MIXED"))
        else:
            read = "INSUFFICIENT CELLS"
        per_signal[SIGNAL_NAME[cfg]] = {
            "config": cfg,
            "n": pooled.get("n", 0),
            "pooled_delta": pooled,
            "regime_delta": {reg: dist_stats(v) for reg, v in deltas_by_regime.items()},
            "regime_means": regime_means,
            "delta_per_window": delta_per_window,
            "read": read,
        }

    out = {
        "version": "v240_signal",
        "baseline": "v238wf main (== V235 standing baseline)",
        "per_signal": per_signal,
        "rows": rows,
        "determinism_failures": det_fail,
        "missing_cells": missing,
        "note": ("solo-signal deltas do not sum to the V238 series-ON delta — "
                 "interactions between feeds are not attributed by this design"),
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = ["# V240 per-signal forensics results (auto-generated)", "",
          "Each of the 5 V238-wired feeds run SOLO (frozen_series_enabled + "
          "frozen_series_signals=<name>) vs the V238 `main` baseline over the "
          "32-window manifest. Question: which feed carries series-ON's "
          "trend −$2,693 / recent −$1,161 floor breach.", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — all reads BLOCKED until bisected/fenced.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    md += ["## Per-signal summary (mean-Δ vs main, $)", "",
           "| signal | n | pooled | " + " | ".join(regimes) + " | read |",
           "|---|---:|---:|" + "---:|" * len(regimes) + "---|"]
    for name, s in per_signal.items():
        cells = " | ".join(f"{s['regime_means'].get(r, float('nan')):,.0f}"
                           if r in s["regime_means"] else "—" for r in regimes)
        md.append(f"| {name} | {s['n']} | {s['pooled_delta'].get('mean', float('nan')):,.0f} "
                  f"| {cells} | {s['read']} |")
    md += ["", "## Per-signal distributions", ""]
    for name, s in per_signal.items():
        md += [f"### {name}", "", "```json",
               json.dumps({"pooled": s["pooled_delta"],
                           "regimes": s["regime_delta"]}, indent=2),
               "```", "",
               "Per-window Δ: " + json.dumps(s["delta_per_window"]), ""]
    md += ["## Interaction caveat", "",
           out["note"], ""]
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"v240_signal_aggregate: {len(rows)} solo cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    for name, s in per_signal.items():
        print(f"  {name}: pooled={s['pooled_delta'].get('mean')} regimes={s['regime_means']} -> {s['read']}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
