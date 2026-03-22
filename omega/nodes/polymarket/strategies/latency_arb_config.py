"""
omega.nodes.polymarket.strategies.latency_arb_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Configuration for the latency-arbitrage engine.

All timing values are in milliseconds unless the field name says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LatencyArbConfig:
    """
    Configuration for LatencyArbEngine.

    The strategy exploits the empirically-observed 9-16 second delay between
    a significant Binance BTC/USDT price move and the corresponding
    repricing on Polymarket BTC-correlated prediction markets.

    Attributes
    ----------
    binance_ws_url
        Full Binance trade-stream WebSocket URL.
    price_move_threshold
        Minimum relative price move (as a fraction, e.g. 0.0011 = 0.11%)
        required to trigger an arb scan.
    min_delay_ms
        Minimum time to wait after detecting a move before querying
        Polymarket. Never enter before this window opens. (default: 9 000 ms)
    max_delay_ms
        Hard deadline: if Polymarket has not been queried and an order placed
        before this time elapses, abort the cycle. (default: 16 000 ms)
    max_position_usd
        Maximum USD notional per single trade.
    markets_to_watch
        List of Polymarket condition_ids for BTC-correlated markets.
        These are the markets the engine will query during an arb cycle.
    cooldown_seconds
        Minimum gap between consecutive arb trades (avoids rapid-fire churn).
    max_daily_trades
        Circuit-breaker: halt all trading after this many completed trades
        in a 24-hour window.
    """

    binance_ws_url: str = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    price_move_threshold: float = 0.0011  # 0.11 %
    min_delay_ms: int = 9_000
    max_delay_ms: int = 16_000
    max_position_usd: float = 500.0
    markets_to_watch: list[str] = field(default_factory=list)
    cooldown_seconds: int = 60
    max_daily_trades: int = 20

    def __post_init__(self) -> None:
        if self.min_delay_ms >= self.max_delay_ms:
            raise ValueError(
                f"min_delay_ms ({self.min_delay_ms}) must be less than "
                f"max_delay_ms ({self.max_delay_ms})"
            )
        if self.price_move_threshold <= 0:
            raise ValueError("price_move_threshold must be positive")
        if self.max_position_usd <= 0:
            raise ValueError("max_position_usd must be positive")

    @property
    def window_ms(self) -> int:
        """Width of the execution window in ms (max - min)."""
        return self.max_delay_ms - self.min_delay_ms
