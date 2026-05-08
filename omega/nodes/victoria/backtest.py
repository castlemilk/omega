"""
omega.nodes.victoria.backtest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Historical backtest harness for Victoria.

Replays cached OHLCV data through the live signal + strategy pipeline
without touching exchange APIs mid-run.  Useful for:
  - Rapid config iteration without waiting for live data fetches
  - Regime-specific stress-tests (feed crisis candles only)
  - Comparing strategy versions on identical historical data

Usage
-----
  # From CLI:
  python3 -m omega.nodes.victoria.backtest \\
    --symbols ETHUSDT NEARUSDT ARBUSDT ADAUSDT \\
    --lookback 90 \\
    --window 30 \\
    --out data/bt_results.json

  # From Python:
  from omega.nodes.victoria.backtest import run_backtest
  results = run_backtest(symbols=["ETHUSDT", "NEARUSDT"], window=30)
  print(results["summary"])

Architecture
------------
1. Fetch phase  — DataIngestionNode fetches full OHLCV history (up to `lookback` days)
                  for each symbol.  Results are saved to a local JSON cache so
                  subsequent runs with the same symbols are instant.
2. Window phase — Slice each symbol's OHLCV at each time-step t using only
                  candles[0:t+window], simulating what the strategy would have seen
                  at that point in history.  The final candle is used as market price.
3. Signal phase — SignalGenerationNode + regime detectors run on the windowed data.
4. Strategy     — StrategyNode produces portfolio weights from the signals.
5. Execution    — PaperTradingEngine records virtual trades with deterministic
                  5-cycle holds (no randomisation, for reproducibility).
6. Results      — Per-symbol / per-regime PnL breakdown + equity curve written to JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from omega.core.actions import NodeAction
from omega.core.node import NodeInput
from omega.core.paper_trading import PaperTradingEngine
from omega.nodes.victoria.data_ingestion import DataIngestionNode
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.strategy import StrategyNode

logger = logging.getLogger("omega.nodes.victoria.backtest")

# Default cache location for fetched OHLCV data
_DEFAULT_CACHE = Path("data/bt_ohlcv_cache.json")

# Deterministic hold period for backtest exits (overrides PaperTradingEngine randomness)
_BT_HOLD_CYCLES = 5


def _fetch_ohlcv(
    symbols: list[str],
    lookback: int = 90,
    cache_path: Path = _DEFAULT_CACHE,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch OHLCV for `symbols` via DataIngestionNode, with local JSON caching.

    Returns dict mapping symbol → OHLCV dict (same format as DataIngestionNode output).
    Cache key includes symbol list + lookback to avoid stale hits on config changes.
    """
    cache_key = f"{sorted(symbols)}:{lookback}"
    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("_cache_key") == cache_key:
                age_h = (time.time() - cached.get("_fetched_at", 0)) / 3600
                if age_h < 6:
                    logger.info("OHLCV cache hit (%d symbols, %.1fh old)", len(symbols), age_h)
                    return {k: v for k, v in cached.items() if not k.startswith("_")}
        except Exception as exc:
            logger.warning("Cache read failed, re-fetching: %s", exc)

    logger.info("Fetching OHLCV for %d symbols (lookback=%d days)…", len(symbols), lookback)
    ingestion = DataIngestionNode()
    # Override the pair list to exactly what the caller wants
    ingestion._pairs = symbols

    out = ingestion.execute(
        NodeInput(
            action=NodeAction.FETCH_MARKET_DATA.value,
            parameters={"limit": lookback},
        )
    )
    if not out.success or not out.result:
        raise RuntimeError(f"DataIngestionNode failed: {out.error}")

    market_data: dict[str, Any] = out.result
    # Persist to cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**market_data, "_cache_key": cache_key, "_fetched_at": time.time()}
    cache_path.write_text(json.dumps(payload, default=str))
    logger.info("OHLCV cached → %s", cache_path)
    return market_data


def _slice_window(market_data: dict[str, Any], end_idx: int, window: int) -> dict[str, Any]:
    """Return a copy of market_data with each symbol's OHLCV sliced to [end_idx-window:end_idx].

    This simulates what the strategy would have seen at candle `end_idx`.
    The last candle in the slice is treated as the current market price.
    """
    sliced: dict[str, Any] = {}
    for symbol, data in market_data.items():
        if not isinstance(data, dict):
            continue
        start = max(0, end_idx - window)
        s: dict[str, Any] = {}
        for key, val in data.items():
            if isinstance(val, list):
                s[key] = val[start:end_idx]
            else:
                s[key] = val
        # Update regularMarketPrice to the last close in the window
        closes = s.get("close") or s.get("adjclose", [])
        if closes:
            meta = dict(s.get("meta", {}))
            meta["regularMarketPrice"] = closes[-1]
            s["meta"] = meta
        sliced[symbol] = s
    return sliced


def run_backtest(
    symbols: list[str] | None = None,
    lookback: int = 90,
    window: int = 30,
    step: int = 1,
    initial_capital: float = 100_000.0,
    cache_path: Path = _DEFAULT_CACHE,
    force_refresh: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run a historical backtest and return a results dict.

    Parameters
    ----------
    symbols      : Symbols to include. Defaults to the standard active basket.
    lookback     : Total candles to fetch per symbol (e.g. 90 days of daily bars).
    window       : Rolling window fed to the signal pipeline at each time-step.
                   Minimum 30 (signal indicators need sufficient history).
    step         : Advance by this many candles per cycle (1 = step-through every bar).
    initial_capital : Starting capital for PaperTradingEngine.
    cache_path   : Where to store the fetched OHLCV JSON cache.
    force_refresh: Bypass cache and re-fetch live data.
    verbose      : Print per-cycle logs.
    """
    if symbols is None:
        # Default active basket (mirrors current non-blacklisted symbols)
        symbols = ["ETHUSDT", "ADAUSDT", "NEARUSDT", "ARBUSDT"]

    if window < 30:
        raise ValueError(f"window must be >= 30 (got {window})")
    if lookback < window + step:
        raise ValueError(f"lookback ({lookback}) must be > window ({window}) + step ({step})")

    # ── 1. Fetch data ────────────────────────────────────────────────────────
    market_data = _fetch_ohlcv(symbols, lookback, cache_path, force_refresh)

    # Find the minimum series length across symbols (use shortest series to align)
    series_len = min(
        len(d.get("close") or d.get("adjclose", []))
        for d in market_data.values()
        if isinstance(d, dict) and (d.get("close") or d.get("adjclose"))
    )
    if series_len < window + step:
        raise RuntimeError(f"Insufficient data: series_len={series_len}, need >= {window + step}")

    # ── 2. Initialise pipeline components ───────────────────────────────────
    signal_node = SignalGenerationNode()
    strategy = StrategyNode()

    engine = PaperTradingEngine(
        initial_capital=initial_capital,
        max_position_per_symbol=1.0,
        max_portfolio_exposure=1.0,
    )
    # Override exit timing to be deterministic for reproducible backtest results.
    # PaperTradingEngine uses module-level _EXIT_CYCLES_MIN/_MAX constants; patch them.
    import omega.core.paper_trading as _pt_module

    _orig_min = _pt_module._EXIT_CYCLES_MIN
    _orig_max = _pt_module._EXIT_CYCLES_MAX
    _pt_module._EXIT_CYCLES_MIN = _BT_HOLD_CYCLES
    _pt_module._EXIT_CYCLES_MAX = _BT_HOLD_CYCLES

    # ── 3. Time-step loop ────────────────────────────────────────────────────
    equity_curve: list[dict[str, Any]] = []
    trade_log: list[dict[str, Any]] = []
    cycle = 0
    n_cycles = (series_len - window) // step

    logger.info(
        "Backtest: %d symbols, %d total bars, window=%d, step=%d → %d cycles",
        len(symbols),
        series_len,
        window,
        step,
        n_cycles,
    )

    for end_idx in range(window, series_len, step):
        cycle += 1
        windowed = _slice_window(market_data, end_idx, window)

        # Signals
        sig_out = signal_node.execute(
            NodeInput(
                action=NodeAction.COMPUTE_SIGNALS.value,
                parameters={"market_data": windowed},
            )
        )
        if not sig_out.success or not sig_out.result:
            logger.debug("Cycle %d: signal failure, skipping", cycle)
            continue

        signals: dict[str, Any] = sig_out.result

        # Strategy
        strat_out = strategy.execute(
            NodeInput(
                action=NodeAction.CONSTRUCT_PORTFOLIO.value,
                parameters={"signals": signals, "market_data": windowed},
            )
        )
        if not strat_out.success or not strat_out.result:
            logger.debug("Cycle %d: strategy failure, skipping", cycle)
            continue

        result = strat_out.result
        weights: dict[str, float] = result.get("weights", {})
        conviction_scores: dict[str, float] = result.get("conviction_scores", {})
        # V179: surface consolidated regime onto each proposal for regime-selective sizing
        _regime_consolidated = result.get("regime_consolidated", "")

        # Build proposals and execute
        proposals = [
            {
                "symbol": sym,
                "weight": float(w),
                "conviction": conviction_scores.get(sym, 0.30),
                "regime": _regime_consolidated,
            }
            for sym, w in weights.items()
        ]

        before_closed = len(engine.closed_trades)
        if proposals:
            engine.execute_proposals(
                proposals,
                market_data=windowed,
                cycle_id=f"bt_{cycle}",
                current_cycle=cycle,
            )
        else:
            engine.mark_to_market(windowed, cycle, cycle_id=f"bt_{cycle}")

        # Collect newly closed trades
        for t in engine.closed_trades[before_closed:]:
            trade_log.append(
                {
                    "cycle": cycle,
                    "symbol": t.get("symbol", ""),
                    "side": t.get("side", ""),
                    "pnl": t.get("pnl", 0.0),
                    "conviction": t.get("conviction", 0.0),
                    "regime": signals.get("_regime", "unknown"),
                    "size": t.get("size", 0.0),
                    "hold_cycles": t.get("hold_cycles", 0),
                }
            )

        equity = initial_capital + engine.realised_pnl
        equity_curve.append(
            {"cycle": cycle, "equity": round(equity, 2), "pnl": round(engine.realised_pnl, 2)}
        )

        if verbose and cycle % 10 == 0:
            n_trades = len(engine.closed_trades)
            logger.info(
                "BT cycle %3d/%d | equity=$%.0f | closed=%d | pnl=$%+.2f",
                cycle,
                n_cycles,
                equity,
                n_trades,
                engine.realised_pnl,
            )

    # Restore original exit cycle constants
    _pt_module._EXIT_CYCLES_MIN = _orig_min
    _pt_module._EXIT_CYCLES_MAX = _orig_max

    # ── 4. Final summary ─────────────────────────────────────────────────────
    from collections import defaultdict

    by_sym: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    by_regime: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    by_side: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})

    for t in trade_log:
        sym, pnl, regime, side = t["symbol"], t["pnl"], t["regime"], t["side"]
        by_sym[sym]["trades"] += 1
        by_sym[sym]["pnl"] += pnl
        if pnl > 0:
            by_sym[sym]["wins"] += 1
        by_regime[regime]["trades"] += 1
        by_regime[regime]["pnl"] += pnl
        if pnl > 0:
            by_regime[regime]["wins"] += 1
        by_side[side]["trades"] += 1
        by_side[side]["pnl"] += pnl
        if pnl > 0:
            by_side[side]["wins"] += 1

    total_closed = len(trade_log)
    wins = sum(1 for t in trade_log if t["pnl"] > 0)
    gross_profit = sum(t["pnl"] for t in trade_log if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trade_log if t["pnl"] < 0))
    total_pnl = sum(t["pnl"] for t in trade_log)
    win_rate = wins / total_closed if total_closed else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown from equity curve
    peak = initial_capital
    max_dd = 0.0
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    summary = {
        "cycles": cycle,
        "symbols": symbols,
        "window": window,
        "step": step,
        "total_closed": total_closed,
        "long_trades": sum(1 for t in trade_log if t["side"] == "long"),
        "short_trades": sum(1 for t in trade_log if t["side"] == "short"),
        "win_rate": round(win_rate, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "per_symbol": {
            sym: {
                "trades": d["trades"],
                "pnl": round(d["pnl"], 2),
                "win_rate": round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0,
            }
            for sym, d in sorted(by_sym.items(), key=lambda x: -x[1]["pnl"])
        },
        "per_regime": {
            r: {
                "trades": d["trades"],
                "pnl": round(d["pnl"], 2),
                "win_rate": round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0,
            }
            for r, d in sorted(by_regime.items(), key=lambda x: -x[1]["pnl"])
        },
        "per_side": {
            s: {
                "trades": d["trades"],
                "pnl": round(d["pnl"], 2),
                "win_rate": round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0,
            }
            for s, d in by_side.items()
        },
    }

    return {
        "summary": summary,
        "equity_curve": equity_curve,
        "trades": trade_log,
    }


def _print_summary(s: dict[str, Any]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  BACKTEST RESULTS  —  {s['cycles']} cycles, window={s['window']}")
    print(f"{'=' * 60}")
    print(f"  Total PnL     : ${s['total_pnl_usd']:+.2f}")
    print(f"  Trades        : {s['total_closed']}  (L:{s['long_trades']} S:{s['short_trades']})")
    print(f"  Win Rate      : {s['win_rate'] * 100:.1f}%")
    print(f"  Profit Factor : {s['profit_factor']:.3f}")
    print(f"  Max Drawdown  : {s['max_drawdown_pct']:.1f}%")
    print("\n  Per Symbol:")
    for sym, d in s["per_symbol"].items():
        print(
            f"    {sym:12s}  {d['trades']:3d}T  ${d['pnl']:+8.2f}  WR={d['win_rate'] * 100:.0f}%"
        )
    print("\n  Per Regime:")
    for r, d in s["per_regime"].items():
        print(f"    {r:12s}  {d['trades']:3d}T  ${d['pnl']:+8.2f}  WR={d['win_rate'] * 100:.0f}%")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(description="Victoria historical backtest harness")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to backtest (default: active basket)",
    )
    parser.add_argument(
        "--lookback", type=int, default=90, help="OHLCV bars to fetch (default 90)"
    )
    parser.add_argument(
        "--window", type=int, default=30, help="Rolling signal window (default 30)"
    )
    parser.add_argument("--step", type=int, default=1, help="Candles per cycle step (default 1)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    parser.add_argument("--out", type=str, default=None, help="Write results JSON to this path")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch (bypass cache)")
    parser.add_argument("--verbose", action="store_true", help="Per-cycle log output")
    args = parser.parse_args()

    results = run_backtest(
        symbols=args.symbols,
        lookback=args.lookback,
        window=args.window,
        step=args.step,
        initial_capital=args.capital,
        force_refresh=args.refresh,
        verbose=args.verbose,
    )

    _print_summary(results["summary"])

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, default=str))
        print(f"Results written → {out_path}")
