package db

import (
	"database/sql"
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// unixNow returns the current time as a float64 Unix timestamp (seconds + fractional).
func unixNow() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}

// ── Node registry ──────────────────────────────────────────────────────────────

// UpsertNode inserts or updates a node record. On conflict, preserves registered_at.
func (d *DB) UpsertNode(nodeID, name, version string, capabilities []string, health float64, status string, brainConfig map[string]any) error {
	capsJSON, _ := json.Marshal(capabilities)
	brainJSON, _ := json.Marshal(brainConfig)
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO nodes (node_id, name, version, capabilities_json, health, status, brain_config_json, registered_at, last_updated)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(node_id) DO UPDATE SET
			name=excluded.name,
			version=excluded.version,
			capabilities_json=excluded.capabilities_json,
			health=excluded.health,
			status=excluded.status,
			brain_config_json=excluded.brain_config_json,
			last_updated=excluded.last_updated`,
		nodeID, name, version, string(capsJSON), health, status, string(brainJSON), now, now)
	return err
}

// ── Executions ────────────────────────────────────────────────────────────────

// BeginExecution inserts a new execution row and returns its exec_id.
// traceID and spanID may be nil to store NULL.
func (d *DB) BeginExecution(nodeID, nodeName, action string, traceID, spanID *string, cycle int64) (string, error) {
	execID := uuid.New().String()
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO node_executions (exec_id, node_id, node_name, trace_id, span_id, action, started_at, success, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)`,
		execID, nodeID, nodeName, traceID, spanID, action, now, cycle)
	if err != nil {
		return "", err
	}
	return execID, nil
}

// EndExecution updates an existing execution row with outcome, duration, and metrics.
func (d *DB) EndExecution(execID string, success bool, errorText string, metrics map[string]float64) error {
	now := unixNow()
	var startedAt float64
	if err := d.state.QueryRow(`SELECT started_at FROM node_executions WHERE exec_id = ?`, execID).Scan(&startedAt); err != nil {
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
// parentSpanID may be nil to store NULL.
func (d *DB) BeginSpan(traceID, nodeID, nodeName, operation string, parentSpanID *string, cycle int64) (string, error) {
	spanID := uuid.New().String()
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO traces (span_id, trace_id, parent_span_id, node_id, node_name, operation, started_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		spanID, traceID, parentSpanID, nodeID, nodeName, operation, now, cycle)
	if err != nil {
		return "", err
	}
	return spanID, nil
}

// EndSpan updates a span with its final status and metadata.
func (d *DB) EndSpan(spanID, status string, metadata map[string]any) error {
	now := unixNow()
	var startedAt float64
	if err := d.state.QueryRow(`SELECT started_at FROM traces WHERE span_id = ?`, spanID).Scan(&startedAt); err != nil {
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

// RecordCost inserts a cost event. execID may be nil.
func (d *DB) RecordCost(nodeID, provider, callType string, durationMS float64, execID *string, estimatedCostUSD float64, metadata map[string]any, cycle int64) error {
	costID := uuid.New().String()
	metaJSON, _ := json.Marshal(metadata)
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO cost_events (cost_id, node_id, exec_id, provider, call_type, duration_ms, estimated_cost_usd, metadata_json, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		costID, nodeID, execID, provider, callType, durationMS, estimatedCostUSD, string(metaJSON), now, cycle)
	return err
}

// ── Issues ────────────────────────────────────────────────────────────────────

// OpenIssue inserts a new issue.
// Returns (true, nil) if created; (false, nil) if already existed (existing pending → escalated).
func (d *DB) OpenIssue(issueID, detector, severity, description string, context map[string]any, cycle int64) (bool, error) {
	var existingState string
	err := d.state.QueryRow(`SELECT state FROM issues WHERE issue_id = ?`, issueID).Scan(&existingState)
	if err == nil {
		// Already exists
		if existingState == "pending" {
			if _, err2 := d.EscalateIssue(issueID); err2 != nil {
				return false, err2
			}
		}
		return false, nil
	}
	if err != sql.ErrNoRows {
		return false, err
	}
	ctxJSON, _ := json.Marshal(context)
	now := unixNow()
	if _, err = d.state.Exec(`
		INSERT INTO issues (issue_id, detector, severity, description, context_json, state, opened_at, cycle_opened)
		VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)`,
		issueID, detector, severity, description, string(ctxJSON), now, cycle); err != nil {
		return false, err
	}
	return true, d.LogActivity("issue_opened", "issue", issueID, map[string]any{"severity": severity, "detector": detector}, cycle)
}

// EscalateIssue promotes a pending issue to active. Returns rows affected.
func (d *DB) EscalateIssue(issueID string) (int64, error) {
	res, err := d.state.Exec(`UPDATE issues SET state='active' WHERE issue_id=? AND state='pending'`, issueID)
	if err != nil {
		return 0, err
	}
	n, _ := res.RowsAffected()
	return n, nil
}

// ResolveIssue marks an issue resolved. Returns true if a row was updated.
func (d *DB) ResolveIssue(issueID string, cycle int64) (bool, error) {
	now := unixNow()
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

// LogActivity appends an immutable entry to the activity log.
func (d *DB) LogActivity(actionType, entityType, entityID string, data map[string]any, cycle int64) error {
	logID := uuid.New().String()
	dataJSON, _ := json.Marshal(data)
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO activity_log (log_id, action_type, entity_type, entity_id, data_json, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?)`,
		logID, actionType, entityType, entityID, string(dataJSON), now, cycle)
	return err
}

// ── Improvement log ───────────────────────────────────────────────────────────

// RecordImprovement inserts an improvement record and appends an activity log entry.
func (d *DB) RecordImprovement(nodeID, nodeName, fromVersion, toVersion string, beforeMetrics, afterMetrics map[string]float64, triggeredBy string, cycle int64) error {
	improveID := uuid.New().String()
	beforeJSON, _ := json.Marshal(beforeMetrics)
	afterJSON, _ := json.Marshal(afterMetrics)
	now := unixNow()
	if _, err := d.state.Exec(`
		INSERT INTO improvement_log (improve_id, node_id, node_name, from_version, to_version, before_metrics_json, after_metrics_json, triggered_by, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		improveID, nodeID, nodeName, fromVersion, toVersion,
		string(beforeJSON), string(afterJSON), triggeredBy, now, cycle); err != nil {
		return err
	}
	return d.LogActivity("node_improved", "node", nodeID, map[string]any{
		"from_version": fromVersion, "to_version": toVersion, "triggered_by": triggeredBy,
	}, cycle)
}

// ── Config revisions ──────────────────────────────────────────────────────────

// SaveConfigRevision records a versioned config snapshot for audit purposes.
func (d *DB) SaveConfigRevision(nodeID, version string, config map[string]any) error {
	revisionID := uuid.New().String()
	configJSON, _ := json.Marshal(config)
	now := unixNow()
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
	now := unixNow()
	if _, err := d.state.Exec(`
		INSERT INTO brain_executions (brain_exec_id, node_id, node_name, provider, model, operation, action_decided, parameters_json, reasoning, confidence, outcome, latency_ms, trace_id, recorded_at, cycle)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		brainExecID, nodeID, nodeName, provider, model, operation, actionDecided,
		string(paramsJSON), reasoning, confidence, outcome, latencyMS, traceID, now, cycle); err != nil {
		return "", err
	}
	err := d.LogActivity("brain_consulted", "node", nodeID, map[string]any{
		"provider": provider, "model": model, "operation": operation,
		"action": actionDecided, "outcome": outcome, "confidence": confidence,
	}, cycle)
	return brainExecID, err
}

// UpdateBrainOutcome sets the outcome field of an existing brain execution record.
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
	approvedInt, gwInt := 0, 0
	if approved {
		approvedInt = 1
	}
	if goodhartWarning {
		gwInt = 1
	}
	now := unixNow()
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
	now := unixNow()
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

// RecordGoalTracking inserts a goal-tracking snapshot and returns its tracking_id.
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
	now := unixNow()
	_, err := d.state.Exec(`
		INSERT INTO goal_tracking (tracking_id, cycle, approved, composite_score, scorecard_json, nash_weights_json, tracking_error, control_action_json, subtasks_json, violations_json, recorded_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		trackingID, cycle, approvedInt, compositeScore,
		string(scorecardJSON), string(nashJSON), trackingError,
		string(ctrlJSON), string(subtasksJSON), string(violationsJSON), now)
	if err != nil {
		return "", err
	}
	return trackingID, nil
}
