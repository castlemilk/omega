package handler

import (
	"context"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.SafetyServiceHandler = (*SafetyHandler)(nil)

// SafetyHandler implements SafetyService — alignment, gate verification, goal evaluation,
// outcome scoring, and devil's advocate challenge management.
type SafetyHandler struct {
	alignment   *core.AlignmentLayer
	gateSystem  *core.VerificationGateSystem
	goalArch    *core.GoalArchitecture
	challenges  *core.ChallengeRegistry
	db          *db.DB
}

// NewSafety creates a SafetyHandler backed by the shared Postgres database.
func NewSafety(database *db.DB) (*SafetyHandler, error) {
	cr, err := core.NewChallengeRegistry(database.StateDB())
	if err != nil {
		return nil, fmt.Errorf("open challenge registry: %w", err)
	}
	return &SafetyHandler{
		alignment:  core.NewAlignmentLayer(nil),
		gateSystem: core.NewVerificationGateSystem(),
		goalArch:   core.NewGoalArchitecture(nil),
		challenges: cr,
		db:         database,
	}, nil
}

// ── CheckAlignment ────────────────────────────────────────────────────────────

func (h *SafetyHandler) CheckAlignment(
	ctx context.Context,
	req *connect.Request[omegav1.CheckAlignmentRequest],
) (*connect.Response[omegav1.CheckAlignmentResponse], error) {
	// Build nodeMetricsMap from proto NodeMetrics
	nodeMetricsMap := make(map[string]map[string]float64, len(req.Msg.NodeMetrics))
	for _, nm := range req.Msg.NodeMetrics {
		nodeMetricsMap[nm.NodeId] = nm.Metrics
	}

	decision := h.alignment.CheckImprovementCycle(
		nodeMetricsMap,
		req.Msg.SystemMetrics,
		req.Msg.Portfolio,
		int(req.Msg.Cycle),
	)

	violations := make([]*omegav1.ConstraintViolation, 0, len(decision.Violations))
	for _, v := range decision.Violations {
		violations = append(violations, &omegav1.ConstraintViolation{
			ConstraintName: v,
			Description:    v,
		})
	}

	paretoRanks := make([]*omegav1.ParetoRank, 0, len(decision.ParetoRanks))
	for nodeID, rank := range decision.ParetoRanks {
		paretoRanks = append(paretoRanks, &omegav1.ParetoRank{
			NodeId: nodeID,
			Rank:   int32(rank), //nolint:gosec
		})
	}

	outcomeScores := make([]*omegav1.OutcomeScore, 0, len(decision.OutcomeScores))
	for nodeID, score := range decision.OutcomeScores {
		outcomeScores = append(outcomeScores, &omegav1.OutcomeScore{
			NodeId:   nodeID,
			Accuracy: score,
		})
	}

	return connect.NewResponse(&omegav1.CheckAlignmentResponse{
		Approved:        decision.Approved,
		Violations:      violations,
		ParetoRanks:     paretoRanks,
		OutcomeScores:   outcomeScores,
		GoodhartWarning: decision.MagnitudeWarning,
		CheckedAt:       timestamppb.Now(),
	}), nil
}

// ── VerifyGates ───────────────────────────────────────────────────────────────

func (h *SafetyHandler) VerifyGates(
	ctx context.Context,
	req *connect.Request[omegav1.VerifyGatesRequest],
) (*connect.Response[omegav1.VerifyGatesResponse], error) {
	// Convert string context to map[string]any
	gateCtx := make(map[string]any, len(req.Msg.Context))
	for k, v := range req.Msg.Context {
		gateCtx[k] = v
	}
	gateCtx["cycle"] = req.Msg.Cycle
	gateCtx["phase"] = req.Msg.Phase.String()

	results := h.gateSystem.RunAll(gateCtx)
	allPassed := h.gateSystem.AllPassed(results)

	protoResults := make([]*omegav1.GateCheckResult, 0, len(results))
	var passedCount, failedCount int32
	now := timestamppb.Now()
	for _, r := range results {
		passed := r.Passed()
		if passed {
			passedCount++
		} else {
			failedCount++
		}
		protoResults = append(protoResults, &omegav1.GateCheckResult{
			GateName:  r.GateName,
			Passed:    passed,
			Details:   r.Evidence,
			CheckedAt: now,
		})
	}

	return connect.NewResponse(&omegav1.VerifyGatesResponse{
		AllPassed:   allPassed,
		Results:     protoResults,
		PassedCount: passedCount,
		FailedCount: failedCount,
	}), nil
}

// ── EvaluateGoals ─────────────────────────────────────────────────────────────

func (h *SafetyHandler) EvaluateGoals(
	ctx context.Context,
	req *connect.Request[omegav1.EvaluateGoalsRequest],
) (*connect.Response[omegav1.EvaluateGoalsResponse], error) {
	// Convert string system state to map[string]any
	systemState := make(map[string]any, len(req.Msg.SystemState))
	for k, v := range req.Msg.SystemState {
		systemState[k] = v
	}

	decision := h.goalArch.Step(ctx, req.Msg.Metrics, systemState, int(req.Msg.Cycle))

	violations := make([]*omegav1.ConstraintViolation, 0, len(decision.ConstraintViolations))
	for _, v := range decision.ConstraintViolations {
		sev := omegav1.ConstraintSeverity_CONSTRAINT_SEVERITY_SOFT
		if v.Severity == "hard" {
			sev = omegav1.ConstraintSeverity_CONSTRAINT_SEVERITY_HARD
		}
		violations = append(violations, &omegav1.ConstraintViolation{
			ConstraintName: v.ConstraintName,
			Severity:       sev,
			Description:    fmt.Sprintf("%s: observed %.4f, limit %.4f", v.ConstraintName, v.CurrentValue, v.Limit),
			ObservedValue:  v.CurrentValue,
			Limit:          v.Limit,
		})
	}

	subtasks := make([]*omegav1.AssignedTask, 0, len(decision.Subtasks))
	for _, t := range decision.Subtasks {
		params := make(map[string]string, len(t.Parameters))
		for k, v := range t.Parameters {
			params[k] = fmt.Sprintf("%v", v)
		}
		subtasks = append(subtasks, &omegav1.AssignedTask{
			TaskName:       t.Name,
			AssignedToNode: t.AssignedTo,
			Parameters:     params,
		})
	}

	controlAction := make(map[string]float64, len(decision.ControlAction))
	for k, v := range decision.ControlAction {
		controlAction[k] = v
	}

	return connect.NewResponse(&omegav1.EvaluateGoalsResponse{
		Approved:       decision.Approved,
		Violations:     violations,
		Scorecard:      decision.Scorecard,
		CompositeScore: decision.CompositeScore,
		Subtasks:       subtasks,
		TrackingError:  decision.TrackingError,
		ControlAction:  controlAction,
		EvaluatedAt:    timestamppb.New(time.Now()),
	}), nil
}

// ── RecordOutcomeScore ────────────────────────────────────────────────────────

func (h *SafetyHandler) RecordOutcomeScore(
	ctx context.Context,
	req *connect.Request[omegav1.RecordOutcomeScoreRequest],
) (*connect.Response[omegav1.RecordOutcomeScoreResponse], error) {
	h.alignment.RecordOutcome(req.Msg.NodeId, req.Msg.Predicted, req.Msg.Actual, req.Msg.ReturnContribution)
	return connect.NewResponse(&omegav1.RecordOutcomeScoreResponse{Ok: true}), nil
}

// ── GetGoalDecision ───────────────────────────────────────────────────────────

func (h *SafetyHandler) GetGoalDecision(
	ctx context.Context,
	req *connect.Request[omegav1.GetGoalDecisionRequest],
) (*connect.Response[omegav1.GetGoalDecisionResponse], error) {
	gs, err := h.db.CurrentGoalState()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	if gs == nil || gs.Cycle != req.Msg.Cycle {
		return connect.NewResponse(&omegav1.GetGoalDecisionResponse{Found: false}), nil
	}

	// Reconstruct an EvaluateGoalsResponse from stored goal state
	decision := &omegav1.EvaluateGoalsResponse{
		Approved:    true,
		Scorecard:   gs.ScorecardValues,
		EvaluatedAt: timestamppb.Now(),
	}
	for _, task := range gs.ActiveTasks {
		decision.Subtasks = append(decision.Subtasks, &omegav1.AssignedTask{
			TaskName: task,
		})
	}

	return connect.NewResponse(&omegav1.GetGoalDecisionResponse{
		Found:    true,
		Decision: decision,
	}), nil
}

// ── HasBlockingChallenges ─────────────────────────────────────────────────────

func (h *SafetyHandler) HasBlockingChallenges(
	ctx context.Context,
	req *connect.Request[omegav1.HasBlockingChallengesRequest],
) (*connect.Response[omegav1.HasBlockingChallengesResponse], error) {
	has, err := h.challenges.HasBlockingChallenges()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	criticals, err := h.challenges.OpenChallenges(core.SeverityCritical)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	highs, err := h.challenges.OpenChallenges(core.SeverityHigh)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&omegav1.HasBlockingChallengesResponse{
		HasBlocking:   has,
		CriticalCount: int32(len(criticals)), //nolint:gosec
		HighCount:     int32(len(highs)),     //nolint:gosec
	}), nil
}

// ── OpenChallenge ─────────────────────────────────────────────────────────────

func (h *SafetyHandler) OpenChallenge(
	ctx context.Context,
	req *connect.Request[omegav1.OpenChallengeRequest],
) (*connect.Response[omegav1.OpenChallengeResponse], error) {
	sev := protoToCoreSeverity(req.Msg.Severity)
	id, err := h.challenges.Add(req.Msg.TargetSubsystem, sev, req.Msg.Description, req.Msg.Evidence, req.Msg.ChallengeId)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.OpenChallengeResponse{
		ChallengeId: id,
		Created:     true,
	}), nil
}

// ── ResolveChallenge ──────────────────────────────────────────────────────────

func (h *SafetyHandler) ResolveChallenge(
	ctx context.Context,
	req *connect.Request[omegav1.ResolveChallengeRequest],
) (*connect.Response[omegav1.ResolveChallengeResponse], error) {
	status := core.StatusResolved
	if req.Msg.Resolution == omegav1.ChallengeResolution_CHALLENGE_RESOLUTION_WONTFIX {
		status = core.StatusWontfix
	}
	ok, err := h.challenges.UpdateStatus(req.Msg.ChallengeId, status, req.Msg.Notes)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.ResolveChallengeResponse{Ok: ok}), nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func protoToCoreSeverity(s omegav1.ChallengeSeverity) core.ChallengeSeverity {
	switch s {
	case omegav1.ChallengeSeverity_CHALLENGE_SEVERITY_CRITICAL:
		return core.SeverityCritical
	case omegav1.ChallengeSeverity_CHALLENGE_SEVERITY_HIGH:
		return core.SeverityHigh
	case omegav1.ChallengeSeverity_CHALLENGE_SEVERITY_MEDIUM:
		return core.SeverityMedium
	default:
		return core.SeverityLow
	}
}
