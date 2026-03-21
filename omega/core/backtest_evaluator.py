"""omega.core.backtest_evaluator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
BacktestEvaluator: plugs real backtest runs into the TPE improvement loop.

Implements ImprovementEvaluator by running a parameterised strategy over a
fixed out-of-sample window, returning the Sharpe ratio as the score.

Walk-forward design
-------------------
- ``oos_start`` / ``oos_end`` define the out-of-sample evaluation window.
- All TPE trials are scored on the *same* OOS window so results are comparable.
- In-sample data is not used here — the TPE itself is the "model"; the backtest
  is purely the objective function.

Thread safety
-------------
A threading.Lock guards the result cache so the TPE can safely evaluate
multiple configurations in parallel threads.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import date
from typing import Any, ClassVar

from omega.core.improvement_engine import (
    ImprovementEvaluator,
    _max_drawdown,
    _sharpe_ratio,
    composite_score,
)

logger = logging.getLogger("omega.core.backtest_evaluator")

# ---------------------------------------------------------------------------
# Strategy helpers (parameterised versions of backtest.py's helpers)
# ---------------------------------------------------------------------------


def _sma(prices: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(prices)):
        if i < window - 1:
            result.append(None)
        else:
            result.append(sum(prices[i - window + 1 : i + 1]) / window)
    return result


def _rsi(prices: list[float], window: int = 14) -> list[float | None]:
    if len(prices) <= window:
        return [None] * len(prices)
    result: list[float | None] = [None] * window
    gains = []
    losses = []
    for i in range(1, window + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window

    for i in range(window, len(prices)):
        delta = prices[i] - prices[i - 1]
        g = max(delta, 0.0)
        lo = max(-delta, 0.0)
        avg_gain = (avg_gain * (window - 1) + g) / window
        avg_loss = (avg_loss * (window - 1) + lo) / window
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1.0 + rs))
    return result


def _run_parameterised_strategy(
    prices: list[float],
    short_window: int,
    long_window: int,
    rsi_window: int,
    rsi_overbought: float,
    rsi_enabled: bool,
) -> tuple[list[float], list[float]]:
    """
    Run a parameterised SMA-crossover strategy (optionally gated by RSI).

    Returns (daily_returns, equity_curve).
    """
    sma_s = _sma(prices, short_window)
    sma_l = _sma(prices, long_window)
    rsi_vals = _rsi(prices, rsi_window) if rsi_enabled else [50.0] * len(prices)

    daily_rets: list[float] = []
    equity: list[float] = [1.0]
    position = 0.0

    for i in range(1, len(prices)):
        if sma_s[i] is None or sma_l[i] is None or rsi_vals[i] is None:
            daily_rets.append(0.0)
            equity.append(equity[-1])
            continue

        prev_s = sma_s[i - 1]
        prev_l = sma_l[i - 1]
        if prev_s is None or prev_l is None:
            daily_rets.append(0.0)
            equity.append(equity[-1])
            continue

        cur_s: float = sma_s[i]  # type: ignore[assignment]
        cur_l: float = sma_l[i]  # type: ignore[assignment]
        rsi_ok = float(rsi_vals[i]) < rsi_overbought  # type: ignore[arg-type]

        # Golden cross → enter long (RSI gate optional)
        if prev_s <= prev_l and cur_s > cur_l and position == 0.0:
            if not rsi_enabled or rsi_ok:
                position = 1.0
                _entry_price = prices[i]

        # Death cross → exit long
        elif prev_s >= prev_l and cur_s < cur_l and position == 1.0:
            position = 0.0

        daily_ret = position * (prices[i] - prices[i - 1]) / prices[i - 1]
        daily_rets.append(daily_ret)
        equity.append(equity[-1] * (1.0 + daily_ret))

    return daily_rets, equity


# ---------------------------------------------------------------------------
# Synthetic data generator (no external deps)
# ---------------------------------------------------------------------------


def _generate_synthetic_prices(symbol: str, start_date: str, end_date: str) -> list[float]:
    """Deterministic geometric random walk seeded by symbol name."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = (end - start).days

    seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    lcg_state = seed
    price = 100.0 + (seed % 900)
    prices = [price]

    for _ in range(days):
        lcg_state = (lcg_state * 1664525 + 1013904223) & 0xFFFFFFFF
        pct = ((lcg_state % 10000) / 10000.0 - 0.5) * 0.04
        price = price * (1.0 + pct)
        prices.append(price)

    return prices


# ---------------------------------------------------------------------------
# BacktestEvaluator
# ---------------------------------------------------------------------------


class BacktestEvaluator(ImprovementEvaluator):
    """
    Evaluate a parameter configuration by running a real backtest.

    Parameters recognised in the ``params`` dict
    ---------------------------------------------
    short_window : int   — SMA short period (default 10)
    long_window  : int   — SMA long period  (default 30)
    rsi_window   : int   — RSI period       (default 14)
    rsi_overbought : float — RSI upper gate (default 70.0)
    rsi_enabled  : int/bool — 0 disables RSI gate (default 1)

    Walk-forward
    ------------
    All evaluations use the out-of-sample window [oos_start, oos_end].
    Setting ``use_oos=False`` uses the full window (useful for debugging).

    Caching
    -------
    Results are cached by a hash of (node_id, sorted params).  The cache
    is bounded to ``max_cache`` entries (LRU eviction via insertion order).
    """

    _PARAM_DEFAULTS: ClassVar[dict[str, Any]] = {
        "short_window": 10,
        "long_window": 30,
        "rsi_window": 14,
        "rsi_overbought": 70.0,
        "rsi_enabled": 1,
    }

    def __init__(
        self,
        symbols: list[str] | None = None,
        oos_start: str = "2024-01-01",
        oos_end: str = "2024-12-31",
        use_oos: bool = True,
        sharpe_weight: float = 0.7,
        dd_weight: float = 0.3,
        max_cache: int = 512,
        allow_synthetic: bool = False,
    ) -> None:
        self._symbols = symbols or ["BTCUSDT"]
        self._oos_start = oos_start
        self._oos_end = oos_end
        self._use_oos = use_oos
        self._sharpe_weight = sharpe_weight
        self._dd_weight = dd_weight
        self._max_cache = max_cache
        self._allow_synthetic = allow_synthetic

        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
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
        Run a parameterised backtest and return (score, metrics).

        score is the composite of Sharpe + drawdown; higher is better.
        """
        resolved = self._resolve_params(params)
        cache_key = self._cache_key(node_id, resolved)

        with self._lock:
            if cache_key in self._cache:
                logger.debug("Cache hit for node=%s key=%s", node_id, cache_key[:8])
                return self._cache[cache_key]

        score, metrics = self._run_backtest(resolved)

        with self._lock:
            if len(self._cache) >= self._max_cache:
                # Evict oldest entry (dict preserves insertion order in Python 3.7+)
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[cache_key] = (score, metrics)

        logger.debug(
            "Evaluated node=%s score=%.4f sharpe=%.4f dd=%.4f params=%s",
            node_id,
            score,
            metrics.get("sharpe", 0.0),
            metrics.get("max_drawdown", 0.0),
            resolved,
        )
        return score, metrics

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Merge supplied params with defaults; clamp windows to valid ranges."""
        resolved = dict(self._PARAM_DEFAULTS)
        resolved.update(params)

        short = max(2, int(resolved["short_window"]))
        long_ = max(short + 1, int(resolved["long_window"]))
        resolved["short_window"] = short
        resolved["long_window"] = long_
        resolved["rsi_window"] = max(2, int(resolved["rsi_window"]))
        resolved["rsi_overbought"] = float(resolved["rsi_overbought"])
        resolved["rsi_enabled"] = bool(int(resolved["rsi_enabled"]))
        return resolved

    def _cache_key(self, node_id: str, params: dict[str, Any]) -> str:
        parts = f"{node_id}:" + ":".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hashlib.sha256(parts.encode()).hexdigest()

    def _run_backtest(self, params: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """Run strategy over all symbols and aggregate metrics."""
        start = self._oos_start
        end = self._oos_end

        all_returns: list[float] = []
        all_equity: list[float] = [1.0]

        for symbol in self._symbols:
            # Try real data first; fall back to synthetic
            prices = self._load_prices(symbol, start, end)
            if len(prices) < params["long_window"] + 5:
                # Not enough bars — return neutral score
                logger.warning(
                    "Insufficient data for %s (%d bars), using neutral score.",
                    symbol,
                    len(prices),
                )
                return 0.0, {"sharpe": 0.0, "max_drawdown": 0.0, "composite": 0.0}

            rets, equity = _run_parameterised_strategy(
                prices=prices,
                short_window=params["short_window"],
                long_window=params["long_window"],
                rsi_window=params["rsi_window"],
                rsi_overbought=params["rsi_overbought"],
                rsi_enabled=params["rsi_enabled"],
            )
            all_returns.extend(rets)
            # Combine equity curves multiplicatively
            if equity:
                all_equity[-1] *= equity[0]
                all_equity.extend(equity[1:])

        if not all_returns:
            return 0.0, {"sharpe": 0.0, "max_drawdown": 0.0, "composite": 0.0}

        sharpe = _sharpe_ratio(all_returns)
        mdd = _max_drawdown(all_equity)  # negative value, lower is worse
        comp = composite_score(sharpe, mdd, self._sharpe_weight, self._dd_weight)

        metrics = {
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 4),
            "composite": round(comp, 4),
            "n_bars": len(all_returns),
            "total_return": round(sum(all_returns), 4),
            "oos_start": self._oos_start,
            "oos_end": self._oos_end,
        }
        return comp, metrics

    def _load_prices(self, symbol: str, start: str, end: str) -> list[float]:
        """
        Load closing prices from DataIngestionNode.

        When ``allow_synthetic=False`` (the default), raises ``ValueError`` if
        real data is unavailable — no silent fallback to noise.
        When ``allow_synthetic=True``, falls back to synthetic prices and logs a
        loud WARNING so callers know results are not meaningful.
        """
        try:
            return self._load_real_prices(symbol, start, end)
        except Exception as exc:
            if not self._allow_synthetic:
                raise ValueError(
                    "No real market data available. "
                    "Pass allow_synthetic=True to use synthetic data for testing only."
                ) from exc
            logger.warning(
                "USING SYNTHETIC DATA — results are not meaningful. "
                "Real data unavailable for %s: %s",
                symbol,
                exc,
            )
            return _generate_synthetic_prices(symbol, start, end)

    def _load_real_prices(self, symbol: str, start: str, end: str) -> list[float]:
        from omega.core.node import NodeInput
        from omega.nodes.vectora.data_ingestion import DataIngestionNode

        node = DataIngestionNode()
        inp = NodeInput(
            action="ingest",
            parameters={"symbols": [symbol], "start_date": start, "end_date": end},
        )
        out = node.execute(inp)
        rows = out.result.get("data", {}).get(symbol, [])
        if not rows:
            raise ValueError(f"No data rows returned for {symbol}")
        return [float(r.get("close", 0)) for r in rows]

    # ------------------------------------------------------------------
    # Cache inspection
    # ------------------------------------------------------------------

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
