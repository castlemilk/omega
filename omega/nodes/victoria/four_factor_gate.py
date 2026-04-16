"""
omega/nodes/victoria/four_factor_gate.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Four-factor AND-gate entry/exit filter (V133).

All four gates must pass for entry. Any gate breaking triggers exit evaluation.

Gates
-----
1. cross_market_divergence_gate  — model vs market-implied probability
2. disposition_gate              — rolling exit discipline
3. capital_velocity_gate         — portfolio utilisation + position count
4. pair_network_gate             — ORC / Fiedler network health

Design reference: docs/research/four-factor-and-gate-design.md

Entry usage (strategy.py:_construct_portfolio)
-----------------------------------------------
    from omega.nodes.victoria.four_factor_gate import FourFactorGate, GateContext
    gate = FourFactorGate(features)
    ctx = GateContext(
        w_conv          = w_conv,
        funding_rate    = float(sig.get("funding_rate_signal", 0.0)),
        closed_trades   = engine.closed_trades,
        open_positions  = engine.positions,
        initial_capital = engine.initial_capital,
        orc_kappa       = float(signals.get("_geometry_orc_kappa") or 0) or None,
        fiedler_zscore  = float(_spectral_val.value) if _spectral_val else None,
    )
    result = gate.evaluate(ctx)
    if not result.all_pass:
        continue   # skip ticker; reason in result.failing_gates

Exit usage (paper_trading.py:mark_to_market)
---------------------------------------------
    result = gate.evaluate_exit(ctx, pos)
    if result.any_broken:
        close = True
        reason = f"gate_break:{','.join(result.failing_gates)}"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Context / Result types
# ---------------------------------------------------------------------------


@dataclass
class GateContext:
    """All inputs needed by FourFactorGate for a single evaluation."""

    w_conv: float
    """IC-weighted composite pre-threshold (from _compute_weighted_conviction)."""

    funding_rate: float
    """sig["funding_rate_signal"]; 0.0 when absent (e.g. geo-blocked exchange)."""

    closed_trades: list[dict[str, Any]]
    """PaperTradingEngine._closed_trades — used by disposition gate."""

    open_positions: dict[str, dict]
    """PaperTradingEngine._positions — used by capital_velocity gate."""

    initial_capital: float
    """PaperTradingEngine.initial_capital — denominator for utilisation."""

    orc_kappa: float | None = None
    """signals["_geometry_orc_kappa"]; None during warmup or when ORC disabled."""

    fiedler_zscore: float | None = None
    """_spectral_val.value (z-score); None during warmup."""


@dataclass
class GateResult:
    """Result of evaluating all four gates."""

    all_pass: bool
    cross_market_divergence: bool
    disposition: bool
    capital_velocity: bool
    pair_network: bool

    # Diagnostics (logged + written to activation trace when available)
    p_model: float = 0.0
    p_implied: float = 0.0
    divergence: float = 0.0
    disposition_coefficient: float | None = None
    utilization: float = 0.0
    n_positions: int = 0
    failing_gates: list[str] = field(default_factory=list)

    @property
    def any_broken(self) -> bool:
        return not self.all_pass

    def summary(self) -> str:
        """One-line human-readable summary for logging."""
        if self.all_pass:
            parts = [
                f"cmd_div={self.divergence:.3f}",
                f"disp={self.disposition_coefficient:.3f}" if self.disposition_coefficient is not None else "disp=cold",
                f"util={self.utilization:.2f}",
                f"orc={self.p_model:.3f}",
            ]
            return "pass(" + " ".join(parts) + ")"
        return "FAIL[" + "; ".join(self.failing_gates) + "]"


# ---------------------------------------------------------------------------
# Gate implementation
# ---------------------------------------------------------------------------


class FourFactorGate:
    """
    Evaluates the four-factor AND-gate for entry and exit decisions.

    Designed as a stateless callable: all position state lives in GateContext.
    Instantiate once per portfolio-construction call (cheap).
    """

    def __init__(self, features: Any) -> None:
        # Read parameters from VictoriaFeatures, falling back to design defaults.
        self._sigmoid_scale: float = getattr(features, "ffg_sigmoid_scale", 5.0)
        self._divergence_threshold: float = getattr(features, "ffg_divergence_threshold", 0.05)
        self._disposition_window: int = int(getattr(features, "ffg_disposition_window", 50))
        self._disposition_min_trades: int = int(getattr(features, "ffg_disposition_min_trades", 10))
        self._utilization_cap: float = getattr(features, "ffg_utilization_cap", 0.50)
        self._max_positions: int = int(getattr(features, "ffg_max_positions", 5))
        self._orc_threshold: float = getattr(features, "ffg_orc_threshold", -0.3)
        self._fiedler_floor: float = getattr(features, "ffg_fiedler_floor", 0.0)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sigmoid(x: float) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    # ------------------------------------------------------------------
    # Individual gate evaluators
    # ------------------------------------------------------------------

    def _gate1_cross_market(
        self, ctx: GateContext
    ) -> tuple[bool, float, float, float]:
        """
        Gate 1: cross_market_divergence_gate.

        Passes when |p_model - p_implied| >= divergence_threshold.
        Prevents zero-edge trades where model and market already agree.
        """
        FUNDING_CLIP = 0.001

        p_model = self._sigmoid(ctx.w_conv * self._sigmoid_scale)

        fr_clipped = max(-FUNDING_CLIP, min(FUNDING_CLIP, ctx.funding_rate))
        # Linear map: fr=0 → 0.50, fr=+clip → 0.75, fr=−clip → 0.25
        p_implied = 0.50 + (fr_clipped / FUNDING_CLIP) * 0.25

        divergence = abs(p_model - p_implied)
        passes = divergence >= self._divergence_threshold
        return passes, p_model, p_implied, divergence

    def _gate2_disposition(
        self, ctx: GateContext
    ) -> tuple[bool, float | None]:
        """
        Gate 2: disposition_gate.

        Passes when rolling median(win_capture) - median(loss_capture) > 0.
        Blocks new entries when exit discipline has collapsed.
        Cold-start (< min_trades): passes by default.
        """
        from omega.nodes.victoria.exit_controller import aggregate_disposition  # local to avoid circular

        n = len(ctx.closed_trades)
        if n < self._disposition_min_trades:
            return True, None  # cold-start: insufficient data

        recent = ctx.closed_trades[-self._disposition_window:]
        stats = aggregate_disposition(recent)
        disp = stats.get("disposition_coefficient")
        if disp is None:
            return True, None  # no telemetry (pre-V128 trades): pass
        return disp > 0.0, disp

    def _gate3_capital_velocity(
        self, ctx: GateContext
    ) -> tuple[bool, float, int]:
        """
        Gate 3: capital_velocity_gate.

        Passes when open_notional / initial_capital < utilization_cap
        AND len(open_positions) < max_positions.
        Prevents overleverage and concentration risk.
        """
        positions = {
            sym: pos
            for sym, pos in ctx.open_positions.items()
            if abs(pos.get("size", 0.0)) > 1e-6
        }
        open_notional = sum(abs(p.get("size", 0.0)) for p in positions.values())
        cap = ctx.initial_capital if ctx.initial_capital > 0 else 1.0
        utilization = open_notional / cap
        n_pos = len(positions)
        passes = utilization < self._utilization_cap and n_pos < self._max_positions
        return passes, utilization, n_pos

    def _gate4_pair_network(self, ctx: GateContext) -> bool:
        """
        Gate 4: pair_network_gate.

        Passes when ORC mean curvature > orc_threshold (default −0.3).
        Blocks entry during asset-correlation network fragmentation.
        Falls back to Fiedler z-score if ORC unavailable.
        Passes conservatively during warmup (both absent or zero).

        Note: fiedler_zscore=0.0 is the system's warmup/not-yet-computed
        sentinel (SpectralGatewaySignal returns 0.0 until the correlation
        window fills). Treat it as absent so the gate passes during backtest
        snapshots where Fiedler never reaches a stable z-score.
        """
        if ctx.orc_kappa is not None:
            return ctx.orc_kappa > self._orc_threshold
        if ctx.fiedler_zscore is not None and ctx.fiedler_zscore != 0.0:
            return ctx.fiedler_zscore > self._fiedler_floor
        return True  # warmup (fiedler=0.0 or both absent): pass conservatively

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, ctx: GateContext) -> GateResult:
        """
        Evaluate all four gates for an entry decision.

        All four gates must pass; any failure blocks entry.
        """
        g1, p_model, p_implied, divergence = self._gate1_cross_market(ctx)
        g2, disp = self._gate2_disposition(ctx)
        g3, utilization, n_pos = self._gate3_capital_velocity(ctx)
        g4 = self._gate4_pair_network(ctx)

        failing: list[str] = []
        if not g1:
            failing.append(
                f"cross_market_divergence(div={divergence:.3f}<{self._divergence_threshold})"
            )
        if not g2:
            failing.append(f"disposition(coeff={disp:.3f}<=0)")
        if not g3:
            orc_info = (
                f"orc={ctx.orc_kappa:.3f}"
                if ctx.orc_kappa is not None
                else (
                    f"fiedler={ctx.fiedler_zscore:.3f}"
                    if ctx.fiedler_zscore is not None
                    else "no_orc"
                )
            )
            failing.append(f"capital_velocity(util={utilization:.2f},n={n_pos})")
        if not g4:
            orc_info = (
                f"orc={ctx.orc_kappa:.3f}"
                if ctx.orc_kappa is not None
                else (
                    f"fiedler={ctx.fiedler_zscore:.3f}"
                    if ctx.fiedler_zscore is not None
                    else "no_geometry"
                )
            )
            failing.append(f"pair_network({orc_info})")

        return GateResult(
            all_pass=g1 and g2 and g3 and g4,
            cross_market_divergence=g1,
            disposition=g2,
            capital_velocity=g3,
            pair_network=g4,
            p_model=p_model,
            p_implied=p_implied,
            divergence=divergence,
            disposition_coefficient=disp,
            utilization=utilization,
            n_positions=n_pos,
            failing_gates=failing,
        )

    def evaluate_exit(
        self, ctx: GateContext, pos: dict[str, Any]  # noqa: ARG002
    ) -> GateResult:
        """
        Evaluate gates for an open position — check if any gate has broken.

        Only gates 1, 3, and 4 are checked on exit.
        Gate 2 (disposition) is entry-only — closing positions because
        recent exit discipline has been bad creates a feedback loop.
        """
        g1, p_model, p_implied, divergence = self._gate1_cross_market(ctx)
        g3, utilization, n_pos = self._gate3_capital_velocity(ctx)
        g4 = self._gate4_pair_network(ctx)

        failing: list[str] = []
        if not g1:
            failing.append(
                f"cross_market_divergence(div={divergence:.3f}<{self._divergence_threshold})"
            )
        if not g3:
            failing.append(f"capital_velocity(util={utilization:.2f},n={n_pos})")
        if not g4:
            orc_info = (
                f"orc={ctx.orc_kappa:.3f}"
                if ctx.orc_kappa is not None
                else (
                    f"fiedler={ctx.fiedler_zscore:.3f}"
                    if ctx.fiedler_zscore is not None
                    else "no_geometry"
                )
            )
            failing.append(f"pair_network({orc_info})")

        return GateResult(
            all_pass=g1 and g3 and g4,
            cross_market_divergence=g1,
            disposition=True,   # not evaluated on exit
            capital_velocity=g3,
            pair_network=g4,
            p_model=p_model,
            p_implied=p_implied,
            divergence=divergence,
            disposition_coefficient=None,
            utilization=utilization,
            n_positions=n_pos,
            failing_gates=failing,
        )
