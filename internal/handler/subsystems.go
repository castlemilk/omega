package handler

import (
	"context"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/db"
)

// ── Alignment ─────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetAlignmentDecisions(
	ctx context.Context,
	req *connect.Request[omegav1.GetAlignmentDecisionsRequest],
) (*connect.Response[omegav1.GetAlignmentDecisionsResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	decisions, err := h.db.RecentAlignmentDecisions(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	out := make([]*omegav1.AlignmentDecision, 0, len(decisions))
	for _, d := range decisions {
		out = append(out, dbAlignmentToProto(d))
	}
	return connect.NewResponse(&omegav1.GetAlignmentDecisionsResponse{Decisions: out}), nil
}

func dbAlignmentToProto(a *db.AlignmentDecision) *omegav1.AlignmentDecision {
	return &omegav1.AlignmentDecision{
		DecisionId:      a.DecisionID,
		Cycle:           a.Cycle,
		Approved:        a.Approved,
		Reasons:         a.Reasons,
		TargetSubsystem: a.TargetSubsystem,
		RecordedAt:      tsFromUnix(a.RecordedAt),
	}
}

// ── Adversarial ───────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetAdversarialResults(
	ctx context.Context,
	req *connect.Request[omegav1.GetAdversarialResultsRequest],
) (*connect.Response[omegav1.GetAdversarialResultsResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	results, err := h.db.RecentAdversarialResults(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	out := make([]*omegav1.AdversarialResult, 0, len(results))
	for _, r := range results {
		out = append(out, dbAdversarialToProto(r))
	}
	return connect.NewResponse(&omegav1.GetAdversarialResultsResponse{Results: out}), nil
}

func dbAdversarialToProto(r *db.AdversarialResult) *omegav1.AdversarialResult {
	return &omegav1.AdversarialResult{
		ResultId:   r.ResultID,
		Cycle:      r.Cycle,
		Ring:       r.Ring,
		Flags:      r.Flags,
		Severity:   r.Severity,
		RecordedAt: tsFromUnix(r.RecordedAt),
	}
}

// ── Goal tracking ─────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetGoalTracking(
	ctx context.Context,
	req *connect.Request[omegav1.GetGoalTrackingRequest],
) (*connect.Response[omegav1.GetGoalTrackingResponse], error) {
	gs, err := h.db.CurrentGoalState()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	resp := &omegav1.GetGoalTrackingResponse{}
	if gs != nil {
		resp.State = dbGoalStateToProto(gs)
	}
	return connect.NewResponse(resp), nil
}

func dbGoalStateToProto(gs *db.GoalState) *omegav1.GoalState {
	return &omegav1.GoalState{
		Cycle:                gs.Cycle,
		ConstitutionalChecks: gs.ConstitutionalChecks,
		ScorecardValues:      gs.ScorecardValues,
		ActiveTasks:          gs.ActiveTasks,
		RecordedAt:           tsFromUnix(gs.RecordedAt),
	}
}

// ── Challenges ────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetChallenges(
	ctx context.Context,
	req *connect.Request[omegav1.GetChallengesRequest],
) (*connect.Response[omegav1.GetChallengesResponse], error) {
	challenges, err := h.db.ListChallenges(req.Msg.StatusFilter)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	out := make([]*omegav1.Challenge, 0, len(challenges))
	for _, c := range challenges {
		out = append(out, dbChallengeToProto(c))
	}
	return connect.NewResponse(&omegav1.GetChallengesResponse{Challenges: out}), nil
}

func dbChallengeToProto(c *db.Challenge) *omegav1.Challenge {
	proto := &omegav1.Challenge{
		ChallengeId:     c.ChallengeID,
		Status:          c.Status,
		Severity:        c.Severity,
		TargetSubsystem: c.TargetSubsystem,
		Description:     c.Description,
		CreatedAt:       tsFromUnix(c.CreatedAt),
	}
	if c.UpdatedAt > 0 {
		proto.UpdatedAt = tsFromUnix(c.UpdatedAt)
	}
	return proto
}

// ── Memory stats ──────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetMemoryStats(
	ctx context.Context,
	req *connect.Request[omegav1.GetMemoryStatsRequest],
) (*connect.Response[omegav1.GetMemoryStatsResponse], error) {
	stats, err := h.db.GetMemoryStatsSummary()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.GetMemoryStatsResponse{
		Stats: &omegav1.MemoryStats{
			EpisodicCount:      stats.EpisodicCount,
			SemanticCount:      stats.SemanticCount,
			RegimeHistory:      stats.RegimeHistory,
			ContradictionCount: stats.ContradictionCount,
		},
	}), nil
}

// ── Verification gates ────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetVerificationGates(
	ctx context.Context,
	req *connect.Request[omegav1.GetVerificationGatesRequest],
) (*connect.Response[omegav1.GetVerificationGatesResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	gates, err := h.db.RecentGateResults(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	out := make([]*omegav1.GateResult, 0, len(gates))
	for _, g := range gates {
		out = append(out, dbGateResultToProto(g))
	}
	return connect.NewResponse(&omegav1.GetVerificationGatesResponse{Gates: out}), nil
}

func dbGateResultToProto(g *db.GateResult) *omegav1.GateResult {
	return &omegav1.GateResult{
		GateId:    g.GateID,
		Cycle:     g.Cycle,
		GateName:  g.GateName,
		Result:    g.Result,
		Details:   g.Details,
		CheckedAt: tsFromUnix(g.CheckedAt),
	}
}

// ── Improvement history ───────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetImprovementHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetImprovementHistoryRequest],
) (*connect.Response[omegav1.GetImprovementHistoryResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	history, err := h.db.ImprovementHistory(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	out := make([]*omegav1.ImprovementDetail, 0, len(history))
	for _, imp := range history {
		out = append(out, dbImprovementDetailToProto(imp))
	}
	return connect.NewResponse(&omegav1.GetImprovementHistoryResponse{Records: out}), nil
}

func dbImprovementDetailToProto(imp *db.ImprovementDetail) *omegav1.ImprovementDetail {
	proto := &omegav1.ImprovementDetail{
		ImproveId:        imp.ImproveID,
		NodeId:           imp.NodeID,
		NodeName:         imp.NodeName,
		FromVersion:      imp.FromVersion,
		ToVersion:        imp.ToVersion,
		TriggeredBy:      imp.TriggeredBy,
		RecordedAt:       tsFromUnix(imp.RecordedAt),
		Cycle:            imp.Cycle,
		BeforeMetrics:    imp.BeforeMetrics,
		AfterMetrics:     imp.AfterMetrics,
		AlignmentReasons: imp.AlignmentReasons,
	}
	if imp.AlignmentApproved != nil {
		proto.HasAlignmentDecision = true
		proto.AlignmentApproved = *imp.AlignmentApproved
	}
	return proto
}
