// Package handler implements the OrchestratorService Connect-RPC handler.
package handler

import (
	"context"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.OrchestratorServiceHandler = (*OrchestratorHandler)(nil)

// OrchestratorHandler implements OrchestratorService.
type OrchestratorHandler struct {
	db *db.DB
}

// New creates an OrchestratorHandler backed by the given DB.
func New(database *db.DB) *OrchestratorHandler {
	return &OrchestratorHandler{db: database}
}

// tsFromUnix converts a float64 Unix timestamp to a protobuf Timestamp.
func tsFromUnix(u float64) *timestamppb.Timestamp {
	if u == 0 {
		return nil
	}
	sec := int64(u)
	nsec := int32((u - float64(sec)) * 1e9)
	return timestamppb.New(time.Unix(sec, int64(nsec)))
}

func tsFromUnixPtr(u *float64) *timestamppb.Timestamp {
	if u == nil {
		return nil
	}
	return tsFromUnix(*u)
}

// ── Health ────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetHealth(
	ctx context.Context,
	req *connect.Request[omegav1.GetHealthRequest],
) (*connect.Response[omegav1.GetHealthResponse], error) {
	health, err := h.db.SystemHealth()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.GetHealthResponse{
		Health: dbHealthToProto(health),
	}), nil
}

func dbHealthToProto(h *db.SystemHealth) *omegav1.SystemHealth {
	return &omegav1.SystemHealth{
		Status:         h.Status,
		CompositeScore: h.CompositeScore,
		AvgNodeHealth:  h.AvgNodeHealth,
		NodeCount:      h.NodeCount,
		OpenIssues:     h.OpenIssues,
		ErrorIssues:    h.ErrorIssues,
		UptimeSeconds:  h.UptimeSeconds,
		TotalCycles:    h.TotalCycles,
	}
}

// ── Nodes ─────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) ListNodes(
	ctx context.Context,
	req *connect.Request[omegav1.ListNodesRequest],
) (*connect.Response[omegav1.ListNodesResponse], error) {
	nodes, err := h.db.AllNodes()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoNodes []*omegav1.Node
	for _, n := range nodes {
		protoNodes = append(protoNodes, dbNodeToProto(n))
	}
	return connect.NewResponse(&omegav1.ListNodesResponse{Nodes: protoNodes}), nil
}

func (h *OrchestratorHandler) GetNode(
	ctx context.Context,
	req *connect.Request[omegav1.GetNodeRequest],
) (*connect.Response[omegav1.GetNodeResponse], error) {
	n, err := h.db.GetNode(req.Msg.NodeId)
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("node not found: %s", req.Msg.NodeId))
	}
	execs, _ := h.db.GetExecutions(req.Msg.NodeId, 10)
	imps, _ := h.db.GetImprovements(req.Msg.NodeId, 20)
	history, _ := h.db.LatencyHistory(req.Msg.NodeId, 100)

	resp := &omegav1.GetNodeResponse{
		Node:         dbNodeToProto(n),
		Improvements: dbImpsToProto(imps),
	}
	for _, e := range execs {
		resp.RecentExecutions = append(resp.RecentExecutions, dbExecToProto(e))
	}
	for _, p := range history {
		resp.LatencyHistory = append(resp.LatencyHistory, &omegav1.LatencyPoint{
			Ts:         tsFromUnix(p.StartedAt),
			DurationMs: p.DurationMS,
			Success:    p.Success,
		})
	}
	return connect.NewResponse(resp), nil
}

func (h *OrchestratorHandler) ListNodeExecutions(
	ctx context.Context,
	req *connect.Request[omegav1.ListNodeExecutionsRequest],
) (*connect.Response[omegav1.ListNodeExecutionsResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	execs, err := h.db.GetExecutions(req.Msg.NodeId, limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoExecs []*omegav1.ExecutionRecord
	for _, e := range execs {
		protoExecs = append(protoExecs, dbExecToProto(e))
	}
	return connect.NewResponse(&omegav1.ListNodeExecutionsResponse{Executions: protoExecs}), nil
}

func dbNodeToProto(n *db.Node) *omegav1.Node {
	node := &omegav1.Node{
		NodeId:           n.NodeID,
		Name:             n.Name,
		Version:          n.Version,
		Capabilities:     n.Capabilities,
		Health:           n.Health,
		Status:           n.Status,
		RegisteredAt:     tsFromUnix(n.RegisteredAt),
		LastUpdated:      tsFromUnix(n.LastUpdated),
		ExecutionsTotal:  n.ExecutionsTotal,
		ErrorRate:        n.ErrorRate,
		AvgLatencyMs:     n.AvgLatencyMS,
		P95LatencyMs:     n.P95LatencyMS,
		ImprovementCount: n.ImprovementCount,
	}
	if n.LastExecution != nil {
		node.LastExecution = dbExecToProto(n.LastExecution)
	}
	return node
}

func dbExecToProto(e *db.Execution) *omegav1.ExecutionRecord {
	rec := &omegav1.ExecutionRecord{
		ExecId:    e.ExecID,
		NodeId:    e.NodeID,
		NodeName:  e.NodeName,
		TraceId:   e.TraceID,
		SpanId:    e.SpanID,
		Action:    e.Action,
		StartedAt: tsFromUnix(e.StartedAt),
		EndedAt:   tsFromUnixPtr(e.EndedAt),
		Success:   e.Success,
		ErrorText: e.ErrorText,
		Metrics:   e.Metrics,
		Cycle:     e.Cycle,
	}
	if e.DurationMS != nil {
		rec.DurationMs = *e.DurationMS
	}
	return rec
}

// ── Traces ────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) ListTraces(
	ctx context.Context,
	req *connect.Request[omegav1.ListTracesRequest],
) (*connect.Response[omegav1.ListTracesResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 20
	}
	traces, err := h.db.RecentTraces(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoTraces []*omegav1.TraceSummary
	for _, t := range traces {
		protoTraces = append(protoTraces, dbTraceSummaryToProto(t))
	}
	return connect.NewResponse(&omegav1.ListTracesResponse{Traces: protoTraces}), nil
}

func (h *OrchestratorHandler) GetTrace(
	ctx context.Context,
	req *connect.Request[omegav1.GetTraceRequest],
) (*connect.Response[omegav1.GetTraceResponse], error) {
	spans, err := h.db.GetTraceSpans(req.Msg.TraceId)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	if len(spans) == 0 {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("trace not found: %s", req.Msg.TraceId))
	}
	var protoSpans []*omegav1.Span
	for _, s := range spans {
		protoSpans = append(protoSpans, dbSpanToProto(s))
	}
	return connect.NewResponse(&omegav1.GetTraceResponse{Spans: protoSpans}), nil
}

func dbTraceSummaryToProto(t *db.TraceSummary) *omegav1.TraceSummary {
	return &omegav1.TraceSummary{
		TraceId:         t.TraceID,
		TraceStarted:    tsFromUnix(t.TraceStarted),
		TraceEnded:      tsFromUnixPtr(t.TraceEnded),
		TotalDurationMs: t.TotalDurationMS,
		SpanCount:       t.SpanCount,
		ErrorSpans:      t.ErrorSpans,
		Cycle:           t.Cycle,
	}
}

func dbSpanToProto(s *db.Span) *omegav1.Span {
	span := &omegav1.Span{
		SpanId:       s.SpanID,
		TraceId:      s.TraceID,
		ParentSpanId: s.ParentSpanID,
		NodeId:       s.NodeID,
		NodeName:     s.NodeName,
		Operation:    s.Operation,
		StartedAt:    tsFromUnix(s.StartedAt),
		EndedAt:      tsFromUnixPtr(s.EndedAt),
		Status:       s.Status,
		Cycle:        s.Cycle,
	}
	if s.DurationMS != nil {
		span.DurationMs = *s.DurationMS
	}
	return span
}

// ── Metrics ───────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.GetMetricsRequest],
) (*connect.Response[omegav1.GetMetricsResponse], error) {
	health, err := h.db.SystemHealth()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	nodes, err := h.db.AllNodes()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	costs, _ := h.db.GetCosts()
	issues, _ := h.db.GetIssues("open")
	traces, _ := h.db.RecentTraces(5)

	resp := &omegav1.GetMetricsResponse{System: dbHealthToProto(health)}
	for _, n := range nodes {
		resp.Nodes = append(resp.Nodes, dbNodeToProto(n))
	}
	for _, c := range costs {
		resp.Costs = append(resp.Costs, dbCostToProto(c))
	}
	for _, i := range issues {
		resp.OpenIssues = append(resp.OpenIssues, dbIssueToProto(i))
	}
	for _, t := range traces {
		resp.RecentTraces = append(resp.RecentTraces, dbTraceSummaryToProto(t))
	}
	return connect.NewResponse(resp), nil
}

func (h *OrchestratorHandler) GetMetricsHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetMetricsHistoryRequest],
) (*connect.Response[omegav1.GetMetricsHistoryResponse], error) {
	nodes, err := h.db.AllNodes()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var histories []*omegav1.NodeLatencyHistory
	for _, n := range nodes {
		if req.Msg.NodeId != "" && n.NodeID != req.Msg.NodeId {
			continue
		}
		history, _ := h.db.LatencyHistory(n.NodeID, 100)
		nh := &omegav1.NodeLatencyHistory{NodeId: n.NodeID, Name: n.Name}
		for _, p := range history {
			nh.History = append(nh.History, &omegav1.LatencyPoint{
				Ts:         tsFromUnix(p.StartedAt),
				DurationMs: p.DurationMS,
				Success:    p.Success,
			})
		}
		histories = append(histories, nh)
	}
	return connect.NewResponse(&omegav1.GetMetricsHistoryResponse{NodeHistories: histories}), nil
}

// ── Issues ────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) ListIssues(
	ctx context.Context,
	req *connect.Request[omegav1.ListIssuesRequest],
) (*connect.Response[omegav1.ListIssuesResponse], error) {
	issues, err := h.db.GetIssues(req.Msg.StateFilter)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoIssues []*omegav1.Issue
	for _, i := range issues {
		protoIssues = append(protoIssues, dbIssueToProto(i))
	}
	return connect.NewResponse(&omegav1.ListIssuesResponse{Issues: protoIssues}), nil
}

func dbIssueToProto(i *db.Issue) *omegav1.Issue {
	issue := &omegav1.Issue{
		IssueId:     i.IssueID,
		Detector:    i.Detector,
		Severity:    i.Severity,
		Description: i.Description,
		State:       i.State,
		OpenedAt:    tsFromUnix(i.OpenedAt),
		ResolvedAt:  tsFromUnixPtr(i.ResolvedAt),
		CycleOpened: i.CycleOpened,
	}
	if i.CycleResolved != nil {
		issue.CycleResolved = *i.CycleResolved
	}
	return issue
}

// ── Activity ──────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) ListActivity(
	ctx context.Context,
	req *connect.Request[omegav1.ListActivityRequest],
) (*connect.Response[omegav1.ListActivityResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	entries, err := h.db.RecentActivity(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoEntries []*omegav1.ActivityEntry
	for _, e := range entries {
		protoEntries = append(protoEntries, &omegav1.ActivityEntry{
			LogId:      e.LogID,
			ActionType: e.ActionType,
			EntityType: e.EntityType,
			EntityId:   e.EntityID,
			RecordedAt: tsFromUnix(e.RecordedAt),
			Cycle:      e.Cycle,
		})
	}
	return connect.NewResponse(&omegav1.ListActivityResponse{Entries: protoEntries}), nil
}

// ── Improvements ──────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) ListImprovements(
	ctx context.Context,
	req *connect.Request[omegav1.ListImprovementsRequest],
) (*connect.Response[omegav1.ListImprovementsResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	imps, err := h.db.GetImprovements(req.Msg.NodeId, limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.ListImprovementsResponse{
		Improvements: dbImpsToProto(imps),
	}), nil
}

func dbImpsToProto(imps []*db.Improvement) []*omegav1.ImprovementRecord {
	result := make([]*omegav1.ImprovementRecord, 0, len(imps))
	for _, imp := range imps {
		result = append(result, &omegav1.ImprovementRecord{
			ImproveId:     imp.ImproveID,
			NodeId:        imp.NodeID,
			NodeName:      imp.NodeName,
			FromVersion:   imp.FromVersion,
			ToVersion:     imp.ToVersion,
			TriggeredBy:   imp.TriggeredBy,
			RecordedAt:    tsFromUnix(imp.RecordedAt),
			Cycle:         imp.Cycle,
			BeforeMetrics: imp.BeforeMetrics,
			AfterMetrics:  imp.AfterMetrics,
		})
	}
	return result
}

// ── Memory ────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetNodeMemory(
	ctx context.Context,
	req *connect.Request[omegav1.GetNodeMemoryRequest],
) (*connect.Response[omegav1.GetNodeMemoryResponse], error) {
	var namespace string
	if req.Msg.NodeId != "" {
		n, err := h.db.GetNode(req.Msg.NodeId)
		if err != nil {
			return nil, connect.NewError(connect.CodeNotFound, err)
		}
		namespace = n.Name
	}

	epCount, semCount, concepts, episodes, err := h.db.GetMemoryStats(namespace)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	resp := &omegav1.GetNodeMemoryResponse{
		Namespace:     namespace,
		EpisodicCount: epCount,
		SemanticCount: semCount,
	}
	for _, c := range concepts {
		resp.TopSemantic = append(resp.TopSemantic, &omegav1.SemanticConcept{
			Concept:       c.Concept,
			Content:       c.Content,
			Confidence:    c.Confidence,
			EvidenceCount: c.EvidenceCount,
			Tags:          c.Tags,
		})
	}
	for _, e := range episodes {
		resp.RecentEpisodes = append(resp.RecentEpisodes, &omegav1.EpisodeEntry{
			EpisodeId:  e.EpisodeID,
			EventType:  e.EventType,
			Timestamp:  tsFromUnix(e.Timestamp),
			Cycle:      e.Cycle,
			Importance: e.Importance,
			Tags:       e.Tags,
		})
	}
	return connect.NewResponse(resp), nil
}

// ── Convergence ───────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetConvergence(
	ctx context.Context,
	req *connect.Request[omegav1.GetConvergenceRequest],
) (*connect.Response[omegav1.GetConvergenceResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 100
	}
	points, err := h.db.GetConvergence(limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoPoints []*omegav1.ConvergencePoint
	for _, p := range points {
		protoPoints = append(protoPoints, &omegav1.ConvergencePoint{
			Cycle:      p.Cycle,
			Timestamp:  tsFromUnix(p.Timestamp),
			Score:      p.Score,
			PipelineMs: p.PipelineMS,
		})
	}
	return connect.NewResponse(&omegav1.GetConvergenceResponse{Points: protoPoints}), nil
}

// ── Costs ─────────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetCosts(
	ctx context.Context,
	req *connect.Request[omegav1.GetCostsRequest],
) (*connect.Response[omegav1.GetCostsResponse], error) {
	costs, err := h.db.GetCosts()
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoCosts []*omegav1.CostEntry
	for _, c := range costs {
		protoCosts = append(protoCosts, dbCostToProto(c))
	}
	return connect.NewResponse(&omegav1.GetCostsResponse{Costs: protoCosts}), nil
}

func dbCostToProto(c *db.CostEntry) *omegav1.CostEntry {
	return &omegav1.CostEntry{
		Provider:     c.Provider,
		NodeId:       c.NodeID,
		Calls:        c.Calls,
		TotalMs:      c.TotalMS,
		TotalCostUsd: c.TotalCostUSD,
	}
}

// ── Feedback ──────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) SubmitFeedback(
	ctx context.Context,
	req *connect.Request[omegav1.SubmitFeedbackRequest],
) (*connect.Response[omegav1.SubmitFeedbackResponse], error) {
	_ = ctx
	if err := h.db.LogActivity("human_feedback", "node", req.Msg.TargetNode, map[string]any{
		"text": req.Msg.Text,
	}, 0); err != nil {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("feedback storage failed: %w", err))
	}
	return connect.NewResponse(&omegav1.SubmitFeedbackResponse{Ok: true}), nil
}

// ── Orchestrator control ──────────────────────────────────────────────────────

func (h *OrchestratorHandler) StartOrchestrator(
	ctx context.Context,
	req *connect.Request[omegav1.StartOrchestratorRequest],
) (*connect.Response[omegav1.StartOrchestratorResponse], error) {
	_, _ = ctx, req
	// TODO: replace with Go-native orchestrator launch once a Go orchestrator is implemented.
	// The Python subprocess exec call has been removed as a security hardening measure.
	return connect.NewResponse(&omegav1.StartOrchestratorResponse{
		Started: false, Message: "orchestrator launch not available (pending Go implementation)",
	}), nil
}

func (h *OrchestratorHandler) StopOrchestrator(
	ctx context.Context,
	req *connect.Request[omegav1.StopOrchestratorRequest],
) (*connect.Response[omegav1.StopOrchestratorResponse], error) {
	_, _ = ctx, req
	return connect.NewResponse(&omegav1.StopOrchestratorResponse{
		Stopped: false, Message: "not running",
	}), nil
}

func (h *OrchestratorHandler) TriggerHeartbeat(
	ctx context.Context,
	req *connect.Request[omegav1.TriggerHeartbeatRequest],
) (*connect.Response[omegav1.TriggerHeartbeatResponse], error) {
	_ = ctx
	_ = req
	if err := h.db.LogActivity("heartbeat_trigger", "system", "orchestrator", map[string]any{}, 0); err != nil {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("heartbeat trigger failed: %w", err))
	}
	return connect.NewResponse(&omegav1.TriggerHeartbeatResponse{
		Triggered: true, Message: "triggered single heartbeat",
	}), nil
}

// ── Streaming ─────────────────────────────────────────────────────────────────

func (h *OrchestratorHandler) StreamEvents(
	ctx context.Context,
	req *connect.Request[omegav1.StreamEventsRequest],
	stream *connect.ServerStream[omegav1.EventResponse],
) error {
	interval := time.Duration(req.Msg.PollIntervalMs) * time.Millisecond
	if interval < 500*time.Millisecond {
		interval = 2 * time.Second
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			health, err := h.db.SystemHealth()
			if err != nil {
				continue
			}
			if err := stream.Send(&omegav1.EventResponse{
				Type: "health_update",
				Payload: &omegav1.EventResponse_HealthUpdate{
					HealthUpdate: dbHealthToProto(health),
				},
			}); err != nil {
				return err
			}
		}
	}
}

// ── Brain config RPCs ─────────────────────────────────────────────────────────

var knownProviders = []*omegav1.ProviderInfo{
	{Id: "anthropic", DisplayName: "Anthropic", Models: []string{"claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"}, RequiresApiKey: true, Available: true},
	{Id: "openai", DisplayName: "OpenAI", Models: []string{"gpt-4o", "gpt-4o-mini", "o1", "o3-mini"}, RequiresApiKey: true, Available: true},
	{Id: "google", DisplayName: "Google", Models: []string{"gemini-2.0-flash", "gemini-2.0-pro"}, RequiresApiKey: true, Available: true},
	{Id: "deepseek", DisplayName: "DeepSeek", Models: []string{"deepseek-chat", "deepseek-reasoner"}, RequiresApiKey: true, Available: true},
	{Id: "ollama", DisplayName: "Ollama (local)", Models: []string{"llama3.3", "qwen2.5-coder", "mistral"}, RequiresApiKey: false, Available: true},
}

func (h *OrchestratorHandler) ListAvailableProviders(
	ctx context.Context,
	req *connect.Request[omegav1.ListAvailableProvidersRequest],
) (*connect.Response[omegav1.ListAvailableProvidersResponse], error) {
	return connect.NewResponse(&omegav1.ListAvailableProvidersResponse{
		Providers: knownProviders,
	}), nil
}

func (h *OrchestratorHandler) GetNodeConfig(
	ctx context.Context,
	req *connect.Request[omegav1.GetNodeConfigRequest],
) (*connect.Response[omegav1.GetNodeConfigResponse], error) {
	n, err := h.db.GetNode(req.Msg.NodeId)
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("node not found: %s", req.Msg.NodeId))
	}
	brain, err := h.db.GetBrainConfig(req.Msg.NodeId)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.GetNodeConfigResponse{
		Config: dbNodeConfigToProto(n, brain),
	}), nil
}

func (h *OrchestratorHandler) UpdateNodeBrain(
	ctx context.Context,
	req *connect.Request[omegav1.UpdateNodeBrainRequest],
) (*connect.Response[omegav1.UpdateNodeBrainResponse], error) {
	if req.Msg.Brain == nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("brain config is required"))
	}
	brain := &db.BrainConfig{
		NodeID:       req.Msg.NodeId,
		Provider:     req.Msg.Brain.Provider,
		Model:        req.Msg.Brain.Model,
		Temperature:  req.Msg.Brain.Temperature,
		MaxTokens:    int64(req.Msg.Brain.MaxTokens),
		SystemPrompt: req.Msg.Brain.SystemPrompt,
		ExtraConfig:  req.Msg.Brain.ExtraConfig,
	}
	if err := h.db.SetBrainConfig(brain); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	n, _ := h.db.GetNode(req.Msg.NodeId)
	updatedBrain, _ := h.db.GetBrainConfig(req.Msg.NodeId)
	return connect.NewResponse(&omegav1.UpdateNodeBrainResponse{
		Config: dbNodeConfigToProto(n, updatedBrain),
	}), nil
}

func (h *OrchestratorHandler) GetBrainExecutionHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetBrainExecutionHistoryRequest],
) (*connect.Response[omegav1.GetBrainExecutionHistoryResponse], error) {
	limit := int(req.Msg.Limit)
	if limit <= 0 {
		limit = 50
	}
	entries, err := h.db.GetBrainHistory(req.Msg.NodeId, limit)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	var protoEntries []*omegav1.BrainExecutionEntry
	for _, e := range entries {
		protoEntries = append(protoEntries, &omegav1.BrainExecutionEntry{
			ExecId:           e.ExecID,
			NodeId:           e.NodeID,
			Provider:         e.Provider,
			Model:            e.Model,
			PromptTokens:     e.PromptTokens,
			CompletionTokens: e.CompletionTokens,
			LatencyMs:        e.LatencyMS,
			Success:          e.Success,
			ErrorText:        e.ErrorText,
			ExecutedAt:       tsFromUnix(e.ExecutedAt),
			Cycle:            e.Cycle,
		})
	}
	return connect.NewResponse(&omegav1.GetBrainExecutionHistoryResponse{Entries: protoEntries}), nil
}

func dbNodeConfigToProto(n *db.Node, brain *db.BrainConfig) *omegav1.NodeConfig {
	cfg := &omegav1.NodeConfig{
		NodeId:   n.NodeID,
		NodeType: n.Name,
		Version:  n.Version,
		Brain: &omegav1.BrainConfig{
			Provider:     brain.Provider,
			Model:        brain.Model,
			Temperature:  brain.Temperature,
			MaxTokens:    int32(brain.MaxTokens), //nolint:gosec
			SystemPrompt: brain.SystemPrompt,
			ExtraConfig:  brain.ExtraConfig,
		},
		UpdatedAt: tsFromUnix(brain.UpdatedAt),
	}
	return cfg
}
