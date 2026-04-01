"""
scripts/analyze_training.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Training-run JSONL analyzer — instant diagnostics for an entire run.

Reads /tmp/{version}_metrics.jsonl (per-cycle metrics) plus companion files
from data/{version}_trades.csv, data/{version}_results.json, and
data/{version}_progress.json when available.

Usage:
    python3 scripts/analyze_training.py v32
    python3 scripts/analyze_training.py --compare v31 v32
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
METRICS_DIR = Path("/tmp")

# In a git worktree, run-data files (trades CSV, results JSON) live in the main
# repo's data/ directory and are not checked out into the worktree.  Resolve the
# shared git dir to find the canonical data location; fall back to local data/.
import subprocess as _sp

def _resolve_data_dir() -> Path:
    try:
        git_common = Path(
            _sp.check_output(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=REPO_ROOT, stderr=_sp.DEVNULL,
            ).decode().strip()
        )
        main_data = git_common.parent / "data"
        if main_data.exists():
            return main_data
    except Exception:
        pass
    return REPO_ROOT / "data"

DATA_DIR = _resolve_data_dir()

# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"


def c(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}"


def bold(text: str) -> str:
    return c(text, BOLD)


def section(title: str, width: int = 68) -> str:
    bar = "─" * width
    return f"\n{CYAN}{bar}{RESET}\n{BOLD}{CYAN}  {title}{RESET}\n{CYAN}{bar}{RESET}"


# ── Data loading ──────────────────────────────────────────────────────────────


def load_jsonl(version: str) -> list[dict]:
    path = METRICS_DIR / f"{version}_metrics.jsonl"
    if not path.exists():
        sys.exit(f"{RED}✗ Not found: {path}{RESET}")
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        sys.exit(f"{RED}✗ Empty metrics file: {path}{RESET}")
    return rows


def load_trades(version: str) -> list[dict]:
    path = DATA_DIR / f"{version}_trades.csv"
    if not path.exists():
        return []
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            # cast numeric fields
            for field in ("pnl", "size", "entry_price", "exit_price", "slippage", "hold_cycles"):
                try:
                    row[field] = float(row[field])
                except (ValueError, KeyError):
                    pass
            rows.append(row)
    return rows


def load_results(version: str) -> dict:
    path = DATA_DIR / f"{version}_results.json"
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def load_progress(version: str) -> list[dict]:
    path = DATA_DIR / f"{version}_progress.json"
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f)


# ── Sparkline ─────────────────────────────────────────────────────────────────

SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 60) -> str:
    if not values:
        return ""
    # downsample to width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values
    lo, hi = min(sampled), max(sampled)
    span = hi - lo or 1.0
    chars = []
    for v in sampled:
        idx = int((v - lo) / span * (len(SPARK_CHARS) - 1))
        chars.append(SPARK_CHARS[idx])
    return "".join(chars)


# ── Histogram ─────────────────────────────────────────────────────────────────


def histogram(values: list[float], bins: int = 10, bar_width: int = 30) -> list[str]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    span = hi - lo
    if span == 0:
        return [f"  all values = {lo:.4f}"]
    step = span / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    lines = []
    for i, count in enumerate(counts):
        bucket_lo = lo + i * step
        bucket_hi = bucket_lo + step
        bar = "█" * int(count / max_count * bar_width)
        lines.append(
            f"  [{bucket_lo:+.3f}, {bucket_hi:+.3f})  {bar:<{bar_width}}  {count:4d}"
        )
    return lines


# ── Formatting helpers ────────────────────────────────────────────────────────


def pct(n: int, total: int) -> str:
    if total == 0:
        return " 0.0%"
    return f"{100 * n / total:5.1f}%"


def fmt_pnl(v: float) -> str:
    s = f"${v:+.2f}"
    return c(s, GREEN if v >= 0 else RED)


def bar_chart(items: list[tuple[str, int]], total: int, bar_width: int = 24) -> list[str]:
    lines = []
    max_count = max((c for _, c in items), default=1) or 1
    for label, count in sorted(items, key=lambda x: -x[1]):
        bar = "█" * int(count / max_count * bar_width)
        lines.append(f"  {label:<18} {bar:<{bar_width}} {count:5d}  ({pct(count, total)})")
    return lines


# ── Core analysis ─────────────────────────────────────────────────────────────


def analyse(version: str) -> dict[str, Any]:
    rows = load_jsonl(version)
    trades = load_trades(version)
    results = load_results(version)
    progress = load_progress(version)

    # ── Time range
    timestamps = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
            timestamps.append(ts)
        except Exception:
            pass

    ts_first = min(timestamps) if timestamps else None
    ts_last = max(timestamps) if timestamps else None
    elapsed_s = (ts_last - ts_first).total_seconds() if (ts_first and ts_last) else None

    # ── Cycle stats
    elapsed_values = [r["elapsed_s"] for r in rows if "elapsed_s" in r]
    avg_cycle_time = statistics.mean(elapsed_values) if elapsed_values else 0

    # ── Composite score
    scores = [r["composite_score"] for r in rows if r.get("composite_score") is not None]

    # ── Conviction distribution
    conviction_counts = Counter(r.get("conviction", "n/a") for r in rows)

    # ── Trade action distribution
    action_counts = Counter(r.get("trade_action", "n/a") for r in rows)

    # ── Regime distribution
    regime_counts = Counter(r.get("regime", "unknown") for r in rows)

    # ── Blocker analysis
    blockers: Counter = Counter()
    for r in rows:
        if r.get("trade_action") == "HOLD":
            if r.get("sit_out_reason") and r["sit_out_reason"] not in (None, "normal", ""):
                blockers[f"sit_out:{r['sit_out_reason']}"] += 1
            elif not r.get("ring1_pass", True):
                blockers["Ring-1 fail"] += 1
            elif r.get("breaker_tripped"):
                blockers["circuit_breaker"] += 1
            elif r.get("conviction") == "HOLD":
                blockers["conviction=HOLD"] += 1
            elif str(r.get("conviction", "")).lower() in ("n/a", "none", ""):
                blockers["conviction=n/a"] += 1
            else:
                blockers[f"conviction={r.get('conviction')}"] += 1

    # ── Ring-1 / breaker stats
    ring1_fails = sum(1 for r in rows if not r.get("ring1_pass", True))
    breaker_trips = sum(1 for r in rows if r.get("breaker_tripped"))

    # ── Signal activity (active_signals count over time)
    sig_counts = [r["active_signals"] for r in rows if "active_signals" in r]
    sig_min = min(sig_counts) if sig_counts else 0
    sig_max = max(sig_counts) if sig_counts else 0
    sig_mean = statistics.mean(sig_counts) if sig_counts else 0

    # ── Trade metrics (from CSV or results JSON)
    trade_stats: dict[str, Any] = {}
    if trades:
        pnls = [t["pnl"] for t in trades if isinstance(t.get("pnl"), float)]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        total_pnl = sum(pnls)
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        win_rate = wins / len(pnls) if pnls else 0

        side_counts = Counter(t.get("side", "?") for t in trades)
        symbol_counts = Counter(t.get("symbol", "?") for t in trades)

        trade_stats = {
            "total": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "side_counts": side_counts,
            "symbol_counts": symbol_counts,
        }
    elif results.get("trades"):
        rt = results["trades"]
        trade_stats = {
            "total": rt.get("total_closed", 0),
            "wins": round(rt.get("win_rate", 0) * rt.get("total_closed", 0)),
            "losses": None,
            "win_rate": rt.get("win_rate", 0),
            "total_pnl": rt.get("total_pnl_usd", 0),
            "gross_profit": rt.get("gross_profit", 0),
            "gross_loss": rt.get("gross_loss", 0),
            "profit_factor": rt.get("profit_factor", 0),
            "side_counts": Counter(
                {"long": rt.get("long_trades", 0), "short": rt.get("short_trades", 0)}
            ),
            "symbol_counts": Counter(),
        }

    # ── PnL curve (from progress JSON)
    pnl_curve: list[float] = []
    if progress:
        pnl_curve = [p["total_pnl"] for p in progress if "total_pnl" in p]
    elif trades:
        # cumulative from trades sorted by cycle
        sorted_trades = sorted(trades, key=lambda t: int(t.get("cycle", 0)))
        cum = 0.0
        for t in sorted_trades:
            if isinstance(t.get("pnl"), float):
                cum += t["pnl"]
                pnl_curve.append(cum)

    return {
        "version": version,
        "rows": rows,
        "n_cycles": len(rows),
        "ts_first": ts_first,
        "ts_last": ts_last,
        "elapsed_s": elapsed_s,
        "avg_cycle_time": avg_cycle_time,
        "scores": scores,
        "conviction_counts": conviction_counts,
        "action_counts": action_counts,
        "regime_counts": regime_counts,
        "blockers": blockers,
        "ring1_fails": ring1_fails,
        "breaker_trips": breaker_trips,
        "sig_min": sig_min,
        "sig_max": sig_max,
        "sig_mean": sig_mean,
        "trade_stats": trade_stats,
        "pnl_curve": pnl_curve,
        "results": results,
    }


# ── Report printing ───────────────────────────────────────────────────────────


def fmt_duration(s: float) -> str:
    if s is None:
        return "n/a"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def print_report(a: dict, width: int = 68) -> None:
    v = a["version"]
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  TRAINING RUN ANALYSIS  —  {v.upper()}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")

    # ── Run overview
    print(section("RUN OVERVIEW", width))
    ts_f = a["ts_first"].strftime("%Y-%m-%d %H:%M:%S UTC") if a["ts_first"] else "n/a"
    ts_l = a["ts_last"].strftime("%Y-%m-%d %H:%M:%S UTC") if a["ts_last"] else "n/a"
    print(f"  {'Cycles':<28} {bold(str(a['n_cycles']))}")
    print(f"  {'Start':<28} {ts_f}")
    print(f"  {'End':<28} {ts_l}")
    print(f"  {'Wall time':<28} {fmt_duration(a['elapsed_s'])}")
    print(f"  {'Avg cycle time':<28} {a['avg_cycle_time']:.2f}s")

    # ── Trade summary
    ts = a["trade_stats"]
    if ts:
        print(section("TRADE SUMMARY", width))
        pf = ts["profit_factor"]
        pf_str = f"{pf:.3f}" if pf != float("inf") else "∞"
        pf_col = GREEN if pf >= 1.0 else RED
        wr_col = GREEN if ts["win_rate"] >= 0.5 else RED
        wr_str = f"{ts['win_rate']*100:.1f}%"
        gp_str = f"${ts['gross_profit']:.2f}"
        gl_str = f"${ts['gross_loss']:.2f}"
        print(f"  {'Closed trades':<28} {bold(str(ts['total']))}")
        print(f"  {'Win rate':<28} {c(wr_str, wr_col)}")
        print(f"  {'Total PnL':<28} {fmt_pnl(ts['total_pnl'])}")
        print(f"  {'Gross profit':<28} {c(gp_str, GREEN)}")
        print(f"  {'Gross loss':<28} {c(gl_str, RED)}")
        print(f"  {'Profit factor':<28} {c(pf_str, pf_col)}")

        sc = ts["side_counts"]
        total_sides = sc.get("long", 0) + sc.get("short", 0)
        long_pct = 100 * sc.get("long", 0) / total_sides if total_sides else 0
        short_pct = 100 * sc.get("short", 0) / total_sides if total_sides else 0
        print(f"  {'Long / Short':<28} {sc.get('long',0)} long ({long_pct:.0f}%)  /  "
              f"{sc.get('short',0)} short ({short_pct:.0f}%)")

        sym = ts["symbol_counts"]
        if sym:
            top5 = sym.most_common(5)
            print(f"  {'Top symbols':<28} " + "  ".join(f"{s}×{n}" for s, n in top5))

    # ── Conviction distribution
    print(section("CONVICTION DISTRIBUTION", width))
    total = a["n_cycles"]
    for label, count in sorted(a["conviction_counts"].items(), key=lambda x: -x[1]):
        col = {
            "BUY": GREEN, "SELL": RED, "HOLD": YELLOW,
            "SIT_OUT": MAGENTA, "n/a": DIM,
        }.get(label, WHITE)
        bar = "█" * int(count / total * 40)
        print(f"  {c(f'{label:<10}', col)} {bar:<40}  {count:5d}  ({pct(count, total)})")

    # ── Trade action distribution
    print(section("TRADE ACTION DISTRIBUTION", width))
    for label, count in sorted(a["action_counts"].items(), key=lambda x: -x[1]):
        col = GREEN if label == "TRADE" else YELLOW
        bar = "█" * int(count / total * 40)
        print(f"  {c(f'{label:<10}', col)} {bar:<40}  {count:5d}  ({pct(count, total)})")

    # ── Regime distribution
    print(section("REGIME DISTRIBUTION", width))
    regime_labels = {
        "normal": GREEN, "high_vol": YELLOW, "crisis": RED, "unknown": DIM
    }
    for label, count in sorted(a["regime_counts"].items(), key=lambda x: -x[1]):
        col = regime_labels.get(label, WHITE)
        bar = "█" * int(count / total * 40)
        print(f"  {c(f'{label:<12}', col)} {bar:<40}  {count:5d}  ({pct(count, total)})")

    # ── Composite score distribution
    print(section("COMPOSITE SCORE DISTRIBUTION", width))
    sc = a["scores"]
    if sc:
        mean_sc = statistics.mean(sc)
        std_sc = statistics.stdev(sc) if len(sc) > 1 else 0
        p25 = sorted(sc)[int(len(sc) * 0.25)]
        p75 = sorted(sc)[int(len(sc) * 0.75)]
        print(f"  {'min':<10} {min(sc):+.4f}   {'max':<10} {max(sc):+.4f}")
        print(f"  {'mean':<10} {mean_sc:+.4f}   {'std':<10} {std_sc:.4f}")
        print(f"  {'p25':<10} {p25:+.4f}   {'p75':<10} {p75:+.4f}")
        print()
        for line in histogram(sc, bins=12, bar_width=28):
            print(f"  {line}")

    # ── Signal activity
    print(section("SIGNAL ACTIVITY", width))
    print(f"  {'Active signals (min/mean/max)':<28} {a['sig_min']} / {a['sig_mean']:.1f} / {a['sig_max']}")
    if a["sig_min"] == a["sig_max"]:
        print(f"  {DIM}Signal count constant at {a['sig_max']} — use scripts/signal_audit.py for per-signal IC/win-rate breakdown{RESET}")

    # ── Blocker analysis
    print(section("BLOCKER ANALYSIS  (why cycles didn't trade)", width))
    hold_total = a["action_counts"].get("HOLD", 0)
    if a["blockers"]:
        for line in bar_chart(list(a["blockers"].items()), hold_total):
            print(line)
    else:
        print(f"  {DIM}No HOLD cycles recorded.{RESET}")
    print(f"\n  Ring-1 fails:   {a['ring1_fails']}  ({pct(a['ring1_fails'], total)})")
    print(f"  Circuit breaker trips: {a['breaker_trips']}")

    # ── PnL curve sparkline
    if a["pnl_curve"]:
        print(section("CUMULATIVE PnL CURVE  (text sparkline)", width))
        curve = a["pnl_curve"]
        final = curve[-1]
        col = GREEN if final >= 0 else RED
        print(f"  {fmt_pnl(curve[0])} → {fmt_pnl(final)}   ({len(curve)} checkpoints)")
        spark = sparkline(curve, width=60)
        # colour sparkline by final direction
        print(f"  {c(spark, col)}")
        print(f"  {DIM}start{' ' * 52}end{RESET}")

    print(f"\n{CYAN}{'═' * width}{RESET}\n")


# ── Compare mode ──────────────────────────────────────────────────────────────


def _row(label: str, va: str, vb: str, w: int = 26) -> str:
    return f"  {label:<{w}} {va:<22} {vb}"


def _diff_pnl(a: float, b: float) -> str:
    delta = b - a
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
    col = GREEN if delta > 0 else (RED if delta < 0 else WHITE)
    return c(f"{arrow} {delta:+.2f}", col)


def print_compare(a1: dict, a2: dict, width: int = 72) -> None:
    v1, v2 = a1["version"], a2["version"]
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  COMPARISON  —  {v1.upper()}  vs  {v2.upper()}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"\n  {'':26} {bold(v1.upper()):<22} {bold(v2.upper())}")

    # run
    print(section("RUN", width))
    print(_row("Cycles", str(a1["n_cycles"]), str(a2["n_cycles"])))
    print(_row("Wall time", fmt_duration(a1["elapsed_s"]), fmt_duration(a2["elapsed_s"])))
    print(_row("Avg cycle time", f"{a1['avg_cycle_time']:.2f}s", f"{a2['avg_cycle_time']:.2f}s"))

    # trades
    if a1["trade_stats"] and a2["trade_stats"]:
        print(section("TRADE SUMMARY", width))
        t1, t2 = a1["trade_stats"], a2["trade_stats"]
        print(_row("Closed trades", str(t1["total"]), str(t2["total"])))
        print(_row("Win rate",
                   c(f"{t1['win_rate']*100:.1f}%", GREEN if t1['win_rate'] >= 0.5 else RED),
                   c(f"{t2['win_rate']*100:.1f}%", GREEN if t2['win_rate'] >= 0.5 else RED)))
        print(_row("Total PnL",
                   fmt_pnl(t1["total_pnl"]) + "  " + _diff_pnl(t1["total_pnl"], t2["total_pnl"]),
                   fmt_pnl(t2["total_pnl"])))
        pf1 = f"{t1['profit_factor']:.3f}" if t1['profit_factor'] != float('inf') else "∞"
        pf2 = f"{t2['profit_factor']:.3f}" if t2['profit_factor'] != float('inf') else "∞"
        print(_row("Profit factor",
                   c(pf1, GREEN if t1['profit_factor'] >= 1.0 else RED),
                   c(pf2, GREEN if t2['profit_factor'] >= 1.0 else RED)))

    # conviction
    print(section("CONVICTION", width))
    all_conv = sorted(set(a1["conviction_counts"]) | set(a2["conviction_counts"]))
    for label in all_conv:
        n1 = a1["conviction_counts"].get(label, 0)
        n2 = a2["conviction_counts"].get(label, 0)
        p1 = pct(n1, a1["n_cycles"])
        p2 = pct(n2, a2["n_cycles"])
        print(_row(label, f"{n1:5d} ({p1})", f"{n2:5d} ({p2})"))

    # regime
    print(section("REGIME", width))
    all_reg = sorted(set(a1["regime_counts"]) | set(a2["regime_counts"]))
    for label in all_reg:
        n1 = a1["regime_counts"].get(label, 0)
        n2 = a2["regime_counts"].get(label, 0)
        p1 = pct(n1, a1["n_cycles"])
        p2 = pct(n2, a2["n_cycles"])
        print(_row(label, f"{n1:5d} ({p1})", f"{n2:5d} ({p2})"))

    # composite score
    if a1["scores"] and a2["scores"]:
        print(section("COMPOSITE SCORE", width))
        for label, vals1, vals2 in [
            ("mean", [statistics.mean(a1["scores"])], [statistics.mean(a2["scores"])]),
            ("std",  [statistics.stdev(a1["scores"]) if len(a1["scores"]) > 1 else 0],
                     [statistics.stdev(a2["scores"]) if len(a2["scores"]) > 1 else 0]),
            ("min",  [min(a1["scores"])], [min(a2["scores"])]),
            ("max",  [max(a1["scores"])], [max(a2["scores"])]),
        ]:
            print(_row(label, f"{vals1[0]:+.4f}", f"{vals2[0]:+.4f}"))

    # blockers
    print(section("TOP BLOCKERS", width))
    all_b = sorted(set(a1["blockers"]) | set(a2["blockers"]))
    hold1 = a1["action_counts"].get("HOLD", 0) or 1
    hold2 = a2["action_counts"].get("HOLD", 0) or 1
    for label in sorted(all_b, key=lambda b: -(a1["blockers"].get(b, 0) + a2["blockers"].get(b, 0))):
        n1 = a1["blockers"].get(label, 0)
        n2 = a2["blockers"].get(label, 0)
        print(_row(label, f"{n1:5d} ({pct(n1, hold1)})", f"{n2:5d} ({pct(n2, hold2)})"))

    # pnl curves side by side
    if a1["pnl_curve"] or a2["pnl_curve"]:
        print(section("PnL CURVE", width))
        if a1["pnl_curve"]:
            c1 = a1["pnl_curve"]
            col1 = GREEN if c1[-1] >= 0 else RED
            print(f"  {v1:<8}  {c(sparkline(c1, 50), col1)}  {fmt_pnl(c1[-1])}")
        if a2["pnl_curve"]:
            c2 = a2["pnl_curve"]
            col2 = GREEN if c2[-1] >= 0 else RED
            print(f"  {v2:<8}  {c(sparkline(c2, 50), col2)}  {fmt_pnl(c2[-1])}")

    print(f"\n{CYAN}{'═' * width}{RESET}\n")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(f"Usage: python3 scripts/analyze_training.py v32")
        print(f"       python3 scripts/analyze_training.py --compare v31 v32")
        sys.exit(1)

    if args[0] == "--compare":
        if len(args) < 3:
            sys.exit("--compare requires two version arguments, e.g. --compare v31 v32")
        v1, v2 = args[1], args[2]
        a1 = analyse(v1)
        a2 = analyse(v2)
        print_compare(a1, a2)
    else:
        version = args[0]
        a = analyse(version)
        print_report(a)


if __name__ == "__main__":
    main()
