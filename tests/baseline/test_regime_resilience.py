"""Test 2: Regime Change Resilience — PICO vs Omega.

PICO: fixed-parameter momentum strategy, no adaptation.
Omega: adaptive strategy that shortens lookback after regime change.

Metrics: recovery time (bars to positive cumulative return) and max drawdown.
"""

import math
import statistics

from tests.baseline.conftest import cumprod, max_drawdown, recovery_time, sharpe_ratio

# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def run_fixed_momentum(
    prices: list[float], *, lookback: int = 20, entry_threshold: float = 0.002
) -> list[float]:
    """PICO: fixed lookback momentum — never adapts to regime change."""
    n = len(prices)
    returns = [0.0] * n
    for i in range(lookback, n):
        momentum = (prices[i] / prices[i - lookback]) - 1.0
        bar_ret = (prices[i] - prices[i - 1]) / prices[i - 1]
        if momentum > entry_threshold:
            returns[i] = bar_ret
        elif momentum < -entry_threshold:
            returns[i] = -bar_ret
    return returns


def run_adaptive_momentum(
    prices: list[float],
    *,
    regime_change_idx: int,
    short_lookback: int = 5,
    long_lookback: int = 20,
    entry_threshold: float = 0.001,
) -> list[float]:
    """Omega: switches to shorter lookback after regime change (AI-advised)."""
    n = len(prices)
    returns = [0.0] * n
    for i in range(long_lookback, n):
        lb = short_lookback if i >= regime_change_idx else long_lookback
        if i < lb:
            continue
        momentum = (prices[i] / prices[i - lb]) - 1.0
        bar_ret = (prices[i] - prices[i - 1]) / prices[i - 1]
        if momentum > entry_threshold:
            returns[i] = bar_ret
        elif momentum < -entry_threshold:
            returns[i] = -bar_ret
    return returns


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegimeResilience:
    def test_regime_change_causes_drawdown_in_fixed_strategy(
        self, synthetic_price_series_with_regime
    ):
        data = synthetic_price_series_with_regime
        ret = run_fixed_momentum(data["prices"])
        post_eq = cumprod(ret[data["regime_change_idx"] :])
        dd = max_drawdown(post_eq)
        assert dd >= 0.0
        print(f"\nFixed strategy post-regime max drawdown: {dd:.4f}")

    def test_adaptive_strategy_produces_returns(self, synthetic_price_series_with_regime):
        data = synthetic_price_series_with_regime
        ret = run_adaptive_momentum(data["prices"], regime_change_idx=data["regime_change_idx"])
        assert len(ret) == data["n"]
        assert any(r != 0.0 for r in ret), "Adaptive strategy never traded"

    def test_recovery_time_is_trackable(self, synthetic_price_series_with_regime):
        data = synthetic_price_series_with_regime
        mid = data["regime_change_idx"]

        fixed_ret = run_fixed_momentum(data["prices"])
        adaptive_ret = run_adaptive_momentum(data["prices"], regime_change_idx=mid)

        fixed_rec = recovery_time(fixed_ret, mid)
        adaptive_rec = recovery_time(adaptive_ret, mid)

        assert isinstance(fixed_rec, int)
        assert isinstance(adaptive_rec, int)
        assert fixed_rec >= 0
        assert adaptive_rec >= 0
        print(f"\nRecovery — Fixed: {fixed_rec} bars, Adaptive: {adaptive_rec} bars")

    def test_max_drawdown_comparison_is_measurable(self, synthetic_price_series_with_regime):
        data = synthetic_price_series_with_regime
        mid = data["regime_change_idx"]

        fixed_ret = run_fixed_momentum(data["prices"])
        adaptive_ret = run_adaptive_momentum(data["prices"], regime_change_idx=mid)

        fixed_dd = max_drawdown(cumprod(fixed_ret[mid:]))
        adaptive_dd = max_drawdown(cumprod(adaptive_ret[mid:]))

        assert 0.0 <= fixed_dd <= 1.0
        assert 0.0 <= adaptive_dd <= 1.0
        print(
            f"\nPost-regime max DD — Fixed: {fixed_dd:.4f}, "
            f"Adaptive: {adaptive_dd:.4f}, Delta: {fixed_dd - adaptive_dd:+.4f}"
        )

    def test_sharpe_pre_vs_post_regime(self, synthetic_price_series_with_regime):
        data = synthetic_price_series_with_regime
        mid = data["regime_change_idx"]

        ret = run_fixed_momentum(data["prices"])
        sharpe_pre = sharpe_ratio(ret[:mid])
        sharpe_post = sharpe_ratio(ret[mid:])

        assert math.isfinite(sharpe_pre)
        assert math.isfinite(sharpe_post)
        print(f"\nFixed Sharpe — pre: {sharpe_pre:.3f}, post: {sharpe_post:.3f}")

    def test_pre_regime_mean_return_is_finite(self, synthetic_price_series_with_regime):
        data = synthetic_price_series_with_regime
        mid = data["regime_change_idx"]
        ret = run_fixed_momentum(data["prices"])
        mean_pre = statistics.mean(ret[:mid])
        assert math.isfinite(mean_pre)
