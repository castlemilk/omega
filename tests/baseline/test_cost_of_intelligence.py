"""Test 3: Cost of Intelligence — LLM API cost vs Sharpe improvement.

Models the economics of AI-augmented trading:
  - LLM API cost per improvement cycle
  - Sharpe improvement per dollar of LLM spend
  - Break-even threshold

Tests the cost tracking infrastructure — no live API calls.
"""

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


@dataclass
class LLMCostModel:
    """Tracks LLM usage costs across improvement cycles."""

    # Pricing in USD per 1M tokens (Claude Sonnet 4.6)
    input_price_per_mtok: float = 3.0
    output_price_per_mtok: float = 15.0

    cycles: list[dict] = field(default_factory=list)

    def record_cycle(
        self,
        input_tokens: int,
        output_tokens: int,
        sharpe_before: float,
        sharpe_after: float,
    ) -> dict:
        input_cost = input_tokens / 1_000_000 * self.input_price_per_mtok
        output_cost = output_tokens / 1_000_000 * self.output_price_per_mtok
        total_cost = input_cost + output_cost
        sharpe_delta = sharpe_after - sharpe_before

        entry = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": total_cost,
            "sharpe_before": sharpe_before,
            "sharpe_after": sharpe_after,
            "sharpe_delta": sharpe_delta,
            "sharpe_per_dollar": sharpe_delta / total_cost if total_cost > 0 else 0.0,
        }
        self.cycles.append(entry)
        return entry

    def total_cost(self) -> float:
        return float(sum(c["cost_usd"] for c in self.cycles))

    def cumulative_sharpe_improvement(self) -> float:
        return float(sum(c["sharpe_delta"] for c in self.cycles))

    def average_sharpe_per_dollar(self) -> float:
        total = self.total_cost()
        if total == 0:
            return 0.0
        return self.cumulative_sharpe_improvement() / total


# ---------------------------------------------------------------------------
# Break-even analysis
# ---------------------------------------------------------------------------


def compute_break_even_sharpe_improvement(
    cost_usd: float,
    annual_capital_usd: float = 10_000.0,
) -> float:
    """Minimum Sharpe improvement to justify the cost.

    Model: 1 Sharpe unit ≈ 1% annual excess return.
    """
    incremental_return_per_sharpe_unit = annual_capital_usd * 0.01
    return cost_usd / incremental_return_per_sharpe_unit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCostOfIntelligence:
    def test_cost_model_records_cycle(self):
        model = LLMCostModel()
        entry = model.record_cycle(2000, 500, 0.5, 0.8)
        assert entry["cost_usd"] > 0
        assert abs(entry["sharpe_delta"] - 0.3) < 1e-9
        assert entry["sharpe_per_dollar"] > 0

    def test_cost_scales_with_tokens(self):
        m1 = LLMCostModel()
        m2 = LLMCostModel()
        small = m1.record_cycle(1000, 100, 0.0, 0.1)
        large = m2.record_cycle(10000, 1000, 0.0, 0.1)
        assert large["cost_usd"] > small["cost_usd"]

    def test_total_cost_accumulates(self):
        model = LLMCostModel()
        model.record_cycle(2000, 500, 0.4, 0.6)
        model.record_cycle(3000, 800, 0.6, 0.75)
        expected = sum(c["cost_usd"] for c in model.cycles)
        assert abs(model.total_cost() - expected) < 1e-12
        assert len(model.cycles) == 2

    def test_cumulative_sharpe_improvement(self):
        model = LLMCostModel()
        model.record_cycle(2000, 500, 0.4, 0.6)  # +0.2
        model.record_cycle(3000, 800, 0.6, 0.65)  # +0.05
        assert abs(model.cumulative_sharpe_improvement() - 0.25) < 1e-9

    def test_break_even_threshold_computable(self):
        threshold = compute_break_even_sharpe_improvement(0.01, annual_capital_usd=10_000.0)
        assert threshold > 0
        assert math.isfinite(threshold)
        print(f"\nBreak-even Sharpe improvement for $0.01 spend: {threshold:.6f}")

    def test_roi_positive_when_improvement_exceeds_threshold(self):
        cost = 0.01
        sharpe_improvement = 0.1
        threshold = compute_break_even_sharpe_improvement(cost, annual_capital_usd=10_000.0)
        assert sharpe_improvement > threshold, (
            f"Expected positive ROI: improvement {sharpe_improvement:.4f} > threshold {threshold:.6f}"
        )

    def test_multiple_cycles_average_sharpe_per_dollar(self):
        model = LLMCostModel()
        for inp, out, sb, sa in [
            (2000, 400, 0.2, 0.35),
            (1500, 350, 0.35, 0.45),
            (2500, 600, 0.45, 0.50),
            (1800, 400, 0.50, 0.52),
            (3000, 700, 0.52, 0.53),
        ]:
            model.record_cycle(inp, out, sb, sa)

        avg = model.average_sharpe_per_dollar()
        assert math.isfinite(avg)
        print(
            f"\n5-cycle summary — Total cost: ${model.total_cost():.4f}, "
            f"Total Sharpe: {model.cumulative_sharpe_improvement():.3f}, "
            f"Avg Sharpe/$: {avg:.3f}"
        )

    def test_negative_cycle_tracked_correctly(self):
        """A cycle where AI advice worsened things is recorded with negative delta."""
        model = LLMCostModel()
        entry = model.record_cycle(2000, 500, 0.8, 0.6)
        assert entry["sharpe_delta"] < 0
        assert entry["sharpe_per_dollar"] < 0
        assert entry["cost_usd"] > 0

    def test_cost_per_cycle_in_expected_range(self):
        """Typical call (4k input, 1k output) costs <$0.10."""
        model = LLMCostModel()
        entry = model.record_cycle(4000, 1000, 0.5, 0.65)
        assert entry["cost_usd"] < 0.10
        assert entry["cost_usd"] > 0.0
        print(f"\nTypical cycle cost: ${entry['cost_usd']:.5f}")
