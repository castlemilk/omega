"""V261 — trade simulator (LOCKED per V261.md param table).

Entry when ``|composite z| >= entry_z``; direction ``sign(z)``; fixed $10k notional;
5-position (≈5-day) non-overlapping holds on the aligned (composite ∩ price) date grid;
5 bps maker per side (10 bps round-trip). Deterministic — pure arithmetic on sorted
dates. No Victoria import.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FlowParams:
    entry_z: float = 1.0
    hold_positions: int = 5           # positions forward on the aligned date grid
    notional_usd: float = 10_000.0
    fee_bps_per_side: float = 5.0     # maker per side; round-trip = 2x


@dataclass
class FlowTrade:
    asset: str
    entry_date: str
    exit_date: str
    direction: int          # +1 long, -1 short
    entry_z: float
    entry_abs_z: float
    entry_price: float
    exit_price: float
    gross_ret: float
    gross_pnl_usd: float
    fee_usd: float
    pnl_usd: float

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0.0


def simulate_asset(
    asset: str,
    composite: dict[str, float],
    price: dict[str, float],
    p: FlowParams,
) -> list[FlowTrade]:
    """Non-overlapping directional trades for one asset."""
    dates = sorted(set(composite) & set(price))
    n = len(dates)
    fee_frac = p.fee_bps_per_side / 1e4
    trades: list[FlowTrade] = []
    i = 0
    while i + p.hold_positions < n:
        d = dates[i]
        z = composite[d]
        if abs(z) < p.entry_z:
            i += 1
            continue
        j = i + p.hold_positions
        entry_date, exit_date = dates[i], dates[j]
        entry_price, exit_price = price[entry_date], price[exit_date]
        direction = 1 if z > 0 else -1
        gross_ret = direction * (exit_price - entry_price) / entry_price
        gross_pnl = gross_ret * p.notional_usd
        fee = p.notional_usd * fee_frac * 2.0  # entry + exit
        trades.append(
            FlowTrade(
                asset=asset,
                entry_date=entry_date,
                exit_date=exit_date,
                direction=direction,
                entry_z=z,
                entry_abs_z=abs(z),
                entry_price=entry_price,
                exit_price=exit_price,
                gross_ret=gross_ret,
                gross_pnl_usd=gross_pnl,
                fee_usd=fee,
                pnl_usd=gross_pnl - fee,
            )
        )
        i = j  # non-overlapping: resume scan at the exit position
    return trades


def trade_to_row(t: FlowTrade) -> dict:
    return asdict(t)
