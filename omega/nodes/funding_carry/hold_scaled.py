"""V255.C — offline simulation of the hold/level-scaled basis-hedged carry.

**No trading engine.** Like ``basis_hedge.py`` (V255.B), this enumerates the
trades the pre-registered V255.C rule WOULD have taken on frozen data and
attaches realized PnL. Nothing places an order or shares state with Victoria.

V255.C re-parameterizes V255.B along exactly three pre-declared levers
(``training_log/V255_C.md``); mechanics are otherwise byte-for-byte identical:

  * **Hold period** — 3 → **7 days** (fixed).
  * **Sizing** — fixed $10k → **level-scaled**:
        notional = min(cap, base * |funding_bps| / funding_ref_bps)
    where funding_bps = |entry funding| * 10_000. At the 5 bps/8h reference the
    baseline $10k is used; it scales *down* proportionally toward the entry
    threshold and is capped at $10k.
  * **Fee model** — parameterized (per-side bps, maker/taker flag). Pre-declared
    value is the SAME 5 bps/side maker, 4 fills = 20 bps round trip as V255.B.

The entry rule (|funding| >= level_thresh), regime filter (near_zero excluded),
and carry-receiver direction are unchanged from V255.B.

### Sizing does NOT flip the median sign (pre-registered fact)
Fee = notional * (n_legs*2*fee_bps_side)/1e4 and every PnL component is linear in
notional, so the SIGN of each trade's net PnL is independent of its size
(notional > 0). Level-scaled sizing changes mean/total PnL but the pooled-median
SIGN is governed purely by whether the pooled win rate exceeds 50% — only the
7-day hold can move that (by letting more trades' carry clear the fixed fee).

### Basis-cleanliness caveat (carried from V255.B)
Frozen data has ONE ``close`` series per symbol; spot & perp price legs cancel to
exactly $0 by construction, so the hedge is validated algebraically, not
empirically. The basis-cleanliness assumption is UNTESTED → caps any positive
verdict at KEEP-FLAG-GATED (ADOPT pre-excluded).

All parameters are PRE-REGISTERED in V255_C.md, not tuned (anti-Goodhart).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .data import SETTLEMENTS_PER_DAY, SymbolSeries
from .regime import FundingRegime


@dataclass(frozen=True)
class HoldScaledParams:
    level_thresh: float = 0.0001        # |funding| entry level (0.01% per 8h)
    hold_days: int = 7                  # V255.C: was 3 in V255.B
    base_notional_usd: float = 10_000.0  # notional at the reference funding
    notional_cap_usd: float = 10_000.0   # hard cap on the level-scaled notional
    funding_ref_bps: float = 5.0        # |funding_bps| at which base notional is used
    fee_bps_per_side: float = 5.0       # per fill; maker tier
    n_legs: int = 2                     # spot + perp
    maker: bool = True                  # recorded; pre-declared maker execution
    # regimes NOT traded (pre-declared): near_zero excluded.
    excluded_regimes: tuple[str, ...] = (FundingRegime.NEAR_ZERO.value,)

    @property
    def round_trip_fee_ret(self) -> float:
        """Total fee as a fraction of one leg's notional (negative)."""
        return -(self.n_legs * 2 * self.fee_bps_per_side) / 10_000.0

    def notional_for(self, entry_funding: float) -> float:
        """Level-scaled per-leg notional (pre-declared Kelly-lite formula)."""
        funding_bps = abs(entry_funding) * 10_000.0
        scaled = self.base_notional_usd * funding_bps / self.funding_ref_bps
        return min(self.notional_cap_usd, scaled)


@dataclass
class HoldScaledTrade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_regime: str
    # perp side is the carry-receiving leg: "short" (funding>0) | "long" (funding<0)
    perp_side: str
    entry_funding: float
    entry_price: float
    exit_price: float
    notional_usd: float     # level-scaled per-leg notional for this trade
    spot_price_ret: float   # per-unit-notional, side-adjusted (spot leg)
    perp_price_ret: float   # per-unit-notional, side-adjusted (perp leg)
    funding_ret: float      # per-unit-notional funding accrual over hold (perp leg)
    cost_ret: float         # per-unit-notional round-trip fee (negative, both legs)
    spot_price_pnl: float
    perp_price_pnl: float
    funding_pnl: float
    fee_pnl: float
    pnl_usd: float          # net (all components)
    gross_carry_pnl: float  # funding_pnl only (pre-fee, price-neutral carry)

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0.0


def simulate_symbol_scaled(
    series: SymbolSeries,
    date_regimes: dict[str, FundingRegime],
    p: HoldScaledParams,
) -> list[HoldScaledTrade]:
    """Enumerate V255.C trades for one symbol. Deterministic, no look-ahead."""
    trades: list[HoldScaledTrade] = []
    n = len(series)
    fee_ret = p.round_trip_fee_ret
    i = 0
    while i < n:
        f0 = series.funding[i]
        d0 = series.dates[i]
        # level entry + regime filter (both pre-declared)
        if abs(f0) < p.level_thresh:
            i += 1
            continue
        regime = date_regimes.get(d0, FundingRegime.NEAR_ZERO)
        if regime.value in p.excluded_regimes:
            i += 1
            continue
        exit_idx = i + p.hold_days
        if exit_idx >= n:
            break  # not enough forward data — drop (no look-ahead cheat)

        notional = p.notional_for(f0)  # level-scaled per-leg notional
        p_entry = series.close[i]
        p_exit = series.close[exit_idx]
        raw_price_ret = (p_exit - p_entry) / p_entry  # long-perspective price return

        if f0 > 0:
            # funding positive: SHORT perp (collect) + LONG spot (hedge)
            perp_side = "short"
            perp_price_ret = -raw_price_ret   # short perp
            spot_price_ret = raw_price_ret    # long spot
        else:
            # funding negative: LONG perp (collect) + SHORT spot (hedge)
            perp_side = "long"
            perp_price_ret = raw_price_ret    # long perp
            spot_price_ret = -raw_price_ret   # short spot

        # funding accrual over the hold: 3 settlements/day, exact-rounded sum.
        fund_sum = math.fsum(
            series.funding[j] for j in range(i, exit_idx)
        ) * SETTLEMENTS_PER_DAY
        funding_ret = fund_sum if perp_side == "short" else -fund_sum

        spot_price_pnl = notional * spot_price_ret
        perp_price_pnl = notional * perp_price_ret
        funding_pnl = notional * funding_ret
        fee_pnl = notional * fee_ret
        pnl_usd = spot_price_pnl + perp_price_pnl + funding_pnl + fee_pnl

        trades.append(
            HoldScaledTrade(
                symbol=series.symbol,
                entry_date=d0,
                exit_date=series.dates[exit_idx],
                entry_regime=regime.value,
                perp_side=perp_side,
                entry_funding=f0,
                entry_price=p_entry,
                exit_price=p_exit,
                notional_usd=notional,
                spot_price_ret=spot_price_ret,
                perp_price_ret=perp_price_ret,
                funding_ret=funding_ret,
                cost_ret=fee_ret,
                spot_price_pnl=spot_price_pnl,
                perp_price_pnl=perp_price_pnl,
                funding_pnl=funding_pnl,
                fee_pnl=fee_pnl,
                pnl_usd=pnl_usd,
                gross_carry_pnl=funding_pnl,
            )
        )
        i = exit_idx  # one position per symbol at a time
    return trades


def simulate_universe_scaled(
    universe: dict[str, SymbolSeries],
    date_regimes: dict[str, FundingRegime],
    p: HoldScaledParams,
) -> list[HoldScaledTrade]:
    """All V255.C trades across the universe, sorted by (entry_date, symbol, side)."""
    all_trades: list[HoldScaledTrade] = []
    for sym in sorted(universe):  # canonical order
        all_trades.extend(simulate_symbol_scaled(universe[sym], date_regimes, p))
    all_trades.sort(key=lambda t: (t.entry_date, t.symbol, t.perp_side))
    return all_trades
