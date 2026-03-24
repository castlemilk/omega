package db

import (
	"database/sql"
	"encoding/json"

	"github.com/google/uuid"
)

// ── Node registry ──────────────────────────────────────────────────────────────

// UpsertNode inserts or updates a node record.
func (d *DB) UpsertNode(nodeID, name, version string, capabilities []string, health float64, status string, brainConfig map[string]any) error {
	capsJSON, _ := json.Marshal(capabilities)
	brainJSON, _ := json.Marshal(brainConfig)
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO nodes (node_id, name, version, capabilities, health, status, brain_config, registered_at, last_updated)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (node_id) DO UPDATE SET
			name=EXCLUDED.name,
			version=EXCLUDED.version,
			capabilities=EXCLUDED.capabilities,
			health=EXCLUDED.health,
			status=EXCLUDED.status,
			brain_config=EXCLUDED.brain_config,
			last_updated=EXCLUDED.last_updated`,
		nodeID, name, version, string(capsJSON), health, status, string(brainJSON), now, now)
	return err
}

// ── Executions ────────────────────────────────────────────────────────────────

// BeginExecution inserts a new execution row and returns its exec_id.
func (d *DB) BeginExecution(nodeID, nodeName, action string, traceID, spanID *string, cycle int64) (string, error) {
	execID := uuid.New().String()
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO node_executions (exec_id, node_id, node_name, trace_id, span_id, action, started_at, success, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8)`,
		execID, nodeID, nodeName, traceID, spanID, action, now, cycle)
	if err != nil {
		return "", err
	}
	return execID, nil
}

// EndExecution updates an existing execution row with outcome and metrics.
func (d *DB) EndExecution(execID string, success bool, errorText string, errorClass int32, errorCode string, isRetryable bool, metrics map[string]float64) error {
	now := unixNow()
	var startedAt float64
	if err := d.db.QueryRow(`SELECT started_at FROM node_executions WHERE exec_id = $1`, execID).Scan(&startedAt); err != nil {
		return err
	}
	durationMS := (now - startedAt) * 1000
	metricsJSON, _ := json.Marshal(metrics)
	_, err := d.db.Exec(`
		UPDATE node_executions
		SET ended_at=$1, duration_ms=$2, success=$3, error_text=$4, metrics=$5,
		    error_class=$6, error_code=$7, is_retryable=$8
		WHERE exec_id=$9`,
		now, durationMS, success, errorText, string(metricsJSON),
		errorClass, errorCode, isRetryable, execID)
	return err
}

// ── Traces ────────────────────────────────────────────────────────────────────

// BeginSpan inserts a new trace span and returns its span_id.
func (d *DB) BeginSpan(traceID, nodeID, nodeName, operation string, parentSpanID *string, cycle int64) (string, error) {
	spanID := uuid.New().String()
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO traces (span_id, trace_id, parent_span_id, node_id, node_name, operation, started_at, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
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
	if err := d.db.QueryRow(`SELECT started_at FROM traces WHERE span_id = $1`, spanID).Scan(&startedAt); err != nil {
		return err
	}
	durationMS := (now - startedAt) * 1000
	metaJSON, _ := json.Marshal(metadata)
	_, err := d.db.Exec(`
		UPDATE traces SET ended_at=$1, duration_ms=$2, status=$3, metadata=$4 WHERE span_id=$5`,
		now, durationMS, status, string(metaJSON), spanID)
	return err
}

// ── Cost events ───────────────────────────────────────────────────────────────

// RecordCost inserts a cost event.
func (d *DB) RecordCost(nodeID, provider, callType string, durationMS float64, execID *string, estimatedCostUSD float64, metadata map[string]any, cycle int64) error {
	costID := uuid.New().String()
	metaJSON, _ := json.Marshal(metadata)
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO cost_events (cost_id, node_id, exec_id, provider, call_type, duration_ms, estimated_cost_usd, metadata, recorded_at, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
		costID, nodeID, execID, provider, callType, durationMS, estimatedCostUSD, string(metaJSON), now, cycle)
	return err
}

// ── Issues ────────────────────────────────────────────────────────────────────

// OpenIssue inserts a new issue. Returns (true, nil) if created; (false, nil) if already existed.
func (d *DB) OpenIssue(issueID, detector, severity, description string, context map[string]any, cycle int64) (bool, error) {
	var existingState string
	err := d.db.QueryRow(`SELECT state FROM issues WHERE issue_id = $1`, issueID).Scan(&existingState)
	if err == nil {
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
	if _, err = d.db.Exec(`
		INSERT INTO issues (issue_id, detector, severity, description, context, state, opened_at, cycle_opened)
		VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7)`,
		issueID, detector, severity, description, string(ctxJSON), now, cycle); err != nil {
		return false, err
	}
	return true, d.LogActivity("issue_opened", "issue", issueID, map[string]any{"severity": severity, "detector": detector}, cycle)
}

// EscalateIssue promotes a pending issue to active.
func (d *DB) EscalateIssue(issueID string) (int64, error) {
	res, err := d.db.Exec(`UPDATE issues SET state='active' WHERE issue_id=$1 AND state='pending'`, issueID)
	if err != nil {
		return 0, err
	}
	n, _ := res.RowsAffected()
	return n, nil
}

// ResolveIssue marks an issue resolved.
func (d *DB) ResolveIssue(issueID string, cycle int64) (bool, error) {
	now := unixNow()
	res, err := d.db.Exec(`
		UPDATE issues SET state='resolved', resolved_at=$1, cycle_resolved=$2
		WHERE issue_id=$3 AND state != 'resolved'`,
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
	_, err := d.db.Exec(`
		INSERT INTO activity_log (log_id, action_type, entity_type, entity_id, data, recorded_at, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7)`,
		logID, actionType, entityType, entityID, string(dataJSON), now, cycle)
	return err
}

// ── Improvement log ───────────────────────────────────────────────────────────

// RecordImprovement inserts an improvement record.
func (d *DB) RecordImprovement(nodeID, nodeName, fromVersion, toVersion string, beforeMetrics, afterMetrics map[string]float64, triggeredBy string, cycle int64) error {
	improveID := uuid.New().String()
	beforeJSON, _ := json.Marshal(beforeMetrics)
	afterJSON, _ := json.Marshal(afterMetrics)
	now := unixNow()
	if _, err := d.db.Exec(`
		INSERT INTO improvement_log (improve_id, node_id, node_name, from_version, to_version, before_metrics, after_metrics, triggered_by, recorded_at, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
		improveID, nodeID, nodeName, fromVersion, toVersion,
		string(beforeJSON), string(afterJSON), triggeredBy, now, cycle); err != nil {
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
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO config_revisions (revision_id, node_id, version, config, recorded_at)
		VALUES ($1, $2, $3, $4, $5)`,
		revisionID, nodeID, version, string(configJSON), now)
	return err
}

// ── Brain executions ──────────────────────────────────────────────────────────

// RecordBrainExecution inserts a brain invocation record and returns its brain_exec_id.
func (d *DB) RecordBrainExecution(nodeID, nodeName, provider, model, operation, actionDecided string, parameters map[string]any, reasoning string, confidence float64, outcome string, latencyMS float64, traceID string, cycle int64) (string, error) {
	brainExecID := uuid.New().String()
	paramsJSON, _ := json.Marshal(parameters)
	now := unixNow()
	if _, err := d.db.Exec(`
		INSERT INTO brain_executions (brain_exec_id, node_id, node_name, provider, model, operation, action_decided, parameters, reasoning, confidence, outcome, latency_ms, trace_id, recorded_at, cycle)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`,
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

// UpdateBrainOutcome sets the outcome of an existing brain execution record.
func (d *DB) UpdateBrainOutcome(brainExecID, outcome string) error {
	_, err := d.db.Exec(`UPDATE brain_executions SET outcome=$1 WHERE brain_exec_id=$2`, outcome, brainExecID)
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
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO alignment_decisions (decision_id, cycle, approved, violations, pareto_ranks, adjustments, vcg_payments, goodhart_warning, recorded_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		decisionID, cycle, approved, string(violationsJSON), string(paretoJSON), string(adjJSON), string(vcgJSON), goodhartWarning, now)
	if err != nil {
		return "", err
	}
	return decisionID, nil
}

// ── Adversarial results ───────────────────────────────────────────────────────

// RecordAdversarialResult inserts an adversarial pressure result and returns its result_id.
func (d *DB) RecordAdversarialResult(cycle int64, ring int32, flagged bool, maxDisagreement float64, scenarioCount int64, failureCases []string, details map[string]any) (string, error) {
	resultID := uuid.New().String()
	failuresJSON, _ := json.Marshal(failureCases)
	detailsJSON, _ := json.Marshal(details)
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO adversarial_results (result_id, cycle, ring, flagged, max_disagreement, scenario_count, failure_cases, details, recorded_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		resultID, cycle, ring, flagged, maxDisagreement, scenarioCount, string(failuresJSON), string(detailsJSON), now)
	if err != nil {
		return "", err
	}
	return resultID, nil
}

// ── Goal tracking ─────────────────────────────────────────────────────────────

// RecordGoalTracking inserts a goal-tracking snapshot and returns its tracking_id.
func (d *DB) RecordGoalTracking(cycle int64, approved bool, compositeScore float64, scorecard, nashWeights map[string]any, trackingError float64, controlAction map[string]any, subtasks, violations []string) (string, error) {
	trackingID := uuid.New().String()
	scorecardJSON, _ := json.Marshal(scorecard)
	nashJSON, _ := json.Marshal(nashWeights)
	ctrlJSON, _ := json.Marshal(controlAction)
	subtasksJSON, _ := json.Marshal(subtasks)
	violationsJSON, _ := json.Marshal(violations)
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO goal_tracking (tracking_id, cycle, approved, composite_score, scorecard, nash_weights, tracking_error, control_action, subtasks, violations, recorded_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
		trackingID, cycle, approved, compositeScore,
		string(scorecardJSON), string(nashJSON), trackingError,
		string(ctrlJSON), string(subtasksJSON), string(violationsJSON), now)
	if err != nil {
		return "", err
	}
	return trackingID, nil
}

// ── Terminal sessions ─────────────────────────────────────────────────────────

// SaveTerminalSession upserts a terminal session record.
func (d *DB) SaveTerminalSession(s *TerminalSessionRecord) error {
	var closedAt any
	if s.ClosedAt != 0 {
		closedAt = s.ClosedAt
	}
	_, err := d.db.Exec(`
		INSERT INTO terminal_sessions(id, work_dir, autonomy_level, status, created_at, closed_at)
		VALUES ($1, $2, $3, $4, $5, $6)
		ON CONFLICT (id) DO UPDATE SET
			status=EXCLUDED.status, closed_at=EXCLUDED.closed_at`,
		s.ID, s.WorkDir, s.AutonomyLevel, s.Status, s.CreatedAt, closedAt,
	)
	return err
}

// ── Coordination outcomes ──────────────────────────────────────────────────────

// RecordCoordinationOutcome inserts a coordination outcome tuple.
// routingJSON and stateJSON should be JSON-encoded strings.
func (d *DB) RecordCoordinationOutcome(goalID string, outcomeQuality float64, routingJSON string, stateJSON string) error {
	recordID := uuid.New().String()
	now := unixNow()
	// Use epoch timestamp as captured_at (TIMESTAMPTZ column accepts epoch seconds as text).
	// We cast the stored value via a SQL expression to avoid driver confusion.
	_, err := d.db.Exec(`
		INSERT INTO coordination_outcomes
			(record_id, goal_id, goal_type, goal_json, routing_json, outcome_quality, captured_at, state_snapshot)
		VALUES ($1, $2, 0, '{}', $3, $4, to_timestamp($5), $6)
		ON CONFLICT (record_id) DO NOTHING`,
		recordID, goalID, routingJSON, outcomeQuality, now, stateJSON)
	return err
}

// ── Verification gates ─────────────────────────────────────────────────────────

// RecordVerificationGate inserts a verification gate result for a cycle.
func (d *DB) RecordVerificationGate(cycle int64, gateName string, passed bool, details string) error {
	gateID := uuid.New().String()
	result := "pass"
	if !passed {
		result = "fail"
	}
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO verification_gates (gate_id, cycle, gate_name, result, details, checked_at)
		VALUES ($1, $2, $3, $4, $5, $6)`,
		gateID, cycle, gateName, result, details, now)
	return err
}

// SaveTerminalCommand inserts a single command record.
func (d *DB) SaveTerminalCommand(c *TerminalCommandRecord) error {
	_, err := d.db.Exec(`
		INSERT INTO terminal_commands
			(id, session_id, command, args, exit_code, stdout, stderr, duration_ms, truncated, executed_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
		ON CONFLICT (id) DO NOTHING`,
		c.ID, c.SessionID, c.Command, c.Args,
		c.ExitCode, c.Stdout, c.Stderr, c.DurationMS, c.Truncated, c.ExecutedAt,
	)
	return err
}
