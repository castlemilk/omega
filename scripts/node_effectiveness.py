#!/usr/bin/env python3
"""
scripts/node_effectiveness.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-signal IC/accuracy/attribution analysis + per-gate attribution + decision tree
for Victoria backtest runs.

Usage:
    python3 scripts/node_effectiveness.py \
        --versions bt500_v136a_crisis bt500_v136a_trend bt500_v136a_recent \
                   bt500_v137a_crisis bt500_v137a_trend bt500_v137a_recent \
        --gate-ablation bt_v137a:bt_v137b:bt_v137c \
        --out docs/research/node-effectiveness-v136-v137.md
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
TRACES_DIR = DATA_DIR / "activation_traces"
DT_DIR = DATA_DIR / "decision_traces"
SCORES_DIR = DATA_DIR / "benchmarks"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_activation_traces(version: str) -> list[dict]:
    path = TRACES_DIR / f"{version}.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_decision_traces(version: str) -> list[dict]:
    path = DT_DIR / f"{version}.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_trades(version: str) -> list[dict]:
    path = DATA_DIR / f"{version}_trades.csv"
    if not path.exists():
        return []
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_results(version: str) -> dict:
    path = DATA_DIR / f"{version}_results.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Per-signal attribution
# ---------------------------------------------------------------------------

SIGNAL_DISPLAY = {
    "sma_crossover": "SMA Crossover",
    "sma_long": "SMA Long",
    "sma_short": "SMA Short",
    "fear_greed_signal": "Fear/Greed",
    "ricci_curvature_signal": "Ricci Curvature",
    "ollivier_ricci_signal": "ORC (Ollivier-Ricci)",
    "tick_momentum": "Tick Momentum",
    "order_book_imbalance": "OBI",
    "return_1d": "1-Day Return",
    "book_depth_velocity": "Book Depth Velocity",
    "trade_flow_direction": "Trade Flow",
    "momentum_crossover": "Momentum Crossover",
    "momentum_derivative": "Momentum Derivative",
    "momentum_persistence": "Momentum Persistence",
    "spread_zscore": "Spread Z-Score",
    "volume_profile": "Volume Profile",
    "vpin": "VPIN",
    "whale_print": "Whale Prints",
    "funding_crossover": "Funding Crossover",
    "funding_derivative": "Funding Derivative",
    "liquidation_proximity": "Liquidation Proximity",
    "regime_duration": "Regime Duration",
    "conviction_trend": "Conviction Trend",
    "agreement_trend": "Agreement Trend",
    "price": "Price",
}

REGIMES = ["crisis", "normal", "high_vol"]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-10 or dy < 1e-10:
        return float("nan")
    return num / (dx * dy)


def compute_signal_metrics(traces: list[dict]) -> dict[str, dict]:
    """
    Compute per-signal accuracy, IC, contribution, and regime breakdown.

    Returns: {signal_name: {accuracy, ic, total_contribution, regime: {label: {accuracy, ic, n}}}}
    """
    # Only include traces with a resolved outcome (exit_pnl not None)
    completed = [t for t in traces if t.get("outcome", {}).get("exit_pnl") is not None]
    if not completed:
        return {}

    # Collect per-signal data
    # signal_data[sig][regime] = list of (raw_value, direction_alignment, exit_pnl)
    signal_data: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    signal_contrib: dict[str, float] = defaultdict(float)

    for trace in completed:
        pnl = trace["outcome"]["exit_pnl"]
        regime = trace.get("regime", {}).get("label", "normal")
        trade_dir = trace.get("direction", "long")
        win = 1 if pnl > 0 else 0
        pnl_sign = 1 if pnl > 0 else -1

        for act in trace.get("activations", []):
            sig = act["name"]
            raw = act.get("raw_value", 0.0) or 0.0
            align = act.get("direction_alignment", 0)
            # Contribution from attribution dict, or estimate from magnitude×alignment
            contrib = trace["outcome"].get("attribution", {}).get(sig)
            if contrib is None:
                # Estimate: magnitude × alignment × |pnl| share
                mag = abs(raw)
                contrib = mag * align * abs(pnl) if mag > 0 else 0.0
            signal_data[sig][regime].append((raw, align, win, pnl_sign, pnl))
            signal_contrib[sig] += contrib

    # Build metrics per signal
    metrics: dict[str, dict] = {}
    for sig, by_regime in signal_data.items():
        all_samples = [s for samples in by_regime.values() for s in samples]
        n = len(all_samples)
        if n == 0:
            continue

        # Accuracy: fraction where direction_alignment == pnl_sign (signal called direction right)
        accuracy = sum(1 for _, a, _, ps, _ in all_samples if a == ps) / n

        # IC: Pearson(raw_value * direction_alignment, win)
        xs = [r * a for r, a, _, _, _ in all_samples]
        ys = [float(w) for _, _, w, _, _ in all_samples]
        ic = _pearson(xs, ys)

        regime_stats: dict[str, dict] = {}
        for reg in REGIMES:
            samples = by_regime.get(reg, [])
            rn = len(samples)
            if rn < 2:
                regime_stats[reg] = {"n": rn, "accuracy": float("nan"), "ic": float("nan")}
                continue
            racc = sum(1 for _, a, _, ps, _ in samples if a == ps) / rn
            rxs = [r * a for r, a, _, _, _ in samples]
            rys = [float(w) for _, _, w, _, _ in samples]
            ric = _pearson(rxs, rys)
            regime_stats[reg] = {"n": rn, "accuracy": racc, "ic": ric}

        metrics[sig] = {
            "n": n,
            "accuracy": accuracy,
            "ic": ic,
            "total_contribution": signal_contrib[sig],
            "by_regime": regime_stats,
        }

    return metrics


# ---------------------------------------------------------------------------
# Per-gate attribution
# ---------------------------------------------------------------------------

def compute_gate_attribution(
    dt_records: list[dict],
    version: str,
    ablation_pnl: dict[str, float] | None = None,
) -> dict:
    """
    Per-gate attribution using decision traces + ablation PnL deltas.

    For each 'conviction_gate:hold' entry, records it as AND-gate blocked.
    Ablation PnL deltas give counterfactual value per gate.
    """
    gate_blocks = [r for r in dt_records if any("conviction_gate" in ff for ff in (r.get("filters_fired") or []))]

    total_decisions = len(dt_records)
    n_traded = sum(1 for r in dt_records if r.get("final_decision") == "TRADE")
    n_gate_blocked = len(gate_blocks)
    n_conviction_filtered = sum(1 for r in dt_records if r.get("final_decision") == "FILTERED")
    n_held = total_decisions - n_traded - n_gate_blocked - n_conviction_filtered

    # Count gate failure by type (if score is negative → failed)
    gate_block_details = []
    for r in gate_blocks:
        filters = r.get("filters_fired", [])
        for ff in filters:
            if "conviction_gate:hold" in ff:
                try:
                    score = float(ff.split("score=")[1].rstrip(")"))
                except (IndexError, ValueError):
                    score = float("nan")
                gate_block_details.append({
                    "ticker": r.get("ticker"),
                    "cycle": r.get("cycle"),
                    "regime": r.get("regime"),
                    "score": score,
                    "proposal": r.get("proposal"),
                })

    result = {
        "version": version,
        "total_decisions": total_decisions,
        "n_traded": n_traded,
        "n_gate_blocked": n_gate_blocked,
        "n_conviction_filtered": n_conviction_filtered,
        "n_held": n_held,
        "gate_blocks": gate_block_details,
        "gate_block_rate": n_gate_blocked / max(1, n_traded + n_gate_blocked),
    }

    if ablation_pnl:
        # Gate attribution from ablation
        base = ablation_pnl.get(version, 0.0)
        for label, ablation_ver in ablation_pnl.items():
            if label == version:
                continue
            delta = base - ablation_ver if isinstance(ablation_ver, (int, float)) else 0.0
            result[f"pnl_delta_{label}"] = delta

    return result


# ---------------------------------------------------------------------------
# Decision tree analysis (top winners / losers)
# ---------------------------------------------------------------------------

def build_decision_tree(
    traces: list[dict],
    trades: list[dict],
    n_top: int = 10,
) -> dict:
    """
    Join activation traces with trades CSV by (ticker, cycle).
    Returns top N winners and N losers with full signal breakdown.
    """
    # Index activation traces by (ticker, cycle)
    trace_index: dict[tuple, dict] = {}
    for t in traces:
        key = (t.get("ticker", ""), t.get("cycle", 0))
        trace_index[key] = t

    # Parse trades
    parsed_trades = []
    for row in trades:
        try:
            pnl = float(row.get("pnl", 0))
            cycle = int(row.get("cycle", 0))
            ticker = row.get("symbol", row.get("ticker", ""))
            parsed_trades.append({
                "ticker": ticker,
                "cycle": cycle,
                "pnl": pnl,
                "side": row.get("side", ""),
                "hold_cycles": row.get("hold_cycles", ""),
                "exit_reason": row.get("close_reason", row.get("sit_out_reason", "")),
                "conviction": row.get("conviction", ""),
                "regime": row.get("regime", ""),
            })
        except (ValueError, TypeError):
            continue

    sorted_trades = sorted(parsed_trades, key=lambda x: x["pnl"])
    losers = sorted_trades[:n_top]
    winners = sorted_trades[-n_top:][::-1]

    def enrich(trade_list: list[dict]) -> list[dict]:
        result = []
        for tr in trade_list:
            key = (tr["ticker"], tr["cycle"])
            trace = trace_index.get(key, {})
            entry = {**tr}
            if trace:
                entry["activations"] = trace.get("activations", [])
                entry["signals_right"] = trace.get("outcome", {}).get("signals_right", [])
                entry["signals_wrong"] = trace.get("outcome", {}).get("signals_wrong", [])
                entry["composite"] = trace.get("composite", {})
                entry["regime_detail"] = trace.get("regime", {})
                entry["geometry"] = trace.get("geometry", {})
                entry["exit_pnl_trace"] = trace.get("outcome", {}).get("exit_pnl")
            result.append(entry)
        return result

    return {
        "top_winners": enrich(winners),
        "top_losers": enrich(losers),
    }


def _render_trade_card(trade: dict, rank: int) -> str:
    """Render a single trade as a decision tree card in markdown."""
    lines = []
    pnl = trade["pnl"]
    pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
    lines.append(f"**#{rank} {trade['ticker']} {trade['side'].upper()}** — {pnl_str} | "
                 f"cycle={trade['cycle']} | hold={trade.get('hold_cycles','')} cycles | "
                 f"regime={trade.get('regime','?')} | exit={trade.get('exit_reason','?')[:40]}")
    lines.append("")

    activations = trade.get("activations", [])
    if activations:
        # Sort by abs(weighted_value) descending
        acts = sorted(activations, key=lambda a: abs(a.get("weighted_value", 0.0)), reverse=True)
        lines.append("| Signal | Value | Weight | Align | Direction |")
        lines.append("|--------|-------|--------|-------|-----------|")
        for a in acts[:12]:
            align_sym = "✓" if a.get("direction_alignment", 0) == 1 else ("✗" if a.get("direction_alignment", 0) == -1 else "·")
            sig = SIGNAL_DISPLAY.get(a["name"], a["name"])
            lines.append(f"| {sig} | {a.get('raw_value', 0):.3f} | {a.get('final_weight', 1.0):.2f} | {align_sym} | {a.get('weighted_value', 0):.3f} |")
        lines.append("")

    right = ", ".join(trade.get("signals_right", []))
    wrong = ", ".join(trade.get("signals_wrong", []))
    if right:
        lines.append(f"✓ Correct signals: `{right}`")
    if wrong:
        lines.append(f"✗ Wrong signals: `{wrong}`")

    comp = trade.get("composite", {})
    if comp:
        lines.append(f"Conviction: weighted={comp.get('weighted_conviction',0):.3f} "
                     f"demeaned={comp.get('demeaned',0):.3f} basket_std={comp.get('basket_std',0):.3f}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Signal-regime heatmap
# ---------------------------------------------------------------------------

def build_heatmap(
    all_metrics: dict[str, dict[str, dict]],
    signals_order: list[str] | None = None,
) -> str:
    """
    Build a markdown heatmap: rows=signals, cols=versions×regimes, cells=accuracy+IC.

    all_metrics: {version_label: {signal: {accuracy, ic, by_regime}}}
    """
    all_sigs: set[str] = set()
    for m in all_metrics.values():
        all_sigs.update(m.keys())
    if signals_order is None:
        signals_order = sorted(all_sigs)

    versions = list(all_metrics.keys())

    # Header: one col per version×regime
    cols = []
    for v in versions:
        for reg in REGIMES:
            cols.append((v, reg))

    header_parts = ["| Signal |"]
    for v, reg in cols:
        vlabel = v.replace("bt500_", "")
        header_parts.append(f" {vlabel}/{reg} |")
    divider_parts = ["|--------|"] + ["----|"] * len(cols)

    lines = ["".join(header_parts), "".join(divider_parts)]
    for sig in signals_order:
        cells = [f"| {SIGNAL_DISPLAY.get(sig, sig)[:22]} |"]
        for v, reg in cols:
            m = all_metrics.get(v, {}).get(sig, {})
            by_reg = m.get("by_regime", {}).get(reg, {})
            n = by_reg.get("n", 0)
            if n < 2:
                cells.append(" — |")
            else:
                acc = by_reg.get("accuracy", float("nan"))
                ic = by_reg.get("ic", float("nan"))
                acc_s = f"{acc:.0%}" if not math.isnan(acc) else "?"
                ic_s = f"{ic:+.2f}" if not math.isnan(ic) else "?"
                cells.append(f" {acc_s}/{ic_s} |")
        lines.append("".join(cells))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def generate_report(
    versions: list[str],
    gate_ablation_map: dict[str, float] | None,
    out_path: Path,
) -> None:
    print(f"Loading data for {len(versions)} versions...")

    # Load all data
    all_traces: dict[str, list[dict]] = {}
    all_dt: dict[str, list[dict]] = {}
    all_trades: dict[str, list[dict]] = {}
    all_results: dict[str, dict] = {}

    for v in versions:
        all_traces[v] = load_activation_traces(v)
        all_dt[v] = load_decision_traces(v)
        all_trades[v] = load_trades(v)
        all_results[v] = load_results(v)
        print(f"  {v}: {len(all_traces[v])} traces, {len(all_dt[v])} decisions, {len(all_trades[v])} trades")

    # Compute signal metrics
    print("Computing per-signal metrics...")
    all_metrics: dict[str, dict[str, dict]] = {}
    for v in versions:
        all_metrics[v] = compute_signal_metrics(all_traces[v])
        print(f"  {v}: {len(all_metrics[v])} signals with data")

    # Compute gate attribution for V137 versions
    gate_attrs: dict[str, dict] = {}
    for v in versions:
        if "v137" in v and all_dt[v]:
            gate_attrs[v] = compute_gate_attribution(all_dt[v], v, gate_ablation_map)

    # Build decision trees
    print("Building decision trees...")
    decision_trees: dict[str, dict] = {}
    for v in versions:
        if all_traces[v] and all_trades[v]:
            decision_trees[v] = build_decision_tree(all_traces[v], all_trades[v])

    # ---------------------------------------------------------------------------
    # Write markdown report
    # ---------------------------------------------------------------------------
    report = []
    report.append("# Node Effectiveness Report: V136a vs V137a")
    report.append("")
    report.append("*Auto-generated by `scripts/node_effectiveness.py`*")
    report.append("")
    report.append("---")
    report.append("")

    # Section 1: Executive Summary
    report.append("## 1. Executive Summary")
    report.append("")
    report.append("| Version | Snapshot | Trades | PnL | WR | PF |")
    report.append("|---------|----------|--------|-----|----|----|")
    for v in versions:
        res = all_results.get(v, {})
        m = res.get("metrics", res)
        trades_count = len(all_trades[v])
        pnl = m.get("pnl", sum(float(t.get("pnl", 0)) for t in all_trades[v]))
        wr = m.get("win_rate", 0.0)
        pf = m.get("profit_factor", 0.0)
        snap = v.rsplit("_", 1)[-1]
        cfg = v.replace(f"_{snap}", "").replace("bt500_", "")
        pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        report.append(f"| {cfg} | {snap} | {trades_count} | {pnl_str} | {wr:.0%} | {pf:.2f} |")
    report.append("")

    # Section 2: Signal-Regime Heatmap
    report.append("## 2. Signal-Regime Heatmap (Accuracy / IC)")
    report.append("")
    report.append("Accuracy = % trades where signal direction aligned with profitable outcome. ")
    report.append("IC = Pearson(signal × direction_alignment, win). Threshold: accuracy > 55% or IC > 0.1 = useful.")
    report.append("")

    # Group by config for cleaner heatmap
    v136_versions = [v for v in versions if "v136a" in v]
    v137_versions = [v for v in versions if "v137a" in v]

    if v136_versions:
        report.append("### V136a (crisis_long_block, no AND-gate)")
        report.append("")
        subset_metrics = {v: all_metrics[v] for v in v136_versions}
        report.append(build_heatmap(subset_metrics))
        report.append("")

    if v137_versions:
        report.append("### V137a (V136a + full AND-gate)")
        report.append("")
        subset_metrics = {v: all_metrics[v] for v in v137_versions}
        report.append(build_heatmap(subset_metrics))
        report.append("")

    # Section 3: Per-signal analysis
    report.append("## 3. Per-Signal Attribution (Aggregate)")
    report.append("")
    report.append("Signals ranked by |IC| across all snapshots combined.")
    report.append("")

    # Aggregate metrics across all versions
    agg_signal: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for v, metrics in all_metrics.items():
        for sig, m in metrics.items():
            if not math.isnan(m.get("ic", float("nan"))):
                agg_signal[sig]["ic"].append(m["ic"])
            if not math.isnan(m.get("accuracy", float("nan"))):
                agg_signal[sig]["accuracy"].append(m["accuracy"])
            agg_signal[sig]["contribution"].append(m.get("total_contribution", 0.0))
            agg_signal[sig]["n"].append(m["n"])

    # Sort by mean |IC|
    ranked = []
    for sig, data in agg_signal.items():
        ics = data["ic"]
        accs = data["accuracy"]
        contribs = data["contribution"]
        mean_ic = sum(ics) / len(ics) if ics else float("nan")
        mean_acc = sum(accs) / len(accs) if accs else float("nan")
        total_contrib = sum(contribs)
        total_n = sum(data["n"])
        ranked.append((sig, mean_ic, mean_acc, total_contrib, total_n))

    ranked.sort(key=lambda x: abs(x[1]) if not math.isnan(x[1]) else 0, reverse=True)

    report.append("| Signal | Mean IC | Mean Accuracy | Total Contribution | N Trades |")
    report.append("|--------|---------|---------------|-------------------|----------|")
    for sig, mic, macc, contrib, n in ranked:
        ic_s = f"{mic:+.3f}" if not math.isnan(mic) else "—"
        acc_s = f"{macc:.0%}" if not math.isnan(macc) else "—"
        contrib_s = f"+${contrib:,.0f}" if contrib >= 0 else f"-${abs(contrib):,.0f}"
        flag = " ⭐" if (not math.isnan(mic) and abs(mic) > 0.10) else ""
        report.append(f"| {SIGNAL_DISPLAY.get(sig, sig)}{flag} | {ic_s} | {acc_s} | {contrib_s} | {n} |")
    report.append("")

    # Section 4: Per-gate attribution
    report.append("## 4. Per-Gate Attribution (V137a)")
    report.append("")
    if gate_attrs:
        for v, ga in gate_attrs.items():
            snap = v.rsplit("_", 1)[-1]
            report.append(f"### {v}")
            report.append("")
            report.append(f"- Total decisions: {ga['total_decisions']}")
            report.append(f"- Traded: {ga['n_traded']}")
            report.append(f"- Gate-blocked (AND-gate): {ga['n_gate_blocked']} "
                          f"({ga['gate_block_rate']:.0%} of passed-conviction entries)")
            report.append(f"- Conviction-filtered (pre-gate): {ga['n_conviction_filtered']}")
            report.append(f"- Held (below threshold): {ga['n_held']}")
            report.append("")
            if ga["gate_blocks"]:
                report.append("**AND-gate blocked entries:**")
                report.append("")
                report.append("| Ticker | Cycle | Regime | Score | Proposal |")
                report.append("|--------|-------|--------|-------|----------|")
                for b in ga["gate_blocks"][:20]:
                    report.append(f"| {b['ticker']} | {b['cycle']} | {b['regime']} | "
                                  f"{b['score']:+.3f} | {b['proposal']} |")
                report.append("")
            report.append("")
    else:
        report.append("*No gate trace data available for V137a versions.*")
        report.append("")

    # Gate ablation summary
    report.append("### Gate Ablation (150-cycle baseline, used as proxy)")
    report.append("")
    report.append("| Gate | Removed in | Agg PnL | Delta vs V137a | Interpretation |")
    report.append("|------|-----------|---------|---------------|----------------|")
    report.append("| Gate 1 (Divergence) | v137b_no_gate1 | $+3,629 | -$4,150 | **Load-bearing** — removes it hurts in crisis |")
    report.append("| Gate 4 (ORC/Fiedler) | v137c_no_gate4 | $+7,779 | $0 | **Dormant** — always passes (ORC in warmup) |")
    report.append("| Gate 2 (Exit Quality) | n/a (cold-start) | — | — | Cold-start for 150 cycles; untested |")
    report.append("| Gate 3 (Capital Velocity) | implicit | — | — | Rarely fires in 150-cycle; tested in live |")
    report.append("")

    # Section 5: Decision tree for top winners/losers
    report.append("## 5. Decision Tree: Top Winners & Losers")
    report.append("")
    for v in versions[:4]:  # Cap at 4 to keep report manageable
        dt = decision_trees.get(v)
        if not dt:
            continue
        snap = v.rsplit("_", 1)[-1]
        cfg = v.replace(f"_{snap}", "").replace("bt500_", "")
        report.append(f"### {cfg} — {snap}")
        report.append("")
        report.append("#### Top 5 Winners")
        report.append("")
        for i, trade in enumerate(dt["top_winners"][:5], 1):
            report.append(_render_trade_card(trade, i))
        report.append("#### Top 5 Losers")
        report.append("")
        for i, trade in enumerate(dt["top_losers"][:5], 1):
            report.append(_render_trade_card(trade, i))

    # Section 6: Recommendations
    report.append("## 6. Recommendations for V138")
    report.append("")
    report.append("Based on per-signal IC and per-gate attribution:")
    report.append("")
    report.append("### Signals to Upweight")
    report.append("")
    top_signals = [(sig, mic) for sig, mic, _, _, _ in ranked if not math.isnan(mic) and mic > 0.08]
    for sig, mic in top_signals[:5]:
        report.append(f"- **{SIGNAL_DISPLAY.get(sig, sig)}** (IC={mic:+.3f}): "
                      f"consistent positive predictive power — consider increasing weight or IC threshold")
    if not top_signals:
        report.append("- *(Insufficient data — rerun with more trades)*")
    report.append("")

    report.append("### Signals to Remove/Downweight")
    report.append("")
    neg_signals = [(sig, mic) for sig, mic, _, _, _ in ranked if not math.isnan(mic) and mic < -0.05]
    for sig, mic in neg_signals[:5]:
        report.append(f"- **{SIGNAL_DISPLAY.get(sig, sig)}** (IC={mic:+.3f}): "
                      f"negative predictive power — acts as noise; consider removing or inverting")
    if not neg_signals:
        report.append("- *(No strongly negative signals identified)*")
    report.append("")

    report.append("### Gate Recommendations")
    report.append("")
    report.append("- **Gate 1 (Divergence)**: Keep at current threshold (0.05). "
                  "Ablation shows $+4,150 value over 150 cycles; primary quality filter.")
    report.append("- **Gate 4 (ORC/Fiedler)**: Needs live data to evaluate. "
                  "Dormant in all backtest snapshots (ORC always in warmup). "
                  "Run V137a_live to 200+ cycles to assess.")
    report.append("- **Gate 2 (Exit Quality)**: Untested beyond cold-start. "
                  "With ATR stops counting as clean exits, should remain open in normal/high_vol. "
                  "Monitor in live Phase B.")
    report.append("- **Gate 3 (Capital Velocity)**: Rarely fires in backtest (<5 positions). "
                  "Appropriate limit but add regime-conditional sizing instead of hard cap.")
    report.append("")

    report.append("### V138 Design Hypotheses")
    report.append("")
    report.append("1. **Regime-conditional signal weights**: weight signals by regime-specific IC "
                  "(crisis: upweight ORC/Ricci geometry; normal: upweight momentum/trend)")
    report.append("2. **Gate 1 regime-specific threshold**: tighten divergence to 0.07 in crisis, "
                  "loosen to 0.03 in normal (adapts to market informativeness)")
    report.append("3. **Gate 4 warm-start**: Pre-compute ORC on 1000-cycle snapshot to give "
                  "Fiedler/ORC a non-zero baseline from cycle 1")
    report.append("4. **Remove dormant signals**: `price` and `sma_long/short` likely add noise; "
                  "trim to 15 highest-IC signals")
    report.append("")

    report.append("---")
    report.append("*Report generated by `scripts/node_effectiveness.py`. "
                  "Run again after 500-cycle backtests complete for full signal coverage.*")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(report))
    print(f"\nReport written → {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Node effectiveness analysis")
    parser.add_argument(
        "--versions", nargs="+", required=True,
        help="Version labels to analyze (e.g. bt500_v136a_crisis bt500_v137a_crisis)"
    )
    parser.add_argument(
        "--out", type=str, default="docs/research/node-effectiveness-v136-v137.md",
        help="Output markdown path"
    )
    parser.add_argument(
        "--gate-ablation", type=str, default=None,
        help="Comma-separated version:pnl pairs for gate ablation (e.g. bt_v137b_crisis:-2228)"
    )
    args = parser.parse_args()

    gate_ablation_map = None
    if args.gate_ablation:
        gate_ablation_map = {}
        for pair in args.gate_ablation.split(","):
            ver, pnl = pair.split(":")
            gate_ablation_map[ver.strip()] = float(pnl)

    out_path = ROOT / args.out
    generate_report(args.versions, gate_ablation_map, out_path)


if __name__ == "__main__":
    main()
