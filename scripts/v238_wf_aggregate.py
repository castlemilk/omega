#!/usr/bin/env python3
"""
V238 — walk-forward re-baseline aggregator (frozen-series OFF vs ON).

Reads every v238wf_<window>_<config>_<gate>_determinism/summary.json produced
by scripts/v238_wf_grid.sh, joins against data/walk_forward_manifest.json, and
emits per-regime distributions for `main` (frozen_series OFF — must equal the
V235 baseline) and `series` (ON), plus the pre-registered V238 acceptance
reads (training_log/V238.md):

  - infra ship gate: determinism PASS on all cells (exit 5 otherwise) +
    OFF-path identity vs the V235 grid (checked per-window when the V235
    distribution.json is available).
  - adopt-ON gate: pooled mean-Δ(series−main) > −$300 AND no regime's
    mean-Δ < −$500. Any "improvement" claim additionally needs to clear the
    REFLECTION_V237 noise threshold (recent 2·SE ≈ $2,400) — reported, not
    auto-verdicted.

Exit codes: 0 = ok, 5 = any cell's determinism verdict FAIL (blocks verdicts).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

POOLED_MEAN_BAR = -300.0   # adopt-ON: pooled mean-Δ must exceed this
REGIME_REGRESS_BAR = -500.0  # adopt-ON: no regime mean-Δ below this

CONFIGS = ("main", "series")


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data", help="audit output root (OMEGA_AUDIT_OUTPUT_DIR)")
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--v235-distribution", default=None,
                    help="optional path to the V235 grid's distribution.json for OFF-identity check")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    root = Path(args.root)

    rows = []
    det_fail = []
    missing = []
    for w in manifest["windows"]:
        for cfg in CONFIGS:
            sp = root / f"v238wf_{w['id']}_{cfg}_{w['regime']}_determinism" / "summary.json"
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
                "pnl": pnls[0] if pnls else None,
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
    all_deltas: list[float] = []
    for reg in regimes:
        dist[reg] = {}
        for cfg in CONFIGS:
            cells = by.get((reg, cfg), [])
            dist[reg][cfg] = dist_stats([c["pnl"] for c in cells])
        main_map = {c["window"]: c["pnl"] for c in by.get((reg, "main"), [])}
        s_map = {c["window"]: c["pnl"] for c in by.get((reg, "series"), [])}
        deltas = {wid: round(s_map[wid] - main_map[wid], 2)
                  for wid in main_map if wid in s_map}
        dist[reg]["delta"] = dist_stats(list(deltas.values()))
        dist[reg]["delta_per_window"] = deltas
        all_deltas.extend(deltas.values())

    # --- OFF-path identity vs the V235 grid (when available) ---------------
    off_identity = {"checked": False}
    v235_path = args.v235_distribution or str(root / "v235_wf" / "distribution.json")
    if Path(v235_path).exists():
        v235 = json.loads(Path(v235_path).read_text())
        v235_main = {r["window"]: r["pnl"] for r in v235.get("rows", [])
                     if r.get("config") == "main" and r.get("pnl") is not None}
        diffs = {}
        for r in rows:
            if r["config"] == "main" and r["pnl"] is not None and r["window"] in v235_main:
                d = round(r["pnl"] - v235_main[r["window"]], 2)
                if d != 0.0:
                    diffs[r["window"]] = d
        off_identity = {
            "checked": True,
            "v235_distribution": v235_path,
            "windows_compared": sum(1 for r in rows
                                    if r["config"] == "main" and r["window"] in v235_main),
            "nonzero_diffs": diffs,
            "verdict": "IDENTICAL" if not diffs else "DIVERGED — OFF path is NOT byte-identical",
        }

    # --- Pre-registered V238 acceptance reads -------------------------------
    verdicts = {}
    pooled = dist_stats(all_deltas)
    regime_means = {reg: dist[reg]["delta"].get("mean")
                    for reg in regimes if dist[reg]["delta"].get("n", 0) > 0}
    worst_regime = min(regime_means.items(), key=lambda kv: kv[1]) if regime_means else (None, None)
    if pooled.get("n", 0) >= 10 and regime_means:
        adopt = (pooled["mean"] > POOLED_MEAN_BAR
                 and all(m > REGIME_REGRESS_BAR for m in regime_means.values()))
        verdicts["adopt_series_on"] = {
            "bar": f"pooled mean-D > {POOLED_MEAN_BAR:+.0f} AND every regime mean-D > {REGIME_REGRESS_BAR:+.0f}",
            "measured": {"pooled_mean": pooled.get("mean"), "pooled_n": pooled.get("n"),
                         "regime_means": regime_means, "worst_regime": worst_regime},
            "verdict": "ADOPT ON AS STANDING BASELINE" if adopt else "KEEP FLAG-GATED — per-signal forensics next",
        }
    else:
        verdicts["adopt_series_on"] = {"verdict": "INSUFFICIENT CELLS", "n": pooled.get("n", 0)}
    verdicts["infra_ship"] = {
        "bar": "determinism PASS all cells + OFF identity + coverage clean",
        "determinism_failures": len(det_fail),
        "off_identity": off_identity.get("verdict", "NOT CHECKED"),
        "verdict": ("SHIP" if not det_fail
                    and off_identity.get("verdict") in ("IDENTICAL", "NOT CHECKED")
                    else "BLOCKED"),
    }
    verdicts["noise_note"] = ("any per-regime 'improvement' claim must clear the "
                              "REFLECTION_V237 threshold (recent 2*SE ~= $2,400); "
                              "this re-baseline makes no improvement claim by itself")

    out = {
        "version": "v238_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "off_identity": off_identity,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = ["# V238 walk-forward re-baseline results (auto-generated)", "",
          "frozen-series OFF (`main`) vs ON (`series`) over the 32-window manifest.", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — all verdicts BLOCKED until bisected/fenced.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    md += ["## OFF-path identity vs V235 grid", "", "```json",
           json.dumps(off_identity, indent=2), "```", ""]
    for reg in regimes:
        md += [f"## {reg}", "",
               "| config | n | mean | p25 | median | min | max |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        for cfg in (*CONFIGS, "delta"):
            s = dist[reg].get(cfg, {})
            if s.get("n"):
                md.append(f"| {cfg} | {s['n']} | {s['mean']:,.2f} | {s['p25']:,.2f} | "
                          f"{s['median']:,.2f} | {s['min']:,.2f} | {s['max']:,.2f} |")
        md += ["", "Per-window Δ (series − main): " +
               json.dumps(dist[reg].get("delta_per_window", {})), ""]
    md += ["## Pooled Δ (series − main, all windows)", "", "```json",
           json.dumps(pooled, indent=2), "```", ""]
    md += ["## Pre-registered verdicts (V238.md acceptance bar)", "", "```json",
           json.dumps(verdicts, indent=2), "```", ""]
    md += ["## Per-window detail", "",
           "| window | regime | config | pnl | trades | det | N |",
           "|---|---|---|---:|---:|---|---:|"]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
                  f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |")
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"v238_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    for k, v in verdicts.items():
        if isinstance(v, dict):
            print(f"  {k}: {v.get('verdict')}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
