"""
omega/nodes/victoria/confidence_surface.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Continuous confidence surfaces for the Victoria strategy engine.

Replaces every binary gate (if x > θ: continue) with a smooth sigmoid surface
that maps signal values to position-size confidence factors c ∈ [0, 1].

Final position size = base_size × Π(cᵢ) for all applicable confidence factors.

See docs/architecture/adaptive-engine-v2.md for full mathematical derivation.

Design principles
-----------------
1. Stateless: all state lives in SurfaceConfig. Evaluation is a pure function.
2. Multiplicative: all confidence factors multiply. No additive blending.
3. Calibrated defaults: centers (μ) and temperatures (T) derived from Phase A
   snapshot empirical data, not arbitrary choices.
4. Composable: additional surfaces (ensemble voting, Bayesian regime) slot into
   the same multiplicative product without redesigning the evaluator.
5. Observable: every factor is logged individually for the decision trace.

Usage
-----
    from omega.nodes.victoria.confidence_surface import ConfidenceSurface, SurfaceConfig

    # Use calibrated defaults derived from Phase A data:
    surface = ConfidenceSurface()

    # Long entry:
    result = surface.evaluate_long(
        bear_prob=0.45,
        composite=0.12,
        regime="normal",
        llm_modifier=0.65,
    )
    # result.confidence ∈ [0, 1]; result.factors has per-dimension breakdown
    size = base_size * result.confidence

    # Short entry:
    result = surface.evaluate_short(
        bear_prob=0.55,
        composite=-0.08,
        regime="crisis",
        llm_modifier=0.75,
    )

Feature flag
------------
    VictoriaFeatures.continuous_surfaces = True   (default False → hard-gate behaviour)

The flag gates ALL surface evaluation. When False, the existing hard-gate logic
in strategy.py is unchanged. When True, the hard gates are bypassed and sizing
uses the multiplicative confidence product.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    """Numerically stable logistic function. Returns value in (0, 1)."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def _increasing(x: float, center: float, temperature: float) -> float:
    """Confidence rises as x increases past center. c(center) = 0.5."""
    return _sigmoid((x - center) / temperature)


def _decreasing(x: float, center: float, temperature: float) -> float:
    """Confidence falls as x increases past center. c(center) = 0.5."""
    return _sigmoid(-(x - center) / temperature)


# ---------------------------------------------------------------------------
# Surface parameters
# ---------------------------------------------------------------------------


@dataclass
class SurfaceParams:
    """
    Center and temperature for a single sigmoid surface.

    center      : midpoint of the transition (analogous to old threshold θ).
                  c(center) = 0.5 always.
    temperature : sharpness of the transition.
                  T → 0   : approaches hard gate (high sensitivity).
                  T = 0.10: 80% of transition in ±2T window.
                  T → ∞   : approaches constant 0.5 (uniform uncertainty).
    """

    center: float
    temperature: float

    def __post_init__(self) -> None:
        if self.temperature <= 0:
            raise ValueError(f"SurfaceParams.temperature must be > 0, got {self.temperature}")


@dataclass
class RegimeBaseWeights:
    """
    Per-regime base weights applied before the sigmoid surfaces.

    These are NOT hard gates — they are multipliers in [0, 1] that represent
    the regime's baseline suitability for each direction. The sigmoid surface
    on bear_prob further refines within each regime.

    Calibrated from Phase A win-rate by regime and direction:
    - crisis/long:   23% WR across V137-V141 → low baseline (0.30)
    - crisis/short:  58% WR → high baseline (0.90)
    - high_vol:      0% WR both directions → very low baseline (0.15/0.30)
    - normal/long:   32% WR → moderate baseline (0.80)
    - normal/short:  34% WR → moderate baseline (0.75)
    - bull/long:     ~50% WR (insufficient data) → optimistic (0.90)
    - bull/short:    ~30% WR → conservative (0.30)
    """

    # Long direction baselines
    crisis_long: float = 0.30
    high_vol_long: float = 0.15
    normal_long: float = 0.80
    bull_long: float = 0.90

    # Short direction baselines
    crisis_short: float = 0.90
    high_vol_short: float = 0.30
    normal_short: float = 0.75
    bull_short: float = 0.30

    def long_base(self, regime: str) -> float:
        mapping = {
            "crisis": self.crisis_long,
            "high_vol": self.high_vol_long,
            "normal": self.normal_long,
            "bull": self.bull_long,
            "sideways": self.normal_long,  # alias
        }
        return mapping.get(regime.lower(), self.normal_long)

    def short_base(self, regime: str) -> float:
        mapping = {
            "crisis": self.crisis_short,
            "high_vol": self.high_vol_short,
            "normal": self.normal_short,
            "bull": self.bull_short,
            "sideways": self.normal_short,
        }
        return mapping.get(regime.lower(), self.normal_short)


@dataclass
class SurfaceConfig:
    """
    Complete surface configuration for one strategy variant.

    All centers and temperatures are calibrated defaults from Phase A data.
    The meta-learning layer (V144) will update these at runtime.

    Calibration notes (derived from bt_v139_recent_trades.csv):
    - Winning long trades: mean bear_prob ≈ 0.28, median composite ≈ 0.12
    - Losing long trades:  mean bear_prob ≈ 0.46, median composite ≈ 0.07
    - Optimal bear_prob center ≈ midpoint = 0.37 (→ rounded to 0.40 for conservatism)
    - Optimal composite center ≈ 0.08 (midpoint of winning vs losing medians)
    """

    # ── Bear probability surface (for long entries) ──
    # c_bear_long(bp) = σ(-(bp - center) / T)
    # At bp=0.40: c=0.50. At bp=0.20: c=0.88. At bp=0.60: c=0.12.
    bear_long: SurfaceParams = field(
        default_factory=lambda: SurfaceParams(center=0.35, temperature=0.12)
    )

    # ── Bear probability surface (for short entries) ──
    # c_bear_short(bp) = σ((bp - center) / T)
    # Shorts benefit from higher bear_prob. At bp=0.35: c=0.50.
    bear_short: SurfaceParams = field(
        default_factory=lambda: SurfaceParams(center=0.35, temperature=0.12)
    )

    # ── Composite conviction surface (long entries) ──
    # c_composite_long(comp) = σ((comp - center) / T)
    # Positive composite → favorable for longs. Center at 0.08 = minimum meaningful long signal.
    composite_long: SurfaceParams = field(
        default_factory=lambda: SurfaceParams(center=0.08, temperature=0.04)
    )

    # ── Composite conviction surface (short entries) ──
    # Victoria composite is the long-side basket signal (usually positive).
    # We use abs(comp) as signal strength; direction is captured by bear_prob + regime.
    # c_composite_short(comp) = σ((|comp| - center) / T)
    composite_short: SurfaceParams = field(
        default_factory=lambda: SurfaceParams(center=0.05, temperature=0.03)
    )

    # ── Regime base weights ──
    regime_weights: RegimeBaseWeights = field(default_factory=RegimeBaseWeights)

    # ── Minimum confidence to enter a position ──
    # Below this, the position is skipped (the effective "block").
    # 0.20 is chosen so that regime base weights act as implicit hard gates:
    #   high_vol_long=0.15 → max confidence=0.15 → always blocked (natural high_vol gate)
    #   crisis_long=0.30 → only top crisis longs (low bear_prob + strong composite) enter
    #   normal/bull longs typically reach 0.25–0.60 → enter
    # This preserves the parameter-sensitivity smoothness of the sigmoid while
    # maintaining regime-level filtering equivalent to the old hard gates.
    min_confidence: float = 0.20

    # ── Temperature bounds for meta-learner ──
    # The meta-learner adjusts temperatures within these bounds.
    T_min: float = 0.05
    T_max: float = 0.30


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------


@dataclass
class SurfaceResult:
    """
    Result of evaluating the confidence surface for one trade direction.

    Attributes
    ----------
    confidence      : final multiplicative product ∈ [0, 1].
    c_bear          : bear_prob confidence factor.
    c_composite     : composite signal confidence factor.
    c_regime_base   : regime baseline weight.
    c_llm           : LLM modifier confidence factor.
    should_enter    : True if confidence >= min_confidence.
    debug_str       : human-readable factor breakdown.
    """

    confidence: float
    c_bear: float
    c_composite: float
    c_regime_base: float
    c_llm: float
    should_enter: bool
    debug_str: str

    def as_dict(self) -> dict:
        return {
            "confidence": round(self.confidence, 4),
            "c_bear": round(self.c_bear, 4),
            "c_composite": round(self.c_composite, 4),
            "c_regime_base": round(self.c_regime_base, 4),
            "c_llm": round(self.c_llm, 4),
            "should_enter": self.should_enter,
        }


# ---------------------------------------------------------------------------
# ConfidenceSurface
# ---------------------------------------------------------------------------


class ConfidenceSurface:
    """
    Stateless evaluator for continuous entry confidence.

    Instantiate once per strategy run (or per SurfaceConfig variant).
    Thread-safe: no mutable state.
    """

    def __init__(self, config: SurfaceConfig | None = None) -> None:
        self.config = config or SurfaceConfig()

    # ------------------------------------------------------------------
    # Long entry confidence
    # ------------------------------------------------------------------

    def evaluate_long(
        self,
        bear_prob: float,
        composite: float,
        regime: str,
        llm_modifier: float = 1.0,
    ) -> SurfaceResult:
        """
        Compute multiplicative confidence for a long entry.

        Parameters
        ----------
        bear_prob     : Wasserstein bear probability ∈ [0, 1].
        composite     : Weighted signal composite (positive = bullish).
        regime        : Regime label ("crisis", "high_vol", "normal", "bull").
        llm_modifier  : LLM conviction modifier ∈ [0, 1]. 1.0 = no LLM call.

        Returns
        -------
        SurfaceResult with confidence ∈ [0, 1].
        """
        cfg = self.config

        # Factor 1: bear probability (longs want LOW bear_prob)
        c_bear = _decreasing(
            bear_prob,
            cfg.bear_long.center,
            cfg.bear_long.temperature,
        )

        # Factor 2: composite conviction (longs want HIGH composite)
        # Clamp composite to [-1, 1] to prevent extreme inputs distorting sigmoid
        comp_clamped = max(-1.0, min(1.0, composite))
        c_composite = _increasing(
            comp_clamped,
            cfg.composite_long.center,
            cfg.composite_long.temperature,
        )

        # Factor 3: regime baseline weight
        c_regime_base = cfg.regime_weights.long_base(regime)

        # Factor 4: LLM modifier (already in [0, 1]; no hard veto)
        # Clamp to [0, 1] to guard against upstream encoding bugs
        c_llm = max(0.0, min(1.0, llm_modifier))

        # Multiplicative product
        confidence = c_bear * c_composite * c_regime_base * c_llm
        should_enter = confidence >= cfg.min_confidence

        debug_str = (
            f"long confidence={confidence:.4f} "
            f"[bear={c_bear:.3f}×comp={c_composite:.3f}×regime={c_regime_base:.2f}×llm={c_llm:.2f}] "
            f"(bear_prob={bear_prob:.3f}, comp={composite:.4f}, regime={regime})"
        )

        return SurfaceResult(
            confidence=confidence,
            c_bear=c_bear,
            c_composite=c_composite,
            c_regime_base=c_regime_base,
            c_llm=c_llm,
            should_enter=should_enter,
            debug_str=debug_str,
        )

    # ------------------------------------------------------------------
    # Short entry confidence
    # ------------------------------------------------------------------

    def evaluate_short(
        self,
        bear_prob: float,
        composite: float,
        regime: str,
        llm_modifier: float = 1.0,
    ) -> SurfaceResult:
        """
        Compute multiplicative confidence for a short entry.

        Parameters
        ----------
        bear_prob     : Wasserstein bear probability ∈ [0, 1].
        composite     : Weighted signal composite (negative = bearish for shorts).
        regime        : Regime label.
        llm_modifier  : LLM conviction modifier ∈ [0, 1].
        """
        cfg = self.config

        # Factor 1: bear probability (shorts want HIGH bear_prob)
        c_bear = _increasing(
            bear_prob,
            cfg.bear_short.center,
            cfg.bear_short.temperature,
        )

        # Factor 2: composite conviction (use signal magnitude, not direction)
        # Victoria's composite is the LONG-side basket signal (usually positive even when
        # shorting individual assets). Using abs() treats it as signal strength:
        # high |composite| = strong signal (bullish OR bearish) = higher short confidence.
        # Direction is already encoded in bear_prob + regime_weight.
        comp_clamped = max(-1.0, min(1.0, composite))
        c_composite = _increasing(
            abs(comp_clamped),
            cfg.composite_short.center,
            cfg.composite_short.temperature,
        )

        # Factor 3: regime baseline weight
        c_regime_base = cfg.regime_weights.short_base(regime)

        # Factor 4: LLM modifier
        c_llm = max(0.0, min(1.0, llm_modifier))

        confidence = c_bear * c_composite * c_regime_base * c_llm
        should_enter = confidence >= cfg.min_confidence

        debug_str = (
            f"short confidence={confidence:.4f} "
            f"[bear={c_bear:.3f}×comp={c_composite:.3f}×regime={c_regime_base:.2f}×llm={c_llm:.2f}] "
            f"(bear_prob={bear_prob:.3f}, comp={composite:.4f}, regime={regime})"
        )

        return SurfaceResult(
            confidence=confidence,
            c_bear=c_bear,
            c_composite=c_composite,
            c_regime_base=c_regime_base,
            c_llm=c_llm,
            should_enter=should_enter,
            debug_str=debug_str,
        )

    # ------------------------------------------------------------------
    # Batch evaluation (for sensitivity testing)
    # ------------------------------------------------------------------

    def sensitivity_grid(
        self,
        trades: list[dict],
        centers: list[float],
        direction: Literal["long", "short"] = "long",
        temperature: float | None = None,
    ) -> dict[float, float]:
        """
        Evaluate total simulated PnL across a grid of bear_prob center values.

        Used for the parameter sensitivity test (see adaptive-engine-v2.md §2.4):
            Run once with centers=[0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
            Target: max(pnl_by_center) - min(pnl_by_center) < $5,000

        Parameters
        ----------
        trades    : List of trade dicts with keys: bear_prob, composite, regime,
                    pnl, llm_modifier (optional).
        centers   : Bear_prob center values to test.
        direction : "long" or "short".
        temperature: Override temperature for the sweep. None uses config default.

        Returns
        -------
        Dict[center → simulated_pnl]
        """
        results: dict[float, float] = {}
        original_center = (
            self.config.bear_long.center if direction == "long" else self.config.bear_short.center
        )
        original_temperature = (
            self.config.bear_long.temperature
            if direction == "long"
            else self.config.bear_short.temperature
        )

        for center in centers:
            # Temporarily set center for this sweep point
            if direction == "long":
                self.config.bear_long.center = center
                if temperature is not None:
                    self.config.bear_long.temperature = temperature
            else:
                self.config.bear_short.center = center
                if temperature is not None:
                    self.config.bear_short.temperature = temperature

            total_pnl = 0.0
            for t in trades:
                bp = float(t.get("bear_prob", 0.3))
                comp = float(t.get("composite", 0.10))
                regime = str(t.get("regime", "normal"))
                pnl = float(t.get("pnl", 0.0))
                llm_mod = float(t.get("llm_modifier", 1.0) or 1.0)

                if direction == "long":
                    result = self.evaluate_long(bp, comp, regime, llm_mod)
                else:
                    result = self.evaluate_short(bp, comp, regime, llm_mod)

                # Scale pnl by confidence (simulates position-sizing effect)
                total_pnl += pnl * result.confidence

            results[center] = round(total_pnl, 2)

        # Restore original parameters
        if direction == "long":
            self.config.bear_long.center = original_center
            self.config.bear_long.temperature = original_temperature
        else:
            self.config.bear_short.center = original_center
            self.config.bear_short.temperature = original_temperature

        return results


# ---------------------------------------------------------------------------
# Surface calibration from Phase A trade data
# ---------------------------------------------------------------------------


def calibrate_from_trades(
    trades: list[dict],
    direction: Literal["long", "short"] = "long",
    min_trades: int = 20,
) -> SurfaceParams:
    """
    Derive bear_prob surface parameters from empirical Phase A trade data.

    Algorithm:
        1. Separate winning and losing trades by direction.
        2. Compute mean bear_prob for each group.
        3. Center = midpoint of the two means.
        4. Temperature = 1.5 × std_dev of bear_prob among boundary trades
           (those within ±0.15 of the center).

    Parameters
    ----------
    trades     : List of trade dicts with keys: bear_prob, pnl, side.
    direction  : "long" or "short" — which side to calibrate.
    min_trades : Minimum trades required for calibration (returns defaults if < min).

    Returns
    -------
    SurfaceParams for the bear_prob surface.
    """
    if direction == "long":
        side_trades = [t for t in trades if str(t.get("side", "")).lower() == "long"]
    else:
        side_trades = [t for t in trades if str(t.get("side", "")).lower() == "short"]

    if len(side_trades) < min_trades:
        # Not enough data — return calibrated defaults
        default_center = 0.40 if direction == "long" else 0.35
        return SurfaceParams(center=default_center, temperature=0.12)

    wins = [
        float(t["bear_prob"])
        for t in side_trades
        if float(t.get("pnl", 0)) > 0 and "bear_prob" in t
    ]
    losses = [
        float(t["bear_prob"])
        for t in side_trades
        if float(t.get("pnl", 0)) < 0 and "bear_prob" in t
    ]

    if not wins or not losses:
        default_center = 0.40 if direction == "long" else 0.35
        return SurfaceParams(center=default_center, temperature=0.12)

    mean_win = sum(wins) / len(wins)
    mean_loss = sum(losses) / len(losses)
    center = (mean_win + mean_loss) / 2.0

    # Temperature from std of boundary trades
    boundary = [t for t in side_trades if abs(float(t.get("bear_prob", 0)) - center) < 0.15]
    if len(boundary) >= 5:
        bp_vals = [float(t["bear_prob"]) for t in boundary]
        mean_bp = sum(bp_vals) / len(bp_vals)
        variance = sum((v - mean_bp) ** 2 for v in bp_vals) / len(bp_vals)
        std_bp = variance**0.5
        temperature = max(0.05, min(0.25, std_bp * 1.5))
    else:
        temperature = 0.12  # default

    return SurfaceParams(center=round(center, 3), temperature=round(temperature, 3))


# ---------------------------------------------------------------------------
# Sensitivity test (standalone, callable from backtesting scripts)
# ---------------------------------------------------------------------------


def run_sensitivity_test(
    csv_path: str,
    centers: list[float] | None = None,
    temperatures: list[float] | None = None,
    direction: Literal["long", "short"] = "long",
) -> dict:
    """
    Run the parameter sensitivity grid test from a trades CSV.

    Expected CSV columns: bear_prob (optional), composite, regime, pnl, side, llm_modifier (optional).

    Returns dict with:
        pnl_by_center    : dict[center → total pnl]
        sensitivity_range: max - min pnl across centers
        target_met       : True if sensitivity_range < $5,000
        pnl_by_temp      : per-temperature sensitivity (if temperatures provided)
        hard_gate_range  : simulated hard-gate sensitivity for comparison
    """
    import csv

    if centers is None:
        centers = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    if temperatures is None:
        temperatures = [0.05, 0.10, 0.15, 0.20]

    try:
        with open(csv_path) as f:
            trades = list(csv.DictReader(f))
    except FileNotFoundError:
        return {"error": f"CSV not found: {csv_path}"}

    side_trades = [t for t in trades if str(t.get("side", "")).lower() == direction]
    if not side_trades:
        return {"error": f"No {direction} trades in {csv_path}"}

    surface = ConfidenceSurface()

    # Sigmoid sensitivity per temperature
    pnl_by_temp: dict[float, dict[float, float]] = {}
    for temp in temperatures:
        grid = surface.sensitivity_grid(side_trades, centers, direction, temperature=temp)
        pnl_by_temp[temp] = grid

    # Hard-gate comparison: simulate binary gate at each center
    hard_gate_pnl: dict[float, float] = {}
    for center in centers:
        total = 0.0
        for t in side_trades:
            bp = float(t.get("bear_prob", 0.30))
            pnl = float(t.get("pnl", 0.0))
            if direction == "long":
                # Long admitted when bear_prob < center (below threshold)
                if bp < center:
                    total += pnl
            else:
                # Short admitted when bear_prob > center (above threshold)
                if bp > center:
                    total += pnl
        hard_gate_pnl[center] = round(total, 2)

    # Sensitivity ranges
    hard_range = max(hard_gate_pnl.values()) - min(hard_gate_pnl.values())
    sigmoid_ranges = {T: max(g.values()) - min(g.values()) for T, g in pnl_by_temp.items()}
    best_sigmoid_range = min(sigmoid_ranges.values())

    return {
        "direction": direction,
        "n_trades": len(side_trades),
        "centers_tested": centers,
        "temperatures_tested": temperatures,
        "hard_gate_pnl": hard_gate_pnl,
        "hard_gate_sensitivity": round(hard_range, 2),
        "sigmoid_pnl_by_temp": pnl_by_temp,
        "sigmoid_sensitivity_by_temp": {T: round(r, 2) for T, r in sigmoid_ranges.items()},
        "best_sigmoid_sensitivity": round(best_sigmoid_range, 2),
        "target_met": best_sigmoid_range < 5000.0,
        "reduction_factor": round(hard_range / max(best_sigmoid_range, 1.0), 2),
    }


# ---------------------------------------------------------------------------
# Feature flag integration point (used by strategy.py)
# ---------------------------------------------------------------------------

# Default surface instance, shared across all strategy evaluations unless
# overridden by VictoriaFeatures.surface_config.
_DEFAULT_SURFACE = ConfidenceSurface()


def get_surface(features: Any) -> ConfidenceSurface:
    """
    Return the ConfidenceSurface for this feature configuration.

    If features.surface_config is set (a SurfaceConfig instance), use it.
    Otherwise return the calibrated default.
    """
    sc = getattr(features, "surface_config", None)
    if sc is not None and isinstance(sc, SurfaceConfig):
        return ConfidenceSurface(sc)
    return _DEFAULT_SURFACE
