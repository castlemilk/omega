from __future__ import annotations

"""
omega.nodes.victoria.strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StrategyNode — combines signals into portfolio decisions and backtests them.

Improvement arc:
  v1.0 — Equal-weight portfolio of buy-signal stocks
  v1.1 — Momentum-weighted portfolio (weight ∝ composite signal strength)
  v1.2 — Risk-parity-weighted portfolio (weight ∝ 1/volatility)
  v1.3 — Signal threshold tuning based on backtest Sharpe feedback
  v1.4 — Relative conviction thresholds: scale by basket composite std (V45)
  v1.5 — Lower conviction multiplier 0.5σ→0.3σ, floor 0.005→0.010 (V48)
  v1.6 — Blacklist AVAXUSDT (27 losing longs in V55); restore DOT normal-regime shorts (V56)
  v1.7 — Freeze weighting at "equal" (V57): v1.1/v1.2 momentum/risk-parity upgrades caused
          extreme zero_streaks (182/200 in V56) when the improvement engine triggered mid-run.
          V56 analysis: 8 trades opened before improvement (WR=62.5%), zero after. Root cause:
          risk_parity + continuous-regime scaling produces near-zero weights post-improvement.
          Frozen at equal weighting; v1.3 signal_threshold tightening also disabled.
  v1.8 — Fix adv_* basket_std inflation (V58): adapt_signals() injects adv_spectral_graph
          (raw Fiedler z-score, ±5+) into the basket used for _cs_norm scaling.  Once the
          SpectralGraphSignal exits its 15-cycle warmup, the inflated basket_std collapses
          _cs_norm, mapping all per-ticker composites to HOLD.  Fix: exclude adv_* synthetic
          aggregates from basket_std computation.  Root cause of V49–V57 zero_streak.
  v1.9 — Blacklist LINKUSDT longs (V59): V58 produced 30 LINK longs, -$34.95 — the entire
          loss for the run.  DOT shorts remain enabled (+$9.63).  Normal regime long threshold
          raised 0.10→0.13 to filter borderline long signals (V58 normal WR=37%).
  v2.0 — Raise normal short_thresh 0.05→0.10 (V61): V59 DOT normal shorts lost -$28.93
          (36 trades, 30% WR in normal) — marginal short signals not credible in normal regime.
          DOT high_vol/crisis shorts remain active via lower thresholds in those branches.
          ETH longs stay fully enabled (50% WR, +$21.83 in V59 — no high_vol blacklist).
  v2.1 — V63 WR improvements: (a) Blacklist MATICUSDT (16 zero-PnL trades in V62).
          (b) Absolute min conviction floor 0.12 — filters bottom third of marginal signals
          (trade distribution shows 0.06–0.14; floor removes low-conviction entries regardless
          of regime). (c+d) Multi-cycle confirmation: only enter when current direction matches
          previous cycle's direction — prevents whipsaw entries on single-cycle spikes.
  v2.2 — V65 improvements: (a) Suppress ETHUSDT longs in high_vol regime — V63 deep
          analysis: all 5 worst trades were ETH longs, $-27 to $-10 each. (b) Crisis short
          threshold 0.05→0.02 to capture more shorts in bear market (shorts 8x more profitable
          per trade in V63: $7.63 vs $0.97). (c) Conviction-weighted sizing: continuous scale
          by (w_conv/0.25) ∈ [0.5, 2.0] — V63 showed zero spread between winner/loser
          conviction; this differentiates position size by actual conviction magnitude.
          (d) Asymmetric hold: losers capped at 4 cycles, winners run to 10.
  v2.3 — V66 improvements: Extend ETH long suppression to normal regime — V65 ETH:normal
          was 15T all-long, avg_win $9 vs avg_loss -$28 (3:1 ratio), -$159 total.  Crisis
          ETH longs remain enabled ($+6.35 in V65, still positive).  Also suppress BNB longs
          in normal regime (V65 BNB:normal: 6T 1W 17% WR, -$18.78).
  v2.4 — V72 post-mortem: V71's long=0.30 in crisis+extreme_fear was wrong.
          Longs opened at 0.30 in crisis regime close later in "normal" regime and
          book as normal-regime losses (V71 normal: -$145.61, V70 partial: -$43).
          Reverting to hard-block on longs (0.99) and raising short_thresh to 0.10
          (bounce guard) when FGI > 0.25 to filter out panic-shorts on true bounces.
          When FGI ≤ 0.25: revert to V65 defaults (long=0.99 hard-block, short=0.02).
  v2.5 — V73 fixes: (a) Suppress SOLUSDT shorts in normal regime — V71: 10 SOL normal
          shorts, 0 wins (0% WR), -$78.87. (b) Increase loser max_hold 4→6 cycles —
          V71 winners held 10 cycles avg, losers 4.6; 6-cycle floor gives more room to
          recover. (c) Blacklist XRPUSDT — V71: 6T 1W 17% WR -$44.91; V72: 8T 2W 25%
          WR -$105.30 — signal consistently wrong across two runs.
  v2.6 — V75 fixes: (a) Ricci crash-proximity gate (signal_generation.py): suppress
          positive Ricci mean-reversion signal when market is closer to crash reference
          than rally reference — V74 post-mortem: ricci=+0.78 during April 2026 crash
          overrode fear_greed(-0.43)+VIX(-0.32), flipping BTC conviction from SELL to BUY.
          Dampening factor = geo_dist_crash/geo_dist_rally (0=fully suppressed at crash).
          (b) Fiedler-fragmented+bear gate: when Fiedler signals fragmented for ≥30 cycles
          AND bear_prob>0.25, raise long_conviction_threshold 0.10→0.25. V74 had Fiedler
          fragmented from cycle 15 with bear_prob 0.29–0.30; standard 0.10 threshold
          allowed 7 losing longs before HMM reached crisis label at cycle ~130.
  v2.7 — V79 fixes: (a) Blacklist ADAUSDT longs — V78: ADA long at conviction 0.125
          lost -$29.17 (signal wrong direction in current regime). ADA shorts remain
          active. (b) Raise _abs_min_conviction 0.02→0.06 — V78 marginal ETH/BNB shorts
          entered at conviction 0.064 (barely above 0.02 floor) and lost $0.5-$3.8 each;
          the basket_std scaling reduced short_thresh to ~0.05, making the 0.02 floor
          the de-facto gate. 0.06 floor ensures minimum signal quality.
          (c) _is_normal includes 'sideways' — Wasserstein HMM returns 'sideways' for
          normal market; previously bypassed SOL/BNB/ETH suppressions.
  v2.8 — V80 fix: Blacklist SOLUSDT entirely — V73: 10T 0W -$78.87 (normal shorts).
          V77: 4T -$4.10 (normal). V78: 2T -$13.19 (normal + crisis). No winning SOL
          short across any regime over 3+ training runs; signal consistently wrong.
  v3.0 — V84 fixes: (a) Cap _thresh_scale at 1.5 — V83 zero-streak (75 cycles) caused by
          basket_std=0.38 producing _thresh_scale=1.9, inflating crisis long_thresh 0.50→0.95
          and short_thresh 0.04→0.076 beyond what any composite can reach. Cap at 1.5 prevents
          threshold inflation while preserving regime-adaptive ratio semantics.
          (b) Lower crisis long_thresh 0.99→0.50 — 0.99 × _thresh_scale was mathematically
          impossible (effective ceiling 1.88); 0.50 × 1.5 cap = 0.75 max, allowing through
          genuinely high-conviction crisis longs while still heavily suppressing marginal entries.
          (c) Widen crisis short bypass composite gate -0.10→-0.07 — AVAX/LINK (the V82 offenders)
          are now in _TRADING_BLACKLIST; post-demeaning crisis composites cluster at -0.06 to -0.09,
          so -0.10 was blocking the bypass for nearly all valid crisis shorts.
  v2.9 — V92 fixes: (a) Remove ETH absolute conviction floors (normal 0.07, high_vol 0.11)
          — floors were unscaled absolutes while long_thresh scales with basket_std (0.017-0.024
          in recovery). ETH composites 0.025-0.063 pass scaled threshold but fail absolute floor.
          2-cycle confirmation + IC-weighted filter are sufficient protection.
          (b) Raise Fiedler bear_prob threshold 0.25→0.40 — recovery bear≈0.31 was re-triggering
          suppression after V89's crisis-reset fix. Streak resets in crisis, re-accumulates in
          normal recovery (30 cycles), then suppresses at bear=0.31 (above 0.25). At 0.40,
          recovery is not suppressed; genuine bear (>0.40) still triggers.
  v3.0 — V95 fixes (four changes):
          (a) Gate regime_hmm/regime_label "crisis" paths with bear_prob >= 0.45.
          HMM transitions slowly and stays "crisis" for 30+ cycles post-crash while
          bear_prob=0.31–0.38 (probability model prices recovery). V94 was no-op (same code
          as V93). V95 requires bear_prob >= 0.45 for HMM/label-based crisis to block longs;
          bear_prob >= 0.65 still triggers hard lock unconditionally.
          (b) Revert normal short_thresh 0.05→0.07. V94 forensics: fewer shorts (3 vs 6),
          loss was crisis-labeled longs opened in normal regime that closed on market decline.
          (c) Geometry signals: ORC stress size mult (kappa>0.1 → 0.6–1.0x), Ricci-weighted
          long sizing (mean-reversion + crash proximity → up to 30% long size reduction),
          geodesic crash gate (crash_prox>=0.6 → long_thresh raised up to 40%).
          (d) Fiedler conviction modulation: fragmented → short_thresh * 0.85 (floor 0.04);
          consensus (z>1) → both thresholds * 0.90–0.95.
  v3.1 — V85 fixes: (a) Restore ETHUSDT long suppression in high_vol regime — V92 removed the
          absolute conviction floor but inadvertently also removed the directional gate that
          V65 introduced. V84: 4 ETH high_vol longs, 0% WR, -$18.09. Re-add the hard block
          (not just a floor) for ETH longs in high_vol; the downside momentum in volatile
          regimes is too strong for mean-reversion entries.
          (b) Lower normal short_thresh 0.08→0.05 — V84 had 0 shorts in 200 cycles despite
          ETH declining -0.43%. Normal-regime composites cluster at ±0.04–0.08; the 0.08
          bar was blocking all short signals. 0.05 captures genuine bearish conviction while
          staying above the abs_min floor (0.02).
  v3.2 — V86 fixes: Restore symbol diversity to break single-asset ETH concentration.
          V84: 23/23 trades ETHUSDT. V85: 22/22 trades ETHUSDT. Root cause: _LONG_BLACKLIST
          blocks ADA longs; _TRADING_BLACKLIST eliminates DOT/SOL/BNB/LINK/AVAX/MATIC/XRP.
          (a) Remove ADAUSDT from _LONG_BLACKLIST — ADA shorts are already allowed; restoring
          longs lets ADA participate in both directions. Prior ADA long losses (-$29.17 V78)
          were at high conviction (0.125); with abs_min=0.02 and normal long_thresh=0.10,
          only quality signals enter. V85-era comment about "V85-V86 confirmation" was
          written speculatively in a prior session — actual V85 generated 0 ADA trades.
          (b) Keep normal long_thresh at 0.07 — initial V86 raised to 0.10 but caused
          max_zero_streak=150 and only 8 trades. Post-crash composites cluster 0.02–0.09;
          0.10 is above the range for both ETH and ADA. Reverting in V87.
  v3.3 — V88 fix: Lower multi-cycle confirmation bypass 0.09→0.05 — V86/V87 produced
          zero_streak=150/167 despite long_thresh=0.07/0.10. Root cause: bypass requires
          w_conv >= 0.09 for first-cycle entry without prior confirmation; current market
          composites cluster at 0.02–0.06, never reaching 0.09. Confirmation gate is
          working as designed but the bypass bar is above the market's conviction range.
          0.05 is still ~1.4x the effective scaled threshold, a meaningful quality floor.
          (c) Lower normal short_thresh 0.05→0.07 — raising slightly from V85's 0.05 to
          reduce noise shorts; still well below V84's 0.08 which blocked all shorts.
"""

import logging
import math
import time
import uuid
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

from omega.core.actions import NodeAction
from omega.core.decision_snapshot import SignalTrace, TickerDecision
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.risk_manager import PositionRiskManager
from omega.nodes.victoria.anomaly_detector import AnomalyDetector
from omega.nodes.victoria.decision_embeddings import DecisionEmbedder
from omega.nodes.victoria.decision_trace import (
    DecisionTrace,
    TraceWriter,
    build_explanation,
)
from omega.nodes.victoria.features import VictoriaFeatures
from omega.nodes.victoria.signal_confluence import ConfluenceAnalyzer, ConfluenceResult
from omega.nodes.victoria.signal_correlation import SignalCorrelationMonitor
from omega.nodes.victoria.spectral_signals import SpectralGraphSignal

logger = logging.getLogger("omega.nodes.victoria.strategy")

# Symbols excluded from trading (still used as regime/signal indicators).
# BTC has a 27.8% win rate — used only as a market regime indicator.
# DOTUSDT: V61 — 12.5% WR, -$33.89; blacklisting projected +$47.44.
# MATICUSDT: V62 post-mortem — 16 zero-PnL trades wasting capacity; signal not credible.
# XRPUSDT: V73 post-mortem — V71: 6T 1W 17% WR -$44.91; V72: 8T 2W 25% WR -$105.30.
#   XRP signal consistently wrong across two independent runs; removing from rotation.
# SOLUSDT: V80 post-mortem — V73 suppressed normal shorts (10T 0W -$78.87). V77: 4 normal
#   shorts -$4.10. V78: normal -$4.30 + crisis -$8.89. No winning SOL short across any regime;
#   signal consistently wrong direction. Removing entirely from trading rotation.
_TRADING_BLACKLIST: frozenset[str] = frozenset(
    # V81: SOLUSDT re-blacklisted — V80 run confirmed SOL short signals are wrong-direction.
    # Two crisis shorts lost -$5.92 and -$24.40 (price went up both times despite negative
    # composite -0.06). The bypass fix doesn't help when the underlying signal direction is wrong.
    # The V79 zero-streak was caused by blacklisting SOL (removing only valid short candidate)
    # but the real fix is to generate normal/high_vol longs instead of crisis shorts.
    # V83: AVAXUSDT fully blacklisted — 3/3 losing trades across all regimes, both directions:
    #   long -$15.28, crisis short -$13.40, normal short -$13.38. Total -$42.06.
    #   AVAX signal consistently wrong or mean-reverting; neither direction is credible.
    # V86: LINKUSDT fully blacklisted — cumulative -$55.73 across all trade types:
    #   30 longs -$34.95 (V58), crisis short -$6.78 (V81), crisis short +$13.62 (V82),
    #   crisis short -$13.75 (V85), high_vol short -$13.87 (V85). One profitable trade
    #   is insufficient to offset 4 losing trades. LINK is mean-reverting in $9.01-$9.10
    #   range; both long and short signals are wrong-direction in current market conditions.
    # V87: BNBUSDT fully blacklisted — 3/3 short losses in V86 first 40 cycles (-$53.82).
    #   BNB is in post-crash recovery (rising from $602→$604 range); shorting is consistently
    #   wrong-direction. BNB long signals are untested; removing entirely until trend clears.
    # V93: SUIUSDT fully blacklisted — V92: 2T 0% WR -$9.14. Only 2 trades, both losses.
    #   SUI signal is noise-level; insufficient data to trust either direction.
    {
        "BTCUSDT",
        "DOTUSDT",
        "MATICUSDT",
        "XRPUSDT",
        "SOLUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "BNBUSDT",
        "SUIUSDT",
    }
)

# Symbols excluded from LONG positions only (shorts still permitted).
# BTC: regime indicator only, <28% win rate.
# V86: ADAUSDT removed from _LONG_BLACKLIST — restoring longs to break ETH-only concentration.
#   V84/V85 both ran 100% ETHUSDT trades. ADA shorts already allowed; enabling longs restores
#   bidirectional participation. Prior V78 loss (-$29.17) was at conviction 0.125 without
#   abs_min gating; current quality filters (abs_min=0.02, normal long_thresh=0.10) provide
#   sufficient protection. The "V85-V86 confirmation" comment in prior session was speculative
#   — actual V85 generated 0 ADA trades (ADA was long-blacklisted the entire run).
_LONG_BLACKLIST: frozenset[str] = frozenset({"BTCUSDT"})

# Symbols excluded from the crisis first-cycle bypass (multi-cycle confirmation
# required even in crisis regime for these tickers).
# Note: LINKUSDT was here but V86 moved it to _TRADING_BLACKLIST (fully removed).
# Note: AVAXUSDT was here, but V83 moved it to _TRADING_BLACKLIST (fully removed).
_CRISIS_BYPASS_BLACKLIST: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# ConvictionLevel — 5-point rating scale
# ---------------------------------------------------------------------------


class ConvictionLevel(IntEnum):
    """
    5-point conviction rating mapped from composite signal score.

    Score thresholds:
      > 0.6  → STRONG_BUY
      > 0.2  → BUY
      > -0.2 → HOLD
      > -0.6 → SELL
      else   → STRONG_SELL
    """

    STRONG_BUY = 2
    BUY = 1
    HOLD = 0
    SELL = -1
    STRONG_SELL = -2


# Position size multipliers relative to base position size.
# Sell/STRONG_SELL multipliers apply to the *short* position.
_CONVICTION_SIZE: dict[ConvictionLevel, float] = {
    ConvictionLevel.STRONG_BUY: 1.5,
    ConvictionLevel.BUY: 1.0,
    ConvictionLevel.HOLD: 0.0,
    ConvictionLevel.SELL: 0.5,
    ConvictionLevel.STRONG_SELL: 1.0,
}


def score_to_conviction(score: float) -> ConvictionLevel:
    """Map a composite signal score [-1, 1] to a ConvictionLevel."""
    if score > 0.6:
        return ConvictionLevel.STRONG_BUY
    elif score > 0.2:
        return ConvictionLevel.BUY
    elif score > -0.2:
        return ConvictionLevel.HOLD
    elif score > -0.6:
        return ConvictionLevel.SELL
    else:
        return ConvictionLevel.STRONG_SELL


def conviction_size_multiplier(conviction: ConvictionLevel) -> float:
    """Return the position size multiplier for a conviction level."""
    return _CONVICTION_SIZE[conviction]


class StrategyNode(Node):
    """
    Constructs portfolios and backtests strategies from trading signals.

    Capabilities : construct_portfolio, backtest_strategy, rank_signals
    Improves via : equal weight → momentum weight → risk parity → signal tuning

    Conviction filters (v1.4+):
      - Agreement ratio: ≥60% of sub-signals must agree on direction
      - Weighted conviction: IC-weighted composite must exceed threshold
      - Regime filter: SIDEWAYS/high-vol requires higher conviction
      - Time filter: no new positions within 2 cycles of last trade
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._weighting = "equal"  # "equal", "momentum", "risk_parity"
        self._signal_threshold = 0.0  # composite signal must exceed this to be included
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_sharpe = 0.0
        self._last_max_drawdown = 0.0
        self._last_hit_rate = 0.0
        self._backtest_count = 0

        # --- Conviction filter parameters ---
        # Agreement ratio disabled (set to 0.0) when cross-sectional demeaning is
        # active: in a bear market ALL sub-signals are negative, so "long" candidates
        # (those that are least-negative after demeaning) would have 0% sub-signal
        # agreement regardless of threshold.  The weighted_conviction_threshold
        # (0.10) serves as the quality gate instead.
        self._agreement_ratio_threshold: float = 0.0
        # IC-weighted conviction must exceed this in absolute value.
        # 0.10 — lowered from 0.20 because cross-sectional demeaning in
        # signal_generation.py centres composites around zero; demeaned values
        # are smaller in magnitude than raw composites, so the old 0.20 bar
        # would have blocked all trades even when genuine spread exists.
        self._weighted_conviction_threshold: float = 0.10
        # Per-direction regime-adaptive conviction thresholds.
        # Set each cycle by _apply_regime_adaptive_thresholds() based on detected regime:
        #   CRISIS/BEAR  → long=0.50 (heavily suppressed, V84), short=0.04 (permissive)
        #   BULL         → long=0.05 (permissive), short=0.20 (suppressed)
        #   NORMAL/other → long=0.13, short=0.10  (V59/V61)
        self._long_conviction_threshold: float = 0.10
        self._short_conviction_threshold: float = 0.10
        # Per-signal IC values loaded from signal_audit.py; empty = fall back to raw composite
        self._signal_ics: dict[str, float] = {}
        # Tracking counters
        self._proposals_generated: int = 0  # tickers that passed basic conviction screen
        self._proposals_filtered: int = 0  # tickers blocked by conviction filters
        # Absolute minimum conviction floor (V63): reject any signal below this regardless
        # of regime-adaptive thresholds.  Trade distribution shows most entries at 0.06–0.14;
        # V77: lowered from 0.12→0.02 — current market composites (0.03–0.05) require this;
        # V75/V76 produced only 2–3 trades with 0.12 floor vs ≥20 gate requirement.
        # Crisis short_thresh=0.02 is already the gating bar; floor matches it.
        # V79: raised 0.02→0.06 — V78 marginal ETH/BNB shorts entered at 0.064 conviction
        # and lost $0.5-$3.8 each; 0.02 floor was too permissive after _thresh_scale lowered
        # short_thresh to ~0.05 in low-basket-std markets.
        # V80: raised 0.06→0.07 — V78 analysis: all winning trades had conviction ≥ 0.078.
        # V81: lowered 0.07→0.06 — V80 run generated only high_vol shorts (all negative);
        # no normal/high_vol longs were generated because 0.07 floor combined with
        # basket_std scaling made long_thresh effectively 0.055 (very close to abs_min).
        # V78's winning floor was 0.078 but that was a bear market; current bull market
        # requires accepting slightly weaker long conviction to generate any entries.
        # V93: lowered 0.06→0.02 — post-crash recovery IC-weighted w_conv clusters at 0.02-0.04
        # (below 0.06 floor). abs_min was raised 0.02→0.06 in V81 for V78/V80 normal markets;
        # current basket_std=0.048 (vs V81 baseline ~0.20) makes the scaled long_thresh=0.017
        # already stricter than the abs_min. Lowering to 0.02 defers quality gating to the
        # IC-weighted conviction check (weighted_conviction >= long_thresh) which is now the
        # binding constraint.
        self._abs_min_conviction: float = 0.02
        # Time filter: don't open new positions within 2 cycles of last trade
        self._last_trade_cycle: int = -999
        # Regime state set each cycle by _apply_regime_adaptive_thresholds
        self._is_crisis: bool = False
        self._is_high_vol_regime: bool = False
        # Regime transition cooldown: skip new entries for 3 cycles after regime shifts
        self._last_regime: str = ""
        self._regime_change_cycle: int = -999
        # Zero-candidate streak: cycles since the last cycle with any trade candidates
        self._zero_candidate_streak: int = 0

        # --- Sit-out filter counters ---
        self._sit_out_regime_count: int = 0  # uncertain regime → 75% size reduction
        self._sit_out_vol_low_count: int = 0  # dead-calm vol → full sit-out
        self._sit_out_vol_high_count: int = 0  # chaotic vol → 50% size reduction
        self._normal_trade_count: int = 0  # cycles with full-size trading

        # --- Sit-out thresholds (mutable so circuit breaker can adapt them) ---
        self._vol_low_threshold: float = (
            0.0  # V55: disabled — abs_conviction_floor=0.15 is sufficient gate
        )
        # History: 0.20 (original) → 0.05 (V53, after reconnecting vol_rank) → 0.0 (V55).
        # V54: 200/200 cycles blocked because current market vol rank is below 5th pct of
        # its own 50d history. abs_conviction_floor handles low-signal environments.
        self._vol_high_threshold: float = 0.80  # percentile above which vol is "chaotic"

        # --- Multi-cycle confirmation (V63): track last 2 signal directions per symbol ---
        # Only enter a trade when the current direction matches the previous cycle's direction.
        # Prevents whipsaw entries on single-cycle signal spikes.
        # Values: "long" | "short" | "hold"
        self._signal_history: dict[str, list[str]] = {}
        # V75: track consecutive cycles where Fiedler regime is "fragmented"
        # Sustained fragmentation + moderate bear_prob = elevated crash risk ahead of HMM label
        self._fiedler_fragmented_streak: int = 0

        # --- Feature flags ---
        self.features: VictoriaFeatures = VictoriaFeatures.from_env()

        # --- Decision embedder (loaded once at init if flag is on) ---
        # Persistence path: data/decision_embeddings/embedder.pkl
        # Fit with: python -m omega.nodes.victoria.decision_embeddings --version <vN> --out data/decision_embeddings/embedder.pkl
        self._embedder: DecisionEmbedder | None = None
        if self.features.decision_embeddings:
            _embedder_pkl = Path("data/decision_embeddings/embedder.pkl")
            if _embedder_pkl.exists():
                try:
                    self._embedder = DecisionEmbedder.load(_embedder_pkl)
                except Exception as _e:
                    logger.warning(
                        "DecisionEmbedder: failed to load %s: %s — bias=0.0", _embedder_pkl, _e
                    )
            else:
                logger.info(
                    "DecisionEmbedder: no model at %s — bias=0.0 (first run; "
                    "fit with: python -m omega.nodes.victoria.decision_embeddings "
                    "--version <vN> --out %s)",
                    _embedder_pkl,
                    _embedder_pkl,
                )

        # --- Activation tracer (V107) — injected via init_tracer() ---
        self._tracer: Any = None

        # --- V133: paper trading engine reference for four-factor AND-gate ---
        # Set by run_training.py after the PaperTradingEngine is created so
        # FourFactorGate.evaluate() can read closed_trades, positions, and
        # initial_capital without polluting the signal/market_data dicts.
        self._paper_engine: Any = None
        # Last bias-adjusted w_conv from _passes_conviction_filters — used by activation trace
        # so we record the exact conviction value that passed, not a fresh bias-free recompute.
        self._last_w_conv: float = 0.0

        # --- Per-cycle decision traces (read by run_training.py → DecisionSnapshot) ---
        self._last_ticker_decisions: dict[str, TickerDecision] = {}

        # --- Observability extensions (gated by self.features) ---
        self._trace_writer: TraceWriter | None = None
        self._confluence: ConfluenceAnalyzer | None = (
            ConfluenceAnalyzer() if self.features.signal_confluence else None
        )
        self._last_confluence: dict[str, ConfluenceResult] = {}
        self._corr_monitor: SignalCorrelationMonitor | None = (
            SignalCorrelationMonitor() if self.features.signal_correlation_monitor else None
        )
        self._anomaly_detector: AnomalyDetector | None = None

        # --- Spectral graph / Fiedler position size modifier ---
        self._spectral = SpectralGraphSignal(window=30)
        self._last_fiedler_scale: float = 1.0
        self._last_fiedler_tag: str = "warmup"

        # --- Portfolio risk manager (drawdown, correlation, vol, time, heat) ---
        self._risk = PositionRiskManager()
        # Optional RMT denoiser reference for correlation-based position limits.
        # Set via set_rmt_denoiser() after construction (avoids circular imports).
        self._rmt_denoiser: Any = None

        # --- Kelly position sizing (V64) ---
        # Track rolling trade outcomes to compute win_rate, avg_win, avg_loss
        from collections import deque

        self._trade_history: deque = deque(maxlen=50)
        self._kelly_min_trades: int = 10  # minimum trades before using Kelly

    # ------------------------------------------------------------------ Kelly sizing

    def _kelly_fraction(self) -> float:
        """
        Compute half-Kelly fraction from recent trade history.

        kelly_f = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        Returns half-Kelly: kelly_f * 0.5, clipped to [0.2, 2.0] so it
        acts as a multiplier on base position size.
        Returns 1.0 (no adjustment) when insufficient history.
        """
        wins = [pnl for pnl in self._trade_history if pnl > 0]
        losses = [abs(pnl) for pnl in self._trade_history if pnl < 0]
        n = len(self._trade_history)
        if n < self._kelly_min_trades or not wins or not losses:
            return 1.0
        win_rate = len(wins) / n
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)
        if avg_win == 0:
            return 1.0
        kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        half_kelly = kelly_f * 0.5
        return max(0.2, min(2.0, half_kelly))

    def record_trade_pnl(self, pnl: float) -> None:
        """Record a closed trade's PnL for Kelly sizing."""
        self._trade_history.append(pnl)

    # ------------------------------------------------------------------ Observability API

    def init_trace_writer(self, version: str, output_dir: str = "data") -> None:
        """Initialise DecisionTrace writer and AnomalyDetector for this run.

        No-op when decision_traces and anomaly_detector flags are both OFF.
        Call once from run_training.py after constructing StrategyNode.
        """
        if self.features.decision_traces:
            self._trace_writer = TraceWriter(version=version, output_dir=output_dir)
            logger.info("StrategyNode: trace writer initialised for %s → %s", version, output_dir)
        if self.features.anomaly_detector:
            self._anomaly_detector = AnomalyDetector(version=version)

    def init_tracer(self, tracer: Any) -> None:
        """Inject an ActivationTracer (from signal_generation.py via VictoriaNode)."""
        self._tracer = tracer

    def init_reinforcer(self, reinforcer: Any) -> None:
        """Inject a TradeReinforcer so _apply_regime_adaptive_thresholds can read n_trades."""
        self._reinforcer = reinforcer

    def get_corr_matrix(self) -> dict:
        """Return the most recent signal correlation matrix (for Go API / dashboard)."""
        if self._corr_monitor is None:
            return {}
        return self._corr_monitor.get_matrix()

    def check_anomalies(
        self,
        cycle: int,
        pnl_delta: float,
        n_new_trades: int,
        zero_streak: int,
        basket_std: float = 0.0,
    ) -> list:
        """Delegate to AnomalyDetector. Returns list of AnomalyEvent (may be empty)."""
        if self._anomaly_detector is None:
            return []
        return self._anomaly_detector.check(
            cycle=cycle,
            pnl_delta=pnl_delta,
            n_new_trades=n_new_trades,
            zero_streak=zero_streak,
            basket_std=basket_std,
        )

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="StrategyNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "sharpe_ratio": self._last_sharpe,
                "max_drawdown": self._last_max_drawdown,
                "hit_rate": self._last_hit_rate,
                "proposals_generated": float(self._proposals_generated),
                "proposals_filtered": float(self._proposals_filtered),
                "filter_rate": self._filter_rate(),
            },
            metadata={
                "weighting": self._weighting,
                "signal_threshold": self._signal_threshold,
                "backtest_count": self._backtest_count,
                "agreement_ratio_threshold": self._agreement_ratio_threshold,
                "weighted_conviction_threshold": self._weighted_conviction_threshold,
                "long_conviction_threshold": self._long_conviction_threshold,
                "short_conviction_threshold": self._short_conviction_threshold,
                "signal_ic_count": len(self._signal_ics),
                "sit_out_regime": self._sit_out_regime_count,
                "sit_out_vol_low": self._sit_out_vol_low_count,
                "sit_out_vol_high": self._sit_out_vol_high_count,
                "normal_trade_cycles": self._normal_trade_count,
                "fiedler_scale": self._last_fiedler_scale,
                "fiedler_tag": self._last_fiedler_tag,
                **{f"risk_{k}": v for k, v in self._risk.get_metrics().items()},
            },
        )

    def get_capabilities(self) -> list[str]:
        return [
            NodeAction.CONSTRUCT_PORTFOLIO.value,
            NodeAction.BACKTEST_STRATEGY.value,
            NodeAction.RANK_SIGNALS.value,
        ]

    def describe(self) -> str:
        return (
            "Constructs investment portfolios from trading signals and backtests "
            "them against historical data. Supports equal-weight, momentum-weighted, "
            "and risk-parity-weighted portfolio construction. Self-improves by "
            "upgrading weighting scheme and tuning signal thresholds."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == NodeAction.CONSTRUCT_PORTFOLIO.value:
                signals = params.get("signals", {})
                market_data = params.get("market_data", {})
                result = self._construct_portfolio(signals, market_data)
            elif action == NodeAction.BACKTEST_STRATEGY.value:
                signals = params.get("signals", {})
                market_data = params.get("market_data", {})
                result = self._backtest(signals, market_data)
            elif action == NodeAction.RANK_SIGNALS.value:
                signals = params.get("signals", {})
                result = self._rank_signals(signals)  # type: ignore[assignment]
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed

            # Extract conviction distribution from result if available
            conviction_dist = (
                result.get("conviction_distribution", {}) if isinstance(result, dict) else {}
            )
            metrics: dict[str, Any] = {
                "latency_ms": elapsed,
                "sharpe_ratio": self._last_sharpe,
                "max_drawdown": self._last_max_drawdown,
                "hit_rate": self._last_hit_rate,
            }
            # Expose per-level conviction counts so Go can read them from step metrics
            for level_name, count in conviction_dist.items():
                metrics[f"conviction_{level_name.lower()}"] = float(count)

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics=metrics,
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("StrategyNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "sharpe_ratio": self._last_sharpe,
            "max_drawdown": self._last_max_drawdown,
            "hit_rate": self._last_hit_rate,
            "proposals_generated": float(self._proposals_generated),
            "proposals_filtered": float(self._proposals_filtered),
            "filter_rate": self._filter_rate(),
            "sit_out_regime": float(self._sit_out_regime_count),
            "sit_out_vol_low": float(self._sit_out_vol_low_count),
            "sit_out_vol_high": float(self._sit_out_vol_high_count),
            "normal_trade_cycles": float(self._normal_trade_count),
            "fiedler_scale": self._last_fiedler_scale,
            **{f"risk_{k}": float(v) for k, v in self._risk.get_metrics().items()},
        }

    def update_signal_ics(self, ics: dict[str, float]) -> None:
        """Load per-signal IC values from signal_audit output for weighted conviction."""
        self._signal_ics = {k: v for k, v in ics.items() if v > 0}
        logger.info(
            "StrategyNode: loaded ICs for %d signals (killed %d negative-IC)",
            len(self._signal_ics),
            sum(1 for v in ics.values() if v <= 0),
        )

    def set_rmt_denoiser(self, denoiser: Any) -> None:
        """
        Attach an RMTDenoiser instance for correlation-based position limits.

        Call this after construction to enable Layer 2 of the risk manager.
        Typically wired in victoria_node.py after both objects are created.
        """
        self._rmt_denoiser = denoiser
        logger.info("StrategyNode: RMT denoiser attached for correlation risk filtering")

    def update_risk_pnl(self, realized_pnl: float, unrealized_pnl: float = 0.0) -> None:
        """
        Update the risk manager's PnL tracking for drawdown protection.

        Call this each cycle with cumulative realised P&L so the drawdown
        halt can trigger appropriately.
        """
        self._risk.update_pnl(realized_pnl, unrealized_pnl)

    def risk_is_halted(self) -> bool:
        """Return True if max-drawdown protection has halted trading."""
        return self._risk.is_halted()

    def improve(self, feedback: dict[str, Any]) -> bool:
        # V57 froze this at equal weighting to diagnose V56's zero_streak. V58 post-mortem:
        # the zero_streak was caused by adv_spectral_graph inflating basket_std (fixed above),
        # not by the weighting upgrade. Re-enable the improvement arc.
        changed = False
        iteration = feedback.get("iteration", 0)

        # v1.1: Switch to momentum weighting after first iteration
        if self._weighting == "equal" and iteration >= 1:
            self._weighting = "momentum"
            self._version = "1.1"
            logger.info("StrategyNode → v1.1: momentum weighting enabled")
            changed = True

        # v1.2: Switch to risk-parity weighting after second iteration
        if self._weighting == "momentum" and iteration >= 2:
            self._weighting = "risk_parity"
            self._version = "1.2"
            logger.info("StrategyNode → v1.2: risk-parity weighting enabled")
            changed = True

        # v1.3: Tighten signal threshold if Sharpe is poor
        if self._version == "1.2" and self._last_sharpe < 0.5 and self._backtest_count >= 2:
            self._signal_threshold = min(0.3, self._signal_threshold + 0.1)
            self._version = "1.3"
            logger.info(
                "StrategyNode → v1.3: signal threshold tightened to %.2f (sharpe=%.2f)",
                self._signal_threshold,
                self._last_sharpe,
            )
            changed = True

        return changed

    # ------------------------------------------------------------------ conviction filters

    def _compute_agreement_ratio(self, signals_dict: dict) -> tuple[float, int, int]:
        """
        Count what fraction of directional sub-signals agree on direction.

        Returns (ratio, n_agreeing, n_total).  Direction is determined by the
        sign of `composite`; signals within ±0.1 of zero are treated as neutral
        and excluded from the denominator.
        """
        composite = float(signals_dict.get("composite", 0.0))
        directional: list[float] = []
        for k, v in signals_dict.items():
            if not (k.endswith("_signal") or k == "sma_crossover"):
                continue
            if not isinstance(v, (int, float)):
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv) or math.isinf(fv):
                continue
            if abs(fv) <= 0.1:
                continue  # neutral — skip
            directional.append(fv)

        total = len(directional)
        if total == 0:
            return 0.0, 0, 0

        if composite >= 0:
            agreeing = sum(1 for v in directional if v > 0)
        else:
            agreeing = sum(1 for v in directional if v < 0)

        return agreeing / total, agreeing, total

    def _compute_weighted_conviction(self, signals_dict: dict) -> float:
        """
        IC-weighted composite signal score.

        If no ICs have been loaded, falls back to the raw composite score so
        the filter still runs with equal weighting.
        """
        if not self._signal_ics:
            return float(signals_dict.get("composite", 0.0))

        weighted_sum = 0.0
        total_ic = 0.0
        for k, v in signals_dict.items():
            if not (k.endswith("_signal") or k == "sma_crossover"):
                continue
            ic = self._signal_ics.get(k, 0.0)
            if ic <= 0:
                continue  # skip killed / negative-IC signals
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv) or math.isinf(fv):
                continue
            weighted_sum += fv * ic
            total_ic += ic

        if total_ic == 0.0:
            return float(signals_dict.get("composite", 0.0))
        return weighted_sum / total_ic

    def _apply_regime_adaptive_thresholds(self, signals: dict) -> None:
        """Set per-direction conviction thresholds based on detected market regime.

        Called once per cycle at the start of _construct_portfolio so that long
        and short candidates are evaluated against regime-appropriate bars:

          CRISIS/BEAR  (bear_prob ≥ 0.55 or HMM == "bear")
            → long_threshold = 0.50  (longs heavily suppressed; V84: was 0.99 hard-block)
            → short_threshold = 0.04 (shorts permissive — trade the trend)

          BULL         (bull_prob ≥ 0.55 or HMM == "bull")
            → long_threshold = 0.05  (longs very permissive)
            → short_threshold = 0.20 (shorts suppressed)

          HIGH_VOL / NORMAL / unknown
            → balanced thresholds: long = short = 0.10
            (position size is already reduced 50% by the sit-out filter)
        """
        bear_prob = float(signals.get("_regime_w_bear_prob", -1.0))
        bull_prob = float(signals.get("_regime_w_bull_prob", -1.0))
        regime_hmm = str(signals.get("_regime_hmm", "")).lower()
        # _regime is the consolidated label (includes VRP "high_vol", HMM-derived "crisis", etc.)
        # _regime_hmm is the raw HMM label (only "bull"/"bear"/"sideways").
        # Use _regime for high_vol detection since that's where the VRP FEAR→high_vol mapping lands.
        regime_label = str(signals.get("_regime", "")).lower()

        # V53: also treat HMM vol-regime "crisis" as crisis even if Wasserstein is flat
        # (Wasserstein can return 1/3 priors when its signal keys don't match the signal dict).
        # V91: raise bear_prob crisis threshold 0.55→0.65 — April 2026 post-crash recovery
        # has bear_prob oscillating 0.55–0.62, triggering false crisis labels. ETH shows
        # +0.19 BUY (strongest signal) exactly when bear_prob crosses 0.55, but longs are
        # blocked. Genuine crashes (initial shock) push bear_prob to 0.70+. Raising to 0.65
        # allows recovery longs at bear_prob 0.55–0.64 while keeping hard lock for ≥0.65.
        # V95: gate regime_hmm/regime_label "crisis" paths with bear_prob >= 0.45.
        # Root cause: HMM transitions slowly; post-April-7-crash HMM stays "crisis" for 30+
        # cycles while bear_prob=0.31–0.38 (market probability already pricing recovery).
        # Requiring bear_prob >= 0.45 for HMM/label-based crisis ensures the probability
        # model confirms genuine crisis before blocking all longs. bear_prob >= 0.65 still
        # hard-blocks unconditionally. This replaces V94 (no-op — same code as V93).
        if self.features.v96_crisis_detection_fix:
            # elastic-buck: when bear_prob=-1 (unavailable), trust regime label directly.
            # V95's >= 0.45 gate only applies when bear_prob is actually available.
            is_crisis = (
                bear_prob >= 0.65
                or (bear_prob < 0.0 and (regime_hmm == "bear" or regime_label == "crisis"))
                or (bear_prob >= 0.0 and regime_hmm == "crisis" and bear_prob >= 0.45)
                or (bear_prob >= 0.0 and regime_label == "crisis" and bear_prob >= 0.45)
            )
        else:
            is_crisis = (
                bear_prob >= 0.65
                or (bear_prob < 0.0 and regime_hmm == "bear")
                or (regime_hmm == "crisis" and bear_prob >= 0.45)
                or (regime_label == "crisis" and bear_prob >= 0.45)
            )
        self._is_crisis = is_crisis
        self._is_high_vol_regime = regime_label == "high_vol"
        is_bull = (
            bull_prob >= 0.55 or (bull_prob < 0.0 and regime_hmm == "bull")
        ) and not is_crisis

        # V60: detect high_vol from consolidated _regime label (VRP FEAR maps to "high_vol").
        # _regime_hmm only carries "bull"/"bear"/"sideways" — never "high_vol".
        # is_high_vol computed per-ticker in _passes_conviction_filters as _is_high_vol

        if is_crisis:
            # V53: raise to 0.99 to hard-block all longs in crisis.
            # V52 post-mortem: 22 crisis longs → -$100.62 (ETH/AVAX momentum chasing).
            # V65: lower short_thresh 0.05→0.02 — V63 shorts earned $7.63/trade vs
            # $0.97/trade for longs; crisis regime inherently favors shorts.
            # V72: hard-block longs in all crisis scenarios; bounce guard raises short_thresh
            # when FGI > 0.25 (extreme fear = contrarian signal = panic-short suppression).
            # V71 mistake: enabling longs at 0.30 in crisis — those longs close in "normal"
            # regime and appear as normal-regime losses (-$145.61). Keep longs blocked.
            _fg_val = (
                next(
                    (
                        v.get("fear_greed_signal", 0.0)
                        for k, v in signals.items()
                        if not k.startswith("_")
                        and isinstance(v, dict)
                        and "fear_greed_signal" in v
                    ),
                    0.0,
                )
                or 0.0
            )
            # V84: lower from 0.99 (hard-block) to 0.50 — 0.99 combined with _thresh_scale
            # inflates to 1.88, making longs mathematically impossible even for exceptionally
            # strong signals. 0.50 still blocks weak/moderate crisis longs but allows through
            # genuinely high-conviction signals (FGI=8 confirms real crisis, not detection error).
            # Post-_thresh_scale cap (1.5): effective ceiling = 0.50 * 1.5 = 0.75.
            self._long_conviction_threshold = 0.50
            if _fg_val > 0.25:
                # Bounce guard: extreme fear → suppress new shorts (raise bar to 0.10)
                self._short_conviction_threshold = 0.10
                logger.info(
                    "Regime-adaptive: CRISIS/BEAR+EXTREME_FEAR (bear_prob=%.2f, fear_greed=%.3f) "
                    "→ long_thresh=0.99 (hard-block), short_thresh=0.10 (bounce guard, V72)",
                    max(bear_prob, 0.0),
                    _fg_val,
                )
            else:
                # V79: raise crisis short_thresh 0.02→0.04 — V78 crisis shorts lost on
                # dead-cat bounces (SOL +0.1% during "crisis" cycles 90-105). 0.02 is too
                # permissive; 0.04 still captures genuine crisis shorts while filtering
                # near-zero composites that reflect noise, not real bearish momentum.
                self._short_conviction_threshold = 0.04
                logger.info(
                    "Regime-adaptive: CRISIS/BEAR (bear_prob=%.2f, hmm=%s, fear_greed=%.3f) "
                    "→ long_thresh=0.99, short_thresh=0.04",
                    max(bear_prob, 0.0),
                    regime_hmm,
                    _fg_val,
                )
        elif is_bull:
            self._long_conviction_threshold = 0.05
            self._short_conviction_threshold = 0.20
            logger.info(
                "Regime-adaptive: BULL (bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.05, short_thresh=0.20",
                max(bull_prob, 0.0),
                regime_hmm,
            )
        else:
            # V59: raise normal long_thresh 0.10→0.13 — V58 had 37% WR on normal longs.
            # V61: raise normal short_thresh 0.05→0.10 — V59 DOT normal shorts lost -$28.93
            #   (36 trades, 30% WR); marginal short signals not credible in normal regime.
            #   DOT high_vol/crisis shorts remain active via lower thresholds in those branches.
            #   ETH longs stay fully enabled (no high_vol blacklist — V59 ETH WR=50%).
            # V79: raise normal long_thresh 0.13→0.15 — V78 ADA long had w_conv=0.141
            #   (barely above 0.13) and lost -$29.17; raising to 0.15 filters that entry
            #   while preserving the winning ADA long at w_conv=0.254.
            # V79: lower normal short_thresh 0.10→0.08 — V78 had 38-cycle zero streaks in
            #   normal regime where composites ranged -0.08 to -0.09; lowering captures the
            #   clean short signals that V61's 0.10 floor was blocking. V78 normal shorts
            #   had 60%+ WR vs V59's 30% — market is more directionally bearish now.
            # V83: lower normal long_thresh 0.15→0.10 — V81/V82 show zero longs in normal
            #   regime because ETH/BNB/LINK composites cluster at 0.08–0.12 (below 0.15 bar).
            #   ADAUSDT is in _LONG_BLACKLIST and AVAXUSDT is in _TRADING_BLACKLIST, removing
            #   the previously troublesome longs (ADA -$29.17, AVAX -$15.28). With those
            #   filtered structurally, 0.10 lets ETH/BNB longs through (V75 ETH long WR=67%).
            # V88: lower normal long_thresh 0.10→0.07 — V87 zero_streak=122 at cycle 100;
            #   ETH conviction hovers at +0.02–0.07 in post-crash recovery but never reached
            #   0.10. With BNB/LINK/AVAX/SOL blacklisted, ETH is the sole long candidate.
            #   V87 ETH winning long opened at ~0.07 conviction. Lowering bar to 0.07 captures
            #   the recovery-phase ETH longs that 0.10 misses.
            # V86: raise 0.07→0.10 — caused max_zero_streak=150, only 8 trades in 200 cycles.
            #   Reverting: 0.10 was already tried in V83→V88 history and required 0.07 for
            #   post-crash recovery conviction levels. ADA re-enablement does not change the
            #   required threshold — ETH/ADA composites both cluster 0.02–0.09 in recovery.
            # V87: revert to 0.07 — preserves trade volume while ADA diversity is active.
            self._long_conviction_threshold = 0.07
            # V85: lower 0.08→0.05 — V84 had 0 shorts in 200 cycles (ETH declining -0.43%).
            # Normal composites cluster ±0.04–0.08; 0.08 was blocking all short signals.
            # V86: raise 0.05→0.07 — slight increase to reduce noise shorts; still well below
            #   V84's 0.08 which blocked all shorts entirely.
            # V94: lower 0.07→0.05 — V92/V93 generated only 3/6 shorts across 200 cycles.
            #   Post-mortem: demeaned composites for short candidates cluster at -0.05 to -0.07,
            #   exactly where the 0.07 floor was blocking them. Lowering to 0.05 captures the
            #   cross-sectional underperformers that demeaning naturally produces.
            # V95: revert 0.05→0.07 — V94 forensics showed only 3 shorts in 200 cycles
            #   (fewer than V93's 6) and the WR/PnL loss was from crisis-labeled longs
            #   (opened in normal regime, closed during market decline), not from shorts.
            #   The short_thresh reduction had no measurable positive effect; reverting to
            #   V88's stable 0.07 which was specifically calibrated to reduce noise shorts.
            self._short_conviction_threshold = 0.07
            logger.debug(
                "Regime-adaptive: NORMAL (bear_prob=%.2f, bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.10, short_thresh=0.07 (V95)",
                max(bear_prob, 0.0),
                max(bull_prob, 0.0),
                regime_hmm,
            )

        # V95: Geodesic crash proximity gate — when the market manifold is closer to
        # the crash reference state than the rally state, raise long_thresh proportionally.
        # Geodesic distance is computed in signal_generation.py (MarketManifold) and
        # injected as _geometry_geo_dist_crash / _geometry_geo_dist_rally in signals.
        # When crash_dist < rally_dist the market's return distribution is closer to the
        # crisis regime (negative drift, high variance, negative skew); we suppress longs
        # without hard-blocking (that's what _block_longs=True does in confirmed crisis).
        # Crash proximity = 1 - crash_dist/(crash_dist + rally_dist): 1.0 = at crash, 0.0 = at rally.
        # Raise long_thresh by up to 40% when proximity ≥ 0.6.  Only applies when not already
        # in hard crisis (where _long_conviction_threshold is already 0.50).
        if self.features.geodesic_crash_distance and not is_crisis:
            _geo_crash = float(signals.get("_geometry_geo_dist_crash", -1.0))
            _geo_rally = float(signals.get("_geometry_geo_dist_rally", -1.0))
            if _geo_crash >= 0.0 and _geo_rally >= 0.0 and (_geo_crash + _geo_rally) > 1e-6:
                _crash_prox = 1.0 - _geo_crash / (_geo_crash + _geo_rally)
                if _crash_prox >= 0.6:
                    _geo_scale = 1.0 + 0.4 * (_crash_prox - 0.6) / 0.4  # linear 1.0→1.4
                    _geo_scale = min(_geo_scale, 1.4)
                    _prev_long = self._long_conviction_threshold
                    self._long_conviction_threshold *= _geo_scale
                    logger.info(
                        "V95 geodesic gate: crash_prox=%.3f geo_scale=%.2f long_thresh %.4f→%.4f",
                        _crash_prox,
                        _geo_scale,
                        _prev_long,
                        self._long_conviction_threshold,
                    )

        # V102: crisis_short_bias threshold layer — applied after all other threshold logic.
        # In crisis/high_vol: lower short bar 40%, raise long bar 50%.
        # In normal: cap short_thresh at 0.05 to catch cross-sectional underperformers.
        if self.features.crisis_short_bias:
            if self._is_crisis or self._is_high_vol_regime:
                _old_short = self._short_conviction_threshold
                _old_long = self._long_conviction_threshold
                self._short_conviction_threshold = _old_short * 0.60
                self._long_conviction_threshold = min(_old_long * 1.50, 0.99)
                logger.info(
                    "crisis_short_bias: %s → short_thresh %.4f→%.4f, long_thresh %.4f→%.4f",
                    "crisis" if self._is_crisis else "high_vol",
                    _old_short,
                    self._short_conviction_threshold,
                    _old_long,
                    self._long_conviction_threshold,
                )
            elif not is_bull:  # normal regime
                _old_short = self._short_conviction_threshold
                _new_short = min(_old_short, 0.05)
                if _new_short < _old_short:
                    self._short_conviction_threshold = _new_short
                    logger.info("crisis_short_bias: normal → short_thresh %.4f→0.05", _old_short)

        # V110: reinforcement threshold reduction — when reinforcement has 50+ trades of
        # history, lower both thresholds 20%. Reinforcement already filters bad signals via
        # weight dampening, so a lower threshold doesn't increase risk — it restores trade
        # volume that dampened signals inadvertently suppress.
        if self.features.trade_reinforcement:
            _reinf = getattr(self, "_reinforcer", None)
            if _reinf is not None and getattr(_reinf, "_n_trades", 0) >= 50:
                self._long_conviction_threshold *= 0.80
                self._short_conviction_threshold *= 0.80
                logger.debug(
                    "Reinforcement threshold reduction (n=%d): long=%.3f short=%.3f",
                    _reinf._n_trades,
                    self._long_conviction_threshold,
                    self._short_conviction_threshold,
                )

    def _passes_conviction_filters(
        self, sig: dict, cycle: int, direction: str = "long"
    ) -> tuple[bool, str]:
        """
        Return (passes, reason) for the full conviction filter stack.

        Filters applied in order:
          1. Time filter  — no new trades within 2 cycles of last
          2. Agreement ratio — ≥ threshold of sub-signals agree on direction
          3. Weighted conviction — IC-weighted composite exceeds threshold
          4. Regime / volatility — higher bar in high-vol regime
        """
        # 1. Time filter
        if cycle - self._last_trade_cycle < 2:
            return False, "time_filter"

        # 2. Agreement ratio (disabled in V84)
        # V83 post-mortem: hardcoded 0.7 agreement threshold for vol_regime="high" was
        # blocking ALL trades in the post-crash recovery period. Sub-signals are mixed
        # (momentum BUY vs macro bearish SELL) even when composite direction is clear.
        # V55 disabled agreement_ratio universally (abs_conviction is the quality gate);
        # V84 restores that — use self._agreement_ratio_threshold (0.0 = disabled) only.
        # The 1.25x conviction multiplier for vol_regime="high" still applies below.
        _vol_regime = sig.get("vol_regime", "normal")
        ratio, _agreeing, _total = self._compute_agreement_ratio(sig)
        if _total > 0 and ratio < self._agreement_ratio_threshold:
            return False, f"agreement_ratio({ratio:.2f}<{self._agreement_ratio_threshold:.2f})"

        # 3. Weighted conviction — use per-direction regime-adaptive threshold.
        # _apply_regime_adaptive_thresholds() sets these each cycle before the
        # per-ticker loop so CRISIS → lower short bar, BULL → lower long bar.
        w_conv = self._compute_weighted_conviction(sig)
        # 3a-embed: V101 Track C — apply cluster bias from fitted DecisionEmbedder.
        # bias ∈ [-0.5, +0.5]; adjusted = w_conv * (1.0 + bias).
        # Falls back to bias=0.0 when no model is loaded (first run or deps missing).
        if self.features.decision_embeddings and self._embedder is not None:
            _sig_vals = {k: float(v) for k, v in sig.items() if isinstance(v, (int, float))}
            _regime_for_embed = "crisis" if self._is_crisis else sig.get("vol_regime", "normal")
            _bias = self._embedder.cluster_bias(
                signal_values=_sig_vals,
                regime=_regime_for_embed,
                conviction_score=abs(w_conv),
            )
            _adjusted = w_conv * (1.0 + _bias)
            logger.debug(
                "Embedding bias (%s %s): w_conv=%.4f bias=%.3f → %.4f",
                sig.get("symbol", "?"),
                direction,
                w_conv,
                _bias,
                _adjusted,
            )
            w_conv = _adjusted
        # 3a. Absolute minimum conviction floor: regime-dependent (V80/V81 fix).
        # Normal/high_vol: use abs_min_conviction (0.06 as of V81) — calibrated on V78/V80 data.
        # Crisis shorts: use crisis short_thresh (0.04) — the floor was negating the V77
        # crisis bypass. V79 post-mortem: 19-cycle zero streak in sustained crisis because all
        # signals with w_conv 0.04–0.07 were blocked by the floor despite the 0.04 threshold.
        if self._is_crisis and direction == "short":
            _effective_floor = self._short_conviction_threshold  # 0.04 in crisis
        else:
            _effective_floor = self._abs_min_conviction  # 0.06 in normal/high_vol (V81)
        if abs(w_conv) < _effective_floor:
            return False, f"abs_min_conviction({abs(w_conv):.2f}<{_effective_floor:.2f})"
        base_threshold = (
            self._long_conviction_threshold
            if direction == "long"
            else self._short_conviction_threshold
        )
        # V85: remove per-ticker vol_regime="high" 1.25x multiplier. Post-crash markets have
        # elevated realized vol on all tickers simultaneously, causing double-filtering:
        # basket-level "high_vol" regime detection already handles the market-level signal,
        # and the per-ticker 1.25x raises thresholds (0.08→0.10) above composites that are
        # still directionally valid (e.g. ETH -0.08 blocked at conv_threshold=0.10).
        # V84's zero_streak=30 was caused by this multiplier blocking all non-blacklisted
        # tickers in the post-crash recovery period. Base thresholds are the quality gate.
        conv_threshold = base_threshold
        if abs(w_conv) < conv_threshold:
            return False, f"weighted_conviction({abs(w_conv):.2f}<{conv_threshold:.2f})"

        # V107: stash the final w_conv (with embedding bias applied) so activation_trace
        # can use the exact value that passed the filter, not a fresh (bias-free) recompute.
        self._last_w_conv = w_conv
        return True, "pass"

    # ------------------------------------------------------------------ spectral / Fiedler

    @staticmethod
    def _fiedler_size_scale(zscore: float, regime_tag: str) -> float:
        """
        Convert Fiedler z-score to a position size multiplier in [0.25, 1.0].

        Interpretation:
          - "warmup"     → 1.0 (no history yet; don't penalise)
          - "fragmented" → 0.25 (graph disconnected; maximum stress)
          - Otherwise: linear decay from 1.0 at z=0 down to 0.25 at z≤−5
            scale = 1.0 + 0.15 * zscore, clamped to [0.25, 1.0]
            Consensus (z > 0) is capped at 1.0 — no leverage bonus.
        """
        if regime_tag == "warmup":
            return 1.0
        if regime_tag == "fragmented":
            return 0.25
        return max(0.25, min(1.0, 1.0 + 0.15 * zscore))

    def _build_spectral_vector(self, signals: dict[str, Any]) -> dict[str, float]:
        """
        Extract the cross-signal category vector for the spectral graph.

        victoria_node.py places each signal module's output as a top-level key in
        the signals dict under its SIGNAL_NAMES identifier (e.g. "basic_signals",
        "order_flow", "cross_asset", …).  Each entry is a dict with a "value" field.

        The spectral graph builds a Laplacian of the correlation network of these
        signal categories over time.  When all signal types agree (high |corr|) →
        high Fiedler → consensus.  When they diverge → low Fiedler → stress.

        Falls back to 0.0 for signal categories not yet computed (warmup / PICO mode).
        """
        from omega.nodes.victoria.information_flow import SIGNAL_NAMES

        result: dict[str, float] = {}
        for name in SIGNAL_NAMES:
            sig_cat = signals.get(name)
            if isinstance(sig_cat, dict):
                val = sig_cat.get("value", 0.0)
                try:
                    f = float(val)
                    result[name] = f if not (math.isnan(f) or math.isinf(f)) else 0.0
                except (TypeError, ValueError):
                    result[name] = 0.0
            else:
                result[name] = 0.0
        return result

    # ------------------------------------------------------------------ sit-out filters

    def _vol_percentile_rank(
        self, prices: list[float], window: int = 20, lookback: int = 100
    ) -> float:
        """
        Return the percentile rank (0-1) of the current window vol within the
        last `lookback` candles.  Returns 0.5 (neutral) if insufficient data.
        """
        if len(prices) < lookback + 1:
            return 0.5

        obs: list[float] = []
        start = max(window + 1, len(prices) - lookback)
        for i in range(start, len(prices)):
            rets = [
                (prices[j] - prices[j - 1]) / prices[j - 1]
                for j in range(i - window + 1, i + 1)
                if prices[j - 1] != 0
            ]
            if len(rets) < 2:
                continue
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            obs.append(math.sqrt(var))

        if not obs:
            return 0.5

        current_vol = obs[-1]
        return sum(1 for v in obs if v <= current_vol) / len(obs)

    def _check_sit_out(
        self, signals: dict[str, Any], market_data: dict[str, Any]
    ) -> tuple[str, float]:
        """
        Check whether market conditions warrant reducing or skipping trades.

        Returns (reason, size_multiplier):
          "vol_low"          → 0.0   (dead-calm market, sit out entirely)
          "regime_uncertain" → 0.25  (no dominant regime, 75% size reduction)
          "vol_high"         → 0.50  (chaotic market, 50% size reduction)
          "normal"           → 1.0

        Vol check takes priority; extreme vol is more dangerous than regime uncertainty.
        """
        # ── Volatility-based check ──────────────────────────────────────────
        vol_rank: float | None = None
        for _ticker, data in market_data.items():
            if not isinstance(data, dict):
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) >= 101:
                vol_rank = self._vol_percentile_rank(prices, window=20, lookback=100)
                break

        if vol_rank is not None:
            if vol_rank < self._vol_low_threshold:
                return "vol_low", 0.0
            if vol_rank > self._vol_high_threshold:
                return "vol_high", 0.50

        # ── Regime uncertainty check ────────────────────────────────────────
        regime_probs: list = signals.get("_regime_probs", [])
        if regime_probs and len(regime_probs) >= 3:
            max_prob = max(float(p) for p in regime_probs[:3])
            if max_prob < 0.50:
                bull_p = float(regime_probs[0])
                bear_p = float(regime_probs[1])
                side_p = float(regime_probs[2])
                logger.info(
                    "Market uncertain (bull %.0f%%, bear %.0f%%, sideways %.0f%%) "
                    "— reducing position size 75%%",
                    bull_p * 100,
                    bear_p * 100,
                    side_p * 100,
                )
                return "regime_uncertain", 0.25

        return "normal", 1.0

    # ------------------------------------------------------------------ portfolio construction

    def _construct_portfolio(
        self, signals: dict[str, Any], market_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Build portfolio weights from signals using conviction-scaled sizing.

        Applies conviction threshold filters before building candidates:
          - Agreement ratio: ≥60% of sub-signals must agree on direction
          - Weighted conviction: IC-weighted composite must exceed threshold
          - Regime filter: higher bar in high-volatility regimes
          - Time filter: no new positions within 2 cycles of last trade
        """
        current_cycle = self._execution_count
        self._last_ticker_decisions = {}  # reset each cycle
        self._last_confluence = {}  # reset confluence cache each cycle

        # Set per-direction conviction thresholds based on current regime.
        # CRISIS/BEAR → shorts get lower bar (0.05), longs get higher bar (0.20).
        # BULL → longs get lower bar (0.05), shorts get higher bar (0.20).
        # NORMAL → balanced (0.10 each).
        self._apply_regime_adaptive_thresholds(signals)

        # V65/V66: detect regime for per-ticker filters (ETH/BNB long suppression).
        # Use the consolidated _regime label — _regime_hmm never carries "high_vol".
        _regime_consolidated = str(signals.get("_regime", "")).lower()
        _is_high_vol = _regime_consolidated == "high_vol"
        # V79: include "sideways" (HMM label for normal market) in the is_normal check.
        # Previously "sideways" ≠ "normal" so SOL/BNB/ETH suppressions were bypassed
        # when Wasserstein regime returned "sideways" instead of "normal".
        _is_normal = _regime_consolidated in ("normal", "sideways")

        # --- Relative conviction threshold calibration (V45) ---
        # After cross-sectional demeaning, composites are typically 0.01–0.05 in magnitude.
        # Absolute thresholds (±0.20 HOLD band, 0.10 weighted-conviction gate) swallow the
        # entire range and produce 99% HOLD cycles.  Scale ALL thresholds proportionally to
        # the basket composite std so that 0.5σ → BUY regardless of absolute scale.
        #
        # V58: exclude adv_* synthetic aggregates from basket_std computation.
        # adv_order_flow, adv_cross_asset, adv_spectral_graph etc. are created by
        # adapt_signals() from signal category "value" fields.  SpectralGraphSignal
        # outputs raw Fiedler z-scores (unclamped, can be ±5+), which inflate
        # basket_std once the 15-cycle warmup ends — collapsing _cs_norm and
        # making every per-ticker composite map to HOLD.  Only real per-ticker
        # composites (ETHUSDT, DOTUSDT, etc.) should anchor the basket std.
        _composites_for_std = [
            float(sig["composite"])
            for t, sig in signals.items()
            if not t.startswith("_")
            and not t.startswith("adv_")
            and isinstance(sig, dict)
            and "composite" in sig
        ]
        if len(_composites_for_std) >= 2:
            _c_mean = sum(_composites_for_std) / len(_composites_for_std)
            _basket_std = math.sqrt(
                sum((v - _c_mean) ** 2 for v in _composites_for_std) / len(_composites_for_std)
            )
        else:
            _basket_std = 0.20  # fallback: no rescaling
        _basket_std = max(
            _basket_std, 0.010
        )  # floor prevents degenerate rescaling (V48: 0.005→0.010)

        # Normalisation factor: composite × _cs_norm before score_to_conviction so that
        # ±0.3σ → ±0.20 (BUY/SELL boundary) and ±0.9σ → ±0.60 (STRONG_BUY/SELL).
        # V48: widened bands from 0.5σ→0.3σ to reduce HOLD cycles (V47 had 66% HOLD).
        _cs_norm = 0.20 / (0.3 * _basket_std)

        # Scale secondary gate thresholds by the same factor (preserves regime ratios).
        # V84: cap _thresh_scale at 1.5 — prevents threshold inflation in high-vol markets.
        # With basket_std=0.38 (April 2026 crisis), uncapped scale=1.9 inflates crisis
        # long_thresh from 0.50→0.95 and short_thresh from 0.04→0.076, blocking all trades.
        # Cap at 1.5 means max 50% above base: long_thresh→0.75, short_thresh→0.06.
        _thresh_scale = min(_basket_std / 0.20, 1.5)
        self._weighted_conviction_threshold = 0.10 * _thresh_scale
        self._long_conviction_threshold *= _thresh_scale
        self._short_conviction_threshold *= _thresh_scale

        logger.info(
            "V45 relative thresholds: basket_std=%.4f cs_norm=%.2f "
            "long_thresh=%.4f short_thresh=%.4f wc_thresh=%.4f",
            _basket_std,
            _cs_norm,
            self._long_conviction_threshold,
            self._short_conviction_threshold,
            self._weighted_conviction_threshold,
        )

        # --- V102: crisis_short_bias threshold adjustments ---
        # Applied after _thresh_scale so multipliers act on final effective thresholds.
        if self.features.crisis_short_bias:
            if _regime_consolidated in ("crisis", "high_vol"):
                _pre_short = self._short_conviction_threshold
                _pre_long = self._long_conviction_threshold
                self._short_conviction_threshold *= 0.6
                self._long_conviction_threshold *= 1.5
                logger.info(
                    "crisis_short_bias: fear regime %s — short_thresh %.4f→%.4f "
                    "long_thresh %.4f→%.4f",
                    _regime_consolidated,
                    _pre_short,
                    self._short_conviction_threshold,
                    _pre_long,
                    self._long_conviction_threshold,
                )
            else:
                # Normal: cap short bar at 0.05 to build short trade history
                _pre_short = self._short_conviction_threshold
                _new_short = min(self._short_conviction_threshold, 0.05)
                if _new_short < _pre_short:
                    self._short_conviction_threshold = _new_short
                    logger.debug(
                        "crisis_short_bias: normal short_thresh %.4f→0.05",
                        _pre_short,
                    )

        # --- Regime transition cooldown (V92) ---
        # Skip new entries for 3 cycles after a regime shift to avoid entering on stale signals.
        _current_regime_for_cooldown = "crisis" if self._is_crisis else _regime_consolidated
        if _current_regime_for_cooldown != self._last_regime and self._last_regime != "":
            logger.info(
                "Regime transition cooldown: %s → %s, skipping entries for 3 cycles",
                self._last_regime,
                _current_regime_for_cooldown,
            )
            self._regime_change_cycle = current_cycle
        self._last_regime = _current_regime_for_cooldown
        _in_cooldown = (current_cycle - self._regime_change_cycle) < 3

        # Compute conviction for every ticker with a composite score
        # Skip metadata keys (_regime_probs, _regime_hmm, etc.)
        convictions: dict[str, ConvictionLevel] = {}
        for ticker, sig in signals.items():
            if ticker.startswith("_") or not isinstance(sig, dict):
                continue
            composite = sig.get("composite")
            if composite is not None:
                convictions[ticker] = score_to_conviction(float(composite) * _cs_norm)

        # --- Regime directional filter ---
        # Block longs in confirmed bear regimes and shorts in confirmed bull regimes.
        # Regime info is embedded in the signals dict by the signal computation pipeline.
        _regime_hmm: str = str(signals.get("_regime_hmm", signals.get("_regime", ""))).lower()
        _regime_probs: list = signals.get("_regime_probs", [])
        _regime_confidence: float = 0.0
        if _regime_probs and len(_regime_probs) >= 3:
            if _regime_hmm == "bear":
                _regime_confidence = float(_regime_probs[1])
            elif _regime_hmm == "bull":
                _regime_confidence = float(_regime_probs[0])
            elif _regime_hmm == "sideways":
                _regime_confidence = float(_regime_probs[2])

        # Continuous regime probability scaling: use raw bear/bull probabilities to scale
        # position weights proportionally. Fall back to binary blocking at 35% if keys absent.
        # victoria_node.py writes _regime_w_bear_prob / _regime_w_bull_prob (Wasserstein output);
        # accept both names for backward compatibility.
        _regime_w_bear: float = float(
            signals.get("_regime_w_bear_prob", signals.get("_regime_w_bear", -1.0))
        )
        _regime_w_bull: float = float(
            signals.get("_regime_w_bull_prob", signals.get("_regime_w_bull", -1.0))
        )
        _use_continuous_regime = _regime_w_bear >= 0.0 and _regime_w_bull >= 0.0
        if _use_continuous_regime:
            _block_longs = False
            _block_shorts = False
            logger.info(
                "Regime scaling: bear=%.2f, bull=%.2f",
                _regime_w_bear,
                _regime_w_bull,
            )
        else:
            # Fallback: binary block at 35% threshold (no Wasserstein probs available)
            _regime_confidence_threshold = 0.35
            _block_longs = (
                _regime_hmm == "bear" and _regime_confidence >= _regime_confidence_threshold
            )
            _block_shorts = (
                _regime_hmm == "bull" and _regime_confidence >= _regime_confidence_threshold
            )
        # V80: crisis regime always hard-blocks longs regardless of the regime detection path.
        # In production (continuous-regime), long_thresh=0.99 is the effective block.
        # In tests/binary-fallback (no Wasserstein probs), _block_longs must be forced True
        # so composite=1.0 doesn't slip through the 0.99 threshold.
        if self._is_crisis:
            _block_longs = True

        # --- Fiedler spectral position size modifier (computed early for all paths) ---
        # λ₂ of the signal correlation graph Laplacian — low = signals fragmenting.
        _sv = self._build_spectral_vector(signals)
        _spectral_val = self._spectral.compute(_sv)
        _fiedler_scale = self._fiedler_size_scale(_spectral_val.value, _spectral_val.regime_tag)
        self._last_fiedler_scale = _fiedler_scale
        self._last_fiedler_tag = _spectral_val.regime_tag

        # V75: Fiedler-fragmented streak tracker + elevated long threshold.
        # When signals are persistently fragmented (30+ consecutive cycles) AND bear_prob is
        # moderately elevated (>0.25), raise the long conviction threshold from 0.10 to 0.25.
        # V74 post-mortem: Fiedler was "fragmented" (scale=0.25) from cycle 15 onwards while
        # bear_prob sat at 0.29–0.30. The standard threshold 0.10 allowed 7 losing longs in
        # "normal" regime before the HMM finally labelled the crash as "crisis" at cycle ~130.
        # Sustained fragmentation + moderate bear = early crash indicator the HMM misses.
        # V89: reset streak when HMM labels crisis — Fiedler is an EARLY WARNING system for
        # pre-crisis detection. Once HMM reaches crisis, _block_longs handles long suppression.
        # Accumulating the streak through crisis then carrying it into recovery causes the
        # post-crash normal phase to inherit a stale 30+ cycle streak, locking long_thresh at
        # 0.25 indefinitely and producing zero trades in recovery. Reset each crisis cycle.
        if self._is_crisis:
            self._fiedler_fragmented_streak = 0
        elif _spectral_val.regime_tag == "fragmented":
            self._fiedler_fragmented_streak += 1
        else:
            self._fiedler_fragmented_streak = 0

        # V92: raise bear_prob threshold 0.25→0.40 — post-crash recovery (bear≈0.31) was
        # repeatedly triggering Fiedler suppression despite V89's crisis-reset fix. Streak
        # resets to 0 during crisis then re-accumulates in NORMAL recovery, hitting 30 cycles
        # again with bear_weight=0.308-0.311 (above 0.25). At 0.40 threshold, recovery phase
        # (bear<0.40) doesn't suppress; genuine pre-crash bearish conviction (bear>0.40) still
        # triggers. V74 scenario (bear 0.29-0.30) now protected by 2-cycle confirmation instead.
        _fiedler_bear_long_suppress = (
            self._fiedler_fragmented_streak >= 30 and _regime_w_bear > 0.40
        )
        if _fiedler_bear_long_suppress and not self._is_crisis:
            self._long_conviction_threshold = max(self._long_conviction_threshold, 0.25)
            logger.info(
                "V75: Fiedler-fragmented(%d cycles)+bear(%.2f) → long_thresh raised to %.2f",
                self._fiedler_fragmented_streak,
                _regime_w_bear,
                self._long_conviction_threshold,
            )

        # V95: Fiedler conviction modulation — use the spectral graph connectivity to
        # fine-tune conviction thresholds beyond the coarse fragmented-streak gate above.
        #
        # When Fiedler is "fragmented" (z < 0, signals diverging): market is under hidden
        # stress; lower short_thresh slightly to allow more bearish entries while the graph
        # is incoherent (directional shorts are more reliable than contrarian longs).
        # Floor: max(0.04, short_thresh * 0.85) — never below 0.04 (crisis short floor).
        #
        # When Fiedler z-score > 1.0 (consensus, signals strongly aligned): the signal
        # consensus increases confidence in directional moves; lower both thresholds by 10%
        # to allow more trades when the graph says "agree on a direction".
        # Cap: consensus can't lower below abs_min_conviction (0.02).
        #
        # "warmup" (not enough history yet): no adjustment.
        if self.features.fiedler_conviction_modulation:
            _fiedler_z = float(_spectral_val.value)
            _fiedler_tag = _spectral_val.regime_tag
            if _fiedler_tag == "fragmented" and not self._is_crisis:
                # Lower short bar during signal fragmentation — shorts are the safer direction
                _new_short = max(0.04, self._short_conviction_threshold * 0.85)
                if _new_short < self._short_conviction_threshold:
                    logger.info(
                        "V95 Fiedler modulation: fragmented (z=%.2f) → short_thresh %.4f→%.4f",
                        _fiedler_z,
                        self._short_conviction_threshold,
                        _new_short,
                    )
                    self._short_conviction_threshold = _new_short
            elif _fiedler_tag not in ("warmup", "fragmented") and _fiedler_z > 1.0:
                # Strong consensus: slightly lower both bars to capture momentum conviction
                _consensus_scale = max(0.90, 1.0 - 0.05 * min(_fiedler_z - 1.0, 2.0))
                _new_long = max(
                    self._abs_min_conviction, self._long_conviction_threshold * _consensus_scale
                )
                _new_short = max(
                    self._abs_min_conviction, self._short_conviction_threshold * _consensus_scale
                )
                if _consensus_scale < 1.0:
                    logger.debug(
                        "V95 Fiedler modulation: consensus (z=%.2f scale=%.2f) "
                        "long %.4f→%.4f short %.4f→%.4f",
                        _fiedler_z,
                        _consensus_scale,
                        self._long_conviction_threshold,
                        _new_long,
                        self._short_conviction_threshold,
                        _new_short,
                    )
                    self._long_conviction_threshold = _new_long
                    self._short_conviction_threshold = _new_short

        # --- Sit-out filter ---
        sit_out_reason, sit_out_size_mult = self._check_sit_out(signals, market_data)
        if sit_out_reason == "vol_low":
            self._sit_out_vol_low_count += 1
            logger.info("Market dead-calm (vol < 20th pct) — sitting out entirely this cycle")
            return {
                "weights": {},
                "positions": 0,
                "method": self._weighting,
                "sit_out": sit_out_reason,
                "sit_out_size_mult": 0.0,
                "fiedler_scale": round(_fiedler_scale, 4),
                "fiedler_regime": _spectral_val.regime_tag,
                "fiedler_zscore": round(float(_spectral_val.value), 4),
                "convictions": {t: c.name for t, c in convictions.items()},
                "proposals_generated": 0,
                "proposals_filtered": 0,
                "regime_blocked_longs": 0,
                "regime_blocked_shorts": 0,
                "regime_filter": {"regime": _regime_hmm, "confidence": _regime_confidence},
                "filter_stats": {
                    "generated": self._proposals_generated,
                    "filtered": self._proposals_filtered,
                    "filter_rate": self._filter_rate(),
                },
            }
        elif sit_out_reason == "vol_high":
            self._sit_out_vol_high_count += 1
            logger.info("Market chaotic (vol > 80th pct) — reducing position size 50%%")
        elif sit_out_reason == "regime_uncertain":
            self._sit_out_regime_count += 1
            # log message already emitted inside _check_sit_out
        else:
            self._normal_trade_count += 1

        # --- Time-of-day filter ---
        # Based on PnL data: 09h UTC shorts +60.9% wr; 23h UTC shorts 28.3% wr (-$215/day).
        # Reduce position size 50% during the US-close reversal window (22-00h UTC).
        _hour_utc = datetime.now(UTC).hour
        if _hour_utc in {22, 23, 0}:
            sit_out_size_mult *= 0.5
            logger.info(
                "Time filter: %02dh UTC (US-close reversal window) — position size reduced 50%%",
                _hour_utc,
            )

        # V133: four-factor AND-gate — instantiate once per portfolio construction.
        # Requires model-vs-market divergence, disposition > 0, low utilisation,
        # and non-fragmented correlation network. All four must pass for entry.
        _ffg = None
        _ffg_orc_kappa: float | None = None
        _ffg_fiedler_z: float | None = None
        if self.features.four_factor_and_gate:
            from omega.nodes.victoria.four_factor_gate import FourFactorGate as _FFGClass

            _ffg = _FFGClass(self.features)
            _raw_orc = signals.get("_geometry_orc_kappa")
            _ffg_orc_kappa = float(_raw_orc) if _raw_orc not in (None, 0.0) else None
            _ffg_fiedler_z = float(_spectral_val.value) if _spectral_val else None

        # Screen tickers that have non-HOLD conviction above signal threshold
        # and apply the full conviction filter stack.
        long_candidates: dict[str, Any] = {}
        proposals_this_cycle = 0
        filtered_this_cycle = 0
        regime_blocked_longs = 0
        regime_blocked_shorts = 0

        # V53: basket-direction guard — suppress longs when market broadly declining.
        # Use per-ticker composites (excluding metadata and synthetics).
        _basket_composites = [
            float(sig["composite"])
            for t, sig in signals.items()
            if not t.startswith("_")
            and not t.startswith("adv_")
            and isinstance(sig, dict)
            and "composite" in sig
        ]
        _basket_mean = (
            sum(_basket_composites) / len(_basket_composites) if _basket_composites else 0.0
        )
        _suppress_longs_basket = _basket_mean < -0.10

        short_candidates: dict[str, Any] = {}

        for ticker, sig in signals.items():
            if ticker.startswith("_") or not isinstance(sig, dict):
                continue
            # Skip synthetic signal-type aggregates (adv_order_flow, adv_cross_asset, etc.)
            # These are metadata entries from adapt_signals — they have no market price and
            # cannot be executed by the paper trading engine.
            if ticker.startswith("adv_"):
                logger.debug("Skipping %s (synthetic signal aggregate, not tradeable)", ticker)
                continue
            # Skip blacklisted symbols — BTC is a regime indicator, not a trading vehicle
            if ticker in _TRADING_BLACKLIST:
                logger.debug("Skipping %s (trading blacklist)", ticker)
                continue
            # Regime transition cooldown: skip new entries for 3 cycles after regime shift
            if _in_cooldown:
                logger.debug(
                    "Regime cooldown: skipping %s (cycle %d, change at %d)",
                    ticker,
                    current_cycle,
                    self._regime_change_cycle,
                )
                continue
            c = convictions.get(ticker, ConvictionLevel.HOLD)
            # Hard gate: HOLD conviction never generates a trade proposal.
            # This is explicit to make the invariant auditable — previously HOLD
            # fell through both branches silently; V32 diagnostics showed trades
            # firing against HOLD-level composites via edge cases in the filter stack.
            if c == ConvictionLevel.HOLD:
                # Record neutral direction for multi-cycle history
                _hist = self._signal_history.setdefault(ticker, [])
                _hist.append("hold")
                if len(_hist) > 2:
                    self._signal_history[ticker] = _hist[-2:]
                continue
            if c in (ConvictionLevel.STRONG_BUY, ConvictionLevel.BUY):
                if ticker in _LONG_BLACKLIST:
                    logger.debug("Skipping %s (long blacklist)", ticker)
                    continue
                # V65: suppress ETHUSDT longs in high_vol regime.
                # V66: extend to normal regime — V65 ETH:normal 15T all-long avg_loss -$28
                # vs avg_win $9 (3:1 ratio), -$159 net. Crisis longs remain enabled (+$6).
                # V68: replace full normal-regime suppression with 0.20 conviction floor —
                # V66 hard block caused trade count to drop 42→17 (gate failure: req ≥20).
                # High-conviction ETH longs (≥0.20) still permitted in normal regime.
                # V92: remove ETH absolute conviction floors (normal and high_vol).
                # Root cause: post-crash recovery composites (0.025-0.063) are above the
                # SCALED long_thresh (0.017-0.024) but below the ABSOLUTE floor (0.07/0.11).
                # The floor was inconsistently scaled — long_thresh scales with basket_std
                # but the floor was hardcoded absolute. This caused ETH to always fail the
                # floor check despite being above the actual quality bar. The 2-cycle
                # confirmation + IC-weighted conviction filter in _passes_conviction_filters
                # provide sufficient quality gating without the absolute floor.
                # V90 comment for history: high_vol floor was 0.11, normal was 0.07.
                # V85: Restore ETH high_vol long suppression (directional block, not floor).
                # V92 removed the floor but the directional gate was lost in the same edit.
                # V84: 4 ETH high_vol longs, 0% WR, -$18.09 — downside momentum in volatile
                # regimes makes mean-reversion longs consistently wrong.
                # V93: extend high_vol long suppression from ETH-only → all symbols.
                # V92 post-mortem: 7 high_vol trades, 0% WR, -$55.88 across ETH/NEAR/ARB/ADA.
                # Pattern is basket-wide: VRP "high_vol" signals elevated fear + downward
                # momentum for all correlated assets, not just ETH.
                if _is_high_vol:
                    logger.debug("Suppressing %s long in high_vol regime (V93)", ticker)
                    continue
                # V101: regime-safe flag — hard-block longs in crisis OR high_vol when on.
                # Uses _regime_consolidated (label-based) instead of self._is_crisis
                # (probabilistic: requires bear_prob>=0.65 or >=0.45 with label).
                # self._is_crisis can be False when _regime_consolidated=="crisis" and
                # bear_prob is between 0 and 0.45 — causing longs to slip through.
                # _regime_consolidated matches exactly what is recorded in trades.csv.
                # V136: hard block on long entries in crisis regime (not high_vol).
                # V135 diagnosis: 70-80% longs in crisis (H1-2022 bear market) drives PF<1.
                # crisis_long_block targets crisis only; high_vol_short_block covers the
                # high_vol case on the short side.
                if self.features.crisis_long_block and _regime_consolidated == "crisis":
                    logger.debug("V136: blocking %s long in crisis regime", ticker)
                    continue
                if self.features.crisis_high_vol_long_block and _regime_consolidated in (
                    "crisis",
                    "high_vol",
                ):
                    logger.debug(
                        "Regime-safe: blocking %s long in %s regime",
                        ticker,
                        _regime_consolidated,
                    )
                    continue
                # V66: suppress BNBUSDT longs in normal regime — V65 BNB:normal 6T 1W 17%WR -$18.
                # V81: removed BNB suppression — V66 was pre-abs_min fix. With abs_min=0.06 and
                # normal long_thresh=0.15 (scaled), BNB longs only trigger on genuine signals.
                # BNB at 0.019 composite in bull market should be tradeable.
                if sig.get("composite", 0.0) <= self._signal_threshold:
                    continue
                # Multi-cycle confirmation (V63 C+D): only enter if last cycle was also long.
                # Prevents whipsaw entries on single-cycle signal spikes.
                # V79: bypass confirmation for high-conviction longs (w_conv >= 0.20).
                # V81: lower bypass to 0.12 — V80 logs show ETH/BNB/AVAX w_conv ≈ 0.06-0.10
                # in normal regime, never reaching 0.20. With basket_std ≈ 0.07 and
                # long_thresh*scale ≈ 0.055, a w_conv of 0.12 (2.2x threshold) is a
                # credible signal. V80's 35-cycle zero streak in normal was caused by this
                # bypass being unreachable at current market conviction levels.
                # V88: lower bypass to 0.09 — V87 had 167-cycle max zero streak with bypass
                # at 0.12. Post-crash recovery composites cluster 0.03–0.10; 0.09 is still
                # 1.65x the scaled long_thresh (~0.055), a credible quality floor.
                # V88: lower bypass 0.09→0.05 — V86/V87 zero_streak=150/167 with composites
                # clustering at 0.02–0.06, never reaching 0.09. The confirmation gate
                # requires two consecutive long signals; at low conviction, this is impossible
                # without bypass. 0.05 is 1.4x scaled long_thresh (0.07*~0.5=0.035) — still
                # meaningful quality floor relative to what the market is producing.
                _prev_hist = self._signal_history.get(ticker, [])
                _hist = self._signal_history.setdefault(ticker, [])
                _hist.append("long")
                if len(_hist) > 2:
                    self._signal_history[ticker] = _hist[-2:]
                if not _prev_hist or _prev_hist[-1] != "long":
                    _wconv_long = abs(self._compute_weighted_conviction(sig))
                    if _wconv_long >= 0.05:
                        logger.debug(
                            "Multi-cycle: %s long — bypassing confirmation (w_conv=%.3f >= 0.05)",
                            ticker,
                            _wconv_long,
                        )
                    else:
                        logger.debug(
                            "Multi-cycle: %s long — no prior long confirmation, skipping", ticker
                        )
                        continue
                proposals_this_cycle += 1
                if _block_longs:
                    regime_blocked_longs += 1
                    continue
                # V53: basket-direction guard — suppress longs in a broadly declining market
                if _suppress_longs_basket:
                    filtered_this_cycle += 1
                    logger.debug(
                        "Filtered %s (long): basket_direction(mean=%.3f<-0.10)",
                        ticker,
                        _basket_mean,
                    )
                    continue
                passes, reason = self._passes_conviction_filters(
                    sig, current_cycle, direction="long"
                )
                if not passes:
                    filtered_this_cycle += 1
                    logger.debug("Filtered %s (long): %s", ticker, reason)
                    continue
                if self.features.signal_confluence and self._confluence is not None:
                    _cf = self._confluence.analyze(sig, ticker=ticker, direction="long")
                    self._last_confluence[ticker] = _cf
                    if _cf.is_uncertain:
                        logger.debug(
                            "Confluence UNCERTAIN %s (long): %s", ticker, _cf.to_log_str()
                        )
                # V107: activation_tracing — record entry trace at exact moment of acceptance
                if self._tracer is not None and self.features.activation_tracing:
                    import contextlib as _cl

                    with _cl.suppress(Exception):
                        from omega.nodes.victoria.activation_trace import (
                            build_activation_trace as _bat,
                        )

                        _at = _bat(
                            ticker=ticker,
                            cycle=current_cycle,
                            version=getattr(self, "_version", ""),
                            direction="long",
                            sig=sig,
                            weighted_conviction=self._last_w_conv,  # bias-adjusted value from filter
                            long_thresh=self._long_conviction_threshold,
                            short_thresh=self._short_conviction_threshold,
                            thresh_scale=_thresh_scale,
                            wc_thresh=self._weighted_conviction_threshold,
                            basket_mean=_basket_mean,
                            basket_std=_basket_std,
                            regime=_regime_consolidated,
                            bear_prob=float(signals.get("_regime_w_bear_prob", -1)),
                            bull_prob=float(signals.get("_regime_w_bull_prob", -1)),
                            is_crisis=self._is_crisis,
                            is_high_vol=self._is_high_vol_regime,
                            final_decision="TRADE",
                            conviction_level=c.name,
                        )
                        self._tracer.record_entry(ticker, _at)
                # V122: removed ADAUSDT from long suppression — single-version evidence only
                # (V116 had 8/10 worst losers as ADA longs, but ADAUSDT was the primary long
                # candidate. Removing it left no long diversity → all-short death spiral
                # in V117-V121). Policy: require ≥50 trades AND 2+ versions.
                _long_suppressed: set[str] = set()
                if self.features.postmortem_signal_filter and ticker in _long_suppressed:
                    logger.debug(
                        "postmortem_signal_filter: suppressing %s long (evidence-based)", ticker
                    )
                    continue
                # V133: four-factor AND-gate check (entry quality filter)
                if _ffg is not None:
                    from omega.nodes.victoria.four_factor_gate import GateContext as _GateCtx

                    _ffg_ctx = _GateCtx(
                        w_conv=float(sig.get("weighted_conviction") or self._last_w_conv),
                        funding_rate=float(sig.get("funding_rate_signal", 0.0)),
                        closed_trades=self._paper_engine.closed_trades
                        if self._paper_engine
                        else [],
                        open_positions=self._paper_engine.positions if self._paper_engine else {},
                        initial_capital=self._paper_engine.initial_capital
                        if self._paper_engine
                        else 100_000.0,
                        orc_kappa=_ffg_orc_kappa,
                        fiedler_zscore=_ffg_fiedler_z,
                    )
                    _ffg_result = _ffg.evaluate(_ffg_ctx)
                    if not _ffg_result.all_pass:
                        filtered_this_cycle += 1
                        logger.info(
                            "FFG blocked %s LONG: %s",
                            ticker,
                            "; ".join(_ffg_result.failing_gates),
                        )
                        self._last_ticker_decisions[ticker] = {
                            "action": "SKIP_FFG",
                            "direction": "long",
                            "failing_gates": _ffg_result.failing_gates,
                        }
                        continue
                long_candidates[ticker] = sig
            elif c in (ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL):
                if sig.get("composite", 0.0) >= -self._signal_threshold:
                    continue
                # Multi-cycle confirmation (V63 C+D): only enter if last cycle was also short.
                _prev_hist = self._signal_history.get(ticker, [])
                _hist = self._signal_history.setdefault(ticker, [])
                _hist.append("short")
                if len(_hist) > 2:
                    self._signal_history[ticker] = _hist[-2:]
                if not _prev_hist or _prev_hist[-1] != "short":
                    # V77: crisis short bypass — skip 2-cycle confirmation in crisis regime
                    # when the per-symbol composite is sufficiently negative.
                    # V79: relax bypass check from composite<=-0.06 to any SELL/STRONG_SELL
                    # conviction in crisis. The -0.06 threshold was calibrated for non-demeaned
                    # composites; after basket demeaning, crisis shorts with basket_mean≈-0.10
                    # produce per-symbol demeaned composites near -0.05 to -0.04 (above -0.06),
                    # silently blocking the bypass. The short_thresh=0.04 gate (V79) is the
                    # real filter; conviction level (SELL/STRONG_SELL) is sufficient gating.
                    # V82: restore raw composite gate at <= -0.10 — V81 post-mortem: AVAX/LINK
                    # with composites -0.07 to -0.09 passed SELL conviction but prices bounced
                    # (crisis regime with mean-reverting tickers). -0.10 floor filters marginal
                    # bear signals; genuinely crisis-aligned shorts have composites ≤ -0.12+.
                    # V84: relax to -0.07 — with _thresh_scale capped at 1.5 and basket_std≈0.38,
                    # post-demeaning per-symbol crisis composites cluster at -0.06 to -0.09.
                    # -0.10 was blocking the bypass for nearly all valid crisis shorts.
                    # AVAX/LINK are now in _TRADING_BLACKLIST (V83/V86), removing the mean-reverting
                    # offenders that motivated -0.10 in V82. -0.07 is the V77 sweet spot.
                    # V88: add normal-regime short bypass at w_conv >= 0.09 — mirrors the long
                    # bypass logic. V87 ADA short worked via 2-cycle confirmation (cycles 28-29);
                    # a w_conv >= 0.09 gate allows first-cycle entry for credible short signals
                    # in normal regime without waiting for confirmation (1.65x short_thresh floor).
                    _c_val = convictions.get(ticker, ConvictionLevel.HOLD)
                    _raw_composite = sig.get("composite", 0.0)
                    _wconv_short = abs(self._compute_weighted_conviction(sig))
                    if (
                        self._is_crisis
                        and _c_val in (ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL)
                        and _raw_composite <= -0.07
                        and ticker not in _CRISIS_BYPASS_BLACKLIST
                    ):
                        logger.debug(
                            "Multi-cycle: %s crisis short — bypassing confirmation "
                            "(conviction=%s, composite=%.3f)",
                            ticker,
                            _c_val.name,
                            _raw_composite,
                        )
                    elif not self._is_crisis and _wconv_short >= (
                        0.07 if self.features.v96_multi_cycle_bypass else 0.09
                    ):
                        logger.debug(
                            "Multi-cycle: %s normal short — bypassing confirmation "
                            "(w_conv=%.3f >= %.2f)",
                            ticker,
                            _wconv_short,
                            0.07 if self.features.v96_multi_cycle_bypass else 0.09,
                        )
                    else:
                        logger.debug(
                            "Multi-cycle: %s short — no prior short confirmation, skipping", ticker
                        )
                        continue
                # V130: block shorts in high_vol regime when flag enabled.
                # Phase A V129 diagnosis: all high_vol losses were ETH shorts (-$3,476/snapshot).
                # V93 already blocks longs in high_vol unconditionally (line ~1676).
                # High_vol shorts work in prolonged bear (crisis) but lose in vol-spike recoveries
                # where price bounces sharply against the position.
                # V136: lower short threshold in crisis to encourage directionally correct shorts.
                # crisis_short_permissive_scale ∈ (0,1] multiplies the short conviction threshold.
                # Default scale=1.0 (disabled). v136a uses 0.5, v136b uses 0.4.
                if (
                    getattr(self.features, "crisis_short_permissive", False)
                    and _regime_consolidated == "crisis"
                ):
                    _crisis_scale = float(getattr(self.features, "crisis_short_thresh_scale", 0.5))
                    _crisis_short_thresh = self._short_conviction_threshold * _crisis_scale
                    _raw_comp = abs(sig.get("composite", 0.0))
                    if _raw_comp < _crisis_short_thresh:
                        logger.debug(
                            "V136: %s short below scaled crisis threshold %.4f (scale=%.2f)",
                            ticker,
                            _crisis_short_thresh,
                            _crisis_scale,
                        )
                        continue
                if self.features.high_vol_short_block and _is_high_vol:
                    logger.debug("Suppressing %s short in high_vol regime (V130)", ticker)
                    continue
                # V73: suppress SOLUSDT shorts in normal regime — V72 normal SOLUSDT shorts
                # showed mixed results and XRPUSDT blacklist reduces basket, so be selective.
                # V79: removed SOL normal short suppression — V78 SOL short cycle 112
                # (normal regime) was +$8.87; V71's -$78.87 was pre-abs_min_conviction fix.
                # The current 0.08 short_thresh is now the gate; per-ticker suppression not needed.
                proposals_this_cycle += 1
                if _block_shorts:
                    regime_blocked_shorts += 1
                    continue
                passes, reason = self._passes_conviction_filters(
                    sig, current_cycle, direction="short"
                )
                if not passes:
                    filtered_this_cycle += 1
                    logger.debug("Filtered %s (short): %s", ticker, reason)
                    continue
                if self.features.signal_confluence and self._confluence is not None:
                    _cf = self._confluence.analyze(sig, ticker=ticker, direction="short")
                    self._last_confluence[ticker] = _cf
                    if _cf.is_uncertain:
                        logger.debug(
                            "Confluence UNCERTAIN %s (short): %s", ticker, _cf.to_log_str()
                        )
                # V107: activation_tracing — record entry trace for short
                if self._tracer is not None and self.features.activation_tracing:
                    import contextlib as _cl

                    with _cl.suppress(Exception):
                        from omega.nodes.victoria.activation_trace import (
                            build_activation_trace as _bat,
                        )

                        _at = _bat(
                            ticker=ticker,
                            cycle=current_cycle,
                            version=getattr(self, "_version", ""),
                            direction="short",
                            sig=sig,
                            weighted_conviction=self._last_w_conv,  # bias-adjusted value from filter
                            long_thresh=self._long_conviction_threshold,
                            short_thresh=self._short_conviction_threshold,
                            thresh_scale=_thresh_scale,
                            wc_thresh=self._weighted_conviction_threshold,
                            basket_mean=_basket_mean,
                            basket_std=_basket_std,
                            regime=_regime_consolidated,
                            bear_prob=float(signals.get("_regime_w_bear_prob", -1)),
                            bull_prob=float(signals.get("_regime_w_bull_prob", -1)),
                            is_crisis=self._is_crisis,
                            is_high_vol=self._is_high_vol_regime,
                            final_decision="TRADE",
                            conviction_level=c.name,
                        )
                        self._tracer.record_entry(ticker, _at)
                        # V114: suppress specific tickers on the short side based on postmortem evidence.
                # NEARUSDT: 22 shorts in V113, 27% WR, -$93 PnL — suppressed when filter active.
                _short_suppressed = {
                    "NEARUSDT",  # V113: 22 shorts, 27% WR, -$93 PnL (50+ trade evidence)
                    "ARBUSDT",  # V115: 21 trades, 38% WR, -$159 gross loss (50+ trade evidence)
                    # V128: ETHUSDT removed (third time). Loop keeps re-adding it on single-run
                    # evidence contaminated by V118 crash. Removing ETHUSDT short candidates
                    # causes all-long bias (V127: 20L/0S). Policy: need ≥50 trades in 2+ clean
                    # (non-crash) versions before suppression. Not met.
                }
                if self.features.postmortem_signal_filter and ticker in _short_suppressed:
                    logger.debug(
                        "postmortem_signal_filter: suppressing %s short (evidence-based)", ticker
                    )
                    continue
                # V133: four-factor AND-gate check (entry quality filter)
                if _ffg is not None:
                    from omega.nodes.victoria.four_factor_gate import GateContext as _GateCtx

                    _ffg_ctx = _GateCtx(
                        w_conv=float(sig.get("weighted_conviction") or self._last_w_conv),
                        funding_rate=float(sig.get("funding_rate_signal", 0.0)),
                        closed_trades=self._paper_engine.closed_trades
                        if self._paper_engine
                        else [],
                        open_positions=self._paper_engine.positions if self._paper_engine else {},
                        initial_capital=self._paper_engine.initial_capital
                        if self._paper_engine
                        else 100_000.0,
                        orc_kappa=_ffg_orc_kappa,
                        fiedler_zscore=_ffg_fiedler_z,
                    )
                    _ffg_result = _ffg.evaluate(_ffg_ctx)
                    if not _ffg_result.all_pass:
                        filtered_this_cycle += 1
                        logger.info(
                            "FFG blocked %s SHORT: %s",
                            ticker,
                            "; ".join(_ffg_result.failing_gates),
                        )
                        self._last_ticker_decisions[ticker] = {
                            "action": "SKIP_FFG",
                            "direction": "short",
                            "failing_gates": _ffg_result.failing_gates,
                        }
                        continue
                short_candidates[ticker] = sig

        if regime_blocked_longs or regime_blocked_shorts:
            logger.info(
                "Regime filter (%s, conf=%.2f) — blocked %d long proposal(s), %d short proposal(s)",
                _regime_hmm,
                _regime_confidence,
                regime_blocked_longs,
                regime_blocked_shorts,
            )

        self._proposals_generated += proposals_this_cycle
        self._proposals_filtered += (
            filtered_this_cycle + regime_blocked_longs + regime_blocked_shorts
        )

        # No candidates: either all filtered by conviction or no conviction signals at all.
        # Do NOT fall back to weak signals — the filter's purpose is to reduce trade count.
        if not long_candidates and not short_candidates:
            self._zero_candidate_streak += 1
            if self._zero_candidate_streak > 30:
                _composites = {
                    t: sig.get("composite", 0.0)
                    for t, sig in signals.items()
                    if not t.startswith("_") and not t.startswith("adv_") and isinstance(sig, dict)
                }
                _cross_asset_nulls = [
                    k
                    for t, sig in signals.items()
                    if isinstance(sig, dict)
                    for k in ("fear_greed_signal", "dxy_signal", "funding_rate_signal")
                    if sig.get(k, None) in (None, 0.0)
                ]
                logger.warning(
                    "Zero-candidate streak: %d cycles — "
                    "regime=%s, long_thresh=%.4f, short_thresh=%.4f, "
                    "composites=%s, cross_asset_null=%s",
                    self._zero_candidate_streak,
                    _regime_hmm,
                    self._long_conviction_threshold,
                    self._short_conviction_threshold,
                    {t: round(v, 4) for t, v in _composites.items()} if _composites else "{}",
                    list(set(_cross_asset_nulls)) if _cross_asset_nulls else "none",
                )
            conviction_dist = {level.name: 0 for level in ConvictionLevel}
            for c in convictions.values():
                conviction_dist[c.name] += 1
            return {
                "weights": {},
                "positions": 0,
                "method": self._weighting,
                "fiedler_scale": round(_fiedler_scale, 4),
                "fiedler_regime": _spectral_val.regime_tag,
                "fiedler_zscore": round(float(_spectral_val.value), 4),
                "convictions": {t: c.name for t, c in convictions.items()},
                "conviction_distribution": conviction_dist,
                "proposals_generated": proposals_this_cycle,
                "proposals_filtered": filtered_this_cycle,
                "regime_blocked_longs": regime_blocked_longs,
                "regime_blocked_shorts": regime_blocked_shorts,
                "regime_filter": {"regime": _regime_hmm, "confidence": _regime_confidence},
                "filter_stats": {
                    "generated": self._proposals_generated,
                    "filtered": self._proposals_filtered,
                    "filter_rate": self._filter_rate(),
                },
            }

        # Limit candidates to top N by |composite| strength before building weights.
        # When many tickers share identical conviction (common in uniform regimes),
        # unrestricted candidates spread capital too thinly — each position falls
        # to MAX_CAPITAL_DEPLOYED / N, which can dip below MIN_POSITION_FRACTION.
        # Capping at MAX_POSITIONS // 2 keeps per-position size meaningful (≥10%).
        _max_per_side = max(1, self._risk.max_positions // 2)
        if len(long_candidates) > _max_per_side:
            long_candidates = dict(
                sorted(
                    long_candidates.items(),
                    key=lambda kv: abs(kv[1].get("composite", 0.0)),
                    reverse=True,
                )[:_max_per_side]
            )
        if len(short_candidates) > _max_per_side:
            short_candidates = dict(
                sorted(
                    short_candidates.items(),
                    key=lambda kv: abs(kv[1].get("composite", 0.0)),
                    reverse=True,
                )[:_max_per_side]
            )

        long_base: dict[str, float] = {}
        short_base: dict[str, float] = {}

        if self._weighting == "equal":
            if long_candidates:
                w = 1.0 / len(long_candidates)
                long_base = {ticker: w for ticker in long_candidates}
            if short_candidates:
                w = 1.0 / len(short_candidates)
                short_base = {ticker: w for ticker in short_candidates}

        elif self._weighting == "momentum":
            if long_candidates:
                raw_l = {
                    ticker: max(0.001, sig.get("composite", 0.001))
                    for ticker, sig in long_candidates.items()
                }
                total_l = sum(raw_l.values())
                long_base = {ticker: v / total_l for ticker, v in raw_l.items()}
            if short_candidates:
                raw_s = {
                    ticker: max(0.001, abs(sig.get("composite", 0.001)))
                    for ticker, sig in short_candidates.items()
                }
                total_s = sum(raw_s.values())
                short_base = {ticker: v / total_s for ticker, v in raw_s.items()}

        elif self._weighting == "risk_parity":
            for _ticker, _sig in {**long_candidates, **short_candidates}.items():
                pass  # vols computed per-pool below
            vols_l: dict[str, float] = {}
            for ticker, _sig in long_candidates.items():
                data = market_data.get(ticker)
                if data:
                    prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
                    vol = self._compute_volatility(prices, window=20)
                    vols_l[ticker] = vol if vol > 0 else 0.3
                else:
                    vols_l[ticker] = 0.3
            if vols_l:
                inv_vol_l = {ticker: 1.0 / v for ticker, v in vols_l.items()}
                total_l = sum(inv_vol_l.values())
                long_base = {ticker: v / total_l for ticker, v in inv_vol_l.items()}

            vols_s: dict[str, float] = {}
            for ticker, _sig in short_candidates.items():
                data = market_data.get(ticker)
                if data:
                    prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
                    vol = self._compute_volatility(prices, window=20)
                    vols_s[ticker] = vol if vol > 0 else 0.3
                else:
                    vols_s[ticker] = 0.3
            if vols_s:
                inv_vol_s = {ticker: 1.0 / v for ticker, v in vols_s.items()}
                total_s = sum(inv_vol_s.values())
                short_base = {ticker: v / total_s for ticker, v in inv_vol_s.items()}

        # Apply conviction size multipliers and continuous conviction scaling.
        # V65: also scale by (w_conv / 0.25) clamped to [0.5, 2.0] — V63 showed
        # winner/loser conviction virtually identical (0.2338 vs 0.2346) because
        # the discrete ConvictionLevel multiplier doesn't capture magnitude within
        # a level.  This continuous factor rewards genuinely high-conviction signals.
        raw_weights: dict[str, float] = {}
        _wconv_scores: dict[str, float] = {}  # w_conv per ticker for paper_trading sizing
        # V102: crisis_short_bias per-direction size multipliers (applied before kelly).
        _csb_fear_regime = self.features.crisis_short_bias and _regime_consolidated in (
            "crisis",
            "high_vol",
        )
        _csb_short_mult = 1.3 if _csb_fear_regime else 1.0
        _csb_long_mult = 0.5 if _csb_fear_regime else 1.0
        # V136: crisis_position_size_boost for shorts in crisis regime.
        # Stacks additively with _csb_short_mult when crisis_short_bias is also on.
        _v136_crisis_short_boost = (
            float(getattr(self.features, "crisis_position_size_boost", 1.0))
            if (
                getattr(self.features, "crisis_long_block", False)
                and _regime_consolidated == "crisis"
            )
            else 1.0
        )
        for ticker, w in long_base.items():
            _w_conv = abs(self._compute_weighted_conviction(long_candidates[ticker]))
            _wconv_scores[ticker] = _w_conv
            if self.features.signal_confluence:
                _cf = self._last_confluence.get(ticker)
                _boosted_conv = _w_conv * (_cf.conviction_multiplier if _cf else 1.0)
                # V101 Fix 3: confluence is observer-only — warn on uncertain signals
                # but do NOT apply size_multiplier=0.5 penalty (was gating trades).
                if _cf and _cf.is_uncertain:
                    logger.warning(
                        "Confluence uncertain %s (long): %s — proceeding at nominal size",
                        ticker,
                        _cf.to_log_str(),
                    )
                _conv_scale = max(0.5, min(2.0, _boosted_conv / 0.25))
                raw_weights[ticker] = (
                    w
                    * conviction_size_multiplier(convictions[ticker])
                    * _conv_scale
                    * _csb_long_mult
                )
            else:
                _conv_scale = max(0.5, min(2.0, _w_conv / 0.25))
                raw_weights[ticker] = (
                    w
                    * conviction_size_multiplier(convictions[ticker])
                    * _conv_scale
                    * _csb_long_mult
                )
        for ticker, w in short_base.items():
            _w_conv = abs(self._compute_weighted_conviction(short_candidates[ticker]))
            _wconv_scores[ticker] = _w_conv
            if self.features.signal_confluence:
                _cf = self._last_confluence.get(ticker)
                _boosted_conv = _w_conv * (_cf.conviction_multiplier if _cf else 1.0)
                # V101 Fix 3: same warn-only policy for shorts
                if _cf and _cf.is_uncertain:
                    logger.warning(
                        "Confluence uncertain %s (short): %s — proceeding at nominal size",
                        ticker,
                        _cf.to_log_str(),
                    )
                _conv_scale = max(0.5, min(2.0, _boosted_conv / 0.25))
                raw_weights[ticker] = (
                    -w
                    * conviction_size_multiplier(convictions[ticker])
                    * _conv_scale
                    * _csb_short_mult
                    * _v136_crisis_short_boost
                )
            else:
                _conv_scale = max(0.5, min(2.0, _w_conv / 0.25))
                raw_weights[ticker] = (
                    -w
                    * conviction_size_multiplier(convictions[ticker])
                    * _conv_scale
                    * _csb_short_mult
                    * _v136_crisis_short_boost
                )

        # V102: crisis_short_bias size multipliers — scale shorts up (1.3x), longs down (0.5x)
        # in crisis/high_vol to tilt allocation toward the favored direction.
        # Applied before Kelly so the Kelly fraction operates on the already-skewed weights.
        if self.features.crisis_short_bias and (self._is_crisis or _is_high_vol):
            _csb_n_shorts = sum(1 for w in raw_weights.values() if w < 0)
            _csb_n_longs = sum(1 for w in raw_weights.values() if w > 0)
            for _ticker in list(raw_weights.keys()):
                _w = raw_weights[_ticker]
                if _w < 0:
                    raw_weights[_ticker] = _w * 1.3
                elif _w > 0:
                    raw_weights[_ticker] = _w * 0.5
            logger.info(
                "crisis_short_bias size: %s — %d shorts *1.3, %d longs *0.5",
                "crisis" if self._is_crisis else "high_vol",
                _csb_n_shorts,
                _csb_n_longs,
            )

        # Kelly scaling: adjust all weights by half-Kelly fraction
        _kelly_scale = self._kelly_fraction()
        # V82: crisis regime reduces position sizes by 50% — V81 post-mortem showed crisis
        # shorts (AVAX/LINK) losing -$40+ when the bypass fires on marginal signals.
        # Crisis markets have high mean-reversion risk; smaller positions limit damage
        # while still participating in genuine directional moves.
        if self._is_crisis and not self.features.crisis_short_bias:
            _kelly_scale *= 0.5
            logger.info("Crisis half-Kelly: scale * 0.5 = %.3f", _kelly_scale)
        elif self._is_crisis and self.features.crisis_short_bias:
            logger.info(
                "Crisis half-Kelly skipped: crisis_short_bias uses per-direction "
                "sizing (short×%.1f long×%.1f)",
                _csb_short_mult,
                _csb_long_mult,
            )
        self._last_kelly_scale: float = _kelly_scale  # expose for observability
        if _kelly_scale != 1.0:
            raw_weights = {t: w * _kelly_scale for t, w in raw_weights.items()}
            logger.info(
                "Kelly sizing: scale=%.3f (n_trades=%d)", _kelly_scale, len(self._trade_history)
            )

        # Apply continuous regime scaling: bear_prob reduces longs, bull_prob reduces shorts
        if _use_continuous_regime:
            for ticker in list(raw_weights.keys()):
                w = raw_weights[ticker]
                if w > 0:
                    raw_weights[ticker] = w * (1.0 - _regime_w_bear)
                elif w < 0:
                    raw_weights[ticker] = w * (1.0 - _regime_w_bull)

        # Normalise so total |weight| = 1.0, then apply sit-out size multiplier
        total_w = sum(abs(v) for v in raw_weights.values())
        weights: dict[str, float] = (
            {ticker: v / total_w * sit_out_size_mult for ticker, v in raw_weights.items()}
            if total_w > 0
            else {}
        )

        # Apply Fiedler scale (computed at top of method before early returns)
        if _fiedler_scale < 1.0 and weights:
            weights = {t: w * _fiedler_scale for t, w in weights.items()}
            logger.info(
                "Fiedler scale %.3f (z=%.3f, regime=%s) — position sizes reduced",
                _fiedler_scale,
                _spectral_val.value,
                _spectral_val.regime_tag,
            )

        # V95: Geometry-based position size modulation.
        #
        # (A) ORC stress signal: when mean Ollivier-Ricci curvature > 0.1 (stress regime —
        # correlated assets share return distributions, signalling contagion), reduce all
        # position sizes.  The stress multiplier decays linearly from 1.0 at kappa=0.1
        # to 0.6 at kappa=0.5+ (20% reduction per 0.1 kappa above the threshold).
        # This is separate from Fiedler — ORC measures cross-asset contagion while Fiedler
        # measures within-signal-type consensus.
        #
        # (B) Ricci-weighted sizing: when the market manifold has high Ricci curvature
        # (mean-reverting geometry) AND the market is closer to the crash reference than
        # the rally reference (geo_dist_crash < geo_dist_rally), reduce long position sizes.
        # This catches the "buying the dip in a crash" failure mode that V75 partially
        # addressed with the theta_mu dampening of the manifold signal.
        # Ricci scale for longs: 1.0 - 0.3 * max(0, ricci_raw / 3.0) when approaching crash.
        _geometry_size_mult = 1.0
        _orc_kappa = float(signals.get("_geometry_orc_kappa", 0.0))
        _orc_regime = str(signals.get("_geometry_orc_regime", "neutral"))
        if self.features.orc_stress_reduction and _orc_regime == "stress" and _orc_kappa > 0.1:
            _orc_mult = max(0.6, 1.0 - 2.0 * (_orc_kappa - 0.1))
            _geometry_size_mult *= _orc_mult
            logger.info(
                "V95 ORC stress: kappa=%.3f regime=%s → size_mult=%.2f",
                _orc_kappa,
                _orc_regime,
                _orc_mult,
            )

        _ricci_raw = float(signals.get("_geometry_ricci_raw", 0.0))
        _geo_crash = float(signals.get("_geometry_geo_dist_crash", -1.0))
        _geo_rally = float(signals.get("_geometry_geo_dist_rally", -1.0))
        _approaching_crash = (
            _geo_crash >= 0.0
            and _geo_rally >= 0.0
            and (_geo_crash + _geo_rally) > 1e-6
            and _geo_crash < _geo_rally
        )
        if self.features.ricci_sizing and _approaching_crash and _ricci_raw > 0.3 and weights:
            # Manifold in mean-reversion geometry AND drifting toward crash state:
            # reduce long position sizes by up to 30%
            _ricci_long_mult = max(0.7, 1.0 - 0.3 * min(_ricci_raw / 3.0, 1.0))
            _new_weights: dict[str, float] = {}
            for _t, _w in weights.items():
                _new_weights[_t] = _w * _ricci_long_mult if _w > 0 else _w
            if any(abs(_new_weights[_t]) != abs(weights[_t]) for _t in _new_weights):
                logger.info(
                    "V95 Ricci sizing: ricci=%.3f approaching_crash=True → long_mult=%.2f",
                    _ricci_raw,
                    _ricci_long_mult,
                )
                weights = _new_weights

        if _geometry_size_mult < 1.0 and weights:
            weights = {t: w * _geometry_size_mult for t, w in weights.items()}
            logger.info(
                "V95 geometry size mult=%.3f (orc_kappa=%.3f orc_regime=%s)",
                _geometry_size_mult,
                _orc_kappa,
                _orc_regime,
            )

        # ── Portfolio risk manager (layers 1-5) ─────────────────────────────
        # Build price_histories for vol-scaling from market_data
        _price_histories: dict[str, list[float]] = {}
        for _t, _d in market_data.items():
            if not isinstance(_d, dict):
                continue
            _prices = self._clean_prices(_d.get("adjclose") or _d.get("close", []))
            if _prices:
                _price_histories[_t] = _prices

        # Retrieve RMT correlation matrix if available (injected via set_rmt_denoiser)
        _corr_matrix = None
        _corr_tickers: list[str] = []
        if self._rmt_denoiser is not None:
            _corr_matrix = self._rmt_denoiser.get_denoised_correlation()
            from omega.nodes.victoria.information_flow import SIGNAL_NAMES as _SNAMES

            _corr_tickers = list(_SNAMES)

        # Conviction scores for corr tie-breaking (use raw float conviction values)
        _conv_scores = {t: float(convictions[t]) for t in weights if t in convictions}

        weights = self._risk.apply_all(
            weights=weights,
            price_histories=_price_histories if _price_histories else None,
            corr_matrix=_corr_matrix,
            tickers=_corr_tickers if _corr_tickers else None,
            convictions=_conv_scores if _conv_scores else None,
        )

        _risk_metrics = self._risk.get_metrics()
        # ────────────────────────────────────────────────────────────────────

        # Conviction distribution summary for metrics
        conviction_dist = {level.name: 0 for level in ConvictionLevel}
        for c in convictions.values():
            conviction_dist[c.name] += 1

        # Also run a quick backtest
        bt = self._backtest(signals, market_data)

        # ── Build per-ticker decision traces for full tensor observability ──
        # Done before updating _last_trade_cycle so time-filter check is consistent.
        # _raw_composite / _basket_mean are stored by signal_generation.py before demeaning.
        _buy_threshold_raw = 0.2 / _cs_norm  # composite > this → BUY conviction
        _ticker_decisions: dict[str, TickerDecision] = {}
        for _td_ticker, _td_sig in signals.items():
            if (
                _td_ticker.startswith("_")
                or _td_ticker.startswith("adv_")
                or not isinstance(_td_sig, dict)
            ):
                continue
            if "composite" not in _td_sig:
                continue

            _td_signal_traces = [
                SignalTrace(
                    signal_name=_k,
                    raw_value=float(_td_sig[_k]),
                    rationale_text="",
                    inputs_used={
                        ik: _td_sig[ik]
                        for ik in (
                            # include the raw indicator values for context
                            {
                                "sma_crossover": ["sma_short", "sma_long"],
                                "rsi_signal": ["rsi"],
                                "macd_crossover": ["macd", "macd_signal_line"],
                                "bb_signal": ["bb_upper", "bb_lower", "bb_mid"],
                                "zscore_signal": ["zscore"],
                                "volume_signal": ["volume_zscore"],
                                "btc_beta_signal": ["btc_beta"],
                                "vol_regime_signal": ["vol_regime", "recent_vol_ann"],
                            }.get(_k, [])
                        )
                        if ik in _td_sig and isinstance(_td_sig[ik], (int, float, str))
                    },
                )
                for _k, _v in _td_sig.items()
                if (_k.endswith("_signal") or _k == "sma_crossover")
                and isinstance(_v, (int, float))
            ]

            _td_demeaned = float(_td_sig.get("composite", 0.0))
            _td_raw = float(_td_sig.get("_raw_composite", _td_demeaned))
            _td_bm = float(_td_sig.get("_basket_mean", 0.0))
            _td_c = convictions.get(_td_ticker, ConvictionLevel.HOLD)
            _td_filters: list[str] = []
            _td_proposal = "NONE"
            _td_final = "HOLD"
            _td_reason = ""

            if _td_ticker in _TRADING_BLACKLIST:
                _td_filters.append("blacklist:skip")
                _td_final = "HOLD"
                _td_reason = "blacklist"
            elif _td_c == ConvictionLevel.HOLD:
                _td_filters.append(f"conviction_gate:hold(score={_td_demeaned * _cs_norm:.3f})")
            elif _td_c in (ConvictionLevel.STRONG_BUY, ConvictionLevel.BUY):
                if _td_ticker in _LONG_BLACKLIST:
                    _td_filters.append("long_blacklist:skip")
                    _td_final = "FILTERED"
                    _td_reason = "long_blacklist"
                elif _td_demeaned <= self._signal_threshold:
                    _td_filters.append(
                        f"signal_threshold:skip(composite={_td_demeaned:.4f}<={self._signal_threshold:.4f})"
                    )
                    _td_final = "FILTERED"
                    _td_reason = "signal_threshold"
                else:
                    _td_proposal = "LONG"
                    if _block_longs:
                        _td_filters.append(
                            f"regime_block:filtered({_regime_hmm}@{_regime_confidence:.2f})"
                        )
                        _td_final = "FILTERED"
                        _td_reason = f"regime_block({_regime_hmm})"
                    else:
                        _td_passes, _td_filter_reason = self._passes_conviction_filters(
                            _td_sig, current_cycle, "long"
                        )
                        if not _td_passes:
                            _td_filters.append(f"conviction_filters:filtered({_td_filter_reason})")
                            _td_final = "FILTERED"
                            _td_reason = _td_filter_reason
                        else:
                            _td_filters.append("conviction_filters:pass")
                            _td_final = "TRADE" if _td_ticker in weights else "FILTERED"
                            if _td_final == "FILTERED":
                                _td_reason = "position_limit"
            elif _td_c in (ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL):
                if _td_demeaned >= -self._signal_threshold:
                    _td_filters.append("signal_threshold:skip")
                    _td_final = "FILTERED"
                    _td_reason = "signal_threshold"
                else:
                    _td_proposal = "SHORT"
                    if _block_shorts:
                        _td_filters.append(
                            f"regime_block:filtered({_regime_hmm}@{_regime_confidence:.2f})"
                        )
                        _td_final = "FILTERED"
                        _td_reason = f"regime_block({_regime_hmm})"
                    else:
                        _td_passes, _td_filter_reason = self._passes_conviction_filters(
                            _td_sig, current_cycle, "short"
                        )
                        if not _td_passes:
                            _td_filters.append(f"conviction_filters:filtered({_td_filter_reason})")
                            _td_final = "FILTERED"
                            _td_reason = _td_filter_reason
                        else:
                            _td_filters.append("conviction_filters:pass")
                            _td_final = "TRADE" if _td_ticker in weights else "FILTERED"
                            if _td_final == "FILTERED":
                                _td_reason = "position_limit"

            _ticker_decisions[_td_ticker] = TickerDecision(
                ticker=_td_ticker,
                signal_traces=_td_signal_traces,
                raw_composite=_td_raw,
                basket_mean=_td_bm,
                demeaned_composite=_td_demeaned,
                conviction=_td_c.name,
                conviction_score=_td_demeaned * _cs_norm,
                conviction_threshold_buy=_buy_threshold_raw,
                conviction_threshold_sell=-_buy_threshold_raw,
                proposal=_td_proposal,
                filters_applied=_td_filters,
                final_action=_td_final,
                filter_reason=_td_reason,
            )

        self._last_ticker_decisions = _ticker_decisions
        # ── end decision traces ──────────────────────────────────────────────

        # ── Signal correlation monitor (gated) ───────────────────────────────
        if self.features.signal_correlation_monitor and self._corr_monitor is not None:
            self._corr_monitor.update(current_cycle, signals)
            if self._trace_writer is not None and self._corr_monitor.get_matrix():
                self._corr_monitor.save(self._trace_writer._version)

        # ── Extended DecisionTrace persistence (gated) ───────────────────────
        if self.features.decision_traces and self._trace_writer is not None:
            import datetime as _dt

            _now_ts = _dt.datetime.now(_dt.UTC).isoformat()
            _trace_version = self._trace_writer._version
            _geo_ricci = float(signals.get("_ricci_scalar", 0.0) or 0.0)
            _geo_orc = float(signals.get("_orc_mean_curvature", 0.0) or 0.0)
            _geo_crash_d = float(signals.get("_geo_dist_crash", float("inf")) or float("inf"))
            _geo_fiedler = float(getattr(self, "_last_fiedler_raw", 1.0))
            _bear = float(signals.get("_regime_w_bear_prob", -1.0))
            _bull = float(signals.get("_regime_w_bull_prob", -1.0))
            _traces: list[DecisionTrace] = []
            for _tr_ticker, _td in _ticker_decisions.items():
                _tr_sig = signals.get(_tr_ticker, {})
                _signal_vals = {
                    k: float(v)
                    for k, v in _tr_sig.items()
                    if (k.endswith("_signal") or k == "sma_crossover")
                    and isinstance(v, (int, float))
                }
                _w_conv = self._compute_weighted_conviction(_tr_sig) if _tr_sig else 0.0
                _thresh = (
                    self._long_conviction_threshold
                    if _td.proposal == "LONG"
                    else self._short_conviction_threshold
                )
                trace = DecisionTrace(
                    ticker=_tr_ticker,
                    cycle=current_cycle,
                    version=_trace_version,
                    timestamp=_now_ts,
                    signals=_signal_vals,
                    raw_composite=_td.raw_composite,
                    demeaned_composite=_td.demeaned_composite,
                    basket_mean=_td.basket_mean,
                    basket_std=_basket_std,
                    weighted_conviction=_w_conv,
                    regime=_regime_consolidated,
                    bear_prob=_bear,
                    bull_prob=_bull,
                    thresh_scale=_thresh_scale,
                    long_thresh=self._long_conviction_threshold,
                    short_thresh=self._short_conviction_threshold,
                    abs_min_conviction=self._abs_min_conviction,
                    ricci_scalar=_geo_ricci,
                    orc_mean=_geo_orc,
                    geo_dist_crash=_geo_crash_d,
                    fiedler_raw=_geo_fiedler,
                    proposal=_td.proposal,
                    filters_fired=_td.filters_applied,
                    blocking_filter=_td.filter_reason,
                    final_decision=_td.final_action,
                    threshold_gap=abs(_w_conv) - _thresh,
                    explanation="",
                )
                trace.explanation = build_explanation(trace)
                _traces.append(trace)
            if _traces:
                self._trace_writer.write_many(_traces)
        # ── end observability ────────────────────────────────────────────────

        # Record cycle as having produced trades (for time filter)
        if weights:
            self._last_trade_cycle = current_cycle
            self._zero_candidate_streak = 0

        return {
            "weights": weights,
            "conviction_scores": {t: _wconv_scores.get(t, 0.30) for t in weights},
            "positions": len(weights),
            "method": self._weighting,
            "signal_threshold": self._signal_threshold,
            "sit_out": sit_out_reason,
            "sit_out_size_mult": sit_out_size_mult,
            "fiedler_scale": round(_fiedler_scale, 4),
            "fiedler_regime": _spectral_val.regime_tag,
            "fiedler_zscore": round(float(_spectral_val.value), 4),
            "kelly_scale": round(_kelly_scale, 4),
            "convictions": {t: convictions[t].name for t in weights},
            "conviction_distribution": conviction_dist,
            "top_picks": self._rank_signals(signals)[:5],
            "backtest": bt,
            "proposals_generated": proposals_this_cycle,
            "proposals_filtered": filtered_this_cycle,
            "regime_blocked_longs": regime_blocked_longs,
            "regime_blocked_shorts": regime_blocked_shorts,
            "regime_filter": {"regime": _regime_hmm, "confidence": _regime_confidence},
            "filter_stats": {
                "generated": self._proposals_generated,
                "filtered": self._proposals_filtered,
                "filter_rate": self._filter_rate(),
            },
            "risk": _risk_metrics,
        }

    def _rank_signals(self, signals: dict[str, Any]) -> list[dict[str, Any]]:
        """Rank tickers by composite signal strength, including conviction."""
        # Recompute basket std for relative normalisation (mirrors _construct_portfolio).
        _vals = [
            float(sig["composite"])
            for t, sig in signals.items()
            if not t.startswith("_") and isinstance(sig, dict) and "composite" in sig
        ]
        if len(_vals) >= 2:
            _m = sum(_vals) / len(_vals)
            _std = math.sqrt(sum((v - _m) ** 2 for v in _vals) / len(_vals))
        else:
            _std = 0.20
        _rank_cs_norm = 0.4 / max(_std, 0.005)

        ranked = []
        for ticker, sig in signals.items():
            if ticker.startswith("_") or not isinstance(sig, dict):
                continue
            composite = sig.get("composite")
            if composite is not None:
                conviction = score_to_conviction(float(composite) * _rank_cs_norm)
                ranked.append(
                    {
                        "ticker": ticker,
                        "composite": composite,
                        "conviction": conviction.name,
                        "conviction_value": int(conviction),
                        "size_multiplier": conviction_size_multiplier(conviction),
                        "price": sig.get("price"),
                        "rsi": sig.get("rsi"),
                        "return_1d": sig.get("return_1d"),
                    }
                )
        ranked.sort(key=lambda x: x["composite"], reverse=True)
        return ranked

    def _backtest(self, signals: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        """
        Simple backtest: compute signal-implied returns over available history.

        Strategy: at each bar, equal-weight long the top quartile, short the bottom.
        Computes Sharpe, max drawdown, and hit rate on 1-day forward returns.
        """
        self._backtest_count += 1

        # Collect per-ticker (signal, return) pairs using all available history
        all_returns: list[float] = []
        hit_count = 0
        total_trades = 0

        for _ticker, data in market_data.items():
            if not isinstance(data, dict) or not data:
                continue
            prices = self._clean_prices(data.get("adjclose") or data.get("close", []))
            if len(prices) < 22:
                continue

            # compute rolling SMA-crossover signal for each bar and 1-day forward return
            for i in range(20, len(prices) - 1):
                window = prices[: i + 1]
                sma5 = sum(window[-5:]) / 5
                sma20 = sum(window[-20:]) / 20
                signal = 1.0 if sma5 > sma20 else -1.0
                fwd_ret = (prices[i + 1] - prices[i]) / prices[i] if prices[i] != 0 else 0.0
                strategy_ret = signal * fwd_ret
                all_returns.append(strategy_ret)
                total_trades += 1
                if strategy_ret > 0:
                    hit_count += 1

        if not all_returns:
            return {"sharpe": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0, "trades": 0}

        from omega.eval.sharpe import (
            sharpe_ratio as _canonical_sharpe,  # lazy: avoids circular import
        )

        mean_ret = sum(all_returns) / len(all_returns)
        # Annualised Sharpe (252 trading days)
        sharpe = _canonical_sharpe(all_returns)

        # Max drawdown on cumulative P&L
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in all_returns:
            cum += r
            if cum > peak:
                peak = cum
            dd = (peak - cum) / (peak + 1e-9)
            if dd > max_dd:
                max_dd = dd

        hit_rate = hit_count / total_trades if total_trades > 0 else 0.0

        self._last_sharpe = sharpe
        self._last_max_drawdown = max_dd
        self._last_hit_rate = hit_rate

        return {
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "hit_rate": hit_rate,
            "trades": total_trades,
            "mean_daily_return": mean_ret,
        }

    # ------------------------------------------------------------------ helpers

    def _compute_volatility(self, prices: list[float], window: int = 20) -> float:
        if len(prices) < window + 1:
            return 0.3
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(max(1, len(prices) - window), len(prices))
            if prices[i - 1] != 0
        ]
        if len(returns) < 2:
            return 0.3
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        daily_vol = math.sqrt(variance)
        return daily_vol * math.sqrt(252)  # annualised

    def _clean_prices(self, prices: list) -> list[float]:
        result = []
        for p in prices:
            if p is None:
                continue
            try:
                f = float(p)
                if not math.isnan(f) and not math.isinf(f):
                    result.append(f)
            except (TypeError, ValueError):
                continue
        return result

    def _calculate_slippage(
        self,
        order_size: float,
        daily_volume: float,
        base_spread_bps: float = 5.0,
        impact_bps: float = 10.0,
    ) -> float:
        """
        Estimate transaction slippage in basis points using a square-root impact model.

        Formula
        -------
          slippage_bps = base_spread_bps + impact_bps * sqrt(order_size / daily_volume)

        Parameters
        ----------
        order_size      : Size of the order (in currency units).
        daily_volume    : Average daily traded volume (same units as order_size).
        base_spread_bps : Half-spread cost for major crypto pairs (default 5 bps).
        impact_bps      : Market impact coefficient (default 10 bps).

        Returns
        -------
        Total estimated slippage in basis points.
        """
        if daily_volume <= 0.0:
            return base_spread_bps
        participation = max(0.0, order_size) / daily_volume
        return base_spread_bps + impact_bps * math.sqrt(participation)

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)

    def _filter_rate(self) -> float:
        """Fraction of conviction-screened proposals that were blocked by filters."""
        return self._proposals_filtered / max(1, self._proposals_generated)
