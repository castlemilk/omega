#!/usr/bin/env python3
"""
scripts/backtest_vs_live_compare.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compare V137a backtest vs live paper trade:
- Per-signal behavior divergence (IC, accuracy, contribution)
- Regime distribution differences
- Gate activation patterns (how often each gate fires live vs replay)
- Conviction distribution comparison
- Slippage/execution effects

Usage:
    python3 scripts/backtest_vs_live_compare.py \
        --backtest bt500_v137a_crisis bt500_v137a_trend bt500_v137a_recent \
        --live bt_v137a_live_phaseb \
        --out docs/research/backtest-vs-live-comparison.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
TRACES_DIR = DATA_DIR / "activation_traces"
DT_DIR = DATA_DIR / "decision_traces"

SIGNAL_DISPLAY = {
    "sma_crossover": "SMA Crossover", "sma_long": "SMA Long", "sma_short": "SMA Short",
    "fear_greed_signal": "Fear/Greed", "ricci_curvature_signal": "Ricci Curvature",
    "ollivier_ricci_signal": "ORC (ORC)", "tick_momentum": "Tick Momentum",
    "order_book_imbalance": "OBI", "return_1d": "1-Day Return",
    "book_depth_velocity": "Book Depth Velocity", "trade_flow_direction": "Trade Flow",
    "momentum_crossover": "Momentum Crossover", "momentum_derivative": "Momentum Deriv.",
    "momentum_persistence": "Momentum Persist.", "spread_zscore": "Spread Z-Score",
    "volume_profile": "Volume Profile", "vpin": "VPIN", "whale_print": "Whale Prints",
    "funding_crossover": "Funding Crossover", "funding_derivative": "Funding Deriv.",
    "liquidation_proximity": "Liq. Proximity", "regime_duration": "Regime Duration",
    "conviction_trend": "Conviction Trend", "agreement_trend": "Agreement Trend", "price": "Price",
}


def load_traces(version: str) -> list[dict]:
    path = TRACES_DIR / f"{version}.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def load_decision_traces(version: str) -> list[dict]:
    path = DT_DIR / f"{version}.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 1e-10 and dy > 1e-10 else float("nan")


def compute_signal_stats(traces: list[dict]) -> dict[str, dict]:
    completed = [t for t in traces if t.get("outcome", {}).get("exit_pnl") is not None]
    stats: dict[str, dict] = defaultdict(lambda: {"xs": [], "wins": [], "contribs": [], "n": 0})
    for t in completed:
        pnl = t["outcome"]["exit_pnl"]
        win = 1 if pnl > 0 else 0
        pnl_sign = 1 if pnl > 0 else -1
        for a in t.get("activations", []):
            sig = a["name"]
            raw = a.get("raw_value", 0.0) or 0.0
            align = a.get("direction_alignment", 0)
            stats[sig]["xs"].append(raw * align)
            stats[sig]["wins"].append(float(win))
            stats[sig]["n"] += 1
            # Estimate contribution
            mag = abs(raw)
            stats[sig]["contribs"].append(mag * align * abs(pnl) if mag > 0 else 0.0)

    result = {}
    for sig, d in stats.items():
        ic = _pearson(d["xs"], d["wins"])
        n = d["n"]
        acc = sum(1 for x, w in zip(d["xs"], d["wins"]) if (x > 0) == (w > 0)) / max(1, n)
        result[sig] = {
            "n": n,
            "ic": ic,
            "accuracy": acc,
            "mean_contribution": sum(d["contribs"]) / max(1, n),
            "total_contribution": sum(d["contribs"]),
        }
    return result


def compute_regime_distribution(traces: list[dict], dt: list[dict]) -> dict:
    regime_counts = Counter()
    for t in traces:
        regime_counts[t.get("regime", {}).get("label", "normal")] += 1
    dt_regimes = Counter(r.get("regime", "normal") for r in dt)
    return {"traded": dict(regime_counts), "all_decisions": dict(dt_regimes)}


def compute_conviction_stats(dt: list[dict]) -> dict:
    convictions = [r.get("weighted_conviction", 0) for r in dt if r.get("weighted_conviction") is not None]
    if not convictions:
        return {}
    n = len(convictions)
    mean = sum(convictions) / n
    var = sum((c - mean) ** 2 for c in convictions) / n
    return {
        "mean": mean,
        "std": math.sqrt(var),
        "min": min(convictions),
        "max": max(convictions),
        "n_positive": sum(1 for c in convictions if c > 0),
        "n_negative": sum(1 for c in convictions if c < 0),
        "pct_positive": sum(1 for c in convictions if c > 0) / n,
    }


def compute_gate_activity(dt: list[dict]) -> dict:
    gate_blocked = [r for r in dt if any("conviction_gate" in ff for ff in (r.get("filters_fired") or []))]
    conviction_filtered = [r for r in dt if r.get("final_decision") == "FILTERED"]
    traded = [r for r in dt if r.get("final_decision") == "TRADE"]
    total = len(dt)
    return {
        "total": total,
        "traded": len(traded),
        "gate_blocked": len(gate_blocked),
        "conviction_filtered": len(conviction_filtered),
        "gate_block_rate": len(gate_blocked) / max(1, len(traded) + len(gate_blocked)),
        "orc_nonzero": sum(1 for r in dt if (r.get("orc_mean") or 0) != 0.0),
        "fiedler_nonzero": sum(1 for r in dt if (r.get("fiedler_raw") or 0) not in (0.0, 1.0)),
    }


def generate_comparison(
    backtest_versions: list[str],
    live_version: str,
    out_path: Path,
) -> None:
    print(f"Loading backtest data ({len(backtest_versions)} versions)...")
    bt_traces: list[dict] = []
    bt_dt: list[dict] = []
    for v in backtest_versions:
        bt_traces.extend(load_traces(v))
        bt_dt.extend(load_decision_traces(v))
    print(f"  Backtest: {len(bt_traces)} traces, {len(bt_dt)} decisions")

    print(f"Loading live data ({live_version})...")
    live_traces = load_traces(live_version)
    live_dt = load_decision_traces(live_version)
    print(f"  Live: {len(live_traces)} traces, {len(live_dt)} decisions")

    # Compute stats
    bt_signals = compute_signal_stats(bt_traces)
    live_signals = compute_signal_stats(live_traces)
    bt_regimes = compute_regime_distribution(bt_traces, bt_dt)
    live_regimes = compute_regime_distribution(live_traces, live_dt)
    bt_conviction = compute_conviction_stats(bt_dt)
    live_conviction = compute_conviction_stats(live_dt)
    bt_gate = compute_gate_activity(bt_dt)
    live_gate = compute_gate_activity(live_dt)

    all_signals = sorted(set(list(bt_signals.keys()) + list(live_signals.keys())))

    # ---------------------------------------------------------------------------
    # Write report
    # ---------------------------------------------------------------------------
    report = []
    report.append("# Backtest vs Live Comparison: V137a")
    report.append("")
    report.append("*Auto-generated by `scripts/backtest_vs_live_compare.py`*")
    report.append("")
    report.append("---")
    report.append("")

    report.append("## 1. Run Summary")
    report.append("")
    report.append(f"**Backtest**: {', '.join(backtest_versions)} (500 cycles × 3 snapshots)")
    report.append(f"**Live**: {live_version} (200 cycles, real market data)")
    report.append("")
    report.append("| Metric | Backtest (agg) | Live |")
    report.append("|--------|---------------|------|")
    report.append(f"| Activation traces (completed trades) | {len(bt_traces)} | {len(live_traces)} |")
    report.append(f"| Decision traces (all evaluations) | {len(bt_dt)} | {len(live_dt)} |")
    bt_wr = sum(1 for t in bt_traces if t.get("outcome", {}).get("exit_pnl", 0) > 0) / max(1, len(bt_traces))
    live_wr = sum(1 for t in live_traces if t.get("outcome", {}).get("exit_pnl", 0) > 0) / max(1, len(live_traces))
    report.append(f"| Win rate (from traces) | {bt_wr:.0%} | {live_wr:.0%} |")
    report.append(f"| AND-gate block rate | {bt_gate['gate_block_rate']:.0%} | {live_gate['gate_block_rate']:.0%} |")
    report.append(f"| ORC non-zero cycles | {bt_gate['orc_nonzero']} | {live_gate['orc_nonzero']} |")
    report.append(f"| Fiedler non-zero cycles | {bt_gate['fiedler_nonzero']} | {live_gate['fiedler_nonzero']} |")
    report.append("")

    report.append("## 2. Regime Distribution")
    report.append("")
    report.append("| Regime | Backtest (decisions) | Live (decisions) |")
    report.append("|--------|---------------------|-----------------|")
    all_regimes = sorted(set(list(bt_regimes["all_decisions"].keys()) + list(live_regimes["all_decisions"].keys())))
    bt_total = sum(bt_regimes["all_decisions"].values()) or 1
    live_total = sum(live_regimes["all_decisions"].values()) or 1
    for reg in all_regimes:
        bt_n = bt_regimes["all_decisions"].get(reg, 0)
        live_n = live_regimes["all_decisions"].get(reg, 0)
        report.append(f"| {reg} | {bt_n} ({bt_n/bt_total:.0%}) | {live_n} ({live_n/live_total:.0%}) |")
    report.append("")

    report.append("## 3. Conviction Distribution")
    report.append("")
    report.append("| Stat | Backtest | Live |")
    report.append("|------|---------|------|")
    for key in ["mean", "std", "min", "max", "pct_positive"]:
        bv = bt_conviction.get(key, float("nan"))
        lv = live_conviction.get(key, float("nan"))
        fmt = ".0%" if key == "pct_positive" else ".4f"
        bvs = f"{bv:{fmt}}" if not math.isnan(bv) else "—"
        lvs = f"{lv:{fmt}}" if not math.isnan(lv) else "—"
        report.append(f"| {key} | {bvs} | {lvs} |")
    report.append("")

    report.append("## 4. Per-Signal Divergence")
    report.append("")
    report.append("Signals where IC or accuracy diverges significantly between backtest and live.")
    report.append("")
    report.append("| Signal | BT IC | Live IC | IC Delta | BT Acc | Live Acc | Acc Delta |")
    report.append("|--------|-------|---------|---------|--------|----------|----------|")

    divergences = []
    for sig in all_signals:
        bt = bt_signals.get(sig, {})
        live = live_signals.get(sig, {})
        if not bt or not live:
            continue
        bt_ic = bt.get("ic", float("nan"))
        live_ic = live.get("ic", float("nan"))
        bt_acc = bt.get("accuracy", float("nan"))
        live_acc = live.get("accuracy", float("nan"))
        ic_delta = live_ic - bt_ic if not (math.isnan(live_ic) or math.isnan(bt_ic)) else float("nan")
        acc_delta = live_acc - bt_acc if not (math.isnan(live_acc) or math.isnan(bt_acc)) else float("nan")
        divergences.append((sig, bt_ic, live_ic, ic_delta, bt_acc, live_acc, acc_delta))

    # Sort by abs IC delta
    divergences.sort(key=lambda x: abs(x[3]) if not math.isnan(x[3]) else 0, reverse=True)
    for sig, bt_ic, live_ic, ic_delta, bt_acc, live_acc, acc_delta in divergences:
        sname = SIGNAL_DISPLAY.get(sig, sig)
        bt_ic_s = f"{bt_ic:+.3f}" if not math.isnan(bt_ic) else "—"
        live_ic_s = f"{live_ic:+.3f}" if not math.isnan(live_ic) else "—"
        ic_d_s = f"{ic_delta:+.3f}" if not math.isnan(ic_delta) else "—"
        bt_acc_s = f"{bt_acc:.0%}" if not math.isnan(bt_acc) else "—"
        live_acc_s = f"{live_acc:.0%}" if not math.isnan(live_acc) else "—"
        acc_d_s = f"{acc_delta:+.0%}" if not math.isnan(acc_delta) else "—"
        flag = " ⚠️" if (not math.isnan(ic_delta) and abs(ic_delta) > 0.15) else ""
        report.append(f"| {sname}{flag} | {bt_ic_s} | {live_ic_s} | {ic_d_s} | {bt_acc_s} | {live_acc_s} | {acc_d_s} |")
    report.append("")

    report.append("## 5. Gate Activation Analysis")
    report.append("")
    report.append("### Gate 4 (ORC / Fiedler) — Critical live vs backtest difference")
    report.append("")
    report.append(f"- **Backtest**: ORC non-zero in {bt_gate['orc_nonzero']}/{bt_gate['total']} decisions "
                  f"({bt_gate['orc_nonzero']/max(1,bt_gate['total']):.0%}) — Gate 4 always passes (warmup)")
    report.append(f"- **Live**: ORC non-zero in {live_gate['orc_nonzero']}/{live_gate['total']} decisions "
                  f"({live_gate['orc_nonzero']/max(1,live_gate['total']):.0%})")
    report.append(f"- **Fiedler live**: {live_gate['fiedler_nonzero']} non-zero readings")
    report.append("")

    if live_gate['orc_nonzero'] > 0:
        report.append("**Gate 4 is ACTIVE in live trading.** ORC provides real signal — ")
        report.append("this is the primary backtest-vs-live fidelity gap.")
    else:
        report.append("**Gate 4 remains dormant in live.** ORC still warming up after 200 cycles.")
    report.append("")

    report.append("### AND-gate Block Rate")
    report.append("")
    report.append(f"- Backtest: {bt_gate['gate_block_rate']:.0%} of passed-conviction entries blocked by AND-gate")
    report.append(f"- Live: {live_gate['gate_block_rate']:.0%} of passed-conviction entries blocked by AND-gate")
    report.append("")

    report.append("## 6. Fidelity Assessment")
    report.append("")
    report.append("| Dimension | Fidelity | Notes |")
    report.append("|-----------|---------|-------|")

    # Regime fidelity
    bt_crisis_pct = bt_regimes["all_decisions"].get("crisis", 0) / bt_total
    live_crisis_pct = live_regimes["all_decisions"].get("crisis", 0) / live_total
    regime_gap = abs(bt_crisis_pct - live_crisis_pct)
    regime_fid = "High" if regime_gap < 0.10 else ("Medium" if regime_gap < 0.25 else "Low")
    report.append(f"| Regime distribution | {regime_fid} | Crisis: BT={bt_crisis_pct:.0%} vs Live={live_crisis_pct:.0%} |")

    # Conviction fidelity
    bt_mean_conv = bt_conviction.get("mean", 0)
    live_mean_conv = live_conviction.get("mean", 0)
    conv_gap = abs(bt_mean_conv - live_mean_conv) if bt_mean_conv and live_mean_conv else float("nan")
    conv_fid = "High" if not math.isnan(conv_gap) and conv_gap < 0.05 else "Medium"
    report.append(f"| Conviction distribution | {conv_fid} | Mean: BT={bt_mean_conv:.4f} vs Live={live_mean_conv:.4f} |")

    # Signal fidelity (avg IC delta)
    ic_deltas = [abs(x[3]) for x in divergences if not math.isnan(x[3])]
    mean_ic_delta = sum(ic_deltas) / len(ic_deltas) if ic_deltas else float("nan")
    sig_fid = "High" if not math.isnan(mean_ic_delta) and mean_ic_delta < 0.10 else "Medium"
    report.append(f"| Signal IC alignment | {sig_fid} | Mean |ΔIC|={mean_ic_delta:.3f} across {len(ic_deltas)} signals |")

    # Gate 4 fidelity
    g4_fid = "Low" if live_gate['orc_nonzero'] == 0 else "High"
    g4_note = "ORC still in warmup" if live_gate['orc_nonzero'] == 0 else f"ORC active in {live_gate['orc_nonzero']} decisions"
    report.append(f"| Gate 4 (ORC/Fiedler) | {g4_fid} | {g4_note} |")
    report.append("")

    report.append("## 7. Conclusions & V138 Implications")
    report.append("")
    report.append("### Where backtest and live agree")
    report.append("")
    matching = [(sig, ic_d) for sig, _, _, ic_d, _, _, _ in divergences
                if not math.isnan(ic_d) and abs(ic_d) < 0.05]
    if matching:
        for sig, ic_d in matching[:5]:
            report.append(f"- **{SIGNAL_DISPLAY.get(sig, sig)}**: ΔIC={ic_d:+.3f} — stable across environments")
    else:
        report.append("- *(Insufficient live data for strong conclusions)*")
    report.append("")

    report.append("### Where they diverge (live reliability concerns)")
    report.append("")
    diverged = [(sig, ic_d) for sig, _, _, ic_d, _, _, _ in divergences
                if not math.isnan(ic_d) and abs(ic_d) > 0.10]
    if diverged:
        for sig, ic_d in diverged[:5]:
            direction = "weaker live" if ic_d < 0 else "stronger live"
            report.append(f"- **{SIGNAL_DISPLAY.get(sig, sig)}**: ΔIC={ic_d:+.3f} — {direction}")
    else:
        report.append("- *(Insufficient live data — rerun after V137a_live completes 200 cycles)*")
    report.append("")

    report.append("### ORC/Fiedler warm-start gap")
    report.append("")
    if live_gate['orc_nonzero'] == 0:
        report.append("ORC remains in warmup for all 200 live cycles. Gate 4 never activates in either ")
        report.append("backtest or live. **V138 action**: pre-compute ORC from historical data at startup ")
        report.append("to give Gate 4 a non-zero baseline from cycle 1.")
    else:
        report.append(f"ORC activated in {live_gate['orc_nonzero']} live decisions. Gate 4 is real. ")
        report.append("Backtest underestimates Gate 4 value — incorporate historical ORC into snapshots.")
    report.append("")

    report.append("---")
    report.append("*Report generated by `scripts/backtest_vs_live_compare.py`. "
                  "Run again after live Phase B completes for fuller signal statistics.*")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(report))
    print(f"\nComparison written → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", nargs="+", required=True)
    parser.add_argument("--live", type=str, required=True)
    parser.add_argument("--out", type=str, default="docs/research/backtest-vs-live-comparison.md")
    args = parser.parse_args()

    out_path = ROOT / args.out
    generate_comparison(args.backtest, args.live, out_path)


if __name__ == "__main__":
    main()
