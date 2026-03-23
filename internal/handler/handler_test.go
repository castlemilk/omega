package handler_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

func setupTestServer(t *testing.T) (omegav1connect.OrchestratorServiceClient, func()) {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)

	database, err := db.New(context.Background())
	if err != nil {
		t.Fatalf("db.New: %v", err)
	}

	h := handler.New(database)
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewOrchestratorServiceHandler(h)
	mux.Handle(path, svc)

	srv := httptest.NewServer(mux)
	client := omegav1connect.NewOrchestratorServiceClient(
		http.DefaultClient,
		srv.URL,
	)

	return client, func() {
		srv.Close()
		database.Close()
	}
}

func TestGetHealth_EmptyDB(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.GetHealth(context.Background(), connect.NewRequest(&omegav1.GetHealthRequest{}))
	if err != nil {
		t.Fatalf("GetHealth: %v", err)
	}
	if resp.Msg.Health == nil {
		t.Fatal("expected non-nil health")
	}
	if resp.Msg.Health.Status != "no_nodes" {
		t.Errorf("want no_nodes, got %q", resp.Msg.Health.Status)
	}
}

func TestListNodes_Empty(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.ListNodes(context.Background(), connect.NewRequest(&omegav1.ListNodesRequest{}))
	if err != nil {
		t.Fatalf("ListNodes: %v", err)
	}
	if len(resp.Msg.Nodes) != 0 {
		t.Errorf("want 0 nodes, got %d", len(resp.Msg.Nodes))
	}
}

func TestListTraces_Empty(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.ListTraces(context.Background(), connect.NewRequest(&omegav1.ListTracesRequest{Limit: 10}))
	if err != nil {
		t.Fatalf("ListTraces: %v", err)
	}
	if len(resp.Msg.Traces) != 0 {
		t.Errorf("want 0 traces, got %d", len(resp.Msg.Traces))
	}
}

func TestListIssues_Empty(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.ListIssues(context.Background(), connect.NewRequest(&omegav1.ListIssuesRequest{StateFilter: "open"}))
	if err != nil {
		t.Fatalf("ListIssues: %v", err)
	}
	if len(resp.Msg.Issues) != 0 {
		t.Errorf("want 0 issues, got %d", len(resp.Msg.Issues))
	}
}

func TestListAvailableProviders(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.ListAvailableProviders(context.Background(), connect.NewRequest(&omegav1.ListAvailableProvidersRequest{}))
	if err != nil {
		t.Fatalf("ListAvailableProviders: %v", err)
	}
	if len(resp.Msg.Providers) == 0 {
		t.Fatal("expected at least one provider")
	}
	// Verify anthropic is present
	var foundAnthropic bool
	for _, p := range resp.Msg.Providers {
		if p.Id == "anthropic" {
			foundAnthropic = true
			break
		}
	}
	if !foundAnthropic {
		t.Error("expected anthropic provider")
	}
}

func TestGetNodeConfig_NotFound(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	_, err := client.GetNodeConfig(context.Background(), connect.NewRequest(&omegav1.GetNodeConfigRequest{NodeId: "nonexistent"}))
	if err == nil {
		t.Fatal("expected error for nonexistent node")
	}
	var connectErr *connect.Error
	if !connect.IsWireError(err) {
		_ = connectErr
	}
}

func TestGetMetrics_Empty(t *testing.T) {
	client, cleanup := setupTestServer(t)
	defer cleanup()

	resp, err := client.GetMetrics(context.Background(), connect.NewRequest(&omegav1.GetMetricsRequest{}))
	if err != nil {
		t.Fatalf("GetMetrics: %v", err)
	}
	if resp.Msg.System == nil {
		t.Fatal("expected non-nil system health in metrics")
	}
}
