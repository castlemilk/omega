"""omega.core.bridge_evaluator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
BridgeEvaluator — ImprovementEvaluator subclass that wires the honest
OmegaBacktestBridge into the TPE improvement loop.

Design
------
- Each TPE trial uses an expanding in-sample window (data up to cycle N)
  and evaluates on the next N+1 to N+K out-of-sample bars.
- The Sharpe confidence interval is computed via bootstrap on the OOS
  returns; if the CI spans zero, the trial is **rejected** (score = -1.0).
- ``min_oos_periods`` (default 60) is enforced: trials with fewer OOS bars
  return a large negative score immediately without running the backtest.
- Window boundaries are logged at INFO level for every evaluation.

Usage
-----
    from omega.core.bridge_evaluator import BridgeEvaluator
    from omega.eval.backtest_bridge import OmegaBacktestBridge

    evaluator = BridgeEvaluator(ohlcv=bars, min_oos_periods=60)
    engine = ImprovementEngine(evaluator=evaluator)
    engine.register_node("node-1", param_space=[...])
    trial = engine.evaluate_and_record("node-1", params, context={"cycle": 5})
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

from omega.core.improvement_engine import ImprovementEvaluator, composite_score

# Heavy imports (backtest_bridge pulls in the full orchestrator stack) are done
# lazily inside evaluate() to avoid circular imports at module load time.
# At module scope we only import the lightweight sharpe utilities.
from omega.eval.sharpe import compute_sharpe, compute_sharpe_confidence_interval

logger = logging.getLogger("omega.core.bridge_evaluator")

# Score returned when a trial is rejected
_REJECTED_SCORE = -1.0
_INSUFFICIENT_DATA_SCORE = -999.0


class BridgeEvaluator(ImprovementEvaluator):
    """
    ImprovementEvaluator that runs OmegaBacktestBridge with expanding
    walk-forward windows and CI-based rejection.

    Parameters
    ----------
    ohlcv             : Full historical OHLCV bar sequence.  Each bar is a
                        dict with keys: timestamp, open, high, low, close, volume.
    min_oos_periods   : Minimum number of out-of-sample bars required for
                        a valid evaluation.  Default 60.
    min_is_bars       : Minimum in-sample bars before any OOS window starts.
                        Default 120.
    expansion_step    : Number of additional IS bars added per cycle. Default 10.
    ticker            : Ticker symbol forwarded to OmegaBacktestBridge.
    mode              : BacktestMode (PICO / SUPERVISED / AUTONOMOUS).
    lookback_window   : Lookback window forwarded to OmegaBacktestBridge.
    ci_confidence     : Bootstrap CI confidence level (default 0.95).
    n_bootstrap       : Bootstrap resamples for CI (default 500).
    commission        : Per-trade commission fraction (default 0.001).
    periods_per_year  : Annualisation factor (default 252).
    """

    def __init__(
        self,
        ohlcv: Sequence[dict[str, Any]],
        min_oos_periods: int = 60,
        min_is_bars: int = 120,
        expansion_step: int = 10,
        ticker: str = "BTCUSDT",
        mode: Any = None,  # BacktestMode.PICO default; imported lazily to avoid circular import
        lookback_window: int = 60,
        ci_confidence: float = 0.95,
        n_bootstrap: int = 500,
        commission: float = 0.001,
        periods_per_year: int = 252,
    ) -> None:
        from omega.eval.backtest_bridge import BacktestMode  # lazy

        self._ohlcv = list(ohlcv)
        self._min_oos_periods = min_oos_periods
        self._min_is_bars = min_is_bars
        self._expansion_step = expansion_step
        self._ticker = ticker
        self._mode = mode if mode is not None else BacktestMode.PICO
        self._lookback_window = lookback_window
        self._ci_confidence = ci_confidence
        self._n_bootstrap = n_bootstrap
        self._commission = commission
        self._periods_per_year = periods_per_year

        self._trial_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # ImprovementEvaluator interface
    # ------------------------------------------------------------------

    def evaluate(
        self,
        node_id: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        """
        Evaluate params using the honest OmegaBacktestBridge.

        Expanding-window protocol
        ~~~~~~~~~~~~~~~~~~~~~~~~~
        IS window = ohlcv[ 0 : is_end ]
        OOS window = ohlcv[ is_end : oos_end ]

        ``is_end`` grows by ``expansion_step`` bars per cycle so the TPE
        sees progressively more history as training matures.

        Returns
        -------
        (score, metrics) where score < 0 indicates a rejected trial.
        """
        ctx = context or {}

        with self._lock:
            trial_idx = self._trial_count
            self._trial_count += 1

        cycle = int(ctx.get("cycle", trial_idx))

        # Compute expanding window boundaries
        is_end = self._min_is_bars + cycle * self._expansion_step
        oos_end = is_end + self._min_oos_periods

        total_bars = len(self._ohlcv)

        logger.info(
            "BridgeEvaluator: node=%s cycle=%d is_end=%d oos_end=%d total=%d",
            node_id,
            cycle,
            is_end,
            oos_end,
            total_bars,
        )

        # Enforce min_oos_periods: we need at least is_end + min_oos_periods bars.
        # Do NOT shrink is_end to compensate — that would corrupt the expanding window.
        available_oos = total_bars - is_end
        if available_oos < self._min_oos_periods:
            logger.warning(
                "BridgeEvaluator: insufficient OOS data: %d bars available, %d required. "
                "Skipping evaluation for node=%s cycle=%d.",
                available_oos,
                self._min_oos_periods,
                node_id,
                cycle,
            )
            return _INSUFFICIENT_DATA_SCORE, {
                "rejected": True,
                "reason": "insufficient_oos_periods",
                "oos_count": available_oos,
                "min_oos_periods": self._min_oos_periods,
                "is_end": is_end,
                "oos_end": oos_end,
                "cycle": cycle,
            }

        # The bridge needs at least lookback_window + 2 bars
        window = self._ohlcv[:oos_end]
        min_bridge_bars = self._lookback_window + 2
        if len(window) < min_bridge_bars:
            logger.warning(
                "BridgeEvaluator: window too small for bridge (%d < %d). node=%s",
                len(window),
                min_bridge_bars,
                node_id,
            )
            return _INSUFFICIENT_DATA_SCORE, {
                "rejected": True,
                "reason": "window_too_small_for_bridge",
                "window_size": len(window),
                "min_bridge_bars": min_bridge_bars,
                "cycle": cycle,
            }

        # Run the honest backtest (lazy import to avoid circular dependency)
        from omega.eval.backtest_bridge import OmegaBacktestBridge

        bridge = OmegaBacktestBridge(
            mode=self._mode,
            ticker=self._ticker,
            lookback_window=self._lookback_window,
            commission=self._commission,
            periods_per_year=self._periods_per_year,
        )

        # Attempt to apply TPE params to the VectoraNode's strategy.
        # This is best-effort: unknown params are silently ignored.
        self._apply_params_to_node(bridge, params)

        try:
            result = bridge.run(window)
        except Exception as exc:
            logger.warning("BridgeEvaluator: bridge.run() failed for node=%s: %s", node_id, exc)
            return _INSUFFICIENT_DATA_SCORE, {
                "rejected": True,
                "reason": f"bridge_error: {exc}",
                "cycle": cycle,
            }

        oos_returns = result.out_of_sample_returns

        # Enforce min_oos_periods on actual OOS returns produced by the bridge
        if len(oos_returns) < self._min_oos_periods:
            logger.warning(
                "BridgeEvaluator: bridge produced only %d OOS returns (need %d). node=%s",
                len(oos_returns),
                self._min_oos_periods,
                node_id,
            )
            return _INSUFFICIENT_DATA_SCORE, {
                "rejected": True,
                "reason": "insufficient_oos_returns_from_bridge",
                "oos_count": len(oos_returns),
                "min_oos_periods": self._min_oos_periods,
                "is_end": is_end,
                "oos_end": oos_end,
                "cycle": cycle,
            }

        # Compute bootstrap Sharpe CI on OOS returns
        ci_lo, ci_hi = compute_sharpe_confidence_interval(
            oos_returns,
            confidence=self._ci_confidence,
            n_bootstrap=self._n_bootstrap,
            periods_per_year=self._periods_per_year,
        )

        oos_sharpe = compute_sharpe(oos_returns, periods_per_year=self._periods_per_year)
        report = result.report

        base_metrics: dict[str, Any] = {
            "ci_lower": round(ci_lo, 4),
            "ci_upper": round(ci_hi, 4),
            "oos_sharpe": round(oos_sharpe, 4),
            "oos_count": len(oos_returns),
            "is_end": is_end,
            "oos_end": oos_end,
            "window_size": len(window),
            "cycle": cycle,
        }
        if report is not None:
            base_metrics.update(
                {
                    "in_sample_sharpe": round(report.in_sample_sharpe, 4),
                    "total_return": round(report.total_return, 4),
                    "max_drawdown": round(report.max_drawdown, 4),
                    "n_trades": report.n_trades,
                }
            )

        # Reject if the CI spans zero (no statistical edge)
        if ci_lo < 0.0 and ci_hi > 0.0:
            logger.info(
                "BridgeEvaluator: CI [%.4f, %.4f] spans zero — rejecting trial. "
                "node=%s cycle=%d oos_sharpe=%.4f",
                ci_lo,
                ci_hi,
                node_id,
                cycle,
                oos_sharpe,
            )
            return _REJECTED_SCORE, {**base_metrics, "rejected": True, "reason": "ci_spans_zero"}

        # Build composite score from OOS Sharpe and max drawdown
        mdd_neg = -abs(report.max_drawdown) if report is not None else 0.0
        score = composite_score(oos_sharpe, mdd_neg)

        logger.info(
            "BridgeEvaluator: accepted trial. node=%s cycle=%d score=%.4f "
            "oos_sharpe=%.4f CI=[%.4f, %.4f]",
            node_id,
            cycle,
            score,
            oos_sharpe,
            ci_lo,
            ci_hi,
        )
        return score, {**base_metrics, "rejected": False, "composite": round(score, 4)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_params_to_node(self, bridge: Any, params: dict[str, Any]) -> None:
        """
        Best-effort application of TPE params to the bridge's VectoraNode
        strategy.  Unknown params are silently ignored so the bridge always
        runs, even when params don't map to known attributes.
        """
        strategy = getattr(bridge._node, "_strategy", None)
        if strategy is None:
            return
        for key, value in params.items():
            if hasattr(strategy, key):
                import contextlib

                with contextlib.suppress(Exception):
                    setattr(strategy, key, value)

    @property
    def trial_count(self) -> int:
        """Number of evaluate() calls made so far."""
        with self._lock:
            return self._trial_count
