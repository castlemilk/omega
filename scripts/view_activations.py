#!/usr/bin/env python3
"""
scripts/view_activations.py
CLI viewer for activation traces.

Usage:
    python scripts/view_activations.py --version v107
    python scripts/view_activations.py --version v107 --ticker ETHUSDT
    python scripts/view_activations.py --version v107 --limit 5 --direction short
    python scripts/view_activations.py --version v107 --trade-id abc123
    python scripts/view_activations.py --version v107 --summary

Examples:
    # Show last 3 completed trades for any ticker
    python scripts/view_activations.py --version v107 --limit 3

    # Show only ETHUSDT shorts
    python scripts/view_activations.py --version v107 --ticker ETHUSDT --direction short

    # Show signal-level summary (aggregate attribution across all trades)
    python scripts/view_activations.py --version v107 --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_WHITE = "\033[97m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + _RESET


def _pnl_color(v: float | None) -> str:
    if v is None:
        return _c("n/a", _DIM)
    if v > 0:
        return _c(f"+${v:.2f}", _GREEN, _BOLD)
    if v < 0:
        return _c(f"-${abs(v):.2f}", _RED, _BOLD)
    return _c("$0.00", _DIM)


def _mult_color(v: float) -> str:
    if v > 1.05:
        return _c(f"{v:.3f}x", _GREEN)
    if v < 0.95:
        return _c(f"{v:.3f}x", _RED)
    return _c(f"{v:.3f}x", _DIM)


def _align_sym(a: int) -> str:
    if a > 0:
        return _c("▲", _GREEN)
    if a < 0:
        return _c("▼", _RED)
    return _c("·", _DIM)


# ---------------------------------------------------------------------------
# Print one trace
# ---------------------------------------------------------------------------

def print_trace(rec: dict, no_color: bool = False) -> None:
    if no_color:
        global _c
        _c = lambda t, *_: str(t)

    # Header
    outcome = rec.get("outcome", {})
    pnl = outcome.get("exit_pnl")
    direction = rec.get("direction", "?")
    ticker = rec.get("ticker", "?")
    cycle = rec.get("cycle", "?")
    regime = rec.get("regime", {}).get("label", "?")
    decision = rec.get("filters", {}).get("decision", "?")

    dir_color = _GREEN if direction == "long" else _RED
    dec_color = _GREEN if decision == "TRADE" else _YELLOW

    print()
    print(_c("═" * 70, _BOLD))
    print(
        f"  {_c(ticker, _BOLD, _WHITE)}  {_c(direction.upper(), dir_color, _BOLD)}  "
        f"cycle={_c(cycle, _CYAN)}  regime={_c(regime, _MAGENTA)}  "
        f"decision={_c(decision, dec_color)}"
    )
    if pnl is not None:
        hold = outcome.get("hold_cycles", "?")
        reason = outcome.get("close_reason", "")
        print(f"  PnL: {_pnl_color(pnl)}   hold={hold} cycles   close_reason={reason or 'age'}")
    else:
        print(f"  {_c('(open — no exit yet)', _DIM)}")
    print(_c("─" * 70, _DIM))

    # Composite + thresholds
    comp = rec.get("composite", {})
    thresh = rec.get("thresholds", {})
    wc = comp.get("weighted_conviction", 0.0)
    gap = thresh.get("conviction_gap", 0.0)
    applicable = thresh.get("long_thresh" if direction == "long" else "short_thresh", 0.0)
    gap_color = _GREEN if (gap or 0) >= 0 else _RED

    demeaned = comp.get("demeaned", 0)
    print(
        f"  composite={_c(f'{demeaned:.4f}', _CYAN)}  "
        f"w_conv={_c(f'{wc:.4f}', _CYAN)}  "
        f"threshold={_c(f'{applicable:.4f}', _YELLOW)}  "
        f"gap={_c(f'{gap:+.4f}', gap_color)}  "
        f"scale={thresh.get('thresh_scale', 1.0):.2f}"
    )

    # Regime
    regime_d = rec.get("regime", {})
    print(
        f"  bear_prob={regime_d.get('bear_prob', -1):.2f}  "
        f"bull_prob={regime_d.get('bull_prob', -1):.2f}  "
        f"crisis={regime_d.get('is_crisis', False)}  "
        f"high_vol={regime_d.get('is_high_vol', False)}"
    )

    # Geometry + temporal (if non-zero)
    geo = rec.get("geometry", {})
    temp = rec.get("temporal", {})
    geo_parts = [f"{k}={v:.3f}" for k, v in geo.items() if v]
    temp_parts = [f"{k}={v:.3f}" for k, v in temp.items() if v]
    if geo_parts or temp_parts:
        print(f"  geometry: {', '.join(geo_parts) or 'n/a'}")
        print(f"  temporal: {', '.join(temp_parts) or 'n/a'}")

    # Filter chain
    filters = rec.get("filters", {})
    blocking = filters.get("blocking", "")
    passed = filters.get("passed", [])
    if blocking:
        print(f"  filters_passed={passed}  {_c('BLOCKED BY: ' + blocking, _RED)}")

    # Signals table
    activations = rec.get("activations", [])
    if activations:
        print()
        print(
            f"  {'Signal':<32} {'Raw':>8} {'Reinf':>8} {'IC':>6} {'Final':>8} "
            f"{'WtdVal':>8} {'Dir':>4}"
        )
        print(_c("  " + "─" * 68, _DIM))
        for act in activations:
            name = act["name"]
            raw = act.get("raw_value", 0.0) or 0.0
            rw = act.get("reinforcement_weight", 1.0) or 1.0
            ic = act.get("ic_weight", 1.0) or 1.0
            fw = act.get("final_weight", 1.0) or 1.0
            wv = act.get("weighted_value", 0.0) or 0.0
            align = act.get("direction_alignment", 0)

            # Color raw by sign
            raw_s = _c(f"{raw:+.4f}", _GREEN if raw > 0 else (_RED if raw < 0 else _DIM))
            wv_s = _c(f"{wv:+.4f}", _GREEN if wv > 0 else (_RED if wv < 0 else _DIM))

            print(
                f"  {name:<32} {raw_s:>8}  {_mult_color(rw):>8}  {ic:>6.3f}  "
                f"{fw:>8.3f}  {wv_s:>8}  {_align_sym(align):>4}"
            )

    # Outcome: signals right / wrong
    if pnl is not None:
        n_right = len(outcome.get("signals_right", []))
        n_wrong = len(outcome.get("signals_wrong", []))
        right_names = ", ".join(outcome.get("signals_right", [])[:5]) or "none"
        wrong_names = ", ".join(outcome.get("signals_wrong", [])[:5]) or "none"
        print()
        print(
            f"  {_c('✓', _GREEN)} {n_right} signals correct: {_c(right_names, _GREEN)}"
        )
        print(
            f"  {_c('✗', _RED)} {n_wrong} signals wrong:   {_c(wrong_names, _RED)}"
        )

    # Attribution
    attr = outcome.get("attribution", {})
    if attr:
        print()
        print(f"  {_c('Attribution (PnL decomposition):', _BOLD)}")
        for sig_name, contrib in sorted(attr.items(), key=lambda x: abs(x[1] or 0), reverse=True)[:8]:
            bar_len = int(abs(contrib or 0) / max(abs(pnl or 1), 0.01) * 20)
            bar = ("█" * bar_len).ljust(20)
            bar_c = _c(bar, _GREEN if (contrib or 0) > 0 else _RED)
            print(f"    {sig_name:<32} {_pnl_color(contrib):>10}  {bar_c}")

    print()


# ---------------------------------------------------------------------------
# Summary: aggregate attribution across all trades
# ---------------------------------------------------------------------------

def print_summary(traces: list[dict]) -> None:
    completed = [t for t in traces if t.get("outcome", {}).get("exit_pnl") is not None]
    if not completed:
        print("No completed trades found.")
        return

    print(_c(f"\n{'═'*70}", _BOLD))
    print(_c(f"  SUMMARY — {len(completed)} completed trades", _BOLD, _WHITE))
    print(_c(f"{'─'*70}", _DIM))

    total_pnl = sum(t["outcome"]["exit_pnl"] or 0 for t in completed)
    winners = [t for t in completed if (t["outcome"]["exit_pnl"] or 0) > 0]
    print(
        f"  Total PnL: {_pnl_color(total_pnl)}   "
        f"WR: {_c(f'{len(winners)/len(completed)*100:.0f}%', _CYAN)}  "
        f"({len(winners)}/{len(completed)} trades)"
    )

    # Aggregate attribution
    totals: dict[str, list[float]] = {}
    for t in completed:
        for k, v in (t["outcome"].get("attribution") or {}).items():
            if v is not None:
                totals.setdefault(k, []).append(v)

    if totals:
        print(f"\n  {_c('Signal attribution (total PnL contribution across all trades):', _BOLD)}")
        ranked = sorted(totals.items(), key=lambda x: abs(sum(x[1])), reverse=True)
        for name, contribs in ranked[:12]:
            total = sum(contribs)
            avg = total / len(contribs)
            pct = total / abs(total_pnl) * 100 if total_pnl else 0
            bar_len = int(abs(pct) / 5)
            bar = ("█" * min(bar_len, 20)).ljust(20)
            bar_c = _c(bar, _GREEN if total > 0 else _RED)
            print(
                f"    {name:<32} {_pnl_color(total):>10}  avg={_pnl_color(avg):>8}  "
                f"n={len(contribs):<3}  {bar_c} {pct:+.0f}%"
            )

    # Right/wrong signal tally
    right_counts: dict[str, int] = {}
    wrong_counts: dict[str, int] = {}
    for t in completed:
        for name in t["outcome"].get("signals_right", []):
            right_counts[name] = right_counts.get(name, 0) + 1
        for name in t["outcome"].get("signals_wrong", []):
            wrong_counts[name] = wrong_counts.get(name, 0) + 1

    all_names = set(right_counts) | set(wrong_counts)
    if all_names:
        print(f"\n  {_c('Signal accuracy (right vs wrong calls):', _BOLD)}")
        rows = []
        for name in sorted(all_names):
            r = right_counts.get(name, 0)
            w = wrong_counts.get(name, 0)
            total_calls = r + w
            acc = r / total_calls if total_calls else 0
            rows.append((name, r, w, acc))
        rows.sort(key=lambda x: x[3], reverse=True)
        for name, r, w, acc in rows[:12]:
            bar_len = int(acc * 20)
            bar = ("█" * bar_len + "░" * (20 - bar_len))
            acc_color = _GREEN if acc > 0.6 else (_RED if acc < 0.4 else _YELLOW)
            print(
                f"    {name:<32}  {_c(f'{acc*100:.0f}%', acc_color):>6}  "
                f"{_c(str(r), _GREEN)}✓ {_c(str(w), _RED)}✗  {bar}"
            )

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_traces(version: str) -> list[dict]:
    path = Path(f"data/activation_traces/{version}.jsonl")
    if not path.exists():
        print(f"No activation trace file found: {path}", file=sys.stderr)
        sys.exit(1)
    traces = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return traces


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View Victoria activation traces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", required=True, help="Training version (e.g. v107)")
    parser.add_argument("--ticker", help="Filter by ticker symbol (e.g. ETHUSDT)")
    parser.add_argument("--direction", choices=["long", "short"], help="Filter by direction")
    parser.add_argument("--limit", type=int, default=10, help="Max traces to show (default 10)")
    parser.add_argument("--trade-id", dest="trade_id", help="Show specific trade by ID")
    parser.add_argument("--summary", action="store_true", help="Print aggregate summary")
    parser.add_argument("--completed", action="store_true", help="Only show completed trades")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--json", action="store_true", dest="raw_json", help="Print raw JSON")
    args = parser.parse_args()

    traces = load_traces(args.version)
    print(f"Loaded {len(traces)} traces from data/activation_traces/{args.version}.jsonl")

    if args.summary:
        print_summary(traces)
        return

    # Filter
    filtered = traces
    if args.ticker:
        filtered = [t for t in filtered if t.get("ticker") == args.ticker]
    if args.direction:
        filtered = [t for t in filtered if t.get("direction") == args.direction]
    if args.completed:
        filtered = [t for t in filtered if t.get("outcome", {}).get("exit_pnl") is not None]
    if args.trade_id:
        filtered = [t for t in filtered if t.get("trade_id") == args.trade_id]

    # Show most recent last
    shown = filtered[-args.limit:]
    print(f"Showing {len(shown)} of {len(filtered)} matching traces\n")

    for rec in shown:
        if args.raw_json:
            print(json.dumps(rec, indent=2))
        else:
            print_trace(rec, no_color=args.no_color)


if __name__ == "__main__":
    main()
