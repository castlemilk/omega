package handler

import (
	"context"
	"encoding/json"

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

// decodeMapStrAny converts map[string]string (proto map with JSON-encoded values)
// to map[string]any by attempting JSON parse of each value; falls back to string.
func decodeMapStrAny(m map[string]string) map[string]any {
	if len(m) == 0 {
		return nil
	}
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

// optStr returns a pointer to s, or nil if s is empty.
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
	if err := h.db.UpsertNode(
		req.Msg.NodeId, req.Msg.Name, req.Msg.Version,
		req.Msg.Capabilities, req.Msg.Health, req.Msg.Status, brainConfig,
	); err != nil {
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
	if err := h.db.EndExecution(req.Msg.ExecId, req.Msg.Success, req.Msg.ErrorText, req.Msg.Metrics); err != nil {
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
	if err := h.db.EndSpan(req.Msg.SpanId, req.Msg.Status, metadata); err != nil {
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
	if err := h.db.RecordCost(
		req.Msg.NodeId, req.Msg.Provider, req.Msg.CallType,
		req.Msg.DurationMs, optStr(req.Msg.ExecId),
		req.Msg.EstimatedCostUsd, metadata, req.Msg.Cycle,
	); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordCostResponse{Ok: true}), nil
}

// ── OpenIssue ─────────────────────────────────────────────────────────────────

func (h *StateHandler) OpenIssue(
	ctx context.Context,
	req *connect.Request[omegav1.OpenIssueRequest],
) (*connect.Response[omegav1.OpenIssueResponse], error) {
	ctx2 := decodeMapStrAny(req.Msg.Context)
	created, err := h.db.OpenIssue(
		req.Msg.IssueId, req.Msg.Detector, req.Msg.Severity,
		req.Msg.Description, ctx2, req.Msg.Cycle,
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
	if err := h.db.LogActivity(req.Msg.ActionType, req.Msg.EntityType, req.Msg.EntityId, data, req.Msg.Cycle); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.LogActivityResponse{Ok: true}), nil
}

// ── RecordImprovement ─────────────────────────────────────────────────────────

func (h *StateHandler) RecordImprovement(
	ctx context.Context,
	req *connect.Request[omegav1.RecordImprovementRequest],
) (*connect.Response[omegav1.RecordImprovementResponse], error) {
	if err := h.db.RecordImprovement(
		req.Msg.NodeId, req.Msg.NodeName,
		req.Msg.FromVersion, req.Msg.ToVersion,
		req.Msg.BeforeMetrics, req.Msg.AfterMetrics,
		req.Msg.TriggeredBy, req.Msg.Cycle,
	); err != nil {
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
	if err := h.db.SaveConfigRevision(req.Msg.NodeId, req.Msg.Version, config); err != nil {
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
	if err := h.db.UpdateBrainOutcome(req.Msg.BrainExecId, req.Msg.Outcome); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.UpdateBrainOutcomeResponse{Ok: true}), nil
}

// ── RecordAlignmentDecision ───────────────────────────────────────────────────

func (h *StateHandler) RecordAlignmentDecision(
	ctx context.Context,
	req *connect.Request[omegav1.RecordAlignmentDecisionRequest],
) (*connect.Response[omegav1.RecordAlignmentDecisionResponse], error) {
	decisionID, err := h.db.RecordAlignmentDecision(
		req.Msg.Cycle, req.Msg.Approved,
		req.Msg.Violations,
		decodeMapStrAny(req.Msg.ParetoRanks),
		decodeMapStrAny(req.Msg.Adjustments),
		decodeMapStrAny(req.Msg.VcgPayments),
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
	resultID, err := h.db.RecordAdversarialResult(
		req.Msg.Cycle, req.Msg.Ring, req.Msg.Flagged,
		req.Msg.MaxDisagreement, req.Msg.ScenarioCount,
		req.Msg.FailureCases, decodeMapStrAny(req.Msg.Details),
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
	trackingID, err := h.db.RecordGoalTracking(
		req.Msg.Cycle, req.Msg.Approved, req.Msg.CompositeScore,
		decodeMapStrAny(req.Msg.Scorecard),
		decodeMapStrAny(req.Msg.NashWeights),
		req.Msg.TrackingError,
		decodeMapStrAny(req.Msg.ControlAction),
		req.Msg.Subtasks, req.Msg.Violations,
	)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.RecordGoalTrackingResponse{TrackingId: trackingID}), nil
}
