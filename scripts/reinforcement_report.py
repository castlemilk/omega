#!/usr/bin/env python3
"""
reinforcement_report.py — Reinforcement weight analysis for Victoria signal system.

Usage:
    python3 scripts/reinforcement_report.py
        [--state data/reinforcement_state.json]
        [--history-dir data/activation_traces]
        [--version v110]
        [--no-color]
"""

import argparse
import json
import sys
import math
from pathlib import Path
from collections import defaultdict

# ── ANSI color helpers ────────────────────────────────────────────────────────

USE_COLOR = True

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):   return _c("32", t)
def red(t):     return _c("31", t)
def yellow(t):  return _c("33", t)
def bold(t):    return _c("1",  t)
def dim(t):     return _c("2",  t)
def cyan(t):    return _c("36", t)
def magenta(t): return _c("35", t)

def score_color(v: float, text: str) -> str:
    if v > 0.05:   return green(text)
    if v < -0.05:  return red(text)
    return yellow(text)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_LONG_THRESH  = 0.10
BASE_SHORT_THRESH = 0.10
THRESH_REDUCTION_AT_50 = 0.20  # 20% reduction once n_trades >= 50

MULTIPLIER_MIN = 0.2
MULTIPLIER_MAX = 1.5

# ── Data loading ──────────────────────────────────────────────────────────────

def load_state(path: Path) -> dict:
    if not path.exists():
        print(red(f"[error] reinforcement_state.json not found: {path}"), file=sys.stderr)
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(red(f"[error] Failed to parse {path}: {e}"), file=sys.stderr)
        return {}


def load_traces(history_dir: Path, version: str | None) -> list[dict]:
    """Load traces from history dir, optionally filtered to a specific version."""
    traces = []
    if not history_dir.exists():
        return traces

    files = sorted(history_dir.glob("*.jsonl"))
    if version:
        files = [f for f in files if f.stem == version]

    for fpath in files:
        with fpath.open() as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return traces

# ── Analysis helpers ──────────────────────────────────────────────────────────

def compute_multiplier(score: float) -> float:
    raw = 1.0 + score * 0.5
    return max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, raw))


def classify_direction(score: float) -> str:
    if score >= 0.05:
        return green("AMPLIFIED")
    elif score <= -0.05:
        return red("DAMPENED ")
    return yellow("NEUTRAL  ")


def multiplier_bar(mult: float, width: int = 20) -> str:
    """Bar showing deviation from 1.0. Center at width//2."""
    center = width // 2
    deviation = mult - 1.0
    max_dev = max(MULTIPLIER_MAX - 1.0, 1.0 - MULTIPLIER_MIN)
    # ratio: how far from center (0=center, 1=max dev)
    ratio = min(abs(deviation) / max_dev, 1.0)
    filled = int(ratio * center)

    if deviation >= 0:
        bar = dim("─" * center) + green("█" * filled) + dim("░" * (center - filled))
    else:
        bar = dim("░" * (center - filled)) + red("█" * filled) + dim("─" * center)
    return f"[{bar}]"


def classify_convergence(score: float) -> str:
    abs_s = abs(score)
    if abs_s >= 0.15:
        direction = "positive" if score > 0 else "negative"
        return green(f"CONVERGING ({direction})")
    elif abs_s < 0.05:
        return yellow("UNCERTAIN ")
    else:
        return cyan("TRENDING  ")

# ── Section printers ──────────────────────────────────────────────────────────

def print_header(state: dict) -> None:
    n_trades = state.get("n_trades", 0)
    updated  = state.get("updated_at", "unknown")
    active   = n_trades >= 5

    print()
    print(bold(cyan("═" * 70)))
    print(bold(cyan("  REINFORCEMENT WEIGHT REPORT")))
    print(bold(cyan("═" * 70)))
    print(f"  n_trades   : {bold(str(n_trades))}  {'(' + green('active') + ')' if active else '(' + red('not yet active — need ≥5 trades') + ')'}")
    print(f"  updated_at : {dim(updated)}")
    print()


def print_weights_table(scores: dict) -> None:
    if not scores:
        print(dim("  No signal scores found."))
        return

    print(bold(cyan("── SIGNAL WEIGHTS TABLE " + "─" * 44)))
    print(f"  {'Signal':<28} {'Score':>8} {'Multiplier':>11} {'Direction':<12}  {'Deviation Bar'}")
    print(f"  {dim('─' * 85)}")

    sorted_sigs = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
    for sig, score in sorted_sigs:
        mult = compute_multiplier(score)
        direction = classify_direction(score)
        bar = multiplier_bar(mult)
        score_str = score_color(score, f"{score:+.4f}")
        mult_str = f"{mult:.3f}x"
        print(f"  {sig:<28} {score_str:>17} {mult_str:>11} {direction:<21}  {bar}")
    print()


def print_convergence(scores: dict) -> None:
    if not scores:
        return

    print(bold(cyan("── CONVERGENCE ANALYSIS " + "─" * 44)))
    sorted_sigs = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
    for sig, score in sorted_sigs:
        status = classify_convergence(score)
        bar_width = 30
        ratio = min(abs(score) / 0.3, 1.0)
        filled = int(ratio * bar_width)
        bar = ("█" * filled + dim("░" * (bar_width - filled)))
        bar_colored = score_color(score, bar)
        print(f"  {sig:<28}  {status:<30}  {bar_colored}")

    print()
    print(f"  {bold('Legend:')}  {green('≥ 0.15')} = converging strong opinion  "
          f"{yellow('< 0.05')} = uncertain  "
          f"{cyan('0.05–0.15')} = trending")
    print()


def print_threshold_impact(n_trades: int) -> None:
    print(bold(cyan("── EFFECTIVE THRESHOLD IMPACT " + "─" * 38)))

    reduction = THRESH_REDUCTION_AT_50 if n_trades >= 50 else 0.0
    eff_long  = BASE_LONG_THRESH  * (1.0 - reduction)
    eff_short = BASE_SHORT_THRESH * (1.0 - reduction)

    print(f"  Base thresholds  : long={BASE_LONG_THRESH:.2f}  short={BASE_SHORT_THRESH:.2f}")
    if n_trades >= 50:
        print(f"  n_trades={n_trades} ≥ 50 → {THRESH_REDUCTION_AT_50*100:.0f}% threshold reduction applied")
    else:
        print(f"  n_trades={n_trades} < 50  → No reduction yet (need {50 - n_trades} more trades)")
    print()
    print(f"  {'Regime':<12} {'EffLong':>10} {'EffShort':>11}  Notes")
    print(f"  {dim('─' * 60)}")

    regimes = [
        ("normal",   eff_long,        eff_short,       ""),
        ("high_vol", eff_long * 1.25, eff_short * 1.25, "1.25x vol multiplier"),
        ("crisis",   eff_long * 0.20, eff_short * 0.05, "bear lean: long suppressed, short permissive"),
        ("bull",     eff_long * 0.05, eff_short * 0.20, "bull lean: short suppressed, long permissive"),
    ]
    for label, lt, st, note in regimes:
        print(f"  {yellow(label):<21} {lt:>10.4f} {st:>11.4f}  {dim(note)}")
    print()


def print_recommendations(scores: dict, n_trades: int) -> None:
    print(bold(cyan("── RECOMMENDATIONS " + "─" * 49)))

    if not scores:
        print(dim("  No scores to analyze."))
        print()
        return

    recs = []
    for sig, score in sorted(scores.items(), key=lambda x: x[1]):
        abs_s = abs(score)
        if score <= -0.20:
            recs.append((red("⚠ HIGH PRIORITY"), sig,
                         f"{red(sig)} is consistently wrong (score={score:+.3f}): "
                         f"consider removing from signal set or heavily dampening IC weight."))
        elif -0.20 < score <= -0.10:
            recs.append((yellow("○ MODERATE"), sig,
                         f"{yellow(sig)} is underperforming (score={score:+.3f}): "
                         f"review signal logic or reduce IC weight."))
        elif score >= 0.20:
            recs.append((green("★ HIGH PRIORITY"), sig,
                         f"{green(sig)} is consistently right (score={score:+.3f}): "
                         f"consider increasing IC weight or expanding its role."))
        elif 0.10 <= score < 0.20:
            recs.append((cyan("○ MODERATE"), sig,
                         f"{cyan(sig)} is performing well (score={score:+.3f}): "
                         f"potential candidate for increased weighting."))
        elif abs_s < 0.05 and n_trades >= 30:
            recs.append((dim("· INFO"), sig,
                         f"{dim(sig)} is neutral (score={score:+.3f}) after {n_trades} trades: "
                         f"may lack predictive signal — monitor or remove."))

    if not recs:
        print(dim("  All signals within expected variance — no urgent actions."))
    else:
        for priority, sig, msg in recs:
            print(f"  [{priority}] {msg}")

    print()
    if n_trades < 50:
        print(f"  {yellow('[note]')} Only {n_trades} trades recorded — weights will stabilize further after 50+ trades.")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(description="Victoria reinforcement weight report")
    parser.add_argument("--state", default="data/reinforcement_state.json",
                        help="Path to reinforcement_state.json")
    parser.add_argument("--history-dir", default="data/activation_traces",
                        help="Directory containing *.jsonl trace files")
    parser.add_argument("--version", default=None,
                        help="Filter traces to a specific version (e.g. v110)")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    USE_COLOR = not args.no_color

    base = Path(__file__).resolve().parent.parent
    state_path = Path(args.state) if Path(args.state).is_absolute() else base / args.state
    history_dir = Path(args.history_dir) if Path(args.history_dir).is_absolute() else base / args.history_dir

    state = load_state(state_path)
    if not state:
        print(red("No reinforcement state loaded. Cannot continue."))
        sys.exit(1)

    scores   = state.get("scores", {})
    n_trades = state.get("n_trades", 0)

    print_header(state)
    print_weights_table(scores)
    print_convergence(scores)
    print_threshold_impact(n_trades)
    print_recommendations(scores, n_trades)


if __name__ == "__main__":
    main()
