"""Tests for omega.core.memory_consolidation."""

from __future__ import annotations

import time

import pytest

from omega.core.memory_consolidation import (
    ConsolidationPipeline,
    DecayManager,
    ImportanceScorer,
    MemoryIndex,
    MemoryRecord,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(
    regime_tag: str = "normal",
    signal_type: str = "price_move",
    importance: float = 0.7,
    is_landmark: bool = False,
    age_seconds: float = 0.0,
) -> MemoryRecord:
    record = MemoryRecord.create(
        regime_tag=regime_tag,
        signal_type=signal_type,
        content={"value": 42},
        importance=importance,
        is_landmark=is_landmark,
    )
    # Backdate creation time to simulate age
    record.created_at -= age_seconds
    return record


# ---------------------------------------------------------------------------
# MemoryRecord
# ---------------------------------------------------------------------------


class TestMemoryRecord:
    def test_create_sets_defaults(self):
        r = make_record()
        assert 0.0 <= r.importance <= 1.0
        assert r.memory_id
        assert r.access_count == 0
        assert not r.consolidated

    def test_create_landmark(self):
        r = make_record(is_landmark=True)
        assert r.is_landmark


# ---------------------------------------------------------------------------
# MemoryIndex
# ---------------------------------------------------------------------------


class TestMemoryIndex:
    def test_add_and_lookup_by_regime(self):
        idx = MemoryIndex()
        r = make_record(regime_tag="volatile")
        idx.add(r)
        assert r.memory_id in idx.by_regime("volatile")
        assert r.memory_id not in idx.by_regime("normal")

    def test_add_and_lookup_by_signal(self):
        idx = MemoryIndex()
        r = make_record(signal_type="volatility_spike")
        idx.add(r)
        assert r.memory_id in idx.by_signal("volatility_spike")

    def test_by_time_range(self):
        idx = MemoryIndex()
        r = make_record()
        now = time.time()
        r.created_at = now
        idx.add(r)
        ids = idx.by_time_range(now - 10, now + 10)
        assert r.memory_id in ids

    def test_time_range_excludes_outside(self):
        idx = MemoryIndex()
        r = make_record()
        r.created_at = time.time() - 10 * 86_400  # 10 days ago
        idx.add(r)
        now = time.time()
        ids = idx.by_time_range(now - 3600, now)
        assert r.memory_id not in ids

    def test_remove(self):
        idx = MemoryIndex()
        r = make_record(regime_tag="crash")
        idx.add(r)
        idx.remove(r)
        assert r.memory_id not in idx.by_regime("crash")

    def test_intersection(self):
        idx = MemoryIndex()
        r1 = make_record(regime_tag="volatile", signal_type="momentum")
        r2 = make_record(regime_tag="volatile", signal_type="trend_follow")
        idx.add(r1)
        idx.add(r2)
        result = idx.intersection(idx.by_regime("volatile"), idx.by_signal("momentum"))
        assert r1.memory_id in result
        assert r2.memory_id not in result

    def test_stats(self):
        idx = MemoryIndex()
        idx.add(make_record(regime_tag="normal"))
        idx.add(make_record(regime_tag="volatile"))
        s = idx.stats()
        assert s["regimes"]["normal"] == 1
        assert s["regimes"]["volatile"] == 1


# ---------------------------------------------------------------------------
# DecayManager
# ---------------------------------------------------------------------------


class TestDecayManager:
    def test_decay_reduces_importance(self):
        dm = DecayManager(half_life_seconds=86_400)
        r = make_record(importance=1.0, age_seconds=86_400)
        dm.decay(r)
        assert abs(r.importance - 0.5) < 0.01

    def test_decay_floor_for_normal(self):
        dm = DecayManager(half_life_seconds=86_400, floor=0.1)
        r = make_record(importance=0.1, age_seconds=86_400 * 100)
        dm.decay(r)
        assert r.importance >= 0.1

    def test_landmark_floor_protection(self):
        dm = DecayManager(half_life_seconds=3600, landmark_floor=0.3)
        r = make_record(importance=0.4, is_landmark=True, age_seconds=3600 * 1000)
        dm.decay(r)
        assert r.importance >= 0.3

    def test_non_landmark_can_go_below_landmark_floor(self):
        dm = DecayManager(half_life_seconds=3600, floor=0.0, landmark_floor=0.3)
        r = make_record(importance=0.4, is_landmark=False, age_seconds=3600 * 1000)
        dm.decay(r)
        assert r.importance < 0.3

    def test_should_prune_below_threshold(self):
        dm = DecayManager()
        r = make_record(importance=0.02)
        assert dm.should_prune(r, threshold=0.05)

    def test_should_not_prune_landmark(self):
        dm = DecayManager()
        r = make_record(importance=0.001, is_landmark=True)
        assert not dm.should_prune(r)

    def test_decay_all(self):
        dm = DecayManager(half_life_seconds=86_400)
        records = [make_record(importance=1.0, age_seconds=86_400) for _ in range(5)]
        dm.decay_all(records)
        for r in records:
            assert r.importance < 0.6

    def test_invalid_half_life_raises(self):
        with pytest.raises(ValueError):
            DecayManager(half_life_seconds=0)


# ---------------------------------------------------------------------------
# ImportanceScorer
# ---------------------------------------------------------------------------


class TestImportanceScorer:
    def test_regime_match_boosts_score(self):
        scorer = ImportanceScorer()
        now = time.time()
        r_match = make_record(regime_tag="volatile", importance=0.5)
        r_no_match = make_record(regime_tag="normal", importance=0.5)
        s_match = scorer.score(r_match, "volatile", now)
        s_no_match = scorer.score(r_no_match, "volatile", now)
        assert s_match > s_no_match

    def test_recency_boosts_score(self):
        scorer = ImportanceScorer()
        now = time.time()
        r_new = make_record(importance=0.5, age_seconds=0)
        r_old = make_record(importance=0.5, age_seconds=60 * 86_400)
        assert scorer.score(r_new, "normal", now) > scorer.score(r_old, "normal", now)

    def test_access_count_boosts_score(self):
        scorer = ImportanceScorer()
        now = time.time()
        r = make_record(importance=0.5)
        r.access_count = 50
        r2 = make_record(importance=0.5)
        r2.access_count = 0
        assert scorer.score(r, "normal", now) > scorer.score(r2, "normal", now)

    def test_rank_returns_sorted(self):
        scorer = ImportanceScorer()
        now = time.time()
        records = [make_record(importance=i / 10) for i in range(1, 6)]
        ranked = scorer.rank(records, "normal", now)
        scores = [s for s, _ in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_top_k(self):
        scorer = ImportanceScorer()
        records = [make_record() for _ in range(10)]
        ranked = scorer.rank(records, "normal", top_k=3)
        assert len(ranked) == 3

    def test_invalid_weights_raise(self):
        with pytest.raises(ValueError):
            ImportanceScorer(w_importance=0.5, w_recency=0.5, w_regime=0.5, w_access=0.5)


# ---------------------------------------------------------------------------
# ConsolidationPipeline
# ---------------------------------------------------------------------------


class TestConsolidationPipeline:
    def test_add_increases_short_term(self):
        pipeline = ConsolidationPipeline()
        pipeline.add(make_record())
        assert pipeline.short_term_size == 1
        assert pipeline.long_term_size == 0

    def test_get_returns_record(self):
        pipeline = ConsolidationPipeline()
        r = make_record()
        pipeline.add(r)
        retrieved = pipeline.get(r.memory_id)
        assert retrieved is not None
        assert retrieved.memory_id == r.memory_id

    def test_get_increments_access_count(self):
        pipeline = ConsolidationPipeline()
        r = make_record()
        pipeline.add(r)
        pipeline.get(r.memory_id)
        pipeline.get(r.memory_id)
        assert r.access_count == 2

    def test_consolidate_promotes_old_important_memories(self):
        pipeline = ConsolidationPipeline(
            min_age_seconds=100,
            promotion_threshold=0.3,
        )
        # Old enough + important enough → should promote
        r = make_record(importance=0.8, age_seconds=200)
        pipeline.add(r)
        result = pipeline.consolidate()
        assert result.consolidated == 1
        assert pipeline.long_term_size == 1
        assert pipeline.short_term_size == 0

    def test_consolidate_does_not_promote_young_memories(self):
        pipeline = ConsolidationPipeline(
            min_age_seconds=3600,
            promotion_threshold=0.3,
        )
        r = make_record(importance=0.9, age_seconds=10)  # too young
        pipeline.add(r)
        result = pipeline.consolidate()
        assert result.consolidated == 0
        assert pipeline.short_term_size == 1

    def test_consolidate_prunes_low_importance(self):
        pipeline = ConsolidationPipeline(
            min_age_seconds=3600,
            prune_threshold=0.1,
            decay_half_life=3600,
        )
        # Very old + low importance → gets decayed below prune threshold
        r = make_record(importance=0.08, age_seconds=7200)
        pipeline.add(r)
        result = pipeline.consolidate()
        assert result.pruned == 1
        assert pipeline.short_term_size == 0

    def test_consolidate_does_not_prune_landmarks(self):
        pipeline = ConsolidationPipeline(
            prune_threshold=0.5,
            landmark_floor=0.3,
            decay_half_life=3600,
        )
        r = make_record(importance=0.4, is_landmark=True, age_seconds=7200)
        pipeline.add(r)
        pipeline.consolidate()
        # Landmark should survive even if importance < prune_threshold after decay
        # (it may be promoted or stay in short-term, but not pruned)
        total = pipeline.short_term_size + pipeline.long_term_size
        assert total == 1

    def test_maybe_consolidate_respects_interval(self):
        pipeline = ConsolidationPipeline(consolidation_interval=3600)
        r = make_record()
        pipeline.add(r)
        result = pipeline.maybe_consolidate(now=time.time())
        assert result is None  # interval not elapsed

    def test_maybe_consolidate_runs_after_interval(self):
        pipeline = ConsolidationPipeline(consolidation_interval=3600)
        r = make_record()
        pipeline.add(r)
        future = time.time() + 7200
        result = pipeline.maybe_consolidate(now=future)
        assert result is not None

    def test_query_by_regime(self):
        pipeline = ConsolidationPipeline()
        r1 = make_record(regime_tag="volatile")
        r2 = make_record(regime_tag="normal")
        pipeline.add(r1)
        pipeline.add(r2)
        results = pipeline.query(regime_tag="volatile", current_regime="volatile")
        ids = [r.memory_id for _, r in results]
        assert r1.memory_id in ids
        assert r2.memory_id not in ids

    def test_query_by_signal_type(self):
        pipeline = ConsolidationPipeline()
        r1 = make_record(signal_type="momentum")
        r2 = make_record(signal_type="mean_reversion")
        pipeline.add(r1)
        pipeline.add(r2)
        results = pipeline.query(signal_type="momentum")
        ids = [r.memory_id for _, r in results]
        assert r1.memory_id in ids
        assert r2.memory_id not in ids

    def test_stats(self):
        pipeline = ConsolidationPipeline()
        pipeline.add(make_record())
        s = pipeline.stats()
        assert "short_term" in s
        assert "long_term" in s
        assert "index" in s
