"""V255.B — offline simulation of the v1 *basis-hedged* carry strategy.

**No trading engine.** Like ``strategy.py`` (v2), this enumerates the trades the
pre-registered V255.B rule WOULD have taken on frozen data and attaches realized
PnL. Nothing places an order or shares state with Victoria.

v1 basis-hedged thesis (V255.md §A form 1; pre-registered in V255_B.md):
  * Enter on funding **LEVEL** (not z-score): |funding| >= LEVEL_THRESH.
  * Trade only in **genuine funding regimes** (exclude ``near_zero``).
  * Direction = **carry receiver**:
      funding > 0  ⇒ short perp + long spot   (longs pay shorts; short collects)
      funding < 0  ⇒ long  perp + short spot   (shorts pay longs; long collects)
  * The spot leg **hedges the perp price risk** that killed v2. Fixed HOLD days.
  * One position per symbol at a time.

PnL (both legs, per-leg notional N):
  spot_price_pnl  = N · spot_ret     (long spot: (S_x-S_0)/S_0 ; short spot: neg)
  perp_price_pnl  = N · perp_ret     (short perp: (P_0-P_x)/P_0 ; long perp: neg)
  funding_pnl     = N · Σ(3·f_d)     (short perp receives +Σ ; long perp -Σ)
  fee_pnl         = -N · (2 legs · 2 sides · fee_bps)/1e4   (4 fills)
  pnl_usd         = spot_price_pnl + perp_price_pnl + funding_pnl + fee_pnl

### Basis-hedge data limitation (see V255_B.md — surfaced BEFORE the scorer)
The frozen data has exactly ONE ``close`` series per symbol (no separate perp
mark / spot index). So spot and perp price legs are computed from the SAME series
and cancel to EXACTLY 0 by construction — the hedge is validated algebraically,
not empirically. ``empirical_basis_check`` documents this honestly and reports the
funding-level proxy for the implied basis. The residual (Δbasis over the hold)
is unmeasurable here → the basis-cleanliness assumption is UNTESTED, a hard caveat
capping any positive verdict at KEEP-FLAG-GATED.

All parameters are PRE-REGISTERED in V255_B.md, not tuned (anti-Goodhart).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .data import SETTLEMENTS_PER_DAY, SymbolSeries
from .regime import FundingRegime


@dataclass(frozen=True)
class BasisHedgeParams:
    level_thresh: float = 0.0001      # |funding| entry level (0.01% per 8h)
    hold_days: int = 3                # fixed hold
    notional_usd: float = 10_000.0    # per leg (spot $10k + perp $10k)
    fee_bps_per_side: float = 5.0     # per fill; 4 fills (2 legs x 2 sides)
    n_legs: int = 2                   # spot + perp
    # regimes NOT traded (pre-declared): near_zero excluded.
    excluded_regimes: tuple[str, ...] = (FundingRegime.NEAR_ZERO.value,)

    @property
    def round_trip_fee_ret(self) -> float:
        """Total fee as a fraction of one leg's notional (negative)."""
        return -(self.n_legs * 2 * self.fee_bps_per_side) / 10_000.0


@dataclass
class HedgedTrade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_regime: str
    # perp side is the carry-receiving leg: "short" (funding>0) | "long" (funding<0)
    perp_side: str
    entry_funding: float
    entry_price: float
    exit_price: float
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


def simulate_symbol_hedged(
    series: SymbolSeries,
    date_regimes: dict[str, FundingRegime],
    p: BasisHedgeParams,
) -> list[HedgedTrade]:
    """Enumerate V255.B basis-hedged trades for one symbol. Deterministic, no look-ahead."""
    trades: list[HedgedTrade] = []
    n = len(series)
    fee_ret = p.round_trip_fee_ret
    notional = p.notional_usd
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
            HedgedTrade(
                symbol=series.symbol,
                entry_date=d0,
                exit_date=series.dates[exit_idx],
                entry_regime=regime.value,
                perp_side=perp_side,
                entry_funding=f0,
                entry_price=p_entry,
                exit_price=p_exit,
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


def simulate_universe_hedged(
    universe: dict[str, SymbolSeries],
    date_regimes: dict[str, FundingRegime],
    p: BasisHedgeParams,
) -> list[HedgedTrade]:
    """All V255.B trades across the universe, sorted by (entry_date, symbol, side)."""
    all_trades: list[HedgedTrade] = []
    for sym in sorted(universe):  # canonical order
        all_trades.extend(simulate_symbol_hedged(universe[sym], date_regimes, p))
    all_trades.sort(key=lambda t: (t.entry_date, t.symbol, t.perp_side))
    return all_trades


# ---------------------------------------------------------------------------
# Empirical basis check (run BEFORE the scorer — mechanism gate)
# ---------------------------------------------------------------------------
def empirical_basis_check(universe: dict[str, SymbolSeries]) -> dict:
    """Honest audit of whether the basis hedge can be validated empirically.

    The task asks: compute realized basis (perp - spot) over the span; if
    materially non-zero over the hold, the hedge isn't clean. That check requires
    TWO price series (perp mark + spot index). The frozen data has exactly ONE
    ``close`` per symbol, so:

      * ``perp_series_available`` = False → realized basis is UNMEASURABLE.
      * ``hedge_cancels_by_construction`` = True → spot+perp price PnL == 0 exactly.
      * The pre-registered "basis-hedge fails empirically" falsifier CANNOT fire.

    We report the funding-level distribution as the best-available proxy for the
    implied instantaneous basis (funding is the market's clamped price of the
    perp premium). The residual (Δbasis over the hold) remains unmeasurable.
    """
    # collect all daily funding levels across the universe (implied basis proxy)
    levels: list[float] = []
    for s in universe.values():
        levels.extend(abs(f) for f in s.funding)
    levels_sorted = sorted(levels)
    n = len(levels_sorted)

    def _pct(q: float) -> float:
        if n == 0:
            return 0.0
        idx = min(n - 1, max(0, round(q * (n - 1))))
        return levels_sorted[idx]

    mean_level = math.fsum(levels_sorted) / n if n else 0.0
    return {
        "perp_series_available": False,
        "spot_series_available": True,
        "n_price_series_per_symbol": 1,
        "hedge_cancels_by_construction": True,
        "realized_basis_measurable": False,
        "basis_falsifier_can_fire": False,
        "note": (
            "Frozen data has one close series per symbol (no separate perp mark / "
            "spot index). Price legs computed from the same series cancel to exactly "
            "0. Hedge is validated algebraically, not empirically. Basis-cleanliness "
            "assumption UNTESTED → caps positive verdict at KEEP-FLAG-GATED; real "
            "basis execution is a mandatory gate for any V255.C."
        ),
        "implied_basis_proxy_abs_funding": {
            "n_obs": n,
            "mean": round(mean_level, 8),
            "median": round(_pct(0.5), 8),
            "p75": round(_pct(0.75), 8),
            "p95": round(_pct(0.95), 8),
            "max": round(levels_sorted[-1], 8) if n else 0.0,
        },
    }
