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
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

// bootstrapSubsystemSchema adds the new subsystem tables to an existing state DB.
func bootstrapSubsystemSchema(t *testing.T, stateDBPath string) {
	t.Helper()
	sqlDB, err := sql.Open("sqlite", stateDBPath)
	if err != nil {
		t.Fatalf("open state db: %v", err)
	}
	defer sqlDB.Close() //nolint:errcheck
	_, err = sqlDB.Exec(`
		CREATE TABLE IF NOT EXISTS alignment_decisions (
			decision_id       TEXT PRIMARY KEY,
			cycle             INTEGER NOT NULL DEFAULT 0,
			approved          INTEGER NOT NULL DEFAULT 1,
			reasons           TEXT NOT NULL DEFAULT '[]',
			target_subsystem  TEXT NOT NULL DEFAULT '',
			recorded_at       REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS adversarial_results (
			result_id   TEXT PRIMARY KEY,
			cycle       INTEGER NOT NULL DEFAULT 0,
			ring        INTEGER NOT NULL DEFAULT 0,
			flags       TEXT NOT NULL DEFAULT '[]',
			severity    TEXT NOT NULL DEFAULT 'low',
			recorded_at REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS goal_tracking (
			id                    INTEGER PRIMARY KEY AUTOINCREMENT,
			cycle                 INTEGER NOT NULL DEFAULT 0,
			constitutional_checks TEXT NOT NULL DEFAULT '{}',
			scorecard_values      TEXT NOT NULL DEFAULT '{}',
			active_tasks          TEXT NOT NULL DEFAULT '[]',
			recorded_at           REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS verification_gates (
			gate_id    TEXT PRIMARY KEY,
			cycle      INTEGER NOT NULL DEFAULT 0,
			gate_name  TEXT NOT NULL DEFAULT '',
			result     TEXT NOT NULL DEFAULT 'pass',
			details    TEXT NOT NULL DEFAULT '',
			checked_at REAL NOT NULL DEFAULT 0
		);
	`)
	if err != nil {
		t.Fatalf("bootstrap subsystem schema: %v", err)
	}
}

// setupSubsystemTestServer creates a test server seeded with both base and subsystem schemas.
func setupSubsystemTestServer(t *testing.T) (omegav1connect.OrchestratorServiceClient, func()) {
	t.Helper()
	dir := t.TempDir()
	stateDB := filepath.Join(dir, "state.db")
	memDB := filepath.Join(dir, "memory.db")

	bootstrapStateSchema(t, stateDB)
	bootstrapSubsystemSchema(t, stateDB)

	// Seed memory DB with required tables
	memSQLDB, _ := sql.Open("sqlite", memDB)
	_, _ = memSQLDB.Exec(`
		CREATE TABLE IF NOT EXISTS episodes (
			episode_id TEXT PRIMARY KEY,
			event_type TEXT NOT NULL DEFAULT '',
			timestamp  REAL NOT NULL DEFAULT 0,
			cycle      INTEGER NOT NULL DEFAULT 0,
			importance REAL NOT NULL DEFAULT 0,
			tags       TEXT NOT NULL DEFAULT '',
			namespace  TEXT NOT NULL DEFAULT ''
		);
		CREATE TABLE IF NOT EXISTS semantic_memories (
			concept_id     TEXT PRIMARY KEY,
			namespace      TEXT NOT NULL DEFAULT '',
			concept        TEXT NOT NULL DEFAULT '',
			content        TEXT NOT NULL DEFAULT '',
			confidence     REAL NOT NULL DEFAULT 0,
			evidence_count INTEGER NOT NULL DEFAULT 0,
			tags_json      TEXT NOT NULL DEFAULT '[]'
		);
	`) //nolint:errcheck
	memSQLDB.Close() //nolint:errcheck,gosec

	f, _ := os.Create(memDB) //nolint:gosec // ensure file exists (already created above)
	f.Close()                //nolint:errcheck,gosec

	database, err := db.New(stateDB, memDB)
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
