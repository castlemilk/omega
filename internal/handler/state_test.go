package handler_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"connectrpc.com/connect"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

func setupStateServer(t *testing.T) (omegav1connect.StateServiceClient, *db.DB) {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)

	database, err := db.New(context.Background())
	if err != nil {
		t.Fatalf("new db: %v", err)
	}
	t.Cleanup(database.Close)

	mux := http.NewServeMux()
	path, svcHandler := omegav1connect.NewStateServiceHandler(handler.NewState(database))
	mux.Handle(path, svcHandler)

	srv := httptest.NewUnstartedServer(h2c.NewHandler(mux, &http2.Server{}))
	srv.Start()
	t.Cleanup(srv.Close)

	client := omegav1connect.NewStateServiceClient(http.DefaultClient, srv.URL)
	return client, database
}

func TestStateHandler_UpsertNodeAndBeginExecution(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	_, err := client.UpsertNode(ctx, connect.NewRequest(&omegav1.UpsertNodeRequest{
		NodeId:       "n1",
		Name:         "TestNode",
		Version:      "1.0",
		Capabilities: []string{"run"},
		Health:       0.95,
		Status:       "active",
	}))
	if err != nil {
		t.Fatalf("UpsertNode: %v", err)
	}

	execResp, err := client.BeginExecution(ctx, connect.NewRequest(&omegav1.BeginExecutionRequest{
		NodeId:   "n1",
		NodeName: "TestNode",
		Action:   "run",
		Cycle:    1,
	}))
	if err != nil {
		t.Fatalf("BeginExecution: %v", err)
	}
	execID := execResp.Msg.ExecId
	if execID == "" {
		t.Fatal("expected non-empty execID")
	}

	_, err = client.EndExecution(ctx, connect.NewRequest(&omegav1.EndExecutionRequest{
		ExecId:  execID,
		Success: true,
		Metrics: map[string]float64{"score": 0.9},
	}))
	if err != nil {
		t.Fatalf("EndExecution: %v", err)
	}
}

func TestStateHandler_SpanLifecycle(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	spanResp, err := client.BeginSpan(ctx, connect.NewRequest(&omegav1.BeginSpanRequest{
		TraceId:   "trace-1",
		NodeId:    "n1",
		NodeName:  "TestNode",
		Operation: "execute",
		Cycle:     2,
	}))
	if err != nil {
		t.Fatalf("BeginSpan: %v", err)
	}
	if spanResp.Msg.SpanId == "" {
		t.Fatal("expected non-empty spanId")
	}

	_, err = client.EndSpan(ctx, connect.NewRequest(&omegav1.EndSpanRequest{
		SpanId: spanResp.Msg.SpanId,
		Status: "ok",
	}))
	if err != nil {
		t.Fatalf("EndSpan: %v", err)
	}
}

func TestStateHandler_RecordCost(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	_, err := client.RecordCost(ctx, connect.NewRequest(&omegav1.RecordCostRequest{
		NodeId:           "n1",
		Provider:         "anthropic",
		CallType:         "llm_call",
		DurationMs:       150.0,
		EstimatedCostUsd: 0.002,
		Cycle:            3,
	}))
	if err != nil {
		t.Fatalf("RecordCost: %v", err)
	}
}

func TestStateHandler_IssueLifecycle(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	openResp, err := client.OpenIssue(ctx, connect.NewRequest(&omegav1.OpenIssueRequest{
		IssueId:     "issue-1",
		Detector:    "cleaner",
		Severity:    "warning",
		Description: "test issue",
		Cycle:       1,
	}))
	if err != nil {
		t.Fatalf("OpenIssue: %v", err)
	}
	if !openResp.Msg.Created {
		t.Error("expected created=true")
	}

	resolveResp, err := client.ResolveIssue(ctx, connect.NewRequest(&omegav1.ResolveIssueRequest{
		IssueId: "issue-1",
		Cycle:   2,
	}))
	if err != nil {
		t.Fatalf("ResolveIssue: %v", err)
	}
	if !resolveResp.Msg.Resolved {
		t.Error("expected resolved=true")
	}
}

func TestStateHandler_LogActivity(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	_, err := client.LogActivity(ctx, connect.NewRequest(&omegav1.LogActivityRequest{
		ActionType: "test_action",
		EntityType: "node",
		EntityId:   "n1",
		Cycle:      0,
	}))
	if err != nil {
		t.Fatalf("LogActivity: %v", err)
	}
}

func TestStateHandler_RecordImprovement(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	_, err := client.RecordImprovement(ctx, connect.NewRequest(&omegav1.RecordImprovementRequest{
		NodeId:        "n1",
		NodeName:      "TestNode",
		FromVersion:   "1.0",
		ToVersion:     "1.1",
		BeforeMetrics: map[string]float64{"score": 0.7},
		AfterMetrics:  map[string]float64{"score": 0.85},
		TriggeredBy:   "metrics",
		Cycle:         5,
	}))
	if err != nil {
		t.Fatalf("RecordImprovement: %v", err)
	}
}

func TestStateHandler_BrainExecution(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordBrainExecution(ctx, connect.NewRequest(&omegav1.RecordBrainExecutionRequest{
		NodeId:        "n1",
		NodeName:      "TestNode",
		Provider:      "anthropic",
		Model:         "claude-sonnet-4-6",
		Operation:     "decide",
		ActionDecided: "execute",
		Reasoning:     "looks good",
		Confidence:    0.85,
		Outcome:       "applied",
		LatencyMs:     120.0,
		Cycle:         3,
	}))
	if err != nil {
		t.Fatalf("RecordBrainExecution: %v", err)
	}
	if resp.Msg.BrainExecId == "" {
		t.Fatal("expected non-empty brainExecId")
	}

	_, err = client.UpdateBrainOutcome(ctx, connect.NewRequest(&omegav1.UpdateBrainOutcomeRequest{
		BrainExecId: resp.Msg.BrainExecId,
		Outcome:     "applied",
	}))
	if err != nil {
		t.Fatalf("UpdateBrainOutcome: %v", err)
	}
}

func TestStateHandler_AlignmentDecision(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordAlignmentDecision(ctx, connect.NewRequest(&omegav1.RecordAlignmentDecisionRequest{
		Cycle:    5,
		Approved: true,
	}))
	if err != nil {
		t.Fatalf("RecordAlignmentDecision: %v", err)
	}
	if resp.Msg.DecisionId == "" {
		t.Fatal("expected non-empty decisionId")
	}
}

func TestStateHandler_AdversarialResult(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordAdversarialResult(ctx, connect.NewRequest(&omegav1.RecordAdversarialResultRequest{
		Cycle:         3,
		Ring:          1,
		Flagged:       false,
		ScenarioCount: 5,
	}))
	if err != nil {
		t.Fatalf("RecordAdversarialResult: %v", err)
	}
	if resp.Msg.ResultId == "" {
		t.Fatal("expected non-empty resultId")
	}
}

func TestStateHandler_GoalTracking(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	resp, err := client.RecordGoalTracking(ctx, connect.NewRequest(&omegav1.RecordGoalTrackingRequest{
		Cycle:          7,
		Approved:       true,
		CompositeScore: 0.8,
	}))
	if err != nil {
		t.Fatalf("RecordGoalTracking: %v", err)
	}
	if resp.Msg.TrackingId == "" {
		t.Fatal("expected non-empty trackingId")
	}
}

func TestStateHandler_SaveConfigRevision(t *testing.T) {
	client, _ := setupStateServer(t)
	ctx := context.Background()

	_, err := client.SaveConfigRevision(ctx, connect.NewRequest(&omegav1.SaveConfigRevisionRequest{
		NodeId:  "n1",
		Version: "1.0",
		Config:  map[string]string{"model": `"claude-sonnet-4-6"`},
	}))
	if err != nil {
		t.Fatalf("SaveConfigRevision: %v", err)
	}
}
