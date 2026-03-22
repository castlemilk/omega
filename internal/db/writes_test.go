package db_test

import (
	"os"
	"testing"

	"github.com/benebsworth/omega/internal/db"
)

func newTestDB(t *testing.T) *db.DB {
	t.Helper()
	stateF, err := os.CreateTemp("", "omega-state-*.db")
	if err != nil {
		t.Fatal(err)
	}
	memF, err := os.CreateTemp("", "omega-memory-*.db")
	if err != nil {
		t.Fatal(err)
	}
	stateF.Close() //nolint:errcheck,gosec
	memF.Close()   //nolint:errcheck,gosec
	t.Cleanup(func() {
		os.Remove(stateF.Name()) //nolint:errcheck,gosec
		os.Remove(memF.Name())   //nolint:errcheck,gosec
	})
	d, err := db.New(stateF.Name(), memF.Name())
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
	// Update same node
	if err = d.UpsertNode("n1", "TestNode", "1.1", []string{"a"}, 0.8, "active", nil); err != nil {
		t.Fatalf("upsert update: %v", err)
	}
	nodes, err := d.AllNodes()
	if err != nil {
		t.Fatalf("all nodes: %v", err)
	}
	if len(nodes) != 1 {
		t.Fatalf("expected 1 node, got %d", len(nodes))
	}
	if nodes[0].Version != "1.1" {
		t.Errorf("expected version 1.1, got %s", nodes[0].Version)
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
	if len(execs) != 1 {
		t.Fatalf("expected 1 execution, got %d", len(execs))
	}
	if !execs[0].Success {
		t.Error("expected success=true")
	}
	if execs[0].DurationMS == nil || *execs[0].DurationMS < 0 {
		t.Error("expected non-negative duration")
	}
	if execs[0].Metrics["score"] != 0.9 {
		t.Errorf("expected score=0.9, got %v", execs[0].Metrics["score"])
	}
}

func TestBeginEndSpan(t *testing.T) {
	d := newTestDB(t)
	traceID := "trace-abc"
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
	if len(spans) != 1 {
		t.Fatalf("expected 1 span, got %d", len(spans))
	}
	if spans[0].Status != "ok" {
		t.Errorf("expected status ok, got %s", spans[0].Status)
	}
}

func TestBeginSpanWithParent(t *testing.T) {
	d := newTestDB(t)
	traceID := "trace-xyz"
	parentID, _ := d.BeginSpan(traceID, "n1", "TestNode", "root", nil, 1)
	childID, err := d.BeginSpan(traceID, "n1", "TestNode", "child", &parentID, 1)
	if err != nil {
		t.Fatalf("begin child span: %v", err)
	}
	d.EndSpan(parentID, "ok", nil) //nolint:errcheck,gosec
	d.EndSpan(childID, "ok", nil)  //nolint:errcheck,gosec
	spans, err := d.GetTraceSpans(traceID)
	if err != nil {
		t.Fatalf("get spans: %v", err)
	}
	if len(spans) != 2 {
		t.Fatalf("expected 2 spans, got %d", len(spans))
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
	if len(costs) != 1 {
		t.Fatalf("expected 1 cost entry, got %d", len(costs))
	}
	if costs[0].Provider != "anthropic" {
		t.Errorf("expected provider anthropic, got %s", costs[0].Provider)
	}
	if costs[0].TotalCostUSD != 0.002 {
		t.Errorf("expected cost 0.002, got %v", costs[0].TotalCostUSD)
	}
}

func TestOpenEscalateResolveIssue(t *testing.T) {
	d := newTestDB(t)
	created, err := d.OpenIssue("issue-1", "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("open issue: %v", err)
	}
	if !created {
		t.Error("expected created=true")
	}
	// Duplicate should NOT create a new row but escalate
	created2, err := d.OpenIssue("issue-1", "cleaner", "warning", "test issue", nil, 1)
	if err != nil {
		t.Fatalf("duplicate open issue: %v", err)
	}
	if created2 {
		t.Error("expected created=false for duplicate")
	}
	resolved, err := d.ResolveIssue("issue-1", 2)
	if err != nil {
		t.Fatalf("resolve issue: %v", err)
	}
	if !resolved {
		t.Error("expected resolved=true")
	}
	// Should not appear in open issues
	issues, err := d.GetIssues("open")
	if err != nil {
		t.Fatalf("get issues: %v", err)
	}
	for _, i := range issues {
		if i.IssueID == "issue-1" {
			t.Error("issue-1 should not be in open issues after resolution")
		}
	}
}

func TestLogActivity(t *testing.T) {
	d := newTestDB(t)
	if err := d.LogActivity("test_action", "node", "n1", map[string]any{"k": "v"}, 0); err != nil {
		t.Fatalf("log activity: %v", err)
	}
	entries, err := d.RecentActivity(10)
	if err != nil {
		t.Fatalf("recent activity: %v", err)
	}
	found := false
	for _, e := range entries {
		if e.ActionType == "test_action" {
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
	if len(imps) != 1 {
		t.Fatalf("expected 1 improvement, got %d", len(imps))
	}
	if imps[0].ToVersion != "1.1" {
		t.Errorf("expected to_version 1.1, got %s", imps[0].ToVersion)
	}
	if imps[0].AfterMetrics["score"] != 0.85 {
		t.Errorf("expected after score 0.85, got %v", imps[0].AfterMetrics["score"])
	}
	// Activity log should have a node_improved entry
	entries, _ := d.RecentActivity(10)
	found := false
	for _, e := range entries {
		if e.ActionType == "node_improved" {
			found = true
		}
	}
	if !found {
		t.Error("expected node_improved activity entry")
	}
}

func TestSaveConfigRevision(t *testing.T) {
	d := newTestDB(t)
	err := d.SaveConfigRevision("n1", "1.0", map[string]any{"model": "claude-sonnet-4-6"})
	if err != nil {
		t.Fatalf("save config revision: %v", err)
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
	// Verify row exists via direct count (RecentAlignmentDecisions reads different columns)
	var count int
	if err = d.StateDB().QueryRow(`SELECT COUNT(*) FROM alignment_decisions WHERE decision_id=?`, decisionID).Scan(&count); err != nil {
		t.Fatalf("count alignment decisions: %v", err)
	}
	if count != 1 {
		t.Errorf("expected 1 row, got %d", count)
	}
}

func TestRecordAdversarialResult(t *testing.T) {
	d := newTestDB(t)
	resultID, err := d.RecordAdversarialResult(
		7, 1, false, 0.12, 3,
		[]string{},
		map[string]any{"detail": "ok"},
	)
	if err != nil {
		t.Fatalf("record adversarial result: %v", err)
	}
	if resultID == "" {
		t.Fatal("expected non-empty resultID")
	}
	// Verify row via direct count (RecentAdversarialResults reads different column names)
	var ring int
	if err = d.StateDB().QueryRow(`SELECT ring FROM adversarial_results WHERE result_id=?`, resultID).Scan(&ring); err != nil {
		t.Fatalf("query adversarial result: %v", err)
	}
	if ring != 1 {
		t.Errorf("expected ring 1, got %d", ring)
	}
}

func TestRecordGoalTracking(t *testing.T) {
	d := newTestDB(t)
	trackingID, err := d.RecordGoalTracking(
		4, true, 0.82,
		map[string]any{"profit": 0.9},
		map[string]any{"profit": 0.5},
		0.01,
		map[string]any{"adjust": 0.02},
		[]string{"task1"},
		[]string{},
	)
	if err != nil {
		t.Fatalf("record goal tracking: %v", err)
	}
	if trackingID == "" {
		t.Fatal("expected non-empty trackingID")
	}
}
