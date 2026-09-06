"""
omega.nodes.victoria.activation_trace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Full computation-graph trace for every trade decision.

Each ActivationTrace captures the exact computation path that led to a trade:
  - Raw signal values at entry
  - Reinforcement weight per signal (from TradeReinforcer)
  - IC weight per signal (from SignalDecayDetector)
  - Final combined weight and weighted_value
  - Direction alignment for each signal
  - Composite computation steps (raw → demeaned → weighted conviction)
  - Threshold values and gap
  - Filter chain (which filters passed, which blocked)
  - Regime + geometry state
  - Conviction level + size

At trade close the trace is completed with:
  - Realized PnL
  - Hold cycles
  - signals_right / signals_wrong lists
  - Per-signal PnL attribution

Written to: data/activation_traces/{version}.jsonl — one JSON per line.

## Usage

    from omega.nodes.victoria.activation_trace import ActivationTracer

    tracer = ActivationTracer(version="v107")
    tracer.open()

    # At trade entry (in strategy.py or victoria_node.py):
    trace = ActivationTrace(ticker="ETHUSDT", cycle=42, ...)
    tracer.record_entry(ticker, trace)

    # At trade close (in orchestrator_v2.py):
    tracer.record_exit(ticker, pnl=-5.20, side="long", hold_cycles=4, attribution={...})

    # End of run:
    tracer.close()

## CLI view:
    python scripts/view_activations.py --version v107 --ticker ETHUSDT --limit 5
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger("omega.victoria.activation_trace")

# Signal keys tracked in activations (subset that has directional meaning)
_DIRECTIONAL_SIGNALS = {
    "sma_crossover",
    "rsi_signal",
    "macd_crossover",
    "zscore_signal",
    "volume_signal",
    "bb_signal",
    "vol_regime_signal",
    "btc_beta_signal",
    "funding_rate_signal",
    "fear_greed_signal",
    "dxy_signal",
    "vix_signal",
    "yield_curve_signal",
    "order_book_imbalance_signal",
    "trade_flow_signal",
    "spread_zscore_signal",
    "volume_profile_signal",
    "tick_momentum_signal",
    "momentum_derivative",
    "conviction_trend",
    "agreement_trend",
}


def _clean(v: float) -> float | None:
    """Return float or None for inf/nan (JSON-safe)."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), 6)


# ---------------------------------------------------------------------------
# SignalActivation — one signal's contribution to a trade decision
# ---------------------------------------------------------------------------


@dataclass
class SignalActivation:
    """Per-signal breakdown for a single trade decision."""

    name: str
    raw_value: float
    """Signal value as seen by strategy (after reinforcement multiplier applied)."""

    reinforcement_weight: float = 1.0
    """Multiplier from TradeReinforcer. 1.0 = no adjustment (pre-5-trade warmup)."""

    ic_weight: float = 1.0
    """IC-derived weight from SignalDecayDetector. 1.0 = unknown/neutral."""

    final_weight: float = 1.0
    """Combined weight = reinforcement_weight × ic_weight."""

    weighted_value: float = 0.0
    """raw_value × final_weight — contribution to composite."""

    direction_alignment: int = 0
    """+1 = aligned with trade direction, -1 = opposed, 0 = neutral (near-zero)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_value": _clean(self.raw_value),
            "reinforcement_weight": _clean(self.reinforcement_weight),
            "ic_weight": _clean(self.ic_weight),
            "final_weight": _clean(self.final_weight),
            "weighted_value": _clean(self.weighted_value),
            "direction_alignment": self.direction_alignment,
        }


# ---------------------------------------------------------------------------
# ActivationTrace — full computation graph for one trade
# ---------------------------------------------------------------------------


@dataclass
class ActivationTrace:
    """Full computation-graph trace for a single trade entry/exit."""

    # ── Identity ────────────────────────────────────────────────────────
    trade_id: str = ""
    ticker: str = ""
    cycle: int = 0
    version: str = ""
    timestamp: str = ""

    # ── Decision ────────────────────────────────────────────────────────
    direction: str = ""
    """'long' or 'short'"""

    # ── Signal activations ──────────────────────────────────────────────
    activations: list[SignalActivation] = field(default_factory=list)

    # ── Composite computation ────────────────────────────────────────────
    raw_composite: float = 0.0
    demeaned_composite: float = 0.0
    basket_mean: float = 0.0
    basket_std: float = 0.0
    weighted_conviction: float = 0.0

    # ── Thresholds ───────────────────────────────────────────────────────
    long_thresh: float = 0.0
    short_thresh: float = 0.0
    thresh_scale: float = 1.0
    wc_thresh: float = 0.0
    conviction_gap: float = 0.0
    """abs(weighted_conviction) - applicable_threshold. Positive = passed."""

    # ── Filter chain ─────────────────────────────────────────────────────
    filters_passed: list[str] = field(default_factory=list)
    blocking_filter: str = ""
    final_decision: str = ""
    """'TRADE' or 'FILTERED'"""

    # ── Regime ───────────────────────────────────────────────────────────
    regime: str = ""
    bear_prob: float = -1.0
    bull_prob: float = -1.0
    is_crisis: bool = False
    is_high_vol: bool = False

    # ── Geometry (optional) ──────────────────────────────────────────────
    ricci: float = 0.0
    fiedler_zscore: float = 0.0
    crash_prox: float = 0.0
    orc_mean: float = 0.0

    # ── Temporal features (optional) ─────────────────────────────────────
    momentum_derivative: float = 0.0
    conviction_trend: float = 0.0
    agreement_trend: float = 0.0

    # ── Conviction + size ────────────────────────────────────────────────
    conviction_level: str = ""
    allocated_size: float = 0.0
    kelly_scale: float = 1.0

    # ── Filled at close ──────────────────────────────────────────────────
    exit_pnl: float | None = None
    hold_cycles: int | None = None
    close_reason: str = ""

    signals_right: list[str] = field(default_factory=list)
    """Signal names aligned with direction AND outcome was profitable."""

    signals_wrong: list[str] = field(default_factory=list)
    """Signal names opposed to direction when outcome was profitable (or vice versa)."""

    attribution: dict[str, float] = field(default_factory=dict)
    """Per-signal PnL contribution from trade_attribution.attribute_trade()."""

    def complete(
        self,
        pnl: float,
        hold_cycles: int,
        close_reason: str = "",
        attribution: dict[str, float] | None = None,
    ) -> None:
        """Fill in exit data and compute signals_right / signals_wrong."""
        self.exit_pnl = pnl
        self.hold_cycles = hold_cycles
        self.close_reason = close_reason
        self.attribution = attribution or {}

        expected_dir = 1 if self.direction == "long" else -1
        outcome_positive = pnl > 0

        for act in self.activations:
            if act.direction_alignment == 0:
                continue
            # Signal was "right" if it agreed with direction AND we won,
            # OR it opposed the direction AND we lost (correctly warned us).
            signal_agrees = act.direction_alignment == expected_dir
            is_right = signal_agrees == outcome_positive
            if is_right:
                self.signals_right.append(act.name)
            else:
                self.signals_wrong.append(act.name)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "trade_id": self.trade_id,
            "ticker": self.ticker,
            "cycle": self.cycle,
            "version": self.version,
            "timestamp": self.timestamp,
            "direction": self.direction,
            "activations": [a.to_dict() for a in self.activations],
            "composite": {
                "raw": _clean(self.raw_composite),
                "demeaned": _clean(self.demeaned_composite),
                "basket_mean": _clean(self.basket_mean),
                "basket_std": _clean(self.basket_std),
                "weighted_conviction": _clean(self.weighted_conviction),
            },
            "thresholds": {
                "long_thresh": _clean(self.long_thresh),
                "short_thresh": _clean(self.short_thresh),
                "thresh_scale": _clean(self.thresh_scale),
                "wc_thresh": _clean(self.wc_thresh),
                "conviction_gap": _clean(self.conviction_gap),
            },
            "filters": {
                "passed": self.filters_passed,
                "blocking": self.blocking_filter,
                "decision": self.final_decision,
            },
            "regime": {
                "label": self.regime,
                "bear_prob": _clean(self.bear_prob),
                "bull_prob": _clean(self.bull_prob),
                "is_crisis": self.is_crisis,
                "is_high_vol": self.is_high_vol,
            },
            "geometry": {
                "ricci": _clean(self.ricci),
                "fiedler_zscore": _clean(self.fiedler_zscore),
                "crash_prox": _clean(self.crash_prox),
                "orc_mean": _clean(self.orc_mean),
            },
            "temporal": {
                "momentum_derivative": _clean(self.momentum_derivative),
                "conviction_trend": _clean(self.conviction_trend),
                "agreement_trend": _clean(self.agreement_trend),
            },
            "execution": {
                "conviction_level": self.conviction_level,
                "allocated_size": _clean(self.allocated_size),
                "kelly_scale": _clean(self.kelly_scale),
            },
            "outcome": {
                "exit_pnl": _clean(self.exit_pnl) if self.exit_pnl is not None else None,
                "hold_cycles": self.hold_cycles,
                "close_reason": self.close_reason,
                "signals_right": self.signals_right,
                "signals_wrong": self.signals_wrong,
                "n_right": len(self.signals_right),
                "n_wrong": len(self.signals_wrong),
                "attribution": {k: _clean(v) for k, v in self.attribution.items()},
            },
        }
        return d


# ---------------------------------------------------------------------------
# ActivationTracer — manages the write lifecycle
# ---------------------------------------------------------------------------


class ActivationTracer:
    """Manages entry + exit recording for activation traces.

    Pending traces are held in memory until the position closes, then written
    to the JSONL file with the full outcome attached.
    """

    def __init__(self, version: str, output_dir: str = "data") -> None:
        self._version = version
        self._dir = Path(output_dir) / "activation_traces"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{version}.jsonl"
        self._fh: TextIO | None = None
        # pending[ticker] = ActivationTrace (entry recorded, exit not yet)
        self._pending: dict[str, ActivationTrace] = {}

    def open(self) -> None:
        """Open the JSONL file for appending."""
        self._fh = open(self._path, "a")
        logger.info("ActivationTracer: writing to %s", self._path)

    def record_entry(self, ticker: str, trace: ActivationTrace) -> None:
        """Store an entry-time trace (overwrite if ticker already pending)."""
        self._pending[ticker] = trace

    def record_exit(
        self,
        ticker: str,
        pnl: float,
        side: str,
        hold_cycles: int = 0,
        close_reason: str = "",
        attribution: dict[str, float] | None = None,
    ) -> None:
        """Complete the pending trace for `ticker` and flush to JSONL."""
        trace = self._pending.get(ticker)
        if trace is None:
            logger.debug("ActivationTracer: no pending entry for %s — skipping exit", ticker)
            return
        trace.complete(pnl, hold_cycles, close_reason, attribution)
        self._write(trace)
        del self._pending[ticker]

    def _write(self, trace: ActivationTrace) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(trace.to_dict()) + "\n")
            self._fh.flush()
        except Exception as exc:
            logger.warning("ActivationTracer: write failed: %s", exc)

    def close(self) -> None:
        """Flush any pending (unclosed) traces and close the file."""
        # Write pending entries without exit data (run ended mid-position)
        for trace in self._pending.values():
            self._write(trace)
        self._pending.clear()
        if self._fh:
            import contextlib

            with contextlib.suppress(Exception):
                self._fh.close()
            self._fh = None

    @property
    def path(self) -> Path:
        return self._path


# ---------------------------------------------------------------------------
# build_activation_trace — construct from strategy context
# ---------------------------------------------------------------------------


def build_activation_trace(
    ticker: str,
    cycle: int,
    version: str,
    direction: str,
    sig: dict[str, Any],
    weighted_conviction: float,
    long_thresh: float,
    short_thresh: float,
    thresh_scale: float,
    wc_thresh: float,
    basket_mean: float,
    basket_std: float,
    regime: str,
    bear_prob: float,
    bull_prob: float,
    is_crisis: bool,
    is_high_vol: bool,
    filters_passed: list[str] | None = None,
    blocking_filter: str = "",
    final_decision: str = "TRADE",
    conviction_level: str = "",
    allocated_size: float = 0.0,
    kelly_scale: float = 1.0,
    trade_id: str = "",
) -> ActivationTrace:
    """Construct an ActivationTrace from strategy-level context.

    `sig` is the per-ticker signal dict from signal_generation.py, which
    includes `_reinf_weights` (injected there) and all signal values.
    """
    reinf_weights: dict[str, float] = sig.get("_reinf_weights") or {}

    # Build per-signal activations — iterate ALL non-underscore numeric keys in sig
    # so every computed signal is captured, not just the hardcoded _DIRECTIONAL_SIGNALS set.
    activations: list[SignalActivation] = []
    expected_dir = 1 if direction == "long" else -1
    # _non_signal_keys: numeric keys in sig that are not directional signals
    _non_signal_keys = {"composite", "vol_regime", "vol_rank", "basket_mean", "basket_std"}
    for name, val in sig.items():
        if name.startswith("_"):
            continue  # internal/meta keys (regime state, reinf_weights, etc.)
        if name in _non_signal_keys:
            continue
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue

        r_weight = reinf_weights.get(name, 1.0)
        # IC weight: approximate from ic_weights if available in sig, else 1.0
        ic_weight = 1.0
        final_w = r_weight * ic_weight
        weighted_val = fval * final_w

        # Direction alignment: +1 if agrees with trade direction
        if abs(fval) < 1e-6:
            align = 0
        elif fval > 0:
            align = 1 if expected_dir > 0 else -1
        else:
            align = -1 if expected_dir > 0 else 1

        activations.append(
            SignalActivation(
                name=name,
                raw_value=fval,
                reinforcement_weight=r_weight,
                ic_weight=ic_weight,
                final_weight=final_w,
                weighted_value=weighted_val,
                direction_alignment=align,
            )
        )

    # Sort by abs(weighted_value) descending — most influential first
    activations.sort(key=lambda a: abs(a.weighted_value), reverse=True)

    applicable_thresh = long_thresh if direction == "long" else short_thresh
    conviction_gap = abs(weighted_conviction) - applicable_thresh

    trace = ActivationTrace(
        trade_id=trade_id,
        ticker=ticker,
        cycle=cycle,
        version=version,
        timestamp=datetime.now(UTC).isoformat(),
        direction=direction,
        activations=activations,
        raw_composite=float(sig.get("_raw_composite", sig.get("composite", 0.0))),
        demeaned_composite=float(sig.get("composite", 0.0)),
        basket_mean=basket_mean,
        basket_std=basket_std,
        weighted_conviction=weighted_conviction,
        long_thresh=long_thresh,
        short_thresh=short_thresh,
        thresh_scale=thresh_scale,
        wc_thresh=wc_thresh,
        conviction_gap=conviction_gap,
        filters_passed=filters_passed or [],
        blocking_filter=blocking_filter,
        final_decision=final_decision,
        regime=regime,
        bear_prob=bear_prob,
        bull_prob=bull_prob,
        is_crisis=is_crisis,
        is_high_vol=is_high_vol,
        ricci=float(sig.get("ricci_curvature_signal", sig.get("ricci_scalar", 0.0))),
        fiedler_zscore=float(sig.get("_fiedler_zscore", 0.0)),
        crash_prox=float(sig.get("_geometry_crash_prox", 0.0)),
        orc_mean=float(sig.get("orc_mean", 0.0)),
        momentum_derivative=float(sig.get("momentum_derivative", 0.0)),
        conviction_trend=float(sig.get("conviction_trend", 0.0)),
        agreement_trend=float(sig.get("agreement_trend", 0.0)),
        conviction_level=conviction_level,
        allocated_size=allocated_size,
        kelly_scale=kelly_scale,
    )
    return trace
