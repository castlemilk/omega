#!/usr/bin/env python3
"""
signal_heatmap.py — Deep ASCII dive into a single Victoria trade trace.

Usage:
    python3 scripts/signal_heatmap.py --version v110 --trade ARBUSDT [--cycle 38] [--direction long] [--no-color]
"""

import argparse
import json
import sys
from pathlib import Path

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
def magenta(t): return _c("35", t)

def pnl_color(v: float, text: str) -> str:
    if v > 0:  return green(text)
    if v < 0:  return red(text)
    return yellow(text)

# ── Data loading ──────────────────────────────────────────────────────────────

def load_traces(version: str, base: Path) -> list[dict]:
    path = base / "data" / "activation_traces" / f"{version}.jsonl"
    if not path.exists():
        print(red(f"[error] Trace file not found: {path}"), file=sys.stderr)
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

# ── Bar rendering ─────────────────────────────────────────────────────────────

BAR_WIDTH = 30

def signal_bar(weighted_value: float, alignment: int) -> str:
    """Render a colored bar proportional to abs(weighted_value), colored by alignment."""
    max_val = 2.0  # clip scale
    ratio = min(abs(weighted_value) / max_val, 1.0)
    filled = int(ratio * BAR_WIDTH)
    bar = "█" * filled + dim("░" * (BAR_WIDTH - filled))
    if alignment == 1:
        return green(bar)
    elif alignment == -1:
        return red(bar)
    else:
        return dim(bar)


def align_symbol(alignment: int) -> str:
    if alignment == 1:  return green("▲ +1")
    if alignment == -1: return red("▼ -1")
    return dim("── 0")


def mini_bar(value: float, width: int = 20) -> str:
    ratio = min(abs(value) / 2.0, 1.0)
    filled = int(ratio * width)
    b = "█" * filled + dim("░" * (width - filled))
    return pnl_color(value, b)

# ── Main print sections ───────────────────────────────────────────────────────

def print_header(t: dict) -> None:
    out = t.get("outcome", {})
    regime = t.get("regime", {})
    pnl = out.get("exit_pnl")
    pnl_str = fmt_pnl(pnl) if pnl is not None else dim("pending")

    print()
    print(bold(cyan("╔" + "═" * 68 + "╗")))
    print(bold(cyan("║")) + bold(f"  TRADE DEEP-DIVE: {t['ticker']}  {t['direction'].upper()}  cycle={t['cycle']}  {t['version']}") + bold(cyan("  ║")))
    print(bold(cyan("║")) + f"  Regime: {yellow(regime.get('label','?'))}  bear={regime.get('bear_prob',0):.2f}  bull={regime.get('bull_prob',0):.2f}  "
          f"crisis={regime.get('is_crisis',False)}  high_vol={regime.get('is_high_vol',False)}" + bold(cyan("  ║")))
    print(bold(cyan("║")) + f"  PnL: {pnl_str}" + bold(cyan("  ║")))
    print(bold(cyan("╚" + "═" * 68 + "╝")))
    print()


def print_signal_heatmap(t: dict) -> None:
    activations = t.get("activations", [])
    if not activations:
        print(dim("  No activations recorded."))
        return

    print(bold(cyan("── SIGNAL HEATMAP " + "─" * 50)))
    print(f"  {'Signal':<28} {'Raw':>8} {'RW':>7} {'FW':>7}  {'Bar (weighted_value)':<32} {'Align':>6}")
    print(f"  {dim('─' * 95)}")

    for act in activations:
        name = act.get("name", "?")
        raw = act.get("raw_value", 0.0)
        rw  = act.get("reinforcement_weight", 1.0)
        fw  = act.get("final_weight", 1.0)
        wv  = act.get("weighted_value", 0.0)
        al  = act.get("direction_alignment", 0)

        bar = signal_bar(wv, al)
        al_str = align_symbol(al)
        wv_label = f"{wv:+.4f}"

        print(f"  {name:<28} {raw:>8.4f} {rw:>7.3f} {fw:>7.3f}  {bar}  {dim(wv_label):>14}  {al_str}")
    print()


def print_composite(t: dict) -> None:
    comp = t.get("composite", {})
    thresh = t.get("thresholds", {})

    print(bold(cyan("── COMPOSITE PIPELINE " + "─" * 46)))
    raw = comp.get("raw", 0.0)
    dm  = comp.get("demeaned", 0.0)
    bm  = comp.get("basket_mean", 0.0)
    bs  = comp.get("basket_std", 0.0)
    wc  = comp.get("weighted_conviction", 0.0)

    lt  = thresh.get("long_thresh", 0.0)
    st  = thresh.get("short_thresh", 0.0)
    wct = thresh.get("wc_thresh", 0.0)
    gap = thresh.get("conviction_gap", 0.0)
    ts  = thresh.get("thresh_scale", 1.0)

    passed = wc >= wct
    thresh_label = green("PASS ✓") if passed else red("FAIL ✗")

    print(f"  raw composite     : {pnl_color(raw, f'{raw:+.6f}')}")
    print(f"  basket_mean       : {bm:+.6f}  basket_std={bs:.6f}")
    print(f"  demeaned          : {pnl_color(dm, f'{dm:+.6f}')}")
    print(f"  weighted_convict. : {pnl_color(wc, f'{wc:+.6f}')}  wc_thresh={wct:.4f}  [{thresh_label}]")
    print(f"  thresh_scale      : {ts:.4f}  long_thresh={lt:.4f}  short_thresh={st:.4f}")
    print(f"  conviction_gap    : {pnl_color(gap, f'{gap:+.6f}')}")
    print()


def print_filter_chain(t: dict) -> None:
    filters = t.get("filters", {})
    passed  = filters.get("passed", [])
    blocking = filters.get("blocking", "")
    decision = filters.get("decision", "?")

    print(bold(cyan("── FILTER CHAIN " + "─" * 52)))
    if passed:
        for p in passed:
            print(f"  {green('✓')} {p}")
    else:
        print(f"  {dim('(no filters recorded as passed)')}")

    if blocking:
        print(f"  {red('✗ BLOCKED BY:')} {red(blocking)}")
    else:
        print(f"  {green('✓ No blocking filters')}")

    dec_col = green(decision) if decision == "TRADE" else red(decision)
    print(f"  Decision: {bold(dec_col)}")
    print()


def print_geometry_temporal(t: dict) -> None:
    geo = t.get("geometry", {})
    tmp = t.get("temporal", {})

    geo_nonzero = {k: v for k, v in geo.items() if v != 0.0}
    tmp_nonzero = {k: v for k, v in tmp.items() if v != 0.0}

    if not geo_nonzero and not tmp_nonzero:
        return

    print(bold(cyan("── GEOMETRY / TEMPORAL " + "─" * 45)))
    if geo_nonzero:
        print(f"  Geometry:")
        for k, v in geo_nonzero.items():
            print(f"    {k:<28} {pnl_color(v, f'{v:+.6f}')}")
    if tmp_nonzero:
        print(f"  Temporal:")
        for k, v in tmp_nonzero.items():
            print(f"    {k:<28} {pnl_color(v, f'{v:+.6f}')}")
    print()


def print_execution(t: dict) -> None:
    ex = t.get("execution", {})
    if not ex:
        return
    print(bold(cyan("── EXECUTION " + "─" * 55)))
    print(f"  conviction_level : {bold(yellow(str(ex.get('conviction_level','?'))))}")
    print(f"  allocated_size   : {ex.get('allocated_size', 0.0):.2f}")
    print(f"  kelly_scale      : {ex.get('kelly_scale', 1.0):.4f}")
    print()


def print_attribution(t: dict) -> None:
    out = t.get("outcome", {})
    attr = out.get("attribution", {})

    if not attr:
        return

    print(bold(cyan("── PnL ATTRIBUTION " + "─" * 49)))
    sorted_attr = sorted(attr.items(), key=lambda x: abs(x[1]), reverse=True)
    max_abs = max(abs(v) for _, v in sorted_attr) if sorted_attr else 1.0

    print(f"  {'Signal':<28} {'PnL Contrib':>12}  {'Bar':<20}")
    print(f"  {dim('─' * 65)}")
    for sig, contrib in sorted_attr:
        ratio = abs(contrib) / max_abs if max_abs > 0 else 0
        filled = int(ratio * 20)
        bar_raw = "█" * filled + dim("░" * (20 - filled))
        bar_str = green(bar_raw) if contrib >= 0 else red(bar_raw)
        print(f"  {sig:<28} {fmt_pnl(contrib):>21}  {bar_str}")
    print()


def print_outcome(t: dict) -> None:
    out = t.get("outcome", {})
    if not out:
        print(dim("  No outcome recorded."))
        return

    pnl = out.get("exit_pnl")
    print(bold(cyan("── OUTCOME " + "─" * 57)))
    print(f"  PnL            : {fmt_pnl(pnl) if pnl is not None else dim('pending')}")
    print(f"  hold_cycles    : {out.get('hold_cycles', '?')}")
    print(f"  close_reason   : {dim(str(out.get('close_reason', '?')))}")
    nr = out.get("n_right", len(out.get("signals_right", [])))
    nw = out.get("n_wrong", len(out.get("signals_wrong", [])))
    total = nr + nw
    acc = nr / total * 100 if total > 0 else 0.0
    print(f"  signals_right  : {green(str(nr))}")
    print(f"  signals_wrong  : {red(str(nw))}")
    print(f"  signal acc     : {pnl_color(acc - 50, f'{acc:.1f}%')}")
    if out.get("signals_right"):
        print(f"  right signals  : {green(', '.join(out['signals_right']))}")
    if out.get("signals_wrong"):
        print(f"  wrong signals  : {red(', '.join(out['signals_wrong']))}")
    print()


def fmt_pnl(v):
    if v is None:
        return dim("n/a")
    s = f"{v:+.4f}"
    return pnl_color(v, s)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(description="Victoria signal heatmap — single trade deep-dive")
    parser.add_argument("--version", required=True, help="Training version e.g. v110")
    parser.add_argument("--trade", required=True, metavar="TICKER", help="Ticker symbol e.g. ARBUSDT")
    parser.add_argument("--cycle", type=int, default=None, help="Specific cycle number")
    parser.add_argument("--direction", default=None, choices=["long", "short"], help="Trade direction")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    USE_COLOR = not args.no_color

    base = Path(__file__).resolve().parent.parent
    traces = load_traces(args.version, base)
    if not traces:
        sys.exit(1)

    # Filter by ticker
    matches = [t for t in traces if t.get("ticker", "").upper() == args.trade.upper()]

    if args.direction:
        matches = [t for t in matches if t.get("direction") == args.direction]

    if args.cycle is not None:
        matches = [t for t in matches if t.get("cycle") == args.cycle]

    if not matches:
        print(red(f"No trace found for ticker={args.trade}"
                  + (f" cycle={args.cycle}" if args.cycle else "")
                  + (f" direction={args.direction}" if args.direction else "")))
        available = sorted({t.get("ticker") for t in traces})
        print(dim(f"Available tickers: {', '.join(available)}"))
        sys.exit(1)

    # Pick most recent by cycle if multiple
    t = max(matches, key=lambda x: x.get("cycle", 0))

    print_header(t)
    print_signal_heatmap(t)
    print_composite(t)
    print_filter_chain(t)
    print_geometry_temporal(t)
    print_execution(t)
    print_attribution(t)
    print_outcome(t)


if __name__ == "__main__":
    main()
