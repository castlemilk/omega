#!/usr/bin/env python3
"""V232 distributional eval aggregator (prefix-parametrized clone of v231).

Reads every per-cell ``summary.json`` produced by ``check_determinism.sh``
(cells live at ``data/{prefix}_{gate}_{window}_{arm}_{gate}_determinism/summary.json``),
groups by (gate, window, arm), ENFORCES the within-window $0.00 determinism gate on
EVERY cell, then emits per-gate mean +/- spread for the absolute PnL (OFF/ON) and the
ON-OFF delta, plus per-window detail.

V232 vs V231: the only difference is ``--prefix`` (default ``v232``) so the same logic
serves the brake grid (ON = skew+brake, OFF = skew-only) without forking the algorithm.
The ``delta`` (ON-OFF) is the brake's MARGINAL Δ on top of the V227 skew. The V232
falsifier (ship iff mean-Δ>0 AND min-Δ>0) reads ``gates.crisis.delta.mean`` and
``gates.crisis.delta_all_windows_positive`` (the latter IS min-Δ>0).

Determinism gate: if ANY cell's verdict != PASS, the distributional verdict is BLOCKED
and the script exits non-zero (5).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys


def _arm_from_dir(dirname: str, gate: str, window: str, prefix: str) -> str:
    """Cell dir = {prefix}_{gate}_{window}_{arm}_{gate}_determinism. Strip the known
    prefix to recover the arm token deterministically (window labels are snapshot
    basenames, so a substring search for on/off would be ambiguous; this is not)."""
    pfx = f"{prefix}_{gate}_{window}_"
    rest = dirname[len(pfx):] if dirname.startswith(pfx) else dirname
    arm = rest.split("_", 1)[0]
    return arm if arm in ("on", "off") else "?"


def load_cells(root: str, prefix: str) -> list[dict]:
    cells = []
    patterns = [
        os.path.join(root, f"{prefix}_*_determinism", "summary.json"),
        os.path.join(root, f"{prefix}_dist", f"{prefix}_*_determinism", "summary.json"),
    ]
    seen = set()
    for pat in patterns:
        for sm in glob.glob(pat):
            rp = os.path.realpath(sm)
            if rp in seen:
                continue
            seen.add(rp)
            try:
                d = json.load(open(sm))
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: unreadable summary {sm}: {exc}", file=sys.stderr)
                continue
            d["_path"] = sm
            d["_dir"] = os.path.basename(os.path.dirname(sm))
            cells.append(d)
    return cells


def cell_pnl(c: dict) -> float:
    """Representative PnL = mean of the N replicates (byte-identical when PASS)."""
    return statistics.fmean(c["pnls"]) if c.get("pnls") else float("nan")


def _stats(xs: list[float]) -> dict | None:
    if not xs:
        return None
    return {
        "mean": statistics.fmean(xs),
        "spread": (max(xs) - min(xs)),
        "min": min(xs),
        "max": max(xs),
        "n": len(xs),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data", help="dir to glob for cell summaries (default: data)")
    ap.add_argument("--prefix", default="v232", help="cell version prefix (default: v232)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    cells = load_cells(args.root, args.prefix)
    if not cells:
        print(f"DIST-VERDICT: NO-CELLS — no {args.prefix}_*_determinism/summary.json found", file=sys.stderr)
        sys.exit(6)

    # 1) DETERMINISM GATE — every (window, cell, arm) must PASS independently.
    failed = [c for c in cells if c.get("verdict") != "PASS"]
    det_ok = not failed

    # 2) group by gate -> window -> arm
    gates: dict[str, dict[str, dict[str, float]]] = {}
    for c in cells:
        gate = c.get("gate", "?")
        window = c.get("window", "?")
        arm = _arm_from_dir(c["_dir"], gate, window, args.prefix)
        gates.setdefault(gate, {}).setdefault(window, {})[arm] = cell_pnl(c)

    report = {
        "determinism_gate": "PASS" if det_ok else "FAIL",
        "failed_cells": [c["_path"] for c in failed],
        "n_cells": len(cells),
        "gates": {},
    }
    for gate, wins in gates.items():
        per_window = []
        for w, arms in sorted(wins.items()):
            on = arms.get("on")
            off = arms.get("off")
            per_window.append({
                "window": w,
                "pnl_off": off,
                "pnl_on": on,
                "delta": (on - off) if (on is not None and off is not None) else None,
            })
        offs = [w["pnl_off"] for w in per_window if w["pnl_off"] is not None]
        ons = [w["pnl_on"] for w in per_window if w["pnl_on"] is not None]
        deltas = [w["delta"] for w in per_window if w["delta"] is not None]
        # V232 falsifier helper: brake ships iff mean-Δ>0 AND min-Δ>0 (= all windows +).
        delta_all_positive = bool(deltas) and all(d > 0 for d in deltas)
        report["gates"][gate] = {
            "n_windows": len(per_window),
            "pnl_off": _stats(offs),
            "pnl_on": _stats(ons),
            "delta": _stats(deltas),
            "delta_all_windows_positive": delta_all_positive,
            "per_window": per_window,
        }

    json.dump(report, open(args.out_json, "w"), indent=2)
    _write_md(report, args.out_md, args.prefix)
    print(
        "DIST-VERDICT:", report["determinism_gate"],
        "n_cells=", report["n_cells"],
        "— per-gate Δ means:",
        {g: (v["delta"] or {}).get("mean") for g, v in report["gates"].items()},
    )
    sys.exit(0 if det_ok else 5)


def _fmt(x) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _write_md(report: dict, path: str, prefix: str) -> None:
    L = [f"# {prefix.upper()} distributional eval — determinism gate: **{report['determinism_gate']}**",
         "", f"_{report['n_cells']} cells aggregated._",
         "", "_ON = V227 skew + RV-term-structure brake; OFF = V227 skew only. "
         "Δ = brake marginal on top of skew. Ship iff mean-Δ>0 AND min-Δ>0._", ""]
    if report["failed_cells"]:
        L += ["## ⛔ FAILED determinism cells (distributional verdict BLOCKED)", ""]
        L += [f"- `{p}`" for p in report["failed_cells"]] + [""]
    for gate, v in report["gates"].items():
        pos = "✅ all windows +" if v["delta_all_windows_positive"] else "⚠️ not all + (or n/a)"
        L += [f"## {gate}  (n_windows={v['n_windows']}, Δ {pos})", "",
              "| metric | mean | spread | min | max |", "|---|---:|---:|---:|---:|"]
        for key, lbl in (("pnl_off", "PnL OFF"), ("pnl_on", "PnL ON"), ("delta", "Δ (ON−OFF)")):
            s = v[key]
            if s:
                L.append(f"| {lbl} | {_fmt(s['mean'])} | {_fmt(s['spread'])} | {_fmt(s['min'])} | {_fmt(s['max'])} |")
        L += ["", "### per-window detail", "",
              "| window | PnL OFF | PnL ON | Δ |", "|---|---:|---:|---:|"]
        for w in v["per_window"]:
            L.append(f"| {w['window']} | {_fmt(w['pnl_off'])} | {_fmt(w['pnl_on'])} | {_fmt(w['delta'])} |")
        L.append("")
    open(path, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
