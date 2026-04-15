#!/usr/bin/env python3
"""
scripts/run_leaderboard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compute the Phase A leaderboard across all benchmark runs.

Reads all data/benchmarks/*.json scorecards and produces a ranked comparison
table. Also accepts explicit version list + snapshot args to run training
first (optional).

Usage:
    # Just rank existing scorecards:
    python3 scripts/run_leaderboard.py

    # Rank with explicit filter:
    python3 scripts/run_leaderboard.py --prefix bt_

    # Output to file:
    python3 scripts/run_leaderboard.py --out data/benchmarks/leaderboard.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
BENCHMARKS_DIR = DATA_DIR / "benchmarks"

# ---------------------------------------------------------------------------
# Config labels → canonical name mapping
# ---------------------------------------------------------------------------

# Maps version prefix → config label for grouping
_CONFIG_LABELS = {
    "bt_v93":   "v93_baseline",
    "bt_v112":  "v112_evidence_based",
    "bt_v115":  "v115_full_vectors",
    "bt_v122":  "v122_guardrail",
    "bt_v127":  "v127_live",
    "bt_v128":  "v128_exit_v1",
    "bt_v129t": "v129_trail_tight",
    "bt_v129m": "v129_trail_moderate",
    "bt_v129l": "v129_trail_loose",
    "bt_v130":  "v130_high_vol_gate",
}

_SNAPSHOT_LABELS = {
    "recent": "snap_recent (mixed, 2026)",
    "trend":  "snap_trending (bull, Q4-2023)",
    "crisis": "snap_crisis (bear, H1-2022)",
}


def load_scorecards(prefix: str = "") -> list[dict]:
    scorecards = []
    for path in sorted(BENCHMARKS_DIR.glob("*.json")):
        if path.name == "scorecard_schema.json":
            continue
        if prefix and not path.stem.startswith(prefix):
            continue
        try:
            sc = json.loads(path.read_text())
            sc["_path"] = str(path)
            scorecards.append(sc)
        except Exception as exc:
            print(f"  Warning: skipping {path.name}: {exc}", file=sys.stderr)
    return scorecards


def infer_config_snapshot(version: str) -> tuple[str, str]:
    """Infer config label and snapshot label from version string like bt_v93_recent."""
    config = "unknown"
    snapshot = "unknown"
    for prefix, label in _CONFIG_LABELS.items():
        if version.startswith(prefix):
            config = label
            suffix = version[len(prefix):].lstrip("_")
            snapshot = _SNAPSHOT_LABELS.get(suffix, suffix)
            break
    return config, snapshot


def rank_scorecards(scorecards: list[dict]) -> list[dict]:
    """
    Aggregate leaderboard score = PnL rank + PF rank + Sharpe rank (lower = better),
    summed across all snapshots for the same config.

    Returns list of dicts with config, per-snapshot metrics, aggregate score.
    """
    # Group by config
    by_config: dict[str, list[dict]] = {}
    for sc in scorecards:
        config, snapshot = infer_config_snapshot(sc["version"])
        if config not in by_config:
            by_config[config] = []
        by_config[config].append({"snapshot": snapshot, "sc": sc})

    # For each metric, rank configs (lower rank = better for all)
    # Collect per-config aggregate metrics
    configs: list[dict] = []
    for config, entries in by_config.items():
        row: dict = {"config": config, "snapshots": {}, "n_snapshots": len(entries)}
        total_pnl = 0.0
        total_pf = 0.0
        total_sharpe = 0.0
        n_sharpe = 0
        all_passed = True
        for e in entries:
            sc = e["sc"]
            m = sc.get("metrics", {})
            snap = e["snapshot"]
            row["snapshots"][snap] = {
                "pnl": m.get("pnl", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "profit_factor": m.get("profit_factor", 0.0),
                "n_trades": m.get("n_trades", 0),
                "long_pct": m.get("long_pct", 0.0),
                "sharpe": m.get("sharpe"),
                "hold_ratio": m.get("hold_ratio"),
                "disposition_coefficient": m.get("disposition_coefficient"),
                "passed": sc.get("gate_result", {}).get("passed", False),
                "failures": sc.get("gate_result", {}).get("failure_reasons", []),
            }
            total_pnl += m.get("pnl", 0.0)
            total_pf += m.get("profit_factor", 0.0)
            sh = m.get("sharpe")
            if sh is not None:
                total_sharpe += sh
                n_sharpe += 1
            if not sc.get("gate_result", {}).get("passed", False):
                all_passed = False

        row["agg_pnl"] = round(total_pnl, 2)
        row["agg_pf"] = round(total_pf / max(1, len(entries)), 4)
        row["agg_sharpe"] = round(total_sharpe / max(1, n_sharpe), 3) if n_sharpe else None
        row["all_passed"] = all_passed
        configs.append(row)

    # Rank by aggregate PnL (descending), then PF, then Sharpe
    configs.sort(key=lambda r: (
        -r["agg_pnl"],
        -r["agg_pf"],
        -(r["agg_sharpe"] or -99),
    ))
    for rank, row in enumerate(configs, 1):
        row["leaderboard_rank"] = rank

    return configs


def print_leaderboard(configs: list[dict]) -> None:
    print()
    print("=" * 90)
    print("  Phase A Benchmark Leaderboard")
    print("=" * 90)
    print(f"  {'Rank':<5} {'Config':<30} {'Agg PnL':>10} {'Avg PF':>8} {'Avg Sharpe':>12} {'Gates':<8}")
    print(f"  {'-'*5} {'-'*30} {'-'*10} {'-'*8} {'-'*12} {'-'*8}")
    for row in configs:
        passed = "ALL PASS" if row["all_passed"] else f"{sum(1 for s in row['snapshots'].values() if s['passed'])}/{row['n_snapshots']} pass"
        sharpe_str = f"{row['agg_sharpe']:.3f}" if row["agg_sharpe"] is not None else "  N/A"
        print(f"  {row['leaderboard_rank']:<5} {row['config']:<30} ${row['agg_pnl']:>+9,.0f} {row['agg_pf']:>8.3f} {sharpe_str:>12} {passed:<8}")

    print()
    print("-" * 90)
    print("  Per-snapshot breakdown:")
    print()
    for row in configs:
        print(f"  [{row['leaderboard_rank']}] {row['config']}")
        for snap, m in sorted(row["snapshots"].items()):
            gate_str = "PASS" if m["passed"] else f"FAIL: {'; '.join(m['failures'][:2])}"
            disp = m.get("disposition_coefficient")
            hold = m.get("hold_ratio")
            disp_str = f"disp={disp:.3f}" if disp is not None else (f"hold={hold:.2f}" if hold is not None else "disp=N/A")
            print(
                f"      {snap[:40]:<40} "
                f"PnL=${m['pnl']:>+8,.0f}  WR={m['win_rate']:.0%}  "
                f"PF={m['profit_factor']:.2f}  n={m['n_trades']:>3}  "
                f"L={m['long_pct']:.0%}  {disp_str}  [{gate_str}]"
            )
        print()
    print("=" * 90)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase A benchmark leaderboard")
    parser.add_argument("--prefix", type=str, default="bt_",
                        help="Version prefix filter (default: bt_)")
    parser.add_argument("--out", type=str, default=None,
                        help="Write leaderboard JSON to this path")
    parser.add_argument("--all", action="store_true",
                        help="Include all versions (not just bt_ prefix)")
    args = parser.parse_args()

    prefix = "" if args.all else args.prefix
    scorecards = load_scorecards(prefix)
    if not scorecards:
        print(f"No scorecards found in {BENCHMARKS_DIR} with prefix={prefix!r}")
        sys.exit(1)

    print(f"Loaded {len(scorecards)} scorecards.")

    configs = rank_scorecards(scorecards)
    print_leaderboard(configs)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(configs, indent=2, default=str))
        print(f"Leaderboard written → {args.out}")


if __name__ == "__main__":
    main()
