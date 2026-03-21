package handler

import (
	"context"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/core"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.AutonomyServiceHandler = (*AutonomyHandler)(nil)

// AutonomyHandler implements AutonomyService — per-node autonomy level management.
type AutonomyHandler struct {
	mgr *core.AutonomyManager
}

// NewAutonomy creates an AutonomyHandler backed by an in-memory AutonomyManager.
func NewAutonomy() *AutonomyHandler {
	return &AutonomyHandler{mgr: core.NewAutonomyManager()}
}

// ── RecordCycleMetrics ────────────────────────────────────────────────────────

func (h *AutonomyHandler) RecordCycleMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.RecordCycleMetricsRequest],
) (*connect.Response[omegav1.RecordCycleMetricsResponse], error) {
	h.mgr.RecordCycleMetrics(req.Msg.NodeId, req.Msg.Cycle, req.Msg.Metrics, req.Msg.Success)
	return connect.NewResponse(&omegav1.RecordCycleMetricsResponse{Ok: true}), nil
}

// ── GetAutonomyLevel ──────────────────────────────────────────────────────────

func (h *AutonomyHandler) GetAutonomyLevel(
	ctx context.Context,
	req *connect.Request[omegav1.GetAutonomyLevelRequest],
) (*connect.Response[omegav1.GetAutonomyLevelResponse], error) {
	st := h.mgr.GetLevel(req.Msg.NodeId)
	return connect.NewResponse(&omegav1.GetAutonomyLevelResponse{
		NodeId:        req.Msg.NodeId,
		Level:         omegav1.AutonomyLevel(st.Level),
		Confidence:    st.Confidence,
		CyclesAtLevel: st.CyclesAtLevel,
		Since:         timestamppb.New(st.Since),
	}), nil
}

// ── RequestPromotion ──────────────────────────────────────────────────────────

func (h *AutonomyHandler) RequestPromotion(
	ctx context.Context,
	req *connect.Request[omegav1.RequestPromotionRequest],
) (*connect.Response[omegav1.RequestPromotionResponse], error) {
	result := h.mgr.RequestPromotion(
		ctx,
		req.Msg.NodeId,
		core.AutonomyLevel(req.Msg.RequestedLevel),
		req.Msg.SupportingMetrics,
		req.Msg.Cycle,
	)
	return connect.NewResponse(&omegav1.RequestPromotionResponse{
		Approved:     result.Approved,
		GrantedLevel: omegav1.AutonomyLevel(result.GrantedLevel),
		Reasons:      result.Reasons,
	}), nil
}

// ── RecordPromotion ───────────────────────────────────────────────────────────

func (h *AutonomyHandler) RecordPromotion(
	ctx context.Context,
	req *connect.Request[omegav1.RecordPromotionRequest],
) (*connect.Response[omegav1.RecordPromotionResponse], error) {
	h.mgr.RecordPromotion(
		req.Msg.NodeId,
		core.AutonomyLevel(req.Msg.FromLevel),
		core.AutonomyLevel(req.Msg.ToLevel),
		req.Msg.Trigger,
		req.Msg.Cycle,
	)
	return connect.NewResponse(&omegav1.RecordPromotionResponse{Ok: true}), nil
}

// ── GetAutonomyHistory ────────────────────────────────────────────────────────

func (h *AutonomyHandler) GetAutonomyHistory(
	ctx context.Context,
	req *connect.Request[omegav1.GetAutonomyHistoryRequest],
) (*connect.Response[omegav1.GetAutonomyHistoryResponse], error) {
	events := h.mgr.GetHistory(req.Msg.NodeId, int(req.Msg.Limit))
	protoEvents := make([]*omegav1.AutonomyEvent, 0, len(events))
	for _, e := range events {
		protoEvents = append(protoEvents, &omegav1.AutonomyEvent{
			NodeId:     e.NodeID,
			FromLevel:  omegav1.AutonomyLevel(e.FromLevel),
			ToLevel:    omegav1.AutonomyLevel(e.ToLevel),
			Trigger:    e.Trigger,
			Cycle:      e.Cycle,
			RecordedAt: timestamppb.New(e.RecordedAt),
		})
	}
	return connect.NewResponse(&omegav1.GetAutonomyHistoryResponse{
		Events: protoEvents,
	}), nil
}

// ── StreamNodeMetrics ─────────────────────────────────────────────────────────

func (h *AutonomyHandler) StreamNodeMetrics(
	ctx context.Context,
	req *connect.Request[omegav1.StreamNodeMetricsRequest],
	stream *connect.ServerStream[omegav1.NodeMetricsEvent],
) error {
	// Block until the client disconnects; the orchestrator pushes metrics via
	// RecordCycleMetrics. A future implementation can use a pub/sub fanout here.
	<-ctx.Done()
	return nil
}
