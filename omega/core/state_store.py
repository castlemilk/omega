"""omega.core.state_store — Infrastructure state store for the Omega system.

Handles execution tracking, distributed traces, cost events, issue management,
and improvement history. Complements MemoryKernel (domain memory) and
Evaluator (goal scoring) without replacing them.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id             TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    version             TEXT NOT NULL DEFAULT '1.0',
    capabilities_json   TEXT NOT NULL DEFAULT '[]',
    health              REAL NOT NULL DEFAULT 1.0,
    status              TEXT NOT NULL DEFAULT 'active',
    brain_config_json   TEXT NOT NULL DEFAULT '{"provider":"none"}',
    registered_at       REAL NOT NULL,
    last_updated        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS node_executions (
    exec_id      TEXT PRIMARY KEY,
    node_id      TEXT NOT NULL,
    node_name    TEXT NOT NULL,
    trace_id     TEXT,
    span_id      TEXT,
    action       TEXT NOT NULL,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    duration_ms  REAL,
    success      INTEGER NOT NULL DEFAULT 1,
    error_text   TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    cycle        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS traces (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    node_id         TEXT,
    node_name       TEXT,
    operation       TEXT NOT NULL,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    duration_ms     REAL,
    status          TEXT NOT NULL DEFAULT 'ok',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    cycle           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cost_events (
    cost_id             TEXT PRIMARY KEY,
    node_id             TEXT NOT NULL,
    exec_id             TEXT,
    provider            TEXT NOT NULL,
    call_type           TEXT NOT NULL,
    duration_ms         REAL NOT NULL DEFAULT 0,
    estimated_cost_usd  REAL NOT NULL DEFAULT 0.0,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    recorded_at         REAL NOT NULL,
    cycle               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id        TEXT PRIMARY KEY,
    detector        TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'warning',
    description     TEXT NOT NULL,
    context_json    TEXT NOT NULL DEFAULT '{}',
    state           TEXT NOT NULL DEFAULT 'pending',
    opened_at       REAL NOT NULL,
    resolved_at     REAL,
    cycle_opened    INTEGER NOT NULL DEFAULT 0,
    cycle_resolved  INTEGER
);

CREATE TABLE IF NOT EXISTS activity_log (
    log_id       TEXT PRIMARY KEY,
    action_type  TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    data_json    TEXT NOT NULL DEFAULT '{}',
    recorded_at  REAL NOT NULL,
    cycle        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS improvement_log (
    improve_id           TEXT PRIMARY KEY,
    node_id              TEXT NOT NULL,
    node_name            TEXT NOT NULL,
    from_version         TEXT NOT NULL,
    to_version           TEXT NOT NULL,
    before_metrics_json  TEXT NOT NULL DEFAULT '{}',
    after_metrics_json   TEXT NOT NULL DEFAULT '{}',
    triggered_by         TEXT NOT NULL DEFAULT 'metrics',
    recorded_at          REAL NOT NULL,
    cycle                INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config_revisions (
    revision_id  TEXT PRIMARY KEY,
    node_id      TEXT NOT NULL,
    version      TEXT NOT NULL,
    config_json  TEXT NOT NULL DEFAULT '{}',
    recorded_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS brain_executions (
    brain_exec_id   TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    node_name       TEXT NOT NULL,
    provider        TEXT NOT NULL DEFAULT 'none',
    model           TEXT NOT NULL DEFAULT '',
    operation       TEXT NOT NULL,
    action_decided  TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    reasoning       TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.0,
    outcome         TEXT NOT NULL DEFAULT 'pending',
    latency_ms      REAL NOT NULL DEFAULT 0.0,
    trace_id        TEXT NOT NULL DEFAULT '',
    recorded_at     REAL NOT NULL,
    cycle           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alignment_decisions (
    decision_id         TEXT PRIMARY KEY,
    cycle               INTEGER NOT NULL DEFAULT 0,
    approved            INTEGER NOT NULL DEFAULT 1,
    violations_json     TEXT NOT NULL DEFAULT '[]',
    pareto_ranks_json   TEXT NOT NULL DEFAULT '{}',
    adjustments_json    TEXT NOT NULL DEFAULT '{}',
    vcg_payments_json   TEXT NOT NULL DEFAULT '{}',
    goodhart_warning    INTEGER NOT NULL DEFAULT 0,
    recorded_at         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS adversarial_results (
    result_id           TEXT PRIMARY KEY,
    cycle               INTEGER NOT NULL DEFAULT 0,
    ring                INTEGER NOT NULL DEFAULT 1,
    flagged             INTEGER NOT NULL DEFAULT 0,
    max_disagreement    REAL NOT NULL DEFAULT 0.0,
    scenario_count      INTEGER NOT NULL DEFAULT 0,
    failure_cases_json  TEXT NOT NULL DEFAULT '[]',
    details_json        TEXT NOT NULL DEFAULT '{}',
    recorded_at         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_tracking (
    tracking_id         TEXT PRIMARY KEY,
    cycle               INTEGER NOT NULL DEFAULT 0,
    approved            INTEGER NOT NULL DEFAULT 1,
    composite_score     REAL NOT NULL DEFAULT 0.0,
    scorecard_json      TEXT NOT NULL DEFAULT '{}',
    nash_weights_json   TEXT NOT NULL DEFAULT '{}',
    tracking_error      REAL NOT NULL DEFAULT 0.0,
    control_action_json TEXT NOT NULL DEFAULT '{}',
    subtasks_json       TEXT NOT NULL DEFAULT '[]',
    violations_json     TEXT NOT NULL DEFAULT '[]',
    recorded_at         REAL NOT NULL
);
"""


class StateBackend(ABC):
    """Abstract base class / protocol for Omega state backends.

    Defines the minimum interface that all state storage implementations must
    satisfy.  The current default implementation is ``SQLiteBackend`` (formerly
    ``StateStore``).  Future implementations (e.g. PostgresBackend) should
    subclass this and implement all abstract methods.

    Node code should type-hint against ``StateBackend``, not the concrete class,
    so backends can be swapped without touching calling code.
    """

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    @abstractmethod
    def upsert_node(
        self,
        node_id: str,
        name: str,
        version: str,
        capabilities: list[str],
        health: float,
        status: str = "active",
        brain_config: dict | None = None,
    ) -> None: ...

    @abstractmethod
    def get_node(self, node_id: str) -> dict | None: ...

    @abstractmethod
    def all_nodes(self) -> list[dict]: ...

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    @abstractmethod
    def begin_execution(
        self,
        node_id: str,
        node_name: str,
        action: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        cycle: int = 0,
    ) -> str: ...

    @abstractmethod
    def end_execution(
        self,
        exec_id: str,
        success: bool,
        error_text: str | None = None,
        metrics: dict | None = None,
    ) -> None: ...

    @abstractmethod
    def get_recent_executions(
        self,
        node_id: str | None = None,
        limit: int = 20,
        since_cycle: int | None = None,
    ) -> list[dict]: ...

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    @abstractmethod
    def begin_span(
        self,
        trace_id: str,
        node_id: str,
        node_name: str,
        operation: str,
        parent_span_id: str | None = None,
        cycle: int = 0,
    ) -> str: ...

    @abstractmethod
    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        metadata: dict | None = None,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    @abstractmethod
    def open_issue(
        self,
        issue_id: str,
        detector: str,
        severity: str,
        description: str,
        context: dict | None = None,
        cycle: int = 0,
    ) -> bool: ...

    @abstractmethod
    def resolve_issue(self, issue_id: str, cycle: int | None = None) -> bool: ...

    @abstractmethod
    def get_open_issues(self) -> list[dict]: ...

    # ------------------------------------------------------------------
    # Improvements
    # ------------------------------------------------------------------

    @abstractmethod
    def record_improvement(
        self,
        node_id: str,
        node_name: str,
        from_version: str,
        to_version: str,
        before_metrics: dict | None = None,
        after_metrics: dict | None = None,
        triggered_by: str = "metrics",
        cycle: int = 0,
    ) -> None: ...

    @abstractmethod
    def get_improvement_history(
        self,
        node_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]: ...


class SQLiteBackend(StateBackend):
    """
    SQLite-backed implementation of StateBackend.

    Central infrastructure state store for the Omega system.

    Single source of truth for:
      - Node registry (health, version, capabilities)
      - Execution history (every Execute() call)
      - Distributed trace spans
      - Cost events (API calls, resource usage)
      - Issues (from cleaner nodes, with triage)
      - Improvement history (version diffs, metric deltas)
      - Immutable activity log

    Complementary to MemoryKernel (domain memory) and Evaluator (goal scoring).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    # ------------------------------------------------------------------
    # Schema migration (safe ALTER TABLE for existing DBs)
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        """Add columns that may be missing in existing databases."""
        existing_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(nodes)").fetchall()
        }
        if "brain_config_json" not in existing_cols:
            self._conn.execute(
                'ALTER TABLE nodes ADD COLUMN brain_config_json TEXT NOT NULL DEFAULT \'{"provider":"none"}\''
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        node_id: str,
        name: str,
        version: str,
        capabilities: list[str],
        health: float,
        status: str = "active",
        brain_config: dict | None = None,
    ) -> None:
        now = time.time()
        brain_json = json.dumps(brain_config or {"provider": "none"})
        existing = self._conn.execute(
            "SELECT registered_at FROM nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                """UPDATE nodes
                   SET name=?, version=?, capabilities_json=?, health=?, status=?,
                       brain_config_json=?, last_updated=?
                   WHERE node_id=?""",
                (
                    name,
                    version,
                    json.dumps(capabilities),
                    health,
                    status,
                    brain_json,
                    now,
                    node_id,
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO nodes
                   (node_id, name, version, capabilities_json, health, status,
                    brain_config_json, registered_at, last_updated)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    node_id,
                    name,
                    version,
                    json.dumps(capabilities),
                    health,
                    status,
                    brain_json,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def get_node(self, node_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["capabilities"] = json.loads(d.pop("capabilities_json", "[]"))
        d["brain_config"] = json.loads(d.pop("brain_config_json", '{"provider":"none"}'))
        return d

    def all_nodes(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM nodes ORDER BY registered_at").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["capabilities"] = json.loads(d.pop("capabilities_json", "[]"))
            d["brain_config"] = json.loads(d.pop("brain_config_json", '{"provider":"none"}'))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Executions (checkout pattern)
    # ------------------------------------------------------------------

    def begin_execution(
        self,
        node_id: str,
        node_name: str,
        action: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        exec_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO node_executions
               (exec_id, node_id, node_name, trace_id, span_id, action, started_at, success, cycle)
               VALUES (?,?,?,?,?,?,?,1,?)""",
            (exec_id, node_id, node_name, trace_id, span_id, action, now, cycle),
        )
        self._conn.commit()
        return exec_id

    def end_execution(
        self,
        exec_id: str,
        success: bool,
        error_text: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        now = time.time()
        row = self._conn.execute(
            "SELECT started_at FROM node_executions WHERE exec_id = ?", (exec_id,)
        ).fetchone()
        duration_ms = (now - row["started_at"]) * 1000 if row else 0
        self._conn.execute(
            """UPDATE node_executions
               SET ended_at=?, duration_ms=?, success=?, error_text=?, metrics_json=?
               WHERE exec_id=?""",
            (
                now,
                duration_ms,
                1 if success else 0,
                error_text,
                json.dumps(metrics or {}),
                exec_id,
            ),
        )
        self._conn.commit()

    def get_recent_executions(
        self,
        node_id: str | None = None,
        limit: int = 20,
        since_cycle: int | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM node_executions WHERE 1=1"
        params: list = []
        if node_id is not None:
            query += " AND node_id = ?"
            params.append(node_id)
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["metrics"] = json.loads(d.pop("metrics_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    def begin_span(
        self,
        trace_id: str,
        node_id: str,
        node_name: str,
        operation: str,
        parent_span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        span_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO traces
               (span_id, trace_id, parent_span_id, node_id, node_name, operation, started_at, cycle)
               VALUES (?,?,?,?,?,?,?,?)""",
            (span_id, trace_id, parent_span_id, node_id, node_name, operation, now, cycle),
        )
        self._conn.commit()
        return span_id

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        metadata: dict | None = None,
    ) -> None:
        now = time.time()
        row = self._conn.execute(
            "SELECT started_at FROM traces WHERE span_id = ?", (span_id,)
        ).fetchone()
        duration_ms = (now - row["started_at"]) * 1000 if row else 0
        self._conn.execute(
            """UPDATE traces
               SET ended_at=?, duration_ms=?, status=?, metadata_json=?
               WHERE span_id=?""",
            (now, duration_ms, status, json.dumps(metadata or {}), span_id),
        )
        self._conn.commit()

    def get_trace(self, trace_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM traces WHERE trace_id = ? ORDER BY started_at",
            (trace_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
            result.append(d)
        return result

    def get_recent_traces(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            """SELECT trace_id,
                      MIN(started_at) as trace_started,
                      MAX(ended_at)   as trace_ended,
                      MAX(ended_at) - MIN(started_at) as total_duration_s,
                      COUNT(*)        as span_count,
                      SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_spans,
                      MAX(cycle)      as cycle
               FROM traces
               GROUP BY trace_id
               ORDER BY trace_started DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Cost events
    # ------------------------------------------------------------------

    def record_cost(
        self,
        node_id: str,
        provider: str,
        call_type: str,
        duration_ms: float,
        exec_id: str | None = None,
        estimated_cost_usd: float = 0.0,
        metadata: dict | None = None,
        cycle: int = 0,
    ) -> None:
        cost_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO cost_events
               (cost_id, node_id, exec_id, provider, call_type, duration_ms,
                estimated_cost_usd, metadata_json, recorded_at, cycle)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                cost_id,
                node_id,
                exec_id,
                provider,
                call_type,
                duration_ms,
                estimated_cost_usd,
                json.dumps(metadata or {}),
                time.time(),
                cycle,
            ),
        )
        self._conn.commit()

    def get_cost_summary(self, since_cycle: int | None = None) -> dict:
        query = "SELECT provider, COUNT(*) as calls, SUM(duration_ms) as total_ms, SUM(estimated_cost_usd) as total_cost FROM cost_events WHERE 1=1"
        params: list = []
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " GROUP BY provider"
        rows = self._conn.execute(query, params).fetchall()
        return {
            row["provider"]: {
                "calls": row["calls"],
                "total_ms": row["total_ms"] or 0.0,
                "total_cost": row["total_cost"] or 0.0,
            }
            for row in rows
        }

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def open_issue(
        self,
        issue_id: str,
        detector: str,
        severity: str,
        description: str,
        context: dict | None = None,
        cycle: int = 0,
    ) -> bool:
        existing = self._conn.execute(
            "SELECT state FROM issues WHERE issue_id = ?", (issue_id,)
        ).fetchone()
        if existing:
            if existing["state"] == "pending":
                self.escalate_issue(issue_id)
            return False
        self._conn.execute(
            """INSERT INTO issues
               (issue_id, detector, severity, description, context_json, state, opened_at, cycle_opened)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                issue_id,
                detector,
                severity,
                description,
                json.dumps(context or {}),
                "pending",
                time.time(),
                cycle,
            ),
        )
        self._conn.commit()
        self.log_activity(
            "issue_opened", "issue", issue_id, {"severity": severity, "detector": detector}, cycle
        )
        return True

    def escalate_issue(self, issue_id: str) -> bool:
        result = self._conn.execute(
            "UPDATE issues SET state='active' WHERE issue_id=? AND state='pending'", (issue_id,)
        )
        self._conn.commit()
        return result.rowcount > 0

    def resolve_issue(self, issue_id: str, cycle: int | None = None) -> bool:
        now = time.time()
        result = self._conn.execute(
            """UPDATE issues
               SET state='resolved', resolved_at=?, cycle_resolved=?
               WHERE issue_id=? AND state != 'resolved'""",
            (now, cycle, issue_id),
        )
        self._conn.commit()
        if result.rowcount > 0:
            self.log_activity("issue_resolved", "issue", issue_id, {"cycle": cycle}, cycle or 0)
            return True
        return False

    def get_open_issues(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM issues WHERE state != 'resolved' ORDER BY opened_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["context"] = json.loads(d.pop("context_json", "{}"))
            result.append(d)
        return result

    def get_all_issues(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM issues ORDER BY opened_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["context"] = json.loads(d.pop("context_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    def log_activity(
        self,
        action_type: str,
        entity_type: str,
        entity_id: str,
        data: dict | None = None,
        cycle: int = 0,
    ) -> None:
        log_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO activity_log
               (log_id, action_type, entity_type, entity_id, data_json, recorded_at, cycle)
               VALUES (?,?,?,?,?,?,?)""",
            (
                log_id,
                action_type,
                entity_type,
                entity_id,
                json.dumps(data or {}),
                time.time(),
                cycle,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Improvement log
    # ------------------------------------------------------------------

    def record_improvement(
        self,
        node_id: str,
        node_name: str,
        from_version: str,
        to_version: str,
        before_metrics: dict | None = None,
        after_metrics: dict | None = None,
        triggered_by: str = "metrics",
        cycle: int = 0,
    ) -> None:
        improve_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO improvement_log
               (improve_id, node_id, node_name, from_version, to_version,
                before_metrics_json, after_metrics_json, triggered_by, recorded_at, cycle)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                improve_id,
                node_id,
                node_name,
                from_version,
                to_version,
                json.dumps(before_metrics),
                json.dumps(after_metrics),
                triggered_by,
                time.time(),
                cycle,
            ),
        )
        self._conn.commit()
        self.log_activity(
            "node_improved",
            "node",
            node_id,
            {"from_version": from_version, "to_version": to_version, "triggered_by": triggered_by},
            cycle,
        )

    def get_improvement_history(self, node_id: str | None = None, limit: int = 20) -> list[dict]:
        query = "SELECT * FROM improvement_log WHERE 1=1"
        params: list = []
        if node_id is not None:
            query += " AND node_id = ?"
            params.append(node_id)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["before_metrics"] = json.loads(d.pop("before_metrics_json", "{}"))
            d["after_metrics"] = json.loads(d.pop("after_metrics_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Config revisions
    # ------------------------------------------------------------------

    def save_config_revision(self, node_id: str, version: str, config: dict) -> None:
        revision_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO config_revisions
               (revision_id, node_id, version, config_json, recorded_at)
               VALUES (?,?,?,?,?)""",
            (revision_id, node_id, version, json.dumps(config), time.time()),
        )
        self._conn.commit()

    def get_config_history(self, node_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM config_revisions WHERE node_id = ? ORDER BY recorded_at DESC",
            (node_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = json.loads(d.pop("config_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # DashboardNode helpers
    # ------------------------------------------------------------------

    def get_nodes_with_recent_metrics(self, minutes: int = 10) -> list[dict]:
        """
        Return node records that have at least one execution in the last N minutes.

        Used by DashboardNode.metric_coverage_audit to compute coverage score.
        """
        cutoff = time.time() - minutes * 60
        rows = self._conn.execute(
            """SELECT DISTINCT n.node_id, n.name, n.version, n.health, n.status
               FROM nodes n
               INNER JOIN node_executions e ON e.node_id = n.node_id
               WHERE e.started_at >= ?""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_execution_time(self) -> float | None:
        """
        Return the Unix timestamp of the most recent node execution.

        Returns None if there are no executions yet.
        """
        row = self._conn.execute(
            "SELECT MAX(started_at) as latest FROM node_executions"
        ).fetchone()
        return row["latest"] if row and row["latest"] is not None else None

    # ------------------------------------------------------------------
    # Brain execution log
    # ------------------------------------------------------------------

    def record_brain_execution(
        self,
        node_id: str,
        node_name: str,
        provider: str,
        model: str,
        operation: str,
        action_decided: str,
        parameters: dict | None = None,
        reasoning: str = "",
        confidence: float = 0.0,
        outcome: str = "pending",
        latency_ms: float = 0.0,
        trace_id: str = "",
        cycle: int = 0,
    ) -> str:
        """
        Record a single brain invocation. Returns the brain_exec_id.

        outcome values: "pending" | "applied" | "ignored" | "overridden"
          - applied   : node acted on the brain's decision
          - ignored   : brain returned action="pass", rule-based logic used
          - overridden: brain suggested an action but node overrode it
        """
        brain_exec_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO brain_executions
               (brain_exec_id, node_id, node_name, provider, model, operation,
                action_decided, parameters_json, reasoning, confidence,
                outcome, latency_ms, trace_id, recorded_at, cycle)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                brain_exec_id,
                node_id,
                node_name,
                provider,
                model,
                operation,
                action_decided,
                json.dumps(parameters or {}),
                reasoning,
                confidence,
                outcome,
                latency_ms,
                trace_id,
                time.time(),
                cycle,
            ),
        )
        self._conn.commit()
        self.log_activity(
            "brain_consulted",
            "node",
            node_id,
            {
                "provider": provider,
                "model": model,
                "operation": operation,
                "action": action_decided,
                "outcome": outcome,
                "confidence": confidence,
            },
            cycle,
        )
        return brain_exec_id

    def update_brain_outcome(self, brain_exec_id: str, outcome: str) -> None:
        """Update the outcome once the node has acted (or not) on the brain's decision."""
        self._conn.execute(
            "UPDATE brain_executions SET outcome=? WHERE brain_exec_id=?",
            (outcome, brain_exec_id),
        )
        self._conn.commit()

    def get_brain_executions(
        self,
        node_id: str | None = None,
        provider: str | None = None,
        operation: str | None = None,
        since_cycle: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query brain execution history — useful for A/B testing model decisions."""
        query = "SELECT * FROM brain_executions WHERE 1=1"
        params: list = []
        if node_id:
            query += " AND node_id = ?"
            params.append(node_id)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if operation:
            query += " AND operation = ?"
            params.append(operation)
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["parameters"] = json.loads(d.pop("parameters_json", "{}"))
            result.append(d)
        return result

    def get_brain_summary(self, since_cycle: int | None = None) -> dict:
        """Aggregate brain execution stats — provider breakdown, action distribution."""
        query = "SELECT provider, model, outcome, COUNT(*) as count, AVG(confidence) as avg_confidence FROM brain_executions WHERE 1=1"
        params: list = []
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " GROUP BY provider, model, outcome"
        rows = self._conn.execute(query, params).fetchall()
        return {"by_provider_outcome": [dict(r) for r in rows]}

    # ------------------------------------------------------------------
    # Alignment decisions
    # ------------------------------------------------------------------

    def record_alignment_decision(
        self,
        cycle: int,
        approved: bool,
        violations: list | None = None,
        pareto_ranks: dict | None = None,
        adjustments: dict | None = None,
        vcg_payments: dict | None = None,
        goodhart_warning: bool = False,
    ) -> str:
        decision_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO alignment_decisions
               (decision_id, cycle, approved, violations_json, pareto_ranks_json,
                adjustments_json, vcg_payments_json, goodhart_warning, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                decision_id,
                cycle,
                1 if approved else 0,
                json.dumps(violations or []),
                json.dumps(pareto_ranks or {}),
                json.dumps(adjustments or {}),
                json.dumps(vcg_payments or {}),
                1 if goodhart_warning else 0,
                time.time(),
            ),
        )
        self._conn.commit()
        return decision_id

    def get_alignment_decisions(
        self, since_cycle: int | None = None, limit: int = 20
    ) -> list[dict]:
        query = "SELECT * FROM alignment_decisions WHERE 1=1"
        params: list = []
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["violations"] = json.loads(d.pop("violations_json", "[]"))
            d["pareto_ranks"] = json.loads(d.pop("pareto_ranks_json", "{}"))
            d["adjustments"] = json.loads(d.pop("adjustments_json", "{}"))
            d["vcg_payments"] = json.loads(d.pop("vcg_payments_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Adversarial results
    # ------------------------------------------------------------------

    def record_adversarial_result(
        self,
        cycle: int,
        ring: int,
        flagged: bool,
        max_disagreement: float = 0.0,
        scenario_count: int = 0,
        failure_cases: list | None = None,
        details: dict | None = None,
    ) -> str:
        result_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO adversarial_results
               (result_id, cycle, ring, flagged, max_disagreement,
                scenario_count, failure_cases_json, details_json, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                result_id,
                cycle,
                ring,
                1 if flagged else 0,
                max_disagreement,
                scenario_count,
                json.dumps(failure_cases or []),
                json.dumps(details or {}),
                time.time(),
            ),
        )
        self._conn.commit()
        return result_id

    def get_adversarial_results(
        self, since_cycle: int | None = None, ring: int | None = None, limit: int = 20
    ) -> list[dict]:
        query = "SELECT * FROM adversarial_results WHERE 1=1"
        params: list = []
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        if ring is not None:
            query += " AND ring = ?"
            params.append(ring)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["failure_cases"] = json.loads(d.pop("failure_cases_json", "[]"))
            d["details"] = json.loads(d.pop("details_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Goal tracking
    # ------------------------------------------------------------------

    def record_goal_tracking(
        self,
        cycle: int,
        approved: bool,
        composite_score: float,
        scorecard: dict | None = None,
        nash_weights: dict | None = None,
        tracking_error: float = 0.0,
        control_action: dict | None = None,
        subtasks: list | None = None,
        violations: list | None = None,
    ) -> str:
        tracking_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO goal_tracking
               (tracking_id, cycle, approved, composite_score, scorecard_json,
                nash_weights_json, tracking_error, control_action_json,
                subtasks_json, violations_json, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tracking_id,
                cycle,
                1 if approved else 0,
                composite_score,
                json.dumps(scorecard or {}),
                json.dumps(nash_weights or {}),
                tracking_error,
                json.dumps(control_action or {}),
                json.dumps(subtasks or []),
                json.dumps(violations or []),
                time.time(),
            ),
        )
        self._conn.commit()
        return tracking_id

    def get_goal_tracking(self, since_cycle: int | None = None, limit: int = 20) -> list[dict]:
        query = "SELECT * FROM goal_tracking WHERE 1=1"
        params: list = []
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["scorecard"] = json.loads(d.pop("scorecard_json", "{}"))
            d["nash_weights"] = json.loads(d.pop("nash_weights_json", "{}"))
            d["control_action"] = json.loads(d.pop("control_action_json", "{}"))
            d["subtasks"] = json.loads(d.pop("subtasks_json", "[]"))
            d["violations"] = json.loads(d.pop("violations_json", "[]"))
            result.append(d)
        return result

    def set_node_brain_config(self, node_id: str, brain_config: dict) -> None:
        """
        Persist an updated brain config to the nodes table.

        Also saves a config_revision so you have a full audit trail of
        which model was active on each node at each point in time.
        """
        self._conn.execute(
            "UPDATE nodes SET brain_config_json=?, last_updated=? WHERE node_id=?",
            (json.dumps(brain_config), time.time(), node_id),
        )
        self._conn.commit()
        self.save_config_revision(
            node_id,
            brain_config.get("model", ""),
            {"brain_config": brain_config},
        )

    # ------------------------------------------------------------------
    # Dashboard data
    # ------------------------------------------------------------------

    def get_dashboard_data(self, since_cycle: int = 0) -> dict:
        """Returns structured dict suitable for feeding a monitoring dashboard."""
        nodes = self.all_nodes()
        node_data = []
        for n in nodes:
            execs = self.get_recent_executions(
                node_id=n["node_id"], limit=100, since_cycle=since_cycle
            )
            total_execs = len(execs)
            failed_execs = sum(1 for e in execs if not e["success"])
            latencies = [e["duration_ms"] for e in execs if e["duration_ms"] is not None]

            improvements = self.get_improvement_history(node_id=n["node_id"], limit=10)

            node_data.append(
                {
                    "id": n["node_id"],
                    "name": n["name"],
                    "version": n["version"],
                    "health": n["health"],
                    "status": n["status"],
                    "executions_total": total_execs,
                    "error_rate": failed_execs / max(1, total_execs),
                    "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
                    "p95_latency_ms": (
                        sorted(latencies)[int(len(latencies) * 0.95)]
                        if len(latencies) > 1
                        else (latencies[0] if latencies else 0)
                    ),
                    "improvement_count": len(improvements),
                    "last_improved_to": improvements[0]["to_version"]
                    if improvements
                    else n["version"],
                }
            )

        cost_summary = self.get_cost_summary(since_cycle=since_cycle)
        open_issues = self.get_open_issues()
        recent_traces = self.get_recent_traces(limit=5)

        brain_summary = self.get_brain_summary(since_cycle=since_cycle)

        return {
            "nodes": node_data,
            "system": {
                "total_nodes": len(nodes),
                "open_issues": len(open_issues),
                "cost_summary": cost_summary,
                "brain_summary": brain_summary,
            },
            "issues": open_issues[:10],
            "recent_traces": recent_traces,
        }


# Backward-compatible alias — existing code using StateStore continues to work.
StateStore = SQLiteBackend
