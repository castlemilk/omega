#!/usr/bin/env python3
"""V234 crisis SIZING-LAYER distributional aggregator (single-arm config cells vs baseline).

Clone of v233_dist_aggregate.py with the config label keyed off the V234 size-throttle
flags instead of the predemean site flags. Each config tests the EXISTING V227 crisis
gate as a SIZE throttle (downstream of the conviction deadband) at a different factor S.
The OFF/standing-main baseline (V227 skew, post_demean, W=0.2) is REUSED from a prior
grid's distribution.json (default ``data/v232_dist/distribution.json``'s ``pnl_off`` per
window) rather than re-run.

For each config × window:  Δ = pnl(config) − pnl_baseline(window).

The config label is derived from each cell's ``features`` JSON:
  - not crisis_size_throttle_enabled  → ``baseline``
  - else                              → ``throttle_s{S}``

V234 falsifier read (the brief): the binding window is snap_crisis_2024aug. The
deadband-break criterion is that the 2024aug ledger ACTUALLY CHANGES — Δ != 0 (no
composite-additive change ever achieved this in 7 versions). A throttle "wins" (branch 1)
iff its 2024aug Δ moves off $0.00 in the LOSS-REDUCING direction (Δ > 0, loss is negative
PnL) AND 2020q1/2022h1 are NOT regressed below their OFF baselines (min non-binding Δ ≥ 0).
We emit per config: 2024aug Δ, whether the binding ledger CHANGED (deadband broken),
min non-binding Δ, and mean-Δ. Determinism gate (every cell PASS) enforced as V231/V232/V233.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys


def _config_label(features_raw) -> str:
    """Derive the V234 config label from a cell's stored ``features`` JSON string."""
    try:
        f = json.loads(features_raw) if isinstance(features_raw, str) else dict(features_raw or {})
    except Exception:
        return "?"
    if not bool(f.get("crisis_size_throttle_enabled", False)):
        return "baseline"
    s = float(f.get("crisis_size_throttle", 1.0) if f.get("crisis_size_throttle") is not None else 1.0)
    return f"throttle_s{s:g}"


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


def cell_trades(c: dict) -> float:
    """Representative trade count = mean of the N replicates (identical when PASS)."""
    return statistics.fmean(c["trades"]) if c.get("trades") else float("nan")


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


def load_baseline(path: str, gate: str) -> dict[str, dict]:
    """Return {window: {pnl, trades}} from a prior grid's distribution.json for the gate."""
    try:
        d = json.load(open(path))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot read baseline {path}: {exc}", file=sys.stderr)
        return {}
    g = d.get("gates", {}).get(gate, {})
    out: dict[str, dict] = {}
    for w in g.get("per_window", []):
        if w.get("pnl_off") is not None:
            out[w["window"]] = {"pnl": float(w["pnl_off"]), "trades": w.get("trades_off")}
    return out


# Windows that DEFINE the binding crisis falsifier vs the non-binding ones.
_BINDING_WINDOW = "snap_crisis_2024aug"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data")
    ap.add_argument("--prefix", default="v234")
    ap.add_argument("--baseline", default="data/v232_dist/distribution.json",
                    help="prior distribution.json whose pnl_off is the V227-skew standing-main baseline")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    cells = load_cells(args.root, args.prefix)
    if not cells:
        print(f"DIST-VERDICT: NO-CELLS — no {args.prefix}_*_determinism/summary.json", file=sys.stderr)
        sys.exit(6)

    failed = [c for c in cells if c.get("verdict") != "PASS"]
    det_ok = not failed

    # group: gate -> config -> window -> {pnl, trades}
    gates: dict[str, dict[str, dict[str, dict]]] = {}
    for c in cells:
        gate = c.get("gate", "?")
        window = c.get("window", "?")
        cfg = _config_label(c.get("features"))
        gates.setdefault(gate, {}).setdefault(cfg, {})[window] = {
            "pnl": cell_pnl(c), "trades": cell_trades(c)
        }

    report = {
        "determinism_gate": "PASS" if det_ok else "FAIL",
        "failed_cells": [c["_path"] for c in failed],
        "n_cells": len(cells),
        "baseline_source": args.baseline,
        "gates": {},
    }
    for gate, configs in gates.items():
        baseline = load_baseline(args.baseline, gate)
        report["gates"][gate] = {
            "baseline": {w: b["pnl"] for w, b in baseline.items()},
            "configs": {},
        }
        for cfg, wins in sorted(configs.items()):
            per_window = []
            for w in sorted(wins):
                pnl = wins[w]["pnl"]
                tr = wins[w]["trades"]
                base = baseline.get(w, {})
                base_pnl = base.get("pnl")
                base_tr = base.get("trades")
                per_window.append({
                    "window": w,
                    "pnl": pnl,
                    "trades": tr,
                    "baseline": base_pnl,
                    "baseline_trades": base_tr,
                    "delta": (pnl - base_pnl) if (pnl is not None and base_pnl is not None) else None,
                    "delta_trades": (
                        (tr - base_tr) if (tr is not None and base_tr is not None) else None
                    ),
                })
            deltas = [w["delta"] for w in per_window if w["delta"] is not None]
            binding = next((w for w in per_window if w["window"] == _BINDING_WINDOW), None)
            nonbind_deltas = [
                w["delta"] for w in per_window
                if w["window"] != _BINDING_WINDOW and w["delta"] is not None
            ]
            binding_delta = binding["delta"] if binding else None
            binding_dtrades = binding["delta_trades"] if binding else None
            # Deadband-break criterion (V234 pre-reg): the binding ledger ACTUALLY CHANGED
            # (Δpnl != 0 OR Δtrades != 0). This is the thing no composite-additive change
            # achieved in 7 versions. Branch 1 (ship) additionally needs loss-reducing +
            # no non-binding regression.
            binding_changed = bool(
                (binding_delta is not None and abs(binding_delta) > 0.0)
                or (binding_dtrades is not None and binding_dtrades != 0)
            )
            throttle_wins = bool(
                binding_delta is not None and binding_delta > 0
                and nonbind_deltas and min(nonbind_deltas) >= 0
            )
            report["gates"][gate]["configs"][cfg] = {
                "delta": _stats(deltas),
                "binding_window": _BINDING_WINDOW,
                "binding_delta": binding_delta,
                "binding_delta_trades": binding_dtrades,
                "binding_ledger_changed": binding_changed,
                "nonbinding_min_delta": (min(nonbind_deltas) if nonbind_deltas else None),
                "delta_all_windows_positive": bool(deltas) and all(d > 0 for d in deltas),
                "throttle_wins": throttle_wins,
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
        "— ledger-changed:",
        {
            cfg: cv["binding_ledger_changed"]
            for g, gv in report["gates"].items()
            for cfg, cv in gv["configs"].items()
        },
    )
    sys.exit(0 if det_ok else 5)


def _fmt(x) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _fmt_dt(x) -> str:
    return f"{x:+g}" if x is not None else "—"


def _write_md(report: dict, path: str, prefix: str) -> None:
    L = [f"# {prefix.upper()} crisis SIZING-LAYER eval — determinism gate: **{report['determinism_gate']}**",
         "", f"_{report['n_cells']} cells aggregated. Baseline (V227 skew standing-main, "
         f"post_demean_w0.2) from `{report['baseline_source']}`._",
         "", "_Each config tests the V227 drawdown gate as a SIZE THROTTLE (downstream of the "
         "conviction deadband). Δ = config PnL − baseline PnL per window. **Deadband-break "
         "criterion**: binding window (snap_crisis_2024aug) ledger CHANGES (Δpnl≠0 or Δtrades≠0) "
         "— no composite-additive change achieved this in 7 versions. Branch-1 (ship): binding "
         "Δ>0 (loss-reducing) AND no non-binding window regressed (min Δ≥0)._", ""]
    if report["failed_cells"]:
        L += ["## ⛔ FAILED determinism cells (distributional verdict BLOCKED)", ""]
        L += [f"- `{p}`" for p in report["failed_cells"]] + [""]
    for gate, gv in report["gates"].items():
        L += [f"## {gate}", "",
              "| config | 2024aug Δ (binding) | Δtrades | ledger changed? | nonbinding min Δ | mean Δ | throttle wins? |",
              "|---|---:|---:|:--:|---:|---:|:--:|"]
        for cfg, cv in gv["configs"].items():
            won = "✅" if cv["throttle_wins"] else "—"
            changed = "✅" if cv["binding_ledger_changed"] else "—"
            mean_d = (cv["delta"] or {}).get("mean")
            L.append(
                f"| {cfg} | {_fmt(cv['binding_delta'])} | {_fmt_dt(cv['binding_delta_trades'])} "
                f"| {changed} | {_fmt(cv['nonbinding_min_delta'])} | {_fmt(mean_d)} | {won} |"
            )
        L += [""]
        for cfg, cv in gv["configs"].items():
            L += [f"### {cfg} — per-window detail", "",
                  "| window | config PnL | baseline PnL | Δ | config trades | baseline trades | Δtrades |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
            for w in cv["per_window"]:
                L.append(
                    f"| {w['window']} | {_fmt(w['pnl'])} | {_fmt(w['baseline'])} | {_fmt(w['delta'])} "
                    f"| {w.get('trades')} | {w.get('baseline_trades')} | {_fmt_dt(w.get('delta_trades'))} |"
                )
            L += [""]
    open(path, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
