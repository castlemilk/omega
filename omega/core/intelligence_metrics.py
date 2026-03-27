"""
omega.core.intelligence_metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-cycle intelligence layer instrumentation.

Records metrics for each orchestrator cycle and flushes to the
``intelligence_metrics`` Postgres table at cycle end.

Usage::

    collector = IntelligenceMetricsCollector(db_url=os.environ.get("DATABASE_URL"))
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

    All methods are no-ops when ``db_url`` is None or DB is unreachable.
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
