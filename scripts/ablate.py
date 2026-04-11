#!/usr/bin/env python3
"""scripts/ablate.py
~~~~~~~~~~~~~~~~~~~~
Feature flag ablation runner — compare multiple presets over the same N cycles.

Runs run_training.run() sequentially for each preset, then prints a comparison
table of PnL, win rate, trades, profit factor, and zero-trade cycle %.

Usage
-----
    python scripts/ablate.py --cycles 100 --sleep 10
    python scripts/ablate.py --cycles 200 --presets v93_baseline,v97_geometry,observability_only
    python scripts/ablate.py --cycles 100 --presets v93_baseline,v98_full_obs --version-prefix ablate

Output
------
    data/ablation_{timestamp}/          — one results JSON per preset
    data/ablation_{timestamp}/summary.json  — comparison table
    Comparison table printed to stdout.

Notes
-----
- Each preset runs with an auto-versioned label: {version_prefix}_{preset}
- Results are compared against the first preset (baseline).
- Does NOT launch training automatically — run manually or via make ablate.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UTC = timezone.utc

DEFAULT_PRESETS = [
    "v93_baseline",
    "v97_geometry",
    "observability_only",
    "v98_full_obs",
]

# ANSI helpers
_R = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_YELLOW = "\033[93m"


def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _fmt_pnl(val: float, baseline: float | None = None) -> str:
    color = _GREEN if val >= 0 else _RED
    s = f"{color}${val:+.2f}{_R}"
    if baseline is not None and baseline != 0.0:
        delta = val - baseline
        d_color = _GREEN if delta >= 0 else _RED
        s += f"  ({d_color}{delta:+.2f}{_R})"
    return s


def _fmt_pct(val: float) -> str:
    color = _GREEN if val >= 0.40 else (_YELLOW if val >= 0.25 else _RED)
    return f"{color}{val * 100:.1f}%{_R}"


def run_ablation(
    presets: list[str],
    cycles: int,
    sleep_seconds: float,
    version_prefix: str,
    output_dir: Path,
) -> dict:
    from scripts.run_training import run as _run

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for preset in presets:
        version = f"{version_prefix}_{preset}"
        print(f"\n{_CYAN}{'=' * 60}{_R}")
        print(f"{_BOLD}Ablation: preset={preset}  version={version}{_R}")
        print(f"{_CYAN}{'=' * 60}{_R}\n")

        try:
            r = _run(
                version=version,
                n_cycles=cycles,
                sleep_seconds=sleep_seconds,
                features=preset,
            )
        except Exception as exc:
            print(f"{_RED}ERROR running preset {preset}: {exc}{_R}")
            r = {"error": str(exc)}

        # Copy results file if it exists
        src = ROOT / "data" / f"{version}_results.json"
        if src.exists():
            dst = output_dir / f"{preset}_results.json"
            dst.write_bytes(src.read_bytes())

        entry = {
            "preset": preset,
            "version": version,
            "pnl": (r.get("trades", {}) or {}).get("total_pnl_usd", 0.0),
            "win_rate": (r.get("trades", {}) or {}).get("win_rate", 0.0),
            "trades": (r.get("trades", {}) or {}).get("total_closed", 0),
            "profit_factor": (r.get("trades", {}) or {}).get("profit_factor", 0.0),
            "zero_cycles_pct": (
                (r.get("observability", {}) or {}).get("total_zero_trade_cycles", 0)
                / max(cycles, 1)
            ),
            "error": r.get("error"),
        }
        results.append(entry)

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "cycles": cycles,
        "sleep_seconds": sleep_seconds,
        "presets": presets,
        "results": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def print_table(summary: dict) -> None:
    results = summary["results"]
    if not results:
        print("No results.")
        return

    baseline_pnl = results[0]["pnl"] if results else None

    col_w = [20, 10, 8, 8, 8, 12]
    headers = ["Preset", "PnL", "WR", "Trades", "PF", "Zero%"]

    def _row(cols: list[str]) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cols, col_w))

    sep = "-" * (sum(col_w) + 2 * len(col_w))
    print(f"\n{_BOLD}{'Ablation Results':^{len(sep)}}{_R}")
    print(f"{_CYAN}{sep}{_R}")
    print(_BOLD + _row(headers) + _R)
    print(sep)

    for r in results:
        if r.get("error"):
            print(_row([r["preset"], "ERROR", "-", "-", "-", "-"]))
            continue
        is_baseline = (r == results[0])
        pnl_str = _fmt_pnl(r["pnl"], None if is_baseline else baseline_pnl)
        wr_str = _fmt_pct(r["win_rate"])
        pf = r["profit_factor"]
        pf_color = _GREEN if pf >= 1.5 else (_YELLOW if pf >= 1.0 else _RED)
        pf_str = f"{pf_color}{pf:.2f}{_R}"
        zp = r["zero_cycles_pct"]
        zp_color = _RED if zp >= 0.70 else (_YELLOW if zp >= 0.50 else _GREEN)
        zp_str = f"{zp_color}{zp * 100:.0f}%{_R}"
        prefix = "(baseline) " if is_baseline else "           "
        print(f"{prefix}{r['preset']:<20}  {pnl_str:<18}  {wr_str:<10}  {r['trades']:<8}  {pf_str:<10}  {zp_str}")

    print(f"{_CYAN}{sep}{_R}\n")


if __name__ == "__main__":
    _load_env()

    parser = argparse.ArgumentParser(
        description="Feature flag ablation: run multiple presets and compare results"
    )
    parser.add_argument("--cycles", type=int, default=100, help="Cycles per preset")
    parser.add_argument("--sleep", type=float, default=10.0, help="Seconds between cycles")
    parser.add_argument(
        "--presets",
        type=str,
        default=",".join(DEFAULT_PRESETS),
        help=f"Comma-separated preset names (default: {','.join(DEFAULT_PRESETS)})",
    )
    parser.add_argument(
        "--version-prefix",
        type=str,
        default="ablate",
        help="Prefix for training version labels (default: ablate)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for ablation outputs (default: data/ablation_{timestamp})",
    )
    args = parser.parse_args()

    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "data" / f"ablation_{ts}"

    print(f"{_BOLD}Ablation run: {len(presets)} presets × {args.cycles} cycles{_R}")
    print(f"Output: {output_dir}")

    summary = run_ablation(
        presets=presets,
        cycles=args.cycles,
        sleep_seconds=args.sleep,
        version_prefix=args.version_prefix,
        output_dir=output_dir,
    )
    print_table(summary)
    print(f"Summary saved: {output_dir / 'summary.json'}")
