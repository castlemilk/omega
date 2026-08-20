#!/usr/bin/env python3
"""V274 G0 — standing-baseline IC provenance audit (zero compute).

Answers, from the RUN RECORD rather than the flag defaults, which arm produced
each of the 32 windows behind the standing baseline (crisis +$599 / trend
+$2,997 / recent +$30), and enumerates every committed grid arm in scripts/ that
would have run the IC overlay ON.

Read-only. Writes one JSON verdict when --out is given.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(ROOT / "data")))

# The standing baseline's own `config` field names the V240 universe_selective arm.
CELL_GLOB = "v240wf_*_universe_selective_*_determinism/summary.json"


def audit_cells() -> dict:
    rows = []
    for f in sorted(glob.glob(str(AUDIT / CELL_GLOB))):
        s = json.load(open(f))
        feats = json.loads(s["features"])
        rows.append(
            {
                "window": s["window"],
                "gate": s["gate"],
                "artifact": os.path.relpath(f, str(AUDIT)),
                # absent => the run inherited the features.py default, which is True
                "ic_seed_weighting": feats.get("ic_seed_weighting", "ABSENT_DEFAULT_TRUE"),
                "per_regime_ic_weighting": feats.get(
                    "per_regime_ic_weighting", "ABSENT_DEFAULT_TRUE"
                ),
                "pnl": s["pnls"][0],
                "n": s["n"],
                "pnl_spread": s["pnl_spread"],
                "trade_range": s["trade_range"],
                "verdict": s["verdict"],
            }
        )
    return {"cells": rows}


def classify(rows: list[dict]) -> str:
    if not rows:
        return "INCONCLUSIVE"
    vals = {r["ic_seed_weighting"] for r in rows}
    if vals == {False}:
        return "IC_OFF"
    if False not in vals:
        return "IC_ON"
    return "MIXED"


def reproduce_baseline(rows: list[dict]) -> dict:
    man = json.load(open(ROOT / "data" / "walk_forward_manifest.json"))
    regime = {w["id"]: w["regime"] for w in man["windows"]}
    sb = json.load(open(ROOT / "data" / "standing_baseline.json"))
    per_family = sb["distributions"]["per_family"]

    byf: dict[str, list[float]] = collections.defaultdict(list)
    unmapped = []
    for r in rows:
        fam = regime.get(r["window"])
        if fam is None:
            unmapped.append(r["window"])
            continue
        byf[fam].append(r["pnl"])

    out = {"unmapped_windows": unmapped, "families": {}, "reproduces_to_the_cent": True}
    for fam, cfg in per_family.items():
        got = byf.get(fam, [])
        mean = sum(got) / len(got) if got else float("nan")
        ok = len(got) == cfg["n"] and abs(round(mean, 2) - round(cfg["mean_usd"], 2)) < 0.005
        out["families"][fam] = {
            "n_artifact": len(got),
            "n_committed": cfg["n"],
            "mean_artifact_usd": round(mean, 2),
            "mean_committed_usd": round(cfg["mean_usd"], 2),
            "match": ok,
        }
        out["reproduces_to_the_cent"] &= bool(ok)
    return out


ARM_RE = re.compile(r"^([A-Z][A-Z0-9_]*)='(\{.*\})'\s*$", re.M)


def exposure_register() -> list[dict]:
    """Every committed grid-script arm, and whether it runs the IC overlay ON."""
    out = []
    for path in sorted(glob.glob(str(ROOT / "scripts" / "*.sh"))):
        txt = open(path).read()
        for m in ARM_RE.finditer(txt):
            name, js = m.group(1), m.group(2)
            try:
                feats = json.loads(js)
            except json.JSONDecodeError:
                continue
            ic = feats.get("ic_seed_weighting", "ABSENT_DEFAULT_TRUE")
            out.append(
                {
                    "script": os.path.relpath(path, str(ROOT)),
                    "arm": name,
                    "ic_seed_weighting": ic,
                    "ic_overlay_active": ic is not False,
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cells = audit_cells()["cells"]
    verdict = classify(cells)
    repro = reproduce_baseline(cells)
    exposure = exposure_register()

    # G0 requires ALL THREE legs (see V274.md §2/G0).
    g0 = verdict
    if not cells or not repro["reproduces_to_the_cent"]:
        g0 = "INCONCLUSIVE"

    result = {
        "gate": "G0",
        "verdict": g0,
        "arm_classification": verdict,
        "n_cells": len(cells),
        "ic_seed_values": dict(collections.Counter(str(r["ic_seed_weighting"]) for r in cells)),
        "per_regime_values": dict(
            collections.Counter(str(r["per_regime_ic_weighting"]) for r in cells)
        ),
        "determinism": {
            "all_pass": all(r["verdict"] == "PASS" for r in cells),
            "max_pnl_spread": max((r["pnl_spread"] for r in cells), default=None),
            "max_trade_range": max((r["trade_range"] for r in cells), default=None),
        },
        "baseline_reproduction": repro,
        "exposure_register": {
            "ic_on_arms": [e for e in exposure if e["ic_overlay_active"]],
            "ic_off_arms": [e for e in exposure if not e["ic_overlay_active"]],
        },
        "cells": cells,
    }

    print(f"G0 verdict: {g0}   (cells={len(cells)})")
    print(f"  ic_seed_weighting values : {result['ic_seed_values']}")
    print(f"  per_regime_ic_weighting  : {result['per_regime_values']}")
    print(
        f"  determinism              : all_pass={result['determinism']['all_pass']} "
        f"max_spread={result['determinism']['max_pnl_spread']}"
    )
    print("  baseline reproduction    :")
    for fam, d in repro["families"].items():
        print(
            f"    {fam:7s} n {d['n_artifact']}/{d['n_committed']}  "
            f"artifact ${d['mean_artifact_usd']:>9,.2f}  committed ${d['mean_committed_usd']:>9,.2f}  "
            f"{'MATCH' if d['match'] else 'MISMATCH'}"
        )
    print("  exposure register (arms that run the IC overlay ON):")
    for e in result["exposure_register"]["ic_on_arms"]:
        print(f"    {e['script']:32s} {e['arm']:14s} ic_seed_weighting={e['ic_seed_weighting']}")
    print(f"  ({len(result['exposure_register']['ic_off_arms'])} arms explicitly IC-OFF)")

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
