"""Performance attribution analysis for Victoria trading runs.

Decomposes total PnL into alpha, beta, timing, and selection components
using only stdlib + csv — no pandas or numpy required.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


_BASELINE_CONVICTION = 0.15  # baseline threshold used in conviction filter


class PerformanceAttribution:
    """Decomposes PnL into alpha, beta, timing, and selection components.

    Columns expected in the trades CSV:
        cycle, timestamp, symbol, side, size, entry_price, exit_price,
        pnl, slippage, hold_cycles, conviction, regime, sit_out_reason
    """

    def __init__(self, trades_path: str | Path) -> None:
        self._path = Path(trades_path)
        self._trades: list[dict] = []
        self._version: str = self._detect_version()
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_version(self) -> str:
        """Try to extract a version tag from the filename (e.g. v55_trades.csv -> v55)."""
        stem = self._path.stem  # e.g. "v55_trades"
        parts = stem.split("_")
        if parts and parts[0].startswith("v") and parts[0][1:].isdigit():
            return parts[0]
        return stem

    def _load(self) -> None:
        with open(self._path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    self._trades.append(
                        {
                            "cycle": int(row["cycle"]),
                            "symbol": row["symbol"],
                            "side": row["side"],
                            "size": float(row["size"]),
                            "entry_price": float(row["entry_price"]),
                            "exit_price": float(row["exit_price"]),
                            "pnl": float(row["pnl"]),
                            "hold_cycles": float(row["hold_cycles"]),
                            "conviction": float(row["conviction"]),
                            "regime": row.get("regime", "unknown"),
                        }
                    )
                except (KeyError, ValueError):
                    # Skip malformed rows silently
                    continue

    # ------------------------------------------------------------------
    # Component calculations
    # ------------------------------------------------------------------

    def _alpha_component(self) -> float:
        """PnL fraction attributable to signal conviction above baseline.

        For each trade: alpha_pnl = pnl * min(conviction / baseline, 1.0)
        """
        total = 0.0
        for t in self._trades:
            scale = min(t["conviction"] / _BASELINE_CONVICTION, 1.0)
            total += t["pnl"] * scale
        return total

    def _beta_component(self) -> tuple[float, dict[int, float]]:
        """PnL from passive market-basket exposure.

        Basket return per cycle = average (exit - entry) / entry across all
        trades in that cycle.  Beta contribution per trade = basket_return *
        size * entry_price.

        Returns (total_beta_pnl, basket_return_by_cycle).
        """
        # Group price returns by cycle
        cycle_returns: dict[int, list[float]] = defaultdict(list)
        for t in self._trades:
            if t["entry_price"] > 0:
                ret = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
                cycle_returns[t["cycle"]].append(ret)

        basket_return: dict[int, float] = {
            c: sum(rets) / len(rets) for c, rets in cycle_returns.items() if rets
        }

        total = 0.0
        for t in self._trades:
            br = basket_return.get(t["cycle"], 0.0)
            total += br * t["size"] * t["entry_price"]

        return total, basket_return

    def _timing_component(self, basket_return: dict[int, float]) -> float:
        """PnL delta from actual entry/exit timing vs. passive basket return.

        timing_pnl per trade = actual_pnl - (basket_return * notional * direction)
        where direction is +1 for long, -1 for short.
        """
        total = 0.0
        for t in self._trades:
            notional = t["size"] * t["entry_price"]
            direction = 1.0 if t["side"] == "long" else -1.0
            br = basket_return.get(t["cycle"], 0.0)
            passive = notional * direction * br
            total += t["pnl"] - passive
        return total

    def _selection_component(self) -> tuple[float, dict[str, dict]]:
        """PnL from symbol selection vs. basket average.

        selection_pnl[sym] = symbol_total_pnl - (trade_count[sym] * basket_avg_pnl_per_trade)

        Returns (total_selection, per_symbol_dict).
        """
        if not self._trades:
            return 0.0, {}

        total_pnl = sum(t["pnl"] for t in self._trades)
        total_trades = len(self._trades)
        basket_avg = total_pnl / total_trades if total_trades else 0.0

        symbol_pnl: dict[str, float] = defaultdict(float)
        symbol_count: dict[str, int] = defaultdict(int)
        for t in self._trades:
            symbol_pnl[t["symbol"]] += t["pnl"]
            symbol_count[t["symbol"]] += 1

        per_symbol: dict[str, dict] = {}
        total_selection = 0.0
        for sym, pnl in symbol_pnl.items():
            sel = pnl - (symbol_count[sym] * basket_avg)
            total_selection += sel
            per_symbol[sym] = {
                "pnl": round(pnl, 4),
                "selection": round(sel, 4),
                "trades": symbol_count[sym],
            }

        return total_selection, per_symbol

    def _per_regime(self) -> dict[str, dict]:
        """Per-regime breakdown: total pnl, alpha contribution, and trade count."""
        regime_pnl: dict[str, float] = defaultdict(float)
        regime_alpha: dict[str, float] = defaultdict(float)
        regime_count: dict[str, int] = defaultdict(int)

        for t in self._trades:
            r = t["regime"]
            scale = min(t["conviction"] / _BASELINE_CONVICTION, 1.0)
            regime_pnl[r] += t["pnl"]
            regime_alpha[r] += t["pnl"] * scale
            regime_count[r] += 1

        result: dict[str, dict] = {}
        for r in regime_pnl:
            result[r] = {
                "pnl": round(regime_pnl[r], 4),
                "alpha": round(regime_alpha[r], 4),
                "trades": regime_count[r],
            }
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self) -> dict:
        """Return the full attribution breakdown as a plain dict."""
        total_pnl = sum(t["pnl"] for t in self._trades)
        trade_count = len(self._trades)

        alpha = self._alpha_component()
        beta_total, basket_return = self._beta_component()
        timing = self._timing_component(basket_return)
        selection_total, per_symbol = self._selection_component()

        residual = total_pnl - (alpha + beta_total + timing + selection_total)

        return {
            "version": self._version,
            "total_pnl": round(total_pnl, 4),
            "trade_count": trade_count,
            "components": {
                "alpha": round(alpha, 4),
                "beta": round(beta_total, 4),
                "timing": round(timing, 4),
                "selection": round(selection_total, 4),
                "residual": round(residual, 4),
            },
            "per_symbol": per_symbol,
            "per_regime": self._per_regime(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self, out_path: str | Path) -> None:
        """Compute attribution and write JSON to *out_path*."""
        result = self.compute()
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as fh:
            json.dump(result, fh, indent=2)
