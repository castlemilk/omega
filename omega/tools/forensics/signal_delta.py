"""Signal contribution delta — Phase 1 trade-level proxy.

This module does not read per-signal weights (no signal log available in Phase 1).
Instead it computes per-symbol and per-side PnL contribution deltas between two runs.
The forensics JSON labels this as `signal_contribution_delta_proxy` to make the
limitation explicit. A full per-signal version lands in Phase 2 once the signal log
is wired into training artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class SignalDeltaProxy:
    per_symbol_delta: dict[str, float] = field(default_factory=dict)
    per_side_delta: dict[str, float] = field(default_factory=dict)
    baseline_version: str = ""
    target_version: str = ""


def _group_pnl(trades: list[dict], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        k = t.get(key, "unknown")
        out[k] = out.get(k, 0.0) + float(t.get("pnl", 0.0))
    return out


def compute_signal_delta_proxy(baseline: RunArtifacts, target: RunArtifacts) -> SignalDeltaProxy:
    """Delta = target - baseline for per-symbol and per-side PnL sums."""
    baseline_by_symbol = _group_pnl(baseline.trades, "symbol")
    target_by_symbol = _group_pnl(target.trades, "symbol")
    baseline_by_side = _group_pnl(baseline.trades, "side")
    target_by_side = _group_pnl(target.trades, "side")

    all_symbols = set(baseline_by_symbol) | set(target_by_symbol)
    all_sides = set(baseline_by_side) | set(target_by_side)

    return SignalDeltaProxy(
        per_symbol_delta={
            s: target_by_symbol.get(s, 0.0) - baseline_by_symbol.get(s, 0.0)
            for s in all_symbols
        },
        per_side_delta={
            s: target_by_side.get(s, 0.0) - baseline_by_side.get(s, 0.0)
            for s in all_sides
        },
        baseline_version=baseline.version,
        target_version=target.version,
    )
