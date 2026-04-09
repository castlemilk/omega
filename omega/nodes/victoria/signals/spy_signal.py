"""
SPY / BTC correlation signal for Victoria.

## Rationale

Since 2020, BTC has shown meaningful co-movement with US equities during
macro-driven regimes (Fed policy, risk-on/risk-off). When BTC/SPY rolling
correlation exceeds 0.4, SPY momentum is a reliable leading indicator:
  - SPY positive 4h momentum → risk-on → BTC bullish → +0.3
  - SPY negative 4h momentum → risk-off → BTC bearish → -0.3
  - Rolling 20-day BTC/SPY correlation < 0.4 → decoupled → 0.0

Signal is intentionally small (±0.3 cap) — SPY co-movement is a weak beta
signal, not an alpha source. It acts as a directional overlay that confirms
or dampens other signals rather than driving position entry on its own.

## Data sources

SPY: Yahoo Finance via yfinance (ticker "SPY"), 4h bars for recent momentum
BTC: CoinGecko price history passed through market_data (already fetched)

## Output

float in [-0.3, 0.3]:
  +0.3 = risk-on (SPY momentum positive, corr > 0.4)
  -0.3 = risk-off (SPY momentum negative, corr > 0.4)
   0.0 = decoupled (corr ≤ 0.4) or flat momentum

## Fallback

Returns 0.0 if yfinance not installed or SPY fetch fails.
"""

import logging
import math
import time
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signals.spy_signal")

_CORR_THRESHOLD = 0.4  # minimum 20d BTC/SPY correlation to fire
_WINDOW = 20  # days for correlation calculation
_SIGNAL_CAP = 0.3  # max signal magnitude — SPY beta, not alpha
_SPY_CACHE_TTL = 3600  # 1 hour


try:
    import yfinance as yf

    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False
    logger.warning(
        "SPYSignal unavailable: yfinance not installed (returning 0.0). "
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
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    denom_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return num / (denom_x * denom_y)


class SPYSignal:
    """
    SPY/BTC momentum signal — fires when BTC/SPY correlation is strong.

    Uses 4h SPY momentum as a directional overlay: positive momentum = risk-on
    (+0.3), negative = risk-off (-0.3). Only active when rolling 20-day
    BTC/SPY Pearson correlation exceeds 0.4.

    Stubs to 0.0 if yfinance is not installed.
    """

    def __init__(self, window: int = _WINDOW, timeout: float = 10.0) -> None:
        self._window = window
        self._timeout = timeout
        self._spy_daily_cache: list[float] = []
        self._spy_daily_ts: float = 0.0
        self._spy_4h_cache: list[float] = []
        self._spy_4h_ts: float = 0.0

    def compute(self, market_data: dict[str, Any]) -> float:
        """
        Compute SPY/BTC co-movement signal.

        Args:
            market_data: Dict keyed by ticker. Expects "BTCUSDT" with a "close"
                         or "adjclose" price list (daily frequency).

        Returns:
            float in [-0.3, 0.3]. Positive = risk-on. Zero = decoupled.
        """
        if not _HAS_YFINANCE:
            return 0.0

        # --- Correlation gate: 20-day daily BTC/SPY ---
        spy_daily = self._get_spy_daily()
        if len(spy_daily) < self._window:
            return 0.0

        btc_data = market_data.get("BTCUSDT") or {}
        btc_prices_raw = btc_data.get("adjclose") or btc_data.get("close") or []
        btc_prices = [float(p) for p in btc_prices_raw if p is not None and float(p) > 0]
        if len(btc_prices) < self._window:
            return 0.0

        spy_rets = [
            (spy_daily[i] - spy_daily[i - 1]) / spy_daily[i - 1]
            for i in range(1, len(spy_daily))
            if spy_daily[i - 1] != 0
        ][-self._window :]
        btc_rets = [
            (btc_prices[i] - btc_prices[i - 1]) / btc_prices[i - 1]
            for i in range(1, len(btc_prices))
            if btc_prices[i - 1] != 0
        ][-self._window :]

        corr = _pearson(spy_rets, btc_rets)
        if corr is None or corr < _CORR_THRESHOLD:
            logger.debug(
                "SPYSignal: corr=%.3f below threshold %.2f — neutral",
                corr or 0.0,
                _CORR_THRESHOLD,
            )
            return 0.0

        # --- Momentum: 4h SPY return ---
        spy_4h = self._get_spy_4h()
        if len(spy_4h) < 2:
            return 0.0

        # Two 4h bars = ~8h momentum (roughly one US session)
        spy_momentum = (spy_4h[-1] - spy_4h[-2]) / spy_4h[-2] if spy_4h[-2] != 0 else 0.0

        if spy_momentum == 0.0:
            return 0.0

        # Scale: ±0.5% 4h move maps to full ±0.3 signal cap
        # Smaller moves produce proportionally smaller signals
        raw = spy_momentum / 0.005 * _SIGNAL_CAP
        signal = max(-_SIGNAL_CAP, min(_SIGNAL_CAP, raw))

        logger.info(
            "SPYSignal: corr=%.3f spy_4h_ret=%.4f → signal=%.3f (risk-%s)",
            corr,
            spy_momentum,
            signal,
            "on" if signal > 0 else "off",
        )
        return signal

    # ------------------------------------------------------------------

    def _get_spy_daily(self) -> list[float]:
        """Fetch daily SPY close prices, 1h cache."""
        now = time.time()
        if now - self._spy_daily_ts < _SPY_CACHE_TTL and self._spy_daily_cache:
            return self._spy_daily_cache
        try:
            ticker = yf.Ticker("SPY")
            hist = ticker.history(
                period=f"{self._window + 5}d", interval="1d", timeout=self._timeout
            )
            if hist.empty:
                return self._spy_daily_cache
            prices = [float(p) for p in hist["Close"].dropna().tolist() if p > 0]
            if len(prices) < 5:
                return self._spy_daily_cache
            self._spy_daily_cache = prices
            self._spy_daily_ts = now
            logger.debug(
                "SPYSignal: fetched %d daily SPY prices (latest=%.2f)", len(prices), prices[-1]
            )
            return self._spy_daily_cache
        except Exception as exc:
            logger.warning("SPYSignal: daily fetch failed: %s", exc)
            return self._spy_daily_cache

    def _get_spy_4h(self) -> list[float]:
        """Fetch 4h SPY bars (last 5 days), 1h cache."""
        now = time.time()
        if now - self._spy_4h_ts < _SPY_CACHE_TTL and self._spy_4h_cache:
            return self._spy_4h_cache
        try:
            ticker = yf.Ticker("SPY")
            hist = ticker.history(period="5d", interval="1h", timeout=self._timeout)
            if hist.empty:
                return self._spy_4h_cache
            closes = [float(p) for p in hist["Close"].dropna().tolist() if p > 0]
            # Resample 1h → 4h by taking every 4th close (approximate 4h bar)
            prices_4h = closes[::4] if len(closes) >= 4 else closes
            if len(prices_4h) < 2:
                return self._spy_4h_cache
            self._spy_4h_cache = prices_4h
            self._spy_4h_ts = now
            logger.debug(
                "SPYSignal: fetched %d 4h SPY bars (latest=%.2f)", len(prices_4h), prices_4h[-1]
            )
            return self._spy_4h_cache
        except Exception as exc:
            logger.warning("SPYSignal: 4h fetch failed: %s", exc)
            return self._spy_4h_cache
