#!/usr/bin/env python3
"""V233 application-SITE distributional aggregator (single-arm config cells vs baseline).

Unlike V231/V232 (which pair on/off arms WITHIN the same grid), V233 cells are
single-arm CONFIGS — each tests the V227 crisis-skew probe under a different
application SITE (post_demean / pre_demean / pre_demean_common_mode) and gated weight.
The OFF/standing-main baseline (post_demean, W=0.2) is REUSED from a prior grid's
distribution.json (default ``data/v232_dist/distribution.json``'s ``pnl_off`` per
window) rather than re-run, so we don't burn ~4h re-measuring the incumbent.

For each config × window:  Δ = pnl(config) − pnl_baseline(window).

The config label is derived from each cell's ``features`` JSON (NOT the dir name —
pre-demean config tokens contain underscores/dots that break positional parsing):
  - not predemean_enabled OR mode == 'post_demean'  → ``post_demean_w{w}``
  - else                                            → ``{mode}_w{w}``

V233 falsifier read (the brief): the binding window is snap_crisis_2024aug. A site fix
"works" iff its 2024aug Δ moves off $0.00 in the LOSS-REDUCING direction (Δ > 0, since
loss is negative PnL) AND 2020q1/2022h1 are NOT regressed below their OFF baselines
(Δ ≥ 0 there). Per config we emit: 2024aug Δ, min-Δ over the non-binding windows, and
mean-Δ. Determinism gate (every cell PASS) is enforced exactly as V231/V232.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys


def _config_label(features_raw) -> str:
    """Derive the V233 config label from a cell's stored ``features`` JSON string."""
    try:
        f = json.loads(features_raw) if isinstance(features_raw, str) else dict(features_raw or {})
    except Exception:
        return "?"
    enabled = bool(f.get("crisis_term_predemean_enabled", False))
    mode = str(f.get("crisis_term_predemean_mode", "post_demean") or "post_demean")
    w = float(f.get("crisis_term_gated_weight", 0.2) or 0.2)
    site = mode if (enabled and mode in ("pre_demean", "pre_demean_common_mode")) else "post_demean"
    return f"{site}_w{w:g}"


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


def load_baseline(path: str, gate: str) -> dict[str, float]:
    """Return {window: pnl_off} from a prior grid's distribution.json for the gate."""
    try:
        d = json.load(open(path))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot read baseline {path}: {exc}", file=sys.stderr)
        return {}
    g = d.get("gates", {}).get(gate, {})
    out = {}
    for w in g.get("per_window", []):
        if w.get("pnl_off") is not None:
            out[w["window"]] = float(w["pnl_off"])
    return out


# Windows that DEFINE the binding crisis falsifier vs the non-binding ones.
_BINDING_WINDOW = "snap_crisis_2024aug"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data")
    ap.add_argument("--prefix", default="v233")
    ap.add_argument("--baseline", default="data/v232_dist/distribution.json",
                    help="prior distribution.json whose pnl_off is the post_demean_w0.2 baseline")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    cells = load_cells(args.root, args.prefix)
    if not cells:
        print(f"DIST-VERDICT: NO-CELLS — no {args.prefix}_*_determinism/summary.json", file=sys.stderr)
        sys.exit(6)

    failed = [c for c in cells if c.get("verdict") != "PASS"]
    det_ok = not failed

    # group: gate -> config -> window -> pnl
    gates: dict[str, dict[str, dict[str, float]]] = {}
    for c in cells:
        gate = c.get("gate", "?")
        window = c.get("window", "?")
        cfg = _config_label(c.get("features"))
        gates.setdefault(gate, {}).setdefault(cfg, {})[window] = cell_pnl(c)

    report = {
        "determinism_gate": "PASS" if det_ok else "FAIL",
        "failed_cells": [c["_path"] for c in failed],
        "n_cells": len(cells),
        "baseline_source": args.baseline,
        "gates": {},
    }
    for gate, configs in gates.items():
        baseline = load_baseline(args.baseline, gate)
        report["gates"][gate] = {"baseline": baseline, "configs": {}}
        for cfg, wins in sorted(configs.items()):
            per_window = []
            for w in sorted(wins):
                pnl = wins[w]
                base = baseline.get(w)
                per_window.append({
                    "window": w,
                    "pnl": pnl,
                    "baseline": base,
                    "delta": (pnl - base) if (pnl is not None and base is not None) else None,
                })
            deltas = [w["delta"] for w in per_window if w["delta"] is not None]
            binding = next((w for w in per_window if w["window"] == _BINDING_WINDOW), None)
            nonbind_deltas = [
                w["delta"] for w in per_window
                if w["window"] != _BINDING_WINDOW and w["delta"] is not None
            ]
            binding_delta = binding["delta"] if binding else None
            # Falsifier branch-1 condition: binding Δ>0 (loss-reducing) AND no non-binding
            # window regressed below its OFF baseline (min non-binding Δ ≥ 0).
            site_fix_wins = bool(
                binding_delta is not None and binding_delta > 0
                and nonbind_deltas and min(nonbind_deltas) >= 0
            )
            report["gates"][gate]["configs"][cfg] = {
                "delta": _stats(deltas),
                "binding_window": _BINDING_WINDOW,
                "binding_delta": binding_delta,
                "nonbinding_min_delta": (min(nonbind_deltas) if nonbind_deltas else None),
                "delta_all_windows_positive": bool(deltas) and all(d > 0 for d in deltas),
                "site_fix_wins": site_fix_wins,
                "per_window": per_window,
            }

    json.dump(report, open(args.out_json, "w"), indent=2)
    _write_md(report, args.out_md, args.prefix)
    print(
        "DIST-VERDICT:", report["determinism_gate"], "n_cells=", report["n_cells"],
        "— binding(2024aug) Δ by config:",
        {
            cfg: cv["binding_delta"]
            for g, gv in report["gates"].items()
            for cfg, cv in gv["configs"].items()
        },
    )
    sys.exit(0 if det_ok else 5)


def _fmt(x) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _write_md(report: dict, path: str, prefix: str) -> None:
    L = [f"# {prefix.upper()} application-SITE eval — determinism gate: **{report['determinism_gate']}**",
         "", f"_{report['n_cells']} cells aggregated. Baseline (post_demean_w0.2 = V227 skew "
         f"standing-main) from `{report['baseline_source']}`._",
         "", "_Each config tests the V227 skew PROBE under a different application site/weight. "
         "Δ = config PnL − baseline PnL per window. Falsifier branch-1: binding window "
         "(snap_crisis_2024aug) Δ>0 (loss-reducing) AND no non-binding window regressed (min Δ≥0)._", ""]
    if report["failed_cells"]:
        L += ["## ⛔ FAILED determinism cells (distributional verdict BLOCKED)", ""]
        L += [f"- `{p}`" for p in report["failed_cells"]] + [""]
    for gate, gv in report["gates"].items():
        L += [f"## {gate}", "",
              "| config | 2024aug Δ (binding) | nonbinding min Δ | mean Δ | site-fix wins? |",
              "|---|---:|---:|---:|:--:|"]
        for cfg, cv in gv["configs"].items():
            won = "✅" if cv["site_fix_wins"] else "—"
            mean_d = (cv["delta"] or {}).get("mean")
            L.append(
                f"| {cfg} | {_fmt(cv['binding_delta'])} | {_fmt(cv['nonbinding_min_delta'])} "
                f"| {_fmt(mean_d)} | {won} |"
            )
        L += [""]
        for cfg, cv in gv["configs"].items():
            L += [f"### {cfg} — per-window detail", "",
                  "| window | config PnL | baseline PnL | Δ |", "|---|---:|---:|---:|"]
            for w in cv["per_window"]:
                L.append(f"| {w['window']} | {_fmt(w['pnl'])} | {_fmt(w['baseline'])} | {_fmt(w['delta'])} |")
            L += [""]
    open(path, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
