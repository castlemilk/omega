"""omega/nodes/victoria/features.py
Feature flag dataclass for Victoria strategy experiments.

All flags default False → V93 champion baseline (no experimental code).

Usage
-----
    from omega.nodes.victoria.features import VictoriaFeatures

    f = VictoriaFeatures.from_env()          # reads VICTORIA_FEATURES env var
    f = VictoriaFeatures.preset("v97_geometry")

Environment
-----------
    VICTORIA_FEATURES=v93_baseline           # named preset
    VICTORIA_FEATURES='{"ricci_sizing":true}'  # inline JSON overrides

Presets
-------
    v93_baseline          all flags OFF  (V93 champion config — the comparison baseline)
    v97_geometry          V95 geometry modifiers only
    observability_only    decision traces + confluence + correlation + anomaly
    embeddings_only       decision_embeddings + llm_trade_review
    v98_full_obs          everything that ran in V98 (geometry + observability)
    v99_full              all flags ON
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

logger = logging.getLogger("omega.victoria.features")


@dataclass
class VictoriaFeatures:
    # ------------------------------------------------------------------
    # Geometry modifiers (V95) — already in main, gatable for baseline
    # All four were present in V97/V98 but caused regression vs V93.
    # ------------------------------------------------------------------
    ricci_sizing: bool = False
    """V95 Ricci long_mult: reduce long sizes when approaching crash manifold."""

    orc_stress_reduction: bool = False
    """V95 ORC stress: reduce all sizes when Ollivier-Ricci curvature > 0.1."""

    geodesic_crash_distance: bool = False
    """V95 geodesic gate: raise long_thresh when crash_prox >= 0.6."""

    fiedler_conviction_modulation: bool = False
    """V95 Fiedler threshold tweaks: fragmented→lower short, consensus→lower both."""

    # ------------------------------------------------------------------
    # Observability stack (strange-clarke) — new in this refactor
    # ------------------------------------------------------------------
    decision_traces: bool = False
    """Write per-ticker DecisionTrace records to data/decision_traces/{version}.jsonl."""

    signal_confluence: bool = False
    """ConfluenceAnalyzer: boost/dampen sizes by sub-signal agreement ratio."""

    signal_correlation_monitor: bool = False
    """SignalCorrelationMonitor: 50-cycle rolling Pearson matrix, saved to /tmp."""

    anomaly_detector: bool = False
    """AnomalyDetector: 3σ deviation alerting on pnl_delta, trades, zero_streak."""

    # ------------------------------------------------------------------
    # LLM / embedding (hopeful-mendeleev — cherry-picked to main)
    # ------------------------------------------------------------------
    decision_embeddings: bool = False
    """DecisionEmbedder: KMeans cluster bias applied to conviction at inference."""

    llm_trade_review: bool = False
    """run_review(): post-trade LLM post-mortem written to data/decision_traces/."""

    # ------------------------------------------------------------------
    # Version-specific fixes from worktrees
    # ------------------------------------------------------------------
    v96_crisis_detection_fix: bool = False
    """elastic-buck: when bear_prob=-1, trust regime_label 'crisis' unconditionally."""

    v96_multi_cycle_bypass: bool = False
    """lucid-pascal: lower normal-short multi-cycle bypass threshold 0.09→0.07."""

    crisis_high_vol_long_block: bool = False
    """V101: hard-block all long allocations when regime is crisis OR high_vol.
    Short-side logic is unchanged. Combats the daily-report finding that normal-regime
    longs were +$169 but crisis/high_vol combined lost -$106 (V99, 200-cycle run).
    Cost: misses recovery longs in crisis (high false-positive rate during post-crash bounce).
    Benefit: eliminates the worst-performing long entries in adverse regimes.
    When to enable: pair with decision_embeddings (v101_regime_safe preset).
    """

    ws_microstructure: bool = False
    """V103: inject 6 real-time microstructure signals from Binance WebSocket feeds.
    order_book_imbalance, trade_flow_direction, spread_zscore, volume_profile,
    tick_momentum, liquidation_proximity. Requires websockets package.
    Degrades to 0.0 if WS unavailable.
    """

    temporal_memory: bool = False
    """V103: inject 8 temporal signal features using 20-cycle rolling history.
    momentum_derivative, funding_derivative, momentum_persistence, regime_duration,
    momentum_crossover, funding_crossover, conviction_trend, agreement_trend.
    """

    adaptive_combiner: bool = False
    """V103: replace static IC-weighted composite with adaptive combiner.
    Anti-predictive signals (IC < -0.02) are flipped rather than removed.
    Falls back to equal-weight when insufficient IC data.
    """

    crisis_short_bias: bool = False
    """V102: lean into fear in crisis/high_vol regimes.
    Threshold adjustments (applied after regime-adaptive base, before Fiedler):
      - short_thresh *= 0.60 (40% lower — more permissive short entry)
      - long_thresh  *= 1.50 (50% higher — further suppress longs)
    Size adjustments (applied after raw_weight computation, before Kelly):
      - short positions * 1.3x
      - long  positions * 0.5x
    In normal regime: lower short_thresh to 0.05 (captures cross-sectional underperformers).
    Motivated by V75: +$110 on 3 pure crisis shorts (+100% WR). V101b: ADA short +$111 in crisis.
    When to enable: pair with decision_embeddings (v102_fear_optimized preset).
    """

    trade_reinforcement: bool = False
    """V106: EMA-based per-signal reinforcement learning from closed trades.
    After 5+ closed trades, per-signal multipliers [0.2, 1.5] are applied to
    signal values in signal_generation.py before composite computation.
    Alignment rule: signals that consistently pointed the right direction get
    amplified; signals that were systematically wrong get dampened.
    State persists to data/reinforcement_state.json across runs.
    Also runs trade_attribution decomposition at each close (JSONL log).
    When to enable: pair with decision_embeddings + ws_microstructure + temporal_memory
    (v106_reinforced preset).
    """

    activation_tracing: bool = False
    """V107: record full computation graph for every trade entry and exit.
    Captures per-signal activations (raw_value, reinforcement_weight, ic_weight,
    final_weight, weighted_value, direction_alignment), composite scores, regime
    state, filter chain, and outcome attribution.
    Traces written to data/activation_traces/{version}.jsonl (one JSON per trade close).
    Completed traces include signals_right/signals_wrong tallies and per-signal PnL
    attribution from trade_attribution.py.
    View with: python scripts/view_activations.py --version {version}
    When to enable: pair with trade_reinforcement for full observability
    (v107_traced preset).
    """

    postmortem_signal_filter: bool = False
    """V112: zero out signals proven consistently wrong across 5+ training runs.
    Based on cross-version analysis of 124+ closed trades (V107-V110):
    DEAD_SIGNALS zeroed: sma_long, sma_short, price, return_1d (accuracy 37-44%,
    n=120+), sma_crossover (46.8% marginal), fear_greed_signal (44.4% marginal),
    liquidation_proximity (26.5%, n=34).
    These signals hurt composite quality despite having directional values.
    Evidence basis: scripts/cross_version_analysis.py output.
    (v112_evidence_based preset)
    """

    # ------------------------------------------------------------------
    # Phase 1 expansion (V115) — sub-second informed-flow vectors
    # ------------------------------------------------------------------
    whale_prints: bool = False
    """V115 Phase 1: inject 3 whale/informed-flow signals from WS tick data.
    whale_print: net buy/sell pressure from trades > 2σ above rolling mean size.
    book_depth_velocity: rate-of-change of bid vs ask depth at top-10 levels.
    vpin: volume-synchronised probability of informed trading (50-trade buckets).
    Requires ws_microstructure=True (shares the same WSFeedManager instance).
    """

    whale_flow: bool = False
    """V115 Phase 2: inject 3 whale smart-money signals from DefiLlama + OKX.
    exchange_net_flow: bridge inflow/outflow via DefiLlama (15-min cache).
    stablecoin_velocity: rate of change of total stablecoin supply (15-min cache).
    oi_rate_of_change: OKX perpetual swap OI derivative (no API key required).
    """

    funding_velocity: bool = False
    """V115 Phase 2: inject funding_rate_velocity — derivative of funding rate
    over last 3 readings.  Rising funding = worsening overleverage risk (bearish).
    Computed by FundingRateSignal.compute_velocity() on each cycle.
    """

    # ------------------------------------------------------------------
    # V128 exit discipline (disposition_coefficient fix)
    # ------------------------------------------------------------------

    disposition_exit_controller: bool = False
    """V128+ exit discipline controller.

    Replaces the fixed-percentage / time-based exit logic with ATR-anchored stops:
      - Hard MAE stop: close immediately when running loss >= mae_stop_k * ATR.
        Prevents "hold-and-pray" losers that drag MAE far past MFE.
      - MFE trailing stop: once peak gain >= mfe_trail_k * ATR, trail at
        MFE * (1 - mfe_retracement_cap) to lock 75% of peak (default).

    Phase A (April 2026): disposition_coefficient was -0.44 to -0.62 across all
    configs, confirming classic disposition effect. This controller targets > 0.0.

    See: omega.nodes.victoria.exit_controller.ExitController
    """

    mfe_trail_k: float = 1.0
    """ATR multiplier to activate MFE trailing stop (default 1.0 × ATR).
    Only used when disposition_exit_controller=True.
    """

    mfe_retracement_cap: float = 0.25
    """Fraction of MFE to give back before trailing fires (default 0.25 → lock 75%).
    Only used when disposition_exit_controller=True.
    """

    mae_stop_k: float = 0.8
    """ATR multiplier for hard MAE stop (default 0.8 × ATR).
    Only used when disposition_exit_controller=True.
    """

    # ------------------------------------------------------------------
    # V131 early loss time-stop
    # ------------------------------------------------------------------

    early_loss_time_stop: bool = False
    """V131: close losers that haven't recovered after N cycles.

    Fires when: age >= early_loss_cycles AND unrealized <= -(early_loss_k_atr × ATR).

    Root cause this fixes: with random 3-7 cycle time-exits and disabled hard stop
    (mae_stop_k=99.0), losing positions drift to their absolute worst point during
    the hold window → loss_capture=1.000 universally → disposition_coefficient
    permanently negative regardless of MFE trailing performance on winners.

    The fix: exit underwater positions at cycle N if they've already lost K×ATR,
    before they drift further. This gives loss_capture < 1.0 because pnl at exit
    is worse than entry but better than the eventual MAE at the random exit.

    See: omega.nodes.victoria.exit_controller.ExitController (early_loss_time_stop)
    """

    early_loss_cycles: int = 3
    """Minimum age (cycles) before early_loss_time_stop can fire. Default 3."""

    early_loss_k_atr: float = 0.3
    """ATR multiplier for early loss threshold (default 0.3 × ATR in $ terms).
    Lower values = tighter early exit; higher = give more room before cutting.
    """

    # ------------------------------------------------------------------
    # V130 regime entry gates
    # ------------------------------------------------------------------

    high_vol_short_block: bool = False
    """V130: hard-block new short entries when consolidated regime is 'high_vol'.

    Phase A analysis (April 2026): all high_vol losses across V129 runs were ETH
    shorts (6 trades, -$3,476 on recent / -$3,476 on trend snapshot). High_vol
    shorts work in prolonged bear markets (crisis) but fail in vol-spike recoveries
    where price bounces sharply against the short.

    V93 already blocks longs in high_vol unconditionally. This flag adds the
    symmetric block for shorts, eliminating the universal 'Regime catastrophe:
    high_vol' failure in Phase A gate checks.

    When to enable: pair with crisis_high_vol_long_block for full high_vol entry
    blackout (v130_high_vol_gate preset).
    """

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> VictoriaFeatures:
        """Load feature flags from VICTORIA_FEATURES env var.

        Accepts a preset name ('v93_baseline') or a JSON dict of flag overrides.
        Unknown keys are silently ignored so old env vars don't crash new code.
        """
        raw = os.environ.get("VICTORIA_FEATURES", "").strip()
        if not raw:
            return cls()
        if raw in _PRESETS:
            return _PRESETS[raw]
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "VICTORIA_FEATURES=%r is not a preset name or valid JSON — using v93_baseline", raw
            )
            return cls()
        valid = set(asdict(cls()))
        filtered = {k: v for k, v in overrides.items() if k in valid}
        unknown = set(overrides) - valid
        if unknown:
            logger.warning("VictoriaFeatures: ignoring unknown flags: %s", sorted(unknown))
        return cls(**filtered)

    @classmethod
    def preset(cls, name: str) -> VictoriaFeatures:
        if name not in _PRESETS:
            raise ValueError(f"Unknown preset {name!r}. Available: {sorted(_PRESETS)}")
        return _PRESETS[name]

    # Alias for ergonomic use in tests / notebooks
    from_preset = preset

    def active_flags(self) -> list[str]:
        """Return names of all True boolean flags, sorted."""
        return sorted(k for k, v in asdict(self).items() if isinstance(v, bool) and v)

    # Alias: enabled() → active_flags()
    def enabled(self) -> list[str]:
        """Return names of all True flags (alias for active_flags())."""
        return self.active_flags()

    def log_header(self) -> None:
        """Log a one-line summary of active flags."""
        active = self.active_flags()
        if active:
            logger.info("VictoriaFeatures ON: %s", ", ".join(active))
        else:
            logger.info("VictoriaFeatures: v93_baseline (all flags OFF)")

    def to_env(self) -> str:
        """Serialize to JSON string suitable for VICTORIA_FEATURES env var."""
        active = {k: True for k in self.active_flags()}
        return json.dumps(active) if active else ""


# ---------------------------------------------------------------------------
# Named presets
# ---------------------------------------------------------------------------

_PRESETS: dict[str, VictoriaFeatures] = {}

# Populated after class definition to allow forward references.
_PRESETS["v93_baseline"] = VictoriaFeatures()

_PRESETS["v97_geometry"] = VictoriaFeatures(
    ricci_sizing=True,
    orc_stress_reduction=True,
    geodesic_crash_distance=True,
    fiedler_conviction_modulation=True,
)

_PRESETS["observability_only"] = VictoriaFeatures(
    decision_traces=True,
    signal_confluence=True,
    signal_correlation_monitor=True,
    anomaly_detector=True,
)

_PRESETS["embeddings_only"] = VictoriaFeatures(
    decision_embeddings=True,
    llm_trade_review=True,
)

_PRESETS["v98_full_obs"] = VictoriaFeatures(
    ricci_sizing=True,
    orc_stress_reduction=True,
    geodesic_crash_distance=True,
    fiedler_conviction_modulation=True,
    decision_traces=True,
    signal_confluence=True,
    signal_correlation_monitor=True,
    anomaly_detector=True,
)

_PRESETS["v99_full"] = VictoriaFeatures(
    ricci_sizing=True,
    orc_stress_reduction=True,
    geodesic_crash_distance=True,
    fiedler_conviction_modulation=True,
    decision_traces=True,
    signal_confluence=True,
    signal_correlation_monitor=True,
    anomaly_detector=True,
    decision_embeddings=True,
    llm_trade_review=True,
    v96_crisis_detection_fix=True,
    v96_multi_cycle_bypass=True,
)

_PRESETS["v101_regime_safe"] = VictoriaFeatures(
    decision_embeddings=True,
    crisis_high_vol_long_block=True,
)

_PRESETS["v102_fear_optimized"] = VictoriaFeatures(
    decision_embeddings=True,
    crisis_short_bias=True,
)

_PRESETS["v103_alpha"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
)

_PRESETS["v103_full"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    adaptive_combiner=True,
)

_PRESETS["v106_reinforced"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
)

_PRESETS["v107_traced"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
)

_PRESETS["v112_evidence_based"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
)

_PRESETS["v115_full_vectors"] = VictoriaFeatures(
    # V114 foundation
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    # Phase 1: sub-second informed-flow vectors
    whale_prints=True,
    # Phase 2: whale smart-money + funding velocity
    whale_flow=True,
    funding_velocity=True,
)

# V128: v115_full_vectors + ATR-based exit controller (disposition fix)
# Phase A target: disposition_coefficient > 0.0 (baseline was -0.44 to -0.62)
_PRESETS["v128_exit_v1"] = VictoriaFeatures(
    # V115 core (WS signals stripped in backtest mode automatically)
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    # V128 addition: ATR-based exit controller
    disposition_exit_controller=True,
    mfe_trail_k=1.0,
    mfe_retracement_cap=0.25,
    mae_stop_k=0.8,
)

# ---------------------------------------------------------------------------
# V129 exit parameter grid — MFE-trail-only (hard stop removed)
#
# V128 post-mortem:
#   - hard MAE stop (0.8×ATR) cut recovering positions → PnL regression
#   - loss_capture=1.0 by definition when hard stop fires (pnl==mae at trigger)
#   - win_capture improved to 0.60 — MFE trailing IS working
#
# Grid hypothesis: removing hard stop lets losers recover via time-exit,
# lowering loss_capture. Tighter trail locks more winner gains.
#
# mae_stop_k=99.0 effectively disables the hard stop (fires only at 99×ATR).
# ---------------------------------------------------------------------------

# v129a: early trail activation (0.5×ATR), tight lock (lock 85% of peak)
# Hypothesis: activates trail on smaller moves, cuts more winners early → higher win_capture
_PRESETS["v129_trail_tight"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    disposition_exit_controller=True,
    mfe_trail_k=0.5,          # activate at 0.5×ATR (earlier than V128's 1.0×)
    mfe_retracement_cap=0.15,  # lock 85% of peak gain
    mae_stop_k=99.0,           # hard stop disabled
)

# v129b: moderate trail (0.5×ATR), wider lock (lock 75% of peak) — control variant
# Same activation as v129a but allows 25% retracement before firing
_PRESETS["v129_trail_moderate"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    disposition_exit_controller=True,
    mfe_trail_k=0.5,           # activate at 0.5×ATR
    mfe_retracement_cap=0.25,  # lock 75% of peak (same as V128 cap, earlier activation)
    mae_stop_k=99.0,           # hard stop disabled
)

# v129c: loose trail (1.5×ATR activation), tight lock (lock 85%) — let it breathe first
# Hypothesis: wait for a larger move to confirm trend, then lock tightly
_PRESETS["v129_trail_loose"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    disposition_exit_controller=True,
    mfe_trail_k=1.5,           # activate at 1.5×ATR (later, bigger move required)
    mfe_retracement_cap=0.15,  # tight lock once activated
    mae_stop_k=99.0,           # hard stop disabled
)

# v130: high-vol entry gate — block all new entries (longs AND shorts) in high_vol regime.
# Phase A V129 diagnosis: 100% of high_vol losses were ETH shorts (-$3,476 per snapshot).
# V93 already blocks longs in high_vol; this preset adds crisis_high_vol_long_block (belt+
# suspenders for crisis) and the new high_vol_short_block for shorts.
# Base: v129_trail_moderate (best V129 aggregate PnL, $+1,332).
# Expected: eliminates Regime catastrophe: high_vol gate failure; restores trend-snapshot PnL.
_PRESETS["v130_high_vol_gate"] = VictoriaFeatures(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    # Exit discipline — carry forward best V129 params
    disposition_exit_controller=True,
    mfe_trail_k=0.5,
    mfe_retracement_cap=0.25,
    mae_stop_k=99.0,
    # V130: block ALL entries in high_vol regime
    crisis_high_vol_long_block=True,   # belt: block longs in crisis+high_vol (V101 flag)
    high_vol_short_block=True,         # new: block shorts in high_vol (V130 flag)
)

# ──────────────────────────────────────────────────────────────────────────────
# V131: early loss time-stop — fix loss_capture=1.000 structural issue
# ──────────────────────────────────────────────────────────────────────────────
#
# Problem diagnosed from V130 Phase A:
#   avg_loss_capture = 1.000 universally. With mae_stop_k=99.0 (hard stop disabled)
#   and random 3-7 cycle time-exits, losing positions drift to their MAE before the
#   timer fires. disposition_coefficient = win_capture - 1.0 ≈ 0.5 - 1.0 = -0.5.
#
# Fix: exit underwater positions at cycle N if already down K×ATR, before the
#   random timer fires at their worst point. loss_capture = |pnl_at_early_exit| /
#   |mae| < 1.0 because the position exits BEFORE reaching its worst point.
#
# Base: V130 (best PnL so far, agg +$16,853 vs V112's +$5,084). Keep high_vol gates.
# Drop crisis_high_vol_long_block (was regressing trend snapshot by -$4k vs V129m).
#
# Grid: 3 variants varying early_loss_cycles (N) and early_loss_k_atr (K).
# All share: mfe_trail_k=0.5, mfe_retracement_cap=0.25, mae_stop_k=99.0.

_V131_BASE = dict(
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    postmortem_signal_filter=True,
    whale_prints=True,
    whale_flow=True,
    funding_velocity=True,
    disposition_exit_controller=True,
    mfe_trail_k=0.5,
    mfe_retracement_cap=0.25,
    mae_stop_k=99.0,
    # Only high_vol_short_block — drop crisis_high_vol_long_block (hurt trend snapshot)
    high_vol_short_block=True,
    early_loss_time_stop=True,
)

# v131a: tight — exit after 2 cycles if down 0.3×ATR
# Hypothesis: catch losers early before they drift further; risk = cutting recoveries
_PRESETS["v131_early_N2K03"] = VictoriaFeatures(
    **_V131_BASE,
    early_loss_cycles=2,
    early_loss_k_atr=0.3,
)

# v131b: moderate — exit after 3 cycles if down 0.3×ATR (baseline grid point)
# Same K as v131a but 1 extra cycle of room to recover
_PRESETS["v131_early_N3K03"] = VictoriaFeatures(
    **_V131_BASE,
    early_loss_cycles=3,
    early_loss_k_atr=0.3,
)

# v131c: loose — exit after 3 cycles but only if down 0.5×ATR
# Higher K = larger loss required before cutting; fewer triggers but deeper cuts
_PRESETS["v131_early_N3K05"] = VictoriaFeatures(
    **_V131_BASE,
    early_loss_cycles=3,
    early_loss_k_atr=0.5,
)
