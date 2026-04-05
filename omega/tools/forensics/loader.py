"""Load Victoria training run artifacts (results JSON + trades CSV) into typed records."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunArtifacts:
    """Normalised view of a single training run's results + trades."""

    version: str
    total_pnl: float
    win_rate: float
    total_trades: int
    long_trades: int
    short_trades: int
    profit_factor: float
    zero_trade_cycles: int
    conviction_filter_rate: float
    trades: list[dict[str, Any]]
    regime_pnl: dict[str, float] = field(default_factory=dict)

    @property
    def trade_cycles(self) -> int:
        """Cycles on which at least one trade was opened."""
        return len({t["cycle"] for t in self.trades})


def _parse_trades_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "cycle": int(row["cycle"]),
                    "timestamp": row["timestamp"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "size": float(row["size"]),
                    "entry_price": float(row["entry_price"]),
                    "exit_price": float(row["exit_price"]),
                    "pnl": float(row["pnl"]),
                    "slippage": float(row["slippage"]),
                    "hold_cycles": int(row["hold_cycles"]),
                    "conviction": float(row["conviction"]),
                    "regime": row["regime"],
                    "sit_out_reason": row["sit_out_reason"],
                }
            )
    return rows


def _compute_regime_pnl(trades: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        regime = t.get("regime", "unknown")
        out[regime] = out.get(regime, 0.0) + t["pnl"]
    return out


def load_run(results_path: Path, trades_path: Path) -> RunArtifacts:
    """Load a results JSON and trades CSV into a single RunArtifacts record."""
    with Path(results_path).open() as f:
        results = json.load(f)

    trades_block = results.get("trades", {})
    obs_block = results.get("observability", {})

    trades = _parse_trades_csv(Path(trades_path))
    regime_pnl = _compute_regime_pnl(trades)

    return RunArtifacts(
        version=results.get("version", "unknown"),
        total_pnl=float(trades_block.get("total_pnl_usd", 0.0)),
        win_rate=float(trades_block.get("win_rate", 0.0)),
        total_trades=int(trades_block.get("total_closed", 0)),
        long_trades=int(trades_block.get("long_trades", 0)),
        short_trades=int(trades_block.get("short_trades", 0)),
        profit_factor=float(trades_block.get("profit_factor", 0.0)),
        zero_trade_cycles=int(obs_block.get("total_zero_trade_cycles", 0)),
        conviction_filter_rate=float(obs_block.get("conviction_filter_rate", 0.0)),
        trades=trades,
        regime_pnl=regime_pnl,
    )
