#!/usr/bin/env python3
"""Run V226 diagnostic with crisis features and analyze trading patterns."""

import logging
import sys
import json
import csv
from pathlib import Path


def analyze_patterns(trades, results):
    """Extract recurring patterns from trading history."""
    patterns = []

    # Pattern 1: Regime-conviction correlation
    regime_conviction = {}
    for t in trades:
        regime = t.get('regime', 'unknown')
        conviction = float(t.get('conviction', 0))
        if regime not in regime_conviction:
            regime_conviction[regime] = []
        regime_conviction[regime].append(conviction)

    for regime, convictions in regime_conviction.items():
        avg_conv = sum(convictions) / len(convictions) if convictions else 0
        pattern = {
            "concept": f"{regime}_conviction_baseline",
            "content": f"{regime} regime shows avg conviction {avg_conv:.3f} across {len(convictions)} trades",
            "confidence": 0.8,
            "tags": ["regime", "conviction", regime]
        }
        patterns.append(pattern)

    # Pattern 2: Outcome by regime
    regime_outcomes = {}
    for t in trades:
        regime = t.get('regime', 'unknown')
        pnl = float(t.get('pnl', 0))
        if regime not in regime_outcomes:
            regime_outcomes[regime] = {"wins": 0, "losses": 0, "total_pnl": 0}
        regime_outcomes[regime]["total_pnl"] += pnl
        if pnl > 0:
            regime_outcomes[regime]["wins"] += 1
        elif pnl < 0:
            regime_outcomes[regime]["losses"] += 1

    for regime, outcome in regime_outcomes.items():
        total = outcome["wins"] + outcome["losses"]
        wr = outcome["wins"] / total if total > 0 else 0
        pattern = {
            "concept": f"{regime}_win_rate",
            "content": f"{regime} regime: {wr:.1%} win rate ({outcome['wins']}/{total} trades), avg PnL ${outcome['total_pnl']:.0f}",
            "confidence": 0.85,
            "tags": ["regime", "outcome", regime]
        }
        patterns.append(pattern)

    return patterns


if __name__ == "__main__":
    # Set up logging filter for gate decisions
    lg = logging.getLogger("omega.nodes.victoria.signal_generation")
    lg.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stderr)
    h.setLevel(logging.INFO)
    h.addFilter(lambda r: "gate_decision" in r.getMessage())
    lg.addHandler(h)
    lg.propagate = False

    # Run the training with diagnostic parameters
    sys.argv = [
        "run_training.py",
        "--version", "v226_diag_crisis",
        "--cycles", "40",
        "--sleep", "0",
        "--seed", "42",
        "--backtest-snapshot", "data/snapshots/snap_crisis_2022h1.json",
        "--frozen-cache",
        "--features", '{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}'
    ]

    import runpy
    try:
        runpy.run_path("scripts/run_training.py", run_name="__main__")
    except SystemExit:
        pass

    # Now analyze the results
    trades_file = Path("data/v226_diag_crisis_trades.csv")
    results_file = Path("data/v226_diag_crisis_results.json")

    if trades_file.exists() and results_file.exists():
        # Load trades
        trades = []
        with open(trades_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)

        # Load results for context
        with open(results_file) as f:
            results = json.load(f)

        print("\n=== TRADING HISTORY ANALYSIS ===")
        print(f"Total trades: {len(trades)}")
        print(f"Cycles run: {len(set(t['cycle'] for t in trades))}")

        # Extract patterns from trading history
        patterns = analyze_patterns(trades, results)

        # Output as JSON lines
        for pattern in patterns:
            print(json.dumps(pattern))
    else:
        print(f"Warning: Expected files not found")
        print(f"  trades_file exists: {trades_file.exists()}")
        print(f"  results_file exists: {results_file.exists()}")
