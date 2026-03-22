"""
omega.nodes.victoria.signals_advanced
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Advanced signal types for crypto market microstructure analysis.

Signal classes:
  - OrderFlowSignal   : order book imbalance and VPIN-style flow toxicity
  - CrossAssetSignal  : BTC/ETH/SOL correlations and lead-lag detection
  - MicrostructureSignal : spread dynamics, quote stuffing, tick patterns
  - SentimentSignal   : fear/greed proxy via funding rates + open interest

Each signal returns a SignalValue with value, confidence, and regime_tag.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Any


@dataclass
class SignalValue:
    """Output of a signal computation."""

    value: float  # directional: -1.0 (bear) to +1.0 (bull)
    confidence: float  # 0.0 (no confidence) to 1.0 (full confidence)
    regime_tag: str  # e.g. "trending", "ranging", "high_vol", "toxic_flow"
    raw: dict[str, float]  # underlying computed values for inspection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _returns(prices: list[float]) -> list[float]:
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] != 0
    ]


def _zscore(values: list[float], period: int) -> float | None:
    if len(values) < period + 1:
        return None
    recent = values[-period:]
    mu = statistics.mean(recent)
    sigma = statistics.pstdev(recent)
    if sigma == 0:
        return 0.0
    return (recent[-1] - mu) / sigma


def _pearson(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    x, y = x[-n:], y[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in x))
    dy = math.sqrt(sum((v - my) ** 2 for v in y))
    denom = dx * dy
    return num / denom if denom > 0 else 0.0


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


# ---------------------------------------------------------------------------
# OrderFlowSignal
# ---------------------------------------------------------------------------


class OrderFlowSignal:
    """
    Tracks order book imbalance and trade flow toxicity (VPIN-style).

    VPIN (Volume-synchronized Probability of Informed trading) approximation:
    - Classifies each volume bar as buy-initiated or sell-initiated using
      price direction as a proxy (bulk volume classification).
    - Toxicity = |buy_vol - sell_vol| / total_vol over a rolling window.
    - High toxicity (> 0.7) signals informed trading / adverse selection.

    Order book imbalance:
    - bid_size / (bid_size + ask_size) → > 0.6 bullish, < 0.4 bearish.
    """

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        prices = market_data.get("close", [])
        volumes = market_data.get("volume", [])
        bid_sizes = market_data.get("bid_sizes", [])
        ask_sizes = market_data.get("ask_sizes", [])

        raw: dict[str, float] = {}

        # VPIN approximation
        vpin = self._compute_vpin(prices, volumes, window=50)
        raw["vpin"] = vpin if vpin is not None else 0.5

        # Order book imbalance
        obi = self._compute_obi(bid_sizes, ask_sizes)
        raw["order_book_imbalance"] = obi if obi is not None else 0.0

        # Derive signal and confidence
        if vpin is None and obi is None:
            return SignalValue(value=0.0, confidence=0.0, regime_tag="insufficient_data", raw=raw)

        toxicity = raw["vpin"]
        regime_tag = (
            "toxic_flow" if toxicity > 0.7 else ("normal_flow" if toxicity < 0.4 else "mixed_flow")
        )

        # In toxic flow, fade the direction signal (informed traders dominate)
        # In normal flow, follow the order book imbalance
        if obi is not None:
            direction = obi * 2 - 1  # map [0,1] → [-1,1]
        else:
            direction = 0.0

        # Toxic flow dampens signal confidence
        confidence = max(0.1, 1.0 - toxicity) if vpin is not None else 0.5
        value = direction * (1.0 - toxicity * 0.5) if vpin is not None else direction

        raw["direction"] = direction
        return SignalValue(
            value=max(-1.0, min(1.0, value)),
            confidence=max(0.0, min(1.0, confidence)),
            regime_tag=regime_tag,
            raw=raw,
        )

    def _compute_vpin(
        self, prices: list[float], volumes: list[float], window: int = 50
    ) -> float | None:
        n = min(len(prices), len(volumes))
        if n < 10:
            return None
        prices = prices[-n:]
        volumes = volumes[-n:]
        window = min(window, n)

        buy_vol = 0.0
        sell_vol = 0.0
        for i in range(1, window):
            idx = n - window + i
            if idx <= 0:
                continue
            if prices[idx] > prices[idx - 1]:
                buy_vol += volumes[idx]
            elif prices[idx] < prices[idx - 1]:
                sell_vol += volumes[idx]
            else:
                buy_vol += volumes[idx] * 0.5
                sell_vol += volumes[idx] * 0.5

        total = buy_vol + sell_vol
        if total == 0:
            return 0.5
        return abs(buy_vol - sell_vol) / total

    def _compute_obi(self, bid_sizes: list[float], ask_sizes: list[float]) -> float | None:
        if not bid_sizes or not ask_sizes:
            return None
        bid = bid_sizes[-1] if bid_sizes else 0.0
        ask = ask_sizes[-1] if ask_sizes else 0.0
        total = bid + ask
        if total == 0:
            return 0.5
        return bid / total


# ---------------------------------------------------------------------------
# CrossAssetSignal
# ---------------------------------------------------------------------------


class CrossAssetSignal:
    """
    Tracks correlations between BTC/ETH/SOL and detects lead-lag relationships.

    Lead-lag: if BTC returns at time t-k correlate with target asset returns
    at time t, BTC "leads" the target. Lag k=1 is most common in crypto.

    Correlation regimes:
      - high_correlation (> 0.7): risk-on/risk-off dominates
      - decorrelated (< 0.3):     asset-specific drivers active
      - divergent (negative):     potential pair trade opportunity
    """

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        btc = market_data.get("BTCUSDT", {})
        eth = market_data.get("ETHUSDT", {})
        sol = market_data.get("SOLUSDT", {})
        target_prices = market_data.get("target_prices", [])

        btc_prices = btc.get("close", []) if btc else []
        eth_prices = eth.get("close", []) if eth else []
        sol_prices = sol.get("close", []) if sol else []

        raw: dict[str, float] = {}

        # Compute returns
        btc_rets = _returns(btc_prices) if len(btc_prices) > 1 else []
        eth_rets = _returns(eth_prices) if len(eth_prices) > 1 else []
        sol_rets = _returns(sol_prices) if len(sol_prices) > 1 else []
        target_rets = _returns(target_prices) if len(target_prices) > 1 else []

        # BTC/ETH/SOL pair correlations
        if btc_rets and eth_rets:
            raw["btc_eth_corr"] = _pearson(btc_rets, eth_rets)
        if btc_rets and sol_rets:
            raw["btc_sol_corr"] = _pearson(btc_rets, sol_rets)
        if eth_rets and sol_rets:
            raw["eth_sol_corr"] = _pearson(eth_rets, sol_rets)

        # Lead-lag: does BTC lead target?
        lead_lag_signal = 0.0
        if btc_rets and target_rets and len(btc_rets) > 5 and len(target_rets) > 5:
            ll = self._lead_lag(btc_rets, target_rets, max_lag=3)
            raw["btc_lead_lag_corr"] = ll["max_corr"]
            raw["btc_lead_lag_k"] = float(ll["best_lag"])
            if ll["best_lag"] > 0 and ll["max_corr"] > 0.3:
                lead_lag_signal = ll["max_corr"] * (1.0 if btc_rets[-1] > 0 else -1.0)

        # Determine regime from average cross-asset correlation
        corrs = [v for k, v in raw.items() if k.endswith("_corr") and "lead" not in k]
        avg_corr = sum(corrs) / len(corrs) if corrs else 0.0
        raw["avg_cross_corr"] = avg_corr

        if avg_corr > 0.7:
            regime_tag = "high_correlation"
            # In high-corr regime, follow BTC direction
            btc_dir = 1.0 if btc_rets and btc_rets[-1] > 0 else -1.0
            value = btc_dir * avg_corr
            confidence = avg_corr
        elif avg_corr < 0.3:
            regime_tag = "decorrelated"
            # Lead-lag signal takes precedence
            value = lead_lag_signal
            confidence = 0.4
        elif avg_corr < 0:
            regime_tag = "divergent"
            # Pairs trade opportunity — signal from lead-lag
            value = lead_lag_signal
            confidence = 0.5
        else:
            regime_tag = "moderate_correlation"
            value = lead_lag_signal
            confidence = 0.3

        return SignalValue(
            value=max(-1.0, min(1.0, value)),
            confidence=max(0.0, min(1.0, confidence)),
            regime_tag=regime_tag,
            raw=raw,
        )

    def _lead_lag(
        self, leader: list[float], follower: list[float], max_lag: int = 3
    ) -> dict[str, Any]:
        best_corr = 0.0
        best_lag = 0
        n = min(len(leader), len(follower))
        for lag in range(1, min(max_lag + 1, n - 2)):
            lead = leader[-(n - lag) :]
            follow = follower[-n:-lag] if lag > 0 else follower[-n:]
            corr = abs(_pearson(lead, follow))
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        return {"max_corr": best_corr, "best_lag": best_lag}


# ---------------------------------------------------------------------------
# MicrostructureSignal
# ---------------------------------------------------------------------------


class MicrostructureSignal:
    """
    Analyzes spread dynamics, quote stuffing detection, and tick patterns.

    Spread dynamics: bid-ask spread relative to its rolling mean.
    Quote stuffing: abnormally high update rate with low volume fill rate.
    Tick patterns: consecutive up/down ticks, run lengths.
    """

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        prices = market_data.get("close", [])
        highs = market_data.get("high", [])
        lows = market_data.get("low", [])
        volumes = market_data.get("volume", [])
        spreads = market_data.get("spreads", [])  # bid-ask spread time series
        quote_updates = market_data.get("quote_updates", [])

        raw: dict[str, float] = {}

        # Spread dynamics
        spread_signal = 0.0
        if spreads and len(spreads) > 5:
            spread_z = _zscore(spreads, min(20, len(spreads) - 1))
            if spread_z is not None:
                raw["spread_zscore"] = spread_z
                # Wide spread (high z) = illiquid = signal dampener
                spread_signal = -abs(spread_z) / 4.0  # max -0.5 dampening

        # Quote stuffing detection
        stuffing_detected = False
        if quote_updates and volumes and len(quote_updates) > 3:
            qs = self._quote_stuffing_score(quote_updates, volumes)
            raw["quote_stuffing_score"] = qs
            stuffing_detected = qs > 0.8

        # Tick pattern: run length and momentum
        tick_signal = 0.0
        if len(prices) >= 10:
            runs = self._tick_runs(prices, n=20)
            raw["tick_run_length"] = float(runs["current_run"])
            raw["tick_momentum"] = runs["momentum"]
            tick_signal = runs["momentum"]

        # High-low range efficiency (are candles directional or choppy?)
        efficiency = 0.0
        if highs and lows and prices and len(prices) > 5:
            efficiency = self._range_efficiency(prices, highs, lows, window=10)
            raw["range_efficiency"] = efficiency

        # Composite
        if stuffing_detected:
            regime_tag = "quote_stuffing"
            value = 0.0
            confidence = 0.1
        elif raw.get("spread_zscore", 0) > 2.0:
            regime_tag = "wide_spread"
            value = tick_signal * 0.3
            confidence = 0.2
        elif efficiency > 0.7:
            regime_tag = "trending_candles"
            value = tick_signal
            confidence = efficiency
        else:
            regime_tag = "choppy"
            value = tick_signal * 0.5
            confidence = 0.3

        value += spread_signal
        return SignalValue(
            value=max(-1.0, min(1.0, value)),
            confidence=max(0.0, min(1.0, confidence)),
            regime_tag=regime_tag,
            raw=raw,
        )

    def _quote_stuffing_score(self, quote_updates: list[float], volumes: list[float]) -> float:
        """High update rate + low volume fill = stuffing score."""
        n = min(len(quote_updates), len(volumes))
        if n < 3:
            return 0.0
        avg_updates = statistics.mean(quote_updates[-n:])
        avg_vol = statistics.mean([v for v in volumes[-n:] if v > 0]) or 1.0
        # Normalize: many updates per unit volume = suspicious
        score = min(1.0, avg_updates / (avg_vol + 1) / 100.0)
        return score

    def _tick_runs(self, prices: list[float], n: int = 20) -> dict[str, float]:
        recent = prices[-min(n, len(prices)) :]
        if len(recent) < 2:
            return {"current_run": 0.0, "momentum": 0.0}

        directions = []
        for i in range(1, len(recent)):
            if recent[i] > recent[i - 1]:
                directions.append(1)
            elif recent[i] < recent[i - 1]:
                directions.append(-1)
            else:
                directions.append(0)

        # Current run length
        run = 1
        for i in range(len(directions) - 1, 0, -1):
            if directions[i] == directions[-1] and directions[i] != 0:
                run += 1
            else:
                break

        # Momentum: proportion of up vs down ticks
        ups = sum(1 for d in directions if d > 0)
        downs = sum(1 for d in directions if d < 0)
        total = ups + downs
        momentum = (ups - downs) / total if total > 0 else 0.0

        return {
            "current_run": float(run * (directions[-1] if directions else 0)),
            "momentum": momentum,
        }

    def _range_efficiency(
        self, prices: list[float], highs: list[float], lows: list[float], window: int = 10
    ) -> float:
        """Directional movement / total range — measures trend efficiency."""
        n = min(window, len(prices), len(highs), len(lows))
        if n < 2:
            return 0.5
        p = prices[-n:]
        h = highs[-n:]
        lo = lows[-n:]
        net_move = abs(p[-1] - p[0])
        total_range = sum(h[i] - lo[i] for i in range(n))
        return net_move / total_range if total_range > 0 else 0.5


# ---------------------------------------------------------------------------
# SentimentSignal
# ---------------------------------------------------------------------------


class SentimentSignal:
    """
    Fear/greed proxy derived from funding rates and open interest changes.

    Funding rate:
      - Positive (> 0.01%): longs pay shorts → excessive bullish positioning
      - Negative (< -0.01%): shorts pay longs → excessive bearish positioning
      - Contrarian signal: extreme funding = mean reversion setup

    Open interest:
      - Rising OI + rising price = trend confirmation (bullish)
      - Rising OI + falling price = trend confirmation (bearish)
      - Falling OI = position unwinding, reduced conviction
    """

    FUNDING_THRESHOLD = 0.0001  # 0.01% per 8h

    def compute(self, market_data: dict[str, Any]) -> SignalValue:
        funding_rates = market_data.get("funding_rates", [])  # list of floats (8h rate)
        open_interest = market_data.get("open_interest", [])  # list of OI values
        prices = market_data.get("close", [])

        raw: dict[str, float] = {}

        funding_signal = 0.0
        if funding_rates:
            latest_funding = funding_rates[-1]
            raw["funding_rate"] = latest_funding
            avg_funding = (
                statistics.mean(funding_rates[-8:]) if len(funding_rates) >= 8 else latest_funding
            )
            raw["avg_funding_8p"] = avg_funding

            # Contrarian: extreme positive funding = bearish signal
            if avg_funding > self.FUNDING_THRESHOLD * 3:
                funding_signal = -0.8  # crowd is too long, fade
                raw["funding_regime"] = 1.0  # extreme bull positioning
            elif avg_funding > self.FUNDING_THRESHOLD:
                funding_signal = -0.3  # mild fade
                raw["funding_regime"] = 0.5
            elif avg_funding < -self.FUNDING_THRESHOLD * 3:
                funding_signal = 0.8  # crowd is too short, fade short
                raw["funding_regime"] = -1.0  # extreme bear positioning
            elif avg_funding < -self.FUNDING_THRESHOLD:
                funding_signal = 0.3
                raw["funding_regime"] = -0.5
            else:
                raw["funding_regime"] = 0.0

        oi_signal = 0.0
        if open_interest and len(open_interest) > 1:
            oi_change = (open_interest[-1] - open_interest[-2]) / max(abs(open_interest[-2]), 1)
            raw["oi_change_pct"] = oi_change
            price_change = 0.0
            if len(prices) > 1 and prices[-2] != 0:
                price_change = (prices[-1] - prices[-2]) / prices[-2]
                raw["price_change_1p"] = price_change

            # OI + price direction alignment
            if oi_change > 0.02 and price_change > 0:
                oi_signal = 0.6  # confirmation of uptrend
            elif oi_change > 0.02 and price_change < 0:
                oi_signal = -0.6  # confirmation of downtrend
            elif oi_change < -0.02:
                oi_signal = 0.0  # unwinding — uncertain
                raw["oi_regime"] = -1.0

        # Combined signal
        has_funding = bool(funding_rates)
        has_oi = bool(open_interest and len(open_interest) > 1)

        if not has_funding and not has_oi:
            return SignalValue(value=0.0, confidence=0.0, regime_tag="no_data", raw=raw)

        weights = []
        signals = []
        if has_funding:
            signals.append(funding_signal)
            weights.append(0.6)
        if has_oi:
            signals.append(oi_signal)
            weights.append(0.4)

        total_w = sum(weights)
        value = sum(s * w for s, w in zip(signals, weights, strict=False)) / total_w

        # Confidence: higher when funding is extreme (clearer signal)
        funding_extremity = abs(raw.get("avg_funding_8p", 0)) / (self.FUNDING_THRESHOLD * 3)
        confidence = min(1.0, 0.4 + funding_extremity * 0.6)

        # Regime tag
        fr = raw.get("funding_regime", 0.0)
        if fr > 0.5:
            regime_tag = "extreme_greed"
        elif fr < -0.5:
            regime_tag = "extreme_fear"
        elif abs(fr) > 0:
            regime_tag = "mild_sentiment"
        else:
            regime_tag = "neutral_sentiment"

        return SignalValue(
            value=max(-1.0, min(1.0, value)),
            confidence=max(0.0, min(1.0, confidence)),
            regime_tag=regime_tag,
            raw=raw,
        )
