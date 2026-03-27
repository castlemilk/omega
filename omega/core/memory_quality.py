"""
omega.core.memory_quality
~~~~~~~~~~~~~~~~~~~~~~~~~
Memory system health and quality assessment.

Queries existing Postgres tables (episodes, semantic_memories, shared_memory,
memory_ratings) to produce a dict of quality metrics for improvement decisions.

Usage::

    assessor = MemoryQualityAssessor(db_url=os.environ.get("DATABASE_URL"))
    metrics = assessor.assess()
    print(f"Episodes: {metrics['episode_count']}, Utilization: {metrics['memory_utilization']:.1%}")
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("omega.core.memory_quality")

_STALE_THRESHOLD_SECONDS = 86_400  # 24 hours


class MemoryQualityAssessor:
    """
    Assesses the health and effectiveness of the memory system.

    All metrics return 0 / 0.0 when no DB connection is available.
    """

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or os.environ.get("DATABASE_URL")
        self._conn: Any = None
        if self._db_url:
            try:
                import psycopg
                from psycopg.rows import dict_row

                self._conn = psycopg.connect(self._db_url, row_factory=dict_row)
                logger.debug("MemoryQualityAssessor connected to DB")
            except Exception as exc:
                logger.warning("MemoryQualityAssessor: DB connect failed: %s", exc)
                self._conn = None

    def assess(self) -> dict[str, Any]:
        """Compute and return all memory quality metrics."""
        return {
            "episode_count": self._count_episodes(),
            "semantic_count": self._count_semantic(),
            "shared_memory_count": self._count_shared(),
            "memory_ratings_count": self._count_ratings(),
            "avg_episode_rating": self._avg_rating(),
            "episode_diversity": self._episode_diversity(),
            "memory_utilization": self._memory_utilization(),
            "stale_memory_pct": self._stale_memory_pct(),
            "cross_project_ratio": self._cross_project_ratio(),
            "memory_influenced_trades": self._memory_influenced_trades(),
            "memory_win_rate": self._memory_win_rate(),
        }

    # ------------------------------------------------------------------
    # Count queries
    # ------------------------------------------------------------------

    def _count_episodes(self) -> int:
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()
            return int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug("_count_episodes failed: %s", exc)
            return 0

    def _count_semantic(self) -> int:
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM semantic_memories").fetchone()
            return int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug("_count_semantic failed: %s", exc)
            return 0

    def _count_shared(self) -> int:
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM shared_memory").fetchone()
            return int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug("_count_shared failed: %s", exc)
            return 0

    def _count_ratings(self) -> int:
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM memory_ratings").fetchone()
            return int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug("_count_ratings failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Quality metrics
    # ------------------------------------------------------------------

    def _avg_rating(self) -> float:
        if self._conn is None:
            return 0.0
        try:
            row = self._conn.execute("SELECT AVG(quality) AS avg FROM memory_ratings").fetchone()
            return float(row["avg"]) if row and row["avg"] is not None else 0.0
        except Exception as exc:
            logger.debug("_avg_rating failed: %s", exc)
            return 0.0

    def _episode_diversity(self) -> float:
        """Fraction of distinct event_types relative to 10 (normalised to [0, 1])."""
        if self._conn is None:
            return 0.0
        try:
            total_row = self._conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()
            total = int(total_row["n"]) if total_row else 0
            if total == 0:
                return 0.0
            distinct_row = self._conn.execute(
                "SELECT COUNT(DISTINCT event_type) AS n FROM episodes"
            ).fetchone()
            distinct = int(distinct_row["n"]) if distinct_row else 0
            return min(1.0, distinct / 10.0)
        except Exception as exc:
            logger.debug("_episode_diversity failed: %s", exc)
            return 0.0

    def _memory_utilization(self) -> float:
        """
        Approximated as total shared_memory_reads / total shared_memory_writes
        accumulated across all recorded intelligence_metrics cycles.
        """
        if self._conn is None:
            return 0.0
        try:
            row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(shared_memory_reads), 0)  AS reads,
                    COALESCE(SUM(shared_memory_writes), 0) AS writes
                FROM intelligence_metrics
                """
            ).fetchone()
            if row is None:
                return 0.0
            reads = int(row["reads"])
            writes = int(row["writes"])
            if writes == 0:
                return 0.0
            return min(1.0, reads / writes)
        except Exception as exc:
            logger.debug("_memory_utilization failed: %s", exc)
            return 0.0

    def _stale_memory_pct(self) -> float:
        """Fraction of shared_memory entries older than 24 hours."""
        if self._conn is None:
            return 0.0
        try:
            cutoff = time.time() - _STALE_THRESHOLD_SECONDS
            total_row = self._conn.execute("SELECT COUNT(*) AS n FROM shared_memory").fetchone()
            total = int(total_row["n"]) if total_row else 0
            if total == 0:
                return 0.0
            stale_row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM shared_memory WHERE created_at < %s",
                (cutoff,),
            ).fetchone()
            stale = int(stale_row["n"]) if stale_row else 0
            return stale / total
        except Exception as exc:
            logger.debug("_stale_memory_pct failed: %s", exc)
            return 0.0

    def _cross_project_ratio(self) -> float:
        """Fraction of shared_memory that comes from >1 distinct project source."""
        if self._conn is None:
            return 0.0
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT project_source) AS projects
                FROM shared_memory
                """
            ).fetchone()
            if row is None or int(row["total"]) == 0:
                return 0.0
            projects = int(row["projects"])
            return min(1.0, (projects - 1) / max(projects, 1))
        except Exception as exc:
            logger.debug("_cross_project_ratio failed: %s", exc)
            return 0.0

    def _memory_influenced_trades(self) -> int:
        """
        Proxy metric: total shared_memory reads across all cycles
        (each read is a potential influence on a downstream trade decision).
        """
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(shared_memory_reads), 0) AS n FROM intelligence_metrics"
            ).fetchone()
            return int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug("_memory_influenced_trades failed: %s", exc)
            return 0

    def _memory_win_rate(self) -> float:
        """
        Win rate of trades where memory was consulted vs not.

        Returns 0.0 — paper_trades lacks a memory_consulted column.
        Will become meaningful once that column is added.
        """
        return 0.0
