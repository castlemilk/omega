"""
omega.nodes.victoria.strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
StrategyNode — combines signals into portfolio decisions and backtests them.

Improvement arc:
  v1.0 — Equal-weight portfolio of buy-signal stocks
  v1.1 — Momentum-weighted portfolio (weight ∝ composite signal strength)
  v1.2 — Risk-parity-weighted portfolio (weight ∝ 1/volatility)
  v1.3 — Signal threshold tuning based on backtest Sharpe feedback
"""

import logging
import math
import time
import uuid
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.risk_manager import PositionRiskManager
from omega.nodes.victoria.spectral_signals import SpectralGraphSignal

logger = logging.getLogger("omega.nodes.victoria.strategy")

# Symbols excluded from trading (still used as regime/signal indicators).
# BTC has a 27.8% win rate — used only as a market regime indicator.
_TRADING_BLACKLIST: frozenset[str] = frozenset({"BTCUSDT"})

# Symbols excluded from LONG positions only (shorts still permitted).
# Only BTC excluded: used purely as regime indicator with <28% win rate.
# ETH longs re-enabled — signal system determines direction per cycle.
_LONG_BLACKLIST: frozenset[str] = frozenset({"BTCUSDT"})


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
        #   CRISIS/BEAR  → long=0.20 (suppressed), short=0.05 (permissive)
        #   BULL         → long=0.05 (permissive), short=0.20 (suppressed)
        #   NORMAL/other → long=0.10, short=0.10  (balanced)
        self._long_conviction_threshold: float = 0.10
        self._short_conviction_threshold: float = 0.10
        # Per-signal IC values loaded from signal_audit.py; empty = fall back to raw composite
        self._signal_ics: dict[str, float] = {}
        # Tracking counters
        self._proposals_generated: int = 0  # tickers that passed basic conviction screen
        self._proposals_filtered: int = 0  # tickers blocked by conviction filters
        # Time filter: don't open new positions within 2 cycles of last trade
        self._last_trade_cycle: int = -999

        # --- Sit-out filter counters ---
        self._sit_out_regime_count: int = 0  # uncertain regime → 75% size reduction
        self._sit_out_vol_low_count: int = 0  # dead-calm vol → full sit-out
        self._sit_out_vol_high_count: int = 0  # chaotic vol → 50% size reduction
        self._normal_trade_count: int = 0  # cycles with full-size trading

        # --- Sit-out thresholds (mutable so circuit breaker can adapt them) ---
        self._vol_low_threshold: float = 0.20  # percentile below which vol is "dead-calm"
        self._vol_high_threshold: float = 0.80  # percentile above which vol is "chaotic"

        # --- Spectral graph / Fiedler position size modifier ---
        self._spectral = SpectralGraphSignal(window=30)
        self._last_fiedler_scale: float = 1.0
        self._last_fiedler_tag: str = "warmup"

        # --- Portfolio risk manager (drawdown, correlation, vol, time, heat) ---
        self._risk = PositionRiskManager()
        # Optional RMT denoiser reference for correlation-based position limits.
        # Set via set_rmt_denoiser() after construction (avoids circular imports).
        self._rmt_denoiser: Any = None

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
            → long_threshold = 0.20  (longs heavily suppressed)
            → short_threshold = 0.05 (shorts very permissive — trade the trend)

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

        if bear_prob >= 0.55 or (bear_prob < 0.0 and regime_hmm == "bear"):
            self._long_conviction_threshold = 0.20
            self._short_conviction_threshold = 0.05
            logger.info(
                "Regime-adaptive: CRISIS/BEAR (bear_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.20, short_thresh=0.05",
                max(bear_prob, 0.0),
                regime_hmm,
            )
        elif bull_prob >= 0.55 or (bull_prob < 0.0 and regime_hmm == "bull"):
            self._long_conviction_threshold = 0.05
            self._short_conviction_threshold = 0.20
            logger.info(
                "Regime-adaptive: BULL (bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.05, short_thresh=0.20",
                max(bull_prob, 0.0),
                regime_hmm,
            )
        else:
            self._long_conviction_threshold = 0.10
            self._short_conviction_threshold = 0.10
            logger.debug(
                "Regime-adaptive: NORMAL (bear_prob=%.2f, bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.10, short_thresh=0.10",
                max(bear_prob, 0.0),
                max(bull_prob, 0.0),
                regime_hmm,
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

        # 2. Agreement ratio (base threshold, tightened in high-vol)
        vol_regime = sig.get("vol_regime", "normal")
        agreement_threshold = 0.7 if vol_regime == "high" else self._agreement_ratio_threshold
        ratio, _agreeing, _total = self._compute_agreement_ratio(sig)
        # Skip agreement ratio when there are no directional sub-signals (e.g. synthetic
        # adv_* tickers that carry only a composite value).  The composite itself serves
        # as the sole direction indicator in that case.
        if _total > 0 and ratio < agreement_threshold:
            return False, f"agreement_ratio({ratio:.2f}<{agreement_threshold:.2f})"

        # 3. Weighted conviction — use per-direction regime-adaptive threshold.
        # _apply_regime_adaptive_thresholds() sets these each cycle before the
        # per-ticker loop so CRISIS → lower short bar, BULL → lower long bar.
        w_conv = self._compute_weighted_conviction(sig)
        base_threshold = (
            self._long_conviction_threshold
            if direction == "long"
            else self._short_conviction_threshold
        )
        # In high per-ticker vol regime, tighten by 1.25x (less aggressive than old 1.5x
        # — regime-adaptive base already accounts for market-level volatility direction).
        conv_threshold = base_threshold * 1.25 if vol_regime == "high" else base_threshold
        if abs(w_conv) < conv_threshold:
            return False, f"weighted_conviction({abs(w_conv):.2f}<{conv_threshold:.2f})"

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

        # Set per-direction conviction thresholds based on current regime.
        # CRISIS/BEAR → shorts get lower bar (0.05), longs get higher bar (0.20).
        # BULL → longs get lower bar (0.05), shorts get higher bar (0.20).
        # NORMAL → balanced (0.10 each).
        self._apply_regime_adaptive_thresholds(signals)

        # Compute conviction for every ticker with a composite score
        # Skip metadata keys (_regime_probs, _regime_hmm, etc.)
        convictions: dict[str, ConvictionLevel] = {}
        for ticker, sig in signals.items():
            if ticker.startswith("_") or not isinstance(sig, dict):
                continue
            composite = sig.get("composite")
            if composite is not None:
                convictions[ticker] = score_to_conviction(float(composite))

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
            # Fallback: binary block at 35% threshold
            _regime_confidence_threshold = 0.35
            _block_longs = (
                _regime_hmm == "bear" and _regime_confidence >= _regime_confidence_threshold
            )
            _block_shorts = (
                _regime_hmm == "bull" and _regime_confidence >= _regime_confidence_threshold
            )

        # --- Fiedler spectral position size modifier (computed early for all paths) ---
        # λ₂ of the signal correlation graph Laplacian — low = signals fragmenting.
        _sv = self._build_spectral_vector(signals)
        _spectral_val = self._spectral.compute(_sv)
        _fiedler_scale = self._fiedler_size_scale(_spectral_val.value, _spectral_val.regime_tag)
        self._last_fiedler_scale = _fiedler_scale
        self._last_fiedler_tag = _spectral_val.regime_tag

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

        # Screen tickers that have non-HOLD conviction above signal threshold
        # and apply the full conviction filter stack.
        long_candidates: dict[str, Any] = {}
        proposals_this_cycle = 0
        filtered_this_cycle = 0
        regime_blocked_longs = 0
        regime_blocked_shorts = 0

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
            c = convictions.get(ticker, ConvictionLevel.HOLD)
            # Hard gate: HOLD conviction never generates a trade proposal.
            # This is explicit to make the invariant auditable — previously HOLD
            # fell through both branches silently; V32 diagnostics showed trades
            # firing against HOLD-level composites via edge cases in the filter stack.
            if c == ConvictionLevel.HOLD:
                continue
            if c in (ConvictionLevel.STRONG_BUY, ConvictionLevel.BUY):
                if ticker in _LONG_BLACKLIST:
                    logger.debug("Skipping %s (long blacklist)", ticker)
                    continue
                if sig.get("composite", 0.0) <= self._signal_threshold:
                    continue
                proposals_this_cycle += 1
                if _block_longs:
                    regime_blocked_longs += 1
                    continue
                passes, reason = self._passes_conviction_filters(
                    sig, current_cycle, direction="long"
                )
                if not passes:
                    filtered_this_cycle += 1
                    logger.debug("Filtered %s (long): %s", ticker, reason)
                    continue
                long_candidates[ticker] = sig
            elif c in (ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL):
                if sig.get("composite", 0.0) >= -self._signal_threshold:
                    continue
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

        # Apply conviction size multipliers; shorts get negative weights
        raw_weights: dict[str, float] = {}
        for ticker, w in long_base.items():
            raw_weights[ticker] = w * conviction_size_multiplier(convictions[ticker])
        for ticker, w in short_base.items():
            raw_weights[ticker] = -w * conviction_size_multiplier(convictions[ticker])

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

        # Record cycle as having produced trades (for time filter)
        if weights:
            self._last_trade_cycle = current_cycle

        return {
            "weights": weights,
            "positions": len(weights),
            "method": self._weighting,
            "signal_threshold": self._signal_threshold,
            "sit_out": sit_out_reason,
            "sit_out_size_mult": sit_out_size_mult,
            "fiedler_scale": round(_fiedler_scale, 4),
            "fiedler_regime": _spectral_val.regime_tag,
            "fiedler_zscore": round(float(_spectral_val.value), 4),
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
        ranked = []
        for ticker, sig in signals.items():
            if ticker.startswith("_") or not isinstance(sig, dict):
                continue
            composite = sig.get("composite")
            if composite is not None:
                conviction = score_to_conviction(float(composite))
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
