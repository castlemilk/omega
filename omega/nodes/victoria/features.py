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

    llm_regime_gate_threshold: float = 0.40
    """V150: bear_prob threshold below which the non-crisis modifier floor applies.
    When bear_prob <= this value the LLM can advise but cannot veto or heavily dampen.
    Default 0.40 = non-crisis markets; 0.0 disables the gate entirely.
    """

    llm_non_crisis_modifier_floor: float = 1.0
    """V150: minimum LLM modifier when bear_prob <= llm_regime_gate_threshold.
    1.0 = off (no floor); 0.70 = LLM can dampen at most 30% but cannot veto in
    non-crisis conditions. Prevents over-vetoing in bull/normal market regimes.
    """

    # ── V152: RMT denoising ───────────────────────────────────────────────────

    rmt_denoise_enabled: bool = False
    """V152: attach RMTDenoiser for correlation-based position limits.
    Denoises the asset correlation matrix using Marchenko-Pastur to remove noise
    eigenvalues before computing position-level correlation risk.
    """

    rmt_n_obs: int = 252
    """V152: observation window for RMT denoiser (trading days). 252 = 1 year."""

    rmt_alpha: float = 0.0
    """V152: blend factor for RMT denoiser (0.0 = pure denoised, 1.0 = empirical)."""

    # ── V152: Wasserstein regime distance ─────────────────────────────────────

    wasserstein_regime_enabled: bool = False
    """V152: enable Wasserstein W₂ regime distance signal.
    Replaces bear_prob-based regime classification with geometry-aware W₁ distance
    to crisis/normal/trending return archetypes. Feeds into regime_w_bear as a
    continuous crash-proximity score.
    """

    wasserstein_window: int = 60
    """V152: rolling return window for Wasserstein distance computation."""

    # ── V152: TDA crash prediction ────────────────────────────────────────────

    tda_signal_enabled: bool = False
    """V152: enable TDA (persistent homology) crash-prediction signal.
    Computes Betti numbers and persistence entropy on delay-embedded returns.
    β₁ loops + low persistence entropy = pre-crash topology.
    """

    tda_window: int = 60
    """V152: rolling return window for TDA embedding."""

    # ── V153: Trend-aware improvements ───────────────────────────────────────

    llm_trend_mode_enabled: bool = False
    """V153: inject trend-mode preamble into LLM system prompt when bull_prob > 0.55.
    Counterpart to llm_crisis_mode_enabled. In a confirmed uptrend the LLM is instructed:
    "Market is in a confirmed uptrend. Long entries are primary. Short entries require
    exceptional conviction." Prevents the LLM from dampening good long entries with
    crisis-trained bearish bias during bull markets.
    """

    trend_signal_dampening: bool = False
    """V153: dampen contrarian/mean-reversion signals in trending/bull regimes.
    Mirror of fear_greed_crisis_weight/sma_crisis_weight but for trend direction:
    mean_reversion and other bearish signals that fight the trend are scaled down
    when bull_prob > 0.55, reducing their drag on composite during uptrends.
    trend_mean_reversion_weight controls the scale factor (default 0.2).
    """

    trend_mean_reversion_weight: float = 0.2
    """V153: weight multiplier for mean_reversion in trending/bull regime (bull_prob > 0.55).
    0.2 = dampen to 20% — removes most contrarian push in strong uptrends.
    Only applied when trend_signal_dampening=True.
    """

    dynamic_modifier_floor: bool = False
    """V153: replace single llm_non_crisis_modifier_floor with per-regime floors.
    Floor map:
      crisis   → dyn_floor_crisis   (default 0.0 — full LLM veto authority)
      normal   → dyn_floor_normal   (default 0.80)
      high_vol → dyn_floor_high_vol (default 0.70 — more LLM influence)
      trending → dyn_floor_trending (default 0.90 — don't fight the trend)
    When True, overrides llm_non_crisis_modifier_floor entirely.
    """

    dyn_floor_crisis: float = 0.0
    """V155: configurable LLM modifier floor in crisis regime. 0.0 = full veto authority."""

    dyn_floor_normal: float = 0.80
    """V155: configurable LLM modifier floor in normal regime."""

    dyn_floor_high_vol: float = 0.70
    """V155: configurable LLM modifier floor in high_vol regime."""

    dyn_floor_trending: float = 0.90
    """V155: configurable LLM modifier floor in trending regime."""

    trend_dampening_bull_prob_threshold: float = 0.65
    """V155: bull_prob threshold above which trend_signal_dampening activates. Default 0.65."""

    regime_transition_signal: bool = False
    """V153: emit a regime_transition signal when the consolidated regime label changes.
    Value encodes direction and magnitude of the transition:
      normal → trending: +0.8  (confirmed bull breakout — strong long)
      crisis → normal:   +0.3  (recovery — moderate long)
      normal → crisis:   -0.8  (regime breakdown — strong short/exit)
      trending → crisis: -0.9  (trend collapse — strongest bearish signal)
      etc.
    Stored as signals["_regime_transition"]; transitions are the highest-alpha
    moments in the cycle where the market hasn't yet priced the new regime.
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

    # V164: softer high_vol gate. The unconditional V142 block costs ~$1.6k of
    # alpha per recent-snapshot window because it sits out high_vol periods that
    # are NOT crisis-precursors. When conditional_high_vol_block=True, the high_vol
    # block fires only when bear_prob also exceeds high_vol_block_bear_threshold,
    # preserving crisis protection (high_vol+high bear_prob = pre-crash) while
    # allowing trading in benign vol spikes (high_vol+low bear_prob = bull volatility).
    conditional_high_vol_block: bool = False
    high_vol_block_bear_threshold: float = 0.40

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
    # V155 — Wasserstein bull_prob auxiliary + asymmetric risk gate
    # ------------------------------------------------------------------

    wasserstein_bull_prob_auxiliary: bool = False
    """V155: suppress crisis mislabeling when bull_prob clearly indicates a bull market.
    Forensics (v152): 30% of trending-snapshot cycles labeled 'crisis' by bear_prob
    oscillation in Q4-2023 bull market. When bull_prob >= threshold, crisis label
    is suppressed regardless of bear_prob, preventing bearish bias in clear uptrends.
    """

    wasserstein_bull_prob_anticrisis_threshold: float = 0.60
    """V155: minimum bull_prob to suppress crisis label when wasserstein_bull_prob_auxiliary=True.
    0.60 = only override crisis when Wasserstein is clearly bullish (not marginal).
    """

    asymmetric_risk_gate: bool = False
    """V155: veto trades where the opposing regime probability dominates the aligned one.
    For longs: veto if bear_prob > bull_prob × asymmetric_risk_threshold.
    For shorts: veto if bull_prob > bear_prob × asymmetric_risk_threshold.
    threshold=1.5 means the opposing regime must be 50% stronger to block entry.
    Preserves trades in balanced regimes; vetoes entries directly against a dominant regime.
    Does NOT block normal-market longs (bear_prob ≈ bull_prob passes at threshold=1.5).
    """

    asymmetric_risk_threshold: float = 1.5
    """V155: regime dominance ratio to trigger asymmetric_risk_gate veto. Default 1.5×.
    1.5 = opposing prob must be 50% stronger than aligned prob to veto (e.g., bear=0.60, bull=0.40).
    """

    # ------------------------------------------------------------------
    # V156 — Regime-adaptive strategy selector
    # ------------------------------------------------------------------

    strategy_selector_enabled: bool = False
    """V156: enable per-cycle regime-adaptive strategy mode switching.
    Detects sustained bull/crisis regimes and applies mode-specific feature overrides:
      TREND mode  — disables crisis protections that fight bull markets
      CRISIS mode — activates full crisis alpha stack
      DEFAULT mode — base config unchanged
    Transitions are hysteresis-gated to prevent oscillation.
    See omega/nodes/victoria/strategy_selector.py for full mode definitions.
    """

    strategy_selector_trend_window: int = 10
    """V156: consecutive cycles with bull_prob above threshold required to enter TREND mode."""

    strategy_selector_crisis_window: int = 5
    """V156: consecutive cycles with bear_prob above threshold required to enter CRISIS mode."""

    strategy_selector_trend_bull_threshold: float = 0.60
    """V156: bull_prob level required (sustained for trend_window cycles) to trigger TREND mode."""

    strategy_selector_crisis_bear_threshold: float = 0.55
    """V156: bear_prob level required (sustained for crisis_window cycles) to trigger CRISIS mode."""

    strategy_selector_trend_exit_window: int = 5
    """V156: consecutive cycles below trend_bull_threshold required to exit TREND mode."""

    strategy_selector_crisis_exit_window: int = 5
    """V156: consecutive cycles below crisis_bear_threshold required to exit CRISIS mode."""

    strategy_selector_trend_crisis_veto: bool = False
    """V160: When True, TREND mode entry is vetoed if any cycle in the last
    strategy_selector_trend_window cycles had a crisis/high_vol/bear regime label.
    Prevents TREND mode from firing during 2022-style pre-crash rising markets where
    regime labels oscillate between 'normal' and 'crisis'/'high_vol'.
    Has no effect on Q4-2023-style sustained bull markets (all-normal labels).
    """

    # ------------------------------------------------------------------
    # V162 — Resilience features (volatility shock, drawdown breaker,
    # correlation breakdown, adaptive sizing, mode-transition blend).
    # See omega/nodes/victoria/resilience.py + signals/vol_shock.py.
    # ------------------------------------------------------------------

    vol_shock_detector_enabled: bool = False
    """V162: Emit vol_shock_max_z / vol_shock_flag / vol_shock_worst_ticker.
    When active (z >= vol_shock_z_threshold): halve sizes, tighten stops 50%,
    raise LLM cadence to every 3 cycles. Hysteresis: release after 5 cycles
    of z < 2.0 (handled inside resilience.ResilienceState)."""

    vol_shock_z_threshold: float = 3.0
    """V162: z-score (current realized vol vs 30-cycle rolling baseline) that
    arms the shock latch. Baseline std must have >=3 samples — else no-op."""

    drawdown_circuit_breaker_enabled: bool = False
    """V162: Track real-time running peak of (realised + unrealised) PnL.
    Halt new entries when drawdown >= max_drawdown_pct; emergency-close every
    open position when drawdown >= 2× max_drawdown_pct. Halt releases when
    drawdown recovers below 0.5× max_drawdown_pct (hysteresis)."""

    max_drawdown_pct: float = 5.0
    """V162: percent drawdown (peak → current equity) that triggers the halt.
    Emergency close at 2× this value. 5.0 = halt at 5% DD, emergency at 10%."""

    correlation_breakdown_protection: bool = False
    """V162: When ORC κ < orc_breakdown_threshold OR Fiedler z <
    fiedler_breakdown_threshold, cap concurrent positions to 2 and tighten
    stops by 30% (multiplier 0.7). Indicates the cross-asset graph has
    decoupled — our basket diversification assumption is broken."""

    orc_breakdown_threshold: float = -0.5
    """V162: ORC κ (Ollivier-Ricci curvature) below this = graph breakdown."""

    fiedler_breakdown_threshold: float = 0.0
    """V162: Fiedler z-score below this = algebraic connectivity collapse."""

    mode_transition_blend: bool = False
    """V162: Blend strategy_selector override values over blend_cycles when
    switching modes, instead of snapping on a single cycle. Numeric fields
    interpolate linearly; boolean fields flip at the midpoint ⌈N/2⌉."""

    blend_cycles: int = 5
    """V162: number of cycles over which to ramp overrides on mode transition."""

    adaptive_position_sizing: bool = False
    """V162: Scale base position size by regime_confidence × (1 − dd/max_dd).
    regime_confidence = |bull_prob − bear_prob|, floored at 0.2. Composes
    multiplicatively with vol_shock size reduction."""

    # ------------------------------------------------------------------
    # V157 — Trend-following signals
    # ------------------------------------------------------------------

    breakout_signal_enabled: bool = False
    """V157: Donchian channel breakout detection signal.
    Computes breakout_position (continuous channel position) and breakout_signal
    (±1 directional flag on N-period high/low break).
    """

    breakout_window: int = 20
    """V157: Donchian channel lookback period (number of candles). Default 20."""

    trend_strength_signal_enabled: bool = False
    """V157: ADX-based trend strength signal.
    adx_signal: directional, 0 when ranging (ADX < adx_min), ±1 in strong trends.
    Suppresses trend-following signals in ranging markets.
    """

    trend_strength_period: int = 14
    """V157: ADX smoothing period (Wilder). Default 14."""

    trend_strength_adx_min: float = 20.0
    """V157: ADX threshold below which trend direction signals are suppressed."""

    multi_timeframe_alignment: bool = False
    """V157: Higher-timeframe momentum alignment signal.
    Computes momentum on short (4-cycle) and long (24-cycle) windows.
    timeframe_signal: +1 when both timeframes agree, 0 when they conflict.
    mtf_size_multiplier: 1.0 aligned, 0.5 conflicting (reduces counter-trend trades).
    """

    mtf_short_window: int = 4
    """V157: Short-term momentum window (cycles). Default 4 ≈ 16h on 4h data."""

    mtf_long_window: int = 24
    """V157: Long-term momentum window (cycles). Default 24 ≈ 4 days on 4h data."""

    regime_signal_weighting: bool = False
    """V157: Regime-adaptive signal weights applied in strategy_selector modes.
    TREND mode: upweights breakout (1.5×), trend_strength (1.5×), momentum (1.2×).
               Downweights mean-reversion signals: ORC (0.5×), SMA (0.3×), BB (0.3×).
    CRISIS mode: upweights mean-reversion (1.5×), ORC (1.2×).
                Downweights momentum (0.5×), breakout (0.3×).
    DEFAULT: equal weights (1.0×).
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

# ---------------------------------------------------------------------------
# V149 — V148 with LLM integration fixed (OpenAICompatibleProvider Anthropic-compat)
# ---------------------------------------------------------------------------
# Root cause: V148's OpenAICompatibleProvider sent Bearer+/chat/completions to
# api.minimax.io/anthropic, which requires x-api-key+/v1/messages (Anthropic format).
# Provider is now fixed — V149 config is identical to V148 but LLM actually fires.
#
# Ablation: v149_no_hysteresis tests whether regime_hysteresis_enabled causes the
# observed -$10k trend-snapshot regression (by locking the crisis label into
# Q4-2023/early-2026 volatile periods where brief volatility triggers crisis briefly).
_V149_BASE = {
    **_V148_BASE,
    # LLM config is unchanged from V148 — provider fix is in llm_analyst.py
}
_PRESETS["v149"] = VictoriaFeatures(**_V149_BASE)

# Kimi-CLI variant (kimi-cli binary, no API key needed)
_PRESETS["v149_kimi"] = VictoriaFeatures(
    **{
        **_V149_BASE,
        "llm_analyst_provider": "kimi_cli",
        "llm_analyst_model": "kimi-latest",
        "llm_analyst_api_base": "",
        "llm_analyst_api_key_env": "",
    }
)

# Ablation: disable regime hysteresis to check if it causes trend regression
_PRESETS["v149_no_hysteresis"] = VictoriaFeatures(
    **{**_V149_BASE, "regime_hysteresis_enabled": False}
)

# No-LLM baseline for isolating LLM contribution
_PRESETS["v149_no_llm"] = VictoriaFeatures(
    **{**_V149_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False}
)

# ---------------------------------------------------------------------------
# V150 — Regime-gated LLM: non-crisis modifier floor
# ---------------------------------------------------------------------------
# V149 post-mortem: LLM helped crisis (-$875 best ever) but hurt recent/trend
# via over-vetoing (46% veto rate, avg_mod=0.527 in normal conditions).
# Fix: when bear_prob <= 0.40 (non-crisis), clamp modifier floor to 0.70 so
# the LLM can advise but cannot veto or cut size by more than 30%.
# Crisis behavior (bear_prob > 0.40) is unchanged from V149.
_V150_BASE = {
    **_V149_BASE,
    "llm_regime_gate_threshold": 0.40,
    "llm_non_crisis_modifier_floor": 0.70,
}
_PRESETS["v150"] = VictoriaFeatures(**_V150_BASE)

# Kimi HTTP variant (if key is valid)
_PRESETS["v150_kimi"] = VictoriaFeatures(
    **{
        **_V150_BASE,
        "llm_analyst_provider": "kimi",
        "llm_analyst_model": "moonshot-v1-8k",
        "llm_analyst_api_base": "",
        "llm_analyst_api_key_env": "KIMI_API_KEY",
    }
)

# No-LLM baseline for isolating V150 structural changes
_PRESETS["v150_no_llm"] = VictoriaFeatures(
    **{**_V150_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False}
)

# ---------------------------------------------------------------------------
# V151 — Regime-label-gated LLM floor (fix V150 crisis regression)
# ---------------------------------------------------------------------------
# V150 post-mortem: bear_prob gate (≤0.40) fired during crisis bear_prob dips,
# applying the floor mid-crisis and allowing trades that should be vetoed.
# Fix: gate the floor on regime label == "crisis" instead of bear_prob.
# When label is crisis, full veto mode regardless of momentary bear_prob.
# When label is normal/high_vol/trending, floor applies.
#
# Grid: 3 floor values to find recent/crisis Pareto optimum.
#   v151a: floor=0.70 — same as V150 but crisis-gated correctly
#   v151b: floor=0.80 — more permissive, LLM can dampen ≤20%
#   v151c: floor=0.90 — near pass-through, LLM advisory only in non-crisis
_V151_BASE = {
    **_V149_BASE,
    # llm_regime_gate_threshold no longer used (V151 uses label gate in strategy.py)
}
_PRESETS["v151a"] = VictoriaFeatures(**{**_V151_BASE, "llm_non_crisis_modifier_floor": 0.70})
_PRESETS["v151b"] = VictoriaFeatures(**{**_V151_BASE, "llm_non_crisis_modifier_floor": 0.80})
_PRESETS["v151c"] = VictoriaFeatures(**{**_V151_BASE, "llm_non_crisis_modifier_floor": 0.90})

# V152: best V151 preset (v151c, floor=0.90) + all 3 research signals enabled.
# - rmt_denoise: already always-on via set_rmt_denoiser() wire; flag kept for clarity
# - wasserstein_regime_enabled: W₁ distances to crisis/normal/trending archetypes
# - tda_signal_enabled: persistent homology crash-prediction on BTC returns
_V152_BASE = {
    **_V151_BASE,
    "llm_non_crisis_modifier_floor": 0.90,  # best V151 floor
    "wasserstein_regime_enabled": True,
    "wasserstein_window": 60,
    "tda_signal_enabled": True,
    "tda_window": 60,
}
_PRESETS["v152"] = VictoriaFeatures(**_V152_BASE)
_PRESETS["v152_no_llm"] = VictoriaFeatures(**{**_V152_BASE, "llm_analyst_enabled": False})
_PRESETS["v152_wasserstein_only"] = VictoriaFeatures(**{
    **_V151_BASE,
    "llm_non_crisis_modifier_floor": 0.90,
    "wasserstein_regime_enabled": True,
    "wasserstein_window": 60,
    "tda_signal_enabled": False,
})
_PRESETS["v152_tda_only"] = VictoriaFeatures(**{
    **_V151_BASE,
    "llm_non_crisis_modifier_floor": 0.90,
    "wasserstein_regime_enabled": False,
    "tda_signal_enabled": True,
    "tda_window": 60,
})

# V153: V152 + 4 trend-aware improvements.
# Forensics (docs/research/trend-forensics-v152.md) identified regime mislabeling
# (30% crisis cycles in a bull market) and LLM bearish bias as root causes of
# trend-snapshot regression vs V139. V153 directly addresses both.
_V153_BASE = {
    **_V152_BASE,
    "llm_trend_mode_enabled": True,       # LLM trend-mode preamble in bull market
    "trend_signal_dampening": True,        # dampen mean_reversion in uptrends
    "dynamic_modifier_floor": True,        # per-regime floors: trending=0.90, high_vol=0.70
    "regime_transition_signal": True,      # high-alpha transition detection signal
}
_PRESETS["v153"] = VictoriaFeatures(**_V153_BASE)
_PRESETS["v153_no_llm"] = VictoriaFeatures(**{**_V153_BASE, "llm_analyst_enabled": False})
_PRESETS["v153_trend_only"] = VictoriaFeatures(**{
    **_V152_BASE,
    "llm_trend_mode_enabled": True,
    "trend_signal_dampening": True,
    "dynamic_modifier_floor": True,
    "regime_transition_signal": False,     # isolate: trend fixes without transition signal
})
_PRESETS["v153_transition_only"] = VictoriaFeatures(**{
    **_V152_BASE,
    "regime_transition_signal": True,      # isolate: just the transition signal
})

# V154: v153_trend_only + crisis floor 0.50 (was 0.0) + bull_prob threshold 0.65 (was 0.55)
_V154_BASE = {
    **_V152_BASE,
    "llm_trend_mode_enabled": True,
    "trend_signal_dampening": True,
    "dynamic_modifier_floor": True,
    "regime_transition_signal": False,
}
_PRESETS["v154"] = VictoriaFeatures(**_V154_BASE)

# V155: grid-search-tuned floor params + Wasserstein bull_prob auxiliary.
#
# Grid search (200 cycles, recent snapshot, 27 combos) winner:
#   dyn_floor_crisis=0.25, dyn_floor_normal=0.70, trend_dampening_bp_thresh=0.65
#   PnL $+10,427 | PF 1.64 | WR 41.3% | 63 trades — sole Pareto-dominant config.
#
# asymmetric_risk_gate disabled after Phase A showed it degrades trend snapshot
# (-$8k vs V153to -$868). Wasserstein bull_prob auxiliary also disabled — it can't
# override mislabeled crisis cycles where bull_prob is already suppressed by the
# Wasserstein distribution shift. Both will be revisited in V156 with a deeper fix.
_V155_BASE = {
    **_V152_BASE,
    "llm_trend_mode_enabled": True,
    "trend_signal_dampening": True,
    "dynamic_modifier_floor": True,
    "regime_transition_signal": False,
    # Floors reverted to V153to defaults after Phase A showed grid-winner params
    # (cf=0.25, nc=0.70) overfit recent-only and hurt crisis (-$2.9k) + trend (-$4.3k).
    # Grid search confirmed td_thresh=0.65 is already optimal (was the default).
    # V156 will run a multi-snapshot grid search to find truly generalizable floors.
    "dyn_floor_crisis": 0.0,                     # reverted: LLM full veto in crisis
    "dyn_floor_normal": 0.80,                    # reverted: original V153to value
    "dyn_floor_high_vol": 0.70,                  # unchanged
    "dyn_floor_trending": 0.90,                  # unchanged
    "trend_dampening_bull_prob_threshold": 0.65,  # grid-confirmed (was already default)
}
_PRESETS["v155"] = VictoriaFeatures(**_V155_BASE)
# v155_wass: with Wasserstein auxiliary — for future ablation testing
_PRESETS["v155_wass"] = VictoriaFeatures(**{
    **_V155_BASE,
    "wasserstein_bull_prob_auxiliary": True,
    "wasserstein_bull_prob_anticrisis_threshold": 0.60,
})
# v155_asymm: with asymmetric gate — for future ablation testing
_PRESETS["v155_asymm"] = VictoriaFeatures(**{
    **_V155_BASE,
    "asymmetric_risk_gate": True,
    "asymmetric_risk_threshold": 1.5,
})

# ---------------------------------------------------------------------------
# V156 — Regime-adaptive strategy selector
# ---------------------------------------------------------------------------
# The manifold analysis proved a single config can't win across all regimes.
# V156 adds a per-cycle mode switcher: TREND (removes crisis blocks in bull
# markets) / CRISIS (full crisis alpha) / DEFAULT (base config unchanged).
# Base: V155 with strategy_selector enabled.
_V156_BASE = {
    **_V155_BASE,
    "strategy_selector_enabled": True,
    "strategy_selector_trend_window": 10,       # 10 bull cycles to enter TREND
    "strategy_selector_crisis_window": 5,       # 5 bear cycles to enter CRISIS
    "strategy_selector_trend_bull_threshold": 0.60,
    "strategy_selector_crisis_bear_threshold": 0.55,
    "strategy_selector_trend_exit_window": 5,
    "strategy_selector_crisis_exit_window": 5,
}
_PRESETS["v156"] = VictoriaFeatures(**_V156_BASE)
_PRESETS["v156_no_llm"] = VictoriaFeatures(**{**_V156_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# ---------------------------------------------------------------------------
# V157 — Trend-following signals + regime-adaptive signal weighting
# ---------------------------------------------------------------------------
# Adds three price-only trend signals (breakout detection, ADX trend strength,
# multi-timeframe momentum alignment) and regime-aware weight scaling.
#
# Best auto-improve params: dyn_floor_crisis=0.0, trend_dampening_bull=0.574,
#                           dyn_floor_normal=0.80 (from 2-snapshot GP search).
# ---------------------------------------------------------------------------
_V157_BASE = {
    **_V156_BASE,
    # Tune best auto-improve params from 2-snapshot GP search
    "dyn_floor_crisis": 0.0,
    "trend_dampening_bull_prob_threshold": 0.574,
    "dyn_floor_normal": 0.80,
    # V157 trend signals
    "breakout_signal_enabled": True,
    "breakout_window": 20,
    "trend_strength_signal_enabled": True,
    "trend_strength_period": 14,
    "trend_strength_adx_min": 20.0,
    "multi_timeframe_alignment": True,
    "mtf_short_window": 4,
    "mtf_long_window": 24,
    # Regime-aware signal weighting
    "regime_signal_weighting": True,
}
_PRESETS["v157"] = VictoriaFeatures(**_V157_BASE)
_PRESETS["v157_no_llm"] = VictoriaFeatures(**{**_V157_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# V157 ablation: selector fix + regime weighting only (no new signals).
# Isolates contribution of reweighting vs the new signal content.
_V157_NO_TREND_SIGNALS_BASE = {
    **_V156_BASE,
    "dyn_floor_crisis": 0.0,
    "trend_dampening_bull_prob_threshold": 0.574,
    "dyn_floor_normal": 0.80,
    "regime_signal_weighting": True,
    # All trend signals OFF
    "breakout_signal_enabled": False,
    "trend_strength_signal_enabled": False,
    "multi_timeframe_alignment": False,
}
_PRESETS["v157_no_trend_signals"] = VictoriaFeatures(**_V157_NO_TREND_SIGNALS_BASE)
_PRESETS["v157_no_trend_signals_no_llm"] = VictoriaFeatures(**{
    **_V157_NO_TREND_SIGNALS_BASE,
    "llm_analyst_enabled": False,
    "llm_crisis_mode_enabled": False,
})

# ---------------------------------------------------------------------------
# V158 — Breakout-aware regime detection
# ---------------------------------------------------------------------------
# Fixes the V157 selector bug: "normal" regime is now only mapped to
# bull_prob=0.65 when basket_breakout > 0.10 AND basket_mtf > 0.
# This prevents TREND mode from firing in the 2022 crisis snapshot's
# "normal" pre-crash period, while still triggering on genuine bull markets
# (Q4-2023) where prices ARE making new Donchian highs.
# ---------------------------------------------------------------------------
_V158_BASE = {
    **_V157_BASE,
    # trend_window stays at 10 (needs 10 × confirmed normal-with-breakout cycles)
    # crisis_window stays at 5 (fast reaction to bear/crisis labels)
    # All V157 signals kept — they're what makes _basket_breakout available
}
_PRESETS["v158"] = VictoriaFeatures(**_V158_BASE)
_PRESETS["v158_no_llm"] = VictoriaFeatures(**{**_V158_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# ---------------------------------------------------------------------------
# V159 — Faster crisis detection + breakout-amplified SHORT signals in crisis
# ---------------------------------------------------------------------------
# Root cause of V158 crisis failure (from progress analysis):
#   1. TREND mode fires in Jan-Feb 2022 (basket_breakout > 0.10 during brief rally)
#   2. When crash hits (~cycle 125), the crisis_window=5 delay costs ~$42k in losses
#   3. After entering CRISIS mode (~cycle 250), breakout signals are suppressed
#      to 0.3× — cutting off the strongest SHORT alpha (breakdown signals)
#
# Fixes:
#   1. trend_window: 10 → 15 (harder to enter TREND: need 15 consecutive breakout
#      cycles = 60h = 2.5 days, less likely during 2022 short bounces)
#   2. crisis_window: 5 → 3 (faster CRISIS entry: only 3 cycles needed = 12h)
#   3. CRISIS breakout weights: 0.3 → 1.5 (breakdown signals = SHORT alpha)
#      (strategy.py _REGIME_SIGNAL_WEIGHTS["CRISIS"]["breakout_signal"] = 1.5)
# ---------------------------------------------------------------------------
_V159_BASE = {
    **_V158_BASE,
    "strategy_selector_trend_window": 15,       # harder to enter TREND
    "strategy_selector_crisis_window": 3,       # faster crisis entry (was 5)
    "strategy_selector_trend_exit_window": 5,   # unchanged
    "strategy_selector_crisis_exit_window": 3,  # faster crisis exit too (was 5)
}
_PRESETS["v159"] = VictoriaFeatures(**_V159_BASE)
_PRESETS["v159_no_llm"] = VictoriaFeatures(**{**_V159_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# ---------------------------------------------------------------------------
# V160 — Crisis-label contamination window veto on TREND entry
# ---------------------------------------------------------------------------
# Root cause of ALL V157/V158/V159 crisis failures (confirmed from trade logs):
#   - 2022 crisis snapshot oscillates between "normal" and "crisis"/"high_vol" labels
#     while prices are still rising in Jan-Feb 2022 (pre-crash bull continuation)
#   - V158/V159's basket_breakout > 0.10 condition fires in BOTH Q4-2023 (genuine bull)
#     and Jan-Feb 2022 (pre-crash rising) → can't disambiguate with price action alone
#   - V159 attempted faster crisis_window=3 + upweighted shorts, but:
#     shorts entered in CRISIS mode lose when prices rise (cycle 153 crash: -$31k in 5c)
#     shorts entered in DEFAULT mode with breakdown signals also lose in rising market
#
# Key differentiator: Q4-2023 vs Jan-Feb 2022:
#   - Q4-2023 (genuine trend): regime labels are SUSTAINED "normal" (no crisis/high_vol
#     labels mixed in over the trend_window period)
#   - 2022 pre-crash: regime labels OSCILLATE between "normal" and "crisis"/"high_vol"
#     even during the rising phase — the regime model detects underlying fragility
#
# Fix: track a crisis-label contamination window (deque of size trend_window).
#      If ANY cycle in the last trend_window cycles had a crisis/high_vol/bear label,
#      cap bull_prob below trend_bull_threshold → TREND mode cannot fire.
#      After the contamination window clears (trend_window consecutive clean cycles),
#      TREND mode can fire normally if breakout/MTF confirm it.
# ---------------------------------------------------------------------------
_V160_BASE = {
    **_V158_BASE,                                     # same signals as V158
    "strategy_selector_trend_window": 10,             # back to V158 (was 15 in V159)
    "strategy_selector_crisis_window": 5,             # back to V158 (was 3 in V159)
    "strategy_selector_trend_exit_window": 5,
    "strategy_selector_crisis_exit_window": 5,
    "strategy_selector_trend_crisis_veto": True,      # V160: the key new flag
}
_PRESETS["v160"] = VictoriaFeatures(**_V160_BASE)
_PRESETS["v160_no_llm"] = VictoriaFeatures(**{**_V160_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# ---------------------------------------------------------------------------
# V161 — Dual-duty crisis veto: CRISIS overrides applied in DEFAULT mode
#         when crisis labels contaminate the window
# ---------------------------------------------------------------------------
# V160 failure analysis (from cycle 170 crisis: -$35k):
#   - Crisis-label veto DID prevent TREND mode (0 StrategySelector transitions) ✓
#   - But DEFAULT mode was still taking longs during the 2022 crash
#   - Root cause: V160 base config has crisis_long_block=False (default)
#     AND the selector's crisis_window=5 counter kept resetting because
#     "normal" labels interrupted the streak → CRISIS mode never armed
#
# V161 change (in strategy_selector.py _apply_overrides only):
#   - When in DEFAULT mode AND crisis_contaminated=True → apply _CRISIS_OVERRIDES
#     (same protections as full CRISIS mode: crisis_long_block, high_vol_entry_block, etc.)
#   - This makes the contamination window dual-purpose:
#     1. Veto TREND mode (prevents longs in pre-crash rising markets)
#     2. Apply CRISIS protections (prevents longs after crash begins)
#   - Net effect in crisis snapshot: always in CRISIS-protected mode
#     (V153-like conservative behaviour → small positive PnL expected)
#   - Net effect in trend snapshot: brief CRISIS override during occasional
#     volatility spikes (acceptable cost), TREND mode fires in clean stretches
# ---------------------------------------------------------------------------
_V161_BASE = _V160_BASE  # same flags; the change is in strategy_selector.py
_PRESETS["v161"] = VictoriaFeatures(**_V161_BASE)
_PRESETS["v161_no_llm"] = VictoriaFeatures(**{**_V161_BASE, "llm_analyst_enabled": False, "llm_crisis_mode_enabled": False})

# V161_LIVE: production config — v161_no_llm base + 5-param optimal from 2026-04-24
# 5-param auto_improve run 2 (iter 8), composite backtest +$41,850 all-positive:
#   recent=+$4,319 (103t, pf 1.13), crisis=+$2,606 (32t, pf 1.23), trend=+$34,925 (100t, pf 2.65)
# Note: LLM analyst stays OFF — matches the backtest config exactly. Tracing flags
#   (decision_traces, activation_tracing, signal_reasoning) are inherited True from
#   v161_no_llm. Enabling llm_analyst for live would diverge from backtest premise.
_V161_LIVE = {
    **_V161_BASE,
    "llm_analyst_enabled": False,
    "llm_crisis_mode_enabled": False,
    # 5-param optimal (auto_improve_5param_run2.jsonl iter 8)
    "trend_dampening_bull_prob_threshold": 0.6305,
    "crisis_short_thresh_scale": 0.701,
    "strategy_selector_trend_bull_threshold": 0.7265,
    "strategy_selector_crisis_bear_threshold": 0.6093,
    "bear_prob_long_block_threshold": 0.4188,
}
_PRESETS["v161_live"] = VictoriaFeatures(**_V161_LIVE)

# V162: resilience-hardened preset — v161_live base + 5 resilience features enabled.
# Trades composite PnL for stability: halves sizes on vol shocks, halts entries at
# 5% drawdown, emergency-closes at 10%, caps positions to 2 during correlation
# breakdown, blends mode transitions over 5 cycles, scales size by regime confidence.
_V162_BASE = {
    **_V161_LIVE,
    # vol_shock
    "vol_shock_detector_enabled": True,
    "vol_shock_z_threshold": 3.0,
    # drawdown
    "drawdown_circuit_breaker_enabled": True,
    "max_drawdown_pct": 5.0,
    # correlation breakdown
    "correlation_breakdown_protection": True,
    "orc_breakdown_threshold": -0.5,
    "fiedler_breakdown_threshold": 0.0,
    # mode transition blend
    "mode_transition_blend": True,
    "blend_cycles": 5,
    # adaptive sizing
    "adaptive_position_sizing": True,
}
_PRESETS["v162"] = VictoriaFeatures(**_V162_BASE)
_PRESETS["v162_resilient"] = VictoriaFeatures(**_V162_BASE)
