"""CLI runner for V35 ↔ V48 (or any baseline/target) forensics diff.

Usage:
    python -m omega.tools.forensics.run_diff \
        --baseline-results data/v35_extended_results.json \
        --baseline-trades data/v35_extended_trades.csv \
        --target-results data/v48_results.json \
        --target-trades data/v48_trades.csv \
        --out-json data/v35-v48-forensics.json \
        --out-md docs/training/v35-v48-forensics.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import rank_hypotheses
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades
from omega.tools.forensics.writer import write_forensics_json, write_forensics_markdown


def run_diff(
    baseline_results: Path,
    baseline_trades: Path,
    target_results: Path,
    target_trades: Path,
    out_json: Path,
    out_md: Path,
    hold_threshold: float = 0.20,
) -> int:
    """Execute the full diff pipeline. Returns process exit code."""
    baseline = load_run(baseline_results, baseline_trades)
    target = load_run(target_results, target_trades)

    h_baseline = compute_histogram(baseline, hold_threshold)
    h_target = compute_histogram(target, hold_threshold)
    delta = compute_signal_delta_proxy(baseline, target)
    skipped = find_skipped_trades(baseline, target)
    hypotheses = rank_hypotheses(
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
    )

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_md).parent.mkdir(parents=True, exist_ok=True)

    write_forensics_json(
        Path(out_json),
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
        hypotheses=hypotheses,
    )
    write_forensics_markdown(
        Path(out_md),
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
        hypotheses=hypotheses,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run V35 ↔ V48 forensics diff.")
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--baseline-trades", type=Path, required=True)
    parser.add_argument("--target-results", type=Path, required=True)
    parser.add_argument("--target-trades", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--hold-threshold", type=float, default=0.20)
    args = parser.parse_args(argv)

    return run_diff(
        baseline_results=args.baseline_results,
        baseline_trades=args.baseline_trades,
        target_results=args.target_results,
        target_trades=args.target_trades,
        out_json=args.out_json,
        out_md=args.out_md,
        hold_threshold=args.hold_threshold,
    )


if __name__ == "__main__":
    sys.exit(main())
