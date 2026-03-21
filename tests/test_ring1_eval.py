"""Tests for omega.eval.ring1_eval — Ring1Evaluator."""

from __future__ import annotations

import pytest

from omega.eval.ring1_eval import (
    Ring1CycleRecord,
    Ring1EvalReport,
    Ring1Evaluator,
    _sharpe,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_records(
    n: int = 100,
    flag_rate: float = 0.3,
    loss_rate: float = 0.4,
    seed: int = 42,
) -> list[Ring1CycleRecord]:
    """Build synthetic cycle records for unit testing the report computation."""
    import random

    rng = random.Random(seed)
    records = []
    for i in range(n):
        flagged = rng.random() < flag_rate
        would_lose = rng.random() < loss_rate
        pnl = rng.gauss(-0.005, 0.002) if would_lose else rng.gauss(0.003, 0.001)
        records.append(
            Ring1CycleRecord(
                cycle_number=i,
                flagged=flagged,
                counterfactual_pnl=pnl,
                trade_would_have_lost=would_lose,
            )
        )
    return records


# ---------------------------------------------------------------------------
# Ring1CycleRecord
# ---------------------------------------------------------------------------


class TestRing1CycleRecord:
    def test_creation(self):
        rec = Ring1CycleRecord(
            cycle_number=5,
            flagged=True,
            counterfactual_pnl=-0.002,
            trade_would_have_lost=True,
        )
        assert rec.cycle_number == 5
        assert rec.flagged is True
        assert rec.trade_would_have_lost is True


# ---------------------------------------------------------------------------
# Report computation
# ---------------------------------------------------------------------------


class TestRing1EvalReportComputation:
    """Unit-test the _compute_report logic via Ring1Evaluator."""

    def _compute(self, records: list[Ring1CycleRecord]) -> Ring1EvalReport:
        ev = Ring1Evaluator(n_cycles=0, inject_flags=False)
        return ev._compute_report(records)

    def test_empty_records_returns_zero_report(self):
        report = self._compute([])
        assert report.n_cycles == 0
        assert report.precision == 0.0
        assert report.recall == 0.0
        assert report.f1 == 0.0

    def test_precision_definition(self):
        """precision = TP / (TP + FP) = (flagged & lost) / (all flagged)"""
        records = [
            # flagged & lost = TP
            Ring1CycleRecord(0, True, -0.01, True),
            Ring1CycleRecord(1, True, -0.01, True),
            # flagged & won = FP
            Ring1CycleRecord(2, True, 0.01, False),
            # not flagged
            Ring1CycleRecord(3, False, 0.01, False),
        ]
        report = self._compute(records)
        # 2 TP, 1 FP → precision = 2/3
        assert report.n_flagged == 3
        assert report.n_true_positives == 2
        assert report.precision == pytest.approx(2 / 3, abs=1e-6)

    def test_recall_definition(self):
        """recall = TP / (TP + FN) = (flagged & lost) / (all losing cycles)"""
        records = [
            Ring1CycleRecord(0, True, -0.01, True),  # TP
            Ring1CycleRecord(1, False, -0.01, True),  # FN (missed loser)
            Ring1CycleRecord(2, False, 0.01, False),  # TN
        ]
        report = self._compute(records)
        assert report.n_losing_cycles == 2
        assert report.n_true_positives == 1
        assert report.recall == pytest.approx(0.5, abs=1e-6)

    def test_f1_harmonic_mean(self):
        records = make_records(n=200, seed=1)
        report = self._compute(records)
        if report.precision + report.recall > 0:
            expected_f1 = 2 * report.precision * report.recall / (report.precision + report.recall)
            assert report.f1 == pytest.approx(expected_f1, abs=1e-6)
        else:
            assert report.f1 == 0.0

    def test_opportunity_cost_only_positive_pnl(self):
        """opportunity_cost = sum of POSITIVE PnL from suppressed winning trades."""
        records = [
            Ring1CycleRecord(0, True, 0.01, False),  # FP with positive PnL
            Ring1CycleRecord(1, True, 0.02, False),  # FP with positive PnL
            Ring1CycleRecord(2, True, -0.01, True),  # TP (loss avoided)
        ]
        report = self._compute(records)
        assert report.opportunity_cost == pytest.approx(0.03, abs=1e-8)

    def test_saved_losses(self):
        """saved_losses = sum of abs(pnl) for TP (flagged losers)."""
        records = [
            Ring1CycleRecord(0, True, -0.005, True),
            Ring1CycleRecord(1, True, -0.003, True),
            Ring1CycleRecord(2, False, 0.01, False),
        ]
        report = self._compute(records)
        assert report.saved_losses == pytest.approx(0.008, abs=1e-8)

    def test_net_impact_formula(self):
        """net_impact = (saved_losses - opportunity_cost) / n_cycles"""
        records = make_records(n=50, seed=7)
        report = self._compute(records)
        expected = (report.saved_losses - report.opportunity_cost) / report.n_cycles
        assert report.net_impact == pytest.approx(expected, abs=1e-8)

    def test_flags_per_100(self):
        records = make_records(n=100, flag_rate=0.25)
        report = self._compute(records)
        # Should be close to 25 flags/100 (stochastic, so use loose bound)
        assert 10 <= report.flags_per_100 <= 50

    def test_net_sharpe_impact_type(self):
        records = make_records(n=100)
        report = self._compute(records)
        assert isinstance(report.net_sharpe_impact, float)


# ---------------------------------------------------------------------------
# Ring1Evaluator.run()
# ---------------------------------------------------------------------------


class TestRing1EvaluatorRun:
    def test_run_returns_report(self):
        ev = Ring1Evaluator(n_cycles=50, seed=42)
        report = ev.run()
        assert isinstance(report, Ring1EvalReport)

    def test_run_cycle_count(self):
        ev = Ring1Evaluator(n_cycles=30, seed=1)
        report = ev.run()
        assert report.n_cycles == 30

    def test_precision_between_0_and_1(self):
        ev = Ring1Evaluator(n_cycles=100, seed=42)
        report = ev.run()
        assert 0.0 <= report.precision <= 1.0

    def test_recall_between_0_and_1(self):
        ev = Ring1Evaluator(n_cycles=100, seed=42)
        report = ev.run()
        assert 0.0 <= report.recall <= 1.0

    def test_f1_between_0_and_1(self):
        ev = Ring1Evaluator(n_cycles=100, seed=42)
        report = ev.run()
        assert 0.0 <= report.f1 <= 1.0

    def test_inject_flags_false(self):
        """Without flag injection, flags come only from real orchestrator adversarial layer."""
        ev = Ring1Evaluator(n_cycles=30, inject_flags=False, seed=99)
        report = ev.run()
        assert isinstance(report, Ring1EvalReport)

    def test_str_representation(self):
        ev = Ring1Evaluator(n_cycles=20, seed=1)
        report = ev.run()
        s = str(report)
        assert "Ring1EvalReport" in s
        assert "precision" in s

    def test_high_loss_rate_higher_saving(self):
        """Higher loss_rate should lead to more saved losses (on average)."""
        ev_low = Ring1Evaluator(n_cycles=200, loss_rate=0.1, seed=42)
        ev_high = Ring1Evaluator(n_cycles=200, loss_rate=0.7, seed=42)
        r_low = ev_low.run()
        r_high = ev_high.run()
        # More losing cycles flagged → more saved losses
        assert r_high.n_losing_cycles >= r_low.n_losing_cycles


# ---------------------------------------------------------------------------
# _sharpe helper
# ---------------------------------------------------------------------------


class TestSharpeHelper:
    def test_empty(self):
        assert _sharpe([]) == 0.0

    def test_single(self):
        assert _sharpe([0.01]) == 0.0

    def test_finite(self):
        import math
        import random

        rng = random.Random(1)
        returns = [rng.gauss(0.001, 0.01) for _ in range(100)]
        s = _sharpe(returns)
        assert math.isfinite(s)
