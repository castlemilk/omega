"""
omega.core.memory_consolidation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Consolidation pipeline for the Omega memory system.

Components
----------
  ConsolidationPipeline : Periodically merges short-term (episodic) memories into
                          long-term (semantic) storage.
  MemoryIndex           : Fast lookup by regime tag, time range, or signal type.
  ImportanceScorer      : Ranks memories by relevance to the current regime.
  DecayManager          : Exponential decay for old memories; landmark events are
                          protected from decay.

Design notes
------------
- Pure Python stdlib only.
- All time values are UNIX timestamps (float seconds).
- Decay half-life is configurable; landmark protection is implemented as a minimum
  floor so protected memories never fall below a threshold importance.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.core.memory_consolidation")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    """A single memory entry that may live in short-term or long-term storage."""

    memory_id: str
    created_at: float  # UNIX timestamp
    last_accessed: float  # updated on read
    importance: float  # 0.0-1.0; decays or is reinforced over time
    regime_tag: str  # regime label at time of creation
    signal_type: str  # e.g. "price_move", "volatility_spike", "regime_shift"
    content: dict[str, Any]
    tags: list[str]
    is_landmark: bool = False  # if True, protected from decay below floor
    access_count: int = 0
    consolidated: bool = False  # True once moved to long-term store

    @classmethod
    def create(
        cls,
        regime_tag: str,
        signal_type: str,
        content: dict[str, Any],
        tags: list[str] | None = None,
        importance: float = 0.5,
        is_landmark: bool = False,
    ) -> MemoryRecord:
        now = time.time()
        return cls(
            memory_id=str(uuid.uuid4()),
            created_at=now,
            last_accessed=now,
            importance=importance,
            regime_tag=regime_tag,
            signal_type=signal_type,
            content=content,
            tags=tags or [],
            is_landmark=is_landmark,
        )


# ---------------------------------------------------------------------------
# MemoryIndex
# ---------------------------------------------------------------------------


class MemoryIndex:
    """
    In-memory inverted index for fast lookup by:
      - regime_tag   (e.g. "volatile", "trending")
      - signal_type  (e.g. "price_move", "regime_shift")
      - time range   (bucketed by day for O(days) range queries)

    All three lookup methods return sets of memory_ids.
    """

    _BUCKET_SIZE = 86_400  # one day in seconds

    def __init__(self) -> None:
        self._by_regime: dict[str, set[str]] = defaultdict(set)
        self._by_signal: dict[str, set[str]] = defaultdict(set)
        # time bucket → set of memory_ids
        self._by_time: dict[int, set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, record: MemoryRecord) -> None:
        self._by_regime[record.regime_tag].add(record.memory_id)
        self._by_signal[record.signal_type].add(record.memory_id)
        bucket = int(record.created_at // self._BUCKET_SIZE)
        self._by_time[bucket].add(record.memory_id)

    def remove(self, record: MemoryRecord) -> None:
        self._by_regime[record.regime_tag].discard(record.memory_id)
        self._by_signal[record.signal_type].discard(record.memory_id)
        bucket = int(record.created_at // self._BUCKET_SIZE)
        self._by_time[bucket].discard(record.memory_id)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def by_regime(self, regime_tag: str) -> set[str]:
        return set(self._by_regime.get(regime_tag, set()))

    def by_signal(self, signal_type: str) -> set[str]:
        return set(self._by_signal.get(signal_type, set()))

    def by_time_range(self, start: float, end: float) -> set[str]:
        start_bucket = int(start // self._BUCKET_SIZE)
        end_bucket = int(end // self._BUCKET_SIZE)
        ids: set[str] = set()
        for b in range(start_bucket, end_bucket + 1):
            ids.update(self._by_time.get(b, set()))
        return ids

    def intersection(self, *id_sets: set[str]) -> set[str]:
        if not id_sets:
            return set()
        result = id_sets[0]
        for s in id_sets[1:]:
            result = result & s
        return result

    def stats(self) -> dict[str, Any]:
        return {
            "regimes": {k: len(v) for k, v in self._by_regime.items()},
            "signal_types": {k: len(v) for k, v in self._by_signal.items()},
            "time_buckets": len(self._by_time),
        }


# ---------------------------------------------------------------------------
# DecayManager
# ---------------------------------------------------------------------------


class DecayManager:
    """
    Applies exponential importance decay to MemoryRecords.

    Importance at time t:
        I(t) = max(floor, I0 x exp(-lambda x dt))

    where λ = ln(2) / half_life_seconds.

    Landmark memories have a protected floor of `landmark_floor` (default 0.3)
    so they are never pruned even after long periods of inactivity.
    """

    def __init__(
        self,
        half_life_seconds: float = 7 * 86_400,  # 7 days default
        floor: float = 0.0,
        landmark_floor: float = 0.3,
    ) -> None:
        if half_life_seconds <= 0:
            raise ValueError("half_life_seconds must be positive")
        self._decay_lambda = math.log(2) / half_life_seconds
        self._floor = floor
        self._landmark_floor = landmark_floor

    def decay(self, record: MemoryRecord, now: float | None = None) -> None:
        """Mutates record.importance in place."""
        if now is None:
            now = time.time()
        elapsed = max(0.0, now - record.created_at)
        decayed = record.importance * math.exp(-self._decay_lambda * elapsed)
        floor = self._landmark_floor if record.is_landmark else self._floor
        record.importance = max(floor, decayed)

    def decay_all(self, records: Iterable[MemoryRecord], now: float | None = None) -> None:
        if now is None:
            now = time.time()
        for r in records:
            self.decay(r, now)

    def should_prune(self, record: MemoryRecord, threshold: float = 0.05) -> bool:
        """Returns True if the record importance is below threshold and not a landmark."""
        if record.is_landmark:
            return False
        return record.importance < threshold


# ---------------------------------------------------------------------------
# ImportanceScorer
# ---------------------------------------------------------------------------


class ImportanceScorer:
    """
    Ranks MemoryRecords by relevance to the current regime.

    Scoring formula (all components in [0, 1]):
        score = w_importance x importance
              + w_recency    x recency_score
              + w_regime     x regime_match
              + w_access     x access_score

    - recency_score  : exp(-lambda x age_seconds) with a 30-day half-life
    - regime_match   : 1.0 if record.regime_tag == current_regime else 0.0
    - access_score   : tanh(access_count / 10)  — rewards frequently accessed memories
    """

    _RECENCY_HALF_LIFE = 30 * 86_400  # 30 days

    def __init__(
        self,
        w_importance: float = 0.4,
        w_recency: float = 0.3,
        w_regime: float = 0.2,
        w_access: float = 0.1,
    ) -> None:
        total = w_importance + w_recency + w_regime + w_access
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        self._wi = w_importance
        self._wr = w_recency
        self._wg = w_regime
        self._wa = w_access
        self._recency_lambda = math.log(2) / self._RECENCY_HALF_LIFE

    def score(
        self,
        record: MemoryRecord,
        current_regime: str,
        now: float | None = None,
    ) -> float:
        if now is None:
            now = time.time()

        age = max(0.0, now - record.created_at)
        recency = math.exp(-self._recency_lambda * age)
        regime_match = 1.0 if record.regime_tag == current_regime else 0.0
        access = math.tanh(record.access_count / 10.0)

        return (
            self._wi * record.importance
            + self._wr * recency
            + self._wg * regime_match
            + self._wa * access
        )

    def rank(
        self,
        records: Iterable[MemoryRecord],
        current_regime: str,
        now: float | None = None,
        top_k: int | None = None,
    ) -> list[tuple[float, MemoryRecord]]:
        """Returns (score, record) pairs sorted descending by score."""
        if now is None:
            now = time.time()
        scored = [(self.score(r, current_regime, now), r) for r in records]
        scored.sort(key=lambda x: x[0], reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored


# ---------------------------------------------------------------------------
# ConsolidationPipeline
# ---------------------------------------------------------------------------


@dataclass
class ConsolidationResult:
    """Summary of a single consolidation run."""

    run_id: str
    timestamp: float
    short_term_before: int
    short_term_after: int
    long_term_before: int
    long_term_after: int
    pruned: int
    consolidated: int


class ConsolidationPipeline:
    """
    Periodically merges short-term memories into long-term storage.

    Short-term → long-term promotion criteria:
      1. Memory is older than `min_age_seconds`.
      2. Memory importance is above `promotion_threshold`.

    After promotion, memories in short-term that are below `prune_threshold`
    importance are pruned.

    The pipeline also manages a MemoryIndex, a DecayManager, and an
    ImportanceScorer so callers only need to interact with one object.
    """

    def __init__(
        self,
        min_age_seconds: float = 3_600,  # 1 hour before eligible for consolidation
        promotion_threshold: float = 0.3,
        prune_threshold: float = 0.05,
        consolidation_interval: float = 900,  # run every 15 minutes
        decay_half_life: float = 7 * 86_400,
        landmark_floor: float = 0.3,
    ) -> None:
        self._min_age = min_age_seconds
        self._promotion_threshold = promotion_threshold
        self._prune_threshold = prune_threshold
        self._interval = consolidation_interval

        self.index = MemoryIndex()
        self.decay_manager = DecayManager(
            half_life_seconds=decay_half_life,
            landmark_floor=landmark_floor,
        )
        self.scorer = ImportanceScorer()

        # short_term: unsettled / recently created
        self._short_term: dict[str, MemoryRecord] = {}
        # long_term: consolidated / stable
        self._long_term: dict[str, MemoryRecord] = {}

        self._last_consolidation: float = time.time()
        self._history: list[ConsolidationResult] = []

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def add(self, record: MemoryRecord) -> None:
        """Add a new memory to short-term storage and index it."""
        self._short_term[record.memory_id] = record
        self.index.add(record)
        logger.debug(
            "Added memory %s (regime=%s signal=%s importance=%.2f)",
            record.memory_id[:8],
            record.regime_tag,
            record.signal_type,
            record.importance,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, memory_id: str) -> MemoryRecord | None:
        record = self._short_term.get(memory_id) or self._long_term.get(memory_id)
        if record is not None:
            record.last_accessed = time.time()
            record.access_count += 1
        return record

    def query(
        self,
        regime_tag: str | None = None,
        signal_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        current_regime: str = "",
        top_k: int = 20,
    ) -> list[tuple[float, MemoryRecord]]:
        """Multi-criteria query returning top-k records by importance score."""
        candidate_ids: set[str] | None = None

        def _intersect(ids: set[str]) -> None:
            nonlocal candidate_ids
            if candidate_ids is None:
                candidate_ids = ids
            else:
                candidate_ids &= ids

        if regime_tag is not None:
            _intersect(self.index.by_regime(regime_tag))
        if signal_type is not None:
            _intersect(self.index.by_signal(signal_type))
        if start_time is not None and end_time is not None:
            _intersect(self.index.by_time_range(start_time, end_time))

        if candidate_ids is None:
            all_records: list[MemoryRecord] = list(self._short_term.values()) + list(
                self._long_term.values()
            )
        else:
            all_records = [r for mid in candidate_ids if (r := self.get(mid)) is not None]

        return self.scorer.rank(all_records, current_regime, top_k=top_k)

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------

    def maybe_consolidate(self, now: float | None = None) -> ConsolidationResult | None:
        """Run consolidation if the interval has elapsed; otherwise no-op."""
        if now is None:
            now = time.time()
        if now - self._last_consolidation < self._interval:
            return None
        return self.consolidate(now)

    def consolidate(self, now: float | None = None) -> ConsolidationResult:
        """Run a full consolidation cycle immediately."""
        if now is None:
            now = time.time()

        st_before = len(self._short_term)
        lt_before = len(self._long_term)

        # 1. Apply decay to all memories
        self.decay_manager.decay_all(self._short_term.values(), now)
        self.decay_manager.decay_all(self._long_term.values(), now)

        # 2. Promote eligible short-term memories to long-term
        consolidated = 0
        to_promote: list[str] = []
        for mid, record in self._short_term.items():
            age = now - record.created_at
            if age >= self._min_age and record.importance >= self._promotion_threshold:
                to_promote.append(mid)

        for mid in to_promote:
            record = self._short_term.pop(mid)
            record.consolidated = True
            self._long_term[mid] = record
            consolidated += 1

        # 3. Prune low-importance short-term memories
        pruned = 0
        to_prune: list[str] = []
        for mid, record in self._short_term.items():
            if self.decay_manager.should_prune(record, self._prune_threshold):
                to_prune.append(mid)

        for mid in to_prune:
            record = self._short_term.pop(mid)
            self.index.remove(record)
            pruned += 1

        self._last_consolidation = now
        result = ConsolidationResult(
            run_id=str(uuid.uuid4()),
            timestamp=now,
            short_term_before=st_before,
            short_term_after=len(self._short_term),
            long_term_before=lt_before,
            long_term_after=len(self._long_term),
            pruned=pruned,
            consolidated=consolidated,
        )
        self._history.append(result)
        logger.info(
            "Consolidation run %s: promoted=%d pruned=%d ST=%d LT=%d",
            result.run_id[:8],
            consolidated,
            pruned,
            result.short_term_after,
            result.long_term_after,
        )
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def short_term_size(self) -> int:
        return len(self._short_term)

    @property
    def long_term_size(self) -> int:
        return len(self._long_term)

    def last_consolidation_result(self) -> ConsolidationResult | None:
        return self._history[-1] if self._history else None

    def stats(self) -> dict[str, Any]:
        return {
            "short_term": self.short_term_size,
            "long_term": self.long_term_size,
            "consolidation_runs": len(self._history),
            "index": self.index.stats(),
        }
