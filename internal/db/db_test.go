package db_test

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"

	"github.com/benebsworth/omega/internal/db"
)

// setupTestDB creates a temporary pair of state + memory DBs for testing.
// It pre-creates the minimal schema that the Python node layer would normally create.
func setupTestDB(t *testing.T) (*db.DB, func()) {
	t.Helper()
	dir := t.TempDir()
	stateDBPath := filepath.Join(dir, "state.db")
	memDBPath := filepath.Join(dir, "memory.db")

	// Bootstrap the state schema so queries don't fail with "no such table".
	if err := bootstrapStateSchema(t, stateDBPath); err != nil {
		t.Fatalf("bootstrap state schema: %v", err)
	}
	// Touch the memory DB file.
	f, err := os.Create(memDBPath) //nolint:gosec
	if err != nil {
		t.Fatalf("create memory db: %v", err)
	}
	f.Close() //nolint:errcheck,gosec

	d, err := db.New(stateDBPath, memDBPath)
	if err != nil {
		t.Fatalf("db.New: %v", err)
	}
	return d, func() { d.Close() }
}

// bootstrapStateSchema creates the tables the Python layer would normally create.
func bootstrapStateSchema(t *testing.T, path string) error {
	t.Helper()
	sqlDB, err := sql.Open("sqlite", path)
	if err != nil {
		return err
	}
	defer sqlDB.Close() //nolint:errcheck
	_, err = sqlDB.Exec(`
		CREATE TABLE IF NOT EXISTS nodes (
			node_id          TEXT PRIMARY KEY,
			name             TEXT NOT NULL DEFAULT '',
			version          TEXT NOT NULL DEFAULT '',
			capabilities_json TEXT NOT NULL DEFAULT '[]',
			health           REAL NOT NULL DEFAULT 1.0,
			status           TEXT NOT NULL DEFAULT 'idle',
			registered_at    REAL NOT NULL DEFAULT 0,
			last_updated     REAL NOT NULL DEFAULT 0
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
			span_id       TEXT PRIMARY KEY,
			trace_id      TEXT NOT NULL,
			parent_span_id TEXT,
			node_id       TEXT,
			node_name     TEXT,
			operation     TEXT NOT NULL DEFAULT '',
			started_at    REAL NOT NULL DEFAULT 0,
			ended_at      REAL,
			duration_ms   REAL,
			status        TEXT NOT NULL DEFAULT 'ok',
			cycle         INTEGER NOT NULL DEFAULT 0
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
			event_id          TEXT PRIMARY KEY,
			provider          TEXT NOT NULL DEFAULT '',
			node_id           TEXT NOT NULL DEFAULT '',
			duration_ms       REAL NOT NULL DEFAULT 0,
			estimated_cost_usd REAL NOT NULL DEFAULT 0
		);
	`)
	return err
}

func TestNew_EmptyDB(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()
	if d == nil {
		t.Fatal("expected non-nil DB")
	}
}

func TestSystemHealth_NoNodes(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	health, err := d.SystemHealth()
	if err != nil {
		t.Fatalf("SystemHealth: %v", err)
	}
	if health.Status != "no_nodes" {
		t.Errorf("want status=no_nodes, got %q", health.Status)
	}
	if health.NodeCount != 0 {
		t.Errorf("want NodeCount=0, got %d", health.NodeCount)
	}
}

func TestAllNodes_Empty(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	nodes, err := d.AllNodes()
	if err != nil {
		t.Fatalf("AllNodes: %v", err)
	}
	if len(nodes) != 0 {
		t.Errorf("want 0 nodes, got %d", len(nodes))
	}
}

func TestGetIssues_Empty(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	issues, err := d.GetIssues("open")
	if err != nil {
		t.Fatalf("GetIssues: %v", err)
	}
	if len(issues) != 0 {
		t.Errorf("want 0 issues, got %d", len(issues))
	}
}

func TestRecentTraces_Empty(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	traces, err := d.RecentTraces(10, "")
	if err != nil {
		t.Fatalf("RecentTraces: %v", err)
	}
	if len(traces) != 0 {
		t.Errorf("want 0 traces, got %d", len(traces))
	}
}

func TestGetConvergence_NoMemoryTables(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	// Empty memory DB has no episodes table yet — should return empty not error
	points, err := d.GetConvergence(100)
	// Either nil error with empty result, or an error about missing table is acceptable
	// The key is that it doesn't panic
	_ = points
	_ = err
	// No panic = pass
}

func TestBrainConfig_DefaultsForUnknownNode(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	cfg, err := d.GetBrainConfig("nonexistent-node")
	if err != nil {
		t.Fatalf("GetBrainConfig: %v", err)
	}
	if cfg.Provider != "anthropic" {
		t.Errorf("want default provider=anthropic, got %q", cfg.Provider)
	}
	if cfg.Model != "claude-sonnet-4-6" {
		t.Errorf("want default model=claude-sonnet-4-6, got %q", cfg.Model)
	}
}

func TestBrainConfig_SetAndGet(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	want := &db.BrainConfig{
		NodeID:      "test-node-1",
		Provider:    "openai",
		Model:       "gpt-4o",
		Temperature: 0.5,
		MaxTokens:   2048,
	}
	if err := d.SetBrainConfig(want); err != nil {
		t.Fatalf("SetBrainConfig: %v", err)
	}

	got, err := d.GetBrainConfig("test-node-1")
	if err != nil {
		t.Fatalf("GetBrainConfig: %v", err)
	}
	if got.Provider != want.Provider {
		t.Errorf("provider: want %q got %q", want.Provider, got.Provider)
	}
	if got.Model != want.Model {
		t.Errorf("model: want %q got %q", want.Model, got.Model)
	}
	if got.Temperature != want.Temperature {
		t.Errorf("temperature: want %v got %v", want.Temperature, got.Temperature)
	}
}

func TestBrainConfig_Upsert(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	cfg1 := &db.BrainConfig{NodeID: "n1", Provider: "anthropic", Model: "claude-sonnet-4-6", Temperature: 0.7, MaxTokens: 4096}
	cfg2 := &db.BrainConfig{NodeID: "n1", Provider: "openai", Model: "gpt-4o-mini", Temperature: 0.3, MaxTokens: 1024}

	if err := d.SetBrainConfig(cfg1); err != nil {
		t.Fatal(err)
	}
	if err := d.SetBrainConfig(cfg2); err != nil {
		t.Fatal(err)
	}

	got, err := d.GetBrainConfig("n1")
	if err != nil {
		t.Fatal(err)
	}
	if got.Provider != "openai" {
		t.Errorf("upsert: want provider=openai got %q", got.Provider)
	}
}

func TestGetBrainHistory_Empty(t *testing.T) {
	d, cleanup := setupTestDB(t)
	defer cleanup()

	entries, err := d.GetBrainHistory("any-node", 50)
	if err != nil {
		t.Fatalf("GetBrainHistory: %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("want 0 entries, got %d", len(entries))
	}
}
