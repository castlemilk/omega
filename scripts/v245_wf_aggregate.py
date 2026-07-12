#!/usr/bin/env python3
"""
V245 — gdelt-solo walk-forward aggregator.

Joins the V245 grid's `gdelt_solo` cells
(v245wf_<window>_gdelt_solo_<gate>_determinism/summary.json) against the
V240 confirm grid's `universe_selective` cells (the standing baseline —
NOT re-run; reproducibility re-certified 2026-07-13 by the 4-window
spot-check), and applies the pre-registered V245 falsifier
(training_log/V245.md):

  V245 FAILS if ANY of:
    1. recent mean-Δ < +$100 AND recent p25-Δ < +$400
    2. pooled p25-Δ  < +$0   (p25 of the pooled per-window Δ distribution)
    3. trend mean-Δ  < −$300
    4. crisis mean-Δ < −$300

  ADOPT (default-ON) only if no clause fires AND pooled mean-Δ > +$0;
  no-clause-fires but pooled mean-Δ ≤ 0 ⇒ KEEP FLAG-GATED.

Exit codes: 0 = ok, 5 = any gdelt_solo cell's determinism verdict FAIL.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

BASELINE_PREFIX, BASELINE_CFG = "v240wf", "universe_selective"
TREATMENT_PREFIX, TREATMENT_CFG = "v245wf", "gdelt_solo"

RECENT_MEAN_BAR = 100.0
RECENT_P25_BAR = 400.0
POOLED_P25_BAR = 0.0
REGIME_REGRESS_BAR = -300.0
ADOPT_POOLED_MEAN_BAR = 0.0


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

    rec_mean, rec_p25 = dmean("recent"), dp25("recent")
    fail_clauses = {
        "recent_conjunction (mean<+100 AND p25<+400)": (
            rec_mean is not None
            and rec_p25 is not None
            and rec_mean < RECENT_MEAN_BAR
            and rec_p25 < RECENT_P25_BAR
        ),
        "pooled_p25_lt_0": (pooled.get("p25") is not None and pooled["p25"] < POOLED_P25_BAR),
        "trend_mean_lt_-300": (dmean("trend") is not None and dmean("trend") < REGIME_REGRESS_BAR),
        "crisis_mean_lt_-300": (
            dmean("crisis") is not None and dmean("crisis") < REGIME_REGRESS_BAR
        ),
    }
    measured = {
        "recent_mean": rec_mean,
        "recent_p25": rec_p25,
        "pooled_p25": pooled.get("p25"),
        "pooled_mean": pooled.get("mean"),
        "trend_mean": dmean("trend"),
        "crisis_mean": dmean("crisis"),
    }
    complete = not missing and all(v is not None for v in measured.values())
    any_fail = any(fail_clauses.values())
    adopt = (
        complete
        and not det_fail
        and not any_fail
        and pooled["mean"] > ADOPT_POOLED_MEAN_BAR
    )
    if not complete or det_fail:
        verdict = "BLOCKED — missing cells or determinism FAIL"
    elif any_fail:
        verdict = "REFUTED — falsifier clause(s) fired; flag stays OFF"
    elif adopt:
        verdict = "ADOPT — gdelt_solo default-ON"
    else:
        verdict = "KEEP FLAG-GATED — no falsifier clause fired but pooled mean-D <= $0"

    verdicts = {
        "v245_falsifier": {
            "bar": (
                "FAIL if ANY: (recent mean-D<+$100 AND recent p25-D<+$400); "
                "pooled p25-D<$0; trend mean-D<-$300; crisis mean-D<-$300. "
                "ADOPT only if none fire AND pooled mean-D>$0."
            ),
            "measured": measured,
            "fail_clauses": fail_clauses,
            "verdict": verdict,
        },
        "determinism": {
            "failures": len(det_fail),
            "verdict": "PASS" if not det_fail else "FAIL",
        },
        "noise_note": (
            "recent 2*SE ~= $2,400; the falsifier's conjunction structure is the "
            "standing REFLECTION_V241 threshold (mean + p25 + no-regression)"
        ),
    }

    out = {
        "version": "v245_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = [
        "# V245 gdelt-solo walk-forward results (auto-generated)",
        "",
        "`gdelt_solo` (selective universe + frozen_series gdelt + "
        "geopolitical_signals) vs `universe_selective` (reused V240 confirm "
        "cells — the standing baseline) over the 32-window manifest.",
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
            "Per-window Δ (gdelt_solo − selective): "
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
        "## Pre-registered verdict (V245.md falsifier)",
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
        f"v245_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
        f"{len(det_fail)} determinism FAILs"
    )
    print(f"  verdict: {verdict}")
    for k, v in measured.items():
        print(f"    {k}: {v}")
    for k, fired in fail_clauses.items():
        print(f"    FAIL-CLAUSE {k}: {'FIRED' if fired else 'ok'}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
