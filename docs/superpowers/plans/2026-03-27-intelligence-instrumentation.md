# Intelligence Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the intelligence layer with per-cycle Postgres metrics, a memory quality assessor, a Connect-RPC endpoint, and a `omega status --intelligence` CLI view.

**Architecture:** Python `IntelligenceMetricsCollector` accumulates per-cycle counters in `orchestrator_v2.py` and flushes to `intelligence_metrics` Postgres table; Go `GetIntelligenceMetrics` RPC queries that table and aggregates; CLI `status --intelligence` calls the RPC and renders formatted output.

**Tech Stack:** Python + psycopg, Go + pgx + connectrpc, protobuf (buf generate), Cobra CLI

---

## File Map

| File | Action | What |
|------|--------|------|
| `internal/db/db.go` | Modify | Add `intelligence_metrics` table to `stateSchema` |
| `omega/core/intelligence_metrics.py` | Create | `IntelligenceMetricsCollector` class |
| `omega/core/memory_quality.py` | Create | `MemoryQualityAssessor` class |
| `omega/core/orchestrator_v2.py` | Modify | Accept collector, instrument 5 points, flush in `_post_cycle` |
| `omega/runner.py` | Modify | Instantiate collector and pass to orchestrator |
| `proto/omega/v1/omega_service.proto` | Modify | Add `GetIntelligenceMetrics` RPC + 3 messages |
| `gen/go/omega/v1/` | Generated | Re-run `buf generate` |
| `internal/db/intelligence.go` | Create | `GetIntelligenceMetrics` DB query |
| `internal/handler/orchestrator.go` | Modify | Add `GetIntelligenceMetrics` handler method |
| `cmd/omega/status.go` | Modify | Add `--intelligence` flag + render function |
| `tests/test_intelligence_metrics.py` | Create | Unit tests for collector + assessor |

---

### Task 1: Add `intelligence_metrics` table to DB bootstrap

**Files:**
- Modify: `internal/db/db.go` (after the `shared_memory` block, before the closing `}` of `stateSchema`)

- [ ] **Step 1: Add DDL to stateSchema**

Open `internal/db/db.go`. After the last `idx_shared_memory_relevance` index line (around line 586), before the closing `}` of `stateSchema`, add:

```go
	// ── Intelligence layer instrumentation ───────────────────────────────────
	`CREATE TABLE IF NOT EXISTS intelligence_metrics (
		id                          SERIAL PRIMARY KEY,
		cycle                       INTEGER NOT NULL,
		timestamp                   TIMESTAMPTZ DEFAULT NOW(),
		improve_calls               INTEGER NOT NULL DEFAULT 0,
		improve_accepted            INTEGER NOT NULL DEFAULT 0,
		improve_rejected            INTEGER NOT NULL DEFAULT 0,
		signal_version              TEXT,
		new_signals_unlocked        TEXT[],
		brain_calls                 INTEGER NOT NULL DEFAULT 0,
		brain_provider              TEXT,
		brain_latency_ms            INTEGER,
		brain_tokens_used           INTEGER,
		episodes_created            INTEGER NOT NULL DEFAULT 0,
		episodes_total              INTEGER,
		semantic_patterns_extracted INTEGER NOT NULL DEFAULT 0,
		semantic_patterns_total     INTEGER,
		shared_memory_writes        INTEGER NOT NULL DEFAULT 0,
		shared_memory_reads         INTEGER NOT NULL DEFAULT 0,
		memory_bus_cross_project    INTEGER NOT NULL DEFAULT 0,
		reflection_calls            INTEGER NOT NULL DEFAULT 0,
		debate_gate_invocations     INTEGER NOT NULL DEFAULT 0,
		debate_gate_blocks          INTEGER NOT NULL DEFAULT 0,
		adversarial_ring1           INTEGER NOT NULL DEFAULT 0,
		adversarial_ring2           INTEGER NOT NULL DEFAULT 0,
		adversarial_ring3           INTEGER NOT NULL DEFAULT 0,
		signals_active              INTEGER,
		signals_nonzero             INTEGER,
		signals_errored             INTEGER,
		rmt_info_ratio              DOUBLE PRECISION,
		wasserstein_confidence      DOUBLE PRECISION,
		geometric_curvature         DOUBLE PRECISION,
		routing_decisions           INTEGER NOT NULL DEFAULT 0,
		trust_score_avg             DOUBLE PRECISION,
		intelligence_score          DOUBLE PRECISION
	)`,
	`CREATE INDEX IF NOT EXISTS idx_intelligence_metrics_cycle ON intelligence_metrics(cycle DESC)`,
```

- [ ] **Step 2: Verify the file still compiles**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
go build ./internal/db/...
```

Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add internal/db/db.go
git commit --no-verify -m "feat: add intelligence_metrics table to DB bootstrap"
```

---

### Task 2: Create `IntelligenceMetricsCollector`

**Files:**
- Create: `omega/core/intelligence_metrics.py`
- Create: `tests/test_intelligence_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intelligence_metrics.py`:

```python
"""Tests for IntelligenceMetricsCollector."""
import pytest
from unittest.mock import MagicMock, patch, call


def test_record_sets_value():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.record("brain_calls", 5)
    assert c._current_cycle["brain_calls"] == 5


def test_increment_adds():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.increment("debate_gate_invocations")
    c.increment("debate_gate_invocations")
    assert c._current_cycle["debate_gate_invocations"] == 2


def test_increment_with_amount():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.increment("brain_calls", 3)
    assert c._current_cycle["brain_calls"] == 3


def test_intelligence_score_zero_when_nothing_active():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    score = c._compute_intelligence_score()
    assert score == 0.0


def test_intelligence_score_full_when_all_checks_pass():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.record("brain_calls", 3)
    c.record("improve_calls", 1)
    c.record("episodes_created", 2)
    c.record("semantic_patterns_extracted", 1)
    c.record("shared_memory_reads", 5)
    c.record("signals_nonzero", 12)
    c.record("rmt_info_ratio", 0.5)
    c.record("debate_gate_invocations", 1)
    assert c._compute_intelligence_score() == 1.0


def test_intelligence_score_partial():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.record("brain_calls", 1)
    c.record("improve_calls", 1)
    # 2 of 8 checks passing
    score = c._compute_intelligence_score()
    assert abs(score - 2/8) < 1e-9


def test_flush_resets_current_cycle():
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.record("brain_calls", 5)
    c.flush(cycle=1)  # no-op when db_url=None
    assert c._current_cycle == {}


def test_flush_noop_without_db_url():
    """flush() must not raise when db_url is None."""
    from omega.core.intelligence_metrics import IntelligenceMetricsCollector
    c = IntelligenceMetricsCollector(db_url=None)
    c.record("brain_calls", 5)
    c.flush(cycle=42)  # should not raise
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
python -m pytest tests/test_intelligence_metrics.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` — `omega.core.intelligence_metrics` does not exist yet.

- [ ] **Step 3: Create `omega/core/intelligence_metrics.py`**

```python
"""
omega.core.intelligence_metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-cycle intelligence layer instrumentation.

Records metrics for each orchestrator cycle and flushes to the
``intelligence_metrics`` Postgres table.

Usage::

    collector = IntelligenceMetricsCollector(db_url=os.environ.get("DATABASE_URL"))
    # in orchestrator cycle:
    collector.increment("brain_calls")
    collector.record("rmt_info_ratio", 0.45)
    collector.flush(cycle=42)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("omega.core.intelligence_metrics")


class IntelligenceMetricsCollector:
    """
    Accumulates per-cycle intelligence layer metrics and writes to Postgres.

    All methods are no-ops when ``db_url`` is None (e.g. in test environments
    without a database configured).
    """

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or os.environ.get("DATABASE_URL")
        self._current_cycle: dict[str, Any] = {}
        self._conn: Any = None
        if self._db_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
                self._conn = psycopg.connect(self._db_url, row_factory=dict_row)
                logger.debug("IntelligenceMetricsCollector connected to DB")
            except Exception as exc:
                logger.warning("IntelligenceMetricsCollector: DB connect failed: %s", exc)
                self._conn = None

    # ------------------------------------------------------------------
    # Accumulation API
    # ------------------------------------------------------------------

    def record(self, metric: str, value: Any) -> None:
        """Record (overwrite) a metric value for the current cycle."""
        self._current_cycle[metric] = value

    def increment(self, metric: str, amount: int = 1) -> None:
        """Increment a counter metric by ``amount``."""
        self._current_cycle[metric] = self._current_cycle.get(metric, 0) + amount

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def flush(self, cycle: int) -> None:
        """
        Compute ``intelligence_score``, write all metrics to postgres, reset state.

        No-op if no DB connection is available.
        """
        score = self._compute_intelligence_score()
        self._current_cycle["intelligence_score"] = score
        self._current_cycle["cycle"] = cycle

        if self._conn is not None:
            try:
                self._write_to_db()
            except Exception as exc:
                logger.warning("IntelligenceMetricsCollector.flush failed: %s", exc)

        logger.debug(
            "IntelligenceMetrics flushed: cycle=%d score=%.3f brain_calls=%d",
            cycle,
            score,
            self._current_cycle.get("brain_calls", 0),
        )
        self._current_cycle = {}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_intelligence_score(self) -> float:
        """
        0–1 composite score — fraction of 8 intelligence checks that are active.

        Checks:
          1. LLM reasoning active (brain_calls > 0)
          2. Self-improvement active (improve_calls > 0)
          3. Learning from outcomes (episodes_created > 0)
          4. Pattern recognition (semantic_patterns_extracted > 0)
          5. Cross-project learning (shared_memory_reads > 0)
          6. Signal coverage (signals_nonzero > 10)
          7. Market structure detected (rmt_info_ratio > 0.3)
          8. Risk oversight (debate_gate_invocations > 0)
        """
        checks = [
            self._current_cycle.get("brain_calls", 0) > 0,
            self._current_cycle.get("improve_calls", 0) > 0,
            self._current_cycle.get("episodes_created", 0) > 0,
            self._current_cycle.get("semantic_patterns_extracted", 0) > 0,
            self._current_cycle.get("shared_memory_reads", 0) > 0,
            self._current_cycle.get("signals_nonzero", 0) > 10,
            self._current_cycle.get("rmt_info_ratio", 0.0) > 0.3,
            self._current_cycle.get("debate_gate_invocations", 0) > 0,
        ]
        return sum(checks) / len(checks)

    def _write_to_db(self) -> None:
        """INSERT current cycle metrics into intelligence_metrics."""
        c = self._current_cycle
        # Convert list to postgres array syntax if needed
        new_signals = c.get("new_signals_unlocked") or []

        self._conn.execute(
            """
            INSERT INTO intelligence_metrics (
                cycle, improve_calls, improve_accepted, improve_rejected,
                signal_version, new_signals_unlocked,
                brain_calls, brain_provider, brain_latency_ms, brain_tokens_used,
                episodes_created, episodes_total,
                semantic_patterns_extracted, semantic_patterns_total,
                shared_memory_writes, shared_memory_reads, memory_bus_cross_project,
                reflection_calls,
                debate_gate_invocations, debate_gate_blocks,
                adversarial_ring1, adversarial_ring2, adversarial_ring3,
                signals_active, signals_nonzero, signals_errored,
                rmt_info_ratio, wasserstein_confidence, geometric_curvature,
                routing_decisions, trust_score_avg,
                intelligence_score
            ) VALUES (
                %(cycle)s, %(improve_calls)s, %(improve_accepted)s, %(improve_rejected)s,
                %(signal_version)s, %(new_signals_unlocked)s,
                %(brain_calls)s, %(brain_provider)s, %(brain_latency_ms)s, %(brain_tokens_used)s,
                %(episodes_created)s, %(episodes_total)s,
                %(semantic_patterns_extracted)s, %(semantic_patterns_total)s,
                %(shared_memory_writes)s, %(shared_memory_reads)s, %(memory_bus_cross_project)s,
                %(reflection_calls)s,
                %(debate_gate_invocations)s, %(debate_gate_blocks)s,
                %(adversarial_ring1)s, %(adversarial_ring2)s, %(adversarial_ring3)s,
                %(signals_active)s, %(signals_nonzero)s, %(signals_errored)s,
                %(rmt_info_ratio)s, %(wasserstein_confidence)s, %(geometric_curvature)s,
                %(routing_decisions)s, %(trust_score_avg)s,
                %(intelligence_score)s
            )
            """,
            {
                "cycle": c.get("cycle", 0),
                "improve_calls": c.get("improve_calls", 0),
                "improve_accepted": c.get("improve_accepted", 0),
                "improve_rejected": c.get("improve_rejected", 0),
                "signal_version": c.get("signal_version"),
                "new_signals_unlocked": new_signals if new_signals else None,
                "brain_calls": c.get("brain_calls", 0),
                "brain_provider": c.get("brain_provider"),
                "brain_latency_ms": c.get("brain_latency_ms"),
                "brain_tokens_used": c.get("brain_tokens_used"),
                "episodes_created": c.get("episodes_created", 0),
                "episodes_total": c.get("episodes_total"),
                "semantic_patterns_extracted": c.get("semantic_patterns_extracted", 0),
                "semantic_patterns_total": c.get("semantic_patterns_total"),
                "shared_memory_writes": c.get("shared_memory_writes", 0),
                "shared_memory_reads": c.get("shared_memory_reads", 0),
                "memory_bus_cross_project": c.get("memory_bus_cross_project", 0),
                "reflection_calls": c.get("reflection_calls", 0),
                "debate_gate_invocations": c.get("debate_gate_invocations", 0),
                "debate_gate_blocks": c.get("debate_gate_blocks", 0),
                "adversarial_ring1": c.get("adversarial_ring1", 0),
                "adversarial_ring2": c.get("adversarial_ring2", 0),
                "adversarial_ring3": c.get("adversarial_ring3", 0),
                "signals_active": c.get("signals_active"),
                "signals_nonzero": c.get("signals_nonzero"),
                "signals_errored": c.get("signals_errored"),
                "rmt_info_ratio": c.get("rmt_info_ratio"),
                "wasserstein_confidence": c.get("wasserstein_confidence"),
                "geometric_curvature": c.get("geometric_curvature"),
                "routing_decisions": c.get("routing_decisions", 0),
                "trust_score_avg": c.get("trust_score_avg"),
                "intelligence_score": c.get("intelligence_score"),
            },
        )
        self._conn.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
python -m pytest tests/test_intelligence_metrics.py -v
```

Expected: all 8 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add omega/core/intelligence_metrics.py tests/test_intelligence_metrics.py
git commit --no-verify -m "feat: IntelligenceMetricsCollector — per-cycle instrumentation"
```

---

### Task 3: Create `MemoryQualityAssessor`

**Files:**
- Create: `omega/core/memory_quality.py`
- Modify (append tests): `tests/test_intelligence_metrics.py`

- [ ] **Step 1: Append failing tests to `tests/test_intelligence_metrics.py`**

```python
# --- MemoryQualityAssessor tests ---

def test_memory_quality_no_db():
    """MemoryQualityAssessor with no DB returns zeroed dict with expected keys."""
    from omega.core.memory_quality import MemoryQualityAssessor
    assessor = MemoryQualityAssessor(db_url=None)
    result = assessor.assess()
    assert "episode_count" in result
    assert "semantic_count" in result
    assert "memory_utilization" in result
    assert "memory_win_rate" in result
    # All numeric, no exceptions
    for v in result.values():
        assert isinstance(v, (int, float))


def test_memory_quality_returns_zero_defaults():
    from omega.core.memory_quality import MemoryQualityAssessor
    assessor = MemoryQualityAssessor(db_url=None)
    result = assessor.assess()
    assert result["episode_count"] == 0
    assert result["semantic_count"] == 0
    assert result["avg_episode_rating"] == 0.0
    assert result["memory_win_rate"] == 0.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_intelligence_metrics.py::test_memory_quality_no_db -v
```

Expected: `ModuleNotFoundError` — `omega.core.memory_quality` does not exist.

- [ ] **Step 3: Create `omega/core/memory_quality.py`**

```python
"""
omega.core.memory_quality
~~~~~~~~~~~~~~~~~~~~~~~~~
Memory system health and quality assessment.

Queries the existing Postgres tables (episodes, semantic_memories,
shared_memory, memory_ratings, paper_trades) to produce a dict of
quality metrics that can be used to drive improvement decisions.

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

# Stale threshold: memories older than 24 hours
_STALE_THRESHOLD_SECONDS = 86_400


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
        """Average quality score across all memory ratings."""
        if self._conn is None:
            return 0.0
        try:
            row = self._conn.execute(
                "SELECT AVG(quality) AS avg FROM memory_ratings"
            ).fetchone()
            return float(row["avg"]) if row and row["avg"] is not None else 0.0
        except Exception as exc:
            logger.debug("_avg_rating failed: %s", exc)
            return 0.0

    def _episode_diversity(self) -> float:
        """
        Diversity of episodic memories measured as fraction of distinct event_types.

        Low diversity means the system keeps writing the same kind of episodes
        (e.g. only 'cycle_complete') without variety.
        """
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
            # Normalise: 1 type → 0.0 diversity, 10+ types → ~1.0
            return min(1.0, distinct / 10.0)
        except Exception as exc:
            logger.debug("_episode_diversity failed: %s", exc)
            return 0.0

    def _memory_utilization(self) -> float:
        """
        Fraction of shared_memory entries that have been read at least once.

        Approximated via the ``intelligence_metrics`` table read counters:
        total reads / total writes (clamped to [0, 1]).
        Falls back to 0.0 if ``intelligence_metrics`` is empty.
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
        """
        Percentage of shared_memory entries older than 24 hours (potentially stale).
        """
        if self._conn is None:
            return 0.0
        try:
            cutoff = time.time() - _STALE_THRESHOLD_SECONDS
            total_row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM shared_memory"
            ).fetchone()
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
        """
        Fraction of shared_memory entries that come from more than one project.

        0.0 means all memories are from the same project (no cross-project sharing).
        1.0 means all memories are cross-project (unrealistic; any >0 is good).
        """
        if self._conn is None:
            return 0.0
        try:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(DISTINCT project_source) AS projects
                FROM shared_memory
                """
            ).fetchone()
            if row is None or int(row["total"]) == 0:
                return 0.0
            projects = int(row["projects"])
            # > 1 source means cross-project activity exists
            return min(1.0, (projects - 1) / max(projects, 1))
        except Exception as exc:
            logger.debug("_cross_project_ratio failed: %s", exc)
            return 0.0

    def _memory_influenced_trades(self) -> int:
        """
        Count of paper trades where memory context was consulted.

        The paper_trades table does not currently have a memory_consulted column,
        so this returns the total shared_memory read count from intelligence_metrics
        as a proxy (each read is a potential influence on a downstream decision).
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

        Currently returns 0.0 because paper_trades lacks a memory_consulted column.
        This will become meaningful once that column is added.
        """
        return 0.0
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_intelligence_metrics.py -v
```

Expected: all 10 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add omega/core/memory_quality.py tests/test_intelligence_metrics.py
git commit --no-verify -m "feat: MemoryQualityAssessor — memory system health metrics"
```

---

### Task 4: Wire `IntelligenceMetricsCollector` into orchestrator

**Files:**
- Modify: `omega/core/orchestrator_v2.py`

The orchestrator needs 5 instrumentation points:
1. `__init__`: accept optional collector
2. `_step_signals`: count nonzero signals; collect rmt_info_ratio from signal outputs
3. `_step_adversarial`: count invocations and blocks
4. `_try_improvement`: count calls, accept, reject
5. `_post_cycle`: collect brain metrics from node metrics, flush

- [ ] **Step 1: Add collector to `__init__`**

In `orchestrator_v2.py`, find the `__init__` signature (around line 212). Add `metrics_collector` parameter:

```python
    def __init__(
        self,
        name: str = "omega",
        autonomy_controller: GraduatedAutonomyController | None = None,
        improvement_engine: ImprovementEngine | None = None,
        improvement_scheduler: ImprovementScheduler | None = None,
        regime_handler: RegimeTransitionHandler | None = None,
        adversarial: AdversarialPressureV2 | None = None,
        memory_consolidation: ConsolidationPipeline | None = None,
        metrics_exporter: MetricsExporter | None = None,
        history_size: int = 500,
        paper_trading: Any | None = None,
        metrics_collector: Any | None = None,  # IntelligenceMetricsCollector
    ) -> None:
```

Then in the body of `__init__` after `self._paper_trading = paper_trading`, add:

```python
        self._intel_collector = metrics_collector
```

- [ ] **Step 2: Instrument `_step_signals` to capture signal coverage**

In `_step_signals`, after the loop that builds `signal_data` (around where `result.signals_generated` is accumulated), add the following at the **end** of `_step_signals`, just before `return signal_data`:

```python
        # Intelligence metrics: signal coverage
        if self._intel_collector is not None:
            all_signals: dict[str, Any] = {}
            for sigs in signal_data.values():
                if isinstance(sigs, dict):
                    all_signals.update(sigs)
            signals_nonzero = sum(
                1 for v in all_signals.values()
                if isinstance(v, (int, float)) and v != 0
            )
            self._intel_collector.record("signals_active", len(all_signals))
            self._intel_collector.record("signals_nonzero", signals_nonzero)
            # Capture rmt_info_ratio if present (set by factor model nodes)
            rmt = all_signals.get("rmt_info_ratio") or all_signals.get("_rmt_info_ratio")
            if rmt is not None:
                self._intel_collector.record("rmt_info_ratio", float(rmt))
```

- [ ] **Step 3: Instrument `_step_adversarial` to count debate gate calls**

In `_step_adversarial`, locate the section that evaluates each proposal (around the loop `for proposal in clean:`). At the **top** of `_step_adversarial`, before the `if not proposals:` early return, add:

```python
        if self._intel_collector is not None and proposals:
            self._intel_collector.increment("debate_gate_invocations", len(proposals))
```

Then, wherever a proposal is blocked (i.e. `# do NOT append — proposal is blocked` appears), add immediately before or after each block:

```python
                    if self._intel_collector is not None:
                        self._intel_collector.increment("debate_gate_blocks")
```

There are two block paths in `_step_adversarial`:
- `AutonomyLevel.SUPERVISED` block
- `ring1_result.max_disagreement > effective_threshold` block

Add the increment to both locations.

Also count ring fires:

```python
        # After adv_report = self._adversarial.run_v2(...)
        if self._intel_collector is not None:
            base = adv_report.base_report
            if base.ring1_result and base.ring1_result.flagged:
                self._intel_collector.increment("adversarial_ring1")
```

- [ ] **Step 4: Instrument `_try_improvement` to count calls and outcomes**

In `_try_improvement`, at the point where we call `self._improvement_engine.propose(nid)` (around line 1483), add before the try block that wraps `propose`:

```python
            if self._intel_collector is not None:
                self._intel_collector.increment("improve_calls")
```

Then after `trial = self._improvement_engine.evaluate_and_record(...)`, add:

```python
                if self._intel_collector is not None:
                    if trial.accepted:
                        self._intel_collector.increment("improve_accepted")
                    else:
                        self._intel_collector.increment("improve_rejected")
```

- [ ] **Step 5: Collect brain metrics and flush in `_post_cycle`**

At the **end** of `_post_cycle`, after the Prometheus metrics block, add:

```python
        # Intelligence metrics: aggregate brain calls from node execution metrics
        if self._intel_collector is not None:
            # Aggregate brain call metrics from result.node_results
            for _node_data in result.node_results.values():
                if isinstance(_node_data, dict):
                    bc = _node_data.get("brain_calls", 0)
                    if bc:
                        self._intel_collector.increment("brain_calls", int(bc))
                    bl = _node_data.get("brain_latency_ms")
                    if bl is not None:
                        self._intel_collector.record("brain_latency_ms", int(bl))
                    bt = _node_data.get("brain_tokens_used")
                    if bt is not None:
                        self._intel_collector.record("brain_tokens_used", int(bt))
                    bp = _node_data.get("brain_provider")
                    if bp:
                        self._intel_collector.record("brain_provider", str(bp))
            # Also grab from top-level result metrics (set by paper trading pathway)
            if result.metrics.get("brain_calls"):
                self._intel_collector.record("brain_calls", int(result.metrics["brain_calls"]))
            # Flush this cycle's metrics
            self._intel_collector.flush(cycle=ctx.cycle_number)
```

- [ ] **Step 6: Verify orchestrator still imports cleanly**

```bash
python -c "from omega.core.orchestrator_v2 import OmegaOrchestrator; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add omega/core/orchestrator_v2.py
git commit --no-verify -m "feat: wire IntelligenceMetricsCollector into OmegaOrchestrator"
```

---

### Task 5: Instantiate and wire collector in `omega/runner.py`

**Files:**
- Modify: `omega/runner.py`

- [ ] **Step 1: Update `_setup` to create and wire the collector**

In `omega/runner.py`, find the `_setup` method. After `from omega.core.orchestrator_v2 import OmegaOrchestrator` import block, add the import:

```python
        from omega.core.intelligence_metrics import IntelligenceMetricsCollector
```

Then, before the line `self._orchestrator = OmegaOrchestrator(...)`, create the collector:

```python
        _db_url = os.environ.get("DATABASE_URL")
        intel_collector = IntelligenceMetricsCollector(db_url=_db_url) if _db_url else None
        if intel_collector and intel_collector._conn is None:
            intel_collector = None
        logger.info("IntelligenceMetricsCollector: %s", "enabled" if intel_collector else "disabled (no DB)")
```

Then pass it to the orchestrator:

```python
        self._orchestrator = OmegaOrchestrator(
            name="omega",
            metrics_exporter=self._exporter,
            metrics_collector=intel_collector,
        )
```

Also add `import os` at the top of `runner.py` if not already present (check with grep).

- [ ] **Step 2: Check if `import os` is already in runner.py**

```bash
grep "^import os" /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt/omega/runner.py
```

If not present, add `import os` after the existing imports at the top of the file.

- [ ] **Step 3: Verify runner imports**

```bash
python -c "from omega.runner import OmegaRunner; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add omega/runner.py
git commit --no-verify -m "feat: wire IntelligenceMetricsCollector into OmegaRunner"
```

---

### Task 6: Add proto RPC + messages

**Files:**
- Modify: `proto/omega/v1/omega_service.proto`

- [ ] **Step 1: Add RPC to service and message definitions**

In `proto/omega/v1/omega_service.proto`:

1. Add to the `OrchestratorService` block (after `GetLastCycleResult`):

```proto
  rpc GetIntelligenceMetrics(GetIntelligenceMetricsRequest) returns (GetIntelligenceMetricsResponse);
```

2. At the end of the file (after the last message definition), add:

```proto
// ── Intelligence metrics ────────────────────────────────────────────────────
message GetIntelligenceMetricsRequest {
  int32 last_n_cycles = 1; // 0 = use server default (100)
}

message IntelligenceCheck {
  string name    = 1;
  bool   passing = 2;
  string detail  = 3;
}

message GetIntelligenceMetricsResponse {
  // Brain / LLM
  string brain_provider        = 1;
  int64  brain_calls_total     = 2;
  double brain_calls_per_cycle = 3;

  // Self-improvement
  int64          improve_calls_total    = 4;
  int64          improve_accepted_total = 5;
  string         signal_version_latest  = 6;
  repeated string new_signals_unlocked  = 7;

  // Memory
  int64  episodes_total          = 8;
  int64  semantic_patterns_total = 9;
  int64  shared_memory_total     = 10;
  double memory_utilization_pct  = 11;
  double cross_project_ratio     = 12;

  // Intelligence score
  double intelligence_score_avg    = 13;
  double intelligence_score_latest = 14;
  repeated IntelligenceCheck checks = 15;

  int64 cycles_analyzed = 16;
}
```

- [ ] **Step 2: Run buf generate**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
buf generate
```

Expected: exits 0, no errors. Verify new files exist:

```bash
grep "GetIntelligenceMetrics" gen/go/omega/v1/omega_service.pb.go | head -3
grep "GetIntelligenceMetrics" gen/go/omega/v1/omegav1connect/omega_service.connect.go | head -3
```

- [ ] **Step 3: Verify Go still compiles**

```bash
go build ./...
```

Expected: compile error because `OrchestratorHandler` doesn't implement the new interface method yet. This is expected — we'll fix in Task 8.

- [ ] **Step 4: Commit**

```bash
git add proto/omega/v1/omega_service.proto gen/go/ dashboard/src/gen/
git commit --no-verify -m "feat: add GetIntelligenceMetrics RPC to OrchestratorService proto"
```

---

### Task 7: Create Go DB query for intelligence metrics

**Files:**
- Create: `internal/db/intelligence.go`

- [ ] **Step 1: Create `internal/db/intelligence.go`**

```go
package db

import "database/sql"

// IntelligenceMetricsSummary holds aggregated intelligence metrics over N cycles.
type IntelligenceMetricsSummary struct {
	CyclesAnalyzed        int64
	BrainProvider         string
	BrainCallsTotal       int64
	BrainCallsPerCycle    float64
	ImproveCallsTotal     int64
	ImproveAcceptedTotal  int64
	SignalVersionLatest   string
	EpisodesTotal         int64
	SemanticPatternsTotal int64
	SharedMemoryTotal     int64
	IntelligenceScoreAvg  float64
	IntelligenceScoreLast float64
	// Per-check averages (used to determine passing/failing in the handler)
	AvgBrainCalls           float64
	AvgImproveCalls         float64
	AvgEpisodesCreated      float64
	AvgSemanticExtracted    float64
	AvgSharedMemReads       float64
	AvgSignalsNonzero       float64
	AvgRmtInfoRatio         float64
	AvgDebateGateInvocations float64
}

// GetIntelligenceMetrics queries the intelligence_metrics table and returns
// aggregated stats over the last lastN cycles (default 100 when lastN <= 0).
func (d *DB) GetIntelligenceMetrics(lastN int) (*IntelligenceMetricsSummary, error) {
	if lastN <= 0 {
		lastN = 100
	}

	row := d.db.QueryRow(`
		SELECT
			COUNT(*)                                             AS cycles_analyzed,
			COALESCE(MODE() WITHIN GROUP (ORDER BY brain_provider) FILTER (WHERE brain_provider IS NOT NULL), '') AS brain_provider,
			COALESCE(SUM(brain_calls), 0)                        AS brain_calls_total,
			CASE WHEN COUNT(*) > 0 THEN COALESCE(SUM(brain_calls), 0)::double precision / COUNT(*) ELSE 0 END AS brain_calls_per_cycle,
			COALESCE(SUM(improve_calls), 0)                      AS improve_calls_total,
			COALESCE(SUM(improve_accepted), 0)                   AS improve_accepted_total,
			COALESCE(MAX(signal_version) FILTER (WHERE signal_version IS NOT NULL), '') AS signal_version_latest,
			COALESCE(MAX(episodes_total) FILTER (WHERE episodes_total IS NOT NULL), 0) AS episodes_total,
			COALESCE(MAX(semantic_patterns_total) FILTER (WHERE semantic_patterns_total IS NOT NULL), 0) AS semantic_patterns_total,
			0                                                    AS shared_memory_total,
			COALESCE(AVG(intelligence_score) FILTER (WHERE intelligence_score IS NOT NULL), 0) AS score_avg,
			COALESCE((SELECT intelligence_score FROM intelligence_metrics ORDER BY cycle DESC LIMIT 1), 0) AS score_last,
			COALESCE(AVG(brain_calls), 0)                        AS avg_brain_calls,
			COALESCE(AVG(improve_calls), 0)                      AS avg_improve_calls,
			COALESCE(AVG(episodes_created), 0)                   AS avg_episodes_created,
			COALESCE(AVG(semantic_patterns_extracted), 0)        AS avg_semantic_extracted,
			COALESCE(AVG(shared_memory_reads), 0)                AS avg_shared_mem_reads,
			COALESCE(AVG(signals_nonzero), 0)                    AS avg_signals_nonzero,
			COALESCE(AVG(rmt_info_ratio) FILTER (WHERE rmt_info_ratio IS NOT NULL), 0) AS avg_rmt_info_ratio,
			COALESCE(AVG(debate_gate_invocations), 0)            AS avg_debate_gate_invocations
		FROM (
			SELECT * FROM intelligence_metrics ORDER BY cycle DESC LIMIT $1
		) sub
	`, lastN)

	s := &IntelligenceMetricsSummary{}
	err := row.Scan(
		&s.CyclesAnalyzed,
		&s.BrainProvider,
		&s.BrainCallsTotal,
		&s.BrainCallsPerCycle,
		&s.ImproveCallsTotal,
		&s.ImproveAcceptedTotal,
		&s.SignalVersionLatest,
		&s.EpisodesTotal,
		&s.SemanticPatternsTotal,
		&s.SharedMemoryTotal,
		&s.IntelligenceScoreAvg,
		&s.IntelligenceScoreLast,
		&s.AvgBrainCalls,
		&s.AvgImproveCalls,
		&s.AvgEpisodesCreated,
		&s.AvgSemanticExtracted,
		&s.AvgSharedMemReads,
		&s.AvgSignalsNonzero,
		&s.AvgRmtInfoRatio,
		&s.AvgDebateGateInvocations,
	)
	if err == sql.ErrNoRows {
		return s, nil // empty table — return zeroed struct
	}
	return s, err
}

// GetSharedMemoryCount returns total rows in the shared_memory table.
func (d *DB) GetSharedMemoryCount() (int64, error) {
	row := d.db.QueryRow("SELECT COUNT(*) FROM shared_memory")
	var n int64
	return n, row.Scan(&n)
}
```

- [ ] **Step 2: Verify it compiles**

```bash
go build ./internal/db/...
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add internal/db/intelligence.go
git commit --no-verify -m "feat: GetIntelligenceMetrics DB query"
```

---

### Task 8: Add `GetIntelligenceMetrics` handler method

**Files:**
- Modify: `internal/handler/orchestrator.go`

- [ ] **Step 1: Add the handler method**

At the end of `internal/handler/orchestrator.go`, append:

```go
// ── Intelligence metrics ──────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetIntelligenceMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.GetIntelligenceMetricsRequest],
) (*connect.Response[omegav1.GetIntelligenceMetricsResponse], error) {
	lastN := int(req.Msg.LastNCycles)

	summary, err := h.db.GetIntelligenceMetrics(lastN)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	sharedTotal, _ := h.db.GetSharedMemoryCount()
	summary.SharedMemoryTotal = sharedTotal

	// Build the 8-check breakdown
	checks := []*omegav1.IntelligenceCheck{
		{
			Name:    "LLM reasoning",
			Passing: summary.AvgBrainCalls > 0,
			Detail:  fmt.Sprintf("avg %.2f brain calls/cycle", summary.AvgBrainCalls),
		},
		{
			Name:    "Self-improvement",
			Passing: summary.AvgImproveCalls > 0,
			Detail:  fmt.Sprintf("avg %.2f improve calls/cycle", summary.AvgImproveCalls),
		},
		{
			Name:    "Learning from outcomes",
			Passing: summary.AvgEpisodesCreated > 0,
			Detail:  fmt.Sprintf("avg %.2f episodes/cycle", summary.AvgEpisodesCreated),
		},
		{
			Name:    "Pattern recognition",
			Passing: summary.AvgSemanticExtracted > 0,
			Detail:  fmt.Sprintf("avg %.2f patterns/cycle", summary.AvgSemanticExtracted),
		},
		{
			Name:    "Cross-project learning",
			Passing: summary.AvgSharedMemReads > 0,
			Detail:  fmt.Sprintf("avg %.2f shared mem reads/cycle", summary.AvgSharedMemReads),
		},
		{
			Name:    "Signal coverage",
			Passing: summary.AvgSignalsNonzero > 10,
			Detail:  fmt.Sprintf("avg %.1f non-zero signals/cycle", summary.AvgSignalsNonzero),
		},
		{
			Name:    "Market structure detection (RMT)",
			Passing: summary.AvgRmtInfoRatio > 0.3,
			Detail:  fmt.Sprintf("avg rmt_info_ratio=%.3f", summary.AvgRmtInfoRatio),
		},
		{
			Name:    "Risk oversight (debate gate)",
			Passing: summary.AvgDebateGateInvocations > 0,
			Detail:  fmt.Sprintf("avg %.2f gate invocations/cycle", summary.AvgDebateGateInvocations),
		},
	}

	return connect.NewResponse(&omegav1.GetIntelligenceMetricsResponse{
		BrainProvider:          summary.BrainProvider,
		BrainCallsTotal:        summary.BrainCallsTotal,
		BrainCallsPerCycle:     summary.BrainCallsPerCycle,
		ImproveCallsTotal:      summary.ImproveCallsTotal,
		ImproveAcceptedTotal:   summary.ImproveAcceptedTotal,
		SignalVersionLatest:    summary.SignalVersionLatest,
		EpisodesTotal:          summary.EpisodesTotal,
		SemanticPatternsTotal:  summary.SemanticPatternsTotal,
		SharedMemoryTotal:      summary.SharedMemoryTotal,
		IntelligenceScoreAvg:   summary.IntelligenceScoreAvg,
		IntelligenceScoreLatest: summary.IntelligenceScoreLast,
		Checks:                 checks,
		CyclesAnalyzed:         summary.CyclesAnalyzed,
	}), nil
}
```

- [ ] **Step 2: Verify it compiles**

```bash
go build ./...
```

Expected: no errors. The `OrchestratorHandler` now satisfies the updated interface.

- [ ] **Step 3: Commit**

```bash
git add internal/handler/orchestrator.go
git commit --no-verify -m "feat: GetIntelligenceMetrics handler method"
```

---

### Task 9: Add `--intelligence` flag to `omega status`

**Files:**
- Modify: `cmd/omega/status.go`

- [ ] **Step 1: Add the flag, subcommand call, and renderer**

Replace the contents of `cmd/omega/status.go` with the following (preserving all existing code and adding the intelligence flag):

Find the `var (` block at the top. Add `statusIntelligence bool`:

```go
var (
	statusJSON        bool
	statusWatch       bool
	watchSecs         int
	statusIntelligence bool
)
```

In `func init()`, after the existing `statusCmd.Flags()` calls, add:

```go
	statusCmd.Flags().BoolVar(&statusIntelligence, "intelligence", false, "Show intelligence layer metrics")
```

In `func printStatus()`, after the last block (the cycle result section), before `return nil`, add:

```go
	if statusIntelligence {
		if err := printIntelligenceMetrics(); err != nil {
			fmt.Fprintf(os.Stderr, "warning: intelligence metrics unavailable: %v\n", err)
		}
	}
```

Then add the new function at the bottom of the file:

```go
func printIntelligenceMetrics() error {
	client := newOrchestratorClient()
	ctx := context.Background()

	resp, err := client.GetIntelligenceMetrics(ctx, connect.NewRequest(&omegav1.GetIntelligenceMetricsRequest{
		LastNCycles: 100,
	}))
	if err != nil {
		return err
	}
	m := resp.Msg

	passing := 0
	for _, c := range m.Checks {
		if c.Passing {
			passing++
		}
	}

	provider := m.BrainProvider
	if provider == "" {
		provider = "nobrain"
	}

	fmt.Printf("\n=== Intelligence Layer Status (last %d cycles) ===\n", m.CyclesAnalyzed)
	fmt.Printf("  Brain provider:    %s\n", provider)
	fmt.Printf("  Brain calls:       %d (%.2f/cycle)\n", m.BrainCallsTotal, m.BrainCallsPerCycle)
	fmt.Printf("  Improve calls:     %d (%d accepted)\n", m.ImproveCallsTotal, m.ImproveAcceptedTotal)
	if m.SignalVersionLatest != "" {
		fmt.Printf("  Signal version:    %s\n", m.SignalVersionLatest)
	}
	if len(m.NewSignalsUnlocked) > 0 {
		fmt.Printf("  New signals:       %v\n", m.NewSignalsUnlocked)
	}
	fmt.Printf("\n  Memory:\n")
	fmt.Printf("    Episodes:          %d\n", m.EpisodesTotal)
	fmt.Printf("    Semantic patterns: %d\n", m.SemanticPatternsTotal)
	fmt.Printf("    Shared memory:     %d\n", m.SharedMemoryTotal)
	fmt.Printf("    Utilization:       %.0f%%\n", m.MemoryUtilizationPct*100)
	fmt.Printf("    Cross-project:     %.0f%%\n", m.CrossProjectRatio*100)

	fmt.Printf("\n  Intelligence score:  %.3f (%d/8 checks passing)\n",
		m.IntelligenceScoreLatest, passing)

	for _, c := range m.Checks {
		mark := "✅"
		if !c.Passing {
			mark = "❌"
		}
		fmt.Printf("    %s %s\n", mark, c.Name)
		if c.Detail != "" {
			fmt.Printf("       %s\n", c.Detail)
		}
	}
	return nil
}
```

- [ ] **Step 2: Verify the file compiles**

```bash
go build ./cmd/omega/...
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cmd/omega/status.go
git commit --no-verify -m "feat: omega status --intelligence CLI flag"
```

---

### Task 10: Run 20 cycles to verify end-to-end

**Files:**
- Read: `omega.example.yml` to understand run config

- [ ] **Step 1: Check that DATABASE_URL is set**

```bash
echo ${DATABASE_URL:-"not set"}
```

If not set, set it to the local dev DSN:

```bash
export DATABASE_URL="postgres://omega:omega@localhost:5432/omega?sslmode=disable"
```

- [ ] **Step 2: Run omega for 20 cycles (NoBrain mode)**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
python -m omega --mode pico --max-cycles 20 2>&1 | tail -30
```

If that command doesn't work, use the runner directly:

```bash
python -c "
from omega.runner import OmegaRunner
r = OmegaRunner(mode='pico', max_iterations=20, heartbeat_override=1)
r.run()
print('Done')
"
```

- [ ] **Step 3: Verify rows in intelligence_metrics**

```bash
psql "$DATABASE_URL" -c "SELECT cycle, brain_calls, signals_nonzero, debate_gate_invocations, intelligence_score FROM intelligence_metrics ORDER BY cycle DESC LIMIT 5;"
```

Expected: 5 rows, each with `cycle` counting up, `intelligence_score` between 0 and 1.

- [ ] **Step 4: Test the CLI command (requires omega-api server running)**

If the API server is running:

```bash
./omega status --intelligence
```

If not running, verify the binary builds:

```bash
go build -o /tmp/omega-test ./cmd/omega/
/tmp/omega-test status --intelligence 2>&1 || echo "API not running (expected without server)"
```

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit --no-verify -m "chore: verify intelligence instrumentation — 20 cycles confirmed"
```

---

### Task 11: Build the final binary

- [ ] **Step 1: Full build + binary**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/suspicious-northcutt
go build -o bin/omega ./cmd/omega/
echo "Build OK: $(./bin/omega --help 2>&1 | head -3)"
```

Expected: binary built, help output shows `status` command.

- [ ] **Step 2: Confirm the status command has the flag**

```bash
./bin/omega status --help
```

Expected: output includes `--intelligence`.

- [ ] **Step 3: Final commit**

```bash
git add bin/omega
git commit --no-verify -m "build: updated omega binary with --intelligence flag"
```

---

## Self-Review

**Spec coverage:**
- ✅ `intelligence_metrics` table — Task 1
- ✅ `IntelligenceMetricsCollector` with `record`, `increment`, `flush`, `_compute_intelligence_score` — Task 2
- ✅ `MemoryQualityAssessor` with all 11 metrics — Task 3
- ✅ Orchestrator wiring at 5 points — Task 4
- ✅ `omega/runner.py` instantiation — Task 5
- ✅ Proto RPC + messages — Task 6
- ✅ `buf generate` — Task 6
- ✅ Go DB query — Task 7
- ✅ Go handler — Task 8
- ✅ CLI `--intelligence` flag — Task 9
- ✅ 20 cycles verification — Task 10
- ✅ `--no-verify` on all commits throughout

**Type consistency:**
- `IntelligenceMetricsCollector._conn` used in `_write_to_db` — consistent
- Handler uses `summary.AvgBrainCalls` etc. — matches `IntelligenceMetricsSummary` fields exactly
- Proto field `checks` matches `repeated IntelligenceCheck checks = 15` — consistent
- `GetIntelligenceMetricsResponse.MemoryUtilizationPct` used in CLI — matches proto field `memory_utilization_pct = 11`
- `GetIntelligenceMetricsResponse.CrossProjectRatio` used in CLI — matches proto field `cross_project_ratio = 12`

**No placeholders:** All code blocks are complete. No "TBD" or "TODO" in plan.
