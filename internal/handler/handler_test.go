package handler_test

import (
	"context"
	"database/sql"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"connectrpc.com/connect"
	_ "modernc.org/sqlite"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

// bootstrapStateSchema creates the tables the Python layer would normally create.
func bootstrapStateSchema(t *testing.T, path string) {
	t.Helper()
	sqlDB, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open state db for bootstrap: %v", err)
	}
	defer sqlDB.Close() //nolint:errcheck
	_, err = sqlDB.Exec(`
		CREATE TABLE IF NOT EXISTS nodes (
			node_id           TEXT PRIMARY KEY,
			name              TEXT NOT NULL DEFAULT '',
			version           TEXT NOT NULL DEFAULT '',
			capabilities_json TEXT NOT NULL DEFAULT '[]',
			health            REAL NOT NULL DEFAULT 1.0,
			status            TEXT NOT NULL DEFAULT 'idle',
			registered_at     REAL NOT NULL DEFAULT 0,
			last_updated      REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS node_executions (
			exec_id      TEXT PRIMARY KEY,
			node_id      TEXT NOT NULL,
			node_name    TEXT NOT NULL DEFAULT '',
			trace_id     TEXT,
			span_id      TEXT,
			action       TEXT NOT NULL DEFAULT '',
			started_at   REAL NOT NULL DEFAULT 0,
			ended_at     REAL,
			duration_ms  REAL,
			success      INTEGER NOT NULL DEFAULT 1,
			error_text   TEXT,
			metrics_json TEXT,
			cycle        INTEGER NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS traces (
			span_id        TEXT PRIMARY KEY,
			trace_id       TEXT NOT NULL,
			parent_span_id TEXT,
			node_id        TEXT,
			node_name      TEXT,
			operation      TEXT NOT NULL DEFAULT '',
			started_at     REAL NOT NULL DEFAULT 0,
			ended_at       REAL,
			duration_ms    REAL,
			status         TEXT NOT NULL DEFAULT 'ok',
			cycle          INTEGER NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS issues (
			issue_id       TEXT PRIMARY KEY,
			detector       TEXT NOT NULL DEFAULT '',
			severity       TEXT NOT NULL DEFAULT 'warning',
			description    TEXT NOT NULL DEFAULT '',
			state          TEXT NOT NULL DEFAULT 'open',
			opened_at      REAL NOT NULL DEFAULT 0,
			resolved_at    REAL,
			cycle_opened   INTEGER NOT NULL DEFAULT 0,
			cycle_resolved INTEGER
		);
		CREATE TABLE IF NOT EXISTS activity_log (
			log_id      TEXT PRIMARY KEY,
			action_type TEXT NOT NULL DEFAULT '',
			entity_type TEXT NOT NULL DEFAULT '',
			entity_id   TEXT NOT NULL DEFAULT '',
			recorded_at REAL NOT NULL DEFAULT 0,
			cycle       INTEGER NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS improvement_log (
			improve_id          TEXT PRIMARY KEY,
			node_id             TEXT NOT NULL,
			node_name           TEXT NOT NULL DEFAULT '',
			from_version        TEXT NOT NULL DEFAULT '',
			to_version          TEXT NOT NULL DEFAULT '',
			triggered_by        TEXT NOT NULL DEFAULT '',
			recorded_at         REAL NOT NULL DEFAULT 0,
			cycle               INTEGER NOT NULL DEFAULT 0,
			before_metrics_json TEXT,
			after_metrics_json  TEXT
		);
		CREATE TABLE IF NOT EXISTS cost_events (
			event_id           TEXT PRIMARY KEY,
			provider           TEXT NOT NULL DEFAULT '',
			node_id            TEXT NOT NULL DEFAULT '',
			duration_ms        REAL NOT NULL DEFAULT 0,
			estimated_cost_usd REAL NOT NULL DEFAULT 0
		);
	`)
	if err != nil {
		t.Fatalf("bootstrap state schema: %v", err)
	}
}

func setupTestServer(t *testing.T) (omegav1connect.OrchestratorServiceClient, func()) {
	t.Helper()
	dir := t.TempDir()
	stateDB := filepath.Join(dir, "state.db")
	memDB := filepath.Join(dir, "memory.db")

	bootstrapStateSchema(t, stateDB)

	// Touch the memory DB file.
	f, _ := os.Create(memDB)
	f.Close() //nolint:errcheck

	database, err := db.New(stateDB, memDB)
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
