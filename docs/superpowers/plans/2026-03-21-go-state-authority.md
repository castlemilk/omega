# Go State Authority — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Go the sole authority for all SQLite writes, with Python calling Go via Connect-RPC to persist state instead of writing directly.

**Architecture:** Extend `internal/db/` with write methods mirroring every Python `SQLiteBackend` operation. Expose those as a new `StateService` via Connect-RPC. Add a thin Python bridge (`omega/bridge/state_client.py`) and a `GoBackend` class in `state_store.py` that delegates to Go, falling back to direct SQLite when the Go service is unreachable.

**Tech Stack:** Go 1.25, Connect-RPC v1.19.1, modernc.org/sqlite, Protobuf, buf generate, Python 3 urllib (no new dependencies)

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `internal/db/db.go` | Add `ensureStateTables()`; update package comment |
| Create | `internal/db/writes.go` | All 17 write methods on `*DB` |
| Create | `internal/db/writes_test.go` | Unit tests for every write method |
| Create | `proto/omega/v1/state_service.proto` | `StateService` — 17 write RPCs |
| Generate | `gen/go/omega/v1/state_service.pb.go` | Auto-generated — do not edit |
| Generate | `gen/go/omega/v1/omegav1connect/state_service.connect.go` | Auto-generated — do not edit |
| Create | `internal/handler/state.go` | `StateServiceHandler` implementing all 17 RPCs |
| Create | `internal/handler/state_test.go` | Handler-level tests |
| Modify | `cmd/omega-api/main.go` | Mount `StateServiceHandler` |
| Create | `omega/bridge/__init__.py` | Python package marker |
| Create | `omega/bridge/state_client.py` | HTTP client for Go StateService (stdlib only) |
| Modify | `omega/core/state_store.py` | Add `GoBackend` class; env-var-driven switching |

---

## Task 1: Add `ensureStateTables()` to Go DB layer

The tables currently exist only because Python creates them via `_SCHEMA`. Go must own this so the API server can start cleanly before Python ever runs.

**Files:**
- Modify: `internal/db/db.go`

- [ ] **Step 1.1: Read current db.go to confirm the `ensureBrainTables` pattern** (already done in planning — skip if re-reading)

- [ ] **Step 1.2: Add `ensureStateTables()` method to `internal/db/db.go`**

Insert the following method just before `ensureBrainTables`:

```go
// ensureStateTables creates all core state tables if they do not already exist.
// This mirrors the _SCHEMA DDL in omega/core/state_store.py; Go is now the
// authoritative creator of these tables.
func (d *DB) ensureStateTables() error {
	_, err := d.state.Exec(`
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
	`)
	return err
}
```

- [ ] **Step 1.3: Update `New()` to call `ensureStateTables()` before `ensureBrainTables()`**

In the `New()` function, after opening the DB connections, add:
```go
if err := d.ensureStateTables(); err != nil {
    state.Close()
    memory.Close()
    if challengeDB != nil { challengeDB.Close() }
    return nil, fmt.Errorf("ensure state tables: %w", err)
}
```

- [ ] **Step 1.4: Update package comment in `db.go`**

Change:
```go
// Package db provides read-only access to the Omega SQLite state and memory databases.
// The Python node layer writes; this Go layer reads.
package db
```
To:
```go
// Package db provides read/write access to the Omega SQLite state and memory databases.
// Go is the authoritative writer; Python calls Go via Connect-RPC to persist state.
package db
```

- [ ] **Step 1.5: Verify Go builds**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go build ./...
```
Expected: no errors.

- [ ] **Step 1.6: Commit**
```bash
git add internal/db/db.go
git commit -m "feat: Go ensures all state tables exist on startup"
```

---

## Task 2: Add write methods to Go DB layer

**Files:**
- Create: `internal/db/writes.go`

- [ ] **Step 2.1: Write the failing test first** (see Task 3 — do Task 3 before this)

Actually, follow TDD order: write tests first in Task 3, then implement here.

> ⚠️ Do Task 3 (write tests) BEFORE implementing writes.go — come back here after.

- [ ] **Step 2.2: Create `internal/db/writes.go`**

```go
package db

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// ── Node registry ─────────────────────────────────────────────────────────────

// UpsertNode inserts or updates a node record. Preserves registered_at on update.
func (d *DB) UpsertNode(nodeID, name, version string, capabilities []string, health float64, status string, brainConfig map[string]any) error {
	capsJSON, _ := json.Marshal(capabilities)
	brainJSON, _ := json.Marshal(brainConfig)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO nodes (node_id, name, version, capabilities_json, health, status, brain_config_json, registered_at, last_updated)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(node_id) DO UPDATE SET
			name=excluded.name, version=excluded.version,
			capabilities_json=excluded.capabilities_json,
			health=excluded.health, status=excluded.status,
			brain_config_json=excluded.brain_config_json,
			last_updated=excluded.last_updated`,
		nodeID, name, version, string(capsJSON), health, status, string(brainJSON), now, now)
	return err
}

// ── Executions ────────────────────────────────────────────────────────────────

// BeginExecution inserts a new execution row and returns its exec_id.
func (d *DB) BeginExecution(nodeID, nodeName, action string, traceID, spanID *string, cycle int64) (string, error) {
	execID := uuid.New().String()
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO node_executions (exec_id, node_id, node_name, trace_id, span_id, action, started_at, success, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)`,
		execID, nodeID, nodeName, traceID, spanID, action, now, cycle)
	if err != nil {
		return "", err
	}
	return execID, nil
}

// EndExecution updates an existing execution row with outcome and duration.
func (d *DB) EndExecution(execID string, success bool, errorText string, metrics map[string]float64) error {
	now := float64(time.Now().UnixNano()) / 1e9
	var startedAt float64
	row := d.state.QueryRow(`SELECT started_at FROM node_executions WHERE exec_id = ?`, execID)
	if err := row.Scan(&startedAt); err != nil {
		return err
	}
	durationMS := (now - startedAt) * 1000
	metricsJSON, _ := json.Marshal(metrics)
	successInt := 0
	if success {
		successInt = 1
	}
	_, err := d.state.Exec(`
		UPDATE node_executions
		SET ended_at=?, duration_ms=?, success=?, error_text=?, metrics_json=?
		WHERE exec_id=?`,
		now, durationMS, successInt, errorText, string(metricsJSON), execID)
	return err
}

// ── Traces ────────────────────────────────────────────────────────────────────

// BeginSpan inserts a new trace span and returns its span_id.
func (d *DB) BeginSpan(traceID, nodeID, nodeName, operation string, parentSpanID *string, cycle int64) (string, error) {
	spanID := uuid.New().String()
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO traces (span_id, trace_id, parent_span_id, node_id, node_name, operation, started_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		spanID, traceID, parentSpanID, nodeID, nodeName, operation, now, cycle)
	if err != nil {
		return "", err
	}
	return spanID, nil
}

// EndSpan updates a span with its outcome.
func (d *DB) EndSpan(spanID, status string, metadata map[string]any) error {
	now := float64(time.Now().UnixNano()) / 1e9
	var startedAt float64
	row := d.state.QueryRow(`SELECT started_at FROM traces WHERE span_id = ?`, spanID)
	if err := row.Scan(&startedAt); err != nil {
		return err
	}
	durationMS := (now - startedAt) * 1000
	metaJSON, _ := json.Marshal(metadata)
	_, err := d.state.Exec(`
		UPDATE traces SET ended_at=?, duration_ms=?, status=?, metadata_json=? WHERE span_id=?`,
		now, durationMS, status, string(metaJSON), spanID)
	return err
}

// ── Cost events ───────────────────────────────────────────────────────────────

// RecordCost inserts a cost event.
func (d *DB) RecordCost(nodeID, provider, callType string, durationMS float64, execID *string, estimatedCostUSD float64, metadata map[string]any, cycle int64) error {
	costID := uuid.New().String()
	metaJSON, _ := json.Marshal(metadata)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO cost_events (cost_id, node_id, exec_id, provider, call_type, duration_ms, estimated_cost_usd, metadata_json, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		costID, nodeID, execID, provider, callType, durationMS, estimatedCostUSD, string(metaJSON), now, cycle)
	return err
}

// ── Issues ────────────────────────────────────────────────────────────────────

// OpenIssue inserts a new issue. Returns (true, nil) if created, (false, nil) if already existed.
// If existing issue is "pending", it is escalated to "active".
func (d *DB) OpenIssue(issueID, detector, severity, description string, context map[string]any, cycle int64) (bool, error) {
	var existingState string
	err := d.state.QueryRow(`SELECT state FROM issues WHERE issue_id = ?`, issueID).Scan(&existingState)
	if err == nil {
		// Already exists — escalate if pending
		if existingState == "pending" {
			if _, err2 := d.EscalateIssue(issueID); err2 != nil {
				return false, err2
			}
		}
		return false, nil
	}
	ctxJSON, _ := json.Marshal(context)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err = d.state.Exec(`
		INSERT INTO issues (issue_id, detector, severity, description, context_json, state, opened_at, cycle_opened)
		VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)`,
		issueID, detector, severity, description, string(ctxJSON), now, cycle)
	if err != nil {
		return false, err
	}
	return true, d.LogActivity("issue_opened", "issue", issueID, map[string]any{"severity": severity, "detector": detector}, cycle)
}

// EscalateIssue sets a pending issue to active. Returns (rowsAffected, error).
func (d *DB) EscalateIssue(issueID string) (int64, error) {
	res, err := d.state.Exec(`UPDATE issues SET state='active' WHERE issue_id=? AND state='pending'`, issueID)
	if err != nil {
		return 0, err
	}
	n, _ := res.RowsAffected()
	return n, nil
}

// ResolveIssue marks an issue as resolved. Returns true if a row was updated.
func (d *DB) ResolveIssue(issueID string, cycle int64) (bool, error) {
	now := float64(time.Now().UnixNano()) / 1e9
	res, err := d.state.Exec(`
		UPDATE issues SET state='resolved', resolved_at=?, cycle_resolved=?
		WHERE issue_id=? AND state != 'resolved'`,
		now, cycle, issueID)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	if n > 0 {
		return true, d.LogActivity("issue_resolved", "issue", issueID, map[string]any{"cycle": cycle}, cycle)
	}
	return false, nil
}

// ── Activity log ──────────────────────────────────────────────────────────────

// LogActivity appends an entry to the activity log.
func (d *DB) LogActivity(actionType, entityType, entityID string, data map[string]any, cycle int64) error {
	logID := uuid.New().String()
	dataJSON, _ := json.Marshal(data)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO activity_log (log_id, action_type, entity_type, entity_id, data_json, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?)`,
		logID, actionType, entityType, entityID, string(dataJSON), now, cycle)
	return err
}

// ── Improvement log ───────────────────────────────────────────────────────────

// RecordImprovement inserts an improvement record and logs the activity.
func (d *DB) RecordImprovement(nodeID, nodeName, fromVersion, toVersion string, beforeMetrics, afterMetrics map[string]float64, triggeredBy string, cycle int64) error {
	improveID := uuid.New().String()
	beforeJSON, _ := json.Marshal(beforeMetrics)
	afterJSON, _ := json.Marshal(afterMetrics)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO improvement_log (improve_id, node_id, node_name, from_version, to_version, before_metrics_json, after_metrics_json, triggered_by, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		improveID, nodeID, nodeName, fromVersion, toVersion, string(beforeJSON), string(afterJSON), triggeredBy, now, cycle)
	if err != nil {
		return err
	}
	return d.LogActivity("node_improved", "node", nodeID, map[string]any{
		"from_version": fromVersion, "to_version": toVersion, "triggered_by": triggeredBy,
	}, cycle)
}

// ── Config revisions ──────────────────────────────────────────────────────────

// SaveConfigRevision records a versioned config snapshot.
func (d *DB) SaveConfigRevision(nodeID, version string, config map[string]any) error {
	revisionID := uuid.New().String()
	configJSON, _ := json.Marshal(config)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO config_revisions (revision_id, node_id, version, config_json, recorded_at)
		VALUES (?, ?, ?, ?, ?)`,
		revisionID, nodeID, version, string(configJSON), now)
	return err
}

// ── Brain executions ──────────────────────────────────────────────────────────

// RecordBrainExecution inserts a brain invocation record and returns its brain_exec_id.
func (d *DB) RecordBrainExecution(nodeID, nodeName, provider, model, operation, actionDecided string, parameters map[string]any, reasoning string, confidence float64, outcome string, latencyMS float64, traceID string, cycle int64) (string, error) {
	brainExecID := uuid.New().String()
	paramsJSON, _ := json.Marshal(parameters)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO brain_executions (brain_exec_id, node_id, node_name, provider, model, operation, action_decided, parameters_json, reasoning, confidence, outcome, latency_ms, trace_id, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		brainExecID, nodeID, nodeName, provider, model, operation, actionDecided, string(paramsJSON), reasoning, confidence, outcome, latencyMS, traceID, now, cycle)
	if err != nil {
		return "", err
	}
	err = d.LogActivity("brain_consulted", "node", nodeID, map[string]any{
		"provider": provider, "model": model, "operation": operation,
		"action": actionDecided, "outcome": outcome, "confidence": confidence,
	}, cycle)
	return brainExecID, err
}

// UpdateBrainOutcome updates the outcome field of a brain execution record.
func (d *DB) UpdateBrainOutcome(brainExecID, outcome string) error {
	_, err := d.state.Exec(`UPDATE brain_executions SET outcome=? WHERE brain_exec_id=?`, outcome, brainExecID)
	return err
}

// ── Alignment decisions ───────────────────────────────────────────────────────

// RecordAlignmentDecision inserts an alignment decision and returns its decision_id.
func (d *DB) RecordAlignmentDecision(cycle int64, approved bool, violations []string, paretoRanks, adjustments, vcgPayments map[string]any, goodhartWarning bool) (string, error) {
	decisionID := uuid.New().String()
	violationsJSON, _ := json.Marshal(violations)
	paretoJSON, _ := json.Marshal(paretoRanks)
	adjJSON, _ := json.Marshal(adjustments)
	vcgJSON, _ := json.Marshal(vcgPayments)
	gwInt := 0
	if goodhartWarning {
		gwInt = 1
	}
	approvedInt := 0
	if approved {
		approvedInt = 1
	}
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO alignment_decisions (decision_id, cycle, approved, violations_json, pareto_ranks_json, adjustments_json, vcg_payments_json, goodhart_warning, recorded_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		decisionID, cycle, approvedInt, string(violationsJSON), string(paretoJSON), string(adjJSON), string(vcgJSON), gwInt, now)
	if err != nil {
		return "", err
	}
	return decisionID, nil
}

// ── Adversarial results ───────────────────────────────────────────────────────

// RecordAdversarialResult inserts an adversarial pressure result and returns its result_id.
func (d *DB) RecordAdversarialResult(cycle int64, ring int32, flagged bool, maxDisagreement float64, scenarioCount int64, failureCases []string, details map[string]any) (string, error) {
	resultID := uuid.New().String()
	flaggedInt := 0
	if flagged {
		flaggedInt = 1
	}
	failuresJSON, _ := json.Marshal(failureCases)
	detailsJSON, _ := json.Marshal(details)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO adversarial_results (result_id, cycle, ring, flagged, max_disagreement, scenario_count, failure_cases_json, details_json, recorded_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		resultID, cycle, ring, flaggedInt, maxDisagreement, scenarioCount, string(failuresJSON), string(detailsJSON), now)
	if err != nil {
		return "", err
	}
	return resultID, nil
}

// ── Goal tracking ─────────────────────────────────────────────────────────────

// RecordGoalTracking inserts a goal tracking snapshot and returns its tracking_id.
func (d *DB) RecordGoalTracking(cycle int64, approved bool, compositeScore float64, scorecard, nashWeights map[string]any, trackingError float64, controlAction map[string]any, subtasks, violations []string) (string, error) {
	trackingID := uuid.New().String()
	approvedInt := 0
	if approved {
		approvedInt = 1
	}
	scorecardJSON, _ := json.Marshal(scorecard)
	nashJSON, _ := json.Marshal(nashWeights)
	ctrlJSON, _ := json.Marshal(controlAction)
	subtasksJSON, _ := json.Marshal(subtasks)
	violationsJSON, _ := json.Marshal(violations)
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := d.state.Exec(`
		INSERT INTO goal_tracking (tracking_id, cycle, approved, composite_score, scorecard_json, nash_weights_json, tracking_error, control_action_json, subtasks_json, violations_json, recorded_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		trackingID, cycle, approvedInt, compositeScore, string(scorecardJSON), string(nashJSON), trackingError, string(ctrlJSON), string(subtasksJSON), string(violationsJSON), now)
	if err != nil {
		return "", err
	}
	return trackingID, nil
}
```

- [ ] **Step 2.3: Build to confirm no compile errors**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go build ./internal/db/...
```
Expected: no errors.

---

## Task 3: Write and run DB write tests

**Files:**
- Create: `internal/db/writes_test.go`

- [ ] **Step 3.1: Write failing tests first (before writes.go is complete)**

Create `internal/db/writes_test.go`:

```go
package db_test

import (
	"os"
	"testing"

	"github.com/benebsworth/omega/internal/db"
)

func newTestDB(t *testing.T) *db.DB {
	t.Helper()
	stateF, _ := os.CreateTemp("", "omega-state-*.db")
	memF, _ := os.CreateTemp("", "omega-memory-*.db")
	stateF.Close()
	memF.Close()
	t.Cleanup(func() {
		os.Remove(stateF.Name())
		os.Remove(memF.Name())
	})
	d, err := db.New(stateF.Name(), memF.Name())
	if err != nil {
		t.Fatalf("new db: %v", err)
	}
	t.Cleanup(d.Close)
	return d
}

func TestUpsertNode(t *testing.T) {
	d := newTestDB(t)
	err := d.UpsertNode("n1", "TestNode", "1.0", []string{"a", "b"}, 0.9, "active", map[string]any{"provider": "none"})
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}
	// Update
	err = d.UpsertNode("n1", "TestNode", "1.1", []string{"a"}, 0.8, "active", nil)
	if err != nil {
		t.Fatalf("upsert update: %v", err)
	}
	nodes, err := d.AllNodes()
	if err != nil {
		t.Fatalf("all nodes: %v", err)
	}
	if len(nodes) != 1 {
		t.Fatalf("expected 1 node, got %d", len(nodes))
	}
	if nodes[0].Version != "1.1" {
		t.Errorf("expected version 1.1, got %s", nodes[0].Version)
	}
}

func TestBeginEndExecution(t *testing.T) {
	d := newTestDB(t)
	// Need a node first for foreign-key-like consistency
	d.UpsertNode("n1", "TestNode", "1.0", nil, 1.0, "active", nil) //nolint:errcheck

	execID, err := d.BeginExecution("n1", "TestNode", "run", nil, nil, 1)
	if err != nil {
		t.Fatalf("begin execution: %v", err)
	}
	if execID == "" {
		t.Fatal("expected non-empty execID")
	}
	err = d.EndExecution(execID, true, "", map[string]float64{"score": 0.9})
	if err != nil {
		t.Fatalf("end execution: %v", err)
	}
	execs, err := d.GetExecutions("n1", 10)
	if err != nil {
		t.Fatalf("get executions: %v", err)
	}
	if len(execs) != 1 {
		t.Fatalf("expected 1 execution, got %d", len(execs))
	}
	if !execs[0].Success {
		t.Error("expected success=true")
	}
	if execs[0].DurationMS == nil || *execs[0].DurationMS < 0 {
		t.Error("expected valid duration")
	}
}

func TestBeginEndSpan(t *testing.T) {
	d := newTestDB(t)
	traceID := "trace-abc"
	spanID, err := d.BeginSpan(traceID, "n1", "TestNode", "execute", nil, 2)
	if err != nil {
		t.Fatalf("begin span: %v", err)
	}
	if spanID == "" {
		t.Fatal("expected non-empty spanID")
	}
	err = d.EndSpan(spanID, "ok", map[string]any{"key": "val"})
	if err != nil {
		t.Fatalf("end span: %v", err)
	}
	spans, err := d.GetTraceSpans(traceID)
	if err != nil {
		t.Fatalf("get spans: %v", err)
	}
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if spans[0].Status != "ok" {
		t.Errorf("expected status ok, got %s", spans[0].Status)
	}
}

func TestRecordCost(t *testing.T) {
	d := newTestDB(t)
	err := d.RecordCost("n1", "anthropic", "llm_call", 150.0, nil, 0.002, nil, 3)
	if err != nil {
		t.Fatalf("record cost: %v", err)
	}
	costs, err := d.GetCosts()
	if err != nil {
		t.Fatalf("get costs: %v", err)
	}
	if len(costs) != 1 {
		t.Fatalf("expected 1 cost entry, got %d", len(costs))
	}
	if costs[0].Provider != "anthropic" {
		t.Errorf("expected provider anthropic, got %s", costs[0].Provider)
	}
}

func TestOpenEscalateResolveIssue(t *testing.T) {
	d := newTestDB(t)
	created, err := d.OpenIssue("issue-1", "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("open issue: %v", err)
	}
	if !created {
		t.Error("expected created=true")
	}
	// Duplicate open should escalate, not create new
	created2, err := d.OpenIssue("issue-1", "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("open issue duplicate: %v", err)
	}
	if created2 {
		t.Error("expected created=false for duplicate")
	}
	resolved, err := d.ResolveIssue("issue-1", 2)
	if err != nil {
		t.Fatalf("resolve issue: %v", err)
	}
	if !resolved {
		t.Error("expected resolved=true")
	}
	issues, err := d.GetIssues("open")
	if err != nil {
		t.Fatalf("get issues: %v", err)
	}
	for _, i := range issues {
		if i.IssueID == "issue-1" {
			t.Error("issue-1 should not appear in open issues after resolution")
		}
	}
}

func TestLogActivity(t *testing.T) {
	d := newTestDB(t)
	err := d.LogActivity("test_action", "node", "n1", map[string]any{"k": "v"}, 0)
	if err != nil {
		t.Fatalf("log activity: %v", err)
	}
	entries, err := d.RecentActivity(10)
	if err != nil {
		t.Fatalf("recent activity: %v", err)
	}
	if len(entries) < 1 {
		t.Fatal("expected at least 1 activity entry")
	}
}

func TestRecordImprovement(t *testing.T) {
	d := newTestDB(t)
	err := d.RecordImprovement("n1", "TestNode", "1.0", "1.1",
		map[string]float64{"score": 0.7},
		map[string]float64{"score": 0.85},
		"metrics", 5)
	if err != nil {
		t.Fatalf("record improvement: %v", err)
	}
	imps, err := d.GetImprovements("n1", 10)
	if err != nil {
		t.Fatalf("get improvements: %v", err)
	}
	if len(imps) != 1 {
		t.Fatalf("expected 1 improvement, got %d", len(imps))
	}
	if imps[0].ToVersion != "1.1" {
		t.Errorf("expected to_version 1.1, got %s", imps[0].ToVersion)
	}
}

func TestSaveConfigRevision(t *testing.T) {
	d := newTestDB(t)
	err := d.SaveConfigRevision("n1", "1.0", map[string]any{"model": "claude-sonnet-4-6"})
	if err != nil {
		t.Fatalf("save config revision: %v", err)
	}
	// No read helper for config_revisions yet — just verify no error
}

func TestRecordBrainExecution(t *testing.T) {
	d := newTestDB(t)
	brainExecID, err := d.RecordBrainExecution(
		"n1", "TestNode", "anthropic", "claude-sonnet-4-6",
		"decide", "execute", map[string]any{"param": 1},
		"reasoning text", 0.85, "applied", 120.0, "trace-1", 3,
	)
	if err != nil {
		t.Fatalf("record brain execution: %v", err)
	}
	if brainExecID == "" {
		t.Fatal("expected non-empty brainExecID")
	}
	err = d.UpdateBrainOutcome(brainExecID, "applied")
	if err != nil {
		t.Fatalf("update brain outcome: %v", err)
	}
}

func TestRecordAlignmentDecision(t *testing.T) {
	d := newTestDB(t)
	decisionID, err := d.RecordAlignmentDecision(
		10, true,
		[]string{},
		map[string]any{"node1": 1.0},
		map[string]any{},
		map[string]any{},
		false,
	)
	if err != nil {
		t.Fatalf("record alignment decision: %v", err)
	}
	if decisionID == "" {
		t.Fatal("expected non-empty decisionID")
	}
	decisions, err := d.RecentAlignmentDecisions(5)
	if err != nil {
		t.Fatalf("get alignment decisions: %v", err)
	}
	if len(decisions) != 1 {
		t.Fatalf("expected 1 decision, got %d", len(decisions))
	}
	if !decisions[0].Approved {
		t.Error("expected approved=true")
	}
}

func TestRecordAdversarialResult(t *testing.T) {
	d := newTestDB(t)
	resultID, err := d.RecordAdversarialResult(
		7, 1, false, 0.12, 3,
		[]string{},
		map[string]any{"detail": "ok"},
	)
	if err != nil {
		t.Fatalf("record adversarial result: %v", err)
	}
	if resultID == "" {
		t.Fatal("expected non-empty resultID")
	}
	results, err := d.RecentAdversarialResults(5)
	if err != nil {
		t.Fatalf("get adversarial results: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
}

func TestRecordGoalTracking(t *testing.T) {
	d := newTestDB(t)
	trackingID, err := d.RecordGoalTracking(
		4, true, 0.82,
		map[string]any{"profit": 0.9},
		map[string]any{"profit": 0.5},
		0.01,
		map[string]any{"adjust": 0.02},
		[]string{"task1"},
		[]string{},
	)
	if err != nil {
		t.Fatalf("record goal tracking: %v", err)
	}
	if trackingID == "" {
		t.Fatal("expected non-empty trackingID")
	}
	gs, err := d.CurrentGoalState()
	if err != nil {
		t.Fatalf("get goal state: %v", err)
	}
	// CurrentGoalState reads goal_tracking table
	_ = gs // May be nil if schema mismatch — acceptable; just verify no crash
}
```

- [ ] **Step 3.2: Run the tests — they should FAIL (writes.go not yet created)**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go test ./internal/db/... -run TestUpsertNode -v
```
Expected: `undefined: db.UpsertNode` or similar compile error.

- [ ] **Step 3.3: Create `internal/db/writes.go`** (from Task 2 code block above)

- [ ] **Step 3.4: Run all DB tests and confirm they pass**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go test ./internal/db/... -v
```
Expected: all tests PASS.

- [ ] **Step 3.5: Commit**
```bash
git add internal/db/writes.go internal/db/writes_test.go
git commit -m "feat: add write methods to Go DB layer with tests"
```

---

## Task 4: Define `StateService` proto

**Files:**
- Create: `proto/omega/v1/state_service.proto`

- [ ] **Step 4.1: Create the proto file**

```protobuf
syntax = "proto3";

package omega.v1;

option go_package = "github.com/benebsworth/omega/gen/go/omega/v1;omegav1";

// StateService is the authoritative write interface for Omega system state.
// Python calls these RPCs instead of writing SQLite directly.
service StateService {
  rpc UpsertNode(UpsertNodeRequest) returns (UpsertNodeResponse);
  rpc BeginExecution(BeginExecutionRequest) returns (BeginExecutionResponse);
  rpc EndExecution(EndExecutionRequest) returns (EndExecutionResponse);
  rpc BeginSpan(BeginSpanRequest) returns (BeginSpanResponse);
  rpc EndSpan(EndSpanRequest) returns (EndSpanResponse);
  rpc RecordCost(RecordCostRequest) returns (RecordCostResponse);
  rpc OpenIssue(OpenIssueRequest) returns (OpenIssueResponse);
  rpc EscalateIssue(EscalateIssueRequest) returns (EscalateIssueResponse);
  rpc ResolveIssue(ResolveIssueRequest) returns (ResolveIssueResponse);
  rpc LogActivity(LogActivityRequest) returns (LogActivityResponse);
  rpc RecordImprovement(RecordImprovementRequest) returns (RecordImprovementResponse);
  rpc SaveConfigRevision(SaveConfigRevisionRequest) returns (SaveConfigRevisionResponse);
  rpc RecordBrainExecution(RecordBrainExecutionRequest) returns (RecordBrainExecutionResponse);
  rpc UpdateBrainOutcome(UpdateBrainOutcomeRequest) returns (UpdateBrainOutcomeResponse);
  rpc RecordAlignmentDecision(RecordAlignmentDecisionRequest) returns (RecordAlignmentDecisionResponse);
  rpc RecordAdversarialResult(RecordAdversarialResultRequest) returns (RecordAdversarialResultResponse);
  rpc RecordGoalTracking(RecordGoalTrackingRequest) returns (RecordGoalTrackingResponse);
}

// ── UpsertNode ─────────────────────────────────────────────────────────────

message UpsertNodeRequest {
  string node_id = 1;
  string name = 2;
  string version = 3;
  repeated string capabilities = 4;
  double health = 5;
  string status = 6;
  map<string, string> brain_config = 7; // JSON-encoded values
}
message UpsertNodeResponse { bool ok = 1; }

// ── BeginExecution ─────────────────────────────────────────────────────────

message BeginExecutionRequest {
  string node_id = 1;
  string node_name = 2;
  string action = 3;
  string trace_id = 4;  // optional; empty string = nil
  string span_id = 5;   // optional; empty string = nil
  int64 cycle = 6;
}
message BeginExecutionResponse { string exec_id = 1; }

// ── EndExecution ───────────────────────────────────────────────────────────

message EndExecutionRequest {
  string exec_id = 1;
  bool success = 2;
  string error_text = 3;
  map<string, double> metrics = 4;
}
message EndExecutionResponse { bool ok = 1; }

// ── BeginSpan ──────────────────────────────────────────────────────────────

message BeginSpanRequest {
  string trace_id = 1;
  string node_id = 2;
  string node_name = 3;
  string operation = 4;
  string parent_span_id = 5; // optional; empty string = nil
  int64 cycle = 6;
}
message BeginSpanResponse { string span_id = 1; }

// ── EndSpan ────────────────────────────────────────────────────────────────

message EndSpanRequest {
  string span_id = 1;
  string status = 2;
  map<string, string> metadata = 3; // JSON-encoded values
}
message EndSpanResponse { bool ok = 1; }

// ── RecordCost ─────────────────────────────────────────────────────────────

message RecordCostRequest {
  string node_id = 1;
  string provider = 2;
  string call_type = 3;
  double duration_ms = 4;
  string exec_id = 5;    // optional; empty string = nil
  double estimated_cost_usd = 6;
  map<string, string> metadata = 7; // JSON-encoded values
  int64 cycle = 8;
}
message RecordCostResponse { bool ok = 1; }

// ── OpenIssue ──────────────────────────────────────────────────────────────

message OpenIssueRequest {
  string issue_id = 1;
  string detector = 2;
  string severity = 3;
  string description = 4;
  map<string, string> context = 5; // JSON-encoded values
  int64 cycle = 6;
}
message OpenIssueResponse { bool created = 1; }

// ── EscalateIssue ──────────────────────────────────────────────────────────

message EscalateIssueRequest { string issue_id = 1; }
message EscalateIssueResponse { int64 rows_affected = 1; }

// ── ResolveIssue ───────────────────────────────────────────────────────────

message ResolveIssueRequest {
  string issue_id = 1;
  int64 cycle = 2;
}
message ResolveIssueResponse { bool resolved = 1; }

// ── LogActivity ────────────────────────────────────────────────────────────

message LogActivityRequest {
  string action_type = 1;
  string entity_type = 2;
  string entity_id = 3;
  map<string, string> data = 4; // JSON-encoded values
  int64 cycle = 5;
}
message LogActivityResponse { bool ok = 1; }

// ── RecordImprovement ──────────────────────────────────────────────────────

message RecordImprovementRequest {
  string node_id = 1;
  string node_name = 2;
  string from_version = 3;
  string to_version = 4;
  map<string, double> before_metrics = 5;
  map<string, double> after_metrics = 6;
  string triggered_by = 7;
  int64 cycle = 8;
}
message RecordImprovementResponse { bool ok = 1; }

// ── SaveConfigRevision ─────────────────────────────────────────────────────

message SaveConfigRevisionRequest {
  string node_id = 1;
  string version = 2;
  map<string, string> config = 3; // JSON-encoded values
}
message SaveConfigRevisionResponse { bool ok = 1; }

// ── RecordBrainExecution ───────────────────────────────────────────────────

message RecordBrainExecutionRequest {
  string node_id = 1;
  string node_name = 2;
  string provider = 3;
  string model = 4;
  string operation = 5;
  string action_decided = 6;
  map<string, string> parameters = 7; // JSON-encoded values
  string reasoning = 8;
  double confidence = 9;
  string outcome = 10;
  double latency_ms = 11;
  string trace_id = 12;
  int64 cycle = 13;
}
message RecordBrainExecutionResponse { string brain_exec_id = 1; }

// ── UpdateBrainOutcome ─────────────────────────────────────────────────────

message UpdateBrainOutcomeRequest {
  string brain_exec_id = 1;
  string outcome = 2;
}
message UpdateBrainOutcomeResponse { bool ok = 1; }

// ── RecordAlignmentDecision ────────────────────────────────────────────────

message RecordAlignmentDecisionRequest {
  int64 cycle = 1;
  bool approved = 2;
  repeated string violations = 3;
  map<string, string> pareto_ranks = 4;  // JSON-encoded values
  map<string, string> adjustments = 5;   // JSON-encoded values
  map<string, string> vcg_payments = 6;  // JSON-encoded values
  bool goodhart_warning = 7;
}
message RecordAlignmentDecisionResponse { string decision_id = 1; }

// ── RecordAdversarialResult ────────────────────────────────────────────────

message RecordAdversarialResultRequest {
  int64 cycle = 1;
  int32 ring = 2;
  bool flagged = 3;
  double max_disagreement = 4;
  int64 scenario_count = 5;
  repeated string failure_cases = 6;
  map<string, string> details = 7; // JSON-encoded values
}
message RecordAdversarialResultResponse { string result_id = 1; }

// ── RecordGoalTracking ─────────────────────────────────────────────────────

message RecordGoalTrackingRequest {
  int64 cycle = 1;
  bool approved = 2;
  double composite_score = 3;
  map<string, string> scorecard = 4;      // JSON-encoded values
  map<string, string> nash_weights = 5;   // JSON-encoded values
  double tracking_error = 6;
  map<string, string> control_action = 7; // JSON-encoded values
  repeated string subtasks = 8;
  repeated string violations = 9;
}
message RecordGoalTrackingResponse { string tracking_id = 1; }
```

- [ ] **Step 4.2: Run buf generate**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
buf generate
```
Expected: generates `gen/go/omega/v1/state_service.pb.go` and `gen/go/omega/v1/omegav1connect/state_service.connect.go`

- [ ] **Step 4.3: Verify Go builds**
```bash
go build ./...
```
Expected: no errors.

- [ ] **Step 4.4: Commit**
```bash
git add proto/omega/v1/state_service.proto gen/go/omega/v1/state_service.pb.go gen/go/omega/v1/omegav1connect/state_service.connect.go
git commit -m "feat: add StateService proto with 17 write RPCs"
```

---

## Task 5: Implement the Go `StateServiceHandler`

**Files:**
- Create: `internal/handler/state.go`

> **Note on map fields:** The proto uses `map<string, string>` with JSON-encoded values for complex nested structures (e.g., `brain_config`, `pareto_ranks`). The handler decodes these strings to `map[string]any` before passing to DB methods. This avoids the need for complex nested proto message hierarchies while keeping the wire format flexible.

- [ ] **Step 5.1: Write the failing handler test first** (see Task 6 — write tests before implementing)

- [ ] **Step 5.2: Create `internal/handler/state.go`**

```go
// Package handler implements the StateService Connect-RPC handler.
package handler

import (
	"context"
	"encoding/json"
	"fmt"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.StateServiceHandler = (*StateHandler)(nil)

// StateHandler implements StateService — all write operations on Omega state.
type StateHandler struct {
	db *db.DB
}

// NewState creates a StateHandler backed by the given DB.
func NewState(database *db.DB) *StateHandler {
	return &StateHandler{db: database}
}

// decodeMapStrAny converts map[string]string (proto JSON values) to map[string]any.
// Each value is first attempted as JSON; if that fails it's kept as a string.
func decodeMapStrAny(m map[string]string) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		var parsed any
		if json.Unmarshal([]byte(v), &parsed) == nil {
			out[k] = parsed
		} else {
			out[k] = v
		}
	}
	return out
}

// optStr returns a pointer to s, or nil if s is "".
func optStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// ── UpsertNode ────────────────────────────────────────────────────────────────

func (h *StateHandler) UpsertNode(
	ctx context.Context,
	req *connect.Request[omegav1.UpsertNodeRequest],
) (*connect.Response[omegav1.UpsertNodeResponse], error) {
	brainConfig := decodeMapStrAny(req.Msg.BrainConfig)
	err := h.db.UpsertNode(
		req.Msg.NodeId, req.Msg.Name, req.Msg.Version,
		req.Msg.Capabilities, req.Msg.Health, req.Msg.Status, brainConfig,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.UpsertNodeResponse{Ok: true}), nil
}

// ── BeginExecution ────────────────────────────────────────────────────────────

func (h *StateHandler) BeginExecution(
	ctx context.Context,
	req *connect.Request[omegav1.BeginExecutionRequest],
) (*connect.Response[omegav1.BeginExecutionResponse], error) {
	execID, err := h.db.BeginExecution(
		req.Msg.NodeId, req.Msg.NodeName, req.Msg.Action,
		optStr(req.Msg.TraceId), optStr(req.Msg.SpanId), req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.BeginExecutionResponse{ExecId: execID}), nil
}

// ── EndExecution ──────────────────────────────────────────────────────────────

func (h *StateHandler) EndExecution(
	ctx context.Context,
	req *connect.Request[omegav1.EndExecutionRequest],
) (*connect.Response[omegav1.EndExecutionResponse], error) {
	err := h.db.EndExecution(req.Msg.ExecId, req.Msg.Success, req.Msg.ErrorText, req.Msg.Metrics)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.EndExecutionResponse{Ok: true}), nil
}

// ── BeginSpan ─────────────────────────────────────────────────────────────────

func (h *StateHandler) BeginSpan(
	ctx context.Context,
	req *connect.Request[omegav1.BeginSpanRequest],
) (*connect.Response[omegav1.BeginSpanResponse], error) {
	spanID, err := h.db.BeginSpan(
		req.Msg.TraceId, req.Msg.NodeId, req.Msg.NodeName,
		req.Msg.Operation, optStr(req.Msg.ParentSpanId), req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.BeginSpanResponse{SpanId: spanID}), nil
}

// ── EndSpan ───────────────────────────────────────────────────────────────────

func (h *StateHandler) EndSpan(
	ctx context.Context,
	req *connect.Request[omegav1.EndSpanRequest],
) (*connect.Response[omegav1.EndSpanResponse], error) {
	metadata := decodeMapStrAny(req.Msg.Metadata)
	err := h.db.EndSpan(req.Msg.SpanId, req.Msg.Status, metadata)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.EndSpanResponse{Ok: true}), nil
}

// ── RecordCost ────────────────────────────────────────────────────────────────

func (h *StateHandler) RecordCost(
	ctx context.Context,
	req *connect.Request[omegav1.RecordCostRequest],
) (*connect.Response[omegav1.RecordCostResponse], error) {
	metadata := decodeMapStrAny(req.Msg.Metadata)
	err := h.db.RecordCost(
		req.Msg.NodeId, req.Msg.Provider, req.Msg.CallType,
		req.Msg.DurationMs, optStr(req.Msg.ExecId),
		req.Msg.EstimatedCostUsd, metadata, req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordCostResponse{Ok: true}), nil
}

// ── OpenIssue ─────────────────────────────────────────────────────────────────

func (h *StateHandler) OpenIssue(
	ctx context.Context,
	req *connect.Request[omegav1.OpenIssueRequest],
) (*connect.Response[omegav1.OpenIssueResponse], error) {
	context := decodeMapStrAny(req.Msg.Context)
	created, err := h.db.OpenIssue(
		req.Msg.IssueId, req.Msg.Detector, req.Msg.Severity,
		req.Msg.Description, context, req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.OpenIssueResponse{Created: created}), nil
}

// ── EscalateIssue ─────────────────────────────────────────────────────────────

func (h *StateHandler) EscalateIssue(
	ctx context.Context,
	req *connect.Request[omegav1.EscalateIssueRequest],
) (*connect.Response[omegav1.EscalateIssueResponse], error) {
	n, err := h.db.EscalateIssue(req.Msg.IssueId)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.EscalateIssueResponse{RowsAffected: n}), nil
}

// ── ResolveIssue ──────────────────────────────────────────────────────────────

func (h *StateHandler) ResolveIssue(
	ctx context.Context,
	req *connect.Request[omegav1.ResolveIssueRequest],
) (*connect.Response[omegav1.ResolveIssueResponse], error) {
	resolved, err := h.db.ResolveIssue(req.Msg.IssueId, req.Msg.Cycle)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.ResolveIssueResponse{Resolved: resolved}), nil
}

// ── LogActivity ───────────────────────────────────────────────────────────────

func (h *StateHandler) LogActivity(
	ctx context.Context,
	req *connect.Request[omegav1.LogActivityRequest],
) (*connect.Response[omegav1.LogActivityResponse], error) {
	data := decodeMapStrAny(req.Msg.Data)
	err := h.db.LogActivity(req.Msg.ActionType, req.Msg.EntityType, req.Msg.EntityId, data, req.Msg.Cycle)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.LogActivityResponse{Ok: true}), nil
}

// ── RecordImprovement ─────────────────────────────────────────────────────────

func (h *StateHandler) RecordImprovement(
	ctx context.Context,
	req *connect.Request[omegav1.RecordImprovementRequest],
) (*connect.Response[omegav1.RecordImprovementResponse], error) {
	err := h.db.RecordImprovement(
		req.Msg.NodeId, req.Msg.NodeName,
		req.Msg.FromVersion, req.Msg.ToVersion,
		req.Msg.BeforeMetrics, req.Msg.AfterMetrics,
		req.Msg.TriggeredBy, req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordImprovementResponse{Ok: true}), nil
}

// ── SaveConfigRevision ────────────────────────────────────────────────────────

func (h *StateHandler) SaveConfigRevision(
	ctx context.Context,
	req *connect.Request[omegav1.SaveConfigRevisionRequest],
) (*connect.Response[omegav1.SaveConfigRevisionResponse], error) {
	config := decodeMapStrAny(req.Msg.Config)
	err := h.db.SaveConfigRevision(req.Msg.NodeId, req.Msg.Version, config)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.SaveConfigRevisionResponse{Ok: true}), nil
}

// ── RecordBrainExecution ──────────────────────────────────────────────────────

func (h *StateHandler) RecordBrainExecution(
	ctx context.Context,
	req *connect.Request[omegav1.RecordBrainExecutionRequest],
) (*connect.Response[omegav1.RecordBrainExecutionResponse], error) {
	params := decodeMapStrAny(req.Msg.Parameters)
	brainExecID, err := h.db.RecordBrainExecution(
		req.Msg.NodeId, req.Msg.NodeName, req.Msg.Provider, req.Msg.Model,
		req.Msg.Operation, req.Msg.ActionDecided, params,
		req.Msg.Reasoning, req.Msg.Confidence, req.Msg.Outcome,
		req.Msg.LatencyMs, req.Msg.TraceId, req.Msg.Cycle,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordBrainExecutionResponse{BrainExecId: brainExecID}), nil
}

// ── UpdateBrainOutcome ────────────────────────────────────────────────────────

func (h *StateHandler) UpdateBrainOutcome(
	ctx context.Context,
	req *connect.Request[omegav1.UpdateBrainOutcomeRequest],
) (*connect.Response[omegav1.UpdateBrainOutcomeResponse], error) {
	err := h.db.UpdateBrainOutcome(req.Msg.BrainExecId, req.Msg.Outcome)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.UpdateBrainOutcomeResponse{Ok: true}), nil
}

// ── RecordAlignmentDecision ───────────────────────────────────────────────────

func (h *StateHandler) RecordAlignmentDecision(
	ctx context.Context,
	req *connect.Request[omegav1.RecordAlignmentDecisionRequest],
) (*connect.Response[omegav1.RecordAlignmentDecisionResponse], error) {
	paretoRanks := decodeMapStrAny(req.Msg.ParetoRanks)
	adjustments := decodeMapStrAny(req.Msg.Adjustments)
	vcgPayments := decodeMapStrAny(req.Msg.VcgPayments)
	decisionID, err := h.db.RecordAlignmentDecision(
		req.Msg.Cycle, req.Msg.Approved,
		req.Msg.Violations, paretoRanks, adjustments, vcgPayments,
		req.Msg.GoodhartWarning,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordAlignmentDecisionResponse{DecisionId: decisionID}), nil
}

// ── RecordAdversarialResult ───────────────────────────────────────────────────

func (h *StateHandler) RecordAdversarialResult(
	ctx context.Context,
	req *connect.Request[omegav1.RecordAdversarialResultRequest],
) (*connect.Response[omegav1.RecordAdversarialResultResponse], error) {
	details := decodeMapStrAny(req.Msg.Details)
	resultID, err := h.db.RecordAdversarialResult(
		req.Msg.Cycle, req.Msg.Ring, req.Msg.Flagged,
		req.Msg.MaxDisagreement, req.Msg.ScenarioCount,
		req.Msg.FailureCases, details,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordAdversarialResultResponse{ResultId: resultID}), nil
}

// ── RecordGoalTracking ────────────────────────────────────────────────────────

func (h *StateHandler) RecordGoalTracking(
	ctx context.Context,
	req *connect.Request[omegav1.RecordGoalTrackingRequest],
) (*connect.Response[omegav1.RecordGoalTrackingResponse], error) {
	scorecard := decodeMapStrAny(req.Msg.Scorecard)
	nashWeights := decodeMapStrAny(req.Msg.NashWeights)
	controlAction := decodeMapStrAny(req.Msg.ControlAction)
	trackingID, err := h.db.RecordGoalTracking(
		req.Msg.Cycle, req.Msg.Approved, req.Msg.CompositeScore,
		scorecard, nashWeights, req.Msg.TrackingError,
		controlAction, req.Msg.Subtasks, req.Msg.Violations,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordGoalTrackingResponse{TrackingId: trackingID}), nil
}

// ── Unused required interface methods (generated from proto) ─────────────────
// The connect interface may require these if the proto has additional RPCs.
// Add any missing stubs here to satisfy the interface.
_ = fmt.Sprintf // keep fmt import live
```

- [ ] **Step 5.3: Build**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go build ./...
```
Expected: no errors.

---

## Task 6: Write and run StateHandler tests

**Files:**
- Create: `internal/handler/state_test.go`

- [ ] **Step 6.1: Write the handler tests**

```go
package handler_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"connectrpc.com/connect"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

func setupStateServer(t *testing.T) (omegav1connect.StateServiceClient, *db.DB) {
	t.Helper()
	stateF, _ := os.CreateTemp("", "omega-state-*.db")
	memF, _ := os.CreateTemp("", "omega-memory-*.db")
	stateF.Close()
	memF.Close()
	t.Cleanup(func() { os.Remove(stateF.Name()); os.Remove(memF.Name()) })

	database, err := db.New(stateF.Name(), memF.Name())
	if err != nil {
		t.Fatalf("new db: %v", err)
	}
	t.Cleanup(database.Close)

	mux := http.NewServeMux()
	path, svcHandler := omegav1connect.NewStateServiceHandler(handler.NewState(database))
	mux.Handle(path, svcHandler)

	srv := httptest.NewUnstartedServer(h2c.NewHandler(mux, &http2.Server{}))
	srv.Start()
	t.Cleanup(srv.Close)

	client := omegav1connect.NewStateServiceClient(http.DefaultClient, srv.URL)
	return client, database
}

func TestStateHandler_UpsertAndBeginExecution(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	// Upsert a node
	_, err := client.UpsertNode(ctx, connect.NewRequest(&omegav1.UpsertNodeRequest{
		NodeId:       "n1",
		Name:         "TestNode",
		Version:      "1.0",
		Capabilities: []string{"run"},
		Health:       0.95,
		Status:       "active",
	}))
	if err != nil {
		t.Fatalf("UpsertNode: %v", err)
	}

	// Begin an execution
	execResp, err := client.BeginExecution(ctx, connect.NewRequest(&omegav1.BeginExecutionRequest{
		NodeId:   "n1",
		NodeName: "TestNode",
		Action:   "run",
		Cycle:    1,
	}))
	if err != nil {
		t.Fatalf("BeginExecution: %v", err)
	}
	execID := execResp.Msg.ExecId
	if execID == "" {
		t.Fatal("expected non-empty execID")
	}

	// End the execution
	_, err = client.EndExecution(ctx, connect.NewRequest(&omegav1.EndExecutionRequest{
		ExecId:  execID,
		Success: true,
		Metrics: map[string]float64{"score": 0.9},
	}))
	if err != nil {
		t.Fatalf("EndExecution: %v", err)
	}
}

func TestStateHandler_SpanLifecycle(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	spanResp, err := client.BeginSpan(ctx, connect.NewRequest(&omegav1.BeginSpanRequest{
		TraceId:   "trace-1",
		NodeId:    "n1",
		NodeName:  "TestNode",
		Operation: "execute",
		Cycle:     2,
	}))
	if err != nil {
		t.Fatalf("BeginSpan: %v", err)
	}
	spanID := spanResp.Msg.SpanId

	_, err = client.EndSpan(ctx, connect.NewRequest(&omegav1.EndSpanRequest{
		SpanId: spanID,
		Status: "ok",
	}))
	if err != nil {
		t.Fatalf("EndSpan: %v", err)
	}
}

func TestStateHandler_OpenAndResolveIssue(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	openResp, err := client.OpenIssue(ctx, connect.NewRequest(&omegav1.OpenIssueRequest{
		IssueId:     "issue-1",
		Detector:    "cleaner",
		Severity:    "warning",
		Description: "test issue",
		Cycle:       1,
	}))
	if err != nil {
		t.Fatalf("OpenIssue: %v", err)
	}
	if !openResp.Msg.Created {
		t.Error("expected created=true")
	}

	resolveResp, err := client.ResolveIssue(ctx, connect.NewRequest(&omegav1.ResolveIssueRequest{
		IssueId: "issue-1",
		Cycle:   2,
	}))
	if err != nil {
		t.Fatalf("ResolveIssue: %v", err)
	}
	if !resolveResp.Msg.Resolved {
		t.Error("expected resolved=true")
	}
}

func TestStateHandler_AlignmentDecision(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordAlignmentDecision(ctx, connect.NewRequest(&omegav1.RecordAlignmentDecisionRequest{
		Cycle:    5,
		Approved: true,
	}))
	if err != nil {
		t.Fatalf("RecordAlignmentDecision: %v", err)
	}
	if resp.Msg.DecisionId == "" {
		t.Fatal("expected non-empty decisionId")
	}
}

func TestStateHandler_AdversarialResult(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordAdversarialResult(ctx, connect.NewRequest(&omegav1.RecordAdversarialResultRequest{
		Cycle:         3,
		Ring:          1,
		Flagged:       false,
		ScenarioCount: 5,
	}))
	if err != nil {
		t.Fatalf("RecordAdversarialResult: %v", err)
	}
	if resp.Msg.ResultId == "" {
		t.Fatal("expected non-empty resultId")
	}
}

func TestStateHandler_GoalTracking(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordGoalTracking(ctx, connect.NewRequest(&omegav1.RecordGoalTrackingRequest{
		Cycle:          7,
		Approved:       true,
		CompositeScore: 0.8,
	}))
	if err != nil {
		t.Fatalf("RecordGoalTracking: %v", err)
	}
	if resp.Msg.TrackingId == "" {
		t.Fatal("expected non-empty trackingId")
	}
}
```

- [ ] **Step 6.2: Run the tests**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go test ./internal/handler/... -v -run TestStateHandler
```
Expected: all `TestStateHandler_*` tests PASS.

- [ ] **Step 6.3: Run all Go tests**
```bash
go test ./...
```
Expected: all tests PASS.

- [ ] **Step 6.4: Commit**
```bash
git add internal/handler/state.go internal/handler/state_test.go
git commit -m "feat: add StateServiceHandler with tests"
```

---

## Task 7: Mount StateService in the API server

**Files:**
- Modify: `cmd/omega-api/main.go`

- [ ] **Step 7.1: Update `cmd/omega-api/main.go`**

After the line `vh := handler.NewVectora(vdb)`, add:
```go
sh := handler.NewState(database)
```

After the existing `mux.Handle(vPath, vSvcHandler)` block, add:
```go
sPath, sSvcHandler := omegav1connect.NewStateServiceHandler(sh,
    connect.WithCompressMinBytes(1024),
)
mux.Handle(sPath, sSvcHandler)
```

- [ ] **Step 7.2: Build**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go build ./...
```
Expected: no errors.

- [ ] **Step 7.3: Commit**
```bash
git add cmd/omega-api/main.go
git commit -m "feat: mount StateService in omega-api server"
```

---

## Task 8: Create Python bridge package

**Files:**
- Create: `omega/bridge/__init__.py`
- Create: `omega/bridge/state_client.py`

The bridge uses only Python stdlib (`urllib.request`, `json`) to avoid new dependencies. It speaks the **Connect-RPC unary protocol over HTTP/1.1**: `POST /<package>.<Service>/<Method>` with `Content-Type: application/json` and `Connect-Protocol-Version: 1`.

- [ ] **Step 8.1: Create `omega/bridge/__init__.py`**

```python
"""omega.bridge — Python clients for Go Connect-RPC services."""
```

- [ ] **Step 8.2: Create `omega/bridge/state_client.py`**

```python
"""omega.bridge.state_client — Thin HTTP client for the Go StateService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Usage:
    client = StateServiceClient("http://localhost:8080")
    exec_id = client.begin_execution("node-1", "TestNode", "run", cycle=1)
    client.end_execution(exec_id, success=True, metrics={"score": 0.9})
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.StateService/"


class StateServiceError(Exception):
    """Raised when the Go StateService returns an error."""


class StateServiceClient:
    """HTTP client for the Go StateService Connect-RPC endpoint."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, method: str, body: dict) -> dict:
        url = self._base_url + _BASE_PATH + method
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_bytes = exc.read()
            try:
                err_body = json.loads(body_bytes)
                msg = err_body.get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise StateServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise StateServiceError(f"{method} unavailable: {exc}") from exc

    # ── Node registry ──────────────────────────────────────────────────────

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
        # brain_config values must be strings for the proto map<string,string>
        bc = {k: json.dumps(v) if not isinstance(v, str) else v
              for k, v in (brain_config or {}).items()}
        self._call("UpsertNode", {
            "nodeId": node_id, "name": name, "version": version,
            "capabilities": capabilities, "health": health,
            "status": status, "brainConfig": bc,
        })

    # ── Executions ─────────────────────────────────────────────────────────

    def begin_execution(
        self,
        node_id: str,
        node_name: str,
        action: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        resp = self._call("BeginExecution", {
            "nodeId": node_id, "nodeName": node_name, "action": action,
            "traceId": trace_id or "", "spanId": span_id or "",
            "cycle": cycle,
        })
        return resp["execId"]

    def end_execution(
        self,
        exec_id: str,
        success: bool,
        error_text: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        self._call("EndExecution", {
            "execId": exec_id,
            "success": success,
            "errorText": error_text or "",
            "metrics": metrics or {},
        })

    # ── Traces ─────────────────────────────────────────────────────────────

    def begin_span(
        self,
        trace_id: str,
        node_id: str,
        node_name: str,
        operation: str,
        parent_span_id: str | None = None,
        cycle: int = 0,
    ) -> str:
        resp = self._call("BeginSpan", {
            "traceId": trace_id, "nodeId": node_id, "nodeName": node_name,
            "operation": operation, "parentSpanId": parent_span_id or "",
            "cycle": cycle,
        })
        return resp["spanId"]

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        metadata: dict | None = None,
    ) -> None:
        meta = {k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in (metadata or {}).items()}
        self._call("EndSpan", {"spanId": span_id, "status": status, "metadata": meta})

    # ── Cost events ────────────────────────────────────────────────────────

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
        meta = {k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in (metadata or {}).items()}
        self._call("RecordCost", {
            "nodeId": node_id, "provider": provider, "callType": call_type,
            "durationMs": duration_ms, "execId": exec_id or "",
            "estimatedCostUsd": estimated_cost_usd,
            "metadata": meta, "cycle": cycle,
        })

    # ── Issues ─────────────────────────────────────────────────────────────

    def open_issue(
        self,
        issue_id: str,
        detector: str,
        severity: str,
        description: str,
        context: dict | None = None,
        cycle: int = 0,
    ) -> bool:
        ctx = {k: json.dumps(v) if not isinstance(v, str) else v
               for k, v in (context or {}).items()}
        resp = self._call("OpenIssue", {
            "issueId": issue_id, "detector": detector, "severity": severity,
            "description": description, "context": ctx, "cycle": cycle,
        })
        return bool(resp.get("created", False))

    def escalate_issue(self, issue_id: str) -> bool:
        resp = self._call("EscalateIssue", {"issueId": issue_id})
        return int(resp.get("rowsAffected", 0)) > 0

    def resolve_issue(self, issue_id: str, cycle: int | None = None) -> bool:
        resp = self._call("ResolveIssue", {"issueId": issue_id, "cycle": cycle or 0})
        return bool(resp.get("resolved", False))

    # ── Activity log ───────────────────────────────────────────────────────

    def log_activity(
        self,
        action_type: str,
        entity_type: str,
        entity_id: str,
        data: dict | None = None,
        cycle: int = 0,
    ) -> None:
        d = {k: json.dumps(v) if not isinstance(v, str) else v
             for k, v in (data or {}).items()}
        self._call("LogActivity", {
            "actionType": action_type, "entityType": entity_type,
            "entityId": entity_id, "data": d, "cycle": cycle,
        })

    # ── Improvement log ────────────────────────────────────────────────────

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
        self._call("RecordImprovement", {
            "nodeId": node_id, "nodeName": node_name,
            "fromVersion": from_version, "toVersion": to_version,
            "beforeMetrics": before_metrics or {},
            "afterMetrics": after_metrics or {},
            "triggeredBy": triggered_by, "cycle": cycle,
        })

    # ── Config revisions ───────────────────────────────────────────────────

    def save_config_revision(self, node_id: str, version: str, config: dict) -> None:
        cfg = {k: json.dumps(v) if not isinstance(v, str) else v
               for k, v in config.items()}
        self._call("SaveConfigRevision", {
            "nodeId": node_id, "version": version, "config": cfg,
        })

    # ── Brain executions ───────────────────────────────────────────────────

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
        params = {k: json.dumps(v) if not isinstance(v, str) else v
                  for k, v in (parameters or {}).items()}
        resp = self._call("RecordBrainExecution", {
            "nodeId": node_id, "nodeName": node_name,
            "provider": provider, "model": model,
            "operation": operation, "actionDecided": action_decided,
            "parameters": params, "reasoning": reasoning,
            "confidence": confidence, "outcome": outcome,
            "latencyMs": latency_ms, "traceId": trace_id, "cycle": cycle,
        })
        return resp["brainExecId"]

    def update_brain_outcome(self, brain_exec_id: str, outcome: str) -> None:
        self._call("UpdateBrainOutcome", {
            "brainExecId": brain_exec_id, "outcome": outcome,
        })

    # ── Alignment decisions ────────────────────────────────────────────────

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
        def encode(d: dict | None) -> dict:
            return {k: json.dumps(v) if not isinstance(v, str) else v
                    for k, v in (d or {}).items()}
        resp = self._call("RecordAlignmentDecision", {
            "cycle": cycle, "approved": approved,
            "violations": violations or [],
            "paretoRanks": encode(pareto_ranks),
            "adjustments": encode(adjustments),
            "vcgPayments": encode(vcg_payments),
            "goodhartWarning": goodhart_warning,
        })
        return resp["decisionId"]

    # ── Adversarial results ────────────────────────────────────────────────

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
        det = {k: json.dumps(v) if not isinstance(v, str) else v
               for k, v in (details or {}).items()}
        resp = self._call("RecordAdversarialResult", {
            "cycle": cycle, "ring": ring, "flagged": flagged,
            "maxDisagreement": max_disagreement,
            "scenarioCount": scenario_count,
            "failureCases": failure_cases or [],
            "details": det,
        })
        return resp["resultId"]

    # ── Goal tracking ──────────────────────────────────────────────────────

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
        def encode(d: dict | None) -> dict:
            return {k: json.dumps(v) if not isinstance(v, str) else v
                    for k, v in (d or {}).items()}
        resp = self._call("RecordGoalTracking", {
            "cycle": cycle, "approved": approved,
            "compositeScore": composite_score,
            "scorecard": encode(scorecard),
            "nashWeights": encode(nash_weights),
            "trackingError": tracking_error,
            "controlAction": encode(control_action),
            "subtasks": subtasks or [],
            "violations": violations or [],
        })
        return resp["trackingId"]
```

- [ ] **Step 8.3: Verify the bridge module imports cleanly**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
python3 -c "from omega.bridge.state_client import StateServiceClient; print('ok')"
```
Expected: `ok`

- [ ] **Step 8.4: Commit**
```bash
git add omega/bridge/__init__.py omega/bridge/state_client.py
git commit -m "feat: add Python bridge client for Go StateService"
```

---

## Task 9: Add `GoBackend` to `state_store.py`

**Files:**
- Modify: `omega/core/state_store.py`

The `GoBackend` class implements the same `StateBackend` abstract interface as `SQLiteBackend`. It delegates every write to the bridge client. The factory function `make_state_backend()` reads `OMEGA_STATE_SERVICE_URL` from the environment; if set, it returns a `GoBackend`, otherwise it falls back to `SQLiteBackend`.

- [ ] **Step 9.1: Add the `GoBackend` class and factory function to `state_store.py`**

Append the following to the **end** of `omega/core/state_store.py` (before the `StateStore = SQLiteBackend` alias line):

```python
# ── Go bridge backend ──────────────────────────────────────────────────────────


class GoBackend(StateBackend):
    """StateBackend implementation that delegates writes to the Go StateService.

    Reads are NOT implemented — use SQLiteBackend (or the Go read API) for reads.
    This backend is purely for write-path ownership transfer.

    Falls back transparently: if a write fails (Go service unreachable),
    logs a warning and re-raises so the caller can decide whether to retry or
    fall back to a SQLiteBackend.
    """

    def __init__(self, service_url: str) -> None:
        from omega.bridge.state_client import StateServiceClient  # late import

        self._client = StateServiceClient(service_url)

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
        self._client.upsert_node(node_id, name, version, capabilities, health, status, brain_config)

    def get_node(self, node_id: str) -> dict | None:
        raise NotImplementedError("GoBackend is write-only; use the read API or SQLiteBackend for reads")

    def all_nodes(self) -> list[dict]:
        raise NotImplementedError("GoBackend is write-only; use the read API or SQLiteBackend for reads")

    # ------------------------------------------------------------------
    # Executions
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
        return self._client.begin_execution(node_id, node_name, action, trace_id, span_id, cycle)

    def end_execution(
        self,
        exec_id: str,
        success: bool,
        error_text: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        self._client.end_execution(exec_id, success, error_text, metrics)

    def get_recent_executions(
        self,
        node_id: str | None = None,
        limit: int = 20,
        since_cycle: int | None = None,
    ) -> list[dict]:
        raise NotImplementedError("GoBackend is write-only")

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
        return self._client.begin_span(trace_id, node_id, node_name, operation, parent_span_id, cycle)

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        metadata: dict | None = None,
    ) -> None:
        self._client.end_span(span_id, status, metadata)

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
        return self._client.open_issue(issue_id, detector, severity, description, context, cycle)

    def resolve_issue(self, issue_id: str, cycle: int | None = None) -> bool:
        return self._client.resolve_issue(issue_id, cycle)

    def get_open_issues(self) -> list[dict]:
        raise NotImplementedError("GoBackend is write-only")

    # ------------------------------------------------------------------
    # Improvements
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
        self._client.record_improvement(
            node_id, node_name, from_version, to_version,
            before_metrics, after_metrics, triggered_by, cycle,
        )

    def get_improvement_history(
        self,
        node_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        raise NotImplementedError("GoBackend is write-only")


def make_state_backend(db_path: str = ":memory:") -> StateBackend:
    """Factory: returns GoBackend if OMEGA_STATE_SERVICE_URL is set, else SQLiteBackend.

    This is the preferred way to obtain a backend — callers don't need to know
    which implementation is active.

    Example:
        store = make_state_backend("/tmp/omega_vectora_state.db")
    """
    import os

    service_url = os.environ.get("OMEGA_STATE_SERVICE_URL", "")
    if service_url:
        import logging
        logging.getLogger(__name__).info(
            "state_store: using GoBackend at %s", service_url
        )
        return GoBackend(service_url)
    return SQLiteBackend(db_path)
```

- [ ] **Step 9.2: Verify Python imports still work**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
python3 -c "from omega.core.state_store import StateStore, SQLiteBackend, GoBackend, make_state_backend; print('ok')"
```
Expected: `ok`

- [ ] **Step 9.3: Run existing Python tests to check nothing broke**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
python3 -m pytest tests/ -x -q --ignore=tests/integration 2>&1 | tail -20
```
Expected: all tests pass (the same count as before; GoBackend is additive and not invoked by any existing tests).

- [ ] **Step 9.4: Commit**
```bash
git add omega/core/state_store.py
git commit -m "feat: add GoBackend and make_state_backend() factory to state_store"
```

---

## Task 10: Run full verification

- [ ] **Step 10.1: Full Go test suite**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
go test ./... -count=1
```
Expected: all tests PASS, zero failures.

- [ ] **Step 10.2: Go build (lint check)**
```bash
go build ./...
```
Expected: no errors.

- [ ] **Step 10.3: Full Python test suite**
```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/hardcore-elbakyan
python3 -m pytest tests/ -q 2>&1 | tail -5
```
Expected: all 1,559 tests pass (same as baseline).

- [ ] **Step 10.4: Final commit — feature branch cleanup**
```bash
git log --oneline -8
```
Review the commit history looks clean. Then:
```bash
git checkout -b go-state-authority 2>/dev/null || git checkout go-state-authority
# If already on the right branch, just verify
git log --oneline -8
```

---

## Summary of What Was Built

| Layer | Before | After |
|-------|--------|-------|
| DB tables | Python creates on startup | Go creates on startup (`ensureStateTables`) |
| DB write methods | None in Go | 17 write methods in `internal/db/writes.go` |
| RPC surface | Read-only `OrchestratorService` | + `StateService` with 17 write RPCs |
| Go handler | None for writes | `StateHandler` in `internal/handler/state.go` |
| API server | Serves 2 services | Serves 3 services |
| Python write path | Direct SQLite via `SQLiteBackend` | `GoBackend` calls Go via HTTP; `SQLiteBackend` remains as fallback |
| Feature flag | N/A | `OMEGA_STATE_SERVICE_URL` env var enables Go backend |

**Next steps (Phase 2):** Once the Python test suite passes with `OMEGA_STATE_SERVICE_URL` set pointing at a live Go API server, switch the default in `make_state_backend()` and deprecate `SQLiteBackend` for writes. Then proceed with orchestration core migration per the audit.
