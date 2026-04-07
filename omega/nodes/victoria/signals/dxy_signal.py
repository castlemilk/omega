"""
DXY / BTC correlation signal for Victoria.

## Rationale

The US Dollar Index (DXY) is historically inversely correlated with risk assets
including BTC. The relationship is regime-dependent:
  - Strong negative correlation (DXY ↑ → BTC ↓) is common in macro-driven regimes
    (Fed tightening, flight to safety, USD liquidity crunch).
  - Correlation weakens or inverts during idiosyncratic crypto events (FTX, halving).

This signal fires only when the correlation is strong AND directional — i.e. when
DXY is actively rising AND the rolling BTC/DXY correlation is below -0.5:
  → DXY rising + corr < -0.5 → BTC likely to fall → bearish signal (negative output)
  → DXY falling + corr < -0.5 → BTC likely to rise → bullish signal (positive output)
  → |corr| >= -0.5 → correlation too weak → return 0.0

## Data sources

DXY: Yahoo Finance via yfinance (ticker "DX-Y.NYB")
BTC: CoinGecko price history passed through market_data (already fetched by victoria_node)

## Fallback / stub

If yfinance is not installed (`pip install yfinance`), the class stubs out and returns 0.0.
Install it to activate:
  pip install yfinance

## Output

float in [-1, 1]:
  -1.0 = strong bearish signal (DXY rising fast, corr very negative)
  +1.0 = strong bullish signal (DXY falling fast, corr very negative)
   0.0 = neutral (correlation above threshold, or DXY direction unclear)

Signal magnitude is scaled by how much stronger the correlation is beyond -0.5.
"""

import logging
import math
import time
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.dxy_signal")

_CORR_THRESHOLD = -0.5     # only fire when 20d rolling correlation is below this
_WINDOW = 20               # days of DXY/BTC price history for correlation
_DXY_CACHE_TTL = 3600      # 1 hour — DXY price data cached between cycles


try:
    import yfinance as yf
    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False
    logger.warning(
        "DXYSignal unavailable: yfinance not installed (returning 0.0). "
        "Run `pip install yfinance` to activate."
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length lists. Returns None if insufficient data."""
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return num / (denom_x * denom_y)


class DXYSignal:
    """
    DXY/BTC correlation signal.

    Returns a directional signal when the rolling 20-day BTC/DXY correlation
    is below -0.5 (strong inverse relationship), scaled by the direction and
    magnitude of DXY's recent move.

    Stubs to 0.0 if yfinance is not installed.
    """

    def __init__(self, window: int = _WINDOW, timeout: float = 10.0) -> None:
        self._window = window
        self._timeout = timeout
        self._dxy_cache: list[float] = []
        self._dxy_cache_ts: float = 0.0

    def compute(self, market_data: dict[str, Any]) -> float:
        """
        Compute DXY/BTC correlation signal.

        Args:
            market_data: Dict keyed by ticker symbol. Expects "BTCUSDT" to contain
                         a "close" or "adjclose" price list.

        Returns:
            float in [-1, 1]. Negative = bearish (DXY up, inverse corr active).
            Positive = bullish (DXY down, inverse corr active). 0 = no signal.
        """
        if not _HAS_YFINANCE:
            return 0.0

        dxy_prices = self._get_dxy()
        if len(dxy_prices) < self._window:
            return 0.0

        btc_data = market_data.get("BTCUSDT") or {}
        btc_prices_raw = btc_data.get("adjclose") or btc_data.get("close") or []
        btc_prices = [float(p) for p in btc_prices_raw if p is not None and float(p) > 0]
        if len(btc_prices) < self._window:
            return 0.0

        # 20-day returns for both series
        dxy_rets = [
            (dxy_prices[i] - dxy_prices[i - 1]) / dxy_prices[i - 1]
            for i in range(1, len(dxy_prices))
            if dxy_prices[i - 1] != 0
        ][-self._window:]
        btc_rets = [
            (btc_prices[i] - btc_prices[i - 1]) / btc_prices[i - 1]
            for i in range(1, len(btc_prices))
            if btc_prices[i - 1] != 0
        ][-self._window:]

        corr = _pearson(dxy_rets, btc_rets)
        if corr is None or corr >= _CORR_THRESHOLD:
            # Correlation too weak — no reliable cross-asset signal
            logger.debug("DXYSignal: corr=%.3f above threshold %.2f — neutral", corr or 0.0, _CORR_THRESHOLD)
            return 0.0

        # DXY direction: 5-day return of DXY (recent momentum)
        if len(dxy_prices) < 5:
            return 0.0
        dxy_5d_ret = (dxy_prices[-1] - dxy_prices[-5]) / dxy_prices[-5] if dxy_prices[-5] != 0 else 0.0

        # Signal strength scales with how far correlation exceeds threshold and DXY move size
        # corr is negative (e.g. -0.7); excess = corr - threshold = -0.7 - (-0.5) = -0.2
        corr_excess = abs(corr - _CORR_THRESHOLD)  # positive, larger = stronger relationship
        # DXY rising (positive ret) + negative corr → BTC bearish → negative signal
        # DXY falling (negative ret) + negative corr → BTC bullish → positive signal
        raw = -dxy_5d_ret * corr_excess * 20.0  # scale: 1% DXY move + full excess → ~0.4 signal
        signal = max(-1.0, min(1.0, raw))

        logger.info(
            "DXYSignal: corr=%.3f dxy_5d_ret=%.4f → signal=%.3f",
            corr,
            dxy_5d_ret,
            signal,
        )
        return signal

    def _get_dxy(self) -> list[float]:
        """Fetch DXY prices via yfinance, with 1-hour cache."""
        now = time.time()
        if now - self._dxy_cache_ts < _DXY_CACHE_TTL and self._dxy_cache:
            return self._dxy_cache

        try:
            ticker = yf.Ticker("DX-Y.NYB")
            hist = ticker.history(period=f"{self._window + 5}d", interval="1d", timeout=self._timeout)
            if hist.empty:
                logger.debug("DXYSignal: empty DXY history from yfinance")
                return self._dxy_cache  # stale on failure
            prices = [float(p) for p in hist["Close"].dropna().tolist() if p > 0]
            if len(prices) < 5:
                return self._dxy_cache
            self._dxy_cache = prices
            self._dxy_cache_ts = now
            logger.debug("DXYSignal: fetched %d DXY prices (latest=%.3f)", len(prices), prices[-1])
            return self._dxy_cache
        except Exception as exc:
            logger.warning("DXYSignal: yfinance fetch failed: %s", exc)
            return self._dxy_cache  # return stale cache on error
