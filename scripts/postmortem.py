#!/usr/bin/env python3
"""
postmortem.py — Post-mortem analysis for Victoria activation traces.

Usage:
    python3 scripts/postmortem.py --version v110 [--top N] [--min-pnl -5.0] [--no-color]
"""

import argparse
import json
import csv
import sys
from pathlib import Path
from collections import defaultdict

# ── ANSI color helpers ────────────────────────────────────────────────────────

USE_COLOR = True

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)
def cyan(t):   return _c("36", t)

def pnl_color(v: float, text: str) -> str:
    if v > 0:  return green(text)
    if v < 0:  return red(text)
    return yellow(text)

# ── Data loading ──────────────────────────────────────────────────────────────

def load_traces(version: str, base: Path) -> list[dict]:
    path = base / "data" / "activation_traces" / f"{version}.jsonl"
    if not path.exists():
        print(red(f"[warn] Trace file not found: {path}"), file=sys.stderr)
        return []
    traces = []
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(dim(f"[warn] Skipping malformed line {lineno}: {e}"), file=sys.stderr)
    return traces


def load_trades_csv(version: str, base: Path) -> list[dict]:
    path = base / "data" / f"{version}_trades.csv"
    if not path.exists():
        print(red(f"[warn] Trades CSV not found: {path}"), file=sys.stderr)
        return []
    rows = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_reinforcement(base: Path) -> dict:
    path = base / "data" / "reinforcement_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(dim(f"[warn] Could not load reinforcement_state.json: {e}"), file=sys.stderr)
        return {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_pnl(v: float) -> str:
    s = f"{v:+.2f}"
    return pnl_color(v, s)


def bar(value: float, width: int = 20, char: str = "█") -> str:
    filled = min(int(abs(value) * width), width)
    return char * filled + dim("░" * (width - filled))


def _completed(traces: list[dict]) -> list[dict]:
    return [t for t in traces if t.get("outcome") and t["outcome"].get("exit_pnl") is not None]

# ── Section printers ──────────────────────────────────────────────────────────

def print_summary(traces: list[dict], csv_rows: list[dict]) -> None:
    completed = _completed(traces)
    if not completed:
        print(yellow("No completed traces found."))
        return

    pnls = [t["outcome"]["exit_pnl"] for t in completed]
    wins = [p for p in pnls if p > 0]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls)
    wr = len(wins) / len(pnls) * 100

    best_t = max(completed, key=lambda t: t["outcome"]["exit_pnl"])
    worst_t = min(completed, key=lambda t: t["outcome"]["exit_pnl"])

    print(bold(cyan("═" * 60)))
    print(bold(cyan("  SUMMARY")))
    print(bold(cyan("═" * 60)))
    print(f"  Completed trades : {bold(str(len(completed)))}")
    print(f"  Win rate         : {pnl_color(wr - 50, f'{wr:.1f}%')}")
    print(f"  Total PnL        : {fmt_pnl(total_pnl)}")
    print(f"  Avg PnL          : {fmt_pnl(avg_pnl)}")
    print()
    b = best_t
    w = worst_t
    print(f"  Top winner  : {green(b['ticker'])} {b['direction']} c{b['cycle']}  {fmt_pnl(b['outcome']['exit_pnl'])}")
    print(f"  Top loser   : {red(w['ticker'])} {w['direction']} c{w['cycle']}  {fmt_pnl(w['outcome']['exit_pnl'])}")
    print()


def print_top_losers(traces: list[dict], top_n: int, min_pnl: float) -> None:
    completed = _completed(traces)
    losers = sorted(completed, key=lambda t: t["outcome"]["exit_pnl"])
    losers = [t for t in losers if t["outcome"]["exit_pnl"] <= min_pnl][:top_n]

    print(bold(cyan("═" * 60)))
    print(bold(cyan(f"  TOP {top_n} LOSERS  (exit_pnl ≤ {min_pnl:+.2f})")))
    print(bold(cyan("═" * 60)))

    if not losers:
        print(dim("  No losers matching filter."))
        print()
        return

    for i, t in enumerate(losers, 1):
        out = t["outcome"]
        regime = t.get("regime", {}).get("label", "?")
        gap = t.get("thresholds", {}).get("conviction_gap", 0.0)
        print(f"  {bold(str(i))}. {red(t['ticker'])} | {t['direction']} | cycle {t['cycle']} | "
              f"regime={yellow(regime)} | gap={gap:.3f}")
        print(f"     PnL: {fmt_pnl(out['exit_pnl'])}  hold={out.get('hold_cycles','?')}  "
              f"reason={dim(str(out.get('close_reason','?')))}")

        # Signal breakdown
        attr = out.get("attribution", {})
        rights = set(out.get("signals_right", []))
        wrongs = set(out.get("signals_wrong", []))

        if rights or wrongs:
            all_sigs = list(rights | wrongs)
            print(f"     {'Signal':<28} {'Outcome':<10} {'Attribution':>12}")
            print(f"     {dim('-'*54)}")
            for sig in sorted(all_sigs):
                if sig in rights:
                    outcome_str = green("  RIGHT")
                else:
                    outcome_str = red("  WRONG")
                attr_v = attr.get(sig)
                attr_str = fmt_pnl(attr_v) if attr_v is not None else dim("     n/a")
                print(f"     {sig:<28} {outcome_str:<20} {attr_str:>12}")
        print()


def print_signal_scorecard(traces: list[dict], reinf: dict) -> None:
    completed = _completed(traces)
    scores = reinf.get("scores", {})

    sig_right: dict[str, int] = defaultdict(int)
    sig_wrong: dict[str, int] = defaultdict(int)
    sig_attr:  dict[str, float] = defaultdict(float)
    sig_attr_n: dict[str, int] = defaultdict(int)

    for t in completed:
        out = t["outcome"]
        attr = out.get("attribution", {})
        for s in out.get("signals_right", []):
            sig_right[s] += 1
            if s in attr:
                sig_attr[s] += attr[s]
                sig_attr_n[s] += 1
        for s in out.get("signals_wrong", []):
            sig_wrong[s] += 1
            if s in attr:
                sig_attr[s] += attr[s]
                sig_attr_n[s] += 1

    all_sigs = sorted(set(list(sig_right.keys()) + list(sig_wrong.keys())))

    print(bold(cyan("═" * 70)))
    print(bold(cyan("  SIGNAL SCORECARD")))
    print(bold(cyan("═" * 70)))
    hdr = f"  {'Signal':<28} {'Right':>5} {'Wrong':>5} {'Acc%':>6} {'TotalAttr':>10} {'AvgAttr':>9} {'RW':>8}"
    print(bold(hdr))
    print(f"  {dim('─'*66)}")

    for sig in all_sigs:
        r = sig_right[sig]
        w = sig_wrong[sig]
        total = r + w
        acc = r / total * 100 if total > 0 else 0.0
        total_attr = sig_attr[sig] if sig in sig_attr else None
        avg_attr = (sig_attr[sig] / sig_attr_n[sig]) if sig_attr_n[sig] > 0 else None
        rw = scores.get(sig)

        acc_str = pnl_color(acc - 50, f"{acc:.1f}%")
        ta_str = fmt_pnl(total_attr) if total_attr is not None else dim("     n/a")
        aa_str = fmt_pnl(avg_attr) if avg_attr is not None else dim("    n/a")
        rw_str = pnl_color(rw, f"{rw:+.3f}") if rw is not None else dim("    n/a")

        print(f"  {sig:<28} {r:>5} {w:>5} {acc_str:>15} {ta_str:>19} {aa_str:>18} {rw_str:>17}")

    print()


def print_regime_breakdown(traces: list[dict]) -> None:
    completed = _completed(traces)

    by_regime: dict[str, list[float]] = defaultdict(list)
    for t in completed:
        label = t.get("regime", {}).get("label", "unknown")
        by_regime[label].append(t["outcome"]["exit_pnl"])

    print(bold(cyan("═" * 60)))
    print(bold(cyan("  REGIME BREAKDOWN")))
    print(bold(cyan("═" * 60)))
    print(f"  {'Regime':<12} {'Trades':>6} {'WinRate':>8} {'TotalPnL':>10} {'AvgPnL':>9}")
    print(f"  {dim('─'*50)}")

    for label in sorted(by_regime.keys()):
        pnls = by_regime[label]
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / len(pnls) * 100
        total = sum(pnls)
        avg = total / len(pnls)
        print(f"  {yellow(label):<21} {len(pnls):>6} {pnl_color(wr-50, f'{wr:.1f}%'):>17} "
              f"{fmt_pnl(total):>19} {fmt_pnl(avg):>18}")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(description="Victoria post-mortem analysis")
    parser.add_argument("--version", required=True, help="Training version, e.g. v110")
    parser.add_argument("--top", type=int, default=10, help="Number of top losers to show")
    parser.add_argument("--min-pnl", type=float, default=float("inf"),
                        help="Only show losers with PnL <= this value (default: all losers)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args()

    USE_COLOR = not args.no_color

    base = Path(__file__).resolve().parent.parent
    version = args.version

    traces = load_traces(version, base)
    csv_rows = load_trades_csv(version, base)
    reinf = load_reinforcement(base)

    if not traces:
        print(red(f"No traces loaded for {version}. Aborting."))
        sys.exit(1)

    completed = _completed(traces)
    print()
    print(bold(f"  Victoria Post-Mortem — {version}  ({len(traces)} traces, {len(completed)} completed)"))
    print()

    # Determine min_pnl filter: if not set, show any loser (< 0)
    min_pnl = args.min_pnl if args.min_pnl != float("inf") else 0.0

    print_summary(traces, csv_rows)
    print_top_losers(traces, args.top, min_pnl)
    print_signal_scorecard(traces, reinf)
    print_regime_breakdown(traces)


if __name__ == "__main__":
    main()
