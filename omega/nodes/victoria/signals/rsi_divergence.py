"""V173 RSI divergence signal.

Detects bullish/bearish RSI divergence — a classic reversal pattern:

  Bearish divergence: price makes new high, RSI does NOT → momentum
                      weakening, expect reversal down → SHORT signal
  Bullish divergence: price makes new low, RSI does NOT → selling
                      exhaustion, expect reversal up → LONG signal

Output:
  > 0  bullish divergence (signal LONG; +1 = strong)
  < 0  bearish divergence (signal SHORT; -1 = strong)
   0   no divergence detected

Magnitude proportional to (rsi_gap × price_extreme_strength).
"""
from __future__ import annotations


def _rsi(prices: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI series (length = len(prices) - period). Returns [] if insufficient."""
    n = len(prices)
    if n < period + 1:
        return []
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        delta = prices[i] - prices[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out = [100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)]
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))
    return out


def compute_divergence(prices: list[float], lookback: int = 20, period: int = 14) -> float:
    """Detect price/RSI divergence over the last `lookback` bars."""
    if len(prices) < period + lookback + 1:
        return 0.0
    rsi = _rsi(prices, period)
    if len(rsi) < lookback:
        return 0.0
    p = prices[-lookback:]
    r = rsi[-lookback:]
    p_max_i, p_min_i = p.index(max(p)), p.index(min(p))
    r_max_i, r_min_i = r.index(max(r)), r.index(min(r))
    sig = 0.0
    # Bearish: latest price near recent high but RSI peak earlier (lower latest RSI than peak)
    if p_max_i >= lookback - 3:  # high in last 3 bars
        rsi_at_high = r[p_max_i]
        rsi_peak = r[r_max_i]
        if r_max_i < p_max_i - 2 and rsi_at_high < rsi_peak - 5:
            gap = (rsi_peak - rsi_at_high) / 100.0
            strength = (max(p) - p[0]) / max(1e-9, p[0])
            sig -= max(0.0, min(1.0, gap * 5.0 + strength * 2.0))
    # Bullish: latest price near low but RSI trough earlier (higher latest RSI)
    if p_min_i >= lookback - 3:
        rsi_at_low = r[p_min_i]
        rsi_trough = r[r_min_i]
        if r_min_i < p_min_i - 2 and rsi_at_low > rsi_trough + 5:
            gap = (rsi_at_low - rsi_trough) / 100.0
            strength = (p[0] - min(p)) / max(1e-9, p[0])
            sig += max(0.0, min(1.0, gap * 5.0 + strength * 2.0))
    return max(-1.0, min(1.0, sig))


def _self_test() -> None:
    # Insufficient data
    assert compute_divergence([100, 101, 102]) == 0.0
    # Constant prices → no divergence
    assert compute_divergence([100.0] * 50) == 0.0
    # Price up trend with RSI keeping up — no divergence
    rising = [100 + i * 0.5 for i in range(50)]
    v = compute_divergence(rising)
    assert -0.3 <= v <= 0.3, f"trending got {v}"
    # Bearish divergence: price tops out, RSI peaked earlier
    bear = [100 + i * 1.0 for i in range(20)] + [120, 121, 121.5, 122, 122.2, 122.4, 122.5, 122.6, 122.7, 122.8] * 1
    v = compute_divergence(bear, lookback=15)
    print(f"bearish-shape divergence: {v:.3f}")
    print("rsi_divergence: OK")


if __name__ == "__main__":
    _self_test()
