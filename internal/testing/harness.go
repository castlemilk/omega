// Package omegatest provides an in-process integration test harness for Omega services.
// It spins up Connect-RPC handlers backed by a real Postgres database so that
// integration tests can exercise the full request path without mocking the DB layer.
// Tests are skipped when TEST_DATABASE_URL is not set.
package omegatest

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

// ---------------------------------------------------------------------------
// TestHarness
// ---------------------------------------------------------------------------

// TestHarness spins up all Omega services in-process, backed by a real Postgres
// database. Callers receive typed Connect clients pointing at the test server.
// All resources are released when Cleanup is called (or automatically via
// t.Cleanup when created with New). Tests are skipped if TEST_DATABASE_URL is unset.
type TestHarness struct {
	t      testing.TB
	db     *db.DB
	server *httptest.Server

	// Typed clients — ready to use immediately after New returns.
	Orchestrator omegav1connect.OrchestratorServiceClient
	State        omegav1connect.StateServiceClient
}

// New creates a TestHarness attached to t. The harness is automatically torn
// down when the test finishes via t.Cleanup.
func New(t testing.TB) *TestHarness {
	t.Helper()

	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)

	database, err := db.New(context.Background())
	if err != nil {
		t.Fatalf("omegatest.New: open db: %v", err)
	}

	mux := http.NewServeMux()

	orchHandler := handler.New(database)
	orchPath, orchSvc := omegav1connect.NewOrchestratorServiceHandler(orchHandler)
	mux.Handle(orchPath, orchSvc)

	stateHandler := handler.NewState(database)
	statePath, stateSvc := omegav1connect.NewStateServiceHandler(stateHandler)
	mux.Handle(statePath, stateSvc)

	srv := httptest.NewServer(mux)

	h := &TestHarness{
		t:      t,
		db:     database,
		server: srv,
		Orchestrator: omegav1connect.NewOrchestratorServiceClient(
			http.DefaultClient,
			srv.URL,
		),
		State: omegav1connect.NewStateServiceClient(
			http.DefaultClient,
			srv.URL,
		),
	}

	t.Cleanup(h.Cleanup)
	return h
}

// Cleanup releases the test server and database connections.
// It is called automatically via t.Cleanup; callers only need to invoke it when
// they want explicit control over teardown order.
func (h *TestHarness) Cleanup() {
	h.server.Close()
	h.db.Close()
}

// BaseURL returns the base URL of the test HTTP server.
func (h *TestHarness) BaseURL() string {
	return h.server.URL
}

// ---------------------------------------------------------------------------
// Helper: CreateNode
// ---------------------------------------------------------------------------

// NodeOpt is a functional option for CreateNode.
type NodeOpt func(*omegav1.UpsertNodeRequest)

// WithNodeVersion sets the node version.
func WithNodeVersion(version string) NodeOpt {
	return func(r *omegav1.UpsertNodeRequest) { r.Version = version }
}

// WithNodeHealth sets the initial health score (0.0–1.0).
func WithNodeHealth(health float64) NodeOpt {
	return func(r *omegav1.UpsertNodeRequest) { r.Health = health }
}

// WithNodeCapabilities sets the node capabilities.
func WithNodeCapabilities(caps ...string) NodeOpt {
	return func(r *omegav1.UpsertNodeRequest) { r.Capabilities = caps }
}

// WithNodeStatus sets the node status string.
func WithNodeStatus(status string) NodeOpt {
	return func(r *omegav1.UpsertNodeRequest) { r.Status = status }
}

// CreateNode registers a node via the StateService and returns its node ID.
// The node is created with sensible defaults; opts can override individual fields.
func (h *TestHarness) CreateNode(nodeID, name string, opts ...NodeOpt) string {
	h.t.Helper()
	req := &omegav1.UpsertNodeRequest{
		NodeId:       nodeID,
		Name:         name,
		Version:      "1.0",
		Capabilities: []string{"inference"},
		Health:       1.0,
		Status:       "active",
	}
	for _, o := range opts {
		o(req)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err := h.State.UpsertNode(ctx, connect.NewRequest(req))
	if err != nil {
		h.t.Fatalf("CreateNode(%s): %v", nodeID, err)
	}
	return nodeID
}

// ---------------------------------------------------------------------------
// Helper: RunCycle
// ---------------------------------------------------------------------------

// CycleResult summarises the outcome of a harness-driven test cycle.
type CycleResult struct {
	NodeID  string
	ExecID  string
	Success bool
	Cycle   int64
}

// RunCycle simulates a single orchestration cycle for the given node:
// it begins an execution, optionally sleeps to create non-zero duration, then
// ends it. Returns a CycleResult for assertion.
func (h *TestHarness) RunCycle(nodeID, nodeName string, cycle int64, success bool) CycleResult {
	h.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Begin execution.
	beginResp, err := h.State.BeginExecution(ctx, connect.NewRequest(&omegav1.BeginExecutionRequest{
		NodeId:   nodeID,
		NodeName: nodeName,
		Action:   "cycle",
		TraceId:  fmt.Sprintf("trace-%s-%d", nodeID, cycle),
		Cycle:    cycle,
	}))
	if err != nil {
		h.t.Fatalf("RunCycle(%s): BeginExecution: %v", nodeID, err)
	}
	execID := beginResp.Msg.ExecId

	// End execution.
	errText := ""
	if !success {
		errText = "simulated failure"
	}
	_, err = h.State.EndExecution(ctx, connect.NewRequest(&omegav1.EndExecutionRequest{
		ExecId:    execID,
		Success:   success,
		ErrorText: errText,
	}))
	if err != nil {
		h.t.Fatalf("RunCycle(%s): EndExecution: %v", nodeID, err)
	}

	return CycleResult{
		NodeID:  nodeID,
		ExecID:  execID,
		Success: success,
		Cycle:   cycle,
	}
}

// ---------------------------------------------------------------------------
// Helper: AssertAutonomyLevel
// ---------------------------------------------------------------------------

// AssertAutonomyLevel asserts that the node's health score (used as autonomy proxy)
// meets or exceeds minHealth. It fetches the node from OrchestratorService and
// fails the test if health < minHealth.
func (h *TestHarness) AssertAutonomyLevel(nodeID string, minHealth float64) {
	h.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.Orchestrator.GetNode(ctx, connect.NewRequest(&omegav1.GetNodeRequest{
		NodeId: nodeID,
	}))
	if err != nil {
		h.t.Fatalf("AssertAutonomyLevel(%s): GetNode: %v", nodeID, err)
	}
	if resp.Msg.Node == nil {
		h.t.Fatalf("AssertAutonomyLevel(%s): node not found", nodeID)
	}
	health := resp.Msg.Node.Health
	if health < minHealth {
		h.t.Errorf("AssertAutonomyLevel(%s): health %.4f < required %.4f", nodeID, health, minHealth)
	}
}

// ---------------------------------------------------------------------------
// Helper: AssertNodeExists
// ---------------------------------------------------------------------------

// AssertNodeExists fails the test if the node cannot be retrieved.
func (h *TestHarness) AssertNodeExists(nodeID string) {
	h.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := h.Orchestrator.GetNode(ctx, connect.NewRequest(&omegav1.GetNodeRequest{
		NodeId: nodeID,
	}))
	if err != nil {
		h.t.Fatalf("AssertNodeExists(%s): %v", nodeID, err)
	}
	if resp.Msg.Node == nil {
		h.t.Fatalf("AssertNodeExists(%s): node is nil", nodeID)
	}
}

