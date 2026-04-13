#!/usr/bin/env python3
"""
cross_version_analysis.py — Read-only cross-version signal accuracy analysis.

Usage:
    python3 scripts/cross_version_analysis.py --versions v107,v108,v109,v110,v111
    python3 scripts/cross_version_analysis.py --versions v107,v108 --no-color --min-trades 5
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"

NO_COLOR = False  # set by --no-color


def _c(code: str, text: str) -> str:
    if NO_COLOR:
        return text
    return f"{code}{text}{RESET}"


def green(t):  return _c(GREEN,  t)
def yellow(t): return _c(YELLOW, t)
def red(t):    return _c(RED,    t)
def bold(t):   return _c(BOLD,   t)
def dim(t):    return _c(DIM,    t)
def cyan(t):   return _c(CYAN,   t)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_traces(versions: list[str], base_dir: Path) -> list[dict]:
    """Load all JSONL traces for the requested versions. Skip missing files."""
    traces = []
    for ver in versions:
        path = base_dir / f"{ver}.jsonl"
        if not path.exists():
            print(dim(f"  [skip] {path} not found"), file=sys.stderr)
            continue
        loaded = 0
        skipped = 0
        with path.open() as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    trace = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(dim(f"  [warn] {path}:{lineno} JSON error: {exc}"), file=sys.stderr)
                    skipped += 1
                    continue

                # Skip open trades (no outcome or null exit_pnl)
                outcome = trace.get("outcome")
                if outcome is None or outcome.get("exit_pnl") is None:
                    skipped += 1
                    continue

                traces.append(trace)
                loaded += 1
        print(dim(f"  [load] {ver}: {loaded} closed trades ({skipped} skipped)"), file=sys.stderr)
    return traces


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(traces: list[dict], min_trades: int):
    """
    Returns:
        signal_stats  — {signal: {"right": int, "wrong": int,
                                  "attribution": float,
                                  "by_version": {ver: {"right": int, "wrong": int}},
                                  "by_regime":  {regime: {"right": int, "wrong": int}}}}
        versions_seen — list[str] (ordered)
    """
    signal_stats: dict[str, dict] = defaultdict(lambda: {
        "right": 0, "wrong": 0, "attribution": 0.0,
        "by_version": defaultdict(lambda: {"right": 0, "wrong": 0}),
        "by_regime":  defaultdict(lambda: {"right": 0, "wrong": 0}),
    })
    versions_seen_set: set[str] = set()

    for trace in traces:
        ver    = trace.get("version", "unknown")
        regime = (trace.get("regime") or {}).get("label", "unknown")
        outcome = trace.get("outcome", {})
        signals_right = set(outcome.get("signals_right") or [])
        signals_wrong = set(outcome.get("signals_wrong") or [])
        attribution   = outcome.get("attribution") or {}
        activations   = trace.get("activations") or []

        versions_seen_set.add(ver)

        for act in activations:
            name = act.get("name")
            if not name:
                continue
            # Only count non-neutral activations
            if act.get("direction_alignment", 0) == 0:
                continue

            s = signal_stats[name]
            if name in signals_right:
                s["right"] += 1
                s["by_version"][ver]["right"] += 1
                s["by_regime"][regime]["right"] += 1
            elif name in signals_wrong:
                s["wrong"] += 1
                s["by_version"][ver]["wrong"] += 1
                s["by_regime"][regime]["wrong"] += 1
            # If neither right nor wrong, we still saw it — no right/wrong credit

            # Attribution (may be empty dict or missing key)
            attr_val = attribution.get(name)
            if attr_val is not None:
                s["attribution"] += attr_val

    # Sort versions deterministically
    versions_sorted = sorted(versions_seen_set)
    return dict(signal_stats), versions_sorted


def accuracy(right: int, wrong: int) -> float | None:
    total = right + wrong
    if total == 0:
        return None
    return right / total * 100.0


def stdev_across_versions(signal_name: str, stats: dict, versions: list[str]) -> float | None:
    """Population stdev of per-version accuracy for versions where signal appears."""
    accs = []
    for ver in versions:
        bv = stats.get("by_version", {}).get(ver, {})
        r, w = bv.get("right", 0), bv.get("wrong", 0)
        a = accuracy(r, w)
        if a is not None:
            accs.append(a)
    if len(accs) < 2:
        return None
    mean = sum(accs) / len(accs)
    variance = sum((x - mean) ** 2 for x in accs) / len(accs)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Sparkline bar
# ---------------------------------------------------------------------------

BARS = " ▁▂▃▄▅▆▇█"

def sparkbar(acc_pct: float | None, width: int = 4) -> str:
    """Convert accuracy 0-100 → ASCII bar characters."""
    if acc_pct is None:
        return dim("----")
    idx = int(acc_pct / 100 * (len(BARS) - 1))
    idx = max(0, min(idx, len(BARS) - 1))
    bar = BARS[idx] * width
    if acc_pct >= 55:
        return green(bar)
    elif acc_pct >= 45:
        return yellow(bar)
    else:
        return red(bar)


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------

def color_accuracy(acc: float | None) -> str:
    if acc is None:
        return dim("  n/a")
    s = f"{acc:5.1f}%"
    if acc >= 55:
        return green(s)
    elif acc >= 45:
        return yellow(s)
    else:
        return red(s)


def section(title: str):
    width = 72
    print()
    print(bold(cyan("=" * width)))
    print(bold(cyan(f"  {title}")))
    print(bold(cyan("=" * width)))


# ---------------------------------------------------------------------------
# Section 1: Cross-version signal accuracy
# ---------------------------------------------------------------------------

def print_signal_accuracy(signal_stats: dict, versions: list[str], min_trades: int):
    section("1. CROSS-VERSION SIGNAL ACCURACY")

    rows = []
    for sig, stats in signal_stats.items():
        r = stats["right"]
        w = stats["wrong"]
        total = r + w
        if total < 1:
            continue
        acc = accuracy(r, w)
        sd  = stdev_across_versions(sig, stats, versions)
        attr = stats["attribution"]
        rows.append((sig, r, w, total, acc, sd, attr))

    # Sort by accuracy desc (None last)
    rows.sort(key=lambda x: (x[4] is None, -(x[4] or 0)))

    print()
    header = (
        f"{'Signal':<32} {'Right':>5} {'Wrong':>5} {'Total':>5}"
        f"  {'Acc%':>6}  {'StdDev':>6}  {'Attribution':>12}"
    )
    print(bold(header))
    print(dim("-" * 80))

    for sig, r, w, total, acc, sd, attr in rows:
        sd_str  = f"{sd:6.1f}" if sd is not None else "   n/a"
        attr_str = f"{attr:+12.2f}" if attr != 0.0 else f"{'n/a':>12}"
        acc_str  = color_accuracy(acc)
        dim_row  = (total < min_trades)
        row = (
            f"{sig:<32} {r:>5} {w:>5} {total:>5}"
            f"  {acc_str}  {sd_str}  {attr_str}"
        )
        print(dim(row) if dim_row else row)


# ---------------------------------------------------------------------------
# Section 2: Version-by-version stability sparklines
# ---------------------------------------------------------------------------

def print_stability(signal_stats: dict, versions: list[str]):
    section("2. VERSION-BY-VERSION STABILITY  (signals in 3+ versions)")

    print()
    # Find signals present in 3+ versions
    qualifying = []
    for sig, stats in signal_stats.items():
        bv = stats.get("by_version", {})
        present_in = [ver for ver in versions
                      if (bv.get(ver, {}).get("right", 0) + bv.get(ver, {}).get("wrong", 0)) > 0]
        if len(present_in) >= 3:
            qualifying.append((sig, stats, present_in))

    qualifying.sort(key=lambda x: x[0])

    if not qualifying:
        print(dim("  No signals found in 3+ versions."))
        return

    max_sig_len = max(len(sig) for sig, _, _ in qualifying)
    for sig, stats, _ in qualifying:
        bv = stats.get("by_version", {})
        parts = []
        for ver in versions:
            entry = bv.get(ver, {})
            r = entry.get("right", 0)
            w = entry.get("wrong", 0)
            total = r + w
            if total == 0:
                parts.append(f"{dim(ver)}:{dim('----')}")
            else:
                acc = accuracy(r, w)
                parts.append(f"{ver}:{sparkbar(acc)}")
        print(f"  {sig:<{max_sig_len}}  " + "  ".join(parts))


# ---------------------------------------------------------------------------
# Section 3: Regime-conditional accuracy
# ---------------------------------------------------------------------------

def print_regime_accuracy(signal_stats: dict, min_trades: int):
    section("3. REGIME-CONDITIONAL ACCURACY")

    # Collect all regimes present
    all_regimes: set[str] = set()
    for stats in signal_stats.values():
        all_regimes.update(stats.get("by_regime", {}).keys())
    regimes = sorted(all_regimes)

    print()
    # Header
    regime_col_w = 10
    sig_w = 28
    header_parts = [f"{'Signal':<{sig_w}}"]
    for regime in regimes:
        header_parts.append(f"  {regime:>{regime_col_w}}")
    print(bold("".join(header_parts)))
    print(dim("-" * (sig_w + (regime_col_w + 2) * len(regimes))))

    # Build rows — only signals with ≥ min_trades total
    rows = []
    for sig, stats in signal_stats.items():
        total = stats["right"] + stats["wrong"]
        if total < min_trades:
            continue
        rows.append((sig, stats))
    rows.sort(key=lambda x: x[0])

    for sig, stats in rows:
        br = stats.get("by_regime", {})
        row = f"{sig:<{sig_w}}"
        for regime in regimes:
            entry = br.get(regime, {})
            r = entry.get("right", 0)
            w = entry.get("wrong", 0)
            acc = accuracy(r, w)
            if acc is None:
                row += f"  {'n/a':>{regime_col_w}}"
            else:
                colored = color_accuracy(acc)
                # color_accuracy returns 6 chars + ANSI; pad around it
                row += f"  {colored:>{regime_col_w}}"
        print(row)


# ---------------------------------------------------------------------------
# Section 4: Actionable recommendations
# ---------------------------------------------------------------------------

def print_recommendations(signal_stats: dict, min_trades: int):
    section("4. ACTIONABLE RECOMMENDATIONS")

    zero_out = []
    boost    = []
    watch    = []
    thin     = []

    THIN_THRESHOLD = 10

    for sig, stats in signal_stats.items():
        total = stats["right"] + stats["wrong"]
        acc   = accuracy(stats["right"], stats["wrong"])

        if total < THIN_THRESHOLD:
            thin.append((sig, total, acc))
        elif acc is not None and acc < 40.0:
            zero_out.append((sig, total, acc))
        elif acc is not None and acc > 55.0:
            boost.append((sig, total, acc))
        elif acc is not None:
            watch.append((sig, total, acc))

    def _fmt_list(items, sort_key=None):
        if sort_key:
            items = sorted(items, key=sort_key)
        return ", ".join(f"{sig} ({acc:.1f}%, n={total})"
                         if acc is not None else f"{sig} (n={total})"
                         for sig, total, acc in items)

    print()
    if zero_out:
        zero_out.sort(key=lambda x: x[2] or 100)
        print(red(bold("  ZERO OUT  ")) + red(f"(< 40% accuracy, 10+ appearances):"))
        for sig, total, acc in zero_out:
            print(red(f"    - {sig:<32} acc={acc:.1f}%  n={total}"))
    else:
        print(green("  ZERO OUT: none — no signals below 40% with 10+ appearances"))

    print()
    if boost:
        boost.sort(key=lambda x: -(x[2] or 0))
        print(green(bold("  BOOST     ")) + green(f"(> 55% accuracy, 10+ appearances):"))
        for sig, total, acc in boost:
            print(green(f"    + {sig:<32} acc={acc:.1f}%  n={total}"))
    else:
        print(dim("  BOOST: none above 55% with 10+ appearances"))

    print()
    if watch:
        watch.sort(key=lambda x: -(x[2] or 0))
        print(yellow(bold("  WATCH     ")) + yellow("(45-55% accuracy — inconclusive):"))
        for sig, total, acc in watch:
            print(yellow(f"    ~ {sig:<32} acc={acc:.1f}%  n={total}"))
    else:
        print(dim("  WATCH: none"))

    print()
    if thin:
        thin.sort(key=lambda x: x[0])
        print(dim(bold("  THIN DATA ")) + dim("(< 10 appearances — insufficient evidence):"))
        for sig, total, acc in thin:
            acc_s = f"{acc:.1f}%" if acc is not None else "n/a"
            print(dim(f"    ? {sig:<32} acc={acc_s}  n={total}"))
    else:
        print(dim("  THIN DATA: none"))

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global NO_COLOR

    parser = argparse.ArgumentParser(
        description="Cross-version signal accuracy analysis (read-only, stdlib only)"
    )
    parser.add_argument(
        "--versions", required=True,
        help="Comma-separated list of versions, e.g. v107,v108,v109,v110"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour output"
    )
    parser.add_argument(
        "--min-trades", type=int, default=1,
        help="Filter signals seen fewer than N times from table (default: 1)"
    )
    args = parser.parse_args()

    NO_COLOR = args.no_color or not sys.stdout.isatty()

    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    base_dir = Path(__file__).parent.parent / "data" / "activation_traces"

    print(bold(f"\nOmega Cross-Version Signal Analysis"))
    print(dim(f"Versions requested : {', '.join(versions)}"))
    print(dim(f"Trace directory    : {base_dir}"))
    print(dim(f"Min trades filter  : {args.min_trades}"))
    print()

    traces = load_traces(versions, base_dir)

    if not traces:
        print(red("No closed trades found. Exiting."))
        sys.exit(1)

    print(dim(f"Total closed trades loaded: {len(traces)}"))

    signal_stats, versions_found = aggregate(traces, args.min_trades)

    print(dim(f"Versions with data : {', '.join(versions_found)}"))
    print(dim(f"Unique signals     : {len(signal_stats)}"))

    print_signal_accuracy(signal_stats, versions_found, args.min_trades)
    print_stability(signal_stats, versions_found)
    print_regime_accuracy(signal_stats, args.min_trades)
    print_recommendations(signal_stats, args.min_trades)

    print(bold(cyan("=" * 72)))
    print(bold("Analysis complete."))
    print()


if __name__ == "__main__":
    main()
