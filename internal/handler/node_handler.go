// Package handler — NodeHandler implements NodeService for the Omega API.
//
// NodeHandler is the Connect-RPC server-side handler for NodeService. It uses a
// NodeRegistry as its source of truth for registered nodes.
//
// Routing convention
//
// Every inbound RPC must identify the target node.  The handler looks for the
// node ID in this priority order:
//  1. The "x-omega-node-id" HTTP/2 header (works for all five RPCs).
//  2. The "node_id" key in ExecuteRequest.Context (Execute only).
//  3. Capability-based routing: selects the first healthy node that advertises
//     the action string as a capability (Execute only, fallback).
//
// Execute, Evaluate, and Improve are forwarded to the node's Connect-RPC
// address stored in the registry.  GetState and GetCapabilities are served
// directly from the registry without a round-trip to the node.
package handler

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/registry"
)

// nodeIDHeader is the Connect/HTTP-2 header used to identify the target node.
const nodeIDHeader = "x-omega-node-id"

// Ensure interface satisfaction at compile time.
var _ omegav1connect.NodeServiceHandler = (*NodeHandler)(nil)

// NodeHandler implements NodeService.
type NodeHandler struct {
	reg *registry.NodeRegistry
}

// NewNodeHandler creates a NodeHandler backed by the given registry.
func NewNodeHandler(reg *registry.NodeRegistry) *NodeHandler {
	return &NodeHandler{reg: reg}
}

// ── Execute ───────────────────────────────────────────────────────────────────

// Execute routes an execution request to a registered node.
// The target node is resolved via (in order):
//  1. x-omega-node-id header
//  2. context["node_id"] field
//  3. first healthy node that advertises req.Action as a capability
func (h *NodeHandler) Execute(
	ctx context.Context,
	req *connect.Request[omegav1.ExecuteRequest],
) (*connect.Response[omegav1.ExecuteResponse], error) {
	entry, err := h.resolveNode(req.Header(), req.Msg.GetContext(), req.Msg.GetAction())
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	client := omegav1connect.NewNodeServiceClient(
		http.DefaultClient,
		entry.Address,
	)

	// Forward with the node-id header so the node knows who it is.
	fwd := connect.NewRequest(req.Msg)
	fwd.Header().Set(nodeIDHeader, entry.ID)

	resp, err := client.Execute(ctx, fwd)
	if err != nil {
		return nil, translateErr(err)
	}
	return connect.NewResponse(resp.Msg), nil
}

// ── Evaluate ──────────────────────────────────────────────────────────────────

func (h *NodeHandler) Evaluate(
	ctx context.Context,
	req *connect.Request[omegav1.EvaluateRequest],
) (*connect.Response[omegav1.EvaluateResponse], error) {
	entry, err := h.resolveNode(req.Header(), nil, "")
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	client := omegav1connect.NewNodeServiceClient(http.DefaultClient, entry.Address)
	fwd := connect.NewRequest(req.Msg)
	fwd.Header().Set(nodeIDHeader, entry.ID)

	resp, err := client.Evaluate(ctx, fwd)
	if err != nil {
		return nil, translateErr(err)
	}
	return connect.NewResponse(resp.Msg), nil
}

// ── Improve ───────────────────────────────────────────────────────────────────

func (h *NodeHandler) Improve(
	ctx context.Context,
	req *connect.Request[omegav1.ImproveRequest],
) (*connect.Response[omegav1.ImproveResponse], error) {
	entry, err := h.resolveNode(req.Header(), nil, "")
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	client := omegav1connect.NewNodeServiceClient(http.DefaultClient, entry.Address)
	fwd := connect.NewRequest(req.Msg)
	fwd.Header().Set(nodeIDHeader, entry.ID)

	resp, err := client.Improve(ctx, fwd)
	if err != nil {
		return nil, translateErr(err)
	}
	return connect.NewResponse(resp.Msg), nil
}

// ── GetState ──────────────────────────────────────────────────────────────────

// GetState serves node state directly from the registry — no round-trip to node.
func (h *NodeHandler) GetState(
	ctx context.Context,
	req *connect.Request[omegav1.GetStateRequest],
) (*connect.Response[omegav1.GetStateResponse], error) {
	entry, err := h.resolveNode(req.Header(), nil, "")
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	return connect.NewResponse(&omegav1.GetStateResponse{
		NodeId:       entry.ID,
		Name:         entry.Name,
		Version:      entry.Version,
		Health:       entry.Health,
		Status:       string(entry.State),
		Capabilities: entry.Capabilities,
	}), nil
}

// ── GetCapabilities ───────────────────────────────────────────────────────────

// GetCapabilities serves capabilities directly from the registry.
func (h *NodeHandler) GetCapabilities(
	ctx context.Context,
	req *connect.Request[omegav1.GetCapabilitiesRequest],
) (*connect.Response[omegav1.GetCapabilitiesResponse], error) {
	entry, err := h.resolveNode(req.Header(), nil, "")
	if err != nil {
		return nil, connect.NewError(connect.CodeNotFound, err)
	}

	return connect.NewResponse(&omegav1.GetCapabilitiesResponse{
		Capabilities: entry.Capabilities,
	}), nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

// resolveNode identifies the target node for an inbound RPC.
// Priority: x-omega-node-id header → contextMap["node_id"] → capability routing.
func (h *NodeHandler) resolveNode(
	header http.Header,
	contextMap map[string]string,
	action string,
) (registry.NodeEntry, error) {
	// 1. Explicit node ID header.
	if id := header.Get(nodeIDHeader); id != "" {
		entry, ok := h.reg.Get(id)
		if !ok {
			return registry.NodeEntry{}, fmt.Errorf("node %q not registered", id)
		}
		return entry, nil
	}

	// 2. node_id key in the context map (Execute only).
	if id := contextMap["node_id"]; id != "" {
		entry, ok := h.reg.Get(id)
		if !ok {
			return registry.NodeEntry{}, fmt.Errorf("node %q not registered", id)
		}
		return entry, nil
	}

	// 3. Capability-based routing: pick first healthy node that handles action.
	if action != "" {
		candidates := h.reg.FindByCapability(action, true)
		if len(candidates) > 0 {
			return candidates[0], nil
		}
		return registry.NodeEntry{}, fmt.Errorf("no healthy node with capability %q", action)
	}

	return registry.NodeEntry{}, errors.New(
		"node ID required: set x-omega-node-id header or context[\"node_id\"]",
	)
}

// translateErr wraps a Connect error from a downstream node call so the caller
// sees a consistent error code.
func translateErr(err error) error {
	var connectErr *connect.Error
	if errors.As(err, &connectErr) {
		return connectErr
	}
	return connect.NewError(connect.CodeInternal, err)
}
