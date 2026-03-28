// handler.go — CoordinationService Connect-RPC handler.
//
// Handler implements omegav1connect.CoordinationServiceHandler and wires
// together the AttentionRouter, TensorAggregator, RoutingWeightAdapter,
// and OutcomeStore into a single service endpoint.
//
// Routing is always handled by the AttentionRouter (attention mode is the
// only mode — there is no legacy fallback).

package coordination

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/google/uuid"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Ensure Handler satisfies the generated interface at compile time.
var _ omegav1connect.CoordinationServiceHandler = (*Handler)(nil)

// Handler is the CoordinationService implementation.
type Handler struct {
	omegav1connect.UnimplementedCoordinationServiceHandler

	router  *AttentionRouter
	agg     *TensorAggregator
	adapter *RoutingWeightAdapter
	store   *OutcomeStore // may be nil — outcomes silently dropped
	logger  *slog.Logger
}

// NewHandler creates a Handler with the provided components.
// store may be nil if outcome persistence is not required.
func NewHandler(
	router *AttentionRouter,
	agg *TensorAggregator,
	adapter *RoutingWeightAdapter,
	store *OutcomeStore,
	logger *slog.Logger,
) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{
		router:  router,
		agg:     agg,
		adapter: adapter,
		store:   store,
		logger:  logger,
	}
}

// NewDefaultHandler builds a fully wired Handler with hand-initialised weights.
// store may be nil.
func NewDefaultHandler(store *OutcomeStore, logger *slog.Logger) *Handler {
	adapter := NewRoutingWeightAdapter(0.95)
	router := NewAttentionRouterWithDeps(
		NewLinearGoalEncoder(),
		NewNodeProjector(),
		adapter,
	)
	return NewHandler(router, NewTensorAggregator(), adapter, store, logger)
}

// ---------------------------------------------------------------------------
// SignalQualityFeeder — feeds empirical signal quality into routing priors
// ---------------------------------------------------------------------------

// SignalQualityDB is the interface the handler uses to read signal quality.
// Satisfied by *db.VictoriaDB; defined here to avoid an import cycle.
type SignalQualityDB interface {
	GetAvgSignalQuality() (float64, error)
}

// RefreshFromSignalPerf reads the average composite_score from signal_performance
// and updates the RoutingWeightAdapter prior for the named node.
//
// Call this after each training cycle (or on a timer) to let empirical signal
// quality influence which nodes the attention router prefers for signal-related goals.
//
//	handler.RefreshFromSignalPerf(db, "victoria_node_1")
func (h *Handler) RefreshFromSignalPerf(qualityDB SignalQualityDB, nodeID string) {
	if h.adapter == nil {
		return
	}
	avg, err := qualityDB.GetAvgSignalQuality()
	if err != nil {
		h.logger.Warn("RefreshFromSignalPerf: could not read signal quality", "err", err)
		return
	}
	// Clamp to [0, 1] and scale to outcome score range
	if avg < 0 {
		avg = 0
	}
	if avg > 1 {
		avg = 1
	}
	h.adapter.UpdateFromOutcome(nodeID, float32(avg))
	h.logger.Debug("RefreshFromSignalPerf: updated routing prior",
		"node", nodeID, "signal_quality", avg)
}

// ---------------------------------------------------------------------------
// Route RPC
// ---------------------------------------------------------------------------

// Route implements CoordinationService.Route.
// It runs the attention router over current node tensors and returns a RoutingPlan.
func (h *Handler) Route(
	ctx context.Context,
	req *connect.Request[omegav1.CoordinationRequest],
) (*connect.Response[omegav1.CoordinationResponse], error) {
	goal := req.Msg.Goal
	if goal == nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("goal is required"))
	}

	// Gather tensors — filter to requested candidates if specified
	allTensors := h.agg.AllTensors()
	tensors := allTensors
	if len(req.Msg.CandidateNodeIds) > 0 {
		tensors = make(map[string]*omegav1.StateTensor, len(req.Msg.CandidateNodeIds))
		for _, nid := range req.Msg.CandidateNodeIds {
			if t, ok := allTensors[nid]; ok {
				tensors[nid] = t
			}
		}
	}

	if len(tensors) == 0 {
		return nil, connect.NewError(connect.CodeFailedPrecondition,
			fmt.Errorf("no node tensors available — cannot route"))
	}

	// Build capabilities map from aggregator
	capabilities := make(map[string][]string, len(tensors))
	for nid := range tensors {
		capabilities[nid] = h.agg.NodeCapabilities(nid)
	}

	result, err := h.router.Route(goal, tensors, capabilities)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("router: %w", err))
	}

	traceID := req.Msg.TraceId
	if traceID == "" {
		traceID = uuid.New().String()
	}

	h.logger.Info("routed goal",
		"goal_id", goal.GoalId,
		"goal_type", goal.Type.String(),
		"primary_node", result.PrimaryNode,
		"confidence", result.Confidence,
		"trace_id", traceID,
	)

	return connect.NewResponse(&omegav1.CoordinationResponse{
		Plan:    result.ToProto(),
		TraceId: traceID,
	}), nil
}

// ---------------------------------------------------------------------------
// RecordOutcome RPC
// ---------------------------------------------------------------------------

// RecordOutcome persists a routing outcome tuple and updates the EMA adapter.
func (h *Handler) RecordOutcome(
	ctx context.Context,
	req *connect.Request[omegav1.RecordCoordinationOutcomeRequest],
) (*connect.Response[omegav1.RecordCoordinationOutcomeResponse], error) {
	record := req.Msg.Record
	if record == nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("record is required"))
	}

	if record.RecordId == "" {
		record.RecordId = uuid.New().String()
	}
	if record.CapturedAt == nil {
		record.CapturedAt = timestamppb.New(time.Now())
	}

	// Update EMA adapter for the primary node
	if record.RoutingPlan != nil && record.RoutingPlan.PrimaryNode != "" {
		// Normalise outcome_quality ∈ [−1,1] → [0,1] for EMA
		normalised := (record.OutcomeQuality + 1.0) / 2.0
		h.adapter.UpdateFromOutcome(record.RoutingPlan.PrimaryNode, normalised)
	}

	// Persist if store available
	if h.store != nil {
		recordID, err := h.store.Store(ctx, record)
		if err != nil {
			h.logger.Warn("failed to persist outcome record", "err", err, "record_id", record.RecordId)
			// Non-fatal: EMA adapter already updated.
		} else {
			record.RecordId = recordID
		}
	}

	return connect.NewResponse(&omegav1.RecordCoordinationOutcomeResponse{
		RecordId: record.RecordId,
	}), nil
}

// ---------------------------------------------------------------------------
// GetRoutingStats RPC
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Accessor helpers (useful in tests and for wiring)
// ---------------------------------------------------------------------------

// Agg returns the TensorAggregator so callers can seed it with tensors.
func (h *Handler) Agg() *TensorAggregator {
	return h.agg
}

// RouteGoal is a convenience wrapper around Route that accepts a plain
// CoordinationRequest and returns CoordinationResponse (bypassing Connect-RPC
// request wrapping). Useful in tests and for direct Go callers.
func (h *Handler) RouteGoal(ctx context.Context, req *omegav1.CoordinationRequest) (*omegav1.CoordinationResponse, error) {
	resp, err := h.Route(ctx, connect.NewRequest(req))
	if err != nil {
		return nil, err
	}
	return resp.Msg, nil
}

// RecordOutcomeRecord is a convenience wrapper for RecordOutcome.
func (h *Handler) RecordOutcomeRecord(ctx context.Context, record *omegav1.OutcomeRecord) (string, error) {
	resp, err := h.RecordOutcome(ctx, connect.NewRequest(&omegav1.RecordCoordinationOutcomeRequest{
		Record: record,
	}))
	if err != nil {
		return "", err
	}
	return resp.Msg.RecordId, nil
}

// AdapterPriorFor returns the EMA prior for a node (useful in tests).
func (h *Handler) AdapterPriorFor(nodeID string) float32 {
	return h.adapter.PriorFor(nodeID)
}

// GetRoutingStats returns aggregate routing statistics.
func (h *Handler) GetRoutingStats(
	ctx context.Context,
	req *connect.Request[omegav1.GetRoutingStatsRequest],
) (*connect.Response[omegav1.GetRoutingStatsResponse], error) {
	if h.store == nil {
		// No store — return zero stats
		return connect.NewResponse(&omegav1.GetRoutingStatsResponse{}), nil
	}

	var since time.Time
	if req.Msg.Since != nil {
		since = req.Msg.Since.AsTime()
	}

	stats, err := h.store.Stats(ctx, since)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("stats query: %w", err))
	}

	return connect.NewResponse(stats), nil
}
