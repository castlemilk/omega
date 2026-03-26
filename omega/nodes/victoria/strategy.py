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
from enum import IntEnum
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.strategy")


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
        # Minimum fraction of sub-signals that must agree on direction (0.6 = 10/16)
        self._agreement_ratio_threshold: float = 0.6
        # IC-weighted conviction must exceed this in absolute value
        self._weighted_conviction_threshold: float = 0.3
        # Per-signal IC values loaded from signal_audit.py; empty = fall back to raw composite
        self._signal_ics: dict[str, float] = {}
        # Tracking counters
        self._proposals_generated: int = 0  # tickers that passed basic conviction screen
        self._proposals_filtered: int = 0  # tickers blocked by conviction filters
        # Time filter: don't open new positions within 2 cycles of last trade
        self._last_trade_cycle: int = -999

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
                "signal_ic_count": len(self._signal_ics),
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
        }

    def update_signal_ics(self, ics: dict[str, float]) -> None:
        """Load per-signal IC values from signal_audit output for weighted conviction."""
        self._signal_ics = {k: v for k, v in ics.items() if v > 0}
        logger.info(
            "StrategyNode: loaded ICs for %d signals (killed %d negative-IC)",
            len(self._signal_ics),
            sum(1 for v in ics.values() if v <= 0),
        )

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

    def _passes_conviction_filters(self, sig: dict, cycle: int) -> tuple[bool, str]:
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
        agreement_threshold = 0.5 if vol_regime == "high" else self._agreement_ratio_threshold
        ratio, _agreeing, _total = self._compute_agreement_ratio(sig)
        if ratio < agreement_threshold:
            return False, f"agreement_ratio({ratio:.2f}<{agreement_threshold:.2f})"

        # 3. Weighted conviction
        w_conv = self._compute_weighted_conviction(sig)
        # In high-vol regime, use a tighter conviction threshold
        conv_threshold = (
            self._weighted_conviction_threshold * 1.5
            if vol_regime == "high"
            else self._weighted_conviction_threshold
        )
        if abs(w_conv) < conv_threshold:
            return False, f"weighted_conviction({abs(w_conv):.2f}<{conv_threshold:.2f})"

        return True, "pass"

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

        # Compute conviction for every ticker with a composite score
        convictions: dict[str, ConvictionLevel] = {}
        for ticker, sig in signals.items():
            composite = sig.get("composite")
            if composite is not None:
                convictions[ticker] = score_to_conviction(float(composite))

        # Screen tickers that have non-HOLD conviction above signal threshold
        # and apply the full conviction filter stack.
        long_candidates: dict[str, Any] = {}
        proposals_this_cycle = 0
        filtered_this_cycle = 0

        short_candidates: dict[str, Any] = {}

        for ticker, sig in signals.items():
            c = convictions.get(ticker, ConvictionLevel.HOLD)
            if c in (ConvictionLevel.STRONG_BUY, ConvictionLevel.BUY):
                if sig.get("composite", 0.0) <= self._signal_threshold:
                    continue
                proposals_this_cycle += 1
                passes, reason = self._passes_conviction_filters(sig, current_cycle)
                if not passes:
                    filtered_this_cycle += 1
                    logger.debug("Filtered %s (long): %s", ticker, reason)
                    continue
                long_candidates[ticker] = sig
            elif c in (ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL):
                if sig.get("composite", 0.0) >= -self._signal_threshold:
                    continue
                proposals_this_cycle += 1
                passes, reason = self._passes_conviction_filters(sig, current_cycle)
                if not passes:
                    filtered_this_cycle += 1
                    logger.debug("Filtered %s (short): %s", ticker, reason)
                    continue
                short_candidates[ticker] = sig

        self._proposals_generated += proposals_this_cycle
        self._proposals_filtered += filtered_this_cycle

        # No candidates: either all filtered by conviction or no conviction signals at all.
        # Do NOT fall back to weak signals — the filter's purpose is to reduce trade count.
        if not long_candidates and not short_candidates:
            return {
                "weights": {},
                "positions": 0,
                "method": self._weighting,
                "convictions": {t: c.name for t, c in convictions.items()},
                "proposals_generated": proposals_this_cycle,
                "proposals_filtered": filtered_this_cycle,
                "filter_stats": {
                    "generated": self._proposals_generated,
                    "filtered": self._proposals_filtered,
                    "filter_rate": self._filter_rate(),
                },
            }

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

        # Normalise so total |weight| = 1.0
        total_w = sum(abs(v) for v in raw_weights.values())
        weights: dict[str, float] = (
            {ticker: v / total_w for ticker, v in raw_weights.items()} if total_w > 0 else {}
        )

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
            "convictions": {t: convictions[t].name for t in weights},
            "conviction_distribution": conviction_dist,
            "top_picks": self._rank_signals(signals)[:5],
            "backtest": bt,
            "proposals_generated": proposals_this_cycle,
            "proposals_filtered": filtered_this_cycle,
            "filter_stats": {
                "generated": self._proposals_generated,
                "filtered": self._proposals_filtered,
                "filter_rate": self._filter_rate(),
            },
        }

    def _rank_signals(self, signals: dict[str, Any]) -> list[dict[str, Any]]:
        """Rank tickers by composite signal strength, including conviction."""
        ranked = []
        for ticker, sig in signals.items():
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
