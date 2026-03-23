package db_test

import (
	"context"
	"os"
	"testing"

	"github.com/benebsworth/omega/internal/db"
)

func newTestDB(t *testing.T) *db.DB {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)
	ctx := context.Background()
	d, err := db.New(ctx)
	if err != nil {
		t.Fatalf("new db: %v", err)
	}
	t.Cleanup(d.Close)
	return d
}

func TestUpsertNode(t *testing.T) {
	d := newTestDB(t)
	err := d.UpsertNode("n1", "TestNode", "1.0", []string{"a", "b"}, 0.9, "active", map[string]any{"provider": "none"})
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}
	if err = d.UpsertNode("n1", "TestNode", "1.1", []string{"a"}, 0.8, "active", nil); err != nil {
		t.Fatalf("upsert update: %v", err)
	}
	nodes, err := d.AllNodes()
	if err != nil {
		t.Fatalf("all nodes: %v", err)
	}
	found := false
	for _, n := range nodes {
		if n.NodeID == "n1" && n.Version == "1.1" {
			found = true
		}
	}
	if !found {
		t.Error("expected node n1 with version 1.1")
	}
}

func TestBeginEndExecution(t *testing.T) {
	d := newTestDB(t)
	d.UpsertNode("n1", "TestNode", "1.0", nil, 1.0, "active", nil) //nolint:errcheck,gosec

	execID, err := d.BeginExecution("n1", "TestNode", "run", nil, nil, 1)
	if err != nil {
		t.Fatalf("begin execution: %v", err)
	}
	if execID == "" {
		t.Fatal("expected non-empty execID")
	}
	if err = d.EndExecution(execID, true, "", 0, "", false, map[string]float64{"score": 0.9}); err != nil {
		t.Fatalf("end execution: %v", err)
	}
	execs, err := d.GetExecutions("n1", 10)
	if err != nil {
		t.Fatalf("get executions: %v", err)
	}
	if len(execs) == 0 {
		t.Fatal("expected at least 1 execution")
	}
	found := false
	for _, e := range execs {
		if e.ExecID == execID {
			found = true
			if !e.Success {
				t.Error("expected success=true")
			}
			if e.DurationMS == nil || *e.DurationMS < 0 {
				t.Error("expected non-negative duration")
			}
			if e.Metrics["score"] != 0.9 {
				t.Errorf("expected score=0.9, got %v", e.Metrics["score"])
			}
		}
	}
	if !found {
		t.Errorf("execution %s not found", execID)
	}
}

func TestBeginEndSpan(t *testing.T) {
	d := newTestDB(t)
	traceID := "trace-abc-" + t.Name()
	spanID, err := d.BeginSpan(traceID, "n1", "TestNode", "execute", nil, 2)
	if err != nil {
		t.Fatalf("begin span: %v", err)
	}
	if spanID == "" {
		t.Fatal("expected non-empty spanID")
	}
	if err = d.EndSpan(spanID, "ok", map[string]any{"key": "val"}); err != nil {
		t.Fatalf("end span: %v", err)
	}
	spans, err := d.GetTraceSpans(traceID)
	if err != nil {
		t.Fatalf("get spans: %v", err)
	}
	if len(spans) == 0 {
		t.Fatal("expected at least 1 span")
	}
	if spans[0].Status != "ok" {
		t.Errorf("expected status ok, got %s", spans[0].Status)
	}
}

func TestRecordCost(t *testing.T) {
	d := newTestDB(t)
	if err := d.RecordCost("n1", "anthropic", "llm_call", 150.0, nil, 0.002, nil, 3); err != nil {
		t.Fatalf("record cost: %v", err)
	}
	costs, err := d.GetCosts()
	if err != nil {
		t.Fatalf("get costs: %v", err)
	}
	found := false
	for _, c := range costs {
		if c.Provider == "anthropic" && c.NodeID == "n1" {
			found = true
		}
	}
	if !found {
		t.Error("expected anthropic/n1 cost entry")
	}
}

func TestOpenResolveIssue(t *testing.T) {
	d := newTestDB(t)
	issueID := "issue-test-" + t.Name()
	created, err := d.OpenIssue(issueID, "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("open issue: %v", err)
	}
	if !created {
		t.Error("expected created=true")
	}
	created2, err := d.OpenIssue(issueID, "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("duplicate open issue: %v", err)
	}
	if created2 {
		t.Error("expected created=false for duplicate")
	}
	resolved, err := d.ResolveIssue(issueID, 2)
	if err != nil {
		t.Fatalf("resolve issue: %v", err)
	}
	if !resolved {
		t.Error("expected resolved=true")
	}
}

func TestLogActivity(t *testing.T) {
	d := newTestDB(t)
	if err := d.LogActivity("test_action_"+t.Name(), "node", "n1", map[string]any{"k": "v"}, 0); err != nil {
		t.Fatalf("log activity: %v", err)
	}
	entries, err := d.RecentActivity(50)
	if err != nil {
		t.Fatalf("recent activity: %v", err)
	}
	found := false
	for _, e := range entries {
		if e.ActionType == "test_action_"+t.Name() {
			found = true
		}
	}
	if !found {
		t.Error("expected test_action in activity log")
	}
}

func TestRecordImprovement(t *testing.T) {
	d := newTestDB(t)
	err := d.RecordImprovement("n1", "TestNode", "1.0", "1.1",
		map[string]float64{"score": 0.7},
		map[string]float64{"score": 0.85},
		"metrics", 5)
	if err != nil {
		t.Fatalf("record improvement: %v", err)
	}
	imps, err := d.GetImprovements("n1", 10)
	if err != nil {
		t.Fatalf("get improvements: %v", err)
	}
	if len(imps) == 0 {
		t.Fatal("expected at least 1 improvement")
	}
}

func TestRecordBrainExecution(t *testing.T) {
	d := newTestDB(t)
	brainExecID, err := d.RecordBrainExecution(
		"n1", "TestNode", "anthropic", "claude-sonnet-4-6",
		"decide", "execute",
		map[string]any{"param": 1},
		"reasoning text", 0.85, "applied", 120.0, "trace-1", 3,
	)
	if err != nil {
		t.Fatalf("record brain execution: %v", err)
	}
	if brainExecID == "" {
		t.Fatal("expected non-empty brainExecID")
	}
	if err = d.UpdateBrainOutcome(brainExecID, "applied"); err != nil {
		t.Fatalf("update brain outcome: %v", err)
	}
}

func TestRecordAlignmentDecision(t *testing.T) {
	d := newTestDB(t)
	decisionID, err := d.RecordAlignmentDecision(
		10, true,
		[]string{},
		map[string]any{"node1": 1.0},
		map[string]any{},
		map[string]any{},
		false,
	)
	if err != nil {
		t.Fatalf("record alignment decision: %v", err)
	}
	if decisionID == "" {
		t.Fatal("expected non-empty decisionID")
	}
	var count int
	if err = d.StateDB().QueryRow(`SELECT COUNT(*) FROM alignment_decisions WHERE decision_id=$1`, decisionID).Scan(&count); err != nil {
		t.Fatalf("count alignment decisions: %v", err)
	}
	if count != 1 {
		t.Errorf("expected 1 row, got %d", count)
	}
}

func TestSaveTerminalSession(t *testing.T) {
	d := newTestDB(t)
	s := &db.TerminalSessionRecord{
		ID:            "sess-" + t.Name(),
		WorkDir:       "/tmp",
		AutonomyLevel: "pico",
		Status:        "active",
		CreatedAt:     1700000000.0,
	}
	if err := d.SaveTerminalSession(s); err != nil {
		t.Fatalf("save terminal session: %v", err)
	}
	got, err := d.GetTerminalSession(s.ID)
	if err != nil {
		t.Fatalf("get terminal session: %v", err)
	}
	if got == nil {
		t.Fatal("expected session, got nil")
	}
	if got.WorkDir != "/tmp" {
		t.Errorf("expected workdir /tmp, got %s", got.WorkDir)
	}
}
