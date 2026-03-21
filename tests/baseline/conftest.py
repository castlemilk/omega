"""Shared fixtures for PICO vs Omega baseline tests — stdlib only."""

import math
import random
import statistics

import pytest

# ---------------------------------------------------------------------------
# Seeded RNG wrapper (stdlib random)
# ---------------------------------------------------------------------------


class SeededRNG:
    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    def normal(self, mu: float = 0.0, sigma: float = 1.0, n: int = 1) -> list[float]:
        return [self._rng.gauss(mu, sigma) for _ in range(n)]

    def uniform(self, lo: float, hi: float, n: int = 1) -> list[float]:
        return [self._rng.uniform(lo, hi) for _ in range(n)]

    def lognormal(self, mean: float = 0.0, sigma: float = 1.0, n: int = 1) -> list[float]:
        return [math.exp(self._rng.gauss(mean, sigma)) for _ in range(n)]


@pytest.fixture
def rng():
    return SeededRNG(seed=42)


# ---------------------------------------------------------------------------
# Synthetic price series
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_price_series(rng):
    """1000 bars of synthetic 1-minute OHLCV data (GBM, crypto-like vol)."""
    n = 1000
    dt = 1 / 1440
    mu = 0.0002
    sigma = 0.03

    log_returns = rng.normal(mu * dt, sigma * math.sqrt(dt), n)
    prices = []
    p = 50000.0
    for lr in log_returns:
        p *= math.exp(lr)
        prices.append(p)

    noise = rng.uniform(0.0002, 0.001, n)
    high = [prices[i] * (1 + noise[i]) for i in range(n)]
    low = [prices[i] * (1 - noise[i]) for i in range(n)]
    open_ = [prices[0], *prices[:-1]]
    volume = rng.lognormal(10, 1, n)

    return {
        "close": prices,
        "high": high,
        "low": low,
        "open": open_,
        "volume": volume,
        "n": n,
    }


@pytest.fixture
def synthetic_price_series_with_regime(rng):
    """1000 bars with a known regime change at bar 500.

    Regime 1 (0-499): low-vol trending bull.
    Regime 2 (500-999): high-vol crash/recovery.
    """
    n = 1000
    mid = n // 2
    dt = 1 / 1440

    log_ret_1 = rng.normal(0.0005 * dt, 0.01 * math.sqrt(dt), mid)
    prices_1: list[float] = []
    p = 50000.0
    for lr in log_ret_1:
        p *= math.exp(lr)
        prices_1.append(p)

    log_ret_2 = rng.normal(-0.001 * dt, 0.05 * math.sqrt(dt), n - mid)
    prices_2: list[float] = []
    p = prices_1[-1]
    for lr in log_ret_2:
        p *= math.exp(lr)
        prices_2.append(p)

    prices = prices_1 + prices_2
    returns = [0.0]
    for i in range(1, len(prices)):
        returns.append(math.log(prices[i] / prices[i - 1]))

    return {
        "prices": prices,
        "returns": returns,
        "regime_change_idx": mid,
        "n": n,
    }


@pytest.fixture
def synthetic_order_book(rng):
    """500 synthetic order book snapshots."""
    n = 500
    mid_price = 50000.0
    snapshots = []

    for _ in range(n):
        mid_price *= math.exp(rng.normal(0, 0.0002, 1)[0])
        spread_bps = rng.uniform(1, 5, 1)[0]
        half_spread = mid_price * spread_bps / 20000

        bid_prices = [mid_price - half_spread * (1 + k * 0.5) for k in range(5)]
        ask_prices = [mid_price + half_spread * (1 + k * 0.5) for k in range(5)]
        bid_sizes = rng.lognormal(2, 1, 5)
        ask_sizes = rng.lognormal(2, 1, 5)

        snapshots.append(
            {
                "mid": mid_price,
                "spread_bps": spread_bps,
                "bids": list(zip(bid_prices, bid_sizes, strict=False)),
                "asks": list(zip(ask_prices, ask_sizes, strict=False)),
            }
        )

    return snapshots


@pytest.fixture
def ensemble_predictions(rng):
    """Factory: generate ensemble predictions with controlled disagreement."""

    def _make(
        n_models: int = 5, n_samples: int = 200, disagreement_level: float = 0.0
    ) -> list[list[float]]:
        """Returns list of n_samples, each a list of n_models values in [-1, 1]."""
        base_signal = rng.uniform(-0.5, 0.5, n_samples)
        predictions = []
        for s in range(n_samples):
            row = []
            for _ in range(n_models):
                noise = rng.normal(0, disagreement_level, 1)[0] if disagreement_level > 0 else 0.0
                val = max(-1.0, min(1.0, base_signal[s] + noise))
                row.append(val)
            predictions.append(row)
        return predictions

    return _make


# ---------------------------------------------------------------------------
# Shared metric helpers (stdlib)
# ---------------------------------------------------------------------------


def sharpe_ratio(returns: list[float], periods_per_year: int = 525600) -> float:
    """Annualised Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    mean = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum drawdown as a positive fraction (0-1)."""
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def recovery_time(returns: list[float], regime_change_idx: int) -> int:
    """Bars after regime_change_idx until cumulative return turns positive."""
    post = returns[regime_change_idx:]
    cum = 0.0
    for i, r in enumerate(post):
        cum += r
        if cum > 0:
            return i
    return len(post)


def cumprod(returns: list[float]) -> list[float]:
    """Cumulative product of (1 + r) for each return."""
    result = []
    p = 1.0
    for r in returns:
        p *= 1 + r
        result.append(p)
    return result
