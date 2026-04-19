#!/usr/bin/env python3
"""
scripts/run_sensitivity_test.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Parameter sensitivity test for the continuous confidence surface (V143).

Tests the core architectural claim from adaptive-engine-v2.md §2.4:
    With hard gates, varying bear_prob center 0.30→0.60 causes ~$30k PnL swing.
    With sigmoid surfaces (T=0.10), the same sweep should produce <$10k swing.
    With T=0.15, <$7k. With T=0.20, <$5k (target).

Usage
-----
    # Sensitivity test on V141 crisis trades (hard-gate baseline):
    python3 scripts/run_sensitivity_test.py \\
        --trades data/bt_v141_crisis_trades.csv \\
        --direction long

    # Multiple snapshots:
    python3 scripts/run_sensitivity_test.py \\
        --trades data/bt_v141_crisis_trades.csv data/bt_v141_trend_trades.csv \\
        --direction long

    # Custom center range and temperatures:
    python3 scripts/run_sensitivity_test.py \\
        --trades data/bt_v141_crisis_trades.csv \\
        --centers 0.30 0.35 0.40 0.45 0.50 0.55 0.60 \\
        --temperatures 0.05 0.10 0.15 0.20 \\
        --out data/sensitivity_v141_crisis.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.nodes.victoria.confidence_surface import ConfidenceSurface, SurfaceConfig, SurfaceParams


def load_trades(csv_path: str) -> list[dict]:
    try:
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        # Deduplicate header rows (some CSVs have duplicate header lines)
        rows = [r for r in rows if r.get("cycle", "") != "cycle"]
        return rows
    except FileNotFoundError:
        print(f"  Warning: {csv_path} not found, skipping", file=sys.stderr)
        return []


def run_sensitivity(
    trades: list[dict],
    centers: list[float],
    temperatures: list[float],
    direction: str,
    label: str = "",
) -> dict:
    """
    Run sensitivity sweep and return result dict.

    Returns
    -------
    dict with keys:
        hard_gate_pnl, hard_gate_sensitivity
        sigmoid_pnl_by_temp, sigmoid_sensitivity_by_temp
        best_sigmoid_sensitivity, target_met, reduction_factor
    """
    surface = ConfidenceSurface()
    side_trades = [t for t in trades if str(t.get("side", "")).lower() == direction]
    n = len(side_trades)

    if not side_trades:
        return {"error": f"No {direction} trades in {label}"}

    # ── Hard gate baseline ──
    hard_pnl: dict[float, float] = {}
    for center in centers:
        total = 0.0
        for t in side_trades:
            bp = float(t.get("bear_prob") or t.get("_regime_w_bear_prob") or 0.30)
            pnl = float(t.get("pnl", 0))
            if direction == "long":
                if bp < center:
                    total += pnl
            else:
                if bp > center:
                    total += pnl
        hard_pnl[center] = round(total, 2)

    hard_range = max(hard_pnl.values()) - min(hard_pnl.values())

    # ── Sigmoid surfaces ──
    sigmoid_by_temp: dict[float, dict[float, float]] = {}
    for T in temperatures:
        pnl_by_center: dict[float, float] = {}
        for center in centers:
            if direction == "long":
                cfg = SurfaceConfig(
                    bear_long=SurfaceParams(center=center, temperature=T)
                )
            else:
                cfg = SurfaceConfig(
                    bear_short=SurfaceParams(center=center, temperature=T)
                )
            surf = ConfidenceSurface(cfg)
            total = 0.0
            for t in side_trades:
                bp = float(t.get("bear_prob") or t.get("_regime_w_bear_prob") or 0.30)
                comp = float(t.get("composite") or t.get("_composite") or 0.10)
                regime = str(t.get("regime") or "normal")
                pnl = float(t.get("pnl", 0))
                llm_mod = float(t.get("llm_modifier") or t.get("_llm_modifier") or 1.0)

                if direction == "long":
                    r = surf.evaluate_long(bp, comp, regime, llm_mod)
                else:
                    r = surf.evaluate_short(bp, comp, regime, llm_mod)

                total += pnl * r.confidence

            pnl_by_center[center] = round(total, 2)
        sigmoid_by_temp[T] = pnl_by_center

    sigmoid_ranges = {
        T: round(max(g.values()) - min(g.values()), 2)
        for T, g in sigmoid_by_temp.items()
    }
    best_T = min(sigmoid_ranges, key=sigmoid_ranges.get)
    best_range = sigmoid_ranges[best_T]
    reduction = round(hard_range / max(best_range, 1.0), 2)

    return {
        "label": label,
        "direction": direction,
        "n_trades": n,
        "centers_tested": centers,
        "temperatures_tested": temperatures,
        "hard_gate_pnl": hard_pnl,
        "hard_gate_sensitivity": round(hard_range, 2),
        "sigmoid_pnl_by_temp": sigmoid_by_temp,
        "sigmoid_sensitivity_by_temp": sigmoid_ranges,
        "best_sigmoid_T": best_T,
        "best_sigmoid_sensitivity": best_range,
        "target_met": best_range < 5000.0,
        "reduction_factor": reduction,
    }


def print_result(result: dict) -> None:
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    print(f"\n{'='*70}")
    print(f"  {result['label']} ({result['direction']} trades, n={result['n_trades']})")
    print(f"{'='*70}")

    print(f"\n  Hard gate sensitivity: ${result['hard_gate_sensitivity']:>+10,.0f}")
    print(f"  {'Center':<8}", end="")
    for c in result["centers_tested"]:
        print(f"  {c:.2f}", end="")
    print()
    print(f"  {'HardGate':<8}", end="")
    for c in result["centers_tested"]:
        pnl = result["hard_gate_pnl"][c]
        print(f"  {pnl:+6,.0f}"[:7], end="")
    print()

    print(f"\n  Sigmoid sensitivity by temperature:")
    print(f"  {'T':<8} {'Range':>12} {'vs Hard':>10} {'Target?':>10}")
    for T in result["temperatures_tested"]:
        rng = result["sigmoid_sensitivity_by_temp"][T]
        ratio = result["hard_gate_sensitivity"] / max(rng, 1)
        target = "✓ YES" if rng < 5000 else "✗ NO"
        print(f"  {T:<8.2f} ${rng:>+10,.0f} {ratio:>9.1f}× {target:>10}")

    best_T = result["best_sigmoid_T"]
    best_rng = result["best_sigmoid_sensitivity"]
    print(f"\n  Best: T={best_T} → sensitivity=${best_rng:+,.0f}  ({result['reduction_factor']}× reduction)")
    print(f"  Target (<$5,000): {'MET ✓' if result['target_met'] else 'NOT MET ✗'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameter sensitivity test for V143")
    parser.add_argument("--trades", nargs="+", required=True, help="Trades CSV paths")
    parser.add_argument(
        "--direction", choices=["long", "short", "both"], default="long"
    )
    parser.add_argument(
        "--centers",
        nargs="+",
        type=float,
        default=[0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60],
    )
    parser.add_argument(
        "--temperatures",
        nargs="+",
        type=float,
        default=[0.05, 0.10, 0.15, 0.20],
    )
    parser.add_argument("--out", type=str, default=None, help="Save JSON results")
    args = parser.parse_args()

    directions = (
        ["long", "short"] if args.direction == "both" else [args.direction]
    )

    all_results = []
    for csv_path in args.trades:
        trades = load_trades(csv_path)
        if not trades:
            continue
        label = Path(csv_path).stem
        for direction in directions:
            result = run_sensitivity(
                trades, args.centers, args.temperatures, direction, label=label
            )
            print_result(result)
            all_results.append(result)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_results, indent=2, default=str))
        print(f"\n  Results saved → {args.out}")


if __name__ == "__main__":
    main()
