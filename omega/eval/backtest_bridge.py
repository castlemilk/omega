"""
omega.eval.backtest_bridge
~~~~~~~~~~~~~~~~~~~~~~~~~~~
OmegaBacktestBridge — runs the ACTUAL OmegaOrchestrator against historical
OHLCV data, cycle-by-cycle, without hardcoding any strategy logic.

Design
------
- Historical OHLCV data is fed to VectoraNode one bar at a time, simulating
  the live data-poll → signals → strategy → adversarial → execute pipeline.
- The bridge intercepts trade proposals and simulates execution at the next
  bar's open price (realistic fill assumption).
- All metrics go through omega.eval.sharpe and omega.eval.metrics.
- Three autonomy modes: PICO (deterministic), SUPERVISED (brain proposes,
  bridge auto-approves for backtest), AUTONOMOUS.
- Walk-forward: first TRAIN_FRACTION of data for in-sample optimisation,
  remainder for out-of-sample evaluation.

OHLCV format
------------
Each entry in `ohlcv` is a dict::

    {
        "timestamp": int,      # unix seconds or integer bar index
        "open":  float,
        "high":  float,
        "low":   float,
        "close": float,
        "volume": float,
    }

The bridge builds a sliding window of historical prices and feeds it to
VectoraNode on each cycle, mimicking DataIngestionNode's output format.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from omega.core.autonomy import AutonomyLevel
from omega.eval.baselines import BaselineResult, buy_and_hold, sma_crossover
from omega.eval.metrics import EvalReport, TradeRecord, build_eval_report
from omega.eval.significance import sharpe_is_significant
from omega.nodes.vectora.vectora_node import VectoraNode

logger = logging.getLogger("omega.eval.backtest_bridge")

TRAIN_FRACTION = 0.60  # first 60% = in-sample, last 40% = out-of-sample


class BacktestMode(str, Enum):  # noqa: UP042
    PICO = "pico"  # deterministic signals only
    SUPERVISED = "supervised"  # brain proposes, bridge auto-approves
    AUTONOMOUS = "autonomous"  # brain operates freely


@dataclass
class CycleRecord:
    """Per-cycle record of what happened during the backtest."""

    bar_index: int
    timestamp: int
    close_price: float
    position: float  # fractional position (-1 to 1), 0 = flat
    signals: dict[str, Any] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    adversarial_flags: list[dict[str, Any]] = field(default_factory=list)
    autonomy_level: str = AutonomyLevel.PICO.value
    trade_executed: bool = False
    pnl: float = 0.0  # unrealised PnL for this bar while in position
    realised_pnl: float = 0.0  # realised PnL if position closed this bar
    equity: float = 1.0


@dataclass
class BacktestResult:
    """Full result of a backtest run."""

    mode: str
    ticker: str
    n_bars: int
    n_cycles: int

    cycles: list[CycleRecord] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)

    # Walk-forward split
    in_sample_returns: list[float] = field(default_factory=list)
    out_of_sample_returns: list[float] = field(default_factory=list)

    # Baseline comparisons
    baselines: dict[str, BaselineResult] = field(default_factory=dict)

    # Final metrics
    report: EvalReport | None = None


class OmegaBacktestBridge:
    """
    Runs the actual OmegaOrchestrator pipeline against historical OHLCV data.

    Parameters
    ----------
    mode              : BacktestMode (PICO / SUPERVISED / AUTONOMOUS).
    ticker            : Primary ticker symbol (used as key in market_data dict).
    lookback_window   : Number of historical bars fed to the signal node per cycle.
    initial_capital   : Starting portfolio value.
    commission        : Per-trade commission as fraction (e.g. 0.001 = 0.1%).
    periods_per_year  : Annualisation factor for Sharpe.
    use_orchestrator_proposals : If True (default), use proposals from the full
        orchestrator cycle (includes adversarial filtering).  If False, fall back
        to calling VectoraNode._do_construct_portfolio directly (bypasses adversarial
        but avoids any orchestrator overhead).
    """

    def __init__(
        self,
        mode: BacktestMode = BacktestMode.PICO,
        ticker: str = "BTCUSDT",
        lookback_window: int = 60,
        initial_capital: float = 1.0,
        commission: float = 0.001,
        periods_per_year: int = 252,
        use_orchestrator_proposals: bool = True,
    ) -> None:
        self.mode = mode
        self.ticker = ticker
        self.lookback_window = lookback_window
        self.initial_capital = initial_capital
        self.commission = commission
        self.periods_per_year = periods_per_year
        self.use_orchestrator_proposals = use_orchestrator_proposals

        # Build orchestrator with a VectoraNode (lazy import breaks circular dependency)
        from omega.core.orchestrator_v2 import OmegaOrchestrator

        self._node = VectoraNode()
        self._orchestrator = OmegaOrchestrator(name=f"backtest_{mode.value}")
        self._orchestrator.register_node(self._node, activate=True)

        # Set autonomy level to match mode
        node_id = self._node.get_state().node_id
        self._node_id = node_id
        level_map = {
            BacktestMode.PICO: AutonomyLevel.PICO,
            BacktestMode.SUPERVISED: AutonomyLevel.SUPERVISED,
            BacktestMode.AUTONOMOUS: AutonomyLevel.AUTONOMOUS,
        }
        # GraduatedAutonomyController uses _cache[node_id] as NodeAutonomyState
        autonomy_state = self._orchestrator._autonomy._cache.get(node_id)
        if autonomy_state is not None:
            autonomy_state.level = level_map[mode]

    def run(self, ohlcv: Sequence[dict[str, Any]]) -> BacktestResult:
        """
        Run the backtest over historical OHLCV bars.

        Each cycle corresponds to one bar. The bridge:
          1. Builds a sliding window of historical prices (lookback_window bars).
          2. Constructs market_data in VectoraNode's expected format.
          3. Calls orchestrator.run_one_cycle() with injected market data.
          4. Interprets proposals as position targets and fills at next bar's open.
          5. Records per-cycle metrics.

        Parameters
        ----------
        ohlcv : List of bar dicts with keys: timestamp, open, high, low, close, volume.

        Returns
        -------
        BacktestResult with full cycle log, returns series, and EvalReport.
        """
        bars = list(ohlcv)
        n = len(bars)
        if n < self.lookback_window + 2:
            raise ValueError(
                f"Need at least {self.lookback_window + 2} bars, got {n}. "
                "Reduce lookback_window or provide more data."
            )

        result = BacktestResult(
            mode=self.mode.value,
            ticker=self.ticker,
            n_bars=n,
            n_cycles=0,
        )

        # Compute close-price-only baseline inputs
        closes = [float(b["close"]) for b in bars]

        # -- Walk-forward split --
        split_idx = int(n * TRAIN_FRACTION)

        # -- Simulate cycle-by-cycle --
        position: float = 0.0  # 0 = flat, 1 = long, -1 = short
        entry_price: float = 0.0
        equity: float = self.initial_capital
        cycle_records: list[CycleRecord] = []
        returns: list[float] = []
        trades: list[TradeRecord] = []

        # Patch VectoraNode's DataIngestionNode to use injected data
        # We intercept by overriding the internal _last_market_data directly.

        for i in range(self.lookback_window, n - 1):
            bar = bars[i]
            next_bar = bars[i + 1]

            close = float(bar["close"])
            next_open = float(next_bar["open"])

            # Build market_data window for this cycle
            window_bars = bars[i - self.lookback_window : i + 1]
            market_data = self._build_market_data(window_bars)

            # Inject data directly into VectoraNode (bypassing network fetch)
            self._node._last_market_data = market_data

            # Run one full orchestrator cycle (signals → strategy → adversarial)
            cycle_result = self._orchestrator.run_one_cycle()

            # Extract proposals.
            # Orchestrator mode (default): use proposals from the full pipeline,
            # which includes adversarial filtering.  The signal adapter in
            # _do_construct_portfolio ensures the orchestrator-wrapped signal format
            # is correctly normalised before reaching StrategyNode.
            # Direct mode (fallback): call _do_construct_portfolio manually, which
            # bypasses adversarial but is simpler to debug.
            proposals: list[dict[str, Any]] = []
            if self.use_orchestrator_proposals and cycle_result.proposals:
                proposals = cycle_result.proposals
            else:
                try:
                    from omega.core.node import NodeInput

                    port_inp = NodeInput(
                        action="construct_portfolio",
                        parameters={
                            "signals": self._node._last_signals,
                            "market_data": market_data,
                            "pico_mode": self.mode == BacktestMode.PICO,
                            "regime": "default",
                        },
                        context={"cycle_id": "backtest", "cycle": i},
                    )
                    proposals = self._node._do_construct_portfolio(port_inp)
                except Exception as exc:
                    logger.debug("Portfolio extraction failed at bar %d: %s", i, exc)

            # Determine target position from proposals
            target_position = self._proposals_to_position(proposals)

            # Simulate trade fill at next bar's open
            bar_pnl = 0.0
            realised_pnl = 0.0
            trade_executed = False

            if position != target_position:
                # Close existing position
                if position != 0.0 and entry_price != 0.0:
                    raw_pnl = (next_open - entry_price) / entry_price * position
                    net_pnl = raw_pnl - self.commission
                    realised_pnl = net_pnl
                    equity *= 1.0 + net_pnl
                    trades.append(
                        TradeRecord(
                            pnl=net_pnl,
                            entry_price=entry_price,
                            exit_price=next_open,
                            size=position,
                            timestamp=i,
                        )
                    )
                    trade_executed = True

                # Open new position
                if target_position != 0.0:
                    entry_price = next_open * (1.0 + self.commission * abs(target_position))
                    position = target_position
                    trade_executed = True
                else:
                    position = 0.0
                    entry_price = 0.0

            # Unrealised PnL for current bar (mark-to-market)
            if position != 0.0 and entry_price != 0.0:
                bar_pnl = (next_open - entry_price) / entry_price * position

            # Bar return (what the strategy earned this bar)
            if i > self.lookback_window:
                prev_close = float(bars[i - 1]["close"])
                bar_return = (
                    (close - prev_close) / prev_close * position if prev_close != 0 else 0.0
                )
            else:
                bar_return = 0.0

            returns.append(bar_return)

            rec = CycleRecord(
                bar_index=i,
                timestamp=int(bar.get("timestamp", i)),
                close_price=close,
                position=position,
                signals=dict(self._node._last_signals),
                proposals=proposals,
                adversarial_flags=[
                    f.__dict__ if hasattr(f, "__dict__") else f
                    for f in cycle_result.adversarial_flags
                ],
                autonomy_level=self._orchestrator._autonomy.get_level(self._node_id).value,
                trade_executed=trade_executed,
                pnl=bar_pnl,
                realised_pnl=realised_pnl,
                equity=equity,
            )
            cycle_records.append(rec)

        result.cycles = cycle_records
        result.returns = returns
        result.trades = trades
        result.n_cycles = len(cycle_records)

        # Walk-forward split on returns (aligned with bars after lookback)
        effective_split = split_idx - self.lookback_window
        effective_split = max(1, min(effective_split, len(returns) - 1))
        result.in_sample_returns = returns[:effective_split]
        result.out_of_sample_returns = returns[effective_split:]

        # Compute mandatory baselines on the same price window
        eval_prices = closes[self.lookback_window :]
        result.baselines["buy_and_hold"] = buy_and_hold(eval_prices, self.periods_per_year)
        result.baselines["sma_crossover"] = sma_crossover(
            eval_prices, periods_per_year=self.periods_per_year
        )

        # Build benchmark returns for IR calculation
        bnh = result.baselines["buy_and_hold"]

        # Build EvalReport
        result.report = build_eval_report(
            strategy_name=f"omega_{self.mode.value}",
            mode=self.mode.value,
            returns=returns,
            trades=trades,
            benchmark_returns=bnh.returns if bnh.returns else None,
            in_sample_returns=result.in_sample_returns,
            out_of_sample_returns=result.out_of_sample_returns,
            periods_per_year=self.periods_per_year,
        )

        self._log_summary(result)
        return result

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_market_data(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Build VectoraNode's expected market_data dict from a window of OHLCV bars.

        DataIngestionNode returns::

            {ticker: {"close": [...], "volume": [...], "open": [...], ...}}
        """
        closes = [float(b["close"]) for b in bars]
        opens = [float(b["open"]) for b in bars]
        highs = [float(b["high"]) for b in bars]
        lows = [float(b["low"]) for b in bars]
        volumes = [float(b.get("volume", 0.0)) for b in bars]
        timestamps = [int(b.get("timestamp", i)) for i, b in enumerate(bars)]

        return {
            self.ticker: {
                "close": closes,
                "adjclose": closes,
                "open": opens,
                "high": highs,
                "low": lows,
                "volume": volumes,
                "timestamps": timestamps,
            }
        }

    def _proposals_to_position(self, proposals: list[dict[str, Any]]) -> float:
        """
        Convert orchestrator proposals to a scalar position target.

        -1.0 = full short, 0.0 = flat, 1.0 = full long.

        Handles both legacy proposal formats (action/direction/weight keys) and
        StrategyNode's portfolio format (weights dict with ticker keys).
        Falls back to flat if no clear signal.
        """
        if not proposals:
            return 0.0

        # Aggregate signals across proposals
        signals: list[float] = []
        for prop in proposals:
            if not isinstance(prop, dict):
                continue
            action = prop.get("action", "").lower()
            direction = prop.get("direction", "").lower()
            weight = prop.get("weight", prop.get("size", 0.0))

            if action in ("buy", "long") or direction == "long":
                signals.append(float(weight) if weight else 1.0)
            elif action in ("sell", "short") or direction == "short":
                signals.append(-float(weight) if weight else -1.0)
            elif "composite" in prop:
                signals.append(float(prop["composite"]))
            elif isinstance(weight, (int, float)) and weight != 0:
                signals.append(float(weight))
            elif "weights" in prop and isinstance(prop["weights"], dict):
                # StrategyNode portfolio format: {"weights": {ticker: float}, ...}
                # Any non-zero allocation = long; sum of weights as position size
                total_weight = sum(prop["weights"].values())
                if total_weight > 0:
                    signals.append(min(1.0, total_weight))

        if not signals:
            return 0.0

        avg = sum(signals) / len(signals)
        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, avg))

    def _log_summary(self, result: BacktestResult) -> None:
        """Log a concise backtest summary."""
        r = result.report
        if r is None:
            return

        bnh = result.baselines.get("buy_and_hold")
        sma = result.baselines.get("sma_crossover")

        logger.info(
            "Backtest complete | mode=%s ticker=%s bars=%d trades=%d",
            result.mode,
            result.ticker,
            result.n_bars,
            r.n_trades,
        )
        sig, point, (ci_lo, ci_hi) = sharpe_is_significant(
            result.returns, periods_per_year=self.periods_per_year
        )
        logger.info(
            "  Strategy: Sharpe=%.3f [95%% CI: %.3f, %.3f] significant=%s"
            " MaxDD=%.1f%% TotalRet=%.1f%%",
            point,
            ci_lo,
            ci_hi,
            sig,
            r.max_drawdown * 100,
            r.total_return * 100,
        )
        logger.info(
            "  Walk-forward: IS_Sharpe=%.3f OOS_Sharpe=%.3f",
            r.in_sample_sharpe,
            r.out_of_sample_sharpe,
        )
        if bnh:
            logger.info(
                "  vs Buy&Hold: Sharpe=%.3f TotalRet=%.1f%%",
                bnh.sharpe,
                bnh.total_return * 100,
            )
        if sma:
            logger.info(
                "  vs SMA Crossover: Sharpe=%.3f TotalRet=%.1f%%",
                sma.sharpe,
                sma.total_return * 100,
            )
