#!/usr/bin/env python3
"""
V243 Candidate A — universe-blacklist-extension confirm-grid aggregator.

Joins the two FRESH same-code arms produced by scripts/v243a_wf_grid.sh:
  BASELINE  = universe_selective     (flag OFF, blacklist {BTC,DOT,LINK})
  TREATMENT = universe_selective_ext (flag ON, blacklist {BTC,DOT,LINK,ADA,NEAR,ARB})
both under prefix v243awf, over the 32-window manifest. Reports the per-regime
and pooled distribution of Δ(ext − selective) and applies the pre-registered
three-tier verdict (V243_A_VERDICT.md).

Three-tier acceptance:
  ADOPT           — recent mean-Δ >= +$300 AND pooled mean-Δ >= +$400 AND no
                    regime mean-Δ worse than −$100.
  KEEP FLAG-GATED — recent mean-Δ in [+$100, +$300) AND positive in every regime.
  REVERT          — any regime mean-Δ worse than −$300 (dominates).
  (otherwise: INCONCLUSIVE — falls between the tiers.)

In-sample drop-only paper prediction (V240 ledgers, ignores budget/N & demean):
  crisis +$838, trend +$163, recent +$374, pooled +$482.

Exit codes: 0 = ok, 5 = any cell's determinism verdict FAIL (blocks verdict).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

PREFIX = "v243awf"
BASELINE = "universe_selective"
TREATMENT = "universe_selective_ext"

# three-tier bars
ADOPT_RECENT_BAR = 300.0
ADOPT_POOLED_BAR = 400.0
ADOPT_REGIME_FLOOR = -100.0
KEEP_RECENT_LO = 100.0
KEEP_RECENT_HI = 300.0
REVERT_REGIME_FLOOR = -300.0

PAPER_PREDICTION = {"crisis": 837.6, "trend": 163.4, "recent": 373.8, "pooled": 482.0}


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
    ap.add_argument("--root", default="data")
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
        for cfg in (BASELINE, TREATMENT):
            cell = read_cell(root, PREFIX, w["id"], cfg, w["regime"])
            if cell is None:
                missing.append(f"{w['id']}/{cfg}")
                continue
            if cell["determinism"] != "PASS":
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

    pooled = dist_stats(all_deltas)
    regime_means = {reg: dist[reg]["delta"].get("mean")
                    for reg in regimes if dist[reg]["delta"].get("n", 0) > 0}
    worst_regime = min(regime_means.items(), key=lambda kv: kv[1]) if regime_means else (None, None)
    recent_mean = regime_means.get("recent")
    pooled_mean = pooled.get("mean")

    # three-tier verdict
    verdict = "INSUFFICIENT CELLS"
    if pooled.get("n", 0) >= 10 and regime_means and recent_mean is not None:
        if any(m < REVERT_REGIME_FLOOR for m in regime_means.values()):
            verdict = "REVERT"
        elif (recent_mean >= ADOPT_RECENT_BAR and pooled_mean >= ADOPT_POOLED_BAR
              and all(m >= ADOPT_REGIME_FLOOR for m in regime_means.values())):
            verdict = "ADOPT — baseline shifts to selective+extended"
        elif (KEEP_RECENT_LO <= recent_mean < KEEP_RECENT_HI
              and all(m > 0 for m in regime_means.values())):
            verdict = "KEEP FLAG-GATED"
        else:
            verdict = "INCONCLUSIVE — between tiers; stays FLAG-GATED OFF by default"

    verdicts = {
        "adopt_bar": (f"recent mean-Δ >= +${ADOPT_RECENT_BAR:.0f} AND pooled mean-Δ "
                      f">= +${ADOPT_POOLED_BAR:.0f} AND every regime mean-Δ >= "
                      f"−${abs(ADOPT_REGIME_FLOOR):.0f}"),
        "keep_bar": (f"recent mean-Δ in [+${KEEP_RECENT_LO:.0f},+${KEEP_RECENT_HI:.0f}) "
                     f"AND positive in every regime"),
        "revert_bar": f"any regime mean-Δ < −${abs(REVERT_REGIME_FLOOR):.0f}",
        "measured": {"recent_mean": recent_mean, "pooled_mean": pooled_mean,
                     "pooled_n": pooled.get("n"), "regime_means": regime_means,
                     "worst_regime": worst_regime},
        "paper_prediction": PAPER_PREDICTION,
        "verdict": verdict,
        "determinism": {"failures": len(det_fail),
                        "status": "SHIP" if not det_fail else "BLOCKED"},
        "noise_note": ("recent 2*SE ~= $2,400 (REFLECTION_V237); a mean-Δ inside "
                       "that band is directional, not significant — the acceptance "
                       "unit is the distribution, not a single window."),
    }

    out = {
        "version": "v243a_wf",
        "rows": rows,
        "distributions": dist,
        "pooled_delta": pooled,
        "verdicts": verdicts,
        "determinism_failures": det_fail,
        "missing_cells": missing,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2) + "\n")

    md = ["# V243.A universe-blacklist-extension confirm results (auto-generated)", "",
          "`universe_selective_ext` (flag ON: blacklist {BTC,DOT,LINK,ADA,NEAR,ARB}, "
          "7-name universe) vs `universe_selective` (flag OFF: {BTC,DOT,LINK}, 10-name "
          "universe) — BOTH arms run fresh on the V243.A branch, same code, flag-only "
          "A/B, over the 32-window manifest. Δ = ext − selective.", ""]
    if det_fail:
        md += ["**DETERMINISM FAIL** on: " + ", ".join(det_fail) +
               " — verdict BLOCKED until bisected/fenced.", ""]
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
        md += ["", "Per-window Δ (ext − selective): " +
               json.dumps(dist[reg].get("delta_per_window", {})), ""]
    md += ["## Pooled Δ (ext − selective, all windows)", "", "```json",
           json.dumps(pooled, indent=2), "```", ""]
    md += ["## Pre-registered three-tier verdict (V243_A_VERDICT.md)", "", "```json",
           json.dumps(verdicts, indent=2), "```", ""]
    md += ["## Per-window detail", "",
           "| window | regime | config | pnl | trades | det | N |",
           "|---|---|---|---:|---:|---|---:|"]
    for r in sorted(rows, key=lambda x: (x["window"], x["config"])):
        pnl = f"{r['pnl']:,.2f}" if r["pnl"] is not None else "—"
        md.append(f"| {r['window']} | {r['regime']} | {r['config']} | {pnl} | "
                  f"{r['trades']} | {r['determinism']} | {r['n_replicates']} |")
    Path(args.out_md).write_text("\n".join(md) + "\n")

    print(f"v243a_wf_aggregate: {len(rows)} cells, {len(missing)} missing, "
          f"{len(det_fail)} determinism FAILs")
    print(f"  recent mean-Δ={recent_mean}  pooled mean-Δ={pooled_mean}  "
          f"regime_means={regime_means}")
    print(f"  VERDICT: {verdict}")
    return 5 if det_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
