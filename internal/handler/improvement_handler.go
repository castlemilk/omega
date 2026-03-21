package handler

import (
	"context"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/core"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.ImprovementServiceHandler = (*ImprovementHandler)(nil)

// ImprovementHandler implements ImprovementService — improvement scheduling,
// trial outcome recording, and strategy compilation.
type ImprovementHandler struct {
	scheduler *core.ImprovementScheduler
	compiler  *core.DeterministicCompiler
}

// NewImprovement creates an ImprovementHandler.
func NewImprovement() *ImprovementHandler {
	return &ImprovementHandler{
		scheduler: core.NewImprovementScheduler(time.Now),
		compiler:  core.NewDeterministicCompiler(),
	}
}

// ── DueNodes ──────────────────────────────────────────────────────────────────

func (h *ImprovementHandler) DueNodes(
	ctx context.Context,
	req *connect.Request[omegav1.DueNodesRequest],
) (*connect.Response[omegav1.DueNodesResponse], error) {
	nodes := h.scheduler.DueNodes()
	return connect.NewResponse(&omegav1.DueNodesResponse{NodeIds: nodes}), nil
}

// ── ScheduleImprovement ───────────────────────────────────────────────────────

func (h *ImprovementHandler) ScheduleImprovement(
	ctx context.Context,
	req *connect.Request[omegav1.ScheduleImprovementRequest],
) (*connect.Response[omegav1.ScheduleImprovementResponse], error) {
	cfg := core.DefaultNodeScheduleConfig(req.Msg.NodeId)
	cfg.Priority = req.Msg.Priority
	if req.Msg.Interval != nil {
		cfg.Interval = req.Msg.Interval.AsDuration()
	}
	runImmediately := req.Msg.FirstRunAt != nil && req.Msg.FirstRunAt.AsTime().Before(time.Now())
	h.scheduler.Register(req.Msg.NodeId, &cfg, runImmediately)

	entry := statusToScheduleEntry(req.Msg.NodeId, h.scheduler.ScheduleStatus())
	return connect.NewResponse(&omegav1.ScheduleImprovementResponse{Entry: entry}), nil
}

// ── RecordOutcome ─────────────────────────────────────────────────────────────

func (h *ImprovementHandler) RecordOutcome(
	ctx context.Context,
	req *connect.Request[omegav1.RecordOutcomeRequest],
) (*connect.Response[omegav1.RecordOutcomeResponse], error) {
	var score *float64
	if req.Msg.Score != 0 {
		s := req.Msg.Score
		score = &s
	}
	if err := h.scheduler.RecordOutcome(req.Msg.NodeId, req.Msg.Success, score); err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	entry := statusToScheduleEntry(req.Msg.NodeId, h.scheduler.ScheduleStatus())
	var nextRun *timestamppb.Timestamp
	if entry != nil && entry.NextRunAt != nil {
		nextRun = entry.NextRunAt
	}
	return connect.NewResponse(&omegav1.RecordOutcomeResponse{
		NextRunAt:    nextRun,
		UpdatedEntry: entry,
	}), nil
}

// ── ProposeTrialParams ────────────────────────────────────────────────────────

func (h *ImprovementHandler) ProposeTrialParams(
	ctx context.Context,
	req *connect.Request[omegav1.ProposeTrialParamsRequest],
) (*connect.Response[omegav1.ProposeTrialParamsResponse], error) {
	// TPE optimisation is a Python-side concern. The Go handler exposes the RPC
	// contract and returns a passthrough response — the Python orchestrator calls
	// this after running Optuna and injects the proposed params via the payload.
	// For now, return an empty params map so the build compiles.
	return connect.NewResponse(&omegav1.ProposeTrialParamsResponse{
		Params:              make(map[string]float64),
		ExpectedImprovement: 0,
		Strategy:            "random",
	}), nil
}

// ── CompileStrategy ───────────────────────────────────────────────────────────

func (h *ImprovementHandler) CompileStrategy(
	ctx context.Context,
	req *connect.Request[omegav1.CompileStrategyRequest],
) (*connect.Response[omegav1.CompileStrategyResponse], error) {
	snap := &protoNodeSnapshot{
		nodeID:      req.Msg.NodeId,
		nodeVersion: req.Msg.NodeVersion,
		parameters:  toAnyMap(req.Msg.Parameters),
		rules:       protoRulesToCore(req.Msg.Rules),
	}
	strategy := h.compiler.Compile(snap)
	if strategy == nil {
		return nil, connect.NewError(connect.CodeInternal, errorf("compiler returned nil strategy"))
	}
	return connect.NewResponse(&omegav1.CompileStrategyResponse{
		StrategyId:  strategy.StrategyID,
		Checksum:    strategy.Checksum,
		NodeVersion: strategy.NodeVersion,
		CompiledAt:  timestamppb.New(strategy.CompiledAt),
	}), nil
}

// ── RollbackStrategy ──────────────────────────────────────────────────────────

func (h *ImprovementHandler) RollbackStrategy(
	ctx context.Context,
	req *connect.Request[omegav1.RollbackStrategyRequest],
) (*connect.Response[omegav1.RollbackStrategyResponse], error) {
	strategy := h.compiler.Rollback(req.Msg.NodeId, int(req.Msg.TargetVersion))
	if strategy == nil {
		return connect.NewResponse(&omegav1.RollbackStrategyResponse{Ok: false}), nil
	}
	return connect.NewResponse(&omegav1.RollbackStrategyResponse{
		StrategyId:  strategy.StrategyID,
		NodeVersion: strategy.NodeVersion,
		Ok:          true,
	}), nil
}

// ── GetImprovementSchedule ────────────────────────────────────────────────────

func (h *ImprovementHandler) GetImprovementSchedule(
	ctx context.Context,
	req *connect.Request[omegav1.GetImprovementScheduleRequest],
) (*connect.Response[omegav1.GetImprovementScheduleResponse], error) {
	entry := statusToScheduleEntry(req.Msg.NodeId, h.scheduler.ScheduleStatus())
	if entry == nil {
		return connect.NewResponse(&omegav1.GetImprovementScheduleResponse{Found: false}), nil
	}
	return connect.NewResponse(&omegav1.GetImprovementScheduleResponse{
		Found: true,
		Entry: entry,
	}), nil
}

// ── ListImprovedNodes ─────────────────────────────────────────────────────────

func (h *ImprovementHandler) ListImprovedNodes(
	ctx context.Context,
	req *connect.Request[omegav1.ListImprovedNodesRequest],
) (*connect.Response[omegav1.ListImprovedNodesResponse], error) {
	statuses := h.scheduler.ScheduleStatus()
	entries := make([]*omegav1.ScheduleEntry, 0, len(statuses))
	for _, st := range statuses {
		entries = append(entries, scheduleStatusToEntry(st))
	}
	return connect.NewResponse(&omegav1.ListImprovedNodesResponse{Entries: entries}), nil
}

// ── StreamImprovementEvents ───────────────────────────────────────────────────

func (h *ImprovementHandler) StreamImprovementEvents(
	ctx context.Context,
	req *connect.Request[omegav1.StreamImprovementEventsRequest],
	stream *connect.ServerStream[omegav1.ImprovementEvent],
) error {
	<-ctx.Done()
	return nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func statusToScheduleEntry(nodeID string, statuses []core.NodeScheduleStatus) *omegav1.ScheduleEntry {
	for _, st := range statuses {
		if st.NodeID == nodeID {
			return scheduleStatusToEntry(st)
		}
	}
	return nil
}

func scheduleStatusToEntry(st core.NodeScheduleStatus) *omegav1.ScheduleEntry {
	e := &omegav1.ScheduleEntry{
		NodeId:              st.NodeID,
		Priority:            st.Priority,
		ConsecutiveFailures: int32(st.ConsecutiveFailures), //nolint:gosec
	}
	if st.NextRunIn > 0 {
		e.NextRunAt = timestamppb.New(time.Now().Add(st.NextRunIn))
		e.BaseInterval = durationpb.New(st.NextRunIn)
	}
	if st.LastRunAt != nil {
		e.LastRunAt = timestamppb.New(*st.LastRunAt)
	}
	if st.LastScore != nil {
		e.LastScore = *st.LastScore
	}
	if st.Suspended {
		e.LastStatus = omegav1.TrialStatus_TRIAL_STATUS_FAILED
	} else {
		e.LastStatus = omegav1.TrialStatus_TRIAL_STATUS_PENDING
	}
	return e
}

func toAnyMap(m map[string]float64) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func protoRulesToCore(rules []*omegav1.StrategyRule) []core.StrategyRule {
	out := make([]core.StrategyRule, 0, len(rules))
	for _, r := range rules {
		cr := core.StrategyRule{
			Name:       r.Name,
			Confidence: r.Confidence,
		}
		for _, c := range r.Conditions {
			cr.Conditions = append(cr.Conditions, core.RuleCondition{
				Field: c.FieldPath,
				Op:    c.Operator,
				Value: c.Threshold,
			})
		}
		out = append(out, cr)
	}
	return out
}

// errorf is a package-local helper to avoid importing fmt at the top level.
func errorf(msg string) error {
	return &simpleError{msg: msg}
}

type simpleError struct{ msg string }

func (e *simpleError) Error() string { return e.msg }

// ── protoNodeSnapshot implements core.NodeSnapshot ────────────────────────────

type protoNodeSnapshot struct {
	nodeID      string
	nodeVersion string
	parameters  map[string]any
	rules       []core.StrategyRule
}

func (s *protoNodeSnapshot) NodeID() string                  { return s.nodeID }
func (s *protoNodeSnapshot) NodeVersion() string             { return s.nodeVersion }
func (s *protoNodeSnapshot) Parameters() map[string]any      { return s.parameters }
func (s *protoNodeSnapshot) Rules() []core.StrategyRule      { return s.rules }
