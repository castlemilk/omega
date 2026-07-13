"""Offline simulation of the v2 directional funding-carry strategy.

**No trading engine.** This computes exactly what trades the v2 rule WOULD have
taken on the frozen data and their realized PnL — a $0 offline scorer in the
V244 discipline (like ``v246_exit_scorer``: enumerate hypothetical trades,
attach realized PnL, run a separator). Nothing here places an order or shares
state with Victoria.

v2 directional thesis (funding mean-reversion + carry, aligned):
  * Signal: z = trailing z-score of a symbol's funding (lookback L).
  * Entry SHORT when z > +Z: funding extreme-positive ⇒ crowded longs ⇒ (a)
    short collects funding, (b) price likely mean-reverts down. Both align.
  * Entry LONG  when z < -Z: funding extreme-negative ⇒ crowded shorts ⇒ (a)
    long collects funding, (b) price likely mean-reverts up. Both align.
  * Exit: fixed hold of H days (deterministic; no path-dependent exit tuning).
  * One position per symbol at a time; skip new entries while in position.

PnL (per unit notional):
  price_ret  = SHORT: (P_entry - P_exit)/P_entry ; LONG: (P_exit - P_entry)/P_entry
  funding    = SHORT receives +Σ(3·f_d) over hold ; LONG pays -Σ(3·f_d)
               (3 settlements/day; series is the daily mean settlement rate)
  cost       = round-trip taker fee (bps each way)
  pnl_usd    = NOTIONAL · (price_ret + funding - cost)

All parameters are PRE-REGISTERED in V255.md, not tuned to make the separator
pass (anti-Goodhart).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .data import SETTLEMENTS_PER_DAY, SymbolSeries


@dataclass(frozen=True)
class StrategyParams:
    lookback: int = 30          # days for funding z-score
    z_thresh: float = 1.0       # |z| entry threshold
    hold_days: int = 7          # fixed hold
    notional_usd: float = 10_000.0
    fee_bps_per_side: float = 5.0  # 5 bps taker each way => 10 bps round trip


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    side: str              # "short" | "long"
    entry_z: float         # trailing funding z-score at entry (signed)
    entry_funding: float   # daily settlement rate at entry
    entry_price: float
    exit_price: float
    price_ret: float       # per-unit-notional price return (side-adjusted)
    funding_ret: float     # per-unit-notional funding accrual (side-adjusted)
    cost_ret: float        # per-unit-notional round-trip cost (negative)
    pnl_usd: float

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0.0


def simulate_symbol(series: SymbolSeries, p: StrategyParams) -> list[Trade]:
    """Enumerate v2 trades for one symbol. Deterministic, no look-ahead."""
    trades: list[Trade] = []
    n = len(series)
    cost_ret = -2.0 * p.fee_bps_per_side / 10_000.0  # round trip, per notional
    i = p.lookback
    while i < n:
        mean, std = series.rolling_stats(i, p.lookback)
        if std <= 0.0:
            i += 1
            continue
        z = (series.funding[i] - mean) / std
        if abs(z) < p.z_thresh:
            i += 1
            continue
        exit_idx = i + p.hold_days
        if exit_idx >= n:
            break  # not enough forward data to close — drop (no look-ahead cheat)
        side = "short" if z > 0 else "long"
        p_entry = series.close[i]
        p_exit = series.close[exit_idx]
        if side == "short":
            price_ret = (p_entry - p_exit) / p_entry
        else:
            price_ret = (p_exit - p_entry) / p_entry
        # funding accrual over the hold: 3 settlements/day.
        fund_sum = math.fsum(
            series.funding[j] for j in range(i, exit_idx)
        ) * SETTLEMENTS_PER_DAY
        funding_ret = fund_sum if side == "short" else -fund_sum
        total_ret = price_ret + funding_ret + cost_ret
        trades.append(
            Trade(
                symbol=series.symbol,
                entry_date=series.dates[i],
                exit_date=series.dates[exit_idx],
                side=side,
                entry_z=z,
                entry_funding=series.funding[i],
                entry_price=p_entry,
                exit_price=p_exit,
                price_ret=price_ret,
                funding_ret=funding_ret,
                cost_ret=cost_ret,
                pnl_usd=p.notional_usd * total_ret,
            )
        )
        i = exit_idx  # one position per symbol at a time
    return trades


def simulate_universe(
    universe: dict[str, SymbolSeries], p: StrategyParams
) -> list[Trade]:
    """All trades across the universe, sorted by (entry_date, symbol)."""
    all_trades: list[Trade] = []
    for sym in sorted(universe):  # canonical order
        all_trades.extend(simulate_symbol(universe[sym], p))
    all_trades.sort(key=lambda t: (t.entry_date, t.symbol, t.side))
    return all_trades
