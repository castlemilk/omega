"""
tests/test_feedback_descent.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for omega.core.feedback_descent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omega.core.feedback_descent import (
    DirectionalGuidance,
    FeedbackDescent,
    FeedbackRecord,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_fd(tmp_path: Path) -> FeedbackDescent:
    return FeedbackDescent(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# FeedbackRecord
# ---------------------------------------------------------------------------


class TestFeedbackRecord:
    def test_is_improvement_positive_score(self) -> None:
        r = FeedbackRecord(
            iteration_id=1,
            feedback_text="improved sharpe by adjusting weights",
            metrics_delta={"score": 0.05, "sharpe": 0.2},
        )
        assert r.is_improvement() is True

    def test_is_improvement_negative_score(self) -> None:
        r = FeedbackRecord(
            iteration_id=2,
            feedback_text="regression — conviction too loose",
            metrics_delta={"score": -0.03, "sharpe": -0.1},
        )
        assert r.is_improvement() is False

    def test_is_improvement_zero_score(self) -> None:
        r = FeedbackRecord(
            iteration_id=3,
            feedback_text="no change",
            metrics_delta={"score": 0.0},
        )
        assert r.is_improvement() is False

    def test_roundtrip_serialisation(self) -> None:
        r = FeedbackRecord(
            iteration_id=5,
            feedback_text="test feedback",
            metrics_delta={"score": 0.1, "sharpe": 0.3},
            tags=["signal_weight"],
        )
        d = r.to_dict()
        r2 = FeedbackRecord.from_dict(d)
        assert r2.iteration_id == 5
        assert r2.feedback_text == "test feedback"
        assert r2.metrics_delta["score"] == pytest.approx(0.1)
        assert r2.tags == ["signal_weight"]


# ---------------------------------------------------------------------------
# FeedbackDescent.record_feedback
# ---------------------------------------------------------------------------


class TestRecordFeedback:
    def test_stores_record(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(1, "good change", {"score": 0.05})
        assert len(tmp_fd.get_all_records()) == 1

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        fd = FeedbackDescent(base_dir=tmp_path)
        fd.record_feedback(1, "some feedback", {"score": 0.02})

        # New instance should reload from disk
        fd2 = FeedbackDescent(base_dir=tmp_path)
        assert len(fd2.get_all_records()) == 1
        assert fd2.get_all_records()[0].feedback_text == "some feedback"

    def test_multiple_records_ordered(self, tmp_fd: FeedbackDescent) -> None:
        for i in range(5):
            tmp_fd.record_feedback(i, f"feedback {i}", {"score": float(i) * 0.01})
        records = tmp_fd.get_all_records()
        assert [r.iteration_id for r in records] == list(range(5))

    def test_record_with_tags(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(
            1, "adjusted ema_alpha", {"score": 0.03}, tags=["signal_weight"]
        )
        r = tmp_fd.get_all_records()[0]
        assert "signal_weight" in r.tags

    def test_returns_feedback_record(self, tmp_fd: FeedbackDescent) -> None:
        result = tmp_fd.record_feedback(1, "text", {"score": 0.01})
        assert isinstance(result, FeedbackRecord)


# ---------------------------------------------------------------------------
# FeedbackDescent.get_records_for_iteration
# ---------------------------------------------------------------------------


class TestGetRecordsForIteration:
    def test_filters_by_iteration(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(1, "a", {"score": 0.01})
        tmp_fd.record_feedback(2, "b", {"score": 0.02})
        tmp_fd.record_feedback(1, "c", {"score": 0.03})
        records = tmp_fd.get_records_for_iteration(1)
        assert len(records) == 2
        assert all(r.iteration_id == 1 for r in records)

    def test_empty_for_missing_iteration(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(1, "a", {"score": 0.01})
        assert tmp_fd.get_records_for_iteration(99) == []


# ---------------------------------------------------------------------------
# FeedbackDescent.get_directional_feedback
# ---------------------------------------------------------------------------


class TestGetDirectionalFeedback:
    def test_insufficient_data(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(1, "one record", {"score": 0.01})
        guidance = tmp_fd.get_directional_feedback(min_records=3)
        assert guidance.confidence == 0.0
        assert guidance.based_on_n == 1
        assert len(guidance.do_more) == 1
        assert "Insufficient" in guidance.do_more[0]

    def test_separates_improvements_and_regressions(self, tmp_fd: FeedbackDescent) -> None:
        for i in range(4):
            tmp_fd.record_feedback(
                i,
                "sharpe improved by weight adjustment momentum signal",
                {"score": 0.05 * (i + 1)},
            )
        for i in range(4, 8):
            tmp_fd.record_feedback(
                i,
                "drawdown increased conviction regression threshold",
                {"score": -0.02},
            )
        guidance = tmp_fd.get_directional_feedback(min_records=3)
        assert isinstance(guidance, DirectionalGuidance)
        assert guidance.based_on_n == 8
        assert guidance.confidence > 0.0

    def test_confidence_grows_with_data(self, tmp_fd: FeedbackDescent) -> None:
        guidance_few = tmp_fd.get_directional_feedback(min_records=3)
        assert guidance_few.confidence == 0.0

        for i in range(20):
            tmp_fd.record_feedback(
                i,
                f"signal weight improved regime momentum factor iteration {i}",
                {"score": 0.01 if i % 3 != 0 else -0.01},
            )
        guidance_many = tmp_fd.get_directional_feedback(min_records=3)
        assert guidance_many.confidence > 0.0
        assert guidance_many.based_on_n == 20

    def test_summary_includes_guidance(self, tmp_fd: FeedbackDescent) -> None:
        for i in range(5):
            tmp_fd.record_feedback(i, f"text {i}", {"score": 0.01 * i})
        guidance = tmp_fd.get_directional_feedback(min_records=3)
        summary = guidance.summary()
        assert "Directional guidance" in summary

    def test_recent_n_limits_records(self, tmp_fd: FeedbackDescent) -> None:
        for i in range(10):
            tmp_fd.record_feedback(i, f"text {i}", {"score": 0.01})
        guidance = tmp_fd.get_directional_feedback(min_records=3, recent_n=5)
        assert guidance.based_on_n == 5


# ---------------------------------------------------------------------------
# FeedbackDescent.summarize_for_llm
# ---------------------------------------------------------------------------


class TestSummarizeForLlm:
    def test_no_records_message(self, tmp_fd: FeedbackDescent) -> None:
        summary = tmp_fd.summarize_for_llm()
        assert "No feedback history" in summary

    def test_includes_iteration_ids(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(7, "some rationale text", {"score": 0.03})
        summary = tmp_fd.summarize_for_llm()
        assert "Iter 7" in summary

    def test_marks_improvements_and_regressions(self, tmp_fd: FeedbackDescent) -> None:
        tmp_fd.record_feedback(1, "good", {"score": 0.05})
        tmp_fd.record_feedback(2, "bad", {"score": -0.02})
        summary = tmp_fd.summarize_for_llm()
        assert "IMPROVED" in summary
        assert "REGRESSED" in summary
