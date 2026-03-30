// Package heartbeat — Connect-RPC handler for HeartbeatService.
package heartbeat

import (
	"context"
	"fmt"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
)

// Compile-time interface check.
var _ omegav1connect.HeartbeatServiceHandler = (*Handler)(nil)

// Handler implements HeartbeatService backed by the in-memory Store.
type Handler struct {
	store *Store
}

// NewHandler returns a Handler wrapping the given store.
func NewHandler(store *Store) *Handler {
	return &Handler{store: store}
}

// SendHeartbeat records a node heartbeat and acknowledges it.
func (h *Handler) SendHeartbeat(
	ctx context.Context,
	req *connect.Request[omegav1.Heartbeat],
) (*connect.Response[omegav1.HeartbeatAck], error) {
	if req.Msg.GetNodeId() == "" {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("node_id required"))
	}
	if req.Msg.Timestamp == nil {
		req.Msg.Timestamp = timestamppb.Now()
	}
	h.store.RecordHeartbeat(req.Msg)
	return connect.NewResponse(&omegav1.HeartbeatAck{
		Acknowledged: true,
		ServerTime:   timestamppb.Now(),
	}), nil
}

// SendTrainingDiagnostics records rich training-loop diagnostics.
func (h *Handler) SendTrainingDiagnostics(
	ctx context.Context,
	req *connect.Request[omegav1.TrainingDiagnostics],
) (*connect.Response[omegav1.HeartbeatAck], error) {
	h.store.RecordDiagnostics(req.Msg)
	return connect.NewResponse(&omegav1.HeartbeatAck{
		Acknowledged: true,
		ServerTime:   timestamppb.Now(),
	}), nil
}

// GetNodeStatus returns the current status of a single node.
func (h *Handler) GetNodeStatus(
	ctx context.Context,
	req *connect.Request[omegav1.NodeStatusRequest],
) (*connect.Response[omegav1.NodeStatusResponse], error) {
	entry, ok := h.store.GetNode(req.Msg.GetNodeId())
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound,
			fmt.Errorf("node %q not registered", req.Msg.GetNodeId()))
	}
	return connect.NewResponse(entryToProto(entry)), nil
}

// ListNodes returns all known nodes with stale detection applied.
func (h *Handler) ListNodes(
	ctx context.Context,
	req *connect.Request[omegav1.ListHeartbeatNodesRequest],
) (*connect.Response[omegav1.ListHeartbeatNodesResponse], error) {
	entries := h.store.ListNodes()
	resp := &omegav1.ListHeartbeatNodesResponse{
		Nodes: make([]*omegav1.NodeStatusResponse, 0, len(entries)),
	}
	for _, e := range entries {
		resp.Nodes = append(resp.Nodes, entryToProto(e))
	}
	return connect.NewResponse(resp), nil
}

// GetDiagnostics returns the latest training diagnostics.
func (h *Handler) GetDiagnostics(
	ctx context.Context,
	req *connect.Request[omegav1.GetDiagnosticsRequest],
) (*connect.Response[omegav1.TrainingDiagnostics], error) {
	d := h.store.GetDiagnostics()
	if d == nil {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("no diagnostics available yet"))
	}
	return connect.NewResponse(d), nil
}

// entryToProto converts a NodeEntry snapshot to the proto response type.
func entryToProto(e *NodeEntry) *omegav1.NodeStatusResponse {
	stale := IsStale(e)
	health := e.Health
	if stale {
		health = omegav1.NodeHealth_NODE_HEALTH_STALE
	}

	var lastSeen *timestamppb.Timestamp
	if !e.LastSeen.IsZero() {
		lastSeen = timestamppb.New(e.LastSeen)
	}

	blockers := e.Blockers
	if blockers == nil {
		blockers = []string{}
	}

	return &omegav1.NodeStatusResponse{
		NodeId:   e.NodeID,
		NodeType: e.NodeType,
		Health:   health,
		LastSeen: lastSeen,
		Metrics:  e.Metrics,
		Blockers: blockers,
		Stale:    stale,
	}
}

// Store returns the underlying store (used by controlplane to share state).
func (h *Handler) Store() *Store { return h.store }
