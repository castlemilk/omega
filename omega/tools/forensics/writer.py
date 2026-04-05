"""Emit forensics output as machine-readable JSON and human-readable Markdown."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omega.tools.forensics.conviction_histogram import ConvictionHistogram
from omega.tools.forensics.hypothesis_ranker import Hypothesis
from omega.tools.forensics.loader import RunArtifacts
from omega.tools.forensics.signal_delta import SignalDeltaProxy
from omega.tools.forensics.skipped_trades import SkippedTrade

SCHEMA_VERSION = "1.0"


def _baseline_dict(run: RunArtifacts, source: str) -> dict[str, Any]:
    return {
        "version": run.version,
        "pnl": run.total_pnl,
        "trades": run.total_trades,
        "win_rate": run.win_rate,
        "long_trades": run.long_trades,
        "short_trades": run.short_trades,
        "profit_factor": run.profit_factor,
        "zero_trade_cycles": run.zero_trade_cycles,
        "conviction_filter_rate": run.conviction_filter_rate,
        "source": source,
    }


def _histogram_dict(h: ConvictionHistogram) -> dict[str, Any]:
    return {
        "hold_threshold": h.hold_threshold,
        "trade_band_count": h.trade_band_count,
        "hold_band_count": h.hold_band_count,
        "trade_band_pct": h.trade_band_pct,
        "hold_band_pct": h.hold_band_pct,
        "min_conviction": h.min_conviction,
        "max_conviction": h.max_conviction,
        "mean_conviction": h.mean_conviction,
    }


def _regime_breakdown(v35: RunArtifacts, v48: RunArtifacts) -> dict[str, Any]:
    regimes = set(v35.regime_pnl) | set(v48.regime_pnl)
    return {
        r: {
            "v35_pnl": v35.regime_pnl.get(r, 0.0),
            "v48_pnl": v48.regime_pnl.get(r, 0.0),
            "delta": v48.regime_pnl.get(r, 0.0) - v35.regime_pnl.get(r, 0.0),
        }
        for r in sorted(regimes)
    }


def write_forensics_json(
    path: Path,
    *,
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
    hypotheses: list[Hypothesis],
    status: str = "ok",
) -> None:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "baselines": {
            "v35": _baseline_dict(v35, source="data/v35_extended_results.json"),
            "v48": _baseline_dict(v48, source="data/v48_results.json"),
        },
        "conviction_histogram": {
            "v35": _histogram_dict(v35_histogram),
            "v48": _histogram_dict(v48_histogram),
        },
        "signal_contribution_delta_proxy": {
            "per_symbol": delta.per_symbol_delta,
            "per_side": delta.per_side_delta,
            "note": "Phase 1 proxy — per-symbol PnL delta, not per-signal weight delta.",
        },
        "skipped_trades": [
            {
                "cycle": s.cycle,
                "symbol": s.symbol,
                "side": s.side,
                "baseline_pnl": s.baseline_pnl,
                "baseline_conviction": s.baseline_conviction,
                "baseline_regime": s.baseline_regime,
                "reason": "present_in_v35_absent_in_v48",
            }
            for s in skipped
        ],
        "hypotheses": [
            {
                "rank": h.rank,
                "claim": h.claim,
                "confidence": h.confidence,
                "evidence_refs": h.evidence_refs,
            }
            for h in hypotheses
        ],
        "regime_breakdown": _regime_breakdown(v35, v48),
    }
    Path(path).write_text(json.dumps(payload, indent=2))


def write_forensics_markdown(
    path: Path,
    *,
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
    hypotheses: list[Hypothesis],
) -> None:
    lines: list[str] = []
    lines.append("# V35 → V48 Forensics Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(UTC).isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | V35 | V48 | Delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Total PnL (USD) | {v35.total_pnl:.2f} | {v48.total_pnl:.2f} | {v48.total_pnl - v35.total_pnl:+.2f} |"
    )
    lines.append(
        f"| Trades | {v35.total_trades} | {v48.total_trades} | {v48.total_trades - v35.total_trades:+d} |"
    )
    lines.append(
        f"| Win rate | {v35.win_rate:.2%} | {v48.win_rate:.2%} | {(v48.win_rate - v35.win_rate):+.2%} |"
    )
    lines.append(
        f"| Profit factor | {v35.profit_factor:.2f} | {v48.profit_factor:.2f} | {v48.profit_factor - v35.profit_factor:+.2f} |"
    )
    lines.append(
        f"| Zero-trade cycles | {v35.zero_trade_cycles} | {v48.zero_trade_cycles} | {v48.zero_trade_cycles - v35.zero_trade_cycles:+d} |"
    )
    lines.append("")
    lines.append("## Conviction Histogram")
    lines.append("")
    lines.append("| Band | V35 | V48 |")
    lines.append("|---|---|---|")
    lines.append(f"| HOLD (< 0.20) | {v35_histogram.hold_band_pct:.0%} | {v48_histogram.hold_band_pct:.0%} |")
    lines.append(f"| Trade (>= 0.20) | {v35_histogram.trade_band_pct:.0%} | {v48_histogram.trade_band_pct:.0%} |")
    lines.append(f"| Mean conviction | {v35_histogram.mean_conviction:.3f} | {v48_histogram.mean_conviction:.3f} |")
    lines.append("")
    lines.append("## Top-3 Hypotheses")
    lines.append("")
    for h in hypotheses:
        lines.append(f"### {h.rank}. (confidence {h.confidence:.2f})")
        lines.append("")
        lines.append(h.claim)
        lines.append("")
        if h.evidence_refs:
            lines.append("**Evidence:** " + ", ".join(h.evidence_refs))
            lines.append("")
    lines.append("## Skipped Trades")
    lines.append("")
    if not skipped:
        lines.append("_None — all baseline trades matched a target entry._")
    else:
        lines.append("| Cycle | Symbol | Side | Baseline PnL | Conviction | Regime |")
        lines.append("|---|---|---|---|---|---|")
        for s in skipped:
            lines.append(
                f"| {s.cycle} | {s.symbol} | {s.side} | {s.baseline_pnl:+.2f} | "
                f"{s.baseline_conviction:.3f} | {s.baseline_regime} |"
            )
    lines.append("")
    lines.append("## Regime Breakdown")
    lines.append("")
    lines.append("| Regime | V35 PnL | V48 PnL | Delta |")
    lines.append("|---|---|---|---|")
    regimes = set(v35.regime_pnl) | set(v48.regime_pnl)
    for r in sorted(regimes):
        v35_p = v35.regime_pnl.get(r, 0.0)
        v48_p = v48.regime_pnl.get(r, 0.0)
        lines.append(f"| {r} | {v35_p:+.2f} | {v48_p:+.2f} | {v48_p - v35_p:+.2f} |")
    lines.append("")
    Path(path).write_text("\n".join(lines))
