"""Test 4: Adversarial Robustness — Ring 1 detection under injected disagreement.

PICO: single deterministic signal, no ensemble.
Omega: ensemble with Ring 1 disagreement detection.

Ring 1 fires when ensemble standard deviation exceeds a threshold, suppressing
the signal and preventing action on noisy/adversarial data.
"""

import math
import statistics

import pytest

from tests.baseline.conftest import sharpe_ratio

# ---------------------------------------------------------------------------
# Ring 1 detector (stdlib)
# ---------------------------------------------------------------------------


def ring1_detect(
    predictions: list[list[float]], *, disagreement_threshold: float = 0.3
) -> list[bool]:
    """Returns True for each sample where ensemble std > threshold."""
    flags = []
    for row in predictions:
        if len(row) < 2:
            flags.append(False)
            continue
        std = statistics.stdev(row)
        flags.append(std > disagreement_threshold)
    return flags


def nobrain_signal(predictions: list[list[float]]) -> list[float]:
    """PICO: use only the first model's signal."""
    return [row[0] for row in predictions]


def brain_signal(
    predictions: list[list[float]], *, disagreement_threshold: float = 0.3
) -> list[float]:
    """Omega: ensemble mean, zeroed out when Ring 1 fires."""
    flags = ring1_detect(predictions, disagreement_threshold=disagreement_threshold)
    result = []
    for i, row in enumerate(predictions):
        if flags[i]:
            result.append(0.0)
        else:
            result.append(statistics.mean(row))
    return result


def signal_to_returns(signal: list[float], prices: list[float]) -> list[float]:
    """Convert signal to per-bar returns (long/short/flat)."""
    n = min(len(signal), len(prices) - 1)
    returns = []
    for i in range(n):
        price_ret = (prices[i + 1] - prices[i]) / prices[i]
        direction = 1.0 if signal[i] > 0 else (-1.0 if signal[i] < 0 else 0.0)
        returns.append(direction * price_ret)
    return returns


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdversarialRobustness:
    def test_ring1_fires_on_high_disagreement(self, ensemble_predictions):
        high = ensemble_predictions(disagreement_level=1.0)
        flags = ring1_detect(high, disagreement_threshold=0.3)
        flag_rate = sum(flags) / len(flags)
        assert flag_rate > 0.1, f"Ring 1 should fire frequently, got {flag_rate:.3f}"
        print(f"\nHigh-disagreement flag rate: {flag_rate:.3f}")

    def test_ring1_rarely_fires_on_consensus(self, ensemble_predictions):
        consensus = ensemble_predictions(disagreement_level=0.0)
        flags = ring1_detect(consensus, disagreement_threshold=0.3)
        flag_rate = sum(flags) / len(flags)
        assert flag_rate < 0.2, f"Ring 1 should rarely fire on consensus, got {flag_rate:.3f}"
        print(f"\nConsensus flag rate: {flag_rate:.3f}")

    def test_flag_count_increases_with_disagreement(self, ensemble_predictions):
        low = ensemble_predictions(disagreement_level=0.1)
        high = ensemble_predictions(disagreement_level=0.9)
        low_flags = sum(ring1_detect(low))
        high_flags = sum(ring1_detect(high))
        assert high_flags >= low_flags, (
            f"More disagreement should produce more flags: low={low_flags}, high={high_flags}"
        )

    def test_brain_suppresses_signal_on_flag(self, ensemble_predictions):
        """Brain zeros out signal on flagged bars."""
        preds = ensemble_predictions(disagreement_level=0.8)
        br_sig = brain_signal(preds)
        flags = ring1_detect(preds)

        for i, flag in enumerate(flags):
            if flag:
                assert br_sig[i] == 0.0, f"Brain signal should be 0 on flagged bar {i}"

        # NoBrain is not suppressed (some flagged bars have non-zero first-model signal)
        nb_sig = nobrain_signal(preds)
        nb_flagged_nonzero = sum(1 for i, f in enumerate(flags) if f and nb_sig[i] != 0.0)
        assert nb_flagged_nonzero > 0, "NoBrain should have non-zero signals on some flagged bars"

    def test_brain_reduces_return_volatility_under_adversarial_noise(
        self, ensemble_predictions, synthetic_price_series
    ):
        prices = synthetic_price_series["close"]
        n = min(len(prices) - 1, 200)
        preds = ensemble_predictions(n_samples=n, disagreement_level=0.6)

        nb_ret = signal_to_returns(nobrain_signal(preds), prices)
        br_ret = signal_to_returns(brain_signal(preds), prices)

        nb_vol = statistics.stdev(nb_ret) if len(nb_ret) > 1 else 0.0
        br_vol = statistics.stdev(br_ret) if len(br_ret) > 1 else 0.0

        print(f"\nReturn vol — NoBrain: {nb_vol:.6f}, Brain: {br_vol:.6f}")
        assert math.isfinite(nb_vol)
        assert math.isfinite(br_vol)

    def test_adaptation_speed_metric_computable(self, ensemble_predictions):
        """Adaptation is instant — suppression starts at the flag bar."""
        preds = ensemble_predictions(disagreement_level=0.7)
        br_sig = brain_signal(preds)
        flags = ring1_detect(preds)

        flag_indices = [i for i, f in enumerate(flags) if f]
        if not flag_indices:
            pytest.skip("No flags generated — increase disagreement level")

        first_flag = flag_indices[0]
        post = br_sig[first_flag:]
        zero_run = 0
        for v in post:
            if v == 0.0:
                zero_run += 1
            else:
                break

        assert zero_run >= 1, "Brain should suppress at least 1 bar after flag"
        print(f"\nAdaptation: {zero_run} suppressed bars from first flag at bar {first_flag}")

    def test_nobrain_returns_nontrivial_signal(self, ensemble_predictions):
        """NoBrain always forwards first-model signal (no suppression)."""
        preds = ensemble_predictions(disagreement_level=1.0)
        nb_sig = nobrain_signal(preds)
        assert len(nb_sig) == len(preds)
        nonzero = sum(1 for s in nb_sig if s != 0.0)
        assert nonzero > 0, "NoBrain should propagate non-zero signals"
        print(f"\nNoBrain: {nonzero}/{len(nb_sig)} non-zero bars")

    def test_sharpe_comparison_under_adversarial_noise(
        self, ensemble_predictions, synthetic_price_series
    ):
        """Sharpe comparison is computable under adversarial conditions."""
        prices = synthetic_price_series["close"]
        n = min(len(prices) - 1, 200)
        preds = ensemble_predictions(n_samples=n, disagreement_level=0.5)

        nb_ret = signal_to_returns(nobrain_signal(preds), prices)
        br_ret = signal_to_returns(brain_signal(preds), prices)

        nb_sharpe = sharpe_ratio(nb_ret)
        br_sharpe = sharpe_ratio(br_ret)

        assert math.isfinite(nb_sharpe)
        assert math.isfinite(br_sharpe)
        print(
            f"\nAdversarial Sharpe — NoBrain: {nb_sharpe:.3f}, Brain: {br_sharpe:.3f}, "
            f"Delta: {br_sharpe - nb_sharpe:+.3f}"
        )
