"""V173 VWAP-deviation signal.

Computes (price - VWAP) / VWAP from a price/volume window. Positive = price
above VWAP (momentum), negative = below (mean-reversion candidate).

Output normalized to [-1, +1] by clipping at ±2% deviation (typical intraday
range for crypto perps; saturate beyond).
"""

from __future__ import annotations


def compute_vwap_deviation(prices: list[float], volumes: list[float], window: int = 60) -> float:
    """Pure function: compute (latest - vwap) / vwap clipped to [-1, +1].

    >>> compute_vwap_deviation([100]*60, [1000]*60)
    0.0
    >>> v = compute_vwap_deviation([100]*59 + [102], [1000]*60)
    >>> 0.9 <= v <= 1.0
    True
    """
    if not prices or not volumes:
        return 0.0
    n = min(len(prices), len(volumes), window)
    if n < 2:
        return 0.0
    p = prices[-n:]
    v = volumes[-n:]
    sum_pv = 0.0
    sum_v = 0.0
    for pi, vi in zip(p, v):
        try:
            pf = float(pi)
            vf = float(vi)
        except (TypeError, ValueError):
            continue
        if vf <= 0 or pf <= 0:
            continue
        sum_pv += pf * vf
        sum_v += vf
    if sum_v <= 0:
        return 0.0
    vwap = sum_pv / sum_v
    if vwap <= 0:
        return 0.0
    try:
        latest = float(p[-1])
    except (TypeError, ValueError):
        return 0.0
    dev = (latest - vwap) / vwap
    # Clip at ±2%; map dev=±0.02 → ±1.0
    scaled = dev / 0.02
    return max(-1.0, min(1.0, scaled))


def _self_test() -> None:
    assert compute_vwap_deviation([], []) == 0.0
    assert compute_vwap_deviation([100] * 60, [1000] * 60) == 0.0
    v = compute_vwap_deviation([100] * 59 + [102], [1000] * 60)
    assert 0.5 <= v <= 1.0, f"got {v}"
    v2 = compute_vwap_deviation([100] * 59 + [98], [1000] * 60)
    assert -1.0 <= v2 <= -0.5
    print("vwap_deviation: OK")


if __name__ == "__main__":
    _self_test()
