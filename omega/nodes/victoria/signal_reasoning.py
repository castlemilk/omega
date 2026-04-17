"""
omega.nodes.victoria.signal_reasoning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Natural-language reasoning layer for Victoria decisions.

Produces a structured, human-readable explanation of each trade decision:
  - Top 3 contributing signals and their direction/magnitude
  - Regime context with threshold scaling
  - AND-gate pass/fail status per gate
  - Final decision and threshold gap

Written into DecisionTrace.reasoning field when signal_reasoning feature is ON.
Rendered as a tooltip in the geometry dashboard.
"""

from __future__ import annotations

from typing import Any

# Short display names for signals
_SIGNAL_NAMES: dict[str, str] = {
    "sma_crossover": "SMA X",
    "sma_long": "SMA Long",
    "sma_short": "SMA Short",
    "fear_greed_signal": "Fear/Greed",
    "ricci_curvature_signal": "Ricci",
    "ollivier_ricci_signal": "ORC",
    "tick_momentum": "Tick Mom.",
    "order_book_imbalance": "OBI",
    "return_1d": "1D Ret.",
    "book_depth_velocity": "BDV",
    "trade_flow_direction": "Trade Flow",
    "momentum_crossover": "Mom. X",
    "momentum_derivative": "Mom. Deriv.",
    "momentum_acceleration": "Mom. Accel.",
    "momentum_persistence": "Mom. Persist.",
    "spread_zscore": "Spread Z",
    "volume_profile": "Vol. Profile",
    "vpin": "VPIN",
    "whale_print": "Whale",
    "funding_crossover": "Fund. X",
    "funding_derivative": "Fund. Deriv.",
    "funding_rate_signal": "Funding",
    "liquidation_proximity": "Liq. Prox.",
    "regime_duration": "Regime Dur.",
    "conviction_trend": "Conv. Trend",
    "agreement_trend": "Agree. Trend",
    "geo_event_intensity": "Geo Intensity",
    "geo_sentiment": "Geo Sentiment",
    "geo_regime_shift": "Geo Shift",
    "sanctions_signal": "Sanctions",
}


def _sname(raw: str) -> str:
    return _SIGNAL_NAMES.get(raw, raw[:14])


def build_reasoning(
    ticker: str,
    proposal: str,
    final_decision: str,
    activations: list[dict[str, Any]],
    composite: float,
    regime: str,
    bear_prob: float,
    bull_prob: float,
    thresh_scale: float,
    long_thresh: float,
    short_thresh: float,
    threshold_gap: float,
    gate_result: Any | None = None,
    blocking_filter: str = "",
) -> str:
    """
    Build a natural-language reasoning string for a single decision.

    Args:
        ticker: Symbol being evaluated.
        proposal: "LONG" / "SHORT" / "NONE"
        final_decision: "TRADE" / "FILTERED" / "HOLD" / "SIT_OUT"
        activations: List of activation dicts (name, raw_value, weighted_value, direction_alignment).
        composite: Demeaned composite conviction.
        regime: Consolidated regime label.
        bear_prob: Wasserstein bear probability.
        bull_prob: Wasserstein bull probability.
        thresh_scale: Regime-adaptive threshold multiplier.
        long_thresh: Effective long threshold (post-scale).
        short_thresh: Effective short threshold (post-scale).
        threshold_gap: composite - applicable threshold (neg = rejected).
        gate_result: GateResult object (optional; None if AND-gate not evaluated).
        blocking_filter: Filter that blocked the trade (empty if passed).

    Returns:
        Multi-clause natural-language reasoning string.
    """
    parts: list[str] = []

    # 1. Top signal drivers
    if activations:
        sorted_acts = sorted(
            activations,
            key=lambda a: abs(a.get("weighted_value", 0.0)),
            reverse=True,
        )[:3]
        sig_clauses = []
        for a in sorted_acts:
            name = _sname(a.get("name", "?"))
            val = a.get("raw_value", 0.0) or 0.0
            wv = a.get("weighted_value", 0.0) or 0.0
            align = a.get("direction_alignment", 0)
            direction = "↑" if align > 0 else ("↓" if align < 0 else "→")
            sig_clauses.append(f"{name}={val:+.2f}{direction}(w={wv:+.2f})")
        parts.append("Drivers: " + ", ".join(sig_clauses))

    # 2. Composite + direction
    direction_label = "LONG" if proposal == "LONG" else ("SHORT" if proposal == "SHORT" else "FLAT")
    parts.append(f"{direction_label} composite={composite:+.4f}")

    # 3. Regime context
    thresh = long_thresh if proposal == "LONG" else short_thresh
    regime_clause = (
        f"regime={regime} bear={bear_prob:.2f} bull={bull_prob:.2f} "
        f"→ thresh×{thresh_scale:.2f}={thresh:.4f}"
    )
    parts.append(regime_clause)

    # 4. AND-gate status
    if gate_result is not None:
        try:
            gate_summary = gate_result.summary()
            parts.append(f"gate={gate_summary}")
        except Exception:
            pass
    elif blocking_filter and "conviction_gate" in blocking_filter:
        parts.append(f"gate=BLOCKED({blocking_filter})")

    # 5. Final decision + gap
    gap_str = f"+{threshold_gap:.4f}" if threshold_gap >= 0 else f"{threshold_gap:.4f}"
    if final_decision == "TRADE":
        parts.append(f"TRADE ✓ gap={gap_str}")
    elif final_decision == "FILTERED":
        reason = blocking_filter or "unknown"
        parts.append(f"FILTERED({reason}) gap={gap_str}")
    elif final_decision == "HOLD":
        parts.append(f"HOLD gap={gap_str}")
    else:
        parts.append(f"{final_decision}")

    return " | ".join(parts)
