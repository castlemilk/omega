"""V262-2 — 1h trade simulator (LOCKED per V262-2.md §4).

Mirrors ``on_chain_flow/sim.py`` (V261), rebased to the 1h bar grid:

  entry ``|composite z| >= 1.0`` AND ``hourly_volume_z >= 0``; direction
  ``sign(z)``; $10k notional; non-overlapping ``hold_bars``-bar holds;
  12 bps per side (24 bps round-trip) = Binance VIP-0 spot taker 10 bps + 2 bps
  slippage. Spot is single-leg, so this is NOT the V255.B 2-leg model.

### Bar contiguity is load-bearing

A hold runs from bar *i* to bar *i + hold_bars* only if those bars are **exactly**
``hold_bars`` hours apart. Index adjacency is not enough: the corpus has real holes
(293 genuine exchange-outage bars, and the 80-hour MATIC→POL migration gap), and
holding "5 bars" across an 80-hour hole would fabricate a 3.3-day position. This is
the same timestamp-not-index discipline F4b adopted for its lag-1 transitions.

Determinism: pure arithmetic over a monotonic bar list; no wall clock, no RNG.
"""

from __future__ import annotations

from dataclasses import dataclass

_HOUR_MS = 3_600_000


@dataclass(frozen=True)
class IntradayParams:
    entry_z: float = 1.0  # inherited verbatim from V261 FlowParams
    hold_bars: int = 5  # obs-count analogue of V261's 5 daily positions
    notional_usd: float = 10_000.0  # inherited verbatim from V261
    fee_bps_per_side: float = 12.0  # 10bps VIP-0 spot taker + 2bps slippage
    min_volume_z: float = 0.0  # entry filter: participation confirmation


@dataclass
class IntradayTrade:
    symbol: str
    entry_ms: int
    exit_ms: int
    direction: int
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

    @property
    def is_winner_gross(self) -> bool:
        return self.gross_pnl_usd > 0.0


def simulate_symbol(
    symbol: str,
    bar_times: list[int],
    close: list[float],
    composite: list[float | None],
    volume_z: list[float | None],
    p: IntradayParams,
) -> list[IntradayTrade]:
    """Non-overlapping directional 1h trades for one symbol-history."""
    fee_frac = p.fee_bps_per_side / 1e4
    span_ms = p.hold_bars * _HOUR_MS
    trades: list[IntradayTrade] = []
    n = len(bar_times)
    i = 0
    while i + p.hold_bars < n:
        z = composite[i]
        vz = volume_z[i]
        if z is None or abs(z) < p.entry_z or vz is None or vz < p.min_volume_z:
            i += 1
            continue
        j = i + p.hold_bars
        # contiguity: the hold must span exactly hold_bars real hours (see module doc)
        if bar_times[j] - bar_times[i] != span_ms:
            i += 1
            continue
        entry_price, exit_price = close[i], close[j]
        if entry_price <= 0.0:
            i += 1
            continue
        direction = 1 if z > 0 else -1
        gross_ret = direction * (exit_price - entry_price) / entry_price
        gross_pnl = gross_ret * p.notional_usd
        fee = p.notional_usd * fee_frac * 2.0  # entry + exit
        trades.append(
            IntradayTrade(
                symbol=symbol,
                entry_ms=bar_times[i],
                exit_ms=bar_times[j],
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
        i = j  # non-overlapping: resume at the exit bar
    return trades
