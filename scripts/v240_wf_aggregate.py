#!/usr/bin/env python3
"""
V240 — selective-universe confirm-grid aggregator.

Joins the V240 grid's `universe_selective` cells
(v240wf_<window>_universe_selective_<gate>_determinism/summary.json, produced
by scripts/v240_wf_grid.sh) against the V239 grid's `universe_legacy` cells
(v239wf_<window>_universe_legacy_<gate>_determinism/summary.json — certified
deterministic and byte-identical to V238 main; NOT re-run), and reads the
pre-registered acceptance bar (training_log/V240.md Track A, same shape as
V239.md):

  - adopt gate: pooled mean-Δ(selective−legacy) > −$300 AND no regime's
    mean-Δ < −$500.
  - Reconstruction prediction to compare against (from
    scripts/v240_universe_forensics.py trade-log reconstruction):
    pooled +$512, crisis −$211, trend +$1,250, recent +$643.

Exit codes: 0 = ok, 5 = any selective cell's determinism verdict FAIL.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

POOLED_MEAN_BAR = -300.0
REGIME_REGRESS_BAR = -500.0

BASELINE = "universe_legacy"    # from the V239 grid
TREATMENT = "universe_selective"  # from the V240 grid

RECONSTRUCTION_PREDICTION = {
    "pooled": 511.71, "crisis": -210.93, "trend": 1250.21, "recent": 642.57,
}


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
    for w in manifest["windows"]:
        for prefix, cfg in (("v239wf", BASELINE), ("v240wf", TREATMENT)):
            cell = read_cell(root, prefix, w["id"], cfg, w["regime"])
            if cell is None:
                missing.append(f"{w['id']}/{cfg}")
                continue
            if cell["determinism"] != "PASS" and cfg == TREATMENT:
                det_fail.append(f"{w['id']}/{cfg} spread=${cell['pnl_spread']}")
            rows.append({
                "window": w["id"], "regime": w["regime"],
                "high_vol": w.get("high_vol", False), "config": cfg, **cell,
            })

    by = {}
    for r in rows:
        if r["pnl"] is not None:
            by.setdefault((r["regime"], r["config"]), []).append(r)

    regimes = sorted({r["regime"] for r in rows})
    dist = {}
    all_deltas: list[float] = []
    for reg in regimes:
        dist[reg] = {}
        for cfg in (BASELINE, TREATMENT):
            dist[reg][cfg] = dist_stats([c["pnl"] for c in by.get((reg, cfg), [])])
        base_map = {c["window"]: c["pnl"] for c in by.get((reg, BASELINE), [])}
        treat_map = {c["window"]: c["pnl"] for c in by.get((reg, TREATMENT), [])}
        deltas = {wid: round(treat_map[wid] - base_map[wid], 2)
                  for wid in base_map if wid in treat_map}
        dist[reg]["delta"] = dist_stats(list(deltas.values()))
        dist[reg]["delta_per_window"] = deltas
        all_deltas.extend(deltas.values())

    verdicts = {}
    pooled = dist_stats(all_deltas)
    regime_means = {reg: dist[reg]["delta"].get("mean")
                    for reg in regimes if dist[reg]["delta"].get("n", 0) > 0}
    worst_regime = min(regime_means.items(), key=lambda kv: kv[1]) if regime_means else (None, None)
    if pooled.get("n", 0) >= 10 and regime_means:
        adopt = (pooled["mean"] > POOLED_MEAN_BAR
                 and all(m > REGIME_REGRESS_BAR for m in regime_means.values()))
        verdicts["adopt_universe_selective"] = {
            "bar": f"pooled mean-D > {POOLED_MEAN_BAR:+.0f} AND every regime mean-D > {REGIME_REGRESS_BAR:+.0f}",
            "measured": {"pooled_mean": pooled.get("mean"), "pooled_n": pooled.get("n"),
                         "regime_means": regime_means, "worst_regime": worst_regime},
            "reconstruction_prediction": RECONSTRUCTION_PREDICTION,
            "verdict": ("ADOPT SELECTIVE UNIVERSE AS STANDING BASELINE" if adopt
                        else "KEEP LEGACY 4-NAME UNIVERSE — selective reconstruction did not survive full-run"),
        }
    else:
        verdicts["adopt_universe_selective"] = {"verdict": "INSUFFICIENT CELLS", "n": pooled.get("n", 0)}
    verdicts["infra_ship"] = {
        "bar": "determinism PASS on all selective cells",
        "determinism_failures": len(det_fail),
        "verdict": "SHIP" if not det_fail else "BLOCKED",
    }
    verdicts["noise_note"] = ("any per-regime 'improvement' claim must clear the "
                              "REFLECTION_V237 threshold (recent 2*SE ~= $2,400); "
                              "the selective flip's null hypothesis is 'does not regress'")

    out = {
        "version": "v240_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = ["# V240 selective-universe confirm results (auto-generated)", "",
          "`universe_selective` (V240 grid: blacklist {BTC, DOT, LINK}, 10-name "
          "universe) vs `universe_legacy` (reused V239 grid cells, 4 names) over "
          "the 32-window manifest.", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — all verdicts BLOCKED until bisected/fenced.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    for reg in regimes:
        md += [f"## {reg}", "",
               "| config | n | mean | p25 | median | min | max |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        for cfg in (BASELINE, TREATMENT, "delta"):
            s = dist[reg].get(cfg, {})
            if s.get("n"):
                md.append(f"| {cfg} | {s['n']} | {s['mean']:,.2f} | {s['p25']:,.2f} | "
                          f"{s['median']:,.2f} | {s['min']:,.2f} | {s['max']:,.2f} |")
        md += ["", "Per-window Δ (selective − legacy): " +
               json.dumps(dist[reg].get("delta_per_window", {})), ""]
    md += ["## Pooled Δ (selective − legacy, all windows)", "", "```json",
           json.dumps(pooled, indent=2), "```", ""]
    md += ["## Pre-registered verdicts (V240.md Track A acceptance bar)", "", "```json",
           json.dumps(verdicts, indent=2), "```", ""]
    md += ["## Per-window detail", "",
           "| window | regime | config | pnl | trades | det | N |",
           "|---|---|---|---:|---:|---|---:|"]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
                  f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |")
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"v240_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    for k, v in verdicts.items():
        if isinstance(v, dict):
            print(f"  {k}: {v.get('verdict')}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
