"""
omega.core.memory_bus
~~~~~~~~~~~~~~~~~~~~~
Cross-project memory bus — shared insights between Victoria and Polymarket.

Victoria writes signal patterns and regime insights; Polymarket reads market
sentiment warnings to adjust edge confidence.

Memory types:
  SIGNAL_PATTERN  — recurring signal behaviours (e.g. "momentum + high funding → reversal")
  REGIME_INSIGHT  — market regime observations (e.g. "extreme fear underprices recovery")
  RISK_WARNING    — active risk alerts (e.g. "high leverage + low liquidity — reduce size")
  OPPORTUNITY     — detected opportunities (e.g. "VRP spike → long vol play in 24h")

Usage::
    bus = MemoryBus()

    # Victoria writes
    bus.write("victoria", MemoryType.REGIME_INSIGHT,
              "Extreme fear + high funding rate preceded a 5% reversal",
              relevance_score=0.9)

    # Polymarket reads
    insights = bus.read(memory_types=[MemoryType.REGIME_INSIGHT], min_relevance=0.5)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from enum import StrEnum
from typing import Any

logger = logging.getLogger("omega.core.memory_bus")


class MemoryType(StrEnum):
    SIGNAL_PATTERN = "SIGNAL_PATTERN"
    REGIME_INSIGHT = "REGIME_INSIGHT"
    RISK_WARNING = "RISK_WARNING"
    OPPORTUNITY = "OPPORTUNITY"


class MemoryBus:
    """
    Shared memory store that both Victoria and Polymarket can read/write.

    Backed by the ``shared_memory`` Postgres table (created by db.go bootstrap).
    Falls back to a no-op if DATABASE_URL is unset.
    """

    def __init__(self, dsn: str | None = None) -> None:
        import psycopg
        from psycopg.rows import dict_row

        _dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not _dsn:
            raise RuntimeError("MemoryBus: DATABASE_URL not set")
        self._conn = psycopg.connect(_dsn, row_factory=dict_row)
        logger.debug("MemoryBus connected")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(
        self,
        project_source: str,
        memory_type: MemoryType | str,
        content: str,
        relevance_score: float = 0.5,
        cycle: int = 0,
        ttl_seconds: float | None = None,
    ) -> str:
        """Write a memory to the shared bus. Returns the new memory id."""
        mem_id = str(uuid.uuid4())
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds else None
        mtype = memory_type.value if isinstance(memory_type, MemoryType) else str(memory_type)

        self._conn.execute(
            """
            INSERT INTO shared_memory
                (id, project_source, memory_type, content,
                 relevance_score, cycle, created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                mem_id,
                project_source,
                mtype,
                content,
                min(1.0, max(0.0, relevance_score)),
                cycle,
                now,
                expires_at,
            ),
        )
        self._conn.commit()
        logger.debug(
            "MemoryBus.write: [%s] from=%s rel=%.2f", mtype, project_source, relevance_score
        )
        return mem_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(
        self,
        memory_types: list[MemoryType | str] | None = None,
        project_source: str | None = None,
        exclude_source: str | None = None,
        min_relevance: float = 0.0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Read shared memories, ordered by relevance descending."""
        now = time.time()
        sql = (
            "SELECT * FROM shared_memory "
            "WHERE relevance_score >= %s "
            "AND (expires_at IS NULL OR expires_at > %s)"
        )
        params: list[Any] = [min_relevance, now]

        if memory_types:
            mtypes = [t.value if isinstance(t, MemoryType) else str(t) for t in memory_types]
            placeholders = ", ".join(["%s"] * len(mtypes))
            sql += f" AND memory_type IN ({placeholders})"
            params.extend(mtypes)
        if project_source:
            sql += " AND project_source = %s"
            params.append(project_source)
        if exclude_source:
            sql += " AND project_source != %s"
            params.append(exclude_source)

        sql += " ORDER BY relevance_score DESC, created_at DESC LIMIT %s"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune_expired(self) -> int:
        """Remove expired memories. Returns count deleted."""
        deleted = self._conn.execute(
            "DELETE FROM shared_memory WHERE expires_at IS NOT NULL AND expires_at < %s",
            (time.time(),),
        ).rowcount
        self._conn.commit()
        return deleted

    def summary(self) -> dict[str, Any]:
        """Return counts per memory_type."""
        rows = self._conn.execute(
            "SELECT memory_type, COUNT(*) as n FROM shared_memory GROUP BY memory_type"
        ).fetchall()
        return {r["memory_type"]: r["n"] for r in rows}
