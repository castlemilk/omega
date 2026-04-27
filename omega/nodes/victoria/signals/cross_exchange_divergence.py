"""Cross-exchange price divergence signal for Victoria.

Inspired by the Polymarket latency-arbitrage pattern (Binance leads spot/perp
prices by ~2-3 seconds vs slower-updating venues). The same lag exists between
Binance WS (real-time tick stream) and our REST snapshot providers (CoinGecko
returns the last bar's close, often 30-60s stale).

When the WS tick price has moved meaningfully away from the REST snapshot, the
REST snapshot is the trailing indicator and the WS price is the truth. The gap
itself is a directional signal:
  - WS > REST by Δ%   → REST is catching up upward → bullish bias
  - WS < REST by Δ%   → REST is catching up downward → bearish bias
  - |gap| < threshold → no divergence → neutral

The signal is normalized to [-1, +1] by dividing the percent gap by a configurable
threshold (default 0.10% = 10 bps). A gap of ±2× the threshold saturates at ±1.

Output: float in [-1, +1]
  > 0 = WS leading up (bullish)
  < 0 = WS leading down (bearish)
  0   = WS price unavailable, REST close unavailable, or gap below threshold

Feature flag: ``cross_exchange_divergence_enabled``.

Dependencies: requires the ``ws_feeds`` manager initialised by
SignalGenerationNode (which it is whenever ``ws_microstructure=True`` —
v161_live and later have this on by default).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.cross_exchange_divergence")

# Default threshold in fraction (0.001 = 0.10%). A 10 bps gap maps to signal=±0.5.
_DEFAULT_THRESHOLD_PCT = 0.001


def compute_divergence(
    ws_price: float | None,
    rest_close: float | None,
    threshold_pct: float = _DEFAULT_THRESHOLD_PCT,
) -> float:
    """Pure function: gap = (ws - rest) / rest, clipped to [-1, +1] after scaling.

    >>> compute_divergence(101.0, 100.0, 0.001)  # 1.0% gap, 10× threshold → +1.0
    1.0
    >>> round(compute_divergence(100.05, 100.0, 0.001), 4)  # 5 bps gap → +0.25
    0.25
    >>> compute_divergence(99.0, 100.0, 0.001)  # -1.0% gap → -1.0
    -1.0
    >>> compute_divergence(None, 100.0)
    0.0
    """
    if ws_price is None or rest_close is None:
        return 0.0
    if rest_close <= 0:
        return 0.0
    gap = (ws_price - rest_close) / rest_close
    if threshold_pct <= 0:
        return 0.0
    # Map gap to signal: gap = ±threshold → ±0.5; gap = ±2*threshold → saturate ±1.
    raw = gap / (2.0 * threshold_pct)
    return max(-1.0, min(1.0, raw))


class CrossExchangeDivergenceSignal:
    """Compares WS real-time price vs REST snapshot close for each ticker."""

    def __init__(self, threshold_pct: float = _DEFAULT_THRESHOLD_PCT) -> None:
        self._threshold = float(threshold_pct)

    def compute(self, symbol: str, ws_feeds: Any | None, market_data: dict[str, Any]) -> float:
        if ws_feeds is None:
            return 0.0
        try:
            ws_price = ws_feeds.get_latest_price(symbol)
        except Exception as exc:
            logger.debug("ws.get_latest_price(%s) failed: %s", symbol, exc)
            return 0.0
        if ws_price is None:
            return 0.0

        ticker_data = market_data.get(symbol) or {}
        rest_close: float | None = None
        prices = ticker_data.get("close") or ticker_data.get("adjclose")
        if isinstance(prices, list) and prices:
            try:
                rest_close = float(prices[-1])
            except (TypeError, ValueError):
                rest_close = None

        return compute_divergence(ws_price, rest_close, self._threshold)


def _self_test() -> None:
    assert compute_divergence(100.0, 100.0) == 0.0
    assert compute_divergence(101.0, 100.0, 0.001) == 1.0
    assert compute_divergence(99.0, 100.0, 0.001) == -1.0
    assert round(compute_divergence(100.05, 100.0, 0.001), 4) == 0.25
    assert compute_divergence(None, 100.0) == 0.0
    assert compute_divergence(100.0, None) == 0.0
    assert compute_divergence(100.0, 0.0) == 0.0
    print("cross_exchange_divergence: OK")


if __name__ == "__main__":
    _self_test()
