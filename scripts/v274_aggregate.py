#!/usr/bin/env python3
"""V274 — pair the IC-ON arm against the standing baseline and score G1/G2/G3/G4/G-DET.

Bars are those pre-registered in omega/nodes/victoria/training_log/V274.md §2,
fixed before any run. This script computes; it does not choose bars.

Read-only apart from the one verdict file it writes.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(ROOT / "data")))

G1_TOLERANCE = 0.20  # V274.md §2/G1 — fixed before any run
G4_TOLERANCE = 0.01  # V274.md §2/G4 — 1.0% per sentinel cell
MDE_Z = 2.801585  # V247_RULER.md §4
SENTINELS = {
    "snap_wf_20240310": "crisis",
    "snap_wf_20230912": "trend",
    "snap_wf_20250305": "recent",
}


def load_cells(pattern: str) -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(AUDIT / pattern))):
        s = json.load(open(f))
        out[s["window"]] = {
            "gate": s["gate"],
            "pnl": s["pnls"][0],
            "pnls": s["pnls"],
            "trades": s["trades"],
            "n": s["n"],
            "pnl_spread": s["pnl_spread"],
            "trade_range": s["trade_range"],
            "verdict": s["verdict"],
            "features": json.loads(s["features"]),
        }
    return out


def mde(sd: float, n: int) -> float:
    return MDE_Z * sd / math.sqrt(n) if n > 1 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    man = json.load(open(ROOT / "data" / "walk_forward_manifest.json"))
    regime = {w["id"]: w["regime"] for w in man["windows"]}
    sb_cfg = json.load(open(ROOT / "data" / "standing_baseline.json"))
    sb_family = sb_cfg["distributions"]["per_family"]

    base = load_cells("v240wf_*_universe_selective_*_determinism/summary.json")
    cand = load_cells("v274_on_*_determinism/summary.json")
    off_smoke = load_cells("v274_off_*_determinism/summary.json")

    res: dict = {"version": "v274", "bars": {"g1_tolerance": G1_TOLERANCE, "g4_tolerance": G4_TOLERANCE}}

    # ── G4: harness sanity on the three sentinels, IC-OFF arm ────────────
    g4 = {"cells": [], "verdict": "not_evaluated"}
    if off_smoke:
        ok = True
        for wid, fam in SENTINELS.items():
            b = base.get(wid)
            o = off_smoke.get(wid)
            if b is None or o is None:
                g4["cells"].append({"window": wid, "status": "missing"})
                ok = False
                continue
            denom = abs(b["pnl"]) or 1.0
            rel = abs(o["pnl"] - b["pnl"]) / denom
            cell_ok = rel <= G4_TOLERANCE
            ok &= cell_ok
            g4["cells"].append(
                {
                    "window": wid,
                    "family": fam,
                    "committed_usd": b["pnl"],
                    "rerun_usd": o["pnl"],
                    "abs_delta_usd": round(o["pnl"] - b["pnl"], 2),
                    "rel_delta": round(rel, 6),
                    "trades_committed": b["trades"][0],
                    "trades_rerun": o["trades"][0],
                    "status": "pass" if cell_ok else "fail",
                }
            )
        g4["verdict"] = "PASS" if ok else "FAIL"
    res["G4_harness_sanity"] = g4

    # ── G-DET ────────────────────────────────────────────────────────────
    det_cells = [
        {"window": w, "arm": arm, "spread": c["pnl_spread"], "trade_range": c["trade_range"],
         "n": c["n"], "verdict": c["verdict"]}
        for arm, src in (("ic_on", cand), ("ic_off_smoke", off_smoke))
        for w, c in sorted(src.items())
    ]
    det_bad = [c for c in det_cells if c["spread"] != 0.0 or c["trade_range"] != 0]
    res["G_DET"] = {
        "verdict": "PASS" if det_cells and not det_bad else ("FAIL" if det_bad else "not_evaluated"),
        "n_cells": len(det_cells),
        "violations": det_bad,
    }

    # ── G3: regime honesty ───────────────────────────────────────────────
    g3_conflicts = []
    for wid, c in cand.items():
        want = regime.get(wid)
        if want is None:
            g3_conflicts.append({"window": wid, "issue": "not in manifest"})
        elif c["gate"] != want:
            g3_conflicts.append({"window": wid, "manifest": want, "candidate_gate": c["gate"]})
        b = base.get(wid)
        if b is not None and want is not None and b["gate"] != want:
            g3_conflicts.append({"window": wid, "manifest": want, "baseline_gate": b["gate"]})
    res["G3_regime_honesty"] = {
        "verdict": "PASS" if cand and not g3_conflicts else ("FAIL" if g3_conflicts else "not_evaluated"),
        "source": "data/walk_forward_manifest.json windows[].regime (ex-post substrate rule)",
        "conflicts": g3_conflicts,
    }

    # ── coverage ─────────────────────────────────────────────────────────
    missing = sorted(set(regime) - set(cand))
    res["coverage"] = {
        "n_manifest": len(regime),
        "n_candidate": len(cand),
        "missing_windows": missing,
        "complete": not missing,
    }

    # ── G1 / G2 ──────────────────────────────────────────────────────────
    byf_pairs: dict[str, list[dict]] = collections.defaultdict(list)
    for wid, c in cand.items():
        b = base.get(wid)
        if b is None:
            continue
        byf_pairs[regime[wid]].append(
            {
                "window": wid,
                "baseline_usd": b["pnl"],
                "candidate_usd": c["pnl"],
                "delta_usd": round(c["pnl"] - b["pnl"], 2),
                "baseline_trades": b["trades"][0],
                "candidate_trades": c["trades"][0],
                "sign_flip": (b["pnl"] > 0) != (c["pnl"] > 0),
                "crosses_zero_floor": b["pnl"] >= 0 > c["pnl"],
            }
        )

    g1: dict = {"families": {}, "verdict": "not_evaluated"}
    g2: dict = {"coupling_class_declared": "heavy", "families": {}}
    g1_ok = True
    for fam, cfg in sb_family.items():
        pairs = sorted(byf_pairs.get(fam, []), key=lambda p: p["window"])
        if not pairs:
            g1["families"][fam] = {"status": "not_evaluated"}
            continue
        sb_mean = cfg["mean_usd"]
        cand_mean = statistics.fmean(p["candidate_usd"] for p in pairs)
        band = G1_TOLERANCE * abs(sb_mean)
        within = abs(cand_mean - sb_mean) <= band
        g1_ok &= within
        g1["families"][fam] = {
            "n": len(pairs),
            "n_committed": cfg["n"],
            "standing_baseline_mean_usd": round(sb_mean, 2),
            "candidate_mean_usd": round(cand_mean, 2),
            "abs_delta_usd": round(cand_mean - sb_mean, 2),
            "rel_delta": round((cand_mean - sb_mean) / abs(sb_mean), 4) if sb_mean else None,
            "band_usd": round(band, 2),
            "status": "pass" if within else "fail",
        }

        deltas = [p["delta_usd"] for p in pairs]
        sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        g2["families"][fam] = {
            "n": len(deltas),
            "mean_delta_usd": round(statistics.fmean(deltas), 2),
            "sd_delta_usd": round(sd, 2),
            "median_delta_usd": round(statistics.median(deltas), 2),
            "min_delta_usd": round(min(deltas), 2),
            "max_delta_usd": round(max(deltas), 2),
            "n_nonzero_delta": sum(1 for d in deltas if d != 0.0),
            "n_sign_flips": sum(1 for p in pairs if p["sign_flip"]),
            "n_crossing_zero_floor": sum(1 for p in pairs if p["crosses_zero_floor"]),
            "mde_at_actual_n_usd": round(mde(sd, len(deltas)), 2) if len(deltas) > 1 else None,
            "mean_delta_inside_mde": (
                abs(statistics.fmean(deltas)) <= mde(sd, len(deltas)) if len(deltas) > 1 and sd else None
            ),
            "published_mde_usd": sb_cfg["grid_ruler"]["published_mde_usd_at_current_n"].get(fam),
            "pairs": pairs,
        }

    if any(v.get("status") in ("pass", "fail") for v in g1["families"].values()):
        g1["verdict"] = "PASS" if g1_ok else "FAIL"
    res["G1_family_mean_survival"] = g1
    res["G2_per_cell_distribution"] = g2

    # pooled
    all_deltas = [p["delta_usd"] for ps in byf_pairs.values() for p in ps]
    if len(all_deltas) > 1:
        sd = statistics.stdev(all_deltas)
        res["pooled"] = {
            "n": len(all_deltas),
            "mean_delta_usd": round(statistics.fmean(all_deltas), 2),
            "sd_delta_usd": round(sd, 2),
            "mde_at_actual_n_usd": round(mde(sd, len(all_deltas)), 2),
            "published_mde_usd": sb_cfg["grid_ruler"]["published_mde_usd_at_current_n"]["pooled"],
        }

    # ── report ───────────────────────────────────────────────────────────
    print(f"G4 harness sanity : {g4['verdict']}")
    for c in g4["cells"]:
        if c.get("status") == "missing":
            print(f"   {c['window']:18s} MISSING")
        else:
            print(
                f"   {c['window']:18s} {c['family']:7s} committed ${c['committed_usd']:>10,.2f}  "
                f"rerun ${c['rerun_usd']:>10,.2f}  rel {c['rel_delta']:.6f}  {c['status'].upper()}"
            )
    print(f"G-DET             : {res['G_DET']['verdict']} ({res['G_DET']['n_cells']} cells, "
          f"{len(res['G_DET']['violations'])} violations)")
    print(f"G3 regime honesty : {res['G3_regime_honesty']['verdict']} "
          f"({len(g3_conflicts)} conflicts)")
    print(f"coverage          : {res['coverage']['n_candidate']}/{res['coverage']['n_manifest']} "
          f"windows{'' if res['coverage']['complete'] else ' — INCOMPLETE'}")
    print(f"G1 family means   : {g1['verdict']}   (bar: ±{G1_TOLERANCE:.0%})")
    for fam, d in g1["families"].items():
        if d.get("status") in ("pass", "fail"):
            print(
                f"   {fam:7s} n={d['n']:>2}  SB ${d['standing_baseline_mean_usd']:>9,.2f}  "
                f"IC-ON ${d['candidate_mean_usd']:>9,.2f}  Δ ${d['abs_delta_usd']:>9,.2f}  "
                f"({d['rel_delta']:+.1%} vs band ±${d['band_usd']:,.2f})  {d['status'].upper()}"
            )
    print("G2 paired Δ       :")
    for fam, d in g2["families"].items():
        print(
            f"   {fam:7s} n={d['n']:>2}  meanΔ ${d['mean_delta_usd']:>9,.2f}  sd ${d['sd_delta_usd']:>9,.2f}  "
            f"medianΔ ${d['median_delta_usd']:>9,.2f}  MDE@n ${d['mde_at_actual_n_usd'] or 0:>9,.2f}  "
            f"(pub ${d['published_mde_usd']:,})  nonzero {d['n_nonzero_delta']}/{d['n']}  "
            f"flips {d['n_sign_flips']}"
        )
    if "pooled" in res:
        p = res["pooled"]
        print(f"   pooled  n={p['n']:>2}  meanΔ ${p['mean_delta_usd']:>9,.2f}  sd ${p['sd_delta_usd']:>9,.2f}  "
              f"MDE@n ${p['mde_at_actual_n_usd']:>9,.2f}  (pub ${p['published_mde_usd']:,})")

    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
