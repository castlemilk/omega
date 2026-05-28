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
    "bt_v130":    "v130_high_vol_gate",
    "bt_v131a":   "v131_early_N2K03",
    "bt_v131b":   "v131_early_N3K03",
    "bt_v131c":   "v131_early_N3K05",
    "bt_v132a":    "v132_fix_a",
    "bt_v132b":    "v132_fix_b",
    "bt_v132c":    "v132_fix_c",
    # V133: stop_loss age guard + four-factor AND-gate
    "bt_v133a":    "v133_and_gate",          # full fix: sl_guard + AND-gate
    "bt_v133b":    "v133_stop_loss_guard",   # stop_loss guard only (gate isolated)
    "bt_v133c":    "v133_gate_only",         # AND-gate only (no sl guard)
    # V134: AND-gate calibration — relax divergence threshold 0.05 → 0.03
    "bt_v134":     "v134_gate_calibrated",
    # V135: ATR-based stop-loss grid (replaces fixed -2% stop)
    "bt_v135a":    "v135_atr_k10",          # K=1.0 tight
    "bt_v135b":    "v135_atr_k12",          # K=1.2 moderate
    "bt_v135c":    "v135_atr_k15",          # K=1.5 wide
    # V133v2: AND-gate with exit-quality Gate 2 (avoids self-referential lock)
    "bt_v133v2a":  "v133v2_gate_quality",   # AND-gate + new Gate 2 only
    "bt_v133v2b":  "v133v2_gate_atr",       # AND-gate + new Gate 2 + ATR stop
    # V136: crisis-regime entry bias fix (hard long block + permissive shorts)
    "bt_v136a":    "v136_crisis_bias",      # crisis_long_block + thresh×0.5 + ATR K=1.2
    "bt_v136b":    "v136_aggressive_short", # crisis_long_block + thresh×0.4
    "bt_v136c":    "v136_size_boost",       # v136a + 1.5× short size boost
    # V137: V136a champion + reworked AND-gate (V133v2 exit-quality Gate 2)
    "bt_v137a":    "v137_full_gate",        # V136a + all 4 AND-gate gates
    "bt_v137b":    "v137_no_gate1",         # V136a + AND-gate minus Gate 1 (divergence off)
    "bt_v137c":    "v137_no_gate4",         # V136a + AND-gate minus Gate 4 (pair network off)
    # 500-cycle deep analysis (Track A)
    "bt500_v136a": "v136a_500cyc",          # V136a baseline, 500 cycles
    "bt500_v137a": "v137a_500cyc",          # V137a full AND-gate, 500 cycles
    # V138: signal improvements + warm-starts + geopolitical (Phase A test)
    "bt_v138": "v138_full",                 # V138 full preset, 500 cycles
    # V138.1: warm-start bugs fixed (backtest-safe) — imd + reasoning only
    "bt_v138_1": "v138_1",                  # V138.1 fixed preset, 500 cycles
    # V139: V138.1 + pluggable LLM analyst conviction modifier
    "bt_v139":        "v139_llm_analyst",          # default alias (Haiku)
    "bt_v139_haiku":  "v139_claude_haiku",
    "bt_v139_sonnet": "v139_claude_sonnet",
    "bt_v139_kimi":   "v139_kimi_v2",
    "bt_v139_glm":    "v139_glm",
    "bt_v139_minimax":"v139_minimax",
    "bt_v139_cli":    "v139_cli",
    # V140: multi-LLM A/B comparison (recent snapshot only)
    "bt_v140_kimi":         "v140_kimi",
    "bt_v140_glm":          "v140_glm",
    "bt_v140_minimax":      "v140_minimax",
    "bt_v140_claude_haiku": "v140_claude_haiku",
    # V141: crisis alpha — all 6 forensics fixes
    "bt_v141":              "v141_crisis_alpha",
    # V142: quick fix — conservative bear_prob gate, gated hysteresis, high_vol block
    "bt_v142":              "v142_crisis_alpha",
    "bt_v142_crisis":       "v142_crisis_alpha",
    "bt_v142_trend":        "v142_crisis_alpha",
    "bt_v142_recent":       "v142_crisis_alpha",
    "bt_v141_crisis":       "v141_crisis_alpha",
    "bt_v141_no_llm":       "v141_crisis_no_llm",
    "bt_v141_no_llm_crisis": "v141_crisis_no_llm",
    # V143: continuous confidence surfaces (Phase 1) — v3 had long-gate bug
    "bt_v143":              "v143_surfaces_buggy",
    "bt_v143_crisis":       "v143_surfaces_buggy",
    "bt_v143_trend":        "v143_surfaces_buggy",
    "bt_v143_recent":       "v143_surfaces_buggy",
    # V143v2: Phase 1 with long surface gate fixed
    "bt_v143v2":            "v143_surfaces",
    "bt_v143v2_crisis":     "v143_surfaces",
    "bt_v143v2_trend":      "v143_surfaces",
    "bt_v143v2_recent":     "v143_surfaces",
    # V144: meta-learning layer (Phase 2)
    "bt_v144":              "v144_meta_learner",
    "bt_v144_crisis":       "v144_meta_learner",
    "bt_v144_trend":        "v144_meta_learner",
    "bt_v144_recent":       "v144_meta_learner",
    # V145: LLM meta-controller (Phase 3)
    "bt_v145":              "v145_llm_meta",
    "bt_v145_crisis":       "v145_llm_meta",
    "bt_v145_trend":        "v145_llm_meta",
    "bt_v145_recent":       "v145_llm_meta",
    # V146: ensemble voting (Phase 4)
    "bt_v146":              "v146_ensemble",
    "bt_v146_crisis":       "v146_ensemble",
    "bt_v146_trend":        "v146_ensemble",
    "bt_v146_recent":       "v146_ensemble",
    # V147: Bayesian regime detection (Phase 5)
    "bt_v147":              "v147_bayesian",
    "bt_v147_crisis":       "v147_bayesian",
    "bt_v147_trend":        "v147_bayesian",
    "bt_v147_recent":       "v147_bayesian",
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
    for prefix, label in sorted(_CONFIG_LABELS.items(), key=lambda kv: -len(kv[0])):
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
