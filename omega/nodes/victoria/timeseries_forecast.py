"""
omega.nodes.victoria.timeseries_forecast
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kronos-inspired time-series forecasting signal for Victoria.

Approach — lightweight statistical forecasting (no neural-network or heavy
ML dependencies; pure Python + stdlib only):

  1. Tokenise  : extract recent OHLCV sequences per ticker (window = 30 bars)
  2. Model A   : Holt double-exponential smoothing → level + trend extrapolation
  3. Model B   : AR(p) return prediction via pure-Python OLS (p = 3 lags)
  4. Blend     : 60 % Holt / 40 % AR, soft-clipped to [-1, +1] via tanh
  5. Bias      : optional news/sentiment shift
                 - first checks for ``finbert_sentiment`` key in market_data
                 - falls back to NewsSignalProvider (F&G + RSS, free endpoints)
  6. Cache     : per-ticker forecast is reused until the close-price hash changes

Output
------
  SignalValue
    .value       : cross-ticker composite forecast signal [-1.0, +1.0]
    .confidence  : fraction of tickers with a valid forecast
    .regime_tag  : "bullish_forecast" | "bearish_forecast" | "neutral_forecast"
                   | "high_uncertainty"
    .raw         : per-ticker forecasts + sentiment bias metadata

Kronos inspiration
------------------
The Amazon Kronos paper uses zero-shot time-series tokenisation (price →
patch tokens) and a probabilistic decoder to generate quantile forecasts.
This module adopts the same *conceptual* pipeline (tokenise → model →
quantile signal) but replaces the transformer with classical exponential
smoothing + AR, keeping the dependency footprint at zero (stdlib only).

The ``forecast_signal`` per ticker is defined as::

    signal = tanh(predicted_return_1step / annualised_vol_scale)

where ``annualised_vol_scale`` is the recent 10-bar rolling volatility,
so the signal is automatically regime-normalised (large moves in
high-vol regimes produce the same signal magnitude as small moves in
calm regimes).
"""

from __future__ import annotations

import hashlib
import logging
import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger("omega.nodes.victoria.timeseries_forecast")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW = 30          # bars of history tokenised per ticker
_AR_LAGS = 3          # AR(p) order
_HOLT_ALPHA = 0.30    # level smoothing
_HOLT_BETA = 0.15     # trend smoothing
_BLEND_HOLT = 0.60    # weight on Holt forecast in blend
_BLEND_AR = 0.40      # weight on AR forecast in blend
_VOL_WINDOW = 10      # bars for rolling vol (denominator of signal)
_SENTIMENT_WEIGHT = 0.15  # max news/sentiment bias on final signal
_CACHE_TTL = 300      # seconds — 5 minutes between forced refreshes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean(prices: list) -> list[float]:
    """Strip None / NaN / inf entries, return floats."""
    result: list[float] = []
    for p in prices:
        if p is None:
            continue
        try:
            f = float(p)
            if math.isfinite(f):
                result.append(f)
        except (TypeError, ValueError):
            pass
    return result


def _returns(prices: list[float]) -> list[float]:
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] != 0
    ]


def _rolling_vol(rets: list[float], window: int) -> float:
    """Annualised rolling vol of most-recent ``window`` returns."""
    sample = [r for r in rets[-window:] if r is not None]
    if len(sample) < 2:
        return 0.02  # fallback: 2% daily vol
    mu = statistics.mean(sample)
    var = statistics.variance(sample, xbar=mu)
    return math.sqrt(var) * math.sqrt(365) or 0.02


def _ols_1d(x: list[float], y: list[float]) -> tuple[float, float]:
    """
    Ordinary least squares: fit y ~ a*x + b.

    Returns (slope, intercept).  Falls back to (0.0, mean(y)) on
    degenerate inputs.
    """
    n = len(x)
    if n < 2:
        return 0.0, (y[0] if y else 0.0)
    sx = sum(x)
    sy = sum(y)
    sxx = sum(xi * xi for xi in x)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


# ---------------------------------------------------------------------------
# Model A: Holt's double-exponential smoothing
# ---------------------------------------------------------------------------


def _holt_forecast(prices: list[float], alpha: float, beta: float) -> float | None:
    """
    Forecast one step ahead using Holt's double-exponential smoothing.

    Returns predicted next-bar price (or None if insufficient data).
    """
    if len(prices) < 4:
        return None

    # Initialise level and trend from first two observations
    level = prices[0]
    trend = prices[1] - prices[0]

    for p in prices[1:]:
        prev_level = level
        level = alpha * p + (1 - alpha) * (prev_level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend

    return level + trend


# ---------------------------------------------------------------------------
# Model B: AR(p) on returns
# ---------------------------------------------------------------------------


def _ar_forecast(rets: list[float], p: int = 3) -> float | None:
    """
    Fit a simple AR(p) model via OLS and return the 1-step return forecast.

    Uses the last ``p`` returns as regressors.  Returns None on failure.
    """
    if len(rets) < p + 4:
        return None

    # Build (X, y) from sliding windows
    xs: list[list[float]] = []
    ys: list[float] = []
    for i in range(p, len(rets)):
        xs.append(rets[i - p : i])
        ys.append(rets[i])

    # OLS per lag weight via sequential single-variable regressions
    # (Gram-Schmidt approximation — exact for p=1; good enough for p≤3)
    weights: list[float] = []
    for lag in range(p):
        col = [row[lag] for row in xs]
        slope, _ = _ols_1d(col, ys)
        weights.append(slope)

    # Predict using last p returns
    last_p = rets[-p:]
    predicted = sum(w * r for w, r in zip(weights, last_p))
    return predicted


# ---------------------------------------------------------------------------
# Per-ticker forecast aggregation
# ---------------------------------------------------------------------------


@dataclass
class TickerForecast:
    """Single-ticker forecast result."""

    ticker: str
    forecast_signal: float          # [-1.0, +1.0]
    predicted_return: float         # raw 1-step predicted return
    confidence: float               # 0.0–1.0
    holt_price: float | None = None # Holt predicted price
    ar_return: float | None = None  # AR predicted return
    vol_scale: float = 0.02
    sentiment_bias: float = 0.0
    raw: dict[str, float] = field(default_factory=dict)


def _forecast_ticker(
    ticker: str,
    data: dict[str, Any],
    sentiment_bias: float,
) -> TickerForecast | None:
    """
    Compute a single-ticker timeseries forecast.

    Parameters
    ----------
    ticker          : ticker symbol (for logging)
    data            : raw market data dict with 'close' / 'adjclose' / 'volume'
    sentiment_bias  : pre-computed news/sentiment bias in [-1, +1]

    Returns None if there is insufficient data.
    """
    close_raw = data.get("adjclose") or data.get("close") or []
    prices = _clean(close_raw)

    if len(prices) < _WINDOW:
        logger.debug("timeseries_forecast: %s skipped — need %d bars, got %d",
                     ticker, _WINDOW, len(prices))
        return None

    # Use last _WINDOW bars
    recent_prices = prices[-_WINDOW:]
    rets = _returns(recent_prices)
    vol_scale = _rolling_vol(rets, _VOL_WINDOW)

    # Model A: Holt
    holt_price = _holt_forecast(recent_prices, _HOLT_ALPHA, _HOLT_BETA)
    holt_return: float | None = None
    if holt_price is not None and recent_prices[-1] != 0:
        holt_return = (holt_price - recent_prices[-1]) / recent_prices[-1]

    # Model B: AR
    ar_return = _ar_forecast(rets, _AR_LAGS)

    # Blend
    blended_return: float | None = None
    n_models = 0
    blend_sum = 0.0
    if holt_return is not None:
        blend_sum += _BLEND_HOLT * holt_return
        n_models += 1
    if ar_return is not None:
        blend_sum += _BLEND_AR * ar_return
        n_models += 1

    if n_models == 0:
        return None

    # Normalise blend to [0, 1] weight sum
    blend_weight = (
        _BLEND_HOLT * (holt_return is not None)
        + _BLEND_AR * (ar_return is not None)
    )
    blended_return = blend_sum / blend_weight if blend_weight > 0 else 0.0

    # Convert predicted return to signal via tanh normalised by vol
    # tanh(x/vol * 0.5): predicting a 1σ move → signal ≈ 0.46
    signal_raw = math.tanh(blended_return / max(vol_scale, 1e-6) * 0.5)

    # Apply sentiment bias (additive, clamped)
    bias = max(-_SENTIMENT_WEIGHT, min(_SENTIMENT_WEIGHT,
                                       sentiment_bias * _SENTIMENT_WEIGHT))
    signal = max(-1.0, min(1.0, signal_raw + bias))

    # Confidence: degrades if models disagree (high |holt - ar| diff)
    if holt_return is not None and ar_return is not None:
        model_agreement = 1.0 - min(1.0, abs(holt_return - ar_return) /
                                        max(abs(blended_return), 1e-8))
        confidence = 0.5 + 0.5 * max(0.0, model_agreement)
    else:
        confidence = 0.4  # single model — lower confidence

    raw: dict[str, float] = {
        "blended_return": blended_return,
        "vol_scale": vol_scale,
        "signal_raw": signal_raw,
        "sentiment_bias_applied": bias,
        "n_models": float(n_models),
    }
    if holt_return is not None:
        raw["holt_return"] = holt_return
    if ar_return is not None:
        raw["ar_return"] = ar_return

    return TickerForecast(
        ticker=ticker,
        forecast_signal=signal,
        predicted_return=blended_return,
        confidence=confidence,
        holt_price=holt_price,
        ar_return=ar_return,
        vol_scale=vol_scale,
        sentiment_bias=bias,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _price_hash(data: dict[str, Any]) -> str:
    """Quick hash of the close prices for cache invalidation."""
    close_raw = data.get("adjclose") or data.get("close") or []
    key = ",".join(str(p) for p in close_raw[-_WINDOW:])
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Sentiment bias sourcing
# ---------------------------------------------------------------------------


def _get_sentiment_bias(market_data: dict[str, Any]) -> float:
    """
    Retrieve a sentiment bias signal in [-1.0, +1.0].

    Priority
    --------
    1. ``finbert_sentiment`` key in market_data (pre-computed external signal)
    2. NewsSignalProvider (F&G + RSS — zero dependencies)
    3. 0.0 fallback
    """
    # 1. finbert_sentiment — caller may inject a pre-computed FinBERT score
    for key in ("finbert_sentiment", "finbert_score", "bert_sentiment"):
        v = market_data.get(key)
        if v is not None:
            try:
                return max(-1.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                pass

    # 2. NewsSignalProvider (free, no auth required)
    try:
        from omega.nodes.victoria.news_signals import NewsSignalProvider
        news_val = NewsSignalProvider().compute(market_data)
        # Use news value only if confidence is meaningful
        if news_val.confidence >= 0.2:
            return news_val.value
    except Exception as exc:
        logger.debug("timeseries_forecast: news sentiment unavailable: %s", exc)

    return 0.0


# ---------------------------------------------------------------------------
# Public signal class
# ---------------------------------------------------------------------------


# Import the standard signal value type used across all Victoria signals
try:
    from omega.nodes.victoria.signals_advanced import SignalValue
except ImportError:
    # Standalone fallback (tests / direct import)
    @dataclass  # type: ignore[no-redef]
    class SignalValue:  # type: ignore[no-redef]
        value: float
        confidence: float
        regime_tag: str
        raw: dict


class TimeseriesForecastSignal:
    """
    Kronos-inspired lightweight time-series forecasting signal.

    Uses Holt double-exponential smoothing + AR(p) on recent OHLCV
    sequences to forecast next-period returns per ticker, then aggregates
    into a single composite signal with an optional news-projection bias.

    Thread-safety
    -------------
    The instance-level cache uses a plain dict — do NOT share a single
    instance across threads without an external lock.
    """

    # Class-level cache: {ticker: (hash_key, TickerForecast, timestamp)}
    _cache: ClassVar[dict[str, tuple[str, TickerForecast, float]]] = {}

    def __init__(self) -> None:
        self._call_count = 0
        self._cache_hits = 0

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        """
        Compute the timeseries forecast signal from OHLCV market data.

        Parameters
        ----------
        market_data : dict[ticker, dict] — standard Victoria market data dict

        Returns
        -------
        SignalValue with composite forecast signal [-1.0, +1.0]
        """
        self._call_count += 1

        if not market_data:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="neutral_forecast",
                raw={"error": 0.0, "ticker_count": 0.0},
            )

        # Sentiment bias (shared across all tickers in this cycle)
        try:
            sentiment_bias = _get_sentiment_bias(market_data)
        except Exception as exc:
            logger.debug("timeseries_forecast: sentiment fetch failed: %s", exc)
            sentiment_bias = 0.0

        # Per-ticker forecasts (with cache)
        forecasts: list[TickerForecast] = []
        now = time.time()

        for ticker, data in market_data.items():
            if not data or not isinstance(data, dict):
                continue

            # Cache check
            price_h = _price_hash(data)
            cached = TimeseriesForecastSignal._cache.get(ticker)
            if (
                cached is not None
                and cached[0] == price_h
                and now - cached[2] < _CACHE_TTL
            ):
                self._cache_hits += 1
                fc = cached[1]
                # Re-apply current sentiment bias (may have changed)
                rebiased = max(
                    -1.0,
                    min(1.0, fc.raw.get("signal_raw", fc.forecast_signal)
                        + max(-_SENTIMENT_WEIGHT,
                              min(_SENTIMENT_WEIGHT,
                                  sentiment_bias * _SENTIMENT_WEIGHT))),
                )
                forecasts.append(TickerForecast(
                    ticker=fc.ticker,
                    forecast_signal=rebiased,
                    predicted_return=fc.predicted_return,
                    confidence=fc.confidence,
                    holt_price=fc.holt_price,
                    ar_return=fc.ar_return,
                    vol_scale=fc.vol_scale,
                    sentiment_bias=sentiment_bias * _SENTIMENT_WEIGHT,
                    raw=dict(fc.raw),
                ))
                continue

            # Compute fresh forecast
            try:
                fc = _forecast_ticker(ticker, data, sentiment_bias)
            except Exception as exc:
                logger.debug(
                    "timeseries_forecast: ticker=%s failed: %s", ticker, exc
                )
                fc = None

            if fc is not None:
                TimeseriesForecastSignal._cache[ticker] = (price_h, fc, now)
                forecasts.append(fc)

        if not forecasts:
            return SignalValue(
                value=0.0,
                confidence=0.0,
                regime_tag="neutral_forecast",
                raw={
                    "ticker_count": float(len(market_data)),
                    "forecast_count": 0.0,
                    "sentiment_bias": sentiment_bias,
                    "cache_hits": float(self._cache_hits),
                },
            )

        # Composite: confidence-weighted average of per-ticker signals
        total_weight = sum(fc.confidence for fc in forecasts)
        if total_weight > 0:
            composite = sum(
                fc.forecast_signal * fc.confidence for fc in forecasts
            ) / total_weight
        else:
            composite = sum(fc.forecast_signal for fc in forecasts) / len(forecasts)

        composite = max(-1.0, min(1.0, composite))

        # Aggregate confidence
        avg_confidence = total_weight / len(forecasts)
        n_valid = len(forecasts)
        n_requested = len(
            [t for t, d in market_data.items() if isinstance(d, dict)]
        )
        coverage_conf = n_valid / max(1, n_requested)
        final_confidence = min(1.0, avg_confidence * 0.7 + coverage_conf * 0.3)

        # Regime tag
        if final_confidence < 0.3:
            regime_tag = "high_uncertainty"
        elif composite > 0.1:
            regime_tag = "bullish_forecast"
        elif composite < -0.1:
            regime_tag = "bearish_forecast"
        else:
            regime_tag = "neutral_forecast"

        # Raw output — include per-ticker summary
        per_ticker_raw: dict[str, float] = {}
        for fc in forecasts:
            per_ticker_raw[f"{fc.ticker}_signal"] = round(fc.forecast_signal, 4)
            per_ticker_raw[f"{fc.ticker}_ret"] = round(fc.predicted_return, 6)

        raw: dict[str, float] = {
            "composite": round(composite, 4),
            "ticker_count": float(n_requested),
            "forecast_count": float(n_valid),
            "avg_confidence": round(avg_confidence, 4),
            "sentiment_bias": round(sentiment_bias, 4),
            "cache_hits": float(self._cache_hits),
            "call_count": float(self._call_count),
            **per_ticker_raw,
        }

        logger.debug(
            "timeseries_forecast: composite=%.4f conf=%.3f tickers=%d/%d "
            "sentiment_bias=%.3f regime=%s",
            composite,
            final_confidence,
            n_valid,
            n_requested,
            sentiment_bias,
            regime_tag,
        )

        return SignalValue(
            value=composite,
            confidence=final_confidence,
            regime_tag=regime_tag,
            raw=raw,
        )
