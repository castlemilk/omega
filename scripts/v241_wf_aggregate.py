#!/usr/bin/env python3
"""
V241 — reasoning-layer walk-forward aggregator.

Joins the V241 grid's `reasoning_on` cells
(v241wf_<window>_reasoning_on_<gate>_determinism/summary.json) against the
V240 confirm grid's `universe_selective` cells (the standing baseline —
NOT re-run; reproducibility certified by scripts/v241_baseline_spotcheck.sh),
and applies the pre-registered V241 falsifier (training_log/V241.md):

  ADOPT (default-ON) iff ALL of:
    1. recent mean-Δ  > +$400
    2. recent p25-Δ   > +$500   (p25 of the per-window Δ distribution)
    3. trend mean-Δ   > −$300
    4. crisis mean-Δ  > −$300

  ANY clause fails → KEEP FLAG-GATED OFF (revert-and-branch reflection per
  the launch directive if the phase-0 tracer also fired).

Exit codes: 0 = ok, 5 = any reasoning_on cell's determinism verdict FAIL.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

BASELINE_PREFIX, BASELINE_CFG = "v240wf", "universe_selective"
TREATMENT_PREFIX, TREATMENT_CFG = "v241wf", "reasoning_on"

RECENT_MEAN_BAR = 400.0
RECENT_P25_BAR = 500.0
REGIME_REGRESS_BAR = -300.0


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
        "p75": round(pctl(vals, 0.75), 2),
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
    ap.add_argument("--root", default="data")
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    root = Path(args.root)

    rows, det_fail, missing = [], [], []
    for w in manifest["windows"]:
        for prefix, cfg in ((BASELINE_PREFIX, BASELINE_CFG), (TREATMENT_PREFIX, TREATMENT_CFG)):
            cell = read_cell(root, prefix, w["id"], cfg, w["regime"])
            if cell is None:
                missing.append(f"{w['id']}/{cfg}")
                continue
            if cell["determinism"] != "PASS" and cfg == TREATMENT_CFG:
                det_fail.append(f"{w['id']}/{cfg} spread=${cell['pnl_spread']}")
            rows.append({"window": w["id"], "regime": w["regime"], "config": cfg, **cell})

    by: dict = {}
    for r in rows:
        if r["pnl"] is not None:
            by.setdefault((r["regime"], r["config"]), []).append(r)

    regimes = sorted({r["regime"] for r in rows})
    dist: dict = {}
    all_deltas: list[float] = []
    for reg in regimes:
        dist[reg] = {}
        for cfg in (BASELINE_CFG, TREATMENT_CFG):
            dist[reg][cfg] = dist_stats([c["pnl"] for c in by.get((reg, cfg), [])])
        base_map = {c["window"]: c["pnl"] for c in by.get((reg, BASELINE_CFG), [])}
        treat_map = {c["window"]: c["pnl"] for c in by.get((reg, TREATMENT_CFG), [])}
        deltas = {
            wid: round(treat_map[wid] - base_map[wid], 2) for wid in base_map if wid in treat_map
        }
        dist[reg]["delta"] = dist_stats(list(deltas.values()))
        dist[reg]["delta_per_window"] = deltas
        all_deltas.extend(deltas.values())

    pooled = dist_stats(all_deltas)

    def dmean(reg: str):
        return dist.get(reg, {}).get("delta", {}).get("mean")

    def dp25(reg: str):
        return dist.get(reg, {}).get("delta", {}).get("p25")

    clauses = {
        "recent_mean_gt_400": (dmean("recent"), RECENT_MEAN_BAR, "gt"),
        "recent_p25_gt_500": (dp25("recent"), RECENT_P25_BAR, "gt"),
        "trend_mean_gt_-300": (dmean("trend"), REGIME_REGRESS_BAR, "gt"),
        "crisis_mean_gt_-300": (dmean("crisis"), REGIME_REGRESS_BAR, "gt"),
    }
    clause_results = {
        k: {"measured": v, "bar": bar, "pass": (v is not None and v > bar)}
        for k, (v, bar, _) in clauses.items()
    }
    complete = not missing and all(v[0] is not None for v in clauses.values())
    adopt = complete and not det_fail and all(c["pass"] for c in clause_results.values())

    verdicts = {
        "adopt_reasoning_layer": {
            "bar": (
                "recent mean-D > +$400 AND recent p25-D > +$500 AND "
                "trend mean-D > -$300 AND crisis mean-D > -$300 (conjunction)"
            ),
            "clauses": clause_results,
            "verdict": (
                "ADOPT — reasoning layer default-ON"
                if adopt
                else "KEEP FLAG-GATED OFF — falsifier clause(s) failed"
                if complete and not det_fail
                else "BLOCKED — missing cells or determinism FAIL"
            ),
        },
        "determinism": {
            "failures": len(det_fail),
            "verdict": "PASS" if not det_fail else "FAIL",
        },
        "noise_note": (
            "recent 2*SE ~= $2,400 (REFLECTION_V237 §2): a lone +$400 mean is in "
            "noise, which is why the falsifier conjoins p25 + no-regression bars"
        ),
    }

    out = {
        "version": "v241_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = [
        "# V241 reasoning-layer walk-forward results (auto-generated)",
        "",
        "`reasoning_on` (V241 grid: selective universe + reasoning_layer_enabled, "
        "served entirely from the frozen LLM cache) vs `universe_selective` "
        "(reused V240 confirm cells — the standing baseline) over the 32-window "
        "manifest.",
        "",
    ]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) + " — verdict BLOCKED.", ""]
    if missing:
        md += [f"Missing cells ({len(missing)}): " + ", ".join(missing), ""]
    for reg in regimes:
        md += [
            f"## {reg}",
            "",
            "| config | n | mean | p25 | median | p75 | min | max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for cfg in (BASELINE_CFG, TREATMENT_CFG, "delta"):
            s = dist[reg].get(cfg, {})
            if s.get("n"):
                md.append(
                    f"| {cfg} | {s['n']} | {s['mean']:,.2f} | {s['p25']:,.2f} | "
                    f"{s['median']:,.2f} | {s['p75']:,.2f} | {s['min']:,.2f} | {s['max']:,.2f} |"
                )
        md += [
            "",
            "Per-window Δ (reasoning_on − selective): "
            + json.dumps(dist[reg].get("delta_per_window", {})),
            "",
        ]
    md += [
        "## Pooled Δ (all windows)",
        "",
        "```json",
        json.dumps(pooled, indent=2),
        "```",
        "",
        "## Pre-registered verdict (V241.md falsifier)",
        "",
        "```json",
        json.dumps(verdicts, indent=2),
        "```",
        "",
        "## Per-window detail",
        "",
        "| window | regime | config | pnl | trades | det | N |",
        "|---|---|---|---:|---:|---|---:|",
    ]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(
            f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
            f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |"
        )
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(
        f"v241_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
        f"{len(det_fail)} determinism FAILs"
    )
    print(f"  adopt_reasoning_layer: {verdicts['adopt_reasoning_layer']['verdict']}")
    for k, c in clause_results.items():
        print(f"    {k}: measured={c['measured']} bar={c['bar']:+.0f} pass={c['pass']}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
