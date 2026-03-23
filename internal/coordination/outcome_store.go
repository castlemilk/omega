// outcome_store.go — Postgres-backed (goal, routing, outcome) tuple store.
//
// OutcomeStore persists OutcomeRecord tuples for future attention model training.
// It also provides the aggregate routing statistics used by GetRoutingStats.
//
// Schema (Postgres):
//
//	CREATE TABLE IF NOT EXISTS coordination_outcomes (
//	    record_id        TEXT        PRIMARY KEY,
//	    goal_id          TEXT        NOT NULL,
//	    goal_type        INTEGER     NOT NULL,
//	    goal_json        JSONB       NOT NULL,  -- full GoalSpec proto JSON
//	    routing_json     JSONB       NOT NULL,  -- RoutingPlan proto JSON
//	    outcome_quality  REAL        NOT NULL,
//	    captured_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
//	    state_snapshot   JSONB       NOT NULL   -- map[node_id]StateTensor JSON
//	);
//
// The storage interface is intentionally abstract: OutcomeStore only depends on
// *sql.DB so the backend can be swapped by the caller.

package coordination

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

// ---------------------------------------------------------------------------
// OutcomeStore
// ---------------------------------------------------------------------------

// OutcomeStore persists routing outcomes and provides aggregate statistics.
type OutcomeStore struct {
	db *sql.DB
}

// NewOutcomeStore creates an OutcomeStore and ensures the schema exists.
func NewOutcomeStore(db *sql.DB) (*OutcomeStore, error) {
	if err := ensureOutcomeSchema(db); err != nil {
		return nil, fmt.Errorf("ensure coordination_outcomes schema: %w", err)
	}
	return &OutcomeStore{db: db}, nil
}

// Store persists an OutcomeRecord. If record.RecordId is empty a new UUID is assigned.
// Returns the record_id.
func (s *OutcomeStore) Store(ctx context.Context, record *omegav1.OutcomeRecord) (string, error) {
	if record.RecordId == "" {
		record.RecordId = uuid.New().String()
	}

	goalJSON, err := protojson.Marshal(record.Goal)
	if err != nil {
		return "", fmt.Errorf("marshal goal: %w", err)
	}

	routingJSON, err := protojson.Marshal(record.RoutingPlan)
	if err != nil {
		return "", fmt.Errorf("marshal routing plan: %w", err)
	}

	// Serialise state snapshot as a map of node_id → JSON-encoded StateTensor
	snapMap := make(map[string]json.RawMessage, len(record.StateSnapshot))
	for nid, t := range record.StateSnapshot {
		b, err := protojson.Marshal(t)
		if err != nil {
			return "", fmt.Errorf("marshal tensor for node %s: %w", nid, err)
		}
		snapMap[nid] = json.RawMessage(b)
	}
	snapJSON, err := json.Marshal(snapMap)
	if err != nil {
		return "", fmt.Errorf("marshal state snapshot: %w", err)
	}

	capturedAt := time.Now()
	if record.CapturedAt != nil {
		capturedAt = record.CapturedAt.AsTime()
	}

	goalType := 0
	if record.Goal != nil {
		goalType = int(record.Goal.Type)
	}
	goalID := ""
	if record.Goal != nil {
		goalID = record.Goal.GoalId
	}

	_, err = s.db.ExecContext(ctx, `
		INSERT INTO coordination_outcomes
			(record_id, goal_id, goal_type, goal_json, routing_json,
			 outcome_quality, captured_at, state_snapshot)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT (record_id) DO NOTHING
	`,
		record.RecordId,
		goalID,
		goalType,
		string(goalJSON),
		string(routingJSON),
		record.OutcomeQuality,
		capturedAt,
		string(snapJSON),
	)
	if err != nil {
		return "", fmt.Errorf("insert outcome record: %w", err)
	}
	return record.RecordId, nil
}

// Stats returns aggregate routing statistics.
func (s *OutcomeStore) Stats(ctx context.Context, since time.Time) (*omegav1.GetRoutingStatsResponse, error) {
	var total, outcomes int64
	var avgConf sql.NullFloat64

	var err error
	if since.IsZero() {
		err = s.db.QueryRowContext(ctx, `
			SELECT COUNT(*) AS total_routes,
			       COUNT(*) AS outcome_records,
			       AVG((routing_json->>'confidence')::FLOAT) AS avg_confidence
			FROM coordination_outcomes
		`).Scan(&total, &outcomes, &avgConf)
	} else {
		err = s.db.QueryRowContext(ctx, `
			SELECT COUNT(*) AS total_routes,
			       COUNT(*) AS outcome_records,
			       AVG((routing_json->>'confidence')::FLOAT) AS avg_confidence
			FROM coordination_outcomes
			WHERE captured_at >= $1
		`, since).Scan(&total, &outcomes, &avgConf)
	}
	if err != nil {
		return nil, fmt.Errorf("query outcome stats: %w", err)
	}

	var conf float32
	if avgConf.Valid {
		conf = float32(avgConf.Float64)
	}

	return &omegav1.GetRoutingStatsResponse{
		TotalRoutes:       total,
		OutcomeRecords:    outcomes,
		AvgConfidence:     conf,
		TrainingEligible:  outcomes >= 1000,
	}, nil
}

// RecentOutcomes returns the most recent n outcomes for a specific node.
// Used by the weight adapter to compute recent performance.
func (s *OutcomeStore) RecentOutcomes(ctx context.Context, nodeID string, n int) ([]float32, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT outcome_quality
		FROM coordination_outcomes
		WHERE routing_json->>'primaryNode' = $1
		ORDER BY captured_at DESC
		LIMIT $2
	`, nodeID, n)
	if err != nil {
		return nil, fmt.Errorf("query recent outcomes: %w", err)
	}
	defer rows.Close() //nolint:errcheck

	var results []float32
	for rows.Next() {
		var q float64
		if err := rows.Scan(&q); err != nil {
			return nil, err
		}
		results = append(results, float32(q))
	}
	return results, rows.Err()
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

func ensureOutcomeSchema(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS coordination_outcomes (
			record_id        TEXT        PRIMARY KEY,
			goal_id          TEXT        NOT NULL DEFAULT '',
			goal_type        INTEGER     NOT NULL DEFAULT 0,
			goal_json        TEXT        NOT NULL DEFAULT '{}',
			routing_json     TEXT        NOT NULL DEFAULT '{}',
			outcome_quality  REAL        NOT NULL DEFAULT 0,
			captured_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			state_snapshot   TEXT        NOT NULL DEFAULT '{}'
		);
		CREATE INDEX IF NOT EXISTS idx_coord_outcomes_node
			ON coordination_outcomes
			((routing_json::json->>'primaryNode'), captured_at DESC);
		CREATE INDEX IF NOT EXISTS idx_coord_outcomes_goal_type
			ON coordination_outcomes (goal_type, captured_at DESC);
	`)
	return err
}
