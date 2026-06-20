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

    trailing_stop_min_age: int = 0
    """V132: minimum position age (cycles) before the legacy 50%-MFE trailing
    stop is allowed to fire.  0 = original behaviour (fires at any age).
    Set to 3 or 4 to prevent the stop firing on new-low ticks at age 1-2,
    breaking the structural loss_capture=1.0 invariant.
    """

    stop_loss_min_age: int = 0
    """V133: minimum position age (cycles) before the legacy -2% ROI stop-loss
    is allowed to fire.  0 = original behaviour (fires immediately).
    Set to 3 so the stop-loss cannot fire at age 1-2 before early_loss_time_stop
    (age ≥ 3) can act.  This is the third and final unguarded exit path that
    causes structural loss_capture=1.0 alongside the trailing stop (V132 fix).
    """

    # ------------------------------------------------------------------
    # V133 four-factor AND-gate entry filter
    # ------------------------------------------------------------------

    four_factor_and_gate: bool = False
    """V133: Replace soft weighted-sum entry with four binary AND-gates.

    All four gates must pass for entry; any gate breaking triggers exit check.
      - cross_market_divergence_gate: |p_model − p_implied| ≥ threshold
      - disposition_gate: rolling median(win_capture) − median(loss_capture) > 0
      - capital_velocity_gate: open notional / capital < 50% AND positions < 5
      - pair_network_gate: ORC mean curvature > −0.3 (network not fragmented)

    Requires V131 early_loss_time_stop to be confirmed before enabling — Gate 2
    (disposition_gate) will permanently block entries when disposition_coefficient
    is structurally negative (−0.4 to −0.5 pre-V133).

    See: omega.nodes.victoria.four_factor_gate.FourFactorGate
    Spec: docs/research/four-factor-and-gate-design.md
    """

    ffg_sigmoid_scale: float = 5.0
    """Gate 1: sigmoid scale mapping w_conv to p_model probability.
    scale=5.0 maps w_conv=0.20 → p_model≈0.73.  Raise to sharpen sensitivity.
    """

    ffg_divergence_threshold: float = 0.05
    """Gate 1: minimum |p_model − p_implied| to pass cross_market_divergence gate.
    Default 0.05 = 5 percentage points.
    """

    ffg_disposition_window: int = 50
    """Gate 2: rolling window of recent closed trades for disposition calculation."""

    ffg_disposition_min_trades: int = 10
    """Gate 2: cold-start floor — gate passes freely until this many trades closed."""

    ffg_utilization_cap: float = 0.50
    """Gate 3: maximum open_notional / initial_capital before gate blocks entry."""

    ffg_max_positions: int = 5
    """Gate 3: maximum concurrent open positions before gate blocks entry."""

    ffg_orc_threshold: float = -0.3
    """Gate 4: minimum ORC mean curvature (orc_kappa) to pass pair_network gate.
    More negative = more permissive (allows entry during light network stress).
    """

    ffg_fiedler_floor: float = 0.0
    """Gate 4: Fiedler z-score floor for fallback when ORC is unavailable.
    0.0 = require Fiedler above its rolling mean.
    """

    # V133v2: exit-quality variant of Gate 2 (replaces disposition gate)
    ffg_exit_quality_gate: bool = False
    """V133v2: when True, Gate 2 uses clean_exit_ratio instead of disposition.
    Avoids the self-referential lock: bad exits → gate blocks → no new trades → no fix.
    """

    ffg_exit_quality_min_clean: int = 20
    """V133v2: Gate 2 cold-start threshold. Gate activates only after this many
    clean (non-stop_loss) exits have been observed. Until then, Gate 2 passes.
    """

    ffg_exit_quality_ratio: float = 0.50
    """V133v2: Gate 2 threshold. Require clean_exit_ratio > this value over the
    last ffg_disposition_window trades.
    """

    ffg_gate1_enabled: bool = True
    """V137: when False, Gate 1 (cross_market_divergence) is bypassed — always passes.
    Used to isolate which gates provide lift without the divergence filter.
    """

    ffg_gate4_enabled: bool = True
    """V137: when False, Gate 4 (pair_network / ORC / Fiedler) is bypassed — always passes.
    Used to isolate whether ORC/Fiedler is still noisy and over-filtering entries.
    """

    # ------------------------------------------------------------------
    # V138 signal improvement flags
    # ------------------------------------------------------------------

    improved_momentum_derivative: bool = False
    """V138: EMA-smooth momentum_derivative (α=0.4, 5-period) + regime-conditional semantics
    (trending=continuation, mean_reversion=overextension inversion, transitional=0.5×).
    Also adds momentum_acceleration (second-order derivative) as a separate signal.
    """

    signal_memory_warm_start: bool = False
    """V138: Pre-seed SignalMemory with first 20 replay cycles before trading starts.
    Fixes cold-start NaN on conviction_trend, agreement_trend, regime_duration signals.
    """

    geometry_warm_start: bool = False
    """V138: Pre-seed MarketManifold and ORC correlation matrices from 30 pre-bars
    before the trading window. Makes Gate 4 (ORC/Fiedler) active from cycle 1 in backtest.
    """

    signal_reasoning: bool = False
    """V138: Write natural-language reasoning to DecisionTrace.reasoning field.
    Explains top 3 signal drivers, regime context, gate status, and threshold gap.
    Rendered as tooltip in geometry dashboard.
    """

    geopolitical_signals: bool = False
    """V138: GDELT DOC 2.0 geopolitical event signals (geo_event_intensity, geo_sentiment,
    geo_regime_shift, sanctions_signal). 15-min TTL cache; backtest replay by date range.
    """

    # ------------------------------------------------------------------
    # V139 LLM analyst flags
    # ------------------------------------------------------------------

    llm_analyst_enabled: bool = False
    """V139: inject LLM conviction_modifier (0.0–1.5) that scales the IC-weighted
    composite before threshold comparison. LLM acts as analyst, not decision-maker;
    quant system retains full control. SHA256-keyed file cache for deterministic replay.
    Degrades gracefully to modifier=1.0 on any error (missing key, timeout, parse fail).
    """

    llm_analyst_call_every_n: int = 10
    """V139: call LLM API every N cycles (per ticker). Cached modifier is reused between
    calls. Lower = fresher analysis; higher = lower API cost.
    Default 10 = ~once per 10 trading cycles per symbol.
    """

    llm_analyst_provider: str = "claude"
    """V139 pluggable provider. Options:
      "claude"            — Anthropic API (ClaudeProvider)
      "openai_compatible" — any OpenAI-format endpoint (Kimi, GLM, MiniMax, etc.)
      "cli"               — wraps a local CLI tool (e.g. claude CLI)
      "kimi" / "glm" / "minimax" / "groq" / "together"
                          — shorthand aliases for known OpenAI-compatible APIs
    """

    llm_analyst_model: str = "claude-haiku-4-5-20251001"
    """V139: model name within the chosen provider.
    Claude shortcuts: "haiku", "sonnet", "opus" are resolved automatically.
    For openai_compatible providers, pass the exact model name the API expects.
    """

    llm_analyst_api_base: str = ""
    """V139: custom API base URL for openai_compatible providers (e.g. Kimi, GLM).
    Leave empty when using named shorthand providers (kimi/glm/minimax) — base
    is inferred automatically. Required only for custom/self-hosted endpoints.
    """

    llm_analyst_api_key_env: str = ""
    """V139: env var name that holds the API key for the chosen provider.
    Empty = use provider default (ANTHROPIC_API_KEY for claude, KIMI_API_KEY for kimi, etc.)
    Override when the key is stored under a non-standard env var name.
    """

    # ------------------------------------------------------------------
    # V141 crisis alpha fixes
    # ------------------------------------------------------------------

    regime_hysteresis_enabled: bool = False
    """V141: require N consecutive non-crisis cycles before allowing crisis→normal transition.
    Prevents Wasserstein false escapes where 1-2 "pause" candles reset the crisis label.
    """

    regime_hysteresis_cycles: int = 3
    """V141: number of consecutive non-crisis cycles required before exiting crisis mode.
    Only applied when regime_hysteresis_enabled=True.
    """

    bear_prob_long_block_threshold: float = 0.55
    """V141: block long entries when bear_prob >= this threshold, regardless of regime label.
    Default 0.55 preserves existing behavior. Set to 0.35 for V141 to catch bear-market longs
    that slip through when the regime label temporarily reads "normal".
    """

    llm_crisis_mode_enabled: bool = False
    """V141: asymmetric LLM veto thresholds when bear_prob > 0.30.
    Long veto raised to llm_crisis_long_veto; short veto lowered to llm_crisis_short_veto.
    Also increases call frequency to llm_crisis_call_every_n cycles.
    """

    llm_crisis_long_veto: float = 0.50
    """V141: LLM veto threshold for LONG entries in crisis/bear regime (bear_prob > 0.30).
    mod < this → veto. Default 0.50 (vs 0.30 in normal) — forensics showed 0.32-0.45 mods
    for losing longs that should have been blocked.
    """

    llm_crisis_short_veto: float = 0.20
    """V141: LLM veto threshold for SHORT entries in crisis/bear regime.
    mod < this → veto. Default 0.20 (vs 0.30 in normal) — be more permissive with shorts
    in crisis since they're the profit engine in bear markets.
    """

    llm_crisis_call_every_n: int = 5
    """V141: LLM call frequency in crisis/bear regime (bear_prob > 0.30).
    More frequent calls = fresher analysis during regime stress.
    """

    long_trail_multiplier: float = 1.0
    """V141: scale factor for mfe_trail_k on LONG positions.
    0.5 = trail activates at 0.5× ATR MFE (tighter — exits losing longs sooner).
    1.0 = no change from base mfe_trail_k.
    """

    short_trail_multiplier: float = 1.0
    """V141: scale factor for mfe_trail_k on SHORT positions.
    1.5 = trail activates at 1.5× ATR MFE (wider — lets crisis shorts run further).
    1.0 = no change from base mfe_trail_k.
    """

    zero_mfe_early_exit_cycles: int = 0
    """V141: close positions with MFE=0 after this many cycles (disabled when 0).
    Forensics: top 7 losers all had mfe=$0 after 3-4 cycles — position was wrong from tick 1.
    Setting to 2 closes these immediately rather than holding to full ATR stop.
    """

    fear_greed_crisis_weight: float = 1.0
    """V141: weight multiplier for fear_greed_signal in crisis/bear regime (bear_prob > 0.30).
    1.0 = no change. 0.1 = dampen — forensics: fear_greed avg=+1.0 in H1-2022 (crisis-poison
    bullish push). At 0.1×, its contribution to composite drops from ~1.0 to 0.1.
    """

    sma_crisis_weight: float = 1.0
    """V141: weight multiplier for sma_crossover in crisis/bear regime (bear_prob > 0.30).
    1.0 = no change. 0.2 = dampen — dead-cat bounces create false bullish crossovers.
    At 0.2×, SMA crossover bullish push is mostly removed in structural downtrends.
    """

    # V142: block ALL entries (both long and short) in high_vol regime.
    # Phase A data: 0% WR across all versions in high_vol (8 trades, -$5,311 V141; 6 trades, -$6,296 V139).
    # High_vol entries are structurally losers: vol spikes mean price bounces sharply against positions.
    high_vol_entry_block: bool = False
    """V142: when True, block both long and short entries in high_vol regime.
    Phase A diagnosis: 0% win-rate in high_vol across V137a/V139/V141 — regime cannot be traded profitably
    with current signal stack. Cleanest fix is to sit out entirely.
    """

    # V142: gate regime hysteresis activation to confirmed bear contexts.
    # V141 hysteresis fired even on marginal crisis readings (bear_prob ≈ 0.45) which
    # bled into Q4-2023 / trend snapshots where brief volatility briefly triggers "crisis".
    # With this gate, hysteresis only locks in when bear_prob > bear_prob_hysteresis_gate
    # at the time of crisis onset — preventing trend-snapshot lock-in.
    bear_prob_hysteresis_gate: float = 0.50
    """V142: minimum bear_prob required to engage regime hysteresis lock.
    When bear_prob < this at crisis onset, hysteresis does not engage.
    0.50 = only lock hysteresis in confirmed bear conditions.
    """

    # ------------------------------------------------------------------
    # V143 — Continuous confidence surfaces (Phase 1 of adaptive engine)
    # ------------------------------------------------------------------
    # Replaces all binary entry gates with multiplicative sigmoid surfaces.
    # See docs/architecture/adaptive-engine-v2.md for mathematical derivation.
    # When False (default): existing hard-gate logic is unchanged.
    # When True: every entry gate is replaced by a continuous confidence factor;
    #   final position size = base_size × Π(cᵢ) for all applicable factors.
    continuous_surfaces: bool = False
    """V143: when True, replace all hard entry gates with continuous sigmoid surfaces.
    Position size = base_size × c_bear × c_composite × c_regime × c_llm.
    All factors ∈ [0, 1] and multiply. No binary cliffs.
    Validated by parameter sensitivity test (target: bear_prob center sweep <$5k range).
    """

    surface_config: object = None
    """V143: optional SurfaceConfig instance for custom surface parameters.
    None → uses calibrated defaults from confidence_surface.py.
    Type is 'object' to avoid circular import; cast to SurfaceConfig at use.
    """

    # ------------------------------------------------------------------
    # V144: Meta-Learning Layer (Phase 2)
    # ------------------------------------------------------------------
    meta_learning_enabled: bool = False
    """V144: when True, MetaLearner tracks rolling PF per regime and adjusts
    surface T and μ each cycle. State persisted to data/meta_learner_state.json.
    Requires continuous_surfaces=True.
    """

    meta_learner_exit_only: bool = False
    """V148: when True with meta_learning_enabled, meta-learner adjusts exit
    trail tightness only (not entry surfaces). Derived from bear_long T:
    low T (high PF) → tighter trail; high T (uncertain) → looser trail.
    Allows V139 entry volume while still benefiting from adaptive exits.
    """

    continuous_sizing: bool = False
    """V148: when True, position size is scaled by regime directional confidence.
    size_long *= sigmoid(bull_prob); size_short *= sigmoid(bear_prob).
    Distinct from continuous_surfaces (which gates entry); this never blocks a trade,
    only modulates its size. Preserves V139 trade volume.
    """

    # ------------------------------------------------------------------
    # V145: LLM Meta-Controller (Phase 3)
    # ------------------------------------------------------------------
    llm_meta_controller: bool = False
    """V145: when True, LLMMetaController calls an LLM every 50 cycles to
    suggest surface parameter adjustments (temperature and center deltas).
    Blended with meta-learner config at 30% LLM weight. Zero overhead when False.
    Requires meta_learning_enabled=True and continuous_surfaces=True.
    """

    # ------------------------------------------------------------------
    # V146 Ensemble Voter
    # ------------------------------------------------------------------
    ensemble_voting: bool = False
    """V146: when True, replace the scalar weighted-sum composite with structured
    vote aggregation (EnsembleVoter).  Each signal casts a directional vote;
    conviction = agreement_ratio × max_confidence_of_majority.  The resulting
    composite is ±conviction, preserving sign convention for downstream filters.
    Backward compatible: False → identical behaviour to V144.
    """

    # ------------------------------------------------------------------
    # V147 Bayesian Regime Detector
    # ------------------------------------------------------------------
    bayesian_regime: bool = False
    """V147: when True, replace hard bear_prob/bull_prob threshold trees with a
    probabilistic posterior P(regime | signals, LLM) over four regimes:
    {crisis, high_vol, normal, trending}.  Long/short sizing scales by
    posterior long_affinity / short_affinity respectively.
    State persisted to data/bayesian_regime_state.json across cycles.
    Backward compatible: False → identical behaviour to V146.
    """

    # ------------------------------------------------------------------
    # V135 ATR-based stop-loss flags
    # ------------------------------------------------------------------

    atr_stop_enabled: bool = False
    """V135: when True, skip the legacy fixed -2% ROI stop-loss in paper_trading.py.
    The ExitController's mae_stop_k ATR stop becomes the sole downside guard.
    Allows loss_capture < 1.0: ATR stop fires at a dollar threshold independent
    of the MAE tick, unlike the -2% stop which fires exactly at the first new-low.
    """

    # ------------------------------------------------------------------
    # V130 regime entry gates
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # V136 crisis-regime entry bias flags
    # ------------------------------------------------------------------

    crisis_long_block: bool = False
    """V136: hard block on long entries when regime == crisis (not high_vol).
    V135 diagnosis: 70-80% longs in crisis (H1-2022 bear) drives PF < 1.
    Pairs with high_vol_short_block which covers the high_vol case.
    """

    crisis_short_permissive: bool = False
    """V136: relax short conviction threshold in crisis regime.
    When True, short threshold is scaled by crisis_short_thresh_scale before
    applying the standard conviction filter, admitting more shorts in bear markets.
    """

    crisis_short_thresh_scale: float = 0.5
    """V136: scale factor for short threshold in crisis (0 < x <= 1).
    0.5 = halve the threshold (twice as permissive). 0.4 = very permissive.
    Only applied when crisis_short_permissive=True and regime == crisis.
    """

    crisis_position_size_boost: float = 1.0
    """V136: size multiplier for short positions in crisis regime.
    Applied on top of other size factors when crisis_long_block=True.
    1.0 = no boost. 1.25 = 25% larger. 1.5 = 50% larger shorts.
    """

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
    # V156 — Regime-adaptive strategy selector (restored V212)
    # See omega/nodes/victoria/strategy_selector.py
    # ------------------------------------------------------------------

    strategy_selector_enabled: bool = False
    """V156/V212: enable per-cycle regime-adaptive strategy mode switching.
    Detects sustained bull/crisis regimes and applies mode-specific overrides:
      TREND — disables crisis protections that fight bull markets
      CRISIS — activates full crisis alpha stack
      DEFAULT — base config unchanged
    Hysteresis-gated transitions prevent oscillation.
    """

    strategy_selector_trend_window: int = 10
    strategy_selector_crisis_window: int = 5
    strategy_selector_trend_bull_threshold: float = 0.60
    strategy_selector_crisis_bear_threshold: float = 0.55
    strategy_selector_trend_exit_window: int = 5
    strategy_selector_crisis_exit_window: int = 5
    strategy_selector_trend_crisis_veto: bool = False
    mode_transition_blend: bool = False
    blend_cycles: int = 5
    preset_override_mode: bool = False

    # ------------------------------------------------------------------
    # V222 — IC subsystem wiring
    # ------------------------------------------------------------------

    ic_seed_weighting: bool = True
    """V222: load seeded pooled + per-regime ICs from data/signal_ic_history.json
    (keys seeded_pooled_ics / seeded_regime_ics) at training startup and feed
    them to StrategyNode.update_signal_ics / update_regime_ics. With this OFF
    (the IC-off control), _signal_ics stays empty and _compute_weighted_conviction
    degrades to the raw composite — bit-identical to pre-V222 behavior.
    """

    per_regime_ic_weighting: bool = True
    """V170 flag, first DECLARED in V222 (was undeclared → getattr→False silent
    no-op, documented by the startup wiring banner since V218). When ON,
    _compute_weighted_conviction looks up the current regime's IC for each
    signal in _regime_ics before falling back to the pooled _signal_ics value.
    """

    regime_conditional_ic_weighting: bool = False
    """V223: gate the IC-weighted conviction path on the cycle's RUNTIME regime
    label. When ON, _compute_weighted_conviction bypasses to the equal-weight
    raw composite (bit-identical to the V222 IC-off control path) in the regimes
    where V222 forensics showed IC weighting HURTS — crisis (−$4,771) and
    high_vol — and keeps IC weights everywhere else (normal/sideways/bull/bear/
    default/unknown), banking V222's +$3,331 trend gain. Denylist on
    {crisis, high_vol}, NOT an allowlist: the runtime label space is
    {bull,bear,sideways,high_vol,crisis,default} and "trend"/"normal" are
    snapshot names, not runtime labels. Default OFF = bit-identical to V222.
    """

    # ------------------------------------------------------------------
    # V225 — additive crisis-skew signal (new orthogonal signal class)
    # ------------------------------------------------------------------

    crisis_skew_enabled: bool = True
    """V225: inject an additive, one-sided risk-off term derived from realized
    downside-semivariance skew + drawdown acceleration over the close window
    (omega/nodes/victoria/signals/crisis_skew.py). When ON, the term (∈ [-1,0],
    weighted by _SKEW_W=0.5) is ADDED to the per-ticker composite AFTER it is set
    — NOT routed through the equal-weight basket selector (so the one-sided term
    is never trimmed away by _balanced_composite's 20% trim, which would mute it
    exactly in crisis). NOT an IC re-weight (IC retired in V224). Targets the
    chronically-negative crisis gate; ≈0 in benign tape so trend/recent are
    untouched by construction. **V227 SHIP: default flipped ON** — with the
    drawdown-gated config below it improves crisis +$630 (−$3,621→−$2,991) at
    trend +$0.02 / recent −$64 (fork #1). Set False to recover the pre-V225
    equal-weight incumbent.
    """

    crisis_skew_regime_gate_enabled: bool = True
    """V226: regime-gate the V225 crisis_skew term. V225's always-on tilt fired
    ~200/200 cycles in EVERY gate (refuted "≈0 outside crisis") and regressed all
    three gates — a directional bias, not a crisis signal. When this flag is ON, the
    term applies ONLY when the prior-cycle consolidated regime label ∈ {crisis,
    high_vol} (signal_generation._regime_gated_skew zeroes it otherwise) AND the
    weight drops to _SKEW_W_GATED=0.2 (vs _SKEW_W=0.5). Requires crisis_skew_enabled.
    Needs the prior-cycle `_regime` threaded by victoria_node. **V227 SHIP: default
    flipped ON** — but V226's categorical-label gate alone over-fired (fork #3);
    the win required the V227 drawdown threshold below. Set False to recover the
    V225 always-on W=0.5 path.
    """

    crisis_skew_drawdown_threshold: float = 0.12
    """V227 (Track B): tighten the regime gate with a realized-drawdown-magnitude
    condition. V226 showed the categorical VRP→regime label is a coin-flip — it
    classified ~half of trend/recent windows as {crisis,high_vol} (skew_on_cycles
    91/113 ≫ the 40 no-harm threshold), leaking the harmful tilt into benign tape.
    When this is > 0.0 (and the regime gate is ON), the term fires ONLY when the
    regime label is risk-off AND the per-ticker realized drawdown over the last
    _DD_LOOKBACK daily bars exceeds this fraction (e.g. 0.10 = a ≥10% pullback from
    the recent peak). 0.0 ⇒ V226 regime-only behaviour (byte-reachable). Requires
    crisis_skew_enabled + crisis_skew_regime_gate_enabled.
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
_PRESETS["v93_baseline"] = VictoriaFeatures(
    decision_traces=True,
    activation_tracing=True,
)

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
    decision_traces=True,
    postmortem_signal_filter=True,
)

_PRESETS["v115_full_vectors"] = VictoriaFeatures(
    # V114 foundation
    decision_embeddings=True,
    ws_microstructure=True,
    temporal_memory=True,
    trade_reinforcement=True,
    activation_tracing=True,
    decision_traces=True,
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
    mfe_trail_k=0.5,  # activate at 0.5×ATR (earlier than V128's 1.0×)
    mfe_retracement_cap=0.15,  # lock 85% of peak gain
    mae_stop_k=99.0,  # hard stop disabled
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
    mfe_trail_k=0.5,  # activate at 0.5×ATR
    mfe_retracement_cap=0.25,  # lock 75% of peak (same as V128 cap, earlier activation)
    mae_stop_k=99.0,  # hard stop disabled
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
    mfe_trail_k=1.5,  # activate at 1.5×ATR (later, bigger move required)
    mfe_retracement_cap=0.15,  # tight lock once activated
    mae_stop_k=99.0,  # hard stop disabled
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
    decision_traces=True,
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
    crisis_high_vol_long_block=True,  # belt: block longs in crisis+high_vol (V101 flag)
    high_vol_short_block=True,  # new: block shorts in high_vol (V130 flag)
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
    decision_traces=True,
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

# ---------------------------------------------------------------------------
# V132: legacy trailing-stop age guard + early-loss time-stop
# Root cause diagnosed in V131: the legacy 50%-MFE trailing stop fires at
# age 1-2 (a new-low tick), making loss_capture=1.0 structurally.
# Fix: suppress the trailing stop until `trailing_stop_min_age` cycles have
# elapsed, giving losers a chance to recover before the stop fires.
# ---------------------------------------------------------------------------
_V132_BASE = {
    # Full signal stack (carried forward from _V131_BASE)
    "decision_embeddings": True,
    "ws_microstructure": True,
    "temporal_memory": True,
    "trade_reinforcement": True,
    "postmortem_signal_filter": True,
    "whale_prints": True,
    "whale_flow": True,
    "funding_velocity": True,
    # Observability — on by default for V132+
    "activation_tracing": True,
    "decision_traces": True,
    # V129m exits (moderate MFE trail)
    "disposition_exit_controller": True,
    "mfe_trail_k": 1.0,
    "mfe_retracement_cap": 0.25,
    "mae_stop_k": 99.0,  # hard stop disabled — rely on early_loss + time_exit
    # V130 regime gates
    "high_vol_short_block": True,
    "crisis_high_vol_long_block": False,  # dropped: regresses trend snapshot
    # V131 early-loss layer (best config from grid: N=3, K=0.3)
    "early_loss_time_stop": True,
    "early_loss_cycles": 3,
    "early_loss_k_atr": 0.3,
}

# v132a: age_guard=3, early_loss N=3 K=0.3
# Primary fix: trailing stop suppressed until age 3.  Most losers that were
# exiting at age 1-2 on a new-low tick now have 3 cycles to recover first.
_PRESETS["v132_fix_a"] = VictoriaFeatures(
    **_V132_BASE,
    trailing_stop_min_age=3,
)

# v132b: age_guard=3, early_loss N=3 K=0.5
# Looser early-loss threshold (0.5×ATR) — fewer cuts, deeper when they fire.
# Tests whether a wider early-loss window is needed alongside the age guard.
_PRESETS["v132_fix_b"] = VictoriaFeatures(
    **{**_V132_BASE, "early_loss_k_atr": 0.5},
    trailing_stop_min_age=3,
)

# v132c: age_guard=4, early_loss N=3 K=0.3
# Extra cycle of recovery room before the legacy trailing stop can fire.
# Hypothesis: some losers recover between cycle 3 and 4; delaying the guard
# further improves disposition without sacrificing too much PnL.
_PRESETS["v132_fix_c"] = VictoriaFeatures(
    **_V132_BASE,
    trailing_stop_min_age=4,
)

# ---------------------------------------------------------------------------
# V133: stop_loss age guard + four-factor AND-gate entry filter
#
# V132 post-mortem:
#   - trailing_stop age guard (V132) blocked MFE-trail and legacy trailing stop
#     at age < 3, but the -2% ROI stop-loss fires at age 1-2 on first new-low
#     tick → loss_capture=1.0 structurally unchanged. 30/55 losers exited via
#     stop_loss before early_loss_time_stop could act.
#   - disposition_coefficient: -0.46 to -0.52 across all 9 V132 runs (no
#     improvement over V130). Phase B gate: FAIL.
#
# V133 fixes:
#   1. stop_loss_min_age=3: suppress the -2% stop-loss until age >= 3.
#      Now ALL three legacy exit paths are age-guarded. early_loss_time_stop
#      (age >= 3, K=0.3 ATR) becomes the primary loser exit, firing before
#      positions drift to absolute MAE.
#   2. four_factor_and_gate=True: independent entry quality filter.
#      Requires model-vs-market divergence, healthy exit discipline, low
#      utilization, and non-fragmented correlation network.
#
# Base: V132c (best V132 preset: -$377 crisis, +$6,891 recent, -$2,132 trend).
# ---------------------------------------------------------------------------

_V133_BASE = {
    # Full signal stack (V115 foundation)
    "decision_embeddings": True,
    "ws_microstructure": True,
    "temporal_memory": True,
    "trade_reinforcement": True,
    "postmortem_signal_filter": True,
    "whale_prints": True,
    "whale_flow": True,
    "funding_velocity": True,
    # Full observability
    "activation_tracing": True,
    "decision_traces": True,
    # Exit discipline — V129m trail parameters
    "disposition_exit_controller": True,
    "mfe_trail_k": 1.0,
    "mfe_retracement_cap": 0.25,
    "mae_stop_k": 99.0,
    # V130 regime gates
    "high_vol_short_block": True,
    "crisis_high_vol_long_block": False,
    # V131 early-loss (fires at age >= 3, loss >= 0.3×ATR)
    "early_loss_time_stop": True,
    "early_loss_cycles": 3,
    "early_loss_k_atr": 0.3,
    # V132 trailing-stop age guard (MFE trail + legacy trail)
    "trailing_stop_min_age": 3,
    # V133 stop-loss age guard (NEW: guard the -2% stop-loss too)
    "stop_loss_min_age": 3,
    # V133 AND-gate entry filter
    "four_factor_and_gate": True,
}

# v133a: full fix — stop_loss age guard + four-factor gate (default params)
# All three exit-path age guards active. Four-factor gate at design defaults.
_PRESETS["v133_and_gate"] = VictoriaFeatures(**_V133_BASE)

# v133b: stop_loss age guard only (no four-factor gate)
# Isolates the stop_loss_min_age fix from the AND-gate to measure each
# contribution independently. If disposition improves here but not in v133a,
# the AND-gate is degrading entry quality (over-filtering).
_PRESETS["v133_stop_loss_guard"] = VictoriaFeatures(
    **{**_V133_BASE, "four_factor_and_gate": False},
)

# v133c: four-factor gate only (no stop_loss age guard, rolling from V132c)
# Tests AND-gate precision improvement without the exit fix.
# Expected: fewer trades (gate filtering), similar disposition (exits unchanged).
_PRESETS["v133_gate_only"] = VictoriaFeatures(
    **{**_V133_BASE, "stop_loss_min_age": 0},
)

# ---------------------------------------------------------------------------
# V134: AND-gate calibration — disable Gate 2 (disposition) in backtest
# ---------------------------------------------------------------------------
# V133a achieved best PF ever (1.97) but too few trades (n=10-13 vs n≥20).
# Root cause: Gate 2 (disposition) fires after ffg_disposition_min_trades=10
# closed trades, then PERMANENTLY blocks new entries because disposition is
# structurally negative (-0.37 to -0.53). This is a feedback-loop dead-lock:
# bad exits → no new entries → no chance to improve exits.
#
# Fix: raise ffg_disposition_min_trades to 100 (effectively cold-start for
# a 150-cycle backtest, since we never reach 100 closed trades). In live
# production with 1000s of trades, Gate 2 would activate normally.
# Also relax ffg_divergence_threshold 0.05→0.03 to allow borderline entries.
# Target: n≥20 per snapshot while maintaining PF > 1.5.
_V134_BASE = {
    **_V133_BASE,
    "ffg_divergence_threshold": 0.03,  # relaxed from 0.05
    "ffg_disposition_min_trades": 100,  # disable Gate 2 in 150-cycle backtest
}
_PRESETS["v134_gate_calibrated"] = VictoriaFeatures(**_V134_BASE)

# ---------------------------------------------------------------------------
# V135: ATR-based stop-loss — structural disposition fix
# ---------------------------------------------------------------------------
# Replaces fixed -2% ROI stop with ExitController's ATR-based mae_stop.
# The -2% stop fires at exactly the first new-low tick = MAE → loss_capture=1.0.
# The ATR stop fires at a dollar threshold anchored to price volatility; if price
# bounces before reaching ATR threshold, loss_capture < 1.0.
#
# Grid: V135a (K=1.0 tight), V135b (K=1.2 moderate), V135c (K=1.5 wide).
# All three disable the legacy stop (atr_stop_enabled=True) and set the appropriate
# mae_stop_k. Keeping all other V133a settings (sl_guard + AND-gate disabled for
# clean isolation of the ATR stop effect).
_V135_BASE = {
    # Same signal stack as V133 base but without the AND-gate (isolate ATR stop)
    "decision_embeddings": True,
    "ws_microstructure": True,
    "temporal_memory": True,
    "trade_reinforcement": True,
    "postmortem_signal_filter": True,
    "whale_prints": True,
    "whale_flow": True,
    "funding_velocity": True,
    "activation_tracing": True,
    "decision_traces": True,
    "disposition_exit_controller": True,
    "mfe_trail_k": 1.0,
    "mfe_retracement_cap": 0.25,
    "high_vol_short_block": True,
    "crisis_high_vol_long_block": False,
    "early_loss_time_stop": True,
    "early_loss_cycles": 3,
    "early_loss_k_atr": 0.3,
    "trailing_stop_min_age": 3,
    "stop_loss_min_age": 0,  # age guard not needed — ATR stop replaces it
    "four_factor_and_gate": False,  # isolate ATR stop effect
    "atr_stop_enabled": True,  # V135: skip fixed -2% stop, use ATR stop only
}
_PRESETS["v135a_atr_k10"] = VictoriaFeatures(**{**_V135_BASE, "mae_stop_k": 1.0})
_PRESETS["v135b_atr_k12"] = VictoriaFeatures(**{**_V135_BASE, "mae_stop_k": 1.2})
_PRESETS["v135c_atr_k15"] = VictoriaFeatures(**{**_V135_BASE, "mae_stop_k": 1.5})

# ---------------------------------------------------------------------------
# V133v2: AND-gate with exit-quality Gate 2 (avoid self-referential lock)
# ---------------------------------------------------------------------------
# V133a's Gate 2 (disposition > 0) permanently blocks after 10 trades once
# disposition goes negative. V133v2 replaces Gate 2 with a clean_exit_ratio
# metric: once 20+ clean exits (non-stop_loss) have been seen, require that
# >50% of recent exits are clean (not stopped out by fixed -2% stop_loss).
# ATR stops count as clean exits (discipline, not drawdown).
#
# V133v2_a: AND-gate + new Gate 2. Still uses legacy -2% stop (stop_loss exits
#            will count against clean_exit_ratio, so Gate 2 should still block
#            partially — this tests whether Gate 2 fires less aggressively).
# V133v2_b: AND-gate + new Gate 2 + ATR stop. ATR stops = clean exits, so
#            clean_exit_ratio should stay high → Gate 2 rarely blocks.
_V133V2_BASE = {
    **_V133_BASE,
    "four_factor_and_gate": True,
    "ffg_exit_quality_gate": True,  # V133v2: new Gate 2
    "ffg_exit_quality_min_clean": 20,  # cold-start until 20 clean exits
    "ffg_exit_quality_ratio": 0.50,  # require >50% clean exits in window
    "ffg_disposition_min_trades": 10,  # unused when exit_quality_gate=True
}
_PRESETS["v133v2_a"] = VictoriaFeatures(**_V133V2_BASE)
_PRESETS["v133v2_b"] = VictoriaFeatures(
    **{
        **_V133V2_BASE,
        "atr_stop_enabled": True,  # ATR stops = clean exits → Gate 2 stays open
        "mae_stop_k": 1.2,  # moderate ATR stop (same as V135b)
        "stop_loss_min_age": 3,  # belt-and-suspenders age guard
    }
)

# ---------------------------------------------------------------------------
# V136: crisis-regime entry bias fix
# ---------------------------------------------------------------------------
# Root finding from V135 Phase A: crisis snapshot bleeds $-5k to -7k because
# the system enters 70-80% LONG in a 2022 bear market (H1-2022 was a sustained
# crypto crash). No exit fix addresses this — the problem is entry-side.
#
# Grid based on V135b (K=1.2 ATR stop) + V130's high_vol_short_block:
#   v136a: crisis_long_block + crisis_short_permissive(0.5) + ATR stop K=1.2
#   v136b: same but crisis_short_permissive × 0.4 (more aggressive short threshold)
#   v136c: v136a + crisis_position_size_boost=1.5 (bigger shorts in crisis)
_V136_BASE = {
    "decision_embeddings": True,
    "ws_microstructure": True,
    "temporal_memory": True,
    "trade_reinforcement": True,
    "postmortem_signal_filter": True,
    "whale_prints": True,
    "whale_flow": True,
    "funding_velocity": True,
    "activation_tracing": True,
    "decision_traces": True,
    "disposition_exit_controller": True,
    "mfe_trail_k": 1.0,
    "mfe_retracement_cap": 0.25,
    "mae_stop_k": 1.2,  # V135b ATR stop
    "high_vol_short_block": True,  # V130 high_vol gate (carry forward)
    "crisis_high_vol_long_block": False,  # covered by crisis_long_block below
    "early_loss_time_stop": True,
    "early_loss_cycles": 3,
    "early_loss_k_atr": 0.3,
    "trailing_stop_min_age": 3,
    "stop_loss_min_age": 0,
    "four_factor_and_gate": False,
    "atr_stop_enabled": True,  # skip fixed -2% stop
    # V136 crisis bias
    "crisis_long_block": True,  # hard block longs in crisis regime
    "crisis_short_permissive": True,  # relax short threshold in crisis
    "crisis_short_thresh_scale": 0.5,  # half threshold → twice as permissive
    "crisis_position_size_boost": 1.25,  # 25% larger crisis shorts
}
_PRESETS["v136a_crisis_bias"] = VictoriaFeatures(**_V136_BASE)
_PRESETS["v136b_aggressive_short"] = VictoriaFeatures(
    **{
        **_V136_BASE,
        "crisis_short_thresh_scale": 0.4,  # more aggressive: 0.4× threshold
    }
)
_PRESETS["v136c_size_boost"] = VictoriaFeatures(
    **{
        **_V136_BASE,
        "crisis_position_size_boost": 1.5,  # 50% larger crisis shorts
    }
)

# ---------------------------------------------------------------------------
# V137 — V136a champion base + reworked AND-gate (V133v2 exit-quality Gate 2)
# ---------------------------------------------------------------------------
# Base: V136a (crisis_long_block + ATR K=1.2 + high_vol_short_block)
# Layer: four_factor_and_gate with exit-quality Gate 2 (clean_exit_ratio > 0.5
#        after 20 clean exits; cold-start passes). Gates 1 and 4 toggleable.
#
#   v137a: full AND-gate (all 4 gates active)
#   v137b: AND-gate minus Gate 1 (divergence off — test if over-filtering)
#   v137c: AND-gate minus Gate 4 (pair network off — ORC/Fiedler noise test)
# ---------------------------------------------------------------------------
_V137_BASE = {
    **_V136_BASE,  # crisis_long_block + ATR K=1.2 etc.
    "four_factor_and_gate": True,
    "ffg_exit_quality_gate": True,  # V133v2 exit-quality Gate 2
    "ffg_exit_quality_min_clean": 20,  # cold-start until 20 clean exits
    "ffg_exit_quality_ratio": 0.50,  # require >50% clean exits in window
    "ffg_divergence_threshold": 0.05,  # Gate 1 threshold (default)
    "ffg_gate1_enabled": True,
    "ffg_gate4_enabled": True,
}
_PRESETS["v137a_full_gate"] = VictoriaFeatures(**_V137_BASE)
_PRESETS["v137b_no_gate1"] = VictoriaFeatures(
    **{**_V137_BASE, "ffg_gate1_enabled": False}  # divergence gate off
)
_PRESETS["v137c_no_gate4"] = VictoriaFeatures(
    **{**_V137_BASE, "ffg_gate4_enabled": False}  # pair-network gate off
)

# ---------------------------------------------------------------------------
# V138 — V137a champion + signal improvements + geopolitical data
# ---------------------------------------------------------------------------
# Run ONLY after all flags are unit-tested and greenlit by user.
_V138_BASE = {
    **_V137_BASE,
    "improved_momentum_derivative": True,
    "signal_memory_warm_start": True,
    "geometry_warm_start": True,
    "signal_reasoning": True,
    "geopolitical_signals": True,
}
_PRESETS["v138_full"] = VictoriaFeatures(**_V138_BASE)

# ---------------------------------------------------------------------------
# V138.1 — warm-start bugs fixed: disable in backtest (regime mismatch)
# ---------------------------------------------------------------------------
# signal_memory_warm_start and geometry_warm_start are now live-mode only.
# In backtest, pre-bar seeding injects wrong-era regime bias (e.g. late-2021
# bullish history at the start of a H1-2022 crisis replay).
# improved_momentum_derivative + signal_reasoning remain enabled.
_V1381_BASE = {
    **_V137_BASE,
    "improved_momentum_derivative": True,
    "signal_memory_warm_start": False,  # disabled: backtest regime mismatch
    "geometry_warm_start": False,  # disabled: backtest regime mismatch
    "signal_reasoning": True,
    "geopolitical_signals": False,  # live-only (no per-bar historical timestamps yet)
}
_PRESETS["v138_1"] = VictoriaFeatures(**_V1381_BASE)

# ---------------------------------------------------------------------------
# V139 — V138.1 base + pluggable LLM analyst conviction modifier
# ---------------------------------------------------------------------------
# LLM acts as senior analyst returning conviction_modifier ∈ [0.0, 1.5].
# modifier < 0.5 → veto (entry skipped regardless of quant score).
# Backtest: fully deterministic via SHA256-keyed file cache per (provider, model, input).
# Provider-agnostic: swap via llm_analyst_provider flag without code changes.
_V139_BASE = {
    **_V1381_BASE,
    "llm_analyst_enabled": True,
    "llm_analyst_call_every_n": 10,
}

# Claude variants
_PRESETS["v139_claude_haiku"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "claude",
        "llm_analyst_model": "claude-haiku-4-5-20251001",
    }
)
_PRESETS["v139_claude_sonnet"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "claude",
        "llm_analyst_model": "claude-sonnet-4-6",
    }
)

# Kimi v2 (Moonshot AI)
_PRESETS["v139_kimi_v2"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "kimi",
        "llm_analyst_model": "kimi-v2",
        "llm_analyst_api_key_env": "KIMI_API_KEY",
    }
)

# GLM 5.1 (Zhipu AI)
_PRESETS["v139_glm"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "glm",
        "llm_analyst_model": "glm-5.1",
        "llm_analyst_api_key_env": "GLM_API_KEY",
    }
)

# MiniMax 2.7
_PRESETS["v139_minimax"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "minimax",
        "llm_analyst_model": "minimax-text-01",
        "llm_analyst_api_key_env": "MINIMAX_API_KEY",
    }
)

# CLI fallback (uses claude CLI binary)
_PRESETS["v139_cli"] = VictoriaFeatures(
    **{
        **_V139_BASE,
        "llm_analyst_provider": "cli",
        "llm_analyst_model": "claude-haiku-4-5-20251001",
    }
)

# Default alias for Phase A — uses CLI provider (authenticated via Claude Desktop;
# no ANTHROPIC_API_KEY env var needed in subprocess).
_PRESETS["v139_llm_analyst"] = _PRESETS["v139_cli"]

# ---------------------------------------------------------------------------
# V140 — Multi-LLM A/B comparison (recent snapshot only, 500 cycles)
# ---------------------------------------------------------------------------
# Same V139_BASE config; only provider/model/api_base/api_key_env differ.
# Endpoints verified: Kimi=moonshot.cn, GLM=bigmodel.cn, MiniMax=minimax.chat
_V140_BASE = {
    **_V1381_BASE,
    "llm_analyst_enabled": True,
    "llm_analyst_call_every_n": 10,
}

_PRESETS["v140_kimi"] = VictoriaFeatures(
    **{
        **_V140_BASE,
        "llm_analyst_provider": "kimi",
        "llm_analyst_model": "kimi-k2",  # Kimi v2 model ID
        "llm_analyst_api_key_env": "KIMI_API_KEY",
    }
)

_PRESETS["v140_glm"] = VictoriaFeatures(
    **{
        **_V140_BASE,
        "llm_analyst_provider": "glm",
        "llm_analyst_model": "glm-4-plus",  # GLM 5.1 uses glm-4-plus API name
        "llm_analyst_api_key_env": "GLM_API_KEY",
    }
)

_PRESETS["v140_minimax"] = VictoriaFeatures(
    **{
        **_V140_BASE,
        "llm_analyst_provider": "minimax",
        "llm_analyst_model": "MiniMax-Text-01",  # MiniMax 2.7 API model name
        "llm_analyst_api_key_env": "MINIMAX_API_KEY",
    }
)

# Claude Haiku baseline for direct comparison (no CLI, uses API directly)
_PRESETS["v140_claude_haiku"] = VictoriaFeatures(
    **{
        **_V140_BASE,
        "llm_analyst_provider": "cli",
        "llm_analyst_model": "claude-haiku-4-5-20251001",
    }
)

# ---------------------------------------------------------------------------
# V141 — Crisis alpha: all 6 forensics fixes applied on top of V139 base
# ---------------------------------------------------------------------------
# Root causes from crisis-forensics-v139.md:
#   1. Regime mislabeling: 56 longs in "normal" during bear (-$21,905) → hysteresis
#   2. Bear-prob direct gate: block longs when bear_prob > 0.35 regardless of label
#   3. LLM veto too permissive for bear-market longs (0.30→0.50 in crisis mode)
#   4. Crisis exit asymmetry: tighter long trail, wider short trail, zero-MFE exit
#   5. fear_greed_signal crisis-poison: coded bullish in bear market → dampen 0.1×
#   6. sma_crossover crisis-poison: dead-cat bounce signals → dampen 0.2×
_V141_BASE = {
    **_V1381_BASE,
    # V139 LLM analyst (Haiku via CLI)
    "llm_analyst_enabled": True,
    "llm_analyst_call_every_n": 10,
    "llm_analyst_provider": "cli",
    "llm_analyst_model": "claude-haiku-4-5-20251001",
    # Fix 1: regime hysteresis (3-cycle exit guard)
    "regime_hysteresis_enabled": True,
    "regime_hysteresis_cycles": 3,
    # Fix 2: bear_prob direct long gate
    "bear_prob_long_block_threshold": 0.35,
    # Fix 3: LLM crisis mode (asymmetric veto thresholds)
    "llm_crisis_mode_enabled": True,
    "llm_crisis_long_veto": 0.50,
    "llm_crisis_short_veto": 0.20,
    "llm_crisis_call_every_n": 5,
    # Fix 4: exit asymmetry (tight long trail, wide short trail)
    "long_trail_multiplier": 0.5,  # trail activates at 0.5× ATR MFE for longs
    "short_trail_multiplier": 1.5,  # trail activates at 1.5× ATR MFE for shorts
    "zero_mfe_early_exit_cycles": 2,  # close zero-MFE positions after 2 cycles
    # Fix 5 + 6: dampen crisis-poison signals
    "fear_greed_crisis_weight": 0.1,
    "sma_crisis_weight": 0.2,
    # Carry forward V136a crisis flags
    "crisis_long_block": True,
    "crisis_short_permissive": True,
    "crisis_short_thresh_scale": 0.5,
    "crisis_position_size_boost": 1.25,
}
_PRESETS["v141_crisis_alpha"] = VictoriaFeatures(**_V141_BASE)

# V141 ablation: no LLM (to isolate structural fixes from LLM contribution)
_PRESETS["v141_crisis_no_llm"] = VictoriaFeatures(
    **{
        **_V141_BASE,
        "llm_analyst_enabled": False,
        "llm_crisis_mode_enabled": False,
    }
)

# ---------------------------------------------------------------------------
# V142 — Quick fix: tighten bear_prob gate, gated hysteresis, high_vol block
# ---------------------------------------------------------------------------
# V141 post-mortem: bear_prob_long_block=0.35 fired in trend/recent snapshots
# (Q4-2023 volatile early period; mixed-2026 regime swings), blocking profitable
# longs and regressing trend by $30k, recent by $21k. Three targeted fixes:
#   1. Revert bear_prob_long_block_threshold to 0.55 (conservative default)
#   2. Gate regime hysteresis to only engage when bear_prob > 0.50 at onset
#   3. Block all entries in high_vol regime (0% WR, structural loser across all versions)
#   4. Keep LLM crisis mode (proved +$3,161 delta vs no-LLM in V141)
_V142_BASE = {
    **_V141_BASE,
    # Fix 1: conservative bear_prob gate (revert from 0.35)
    "bear_prob_long_block_threshold": 0.55,
    # Fix 2: hysteresis gate (only lock in confirmed bear, bear_prob > 0.50)
    "regime_hysteresis_enabled": True,
    "bear_prob_hysteresis_gate": 0.50,
    # Fix 3: block all high_vol entries (0% WR across all versions)
    "high_vol_entry_block": True,
    # Keep V141 exit asymmetry + signal dampening + LLM crisis mode
}
_PRESETS["v142"] = VictoriaFeatures(**_V142_BASE)
_PRESETS["v142_no_llm"] = VictoriaFeatures(
    **{**_V142_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False}
)

# ---------------------------------------------------------------------------
# V143 — Continuous confidence surfaces (Phase 1: sigmoid entry model)
# ---------------------------------------------------------------------------
# Replaces all 47 binary gate exits in the long/short entry paths with
# multiplicative sigmoid confidence factors. Position size ∝ product of factors.
# Validated by parameter sensitivity test: bear_prob center 0.30→0.60 sweep
# should show PnL range < $5,000 (vs $30,000 with hard gates).
_V143_BASE = {
    **_V142_BASE,
    # Phase 1: enable continuous surfaces
    "continuous_surfaces": True,
    # V143 uses V142's conservative bear_prob gate AS the sigmoid center default.
    # The sigmoid surface calibration is in confidence_surface.py SurfaceConfig defaults.
}
_PRESETS["v143"] = VictoriaFeatures(**_V143_BASE)

# V143 sensitivity sweep presets — for parameter sensitivity test.
# Vary sigmoid center from 0.30 to 0.60 to validate <$5k PnL swing.
# Usage: python3 scripts/run_sensitivity_test.py --preset v143_center_{N}
for _center_10x in [30, 35, 40, 45, 50, 55, 60]:
    _center_val = _center_10x / 100.0
    from omega.nodes.victoria.confidence_surface import SurfaceConfig, SurfaceParams

    _sc = SurfaceConfig(bear_long=SurfaceParams(center=_center_val, temperature=0.10))
    _PRESETS[f"v143_center_{_center_10x}"] = VictoriaFeatures(
        **{**_V143_BASE, "surface_config": _sc}
    )

# ---------------------------------------------------------------------------
# V144 — Meta-Learning Layer (Phase 2: adaptive surface T and μ)
# ---------------------------------------------------------------------------
# Adds rolling 20-trade PF tracking per regime. Adjusts surface temperatures
# and centers automatically without LLM calls.
# Learning rules:
#   PF > 1.5 → T -= 0.01  (sharpen: well-calibrated)
#   PF < 0.8 → T += 0.02  (soften: miscalibrated)
#   T ∈ [0.05, 0.30]; μ EMA toward mean entry_value of winners
# State persisted to data/meta_learner_state.json across cycles.
_V144_BASE = {
    **_V143_BASE,
    "meta_learning_enabled": True,
}
_PRESETS["v144"] = VictoriaFeatures(**_V144_BASE)
_PRESETS["v144_no_llm"] = VictoriaFeatures(
    **{
        **_V144_BASE,
        "llm_analyst_enabled": False,
        "llm_crisis_mode_enabled": False,
    }
)

# ---------------------------------------------------------------------------
# V145 — LLM Meta-Controller (Phase 3: LLM adjusts surface parameters)
# ---------------------------------------------------------------------------
# Every 50 cycles, an LLM receives regime PF, signal IC drift, and surface
# parameters, and suggests temperature / center adjustments. The suggestions
# are blended at 30% weight with the meta-learner's config.
_V145_BASE = {
    **_V144_BASE,
    "llm_meta_controller": True,
    # MiniMax (Anthropic-compat) via hermes auth.json — confirmed working 2026-04-19
    "llm_analyst_provider": "openai_compatible",
    "llm_analyst_model": "claude-3-5-haiku-20241022",
    "llm_analyst_api_base": "https://api.minimax.io/anthropic",
    "llm_analyst_api_key_env": "MINIMAX_API_KEY",
}
_PRESETS["v145"] = VictoriaFeatures(**_V145_BASE)
_PRESETS["v145_minimax"] = VictoriaFeatures(**_V145_BASE)
_PRESETS["v145_zai"] = VictoriaFeatures(**_V145_BASE)  # legacy alias

# ---------------------------------------------------------------------------
# V146 — Ensemble Voter (Phase 4: structured vote aggregation)
# ---------------------------------------------------------------------------
# Replaces the scalar weighted-sum composite (Σ signal × weight) with a
# majority-vote aggregation that preserves uncertainty information:
#   conviction = agreement_ratio × max_confidence_of_majority
# Backward compatible with V144 confidence surfaces + meta-learner.
_V146_BASE = {**_V144_BASE, "ensemble_voting": True}
_PRESETS["v146"] = VictoriaFeatures(**_V146_BASE)

# ---------------------------------------------------------------------------
# V147 — Bayesian Regime Detector (Phase 5)
# ---------------------------------------------------------------------------
# Replaces hard bear_prob/bull_prob threshold trees with a probabilistic
# posterior P(regime | signals, LLM) over four regimes: crisis, high_vol,
# normal, trending.  Long/short sizing multipliers are derived from
# posterior.long_affinity() and posterior.short_affinity() respectively.
# Likelihood distributions are learned online via Welford updates each time
# a trade closes with a known regime label.
# State: data/bayesian_regime_state.json (persisted across cycles).
_V147_BASE = {**_V146_BASE, "bayesian_regime": True}
_PRESETS["v147"] = VictoriaFeatures(**_V147_BASE)

# ---------------------------------------------------------------------------
# V148 — Best-of-phases: V139 volume × V141 crisis × V144 adaptive exits ×
#         V143 continuous sizing.
# ---------------------------------------------------------------------------
# Design principle: V139 proved volume matters more than per-trade perfection.
# V148 preserves V139's 100+ trades/snapshot by using hard conviction gates for
# entry (not continuous surfaces) while adding two non-volume-killing upgrades:
#   1. meta_learner_exit_only: meta-learner tunes trailing stop tightness based
#      on rolling PF — high PF → tighten trail, low PF → loosen. Zero effect on
#      entry gating.
#   2. continuous_sizing: position size ∝ sigmoid(bull_prob) for longs,
#      sigmoid(bear_prob) for shorts. Trades always execute; only size varies.
# LLM: MiniMax (Anthropic-compat) via hermes auth.json — trade-level analyst.
_V148_BASE = {
    **_V142_BASE,
    # V144 meta-learner — exit tuning only (not entry gating)
    "meta_learning_enabled": True,
    "meta_learner_exit_only": True,
    # V143 continuous regime-confidence sizing (not entry gating)
    "continuous_sizing": True,
    # LLM analyst: MiniMax via hermes (confirmed working, 60s timeout)
    "llm_analyst_provider": "openai_compatible",
    "llm_analyst_model": "claude-3-5-haiku-20241022",
    "llm_analyst_api_base": "https://api.minimax.io/anthropic",
    "llm_analyst_api_key_env": "MINIMAX_API_KEY",
    "llm_analyst_call_every_n": 10,
    "llm_crisis_mode_enabled": True,
}
_PRESETS["v148"] = VictoriaFeatures(**_V148_BASE)
_PRESETS["v148_no_llm"] = VictoriaFeatures(
    **{**_V148_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False}
)
