#!/usr/bin/env python3
"""
scripts/compute_scorecard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compute the Phase A benchmark scorecard for a completed training run.

Reads trades CSV + results JSON, computes all scorecard metrics including
the disposition coefficient (or hold-ratio proxy for pre-V128 runs), and
writes the scorecard to data/benchmarks/{version}_{snapshot_id}.json.

Usage:
    # After a backtest run completes:
    python3 scripts/compute_scorecard.py --version v128 --snapshot snap_20260414

    # Backfill a live run (no snapshot — use "live" as snapshot_id):
    python3 scripts/compute_scorecard.py --version v122 --snapshot live

    # Backfill all available versions:
    python3 scripts/compute_scorecard.py --backfill --snapshot live
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
BENCHMARKS_DIR = DATA_DIR / "benchmarks"
BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _load_trades(version: str) -> list[dict]:
    path = DATA_DIR / f"{version}_trades.csv"
    if not path.exists():
        return []
    rows = list(csv.DictReader(open(path)))
    return rows


def _load_results(version: str) -> dict:
    path = DATA_DIR / f"{version}_results.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_disposition(trades: list[dict]) -> dict:
    """
    Compute disposition metrics from closed trades.

    Two forms:
    1. Capture form (V128+ only, requires mae/mfe columns):
       win_capture = pnl / mfe  (winners)
       loss_capture = pnl / mae (losers, both negative, ratio in [0,1])
       disposition_coefficient = nanmedian(win_capture) - nanmedian(loss_capture)

    2. Hold-ratio proxy (all versions, backfill approximation):
       hold_ratio = mean hold_cycles(winners) / mean hold_cycles(losers)
       >1 = holding winners longer than losers → good discipline
       <1 = holding losers longer (classic disposition effect)
    """
    if not trades:
        return {"disposition_coefficient": None, "hold_ratio": None,
                "avg_mae": None, "avg_mfe": None}

    win_captures = []
    loss_captures = []
    winner_holds = []
    loser_holds = []
    maes = []
    mfes = []
    has_mfe_mae = "mfe" in trades[0] and trades[0]["mfe"] != ""

    for t in trades:
        pnl = float(t.get("pnl", 0) or 0)
        hold = float(t.get("hold_cycles", 0) or 0)

        if pnl > 0:
            winner_holds.append(hold)
        elif pnl < 0:
            loser_holds.append(hold)

        if has_mfe_mae:
            mfe = float(t.get("mfe", 0) or 0)
            mae = float(t.get("mae", 0) or 0)
            if mfe != 0:
                maes.append(mae)
                mfes.append(mfe)
            if pnl > 0 and mfe > 0:
                win_captures.append(pnl / mfe)
            elif pnl < 0 and mae < 0:
                loss_captures.append(abs(pnl) / abs(mae))

    # Hold-ratio proxy
    hold_ratio = None
    if winner_holds and loser_holds:
        hold_ratio = (sum(winner_holds) / len(winner_holds)) / (sum(loser_holds) / len(loser_holds))

    # Capture-form disposition coefficient
    disp_coef = None
    if win_captures and loss_captures:
        def nanmedian(vals):
            v = sorted(vals)
            n = len(v)
            return (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2) if v else 0.0
        disp_coef = nanmedian(win_captures) - nanmedian(loss_captures)

    avg_mae = sum(maes) / len(maes) if maes else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None

    return {
        "disposition_coefficient": round(disp_coef, 4) if disp_coef is not None else None,
        "hold_ratio": round(hold_ratio, 3) if hold_ratio is not None else None,
        "avg_mae": round(avg_mae, 4) if avg_mae is not None else None,
        "avg_mfe": round(avg_mfe, 4) if avg_mfe is not None else None,
        "_n_win_captures": len(win_captures),
        "_n_loss_captures": len(loss_captures),
    }


def compute_metrics(trades: list[dict], results: dict) -> dict:
    if not trades:
        return {
            "pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
            "n_trades": 0, "long_pct": 0.0, "short_pct": 0.0,
            "max_drawdown": 0.0, "sharpe": None,
            "regime_pnl": {"normal": 0.0, "crisis": 0.0, "high_vol": 0.0},
            **compute_disposition([]),
        }

    pnls = [float(t.get("pnl", 0) or 0) for t in trades]
    sides = [t.get("side", "") for t in trades]
    regimes = [t.get("regime", "normal") for t in trades]
    n = len(trades)

    total_pnl = sum(pnls)
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    win_rate = len(winners) / n if n else 0.0
    gross_win = sum(winners) if winners else 0.0
    gross_loss = abs(sum(losers)) if losers else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    profit_factor = min(profit_factor, 99.99)  # cap for JSON

    long_count = sides.count("long")
    short_count = sides.count("short")
    long_pct = long_count / n if n else 0.0
    short_pct = short_count / n if n else 0.0

    # Max drawdown from equity curve
    equity = 100_000.0
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = equity - peak
        if dd < max_dd:
            max_dd = dd

    # Regime breakdown
    regime_pnl: dict[str, float] = {"normal": 0.0, "crisis": 0.0, "high_vol": 0.0}
    for t in trades:
        regime = t.get("regime", "normal")
        regime_pnl[regime] = regime_pnl.get(regime, 0.0) + float(t.get("pnl", 0) or 0)

    # Sharpe (annualised, using per-trade PnL as returns, daily assumption)
    sharpe = None
    if len(pnls) >= 5:
        mean_r = sum(pnls) / len(pnls)
        var = sum((p - mean_r) ** 2 for p in pnls) / max(1, len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 1e-8
        # Approximate annualisation: assume ~2 trades/day × 365
        annual_factor = math.sqrt(len(pnls) * 2)
        sharpe = round((mean_r / std) * annual_factor, 3)

    return {
        "pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "n_trades": n,
        "long_pct": round(long_pct, 4),
        "short_pct": round(short_pct, 4),
        "max_drawdown": round(max_dd, 2),
        "sharpe": sharpe,
        "regime_pnl": {k: round(v, 2) for k, v in regime_pnl.items()},
        **compute_disposition(trades),
    }


def evaluate_gates(metrics: dict) -> dict:
    gates = {}
    failures = []

    gates["pnl_positive"] = metrics["pnl"] > 0
    if not gates["pnl_positive"]:
        failures.append(f"PnL negative: ${metrics['pnl']:.2f}")

    gates["profit_factor_above_1"] = metrics["profit_factor"] > 1.0
    if not gates["profit_factor_above_1"]:
        failures.append(f"PF < 1: {metrics['profit_factor']:.3f}")

    gates["n_trades_sufficient"] = metrics["n_trades"] >= 20
    if not gates["n_trades_sufficient"]:
        failures.append(f"Too few trades: {metrics['n_trades']} (need ≥20)")

    gates["long_short_balanced"] = 0.20 <= metrics["long_pct"] <= 0.80
    if not gates["long_short_balanced"]:
        failures.append(f"L/S imbalance: {metrics['long_pct']:.0%} long")

    # No regime should be below -$100
    regime_ok = all(v >= -100 for v in metrics["regime_pnl"].values())
    gates["no_regime_catastrophe"] = regime_ok
    if not regime_ok:
        bad = {k: v for k, v in metrics["regime_pnl"].items() if v < -100}
        failures.append(f"Regime catastrophe: {bad}")

    # Disposition: hold_ratio > 0.7 (acceptable), disposition_coef > -0.2
    disp = metrics.get("disposition_coefficient")
    hold = metrics.get("hold_ratio")
    disp_ok = (
        (disp is not None and disp > -0.2)
        or (hold is not None and hold > 0.7)
        or (disp is None and hold is None)  # no data — pass
    )
    gates["disposition_acceptable"] = disp_ok
    if not disp_ok:
        failures.append(f"Poor exit discipline: disp_coef={disp}, hold_ratio={hold}")

    return {
        "passed": all(gates.values()),
        "gates": gates,
        "failure_reasons": failures,
    }


def compute_scorecard(
    version: str,
    snapshot_id: str,
    snapshot_path: str = "",
    features: str = "",
    seed: int | None = 42,
    n_cycles: int = 200,
) -> dict:
    trades = _load_trades(version)
    results = _load_results(version)
    metrics = compute_metrics(trades, results)
    gate_result = evaluate_gates(metrics)

    return {
        "version": version,
        "snapshot_id": snapshot_id,
        "snapshot_path": snapshot_path,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "features": features or results.get("features", ""),
        "n_cycles": n_cycles,
        "metrics": metrics,
        "gate_result": gate_result,
        "leaderboard_rank": None,
    }


def save_scorecard(scorecard: dict) -> Path:
    version = scorecard["version"]
    snap = scorecard["snapshot_id"].replace("/", "_")
    path = BENCHMARKS_DIR / f"{version}_{snap}.json"
    path.write_text(json.dumps(scorecard, indent=2, default=str))
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Compute Phase A benchmark scorecard")
    parser.add_argument("--version", type=str, help="Version label (e.g. v128)")
    parser.add_argument("--snapshot", type=str, default="live",
                        help="Snapshot ID (e.g. snap_20260414 or 'live')")
    parser.add_argument("--snapshot-path", type=str, default="",
                        help="Path to snapshot file (optional, for metadata)")
    parser.add_argument("--features", type=str, default="",
                        help="Feature preset used for this run")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cycles", type=int, default=200)
    parser.add_argument("--backfill", action="store_true",
                        help="Compute scorecards for all available versions")
    args = parser.parse_args()

    if args.backfill:
        # Find all versions with trades CSVs
        import re
        versions = []
        for f in sorted(DATA_DIR.glob("v*_trades.csv")):
            m = re.match(r"(v\d+)_trades\.csv", f.name)
            if m:
                versions.append(m.group(1))
        print(f"Backfilling {len(versions)} versions against snapshot='{args.snapshot}'")
        for version in versions:
            sc = compute_scorecard(version, args.snapshot, args.snapshot_path,
                                   args.features, args.seed, args.cycles)
            path = save_scorecard(sc)
            passed = "✅" if sc["gate_result"]["passed"] else "❌"
            print(f"  {version}: PnL=${sc['metrics']['pnl']:+.0f} "
                  f"WR={sc['metrics']['win_rate']:.0%} "
                  f"PF={sc['metrics']['profit_factor']:.2f} "
                  f"L/S={sc['metrics']['long_pct']:.0%}/{sc['metrics']['short_pct']:.0%} "
                  f"hold_ratio={sc['metrics']['hold_ratio']} "
                  f"{passed} → {path.name}")
        return

    if not args.version:
        parser.error("--version is required (or use --backfill)")

    sc = compute_scorecard(
        args.version, args.snapshot, args.snapshot_path,
        args.features, args.seed, args.cycles
    )
    path = save_scorecard(sc)
    print(json.dumps(sc, indent=2, default=str))
    print(f"\nSaved → {path}")


if __name__ == "__main__":
    main()
