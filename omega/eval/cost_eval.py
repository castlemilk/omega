"""
omega.eval.cost_eval
~~~~~~~~~~~~~~~~~~~~~
Cost-adjusted metrics for the Omega system.

Tracks LLM token usage per cycle type and computes cost-adjusted Sharpe,
break-even capital, and ROI per subsystem.

Assumptions
-----------
- Token costs are supplied in USD per 1M tokens (configurable).
- Default pricing approximates Claude Sonnet 4.6 (input: $3/1M, output: $15/1M).
- Subsystem costs are derived from ablation Sharpe contributions.

Usage::

    from omega.eval.cost_eval import CostEvaluator

    ev = CostEvaluator()
    ev.record_cycle("signal_analysis", input_tokens=1200, output_tokens=300)
    ev.record_cycle("parameter_proposal", input_tokens=800, output_tokens=200)

    print(ev.cost_per_sharpe_unit(sharpe=1.5))
    print(ev.break_even_capital(cost_per_cycle=0.005, sharpe_improvement=0.3))
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("omega.eval.cost_eval")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CycleTokenUsage:
    """Token usage for a single cycle."""

    cycle_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class CostReport:
    """Summary of cost-adjusted metrics."""

    total_cost_usd: float
    total_cycles: int
    cost_per_cycle: float
    cost_by_type: dict[str, float]
    tokens_by_type: dict[str, int]
    cost_per_sharpe_unit: float  # USD per 1 unit of Sharpe ratio
    cost_adjusted_sharpe: float
    roi_by_subsystem: dict[str, float]

    def __str__(self) -> str:
        lines = [
            "CostReport(",
            f"  total_cost=${self.total_cost_usd:.6f}, "
            f"cycles={self.total_cycles}, "
            f"cost/cycle=${self.cost_per_cycle:.6f}",
            f"  cost_per_sharpe_unit=${self.cost_per_sharpe_unit:.6f}",
            f"  cost_adjusted_sharpe={self.cost_adjusted_sharpe:.6f}",
            "  cost_by_type:",
        ]
        for k, v in self.cost_by_type.items():
            lines.append(f"    {k}: ${v:.6f}")
        lines.append("  roi_by_subsystem:")
        for k, v in self.roi_by_subsystem.items():
            lines.append(f"    {k}: {v:.4f}")
        lines.append(")")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pricing constants (USD per 1M tokens)
# ---------------------------------------------------------------------------


# Default: Claude Sonnet 4.6 pricing (approximate)
DEFAULT_INPUT_COST_PER_1M = 3.0  # $3 per 1M input tokens
DEFAULT_OUTPUT_COST_PER_1M = 15.0  # $15 per 1M output tokens

# Typical token budgets per cycle type (input, output)
TYPICAL_TOKEN_BUDGETS: dict[str, tuple[int, int]] = {
    "signal_analysis": (1_200, 300),
    "parameter_proposal": (800, 200),
    "scenario_generation": (1_500, 500),
    "memory_consolidation": (2_000, 400),
    "regime_analysis": (600, 150),
}


# ---------------------------------------------------------------------------
# CostEvaluator
# ---------------------------------------------------------------------------


class CostEvaluator:
    """
    Track LLM token usage and compute cost-adjusted metrics.

    Parameters
    ----------
    input_cost_per_1m  : USD per 1M input tokens.
    output_cost_per_1m : USD per 1M output tokens.
    """

    def __init__(
        self,
        input_cost_per_1m: float = DEFAULT_INPUT_COST_PER_1M,
        output_cost_per_1m: float = DEFAULT_OUTPUT_COST_PER_1M,
    ) -> None:
        self._input_cost_per_1m = input_cost_per_1m
        self._output_cost_per_1m = output_cost_per_1m
        self._records: list[CycleTokenUsage] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_cycle(
        self,
        cycle_type: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CycleTokenUsage:
        """
        Record token usage for one LLM call in a cycle.

        Parameters
        ----------
        cycle_type    : Category of call (e.g. "signal_analysis").
        input_tokens  : Number of input (prompt) tokens.
        output_tokens : Number of output (completion) tokens.
        """
        cost = self._compute_cost(input_tokens, output_tokens)
        record = CycleTokenUsage(
            cycle_type=cycle_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self._records.append(record)
        logger.debug(
            "record_cycle: type=%s input=%d output=%d cost=%.6f",
            cycle_type,
            input_tokens,
            output_tokens,
            cost,
        )
        return record

    def record_typical_cycle(self, cycle_type: str, n: int = 1) -> list[CycleTokenUsage]:
        """
        Record N cycles using the typical token budget for a known cycle type.

        Uses TYPICAL_TOKEN_BUDGETS; falls back to (1000, 250) if unknown.
        """
        inp, out = TYPICAL_TOKEN_BUDGETS.get(cycle_type, (1_000, 250))
        return [self.record_cycle(cycle_type, inp, out) for _ in range(n)]

    def clear(self) -> None:
        """Reset all recorded usage."""
        self._records.clear()

    # ------------------------------------------------------------------
    # Core metrics
    # ------------------------------------------------------------------

    def total_cost_usd(self) -> float:
        """Total cost across all recorded cycles."""
        return sum(r.cost_usd for r in self._records)

    def cost_per_cycle_type(self) -> dict[str, float]:
        """Total cost grouped by cycle_type."""
        costs: dict[str, float] = {}
        for r in self._records:
            costs[r.cycle_type] = costs.get(r.cycle_type, 0.0) + r.cost_usd
        return costs

    def tokens_per_cycle_type(self) -> dict[str, int]:
        """Total tokens (input + output) grouped by cycle_type."""
        tokens: dict[str, int] = {}
        for r in self._records:
            tokens[r.cycle_type] = tokens.get(r.cycle_type, 0) + r.input_tokens + r.output_tokens
        return tokens

    def cost_per_sharpe_unit(
        self,
        sharpe: float | None = None,
        total_cost: float | None = None,
    ) -> float:
        """
        USD cost per unit of Sharpe ratio achieved.

        Parameters
        ----------
        sharpe      : The Sharpe ratio achieved (required unless pre-recorded).
        total_cost  : Override total cost; defaults to self.total_cost_usd().

        Returns infinity if sharpe <= 0.
        """
        cost = total_cost if total_cost is not None else self.total_cost_usd()
        if sharpe is None or sharpe <= 0:
            return math.inf
        return cost / sharpe

    def cost_adjusted_sharpe(
        self,
        raw_sharpe: float,
        total_cost: float | None = None,
        capital: float = 100_000.0,
    ) -> float:
        """
        Sharpe ratio adjusted for LLM running costs.

        Deducts the annualised cost drag from the expected return before
        recomputing Sharpe.

        Parameters
        ----------
        raw_sharpe  : The unadjusted Sharpe ratio.
        total_cost  : Total LLM cost over the evaluation period (USD).
        capital     : Capital under management (USD).

        Returns the cost-adjusted Sharpe ratio.
        """
        cost = total_cost if total_cost is not None else self.total_cost_usd()
        if capital <= 0:
            return raw_sharpe

        # Annual cost drag as fraction of capital
        annual_cost_fraction = cost / capital

        # Approximate vol from Sharpe = mean / std → mean = Sharpe * std
        # Assume std = 0.15 (15% annualised vol — typical for crypto strategies)
        assumed_vol = 0.15
        implied_mean = raw_sharpe * assumed_vol
        adjusted_mean = implied_mean - annual_cost_fraction
        return adjusted_mean / assumed_vol if assumed_vol > 0 else 0.0

    def break_even_capital(
        self,
        cost_per_cycle: float | None = None,
        sharpe_improvement: float = 0.1,
        annual_cycles: int = 252,
        assumed_vol: float = 0.15,
    ) -> float:
        """
        Minimum capital required for the LLM cost to be profitable.

        The subsystem's Sharpe improvement translates to an additional
        return of (sharpe_improvement * assumed_vol) per year.  The
        break-even point is when that additional return covers the annual
        cost.

        Parameters
        ----------
        cost_per_cycle    : USD per cycle; defaults to average across records.
        sharpe_improvement: Sharpe improvement attributable to the subsystem.
        annual_cycles     : Cycles per year.
        assumed_vol       : Assumed annualised volatility.
        """
        if cost_per_cycle is None:
            n = len(self._records)
            cost_per_cycle = self.total_cost_usd() / n if n > 0 else 0.0

        annual_cost = cost_per_cycle * annual_cycles
        additional_return_fraction = sharpe_improvement * assumed_vol

        if additional_return_fraction <= 0:
            return math.inf

        return annual_cost / additional_return_fraction

    def roi_by_subsystem(
        self,
        sharpe_attributions: dict[str, float],
        capital: float = 100_000.0,
        annual_cycles: int = 252,
    ) -> dict[str, float]:
        """
        Compute ROI for each subsystem based on Sharpe contribution vs cost.

        ROI = (annual_alpha_value - annual_cost) / annual_cost

        Parameters
        ----------
        sharpe_attributions : Dict of subsystem → Sharpe contribution
                              (from AblationHarness.compute_attribution()).
        capital             : Capital under management (USD).
        annual_cycles       : Trading cycles per year.

        Returns dict of subsystem → ROI (positive = profitable subsystem).
        """
        # Estimate cost per subsystem from cycle type mappings
        subsystem_cost_types: dict[str, list[str]] = {
            "ring1": ["scenario_generation"],
            "memory": ["memory_consolidation"],
            "tpe": ["parameter_proposal"],
            "autonomy": [],  # no direct LLM cost — runs deterministic
            "signals": ["signal_analysis"],
        }

        costs_by_type = self.cost_per_cycle_type()
        assumed_vol = 0.15

        roi: dict[str, float] = {}
        for subsystem, sharpe_delta in sharpe_attributions.items():
            cost_types = subsystem_cost_types.get(subsystem, [])
            annual_subsystem_cost = sum(
                costs_by_type.get(ct, 0.0) / max(1, len(self._records)) * annual_cycles
                for ct in cost_types
            )

            # Additional annual return from Sharpe improvement
            additional_return = sharpe_delta * assumed_vol * capital

            if annual_subsystem_cost <= 0:
                roi[subsystem] = math.inf if additional_return > 0 else 0.0
            else:
                roi[subsystem] = round(
                    (additional_return - annual_subsystem_cost) / annual_subsystem_cost, 6
                )

        return roi

    def report(
        self,
        sharpe: float = 0.0,
        capital: float = 100_000.0,
        sharpe_attributions: dict[str, float] | None = None,
    ) -> CostReport:
        """
        Generate a full CostReport.

        Parameters
        ----------
        sharpe               : Achieved Sharpe ratio for cost_per_sharpe_unit.
        capital              : Capital for cost_adjusted_sharpe.
        sharpe_attributions  : Subsystem attributions for roi_by_subsystem.
        """
        total_cost = self.total_cost_usd()
        n = len(self._records)
        cost_per_cycle = total_cost / n if n > 0 else 0.0

        return CostReport(
            total_cost_usd=round(total_cost, 8),
            total_cycles=n,
            cost_per_cycle=round(cost_per_cycle, 8),
            cost_by_type={k: round(v, 8) for k, v in self.cost_per_cycle_type().items()},
            tokens_by_type=self.tokens_per_cycle_type(),
            cost_per_sharpe_unit=round(
                self.cost_per_sharpe_unit(sharpe=sharpe, total_cost=total_cost), 8
            ),
            cost_adjusted_sharpe=round(
                self.cost_adjusted_sharpe(
                    raw_sharpe=sharpe, total_cost=total_cost, capital=capital
                ),
                8,
            ),
            roi_by_subsystem=self.roi_by_subsystem(
                sharpe_attributions=sharpe_attributions or {},
                capital=capital,
            ),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_cost = (input_tokens / 1_000_000) * self._input_cost_per_1m
        output_cost = (output_tokens / 1_000_000) * self._output_cost_per_1m
        return input_cost + output_cost
