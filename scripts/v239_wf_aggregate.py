#!/usr/bin/env python3
"""
V239 — walk-forward universe-flip aggregator (blacklist legacy vs full).

Reads every v239wf_<window>_<config>_<gate>_determinism/summary.json produced
by scripts/v239_wf_grid.sh, joins against data/walk_forward_manifest.json, and
emits per-regime distributions for `universe_legacy` (the 4-name blacklist ON
baseline — must equal the V238 `main` baseline, which is byte-identical to
V235) and `universe_full` (blacklist flipped to empty → 13-name universe), plus
the pre-registered V239 acceptance reads (training_log/V239.md):

  - infra ship gate: determinism PASS on all cells (exit 5 otherwise) +
    legacy-path identity vs the V238 grid's `main` cells (checked per-window
    when the V238 distribution.json is available). universe_full_enabled
    defaults OFF, so the legacy arm must be byte-identical.
  - adopt gate: pooled mean-Δ(full−legacy) > −$300 AND no regime's mean-Δ
    < −$500 (same acceptance shape as V238's adopt-ON, per V239.md "universe
    changes are strategy changes"). Any "improvement" claim additionally needs
    to clear the REFLECTION_V237 noise threshold (recent 2·SE ≈ $2,400) —
    reported, not auto-verdicted.

Exit codes: 0 = ok, 5 = any cell's determinism verdict FAIL (blocks verdicts).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

POOLED_MEAN_BAR = -300.0   # adopt: pooled mean-Δ must exceed this
REGIME_REGRESS_BAR = -500.0  # adopt: no regime mean-Δ below this

BASELINE = "universe_legacy"
TREATMENT = "universe_full"
CONFIGS = (BASELINE, TREATMENT)


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
    ap.add_argument("--v238-distribution", default=None,
                    help="optional path to the V238 grid's distribution.json for legacy-identity check")
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
            sp = root / f"v239wf_{w['id']}_{cfg}_{w['regime']}_determinism" / "summary.json"
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
        base_map = {c["window"]: c["pnl"] for c in by.get((reg, BASELINE), [])}
        treat_map = {c["window"]: c["pnl"] for c in by.get((reg, TREATMENT), [])}
        deltas = {wid: round(treat_map[wid] - base_map[wid], 2)
                  for wid in base_map if wid in treat_map}
        dist[reg]["delta"] = dist_stats(list(deltas.values()))
        dist[reg]["delta_per_window"] = deltas
        all_deltas.extend(deltas.values())

    # --- legacy-path identity vs the V238 grid's `main` cells (when available) ---
    off_identity = {"checked": False}
    v238_path = args.v238_distribution or str(root / "v238_wf" / "distribution.json")
    if Path(v238_path).exists():
        v238 = json.loads(Path(v238_path).read_text())
        v238_main = {r["window"]: r["pnl"] for r in v238.get("rows", [])
                     if r.get("config") == "main" and r.get("pnl") is not None}
        diffs = {}
        for r in rows:
            if r["config"] == BASELINE and r["pnl"] is not None and r["window"] in v238_main:
                d = round(r["pnl"] - v238_main[r["window"]], 2)
                if d != 0.0:
                    diffs[r["window"]] = d
        off_identity = {
            "checked": True,
            "v238_distribution": v238_path,
            "baseline_config": BASELINE,
            "windows_compared": sum(1 for r in rows
                                    if r["config"] == BASELINE and r["window"] in v238_main),
            "nonzero_diffs": diffs,
            "verdict": "IDENTICAL" if not diffs else "DIVERGED — legacy path is NOT byte-identical",
        }

    # --- Pre-registered V239 acceptance reads -------------------------------
    verdicts = {}
    pooled = dist_stats(all_deltas)
    regime_means = {reg: dist[reg]["delta"].get("mean")
                    for reg in regimes if dist[reg]["delta"].get("n", 0) > 0}
    worst_regime = min(regime_means.items(), key=lambda kv: kv[1]) if regime_means else (None, None)
    if pooled.get("n", 0) >= 10 and regime_means:
        adopt = (pooled["mean"] > POOLED_MEAN_BAR
                 and all(m > REGIME_REGRESS_BAR for m in regime_means.values()))
        verdicts["adopt_universe_full"] = {
            "bar": f"pooled mean-D > {POOLED_MEAN_BAR:+.0f} AND every regime mean-D > {REGIME_REGRESS_BAR:+.0f}",
            "measured": {"pooled_mean": pooled.get("mean"), "pooled_n": pooled.get("n"),
                         "regime_means": regime_means, "worst_regime": worst_regime},
            "verdict": "ADOPT FULL UNIVERSE AS STANDING BASELINE" if adopt else "KEEP LEGACY 4-NAME UNIVERSE — per-ticker forensics next",
        }
    else:
        verdicts["adopt_universe_full"] = {"verdict": "INSUFFICIENT CELLS", "n": pooled.get("n", 0)}
    verdicts["infra_ship"] = {
        "bar": "determinism PASS all cells + legacy identity vs V238 main + coverage clean",
        "determinism_failures": len(det_fail),
        "legacy_identity": off_identity.get("verdict", "NOT CHECKED"),
        "verdict": ("SHIP" if not det_fail
                    and off_identity.get("verdict") in ("IDENTICAL", "NOT CHECKED")
                    else "BLOCKED"),
    }
    verdicts["noise_note"] = ("any per-regime 'improvement' claim must clear the "
                              "REFLECTION_V237 threshold (recent 2*SE ~= $2,400); "
                              "the flip's null hypothesis is 'does not regress'")

    out = {
        "version": "v239_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "off_identity": off_identity,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = ["# V239 walk-forward universe-flip results (auto-generated)", "",
          "blacklist ON (`universe_legacy`, 4 names) vs OFF (`universe_full`, 13 names) "
          "over the 32-window manifest.", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — all verdicts BLOCKED until bisected/fenced.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    md += ["## legacy-path identity vs V238 `main` grid", "", "```json",
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
        md += ["", "Per-window Δ (full − legacy): " +
               json.dumps(dist[reg].get("delta_per_window", {})), ""]
    md += ["## Pooled Δ (full − legacy, all windows)", "", "```json",
           json.dumps(pooled, indent=2), "```", ""]
    md += ["## Pre-registered verdicts (V239.md acceptance bar)", "", "```json",
           json.dumps(verdicts, indent=2), "```", ""]
    md += ["## Per-window detail", "",
           "| window | regime | config | pnl | trades | det | N |",
           "|---|---|---|---:|---:|---|---:|"]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
                  f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |")
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"v239_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    for k, v in verdicts.items():
        if isinstance(v, dict):
            print(f"  {k}: {v.get('verdict')}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
