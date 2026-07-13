#!/usr/bin/env python3
"""V246 $0 offline exit-rule counterfactual scorer.

Scores per-trade exit transforms on the EXISTING V240 confirm ledgers
(32 windows, universe_selective) using the mae/mfe dollar-extreme columns:

  A. Hard MAE stop:    mae <= -theta*size          -> pnl' = -theta*size
  B. MFE trailing lock: mfe >= m*size and rule binds -> pnl' = max(pnl, (1-r)*mfe)
  C. A+B combined (top-2 A x top-2 B by pooled p25 delta)
  D. Regime-conditional variants of the best pooled cell

Per-trade transforms; subsequent trades held fixed (no re-entry modeling).
Family B is optimistic (ignores gap-through); recorded as such.

Sanity gate (pre-registered, V246.md): >=1 cell pooled p25-D > +$100 AND
recent mean-D > +$100; B-only passes are upper-bound-only and need an A-or-C
cell within 50% of the bar.

Usage: python3 scripts/v246_exit_scorer.py \
          --audit-root /Volumes/gamma-systems-2/omega-victoria-data \
          --out-json <path>
"""

import argparse
import csv
import json
import math
import os
import sys

THETAS = [0.01, 0.02, 0.03, 0.05]
LOCKS = [(m, r) for m in (0.01, 0.02, 0.03) for r in (0.25, 0.5)]


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def load_ledgers(audit_root, manifest_path):
    windows = []
    for w in json.load(open(manifest_path))["windows"]:
        wid, regime = w["id"], w["regime"]
        path = os.path.join(
            audit_root,
            f"v240wf_{wid}_universe_selective_{regime}_determinism",
            f"v240wf_{wid}_universe_selective_{regime}_r1_trades.csv",
        )
        if not os.path.exists(path):
            print(f"FATAL: missing {path}", file=sys.stderr)
            sys.exit(2)
        trades = []
        with open(path) as f:
            for row in csv.DictReader(f):
                trades.append(
                    {
                        "pnl": float(row["pnl"]),
                        "size": float(row["size"]),
                        "mae": float(row["mae"]) if row["mae"] else 0.0,
                        "mfe": float(row["mfe"]) if row["mfe"] else 0.0,
                        "regime": regime,
                    }
                )
        windows.append({"id": wid, "regime": regime, "trades": trades})
    return windows


def transform(t, rule):
    """Return (pnl', fired) under rule dict."""
    pnl = t["pnl"]
    fired = False
    kind = rule["kind"]
    if kind in ("A", "C", "D"):
        theta = rule.get("theta")
        if theta is not None and t["mae"] <= -theta * t["size"]:
            # stop binds: loss capped at stop level
            pnl = -theta * t["size"]
            fired = True
            return pnl, fired  # stopped out; lock can't also apply
    if kind in ("B", "C", "D"):
        m, r = rule.get("m"), rule.get("r")
        if m is not None and t["mfe"] >= m * t["size"]:
            locked = (1.0 - r) * t["mfe"]
            if locked > pnl:
                pnl = locked
                fired = True
    return pnl, fired


def score(windows, rule, regimes_applied=None):
    window_pnls = []
    n_trades = n_fired = 0
    for w in windows:
        tot = 0.0
        for t in w["trades"]:
            n_trades += 1
            if regimes_applied and t["regime"] not in regimes_applied:
                tot += t["pnl"]
                continue
            pnl, fired = transform(t, rule)
            tot += pnl
            n_fired += fired
        window_pnls.append((w["regime"], tot))
    stats = {}
    for reg in ("crisis", "trend", "recent", "pooled"):
        vals = [v for r, v in window_pnls if reg == "pooled" or r == reg]
        stats[reg] = {
            "n": len(vals),
            "mean": math.fsum(vals) / len(vals),
            "p25": percentile(vals, 25),
            "p50": percentile(vals, 50),
            "p75": percentile(vals, 75),
        }
    return stats, n_fired / n_trades if n_trades else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", default=os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "data"))
    ap.add_argument("--manifest", default="data/walk_forward_manifest.json")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    windows = load_ledgers(args.audit_root, args.manifest)
    base_stats, _ = score(windows, {"kind": "B", "m": None, "r": None})

    def delta(st):
        return {
            reg: {k: st[reg][k] - base_stats[reg][k] for k in ("mean", "p25", "p50", "p75")}
            for reg in st
        }

    cells = []

    def add(label, rule, regimes=None):
        st, fire = score(windows, rule, regimes)
        d = delta(st)
        cells.append(
            {
                "label": label,
                "rule": {k: v for k, v in rule.items()},
                "regimes_applied": regimes,
                "fire_rate": fire,
                "delta": d,
                "gate": d["pooled"]["p25"] > 100.0 and d["recent"]["mean"] > 100.0,
            }
        )
        return cells[-1]

    for th in THETAS:
        add(f"A.stop{int(th*100)}pct", {"kind": "A", "theta": th})
    for m, r in LOCKS:
        add(f"B.lock_m{int(m*100)}_r{int(r*100)}", {"kind": "B", "m": m, "r": r})

    a_cells = sorted(
        [c for c in cells if c["label"].startswith("A.")],
        key=lambda c: -c["delta"]["pooled"]["p25"],
    )[:2]
    b_cells = sorted(
        [c for c in cells if c["label"].startswith("B.")],
        key=lambda c: -c["delta"]["pooled"]["p25"],
    )[:2]
    for ac in a_cells:
        for bc in b_cells:
            add(
                f"C.{ac['label']}+{bc['label']}",
                {
                    "kind": "C",
                    "theta": ac["rule"]["theta"],
                    "m": bc["rule"]["m"],
                    "r": bc["rule"]["r"],
                },
            )

    best = max(cells, key=lambda c: c["delta"]["pooled"]["p25"])
    for regs, tag in (
        (("crisis",), "crisis_only"),
        (("recent",), "recent_only"),
        (("crisis", "recent"), "non_trend"),
    ):
        add(f"D.{best['label']}~{tag}", {**best["rule"], "kind": "D"}, list(regs))

    survivors = [c for c in cells if c["gate"]]
    a_or_c_near = [
        c
        for c in cells
        if (c["label"].startswith(("A.", "C.")) or (c.get("regimes_applied") and not c["rule"].get("m")))
        and c["delta"]["pooled"]["p25"] > 50.0
        and c["delta"]["recent"]["mean"] > 50.0
    ]
    b_only = survivors and all(c["label"].startswith(("B.", "D.B")) for c in survivors)
    verdict = "PASS" if survivors and not (b_only and not a_or_c_near) else (
        "PASS_UPPER_BOUND_ONLY_BLOCKED" if survivors else "REFUTED_AT_SCORING"
    )

    out = {
        "version": "v246_exit_scorer",
        "baseline": base_stats,
        "cells": cells,
        "survivors": [c["label"] for c in survivors],
        "b_only_pass": bool(b_only),
        "verdict": verdict,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=1)

    print("=== V246 offline exit scorer ===")
    print(
        f"{'cell':<34}{'fire%':>7}{'poolΔp25':>10}{'poolΔmean':>10}{'recΔmean':>10}"
        f"{'recΔp25':>10}{'trnΔmean':>10}{'crsΔmean':>10} gate"
    )
    for c in cells:
        d = c["delta"]
        print(
            f"{c['label']:<34}{c['fire_rate']*100:>6.1f}%"
            f"{d['pooled']['p25']:>10.0f}{d['pooled']['mean']:>10.0f}"
            f"{d['recent']['mean']:>10.0f}{d['recent']['p25']:>10.0f}"
            f"{d['trend']['mean']:>10.0f}{d['crisis']['mean']:>10.0f}"
            f"  {'PASS' if c['gate'] else '-'}"
        )
    print(f"VERDICT: {verdict}  survivors={out['survivors']}")


if __name__ == "__main__":
    main()
