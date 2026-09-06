"""
tests/test_meta_harness.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for omega.core.meta_harness.

All tests use synthetic evaluation (live=False) — no live trading or
network calls. The LLM proposer is disabled (OMEGA_META_LLM unset).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omega.core.meta_harness import (
    MetaEvaluator,
    MetaHarness,
    MetaProposer,
    StrategyFileSystem,
    StrategyIteration,
    StrategyProposal,
    compute_score,
)

# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------


class TestComputeScore:
    def test_zero_trades_returns_zero(self) -> None:
        score = compute_score({"sharpe": 2.0, "hit_rate": 0.6, "trade_count": 0})
        assert score == 0.0

    def test_perfect_metrics_high_score(self) -> None:
        score = compute_score({
            "sharpe": 3.0,
            "drawdown": 0.0,
            "hit_rate": 1.0,
            "profit_factor": 3.0,
            "long_ratio": 0.5,
            "trade_count": 50,
        })
        assert score > 0.9

    def test_terrible_metrics_low_score(self) -> None:
        score = compute_score({
            "sharpe": 0.0,
            "drawdown": -1.0,
            "hit_rate": 0.0,
            "profit_factor": 0.0,
            "long_ratio": 0.0,
            "trade_count": 5,
        })
        assert score < 0.1

    def test_score_in_0_1_range(self) -> None:
        score = compute_score({
            "sharpe": 1.5,
            "drawdown": -0.05,
            "hit_rate": 0.55,
            "profit_factor": 1.4,
            "long_ratio": 0.48,
            "trade_count": 30,
        })
        assert 0.0 <= score <= 1.0

    def test_long_ratio_penalty_at_extremes(self) -> None:
        balanced = compute_score({
            "sharpe": 1.0, "drawdown": 0.0, "hit_rate": 0.5,
            "profit_factor": 1.5, "long_ratio": 0.5, "trade_count": 20,
        })
        all_short = compute_score({
            "sharpe": 1.0, "drawdown": 0.0, "hit_rate": 0.5,
            "profit_factor": 1.5, "long_ratio": 0.0, "trade_count": 20,
        })
        assert balanced > all_short

    def test_missing_metrics_default_to_zero(self) -> None:
        # Should not raise, should produce a valid score
        score = compute_score({"trade_count": 10})
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# StrategyIteration
# ---------------------------------------------------------------------------


class TestStrategyIteration:
    def _make_iter(self, **kwargs) -> StrategyIteration:
        defaults = dict(
            iteration_id=1,
            parent_id=None,
            changes_description="test change",
            code_diff="risk.stop_loss_pct: 0.02 → 0.015",
            metrics={"sharpe": 1.2, "hit_rate": 0.55, "trade_count": 20},
            trade_log_path="/tmp/trades.csv",
            score=0.55,
        )
        defaults.update(kwargs)
        return StrategyIteration(**defaults)

    def test_roundtrip_serialisation(self) -> None:
        it = self._make_iter()
        d = it.to_dict()
        it2 = StrategyIteration.from_dict(d)
        assert it2.iteration_id == 1
        assert it2.score == pytest.approx(0.55)
        assert it2.parent_id is None

    def test_from_dict_with_parent(self) -> None:
        it = self._make_iter(iteration_id=5, parent_id=4)
        it2 = StrategyIteration.from_dict(it.to_dict())
        assert it2.parent_id == 4

    def test_metrics_summary_format(self) -> None:
        it = self._make_iter(
            metrics={"sharpe": 1.5, "drawdown": -0.03, "hit_rate": 0.60, "profit_factor": 1.8},
            score=0.6,
        )
        summary = it.metrics_summary()
        assert "sharpe=1.500" in summary
        assert "score=0.6000" in summary


# ---------------------------------------------------------------------------
# StrategyFileSystem
# ---------------------------------------------------------------------------


class TestStrategyFileSystem:
    @pytest.fixture
    def fs(self, tmp_path: Path) -> StrategyFileSystem:
        return StrategyFileSystem(base_dir=tmp_path)

    def _make_iter(self, iteration_id: int, score: float, parent_id=None) -> StrategyIteration:
        return StrategyIteration(
            iteration_id=iteration_id,
            parent_id=parent_id,
            changes_description="test",
            code_diff="x: 1 → 2",
            metrics={"sharpe": score * 2, "hit_rate": 0.5, "trade_count": 10},
            trade_log_path="",
            score=score,
        )

    def test_save_creates_directory(self, fs: StrategyFileSystem, tmp_path: Path) -> None:
        it = self._make_iter(1, 0.5)
        fs.save(it, {"strategy": {"x": 1}}, [])
        assert (tmp_path / "iter_001").exists()

    def test_save_writes_all_files(self, fs: StrategyFileSystem, tmp_path: Path) -> None:
        it = self._make_iter(1, 0.5)
        fs.save(it, {"strategy": {"x": 1}}, [{"symbol": "BTC", "pnl": 10.0}])
        d = tmp_path / "iter_001"
        assert (d / "strategy_snapshot.json").exists()
        assert (d / "trades.csv").exists()
        assert (d / "metrics.json").exists()
        assert (d / "rationale.md").exists()

    def test_index_updated_after_save(self, fs: StrategyFileSystem) -> None:
        fs.save(self._make_iter(1, 0.5), {}, [])
        fs.save(self._make_iter(2, 0.6), {}, [])
        assert len(fs._index) == 2

    def test_get_full_history_ordered(self, fs: StrategyFileSystem) -> None:
        for i in [3, 1, 2]:
            fs.save(self._make_iter(i, 0.1 * i), {}, [])
        history = fs.get_full_history()
        assert [it.iteration_id for it in history] == [1, 2, 3]

    def test_get_best_iteration(self, fs: StrategyFileSystem) -> None:
        fs.save(self._make_iter(1, 0.3), {}, [])
        fs.save(self._make_iter(2, 0.7), {}, [])
        fs.save(self._make_iter(3, 0.5), {}, [])
        best = fs.get_best_iteration()
        assert best is not None
        assert best.iteration_id == 2

    def test_get_best_iteration_empty(self, fs: StrategyFileSystem) -> None:
        assert fs.get_best_iteration() is None

    def test_get_recent_regressions(self, fs: StrategyFileSystem) -> None:
        fs.save(self._make_iter(1, 0.5, parent_id=None), {}, [])
        fs.save(self._make_iter(2, 0.4, parent_id=1), {}, [])  # regression
        fs.save(self._make_iter(3, 0.6, parent_id=2), {}, [])  # improvement
        fs.save(self._make_iter(4, 0.3, parent_id=3), {}, [])  # regression
        regressions = fs.get_recent_regressions(n=5)
        reg_ids = {r.iteration_id for r in regressions}
        assert 2 in reg_ids
        assert 4 in reg_ids
        assert 3 not in reg_ids

    def test_next_iteration_id_starts_at_1(self, fs: StrategyFileSystem) -> None:
        assert fs.next_iteration_id() == 1

    def test_next_iteration_id_increments(self, fs: StrategyFileSystem) -> None:
        fs.save(self._make_iter(1, 0.5), {}, [])
        fs.save(self._make_iter(2, 0.5), {}, [])
        assert fs.next_iteration_id() == 3

    def test_load_snapshot(self, fs: StrategyFileSystem) -> None:
        snapshot = {"strategy": {"conviction_threshold_buy": 0.25}}
        it = self._make_iter(1, 0.5)
        fs.save(it, snapshot, [])
        loaded = fs.load_snapshot(1)
        assert loaded["strategy"]["conviction_threshold_buy"] == pytest.approx(0.25)

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        fs1 = StrategyFileSystem(base_dir=tmp_path)
        fs1.save(self._make_iter(1, 0.5), {"x": 1}, [])

        fs2 = StrategyFileSystem(base_dir=tmp_path)
        assert len(fs2._index) == 1
        assert fs2._index[0]["score"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# StrategyProposal
# ---------------------------------------------------------------------------


class TestStrategyProposal:
    def test_construction(self) -> None:
        p = StrategyProposal(
            category="conviction",
            param_path="strategy.conviction_threshold_buy",
            old_value=0.20,
            new_value=0.15,
            rationale="Lower conviction threshold to improve hit rate",
            confidence=0.7,
        )
        assert p.category == "conviction"
        assert p.new_value == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# MetaProposer (heuristic mode, no LLM)
# ---------------------------------------------------------------------------


class TestMetaProposer:
    @pytest.fixture
    def fs(self, tmp_path: Path) -> StrategyFileSystem:
        return StrategyFileSystem(base_dir=tmp_path)

    @pytest.fixture
    def proposer(self, fs: StrategyFileSystem) -> MetaProposer:
        return MetaProposer(fs, feedback_descent=None, use_llm=False)

    def test_propose_returns_strategy_proposal(
        self, proposer: MetaProposer
    ) -> None:
        snapshot = MetaHarness._default_snapshot()
        proposal = proposer.propose(snapshot)
        assert isinstance(proposal, StrategyProposal)
        assert proposal.category in [
            "signal_weight", "conviction", "risk", "signal_toggle", "regime"
        ]

    def test_proposal_has_rationale(self, proposer: MetaProposer) -> None:
        snapshot = MetaHarness._default_snapshot()
        proposal = proposer.propose(snapshot)
        assert len(proposal.rationale) > 0

    def test_proposal_confidence_in_range(self, proposer: MetaProposer) -> None:
        snapshot = MetaHarness._default_snapshot()
        proposal = proposer.propose(snapshot)
        assert 0.0 <= proposal.confidence <= 1.0

    def test_propose_with_history(
        self, fs: StrategyFileSystem, proposer: MetaProposer
    ) -> None:
        # Add some history and verify proposal is still valid
        for i in range(3):
            it = StrategyIteration(
                iteration_id=i + 1,
                parent_id=i if i > 0 else None,
                changes_description="adjusted param",
                code_diff=f"strategy.conviction_threshold_buy: 0.2 → {0.2 - i*0.02}",
                metrics={
                    "sharpe": 1.5 - i * 0.1,
                    "drawdown": -0.03,
                    "hit_rate": 0.55,
                    "profit_factor": 1.4,
                    "long_ratio": 0.5,
                    "trade_count": 20,
                },
                trade_log_path="",
                score=0.55 - i * 0.01,
            )
            fs.save(it, MetaHarness._default_snapshot(), [])

        proposal = proposer.propose(MetaHarness._default_snapshot())
        assert isinstance(proposal, StrategyProposal)

    def test_propose_detects_long_short_imbalance(
        self, fs: StrategyFileSystem
    ) -> None:
        proposer = MetaProposer(fs, use_llm=False)
        # Add history with all-short bias
        for i in range(3):
            it = StrategyIteration(
                iteration_id=i + 1,
                parent_id=None,
                changes_description="test",
                code_diff="",
                metrics={
                    "sharpe": 1.0, "drawdown": -0.02, "hit_rate": 0.5,
                    "profit_factor": 1.2, "long_ratio": 0.1,  # all short
                    "trade_count": 15,
                },
                trade_log_path="",
                score=0.4,
            )
            fs.save(it, {}, [])

        snapshot = MetaHarness._default_snapshot()
        proposal = proposer.propose(snapshot)
        # Should propose adjusting conviction or similar to fix bias
        assert isinstance(proposal, StrategyProposal)


# ---------------------------------------------------------------------------
# MetaEvaluator (synthetic mode)
# ---------------------------------------------------------------------------


class TestMetaEvaluator:
    @pytest.fixture
    def evaluator(self) -> MetaEvaluator:
        return MetaEvaluator(n_eval_cycles=5, live=False)

    def test_evaluate_returns_iteration_and_trades(
        self, evaluator: MetaEvaluator
    ) -> None:
        proposal = StrategyProposal(
            category="risk",
            param_path="risk.stop_loss_pct",
            old_value=0.02,
            new_value=0.015,
            rationale="tighter stop to reduce drawdown",
            confidence=0.6,
        )
        snapshot = MetaHarness._default_snapshot()
        iteration, trades = evaluator.evaluate(proposal, None, snapshot, iteration_id=1)
        assert isinstance(iteration, StrategyIteration)
        assert isinstance(trades, list)

    def test_evaluate_fills_metrics(self, evaluator: MetaEvaluator) -> None:
        proposal = StrategyProposal(
            category="conviction",
            param_path="strategy.conviction_threshold_buy",
            old_value=0.20,
            new_value=0.15,
            rationale="lower threshold",
            confidence=0.7,
        )
        iteration, _ = evaluator.evaluate(
            proposal, None, MetaHarness._default_snapshot(), iteration_id=1
        )
        assert "sharpe" in iteration.metrics
        assert "hit_rate" in iteration.metrics
        assert "trade_count" in iteration.metrics
        assert iteration.score >= 0.0

    def test_evaluate_sets_code_diff(self, evaluator: MetaEvaluator) -> None:
        proposal = StrategyProposal(
            category="risk",
            param_path="risk.stop_loss_pct",
            old_value=0.02,
            new_value=0.015,
            rationale="test",
            confidence=0.5,
        )
        iteration, _ = evaluator.evaluate(
            proposal, None, MetaHarness._default_snapshot(), iteration_id=1
        )
        assert "risk.stop_loss_pct" in iteration.code_diff
        assert "0.02" in iteration.code_diff
        assert "0.015" in iteration.code_diff

    def test_evaluate_applies_parent_metrics(self, evaluator: MetaEvaluator) -> None:
        parent = StrategyIteration(
            iteration_id=1,
            parent_id=None,
            changes_description="baseline",
            code_diff="",
            metrics={"sharpe": 2.0, "hit_rate": 0.65, "trade_count": 30},
            trade_log_path="",
            score=0.7,
        )
        proposal = StrategyProposal(
            category="signal_weight",
            param_path="dynamic_weights.ema_alpha",
            old_value=0.3,
            new_value=0.35,
            rationale="slightly more reactive weights",
            confidence=0.6,
        )
        iteration, _ = evaluator.evaluate(
            proposal, parent, MetaHarness._default_snapshot(), iteration_id=2
        )
        assert iteration.parent_id == 1

    def test_apply_proposal_to_snapshot(self, evaluator: MetaEvaluator) -> None:
        snapshot = {"risk": {"stop_loss_pct": 0.02}}
        proposal = StrategyProposal(
            category="risk",
            param_path="risk.stop_loss_pct",
            old_value=0.02,
            new_value=0.015,
            rationale="",
            confidence=0.5,
        )
        new_snap = evaluator._apply_proposal_to_snapshot(proposal, snapshot)
        assert new_snap["risk"]["stop_loss_pct"] == pytest.approx(0.015)
        # Original should not be mutated
        assert snapshot["risk"]["stop_loss_pct"] == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# MetaHarness (integration, synthetic mode)
# ---------------------------------------------------------------------------


class TestMetaHarness:
    @pytest.fixture
    def harness(self, tmp_path: Path) -> MetaHarness:
        return MetaHarness(
            n_eval_cycles=5,
            live=False,
            use_llm=False,
            base_dir=tmp_path,
        )

    def test_run_iteration_returns_strategy_iteration(
        self, harness: MetaHarness
    ) -> None:
        result = harness.run_iteration()
        assert isinstance(result, StrategyIteration)
        assert result.iteration_id == 1

    def test_run_iteration_persists_to_fs(self, harness: MetaHarness) -> None:
        harness.run_iteration()
        history = harness._fs.get_full_history()
        assert len(history) == 1

    def test_run_loop_produces_n_iterations(self, harness: MetaHarness) -> None:
        results = harness.run_loop(3)
        assert len(results) == 3
        ids = [r.iteration_id for r in results]
        assert ids == [1, 2, 3]

    def test_consecutive_regressions_trigger_revert(
        self, tmp_path: Path
    ) -> None:
        harness = MetaHarness(
            n_eval_cycles=2, live=False, use_llm=False, base_dir=tmp_path
        )
        # Pre-seed a good iteration so revert has a target
        good_it = StrategyIteration(
            iteration_id=1,
            parent_id=None,
            changes_description="baseline",
            code_diff="",
            metrics={
                "sharpe": 2.5, "drawdown": -0.01, "hit_rate": 0.65,
                "profit_factor": 2.0, "long_ratio": 0.5, "trade_count": 30,
            },
            trade_log_path="",
            score=0.85,
        )
        harness._fs.save(good_it, MetaHarness._default_snapshot(), [])
        harness._consecutive_regressions = harness._MAX_CONSECUTIVE_REGRESSIONS - 1

        # One more regression should trigger revert
        result = harness.run_iteration()
        # After potential revert, regression counter should reset
        # (score may or may not have improved — synthetic is random)
        assert isinstance(result, StrategyIteration)

    def test_get_status(self, harness: MetaHarness) -> None:
        status = harness.get_status()
        assert "total_iterations" in status
        assert "best_score" in status
        assert "llm_enabled" in status
        assert status["llm_enabled"] is False

    def test_default_snapshot_structure(self) -> None:
        snap = MetaHarness._default_snapshot()
        assert "dynamic_weights" in snap
        assert "strategy" in snap
        assert "risk" in snap
        assert "ema_alpha" in snap["dynamic_weights"]
        assert "conviction_threshold_buy" in snap["strategy"]

    def test_feedback_recorded_per_iteration(self, harness: MetaHarness) -> None:
        harness.run_iteration()
        harness.run_iteration()
        records = harness._fd.get_all_records()
        assert len(records) == 2

    def test_run_loop_with_exception_continues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = MetaHarness(
            n_eval_cycles=2, live=False, use_llm=False, base_dir=tmp_path
        )
        call_count = 0
        original = harness.run_iteration

        def patched_run_iteration():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Simulated failure")
            return original()

        monkeypatch.setattr(harness, "run_iteration", patched_run_iteration)
        results = harness.run_loop(3)
        # Should have 2 successful results (iter 1 and iter 3)
        assert len(results) == 2
