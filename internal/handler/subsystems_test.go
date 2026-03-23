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

// setupSubsystemTestServer creates a test server backed by Postgres.
func setupSubsystemTestServer(t *testing.T) (omegav1connect.OrchestratorServiceClient, func()) {
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
	client := omegav1connect.NewOrchestratorServiceClient(http.DefaultClient, srv.URL)

	return client, func() {
		srv.Close()
		database.Close()
	}
}

func TestGetAlignmentDecisions_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetAlignmentDecisions(
		context.Background(),
		connect.NewRequest(&omegav1.GetAlignmentDecisionsRequest{Limit: 10}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// empty table → empty (or nil) slice, no error
	if len(resp.Msg.Decisions) != 0 {
		t.Errorf("expected 0 decisions, got %d", len(resp.Msg.Decisions))
	}
}

func TestGetAdversarialResults_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetAdversarialResults(
		context.Background(),
		connect.NewRequest(&omegav1.GetAdversarialResultsRequest{Limit: 10}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Msg.Results) != 0 {
		t.Errorf("expected 0 results, got %d", len(resp.Msg.Results))
	}
}

func TestGetGoalTracking_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetGoalTracking(
		context.Background(),
		connect.NewRequest(&omegav1.GetGoalTrackingRequest{}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// state should be nil when table is empty
	if resp.Msg.State != nil {
		t.Errorf("expected nil state when table empty, got %+v", resp.Msg.State)
	}
}

func TestGetChallenges_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetChallenges(
		context.Background(),
		connect.NewRequest(&omegav1.GetChallengesRequest{}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Msg.Challenges) != 0 {
		t.Errorf("expected 0 challenges, got %d", len(resp.Msg.Challenges))
	}
}

func TestGetMemoryStats_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetMemoryStats(
		context.Background(),
		connect.NewRequest(&omegav1.GetMemoryStatsRequest{}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Msg.Stats == nil {
		t.Error("expected non-nil stats")
	}
	if resp.Msg.Stats.EpisodicCount != 0 {
		t.Errorf("expected 0 episodic count, got %d", resp.Msg.Stats.EpisodicCount)
	}
}

func TestGetVerificationGates_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetVerificationGates(
		context.Background(),
		connect.NewRequest(&omegav1.GetVerificationGatesRequest{Limit: 10}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Msg.Gates) != 0 {
		t.Errorf("expected 0 gates, got %d", len(resp.Msg.Gates))
	}
}

func TestGetImprovementHistory_Empty(t *testing.T) {
	client, cleanup := setupSubsystemTestServer(t)
	defer cleanup()
	resp, err := client.GetImprovementHistory(
		context.Background(),
		connect.NewRequest(&omegav1.GetImprovementHistoryRequest{Limit: 20}),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(resp.Msg.Records) != 0 {
		t.Errorf("expected 0 records, got %d", len(resp.Msg.Records))
	}
}
