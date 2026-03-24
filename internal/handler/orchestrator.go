// Package handler implements the OrchestratorService Connect-RPC handler.
package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"connectrpc.com/connect"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/bridge"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/observability"
	"github.com/benebsworth/omega/internal/telemetry"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.OrchestratorServiceHandler = (*OrchestratorHandler)(nil)

// lastCycleResult holds the most recent cycle's outcome for GetLastCycleResult.
type lastCycleResult struct {
	Cycle      int64
	Steps      []stepResult
	TotalMS    float64
	ErrorCount int32
}

// OrchestratorHandler implements OrchestratorService.
type OrchestratorHandler struct {
	db             *db.DB
	cbRegistry     *observability.CircuitBreakerRegistry // may be nil
	pipelineClient *bridge.PipelineClient                // may be nil
	projectHandler *ProjectHandler                       // may be nil; provides pipeline configs
	metrics        *observability.Metrics                // may be nil

	mu     sync.Mutex
	cancel context.CancelFunc // non-nil while orchestrator loop is running
	cycleN atomic.Int64       // total cycles completed

	lastCycleMu    sync.RWMutex
	lastCycleCache *lastCycleResult
}

// New creates an OrchestratorHandler backed by the given DB.
func New(database *db.DB) *OrchestratorHandler {
	return &OrchestratorHandler{db: database}
}

// WithCircuitBreakerRegistry attaches a circuit breaker registry so that
// ListNodes and GetNode responses include live circuit breaker state.
func (h *OrchestratorHandler) WithCircuitBreakerRegistry(r *observability.CircuitBreakerRegistry) *OrchestratorHandler {
	h.cbRegistry = r
	return h
}

// WithPipelineClient attaches a Python pipeline client so runCycle() can drive
// pipeline step execution on the Python side.  When set, each orchestration
// cycle will call ExecuteStep on the Python server for every pipeline step
// defined in the registered projects.
func (h *OrchestratorHandler) WithPipelineClient(c *bridge.PipelineClient) *OrchestratorHandler {
	h.pipelineClient = c
	return h
}

// WithProjectHandler attaches the project registry so runCycle() can read
// pipeline configurations from registered projects instead of using
// hardcoded step lists.
func (h *OrchestratorHandler) WithProjectHandler(ph *ProjectHandler) *OrchestratorHandler {
	h.projectHandler = ph
	return h
}

// WithMetrics attaches the Prometheus metrics instance so runCycleWithResults()
// can increment cycle/node counters on the same registry that /metrics serves.
func (h *OrchestratorHandler) WithMetrics(m *observability.Metrics) *OrchestratorHandler {
	h.metrics = m
	return h
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
		pn := dbNodeToProto(n)
		h.attachCircuitBreaker(pn, n.NodeID)
		protoNodes = append(protoNodes, pn)
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

	pn := dbNodeToProto(n)
	h.attachCircuitBreaker(pn, req.Msg.NodeId)
	resp := &omegav1.GetNodeResponse{
		Node:         pn,
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

// attachCircuitBreaker populates the circuit_breaker field on a Node proto
// from the in-memory registry. No-op if the registry is nil or has no entry.
func (h *OrchestratorHandler) attachCircuitBreaker(n *omegav1.Node, nodeID string) {
	if h.cbRegistry == nil {
		return
	}
	info, ok := h.cbRegistry.NodeInfo(nodeID)
	if !ok {
		return
	}
	cb := &omegav1.CircuitBreakerState{
		State:        info.State.String(),
		FailureCount: info.Failures,
	}
	if !info.LastFailure.IsZero() {
		cb.LastFailureTime = timestamppb.New(info.LastFailure)
	}
	n.CircuitBreaker = cb
}

func dbExecToProto(e *db.Execution) *omegav1.ExecutionRecord {
	rec := &omegav1.ExecutionRecord{
		ExecId:      e.ExecID,
		NodeId:      e.NodeID,
		NodeName:    e.NodeName,
		TraceId:     e.TraceID,
		SpanId:      e.SpanID,
		Action:      e.Action,
		StartedAt:   tsFromUnix(e.StartedAt),
		EndedAt:     tsFromUnixPtr(e.EndedAt),
		Success:     e.Success,
		ErrorText:   e.ErrorText,
		Metrics:     e.Metrics,
		Cycle:       e.Cycle,
		ErrorClass:  omegav1.ErrorClassification(e.ErrorClass),
		ErrorCode:   e.ErrorCode,
		IsRetryable: e.IsRetryable,
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
	traces, err := h.db.RecentTraces(limit, req.Msg.NodeFilter)
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
	traces, _ := h.db.RecentTraces(5, "")

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

// StartOrchestrator starts the Go orchestration loop if it is not already running.
// The loop runs one cycle per heartbeat_secs, emitting an OTel span per cycle and
// recording a DB activity entry.  It exits cleanly when the returned context is
// cancelled (via StopOrchestrator) or when the parent server context is done.
func (h *OrchestratorHandler) StartOrchestrator(
	ctx context.Context,
	req *connect.Request[omegav1.StartOrchestratorRequest],
) (*connect.Response[omegav1.StartOrchestratorResponse], error) {
	interval := time.Duration(req.Msg.HeartbeatSecs) * time.Second
	if interval <= 0 {
		interval = 60 * time.Second
	}

	h.mu.Lock()
	defer h.mu.Unlock()

	if h.cancel != nil {
		return connect.NewResponse(&omegav1.StartOrchestratorResponse{
			Started: false, Message: "orchestrator already running",
		}), nil
	}

	loopCtx, cancel := context.WithCancel(ctx)
	h.cancel = cancel

	go h.runLoop(loopCtx, interval)

	return connect.NewResponse(&omegav1.StartOrchestratorResponse{
		Started: true, Message: fmt.Sprintf("orchestrator started (interval=%s)", interval),
	}), nil
}

// runLoop is the main orchestration goroutine.  It runs until ctx is cancelled.
func (h *OrchestratorHandler) runLoop(ctx context.Context, interval time.Duration) {
	defer func() {
		h.mu.Lock()
		h.cancel = nil
		h.mu.Unlock()
	}()

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			h.runCycle(ctx)
		}
	}
}

// stepResult captures the outcome of one pipeline step execution.
type stepResult struct {
	Name       string
	NodeType   string
	NodeID     string
	Success    bool
	DurationMS float64
	Error      string
	Metrics    map[string]float64
}

// runCycleWithResults executes one orchestration cycle and returns per-step results.
// It is called synchronously by TriggerHeartbeat so the caller can surface step
// success/failure and latency directly in the response.
func (h *OrchestratorHandler) runCycleWithResults(ctx context.Context) ([]stepResult, error) {
	t0Cycle := time.Now()
	cycle := h.cycleN.Add(1)

	tracer := telemetry.Tracer()
	cycleCtx, cycleSpan := tracer.Start(ctx, "orchestrator.cycle",
		trace.WithAttributes(attribute.Int64("cycle", cycle)),
	)
	defer cycleSpan.End()

	nodes, err := h.db.AllNodes()
	if err != nil {
		cycleSpan.SetStatus(codes.Error, err.Error())
		_ = h.db.LogActivity("cycle_error", "system", "orchestrator", map[string]any{
			"cycle": cycle, "error": err.Error(),
		}, cycle)
		return nil, err
	}

	for _, n := range nodes {
		_, nodeSpan := tracer.Start(cycleCtx, "orchestrator.node",
			trace.WithAttributes(
				attribute.String("node_id", n.NodeID),
				attribute.String("node_name", n.Name),
				attribute.Float64("health", n.Health),
				attribute.Int64("cycle", cycle),
			),
		)
		nodeSpan.End()
	}

	var results []stepResult

	if h.pipelineClient != nil {
		projects := h.projectPipelineSteps()
		if len(projects) == 0 {
			_ = h.db.LogActivity("cycle_warning", "system", "orchestrator", map[string]any{
				"cycle": cycle, "warning": "no projects registered — pipeline dispatch skipped",
			}, cycle)
		}
		for projectID, steps := range projects {
			var projectResults []stepResult
			for _, step := range steps {
				_, stepSpan := tracer.Start(cycleCtx, "orchestrator.pipeline.step",
					trace.WithAttributes(
						attribute.String("project_id", projectID),
						attribute.String("step_id", step.StepId),
						attribute.String("step_name", step.Name),
						attribute.String("node_type", step.NodeType),
						attribute.Int64("cycle", cycle),
					),
				)
				execID, _ := h.db.BeginExecution(step.NodeType, step.Name, step.NodeType, nil, nil, cycle)
				t0 := time.Now()
				resp, stepErr := h.pipelineClient.ExecuteStep(cycleCtx, &omegav1.ExecuteStepRequest{
					StepId:    step.StepId,
					StepName:  step.Name,
					NodeType:  step.NodeType,
					Cycle:     cycle,
					ProjectId: projectID,
				})
				elapsed := float64(time.Since(t0).Milliseconds())
				sr := stepResult{Name: step.Name, NodeType: step.NodeType, DurationMS: elapsed}
				if stepErr != nil {
					sr.Success = false
					sr.Error = stepErr.Error()
					stepSpan.SetStatus(codes.Error, stepErr.Error())
				} else {
					sr.Success = resp.Success
					sr.NodeID = resp.NodeId
					sr.Metrics = resp.Metrics
					if !resp.Success {
						sr.Error = resp.ErrorText
						stepSpan.SetStatus(codes.Error, resp.ErrorText)
					} else {
						stepSpan.SetStatus(codes.Ok, "")
					}
					stepSpan.SetAttributes(
						attribute.Bool("success", resp.Success),
						attribute.Float64("duration_ms", resp.DurationMs),
						attribute.String("node_id", resp.NodeId),
					)
					elapsed = resp.DurationMs // prefer server-side measurement
					sr.DurationMS = elapsed
				}
				if execID != "" {
					_ = h.db.EndExecution(execID, sr.Success, sr.Error, 0, "", false, map[string]float64{"duration_ms": elapsed})
				}
				if h.metrics != nil {
					status := "success"
					if !sr.Success {
						status = "error"
					}
					h.metrics.IncNodeExecution(step.Name, status)
					h.metrics.ObserveNodeDuration(step.Name, elapsed/1000)
				}
				stepSpan.End()

				// Record execution outcome and update Prometheus metrics.
				if execID != "" {
					_ = h.db.EndExecution(execID, sr.Success, sr.Error, 0, "", false, nil)
				}
				if h.metrics != nil {
					statusStr := "success"
					if !sr.Success {
						statusStr = "error"
					}
					h.metrics.IncNodeExecution(step.Name, statusStr)
					h.metrics.ObserveNodeDuration(step.Name, elapsed/1000.0)
				}

				results = append(results, sr)
				projectResults = append(projectResults, sr)

				// ── DARK signal: improvement log ────────────────────────────────────
				if sr.NodeType == "IMPROVEMENT" && sr.NodeID != "" {
					if err := h.db.RecordImprovement(
						sr.NodeID, sr.Name,
						fmt.Sprintf("cycle-%d", cycle-1),
						fmt.Sprintf("cycle-%d", cycle),
						map[string]float64{}, sr.Metrics,
						"tpe", cycle,
					); err != nil {
						_ = err // non-fatal
					}
				}

				// ── DARK signal: verification gates ─────────────────────────────────
				if sr.NodeType == "VERIFICATION" {
					if err := h.db.RecordVerificationGate(cycle, sr.Name, sr.Success, sr.Error); err != nil {
						_ = err // non-fatal
					}
				}
			}

			// ── DARK signal: coordination outcome (per project) ──────────────────
			h.recordCoordinationOutcome(ctx, projectID, cycle, projectResults)

			// ── DARK signal: goal tracking (per project) ─────────────────────────
			h.recordGoalTracking(projectID, cycle, projectResults)
		}
	}

	_ = h.db.LogActivity("cycle_complete", "system", "orchestrator", map[string]any{
		"cycle": cycle, "node_count": len(nodes),
	}, cycle)
	if h.metrics != nil {
		h.metrics.IncCycles()
	}
	cycleSpan.SetStatus(codes.Ok, "")

	// Cache last cycle result for GetLastCycleResult.
	var errCount int32
	for _, r := range results {
		if !r.Success {
			errCount++
		}
	}
	h.lastCycleMu.Lock()
	h.lastCycleCache = &lastCycleResult{
		Cycle:      cycle,
		Steps:      results,
		TotalMS:    float64(time.Since(t0Cycle).Milliseconds()),
		ErrorCount: errCount,
	}
	h.lastCycleMu.Unlock()

	return results, nil
}

// runCycle executes one orchestration cycle. Delegates to runCycleWithResults
// and discards the step results (they are only surfaced via TriggerHeartbeat).
func (h *OrchestratorHandler) runCycle(ctx context.Context) {
	_, _ = h.runCycleWithResults(ctx) //nolint:errcheck
}

// projectPipelineSteps returns the ordered pipeline steps for each registered
// active project, keyed by project_id.  When no ProjectHandler is attached or
// no projects are registered, returns an empty map.
//
// This is the single place where the orchestrator reads project-driven pipeline
// configurations.  No project-specific step names live in this file.
func (h *OrchestratorHandler) projectPipelineSteps() map[string][]*omegav1.PipelineStep {
	result := make(map[string][]*omegav1.PipelineStep)
	if h.projectHandler == nil {
		return result
	}
	for _, p := range h.projectHandler.AllProjects() {
		if p.Status != "active" || len(p.PipelineConfig) == 0 {
			continue
		}
		steps := make([]*omegav1.PipelineStep, len(p.PipelineConfig))
		copy(steps, p.PipelineConfig)
		result[p.ProjectId] = steps
	}
	return result
}

func (h *OrchestratorHandler) StopOrchestrator(
	ctx context.Context,
	req *connect.Request[omegav1.StopOrchestratorRequest],
) (*connect.Response[omegav1.StopOrchestratorResponse], error) {
	_ = ctx
	_ = req

	h.mu.Lock()
	cancel := h.cancel
	h.mu.Unlock()

	if cancel == nil {
		return connect.NewResponse(&omegav1.StopOrchestratorResponse{
			Stopped: false, Message: "orchestrator is not running",
		}), nil
	}

	cancel()
	return connect.NewResponse(&omegav1.StopOrchestratorResponse{
		Stopped: true, Message: "orchestrator stopped",
	}), nil
}

func (h *OrchestratorHandler) TriggerHeartbeat(
	ctx context.Context,
	req *connect.Request[omegav1.TriggerHeartbeatRequest],
) (*connect.Response[omegav1.TriggerHeartbeatResponse], error) {
	_ = req
	if err := h.db.LogActivity("heartbeat_trigger", "system", "orchestrator", map[string]any{}, 0); err != nil {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("heartbeat trigger failed: %w", err))
	}

	t0 := time.Now()
	results, err := h.runCycleWithResults(ctx)
	totalMS := float64(time.Since(t0).Milliseconds())

	// Build a human-readable step summary packed into Message.
	var msg string
	switch {
	case err != nil:
		msg = fmt.Sprintf("cycle error: %s", err)
	case len(results) == 0:
		msg = fmt.Sprintf("cycle complete in %.0fms (no pipeline steps)", totalMS)
	default:
		var errCount int
		lines := make([]string, 0, len(results)+2)
		for _, r := range results {
			if r.Success {
				lines = append(lines, fmt.Sprintf("  %s: success (%.0fms)", r.Name, r.DurationMS))
			} else {
				errCount++
				lines = append(lines, fmt.Sprintf("  %s: FAILED (%s)", r.Name, r.Error))
			}
		}
		summary := fmt.Sprintf("cycle complete in %.0fms — %d steps, %d errors",
			totalMS, len(results), errCount)
		lines = append([]string{summary}, lines...)
		for i, l := range lines {
			if i == 0 {
				msg = l
			} else {
				msg += "\n" + l
			}
		}
	}

	return connect.NewResponse(&omegav1.TriggerHeartbeatResponse{
		Triggered: true, Message: msg,
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

// ── GetLastCycleResult ────────────────────────────────────────────────────────

func (h *OrchestratorHandler) GetLastCycleResult(
	ctx context.Context,
	req *connect.Request[omegav1.GetLastCycleResultRequest],
) (*connect.Response[omegav1.GetLastCycleResultResponse], error) {
	_ = ctx
	_ = req
	h.lastCycleMu.RLock()
	cached := h.lastCycleCache
	h.lastCycleMu.RUnlock()

	if cached == nil {
		return connect.NewResponse(&omegav1.GetLastCycleResultResponse{
			HasResult: false,
		}), nil
	}

	resp := &omegav1.GetLastCycleResultResponse{
		Cycle:           cached.Cycle,
		TotalDurationMs: cached.TotalMS,
		ErrorCount:      cached.ErrorCount,
		HasResult:       true,
	}
	for _, s := range cached.Steps {
		resp.StepResults = append(resp.StepResults, &omegav1.CycleStepResult{
			Name:       s.Name,
			Success:    s.Success,
			DurationMs: s.DurationMS,
			Error:      s.Error,
		})
	}
	return connect.NewResponse(resp), nil
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

// ── DARK signal helpers ───────────────────────────────────────────────────────

// recordCoordinationOutcome writes a per-cycle coordination outcome tuple.
// outcome_quality is the fraction of steps that succeeded (0.0–1.0).
func (h *OrchestratorHandler) recordCoordinationOutcome(ctx context.Context, projectID string, cycle int64, results []stepResult) {
	if len(results) == 0 {
		return
	}
	var successes int
	for _, r := range results {
		if r.Success {
			successes++
		}
	}
	quality := float64(successes) / float64(len(results))

	// routing_json: ordered list of steps that ran
	type routingStep struct {
		Name       string  `json:"name"`
		NodeType   string  `json:"node_type"`
		Success    bool    `json:"success"`
		DurationMS float64 `json:"duration_ms"`
	}
	rSteps := make([]routingStep, 0, len(results))
	for _, r := range results {
		rSteps = append(rSteps, routingStep{Name: r.Name, NodeType: r.NodeType, Success: r.Success, DurationMS: r.DurationMS})
	}
	rJSON, _ := json.Marshal(rSteps)

	// state_snapshot: per-step success/duration keyed by step name
	snapshot := make(map[string]any, len(results))
	for _, r := range results {
		snapshot[r.Name] = map[string]any{
			"success":     r.Success,
			"duration_ms": r.DurationMS,
			"node_id":     r.NodeID,
		}
	}
	sJSON, _ := json.Marshal(snapshot)

	goalID := fmt.Sprintf("%s:cycle:%d", projectID, cycle)
	if err := h.db.RecordCoordinationOutcome(goalID, quality, string(rJSON), string(sJSON)); err != nil {
		_ = err // non-fatal
	}
}

// recordGoalTracking writes per-cycle goal progress from the project's eval_config.
// Uses the improvement_metrics from step results where available.
func (h *OrchestratorHandler) recordGoalTracking(projectID string, cycle int64, results []stepResult) {
	if h.projectHandler == nil {
		return
	}
	// Find the project to read eval_config targets
	var evalConfig *omegav1.EvalConfig
	for _, p := range h.projectHandler.AllProjects() {
		if p.ProjectId == projectID {
			evalConfig = p.EvalConfig
			break
		}
	}
	if evalConfig == nil || len(evalConfig.MetricTargets) == 0 {
		return
	}

	// Gather any metrics from step results to compare against targets
	stepMetrics := make(map[string]float64)
	for _, r := range results {
		for k, v := range r.Metrics {
			if _, exists := stepMetrics[k]; !exists {
				stepMetrics[k] = v
			}
		}
	}

	// Compute composite score and scorecard
	var compositeScore float64
	scorecard := make(map[string]any, len(evalConfig.MetricTargets))
	violations := make([]string, 0)
	for metric, target := range evalConfig.MetricTargets {
		current, ok := stepMetrics[metric]
		if !ok {
			current = 0
		}
		gap := current - target
		scorecard[metric] = map[string]any{
			"target":  target,
			"current": current,
			"gap":     gap,
		}
		if target != 0 {
			compositeScore += current / target
		}
		if gap < 0 {
			violations = append(violations, fmt.Sprintf("%s: %.4f < %.4f (gap %.4f)", metric, current, target, gap))
		}
	}
	if len(evalConfig.MetricTargets) > 0 {
		compositeScore /= float64(len(evalConfig.MetricTargets))
	}

	_, _ = h.db.RecordGoalTracking(
		cycle,
		len(violations) == 0,
		compositeScore,
		scorecard,
		map[string]any{},
		0.0,
		map[string]any{"project_id": projectID},
		[]string{},
		violations,
	)
}
