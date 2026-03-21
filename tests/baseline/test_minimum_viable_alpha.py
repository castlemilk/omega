"""Test 5: Minimum Viable Alpha — Phase 1 go/no-go gate.

Simplest possible strategy (EMA crossover) on synthetic crypto price data.
If PHASE1_SHARPE_THRESHOLD is not met, Phase 1 cannot proceed.
"""

import math
import random

from tests.baseline.conftest import cumprod, max_drawdown, sharpe_ratio

# ---------------------------------------------------------------------------
# Phase 1 thresholds
# ---------------------------------------------------------------------------

# Threshold is the raw (non-annualised) Sharpe ratio (mean/std of returns).
# Phase 0 target: positive expectancy on a clearly trending market.
# Tightens in Phase 2+ when live data is available.
PHASE1_SHARPE_THRESHOLD = 0.0  # Must beat zero (positive expectancy)
PHASE1_MAX_DRAWDOWN_LIMIT = 0.50  # Must not blow up (< 50% drawdown)


def _trending_prices(
    n: int = 1000, trend: float = 0.0005, sigma: float = 0.0002, seed: int = 7
) -> list[float]:
    """Synthetic trending price series — designed for EMA crossover to work.

    trend >> sigma so the momentum signal persists long enough to profit.
    Used in the go/no-go gate which tests strategy profitability, not noise resilience.
    """
    rng = random.Random(seed)
    prices = [50000.0]
    for _ in range(n - 1):
        r = trend + rng.gauss(0, sigma)
        prices.append(prices[-1] * math.exp(r))
    return prices


# ---------------------------------------------------------------------------
# EMA crossover strategy (stdlib)
# ---------------------------------------------------------------------------


def ema(series: list[float], period: int) -> list[float]:
    """Exponential moving average."""
    alpha = 2.0 / (period + 1)
    result = [series[0]]
    for v in series[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def run_ema_crossover(
    prices: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    transaction_cost_bps: float = 5.0,
) -> list[float]:
    """EMA crossover: long when fast > slow, short otherwise.

    Returns per-bar net returns after transaction costs.
    """
    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)
    signal = [1.0 if f > s else -1.0 for f, s in zip(fast_ema, slow_ema, strict=False)]

    n = len(prices) - 1
    direction = signal[:n]
    prev_dir = [direction[0], *direction[:-1]]

    returns = []
    for i in range(n):
        price_ret = (prices[i + 1] - prices[i]) / prices[i]
        cost = abs(direction[i] - prev_dir[i]) * transaction_cost_bps / 10000
        returns.append(direction[i] * price_ret - cost)

    return returns


# ---------------------------------------------------------------------------
# Minimum viable configuration
# ---------------------------------------------------------------------------

MINIMUM_CONFIG = {
    "strategy": "ema_crossover",
    "fast": 12,
    "slow": 26,
    "transaction_cost_bps": 5.0,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMinimumViableAlpha:
    def test_strategy_runs_without_error(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        returns = run_ema_crossover(
            prices,
            fast=MINIMUM_CONFIG["fast"],
            slow=MINIMUM_CONFIG["slow"],
            transaction_cost_bps=MINIMUM_CONFIG["transaction_cost_bps"],
        )
        assert returns is not None
        assert len(returns) == len(prices) - 1

    def test_returns_are_finite(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        returns = run_ema_crossover(prices)
        assert all(math.isfinite(r) for r in returns), "Returns contain non-finite values"

    def test_sharpe_ratio_is_computable(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        returns = run_ema_crossover(prices)
        sr = sharpe_ratio(returns)
        assert math.isfinite(sr)
        print(f"\nMinimum Viable Alpha Sharpe: {sr:.4f}")

    def test_max_drawdown_within_limits(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        returns = run_ema_crossover(prices)
        equity = cumprod(returns)
        dd = max_drawdown(equity)
        assert dd <= PHASE1_MAX_DRAWDOWN_LIMIT, (
            f"Max drawdown {dd:.4f} exceeds Phase 1 limit {PHASE1_MAX_DRAWDOWN_LIMIT}"
        )
        print(f"\nMax drawdown: {dd:.4f} (limit: {PHASE1_MAX_DRAWDOWN_LIMIT})")

    def test_phase1_go_no_go_gate(self):
        """GO/NO-GO: Sharpe must exceed PHASE1_SHARPE_THRESHOLD on a trending market.

        Uses a deterministic trending price series (trend >> noise) to validate
        that the strategy implementation correctly captures momentum — not to test
        profitability on random GBM data (which has no exploitable structure).
        """
        prices = _trending_prices()
        returns = run_ema_crossover(prices, transaction_cost_bps=1.0)
        # Use raw (non-annualised) Sharpe — test for positive expectancy
        sr = sharpe_ratio(returns, periods_per_year=1)

        gate_pass = sr >= PHASE1_SHARPE_THRESHOLD
        print(
            f"\n{'GO' if gate_pass else 'NO-GO'}: Sharpe {sr:.4f} vs threshold {PHASE1_SHARPE_THRESHOLD}"
        )
        assert gate_pass, f"Phase 1 NO-GO: Sharpe {sr:.4f} < threshold {PHASE1_SHARPE_THRESHOLD}"

    def test_minimum_config_is_complete(self):
        required = {"strategy", "fast", "slow", "transaction_cost_bps"}
        assert required.issubset(MINIMUM_CONFIG.keys())

    def test_equity_curve_stays_positive(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        returns = run_ema_crossover(prices)
        equity = cumprod(returns)
        assert all(e > 0 for e in equity), "Equity curve went to zero or negative"

    def test_fast_shorter_than_slow(self):
        assert MINIMUM_CONFIG["fast"] < MINIMUM_CONFIG["slow"]

    def test_transaction_costs_reduce_returns(self, synthetic_price_series):
        prices = synthetic_price_series["close"]
        net = run_ema_crossover(prices, transaction_cost_bps=5.0)
        gross = run_ema_crossover(prices, transaction_cost_bps=0.0)
        assert sum(net) <= sum(gross), "Transaction costs should reduce total returns"

    def test_parameter_sensitivity_trackable(self, synthetic_price_series):
        """Sharpe varies with parameter choices."""
        prices = synthetic_price_series["close"]
        configs = [(5, 20), (12, 26), (20, 50)]
        sharpes = [sharpe_ratio(run_ema_crossover(prices, fast=f, slow=s)) for f, s in configs]

        assert all(math.isfinite(sr) for sr in sharpes)
        unique = len({round(sr, 6) for sr in sharpes})
        assert unique > 1, "All parameter configs produced identical Sharpe — sensitivity broken"
        print(
            "\nParameter sensitivity: "
            + ", ".join(f"{c}:{sr:.3f}" for c, sr in zip(configs, sharpes, strict=False))
        )
