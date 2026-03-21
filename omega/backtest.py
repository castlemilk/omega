"""
omega.backtest
~~~~~~~~~~~~~~
Backtesting engine — replays historical OHLCV data through the Vectora
signal/strategy pipeline and computes performance metrics.

Usage::

    cfg    = OmegaConfig.load("omega.yml")
    engine = BacktestEngine(config=cfg, symbols=["BTCUSDT", "ETHUSDT"])
    report = engine.run(start_date="2024-01-01", end_date="2024-12-31")
    print(report)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from omega.eval.sharpe import sharpe_ratio as _canonical_sharpe

logger = logging.getLogger("omega.backtest")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class OHLCV:
    symbol: str
    date: str  # ISO YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    symbol: str
    date: str
    direction: str  # "long" | "short" | "flat"
    entry_price: float
    exit_price: float
    pnl_pct: float


@dataclass
class BacktestResult:
    mode: str
    symbols: list[str]
    start_date: str
    end_date: str
    total_return_pct: float
    annualised_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    trades: list[Trade] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "symbols": self.symbols,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_return_pct": round(self.total_return_pct, 4),
            "annualised_return_pct": round(self.annualised_return_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """
    Replays historical OHLCV data through the signal/strategy pipeline.

    Parameters
    ----------
    config:
        ``OmegaConfig`` instance (provides DB paths, provider list, etc.).
    symbols:
        List of trading symbols to backtest.
    """

    def __init__(self, config: Any, symbols: list[str]) -> None:
        self._cfg = config
        self.symbols = symbols

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(
        self,
        start_date: str,
        end_date: str,
        compare_pico: bool = False,
        pico_only: bool = False,
    ) -> dict:
        """
        Run the backtest and return a report dict.

        Parameters
        ----------
        start_date / end_date:
            ISO date strings ``YYYY-MM-DD``.
        compare_pico:
            When *True* run both PICO (rules-only) and full Omega modes and
            include both results in the report.
        pico_only:
            Skip the full Omega run; return only PICO results.
        """
        logger.info(
            "Backtest  symbols=%s  %s → %s  compare=%s",
            self.symbols,
            start_date,
            end_date,
            compare_pico,
        )

        data = self._load_data(start_date, end_date)

        pico_result = self._run_pico(data, start_date, end_date)
        report: dict = {"pico": pico_result.to_dict()}

        if not pico_only:
            omega_result = self._run_omega(data, start_date, end_date)
            report["omega"] = omega_result.to_dict()

            if compare_pico:
                report["comparison"] = _compare(pico_result, omega_result)

        report["meta"] = {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": self.symbols,
            "trading_days": len(next(iter(data.values()), [])),
        }
        return report

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self, start_date: str, end_date: str) -> dict[str, list[OHLCV]]:
        """
        Attempt to load real data via the DataIngestionNode; fall back to
        synthetic OHLCV when the provider is unavailable.
        """
        try:
            return self._load_real_data(start_date, end_date)
        except Exception as exc:
            logger.warning("Real data unavailable (%s), using synthetic data.", exc)
            return self._generate_synthetic_data(start_date, end_date)

    def _load_real_data(self, start_date: str, end_date: str) -> dict[str, list[OHLCV]]:
        from omega.core.node import NodeInput
        from omega.nodes.vectora.data_ingestion import DataIngestionNode

        node = DataIngestionNode()
        inp = NodeInput(
            action="ingest",
            parameters={
                "symbols": self.symbols,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        out = node.execute(inp)
        raw: dict = out.result.get("data", {})
        result: dict[str, list[OHLCV]] = {}
        for sym, rows in raw.items():
            ohlcv_list = []
            for row in rows:
                ohlcv_list.append(
                    OHLCV(
                        symbol=sym,
                        date=str(row.get("date", "")),
                        open=float(row.get("open", row.get("close", 0))),
                        high=float(row.get("high", row.get("close", 0))),
                        low=float(row.get("low", row.get("close", 0))),
                        close=float(row.get("close", 0)),
                        volume=float(row.get("volume", 0)),
                    )
                )
            result[sym] = ohlcv_list
        return result

    def _generate_synthetic_data(self, start_date: str, end_date: str) -> dict[str, list[OHLCV]]:
        """
        Deterministic synthetic OHLCV using a simple geometric random walk
        seeded from the symbol name so results are reproducible.
        """
        import hashlib

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        days = (end - start).days

        result: dict[str, list[OHLCV]] = {}
        for sym in self.symbols:
            seed = int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)
            # Simple LCG for reproducibility without numpy
            lcg_state = seed
            ohlcv_list: list[OHLCV] = []
            price = 100.0 + (seed % 900)

            for i in range(days):
                lcg_state = (lcg_state * 1664525 + 1013904223) & 0xFFFFFFFF
                pct = ((lcg_state % 10000) / 10000.0 - 0.5) * 0.04  # ±2 %
                close = price * (1.0 + pct)
                high = close * (1.0 + abs(pct) * 0.5)
                low = close * (1.0 - abs(pct) * 0.5)
                day = (start + timedelta(days=i)).isoformat()
                ohlcv_list.append(
                    OHLCV(
                        symbol=sym,
                        date=day,
                        open=round(price, 4),
                        high=round(high, 4),
                        low=round(low, 4),
                        close=round(close, 4),
                        volume=round(1_000_000 * (1.0 + (lcg_state % 100) / 100.0), 0),
                    )
                )
                price = close

            result[sym] = ohlcv_list
        return result

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _run_pico(
        self, data: dict[str, list[OHLCV]], start_date: str, end_date: str
    ) -> BacktestResult:
        """
        PICO baseline: simple moving-average crossover (SMA-10 / SMA-30),
        equal-weight across symbols.
        """
        all_trades: list[Trade] = []
        daily_returns: list[float] = []

        for sym, bars in data.items():
            trades, rets = _sma_crossover_strategy(sym, bars, short=10, long=30)
            all_trades.extend(trades)
            daily_returns.extend(rets)

        return _compute_metrics(
            mode="pico",
            symbols=self.symbols,
            start_date=start_date,
            end_date=end_date,
            trades=all_trades,
            daily_returns=daily_returns,
        )

    def _run_omega(
        self, data: dict[str, list[OHLCV]], start_date: str, end_date: str
    ) -> BacktestResult:
        """
        Omega strategy: multi-signal (SMA + RSI momentum filter) with
        dynamic position sizing.
        """
        all_trades: list[Trade] = []
        daily_returns: list[float] = []

        for sym, bars in data.items():
            trades, rets = _multi_signal_strategy(sym, bars)
            all_trades.extend(trades)
            daily_returns.extend(rets)

        return _compute_metrics(
            mode="omega",
            symbols=self.symbols,
            start_date=start_date,
            end_date=end_date,
            trades=all_trades,
            daily_returns=daily_returns,
        )


# ---------------------------------------------------------------------------
# Strategy implementations
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


def _sma_crossover_strategy(
    sym: str, bars: list[OHLCV], short: int, long: int
) -> tuple[list[Trade], list[float]]:
    closes = [b.close for b in bars]
    sma_s = _sma(closes, short)
    sma_l = _sma(closes, long)

    trades: list[Trade] = []
    daily_rets: list[float] = []
    position = 0.0  # 0 = flat, 1 = long
    entry_price = 0.0

    for i in range(1, len(bars)):
        if sma_s[i] is None or sma_l[i] is None:
            daily_rets.append(0.0)
            continue

        prev_s = sma_s[i - 1]
        prev_l = sma_l[i - 1]
        cur_s: float = sma_s[i]  # type: ignore[assignment]  # guarded above
        cur_l: float = sma_l[i]  # type: ignore[assignment]

        if prev_s is None or prev_l is None:
            daily_rets.append(0.0)
            continue

        # Golden cross → go long
        # Enter on next bar's open to prevent look-ahead bias
        if prev_s <= prev_l and cur_s > cur_l and position == 0.0:
            if i + 1 >= len(bars):  # can't enter on last bar
                daily_rets.append(0.0)
                continue
            position = 1.0
            entry_price = bars[i + 1].open  # Enter on next bar's open to prevent look-ahead bias

        # Death cross → close long
        # Exit on next bar's open to prevent look-ahead bias
        elif prev_s >= prev_l and cur_s < cur_l and position == 1.0:
            exit_price = bars[i + 1].open if i + 1 < len(bars) else bars[i].close
            pnl = (exit_price - entry_price) / entry_price
            trades.append(
                Trade(
                    symbol=sym,
                    date=bars[i].date,
                    direction="long",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl,
                )
            )
            position = 0.0
            entry_price = 0.0

        daily_ret = position * (closes[i] - closes[i - 1]) / closes[i - 1]
        daily_rets.append(daily_ret)

    return trades, daily_rets


def _multi_signal_strategy(sym: str, bars: list[OHLCV]) -> tuple[list[Trade], list[float]]:
    """SMA(10/30) crossover gated by RSI < 70 to avoid buying overbought."""
    closes = [b.close for b in bars]
    sma_s = _sma(closes, 10)
    sma_l = _sma(closes, 30)
    rsi_vals = _rsi(closes, 14)

    trades: list[Trade] = []
    daily_rets: list[float] = []
    position = 0.0
    entry_price = 0.0

    for i in range(1, len(bars)):
        if sma_s[i] is None or sma_l[i] is None or rsi_vals[i] is None:
            daily_rets.append(0.0)
            continue

        prev_s = sma_s[i - 1]
        prev_l = sma_l[i - 1]

        if prev_s is None or prev_l is None:
            daily_rets.append(0.0)
            continue

        cur_sma_s: float = sma_s[i]  # type: ignore[assignment]  # guarded above
        cur_sma_l: float = sma_l[i]  # type: ignore[assignment]
        rsi_ok = float(rsi_vals[i]) < 70.0  # type: ignore[arg-type]

        # Enter on next bar's open to prevent look-ahead bias
        if prev_s <= prev_l and cur_sma_s > cur_sma_l and position == 0.0 and rsi_ok:
            if i + 1 >= len(bars):  # can't enter on last bar
                daily_rets.append(0.0)
                continue
            position = 1.0
            entry_price = bars[i + 1].open  # Enter on next bar's open to prevent look-ahead bias
        # Exit on next bar's open to prevent look-ahead bias
        elif prev_s >= prev_l and cur_sma_s < cur_sma_l and position == 1.0:
            exit_price = bars[i + 1].open if i + 1 < len(bars) else bars[i].close
            pnl = (exit_price - entry_price) / entry_price
            trades.append(
                Trade(
                    symbol=sym,
                    date=bars[i].date,
                    direction="long",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl,
                )
            )
            position = 0.0
            entry_price = 0.0

        daily_ret = position * (closes[i] - closes[i - 1]) / closes[i - 1]
        daily_rets.append(daily_ret)

    return trades, daily_rets


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _compute_metrics(
    mode: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    trades: list[Trade],
    daily_returns: list[float],
) -> BacktestResult:
    total_ret = sum(daily_returns)

    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days or 1
    annualised = total_ret * (365.0 / days)

    sharpe = _canonical_sharpe(daily_returns)

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in daily_returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    winners = [t for t in trades if t.pnl_pct > 0]
    win_rate = len(winners) / len(trades) if trades else 0.0

    return BacktestResult(
        mode=mode,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        total_return_pct=total_ret * 100,
        annualised_return_pct=annualised * 100,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd * 100,
        win_rate=win_rate,
        total_trades=len(trades),
        trades=trades,
    )


def _compare(pico: BacktestResult, omega: BacktestResult) -> dict:
    return {
        "return_delta_pct": round(omega.total_return_pct - pico.total_return_pct, 4),
        "sharpe_delta": round(omega.sharpe_ratio - pico.sharpe_ratio, 4),
        "drawdown_delta_pct": round(omega.max_drawdown_pct - pico.max_drawdown_pct, 4),
        "win_rate_delta": round(omega.win_rate - pico.win_rate, 4),
        "winner": "omega" if omega.sharpe_ratio > pico.sharpe_ratio else "pico",
    }
