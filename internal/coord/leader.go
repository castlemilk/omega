// Package coord provides distributed coordination primitives for multi-process Omega.
// All coordination is backed by SQLite with WAL mode to allow concurrent readers.
package coord

import (
	"context"
	"database/sql"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// LeaderElection implements lease-based leader election using a SQLite row lock.
// A node holds leadership while it refreshes the lease before TTL expiry.
type LeaderElection struct {
	db             *sql.DB
	nodeID         string
	ttl            time.Duration
	mu             sync.RWMutex
	isLeader       bool
	onLeaderChange func(isLeader bool, leaderID string)
}

// NewLeaderElection creates a LeaderElection and ensures the schema exists.
func NewLeaderElection(db *sql.DB, nodeID string, ttl time.Duration) (*LeaderElection, error) {
	if err := ensureLeaderTable(db); err != nil {
		return nil, fmt.Errorf("ensure leader table: %w", err)
	}
	return &LeaderElection{
		db:     db,
		nodeID: nodeID,
		ttl:    ttl,
	}, nil
}

// OnLeaderChange registers a callback invoked when leadership status changes.
// The callback receives the new state and the ID of the current leader.
func (le *LeaderElection) OnLeaderChange(fn func(isLeader bool, leaderID string)) {
	le.mu.Lock()
	le.onLeaderChange = fn
	le.mu.Unlock()
}

// TryAcquire attempts to become leader. Returns true if this node is now leader.
// It either inserts a new lease or steals an expired one.
func (le *LeaderElection) TryAcquire(ctx context.Context) (bool, error) {
	now := time.Now()
	expires := now.Add(le.ttl)

	tx, err := le.db.BeginTx(ctx, nil)
	if err != nil {
		return false, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck

	// Try to insert (first acquisition) or update an expired lease.
	res, err := tx.ExecContext(ctx, `
		INSERT INTO leader_election (singleton, leader_id, acquired_at, expires_at)
		VALUES (1, ?, ?, ?)
		ON CONFLICT(singleton) DO UPDATE SET
			leader_id   = excluded.leader_id,
			acquired_at = excluded.acquired_at,
			expires_at  = excluded.expires_at
		WHERE expires_at < ?
	`, le.nodeID, now.UnixNano(), expires.UnixNano(), now.UnixNano())
	if err != nil {
		return false, fmt.Errorf("upsert leader: %w", err)
	}

	rows, _ := res.RowsAffected()
	if rows == 0 {
		// Someone else holds a live lease — check if it's us (already leader).
		var currentLeader string
		err = tx.QueryRowContext(ctx, `SELECT leader_id FROM leader_election LIMIT 1`).Scan(&currentLeader)
		if err != nil && err != sql.ErrNoRows {
			return false, fmt.Errorf("query leader: %w", err)
		}
		if err := tx.Commit(); err != nil {
			return false, err
		}
		alreadyLeader := currentLeader == le.nodeID
		le.setLeader(alreadyLeader, currentLeader)
		return alreadyLeader, nil
	}

	if err := tx.Commit(); err != nil {
		return false, err
	}
	le.setLeader(true, le.nodeID)
	return true, nil
}

// Renew refreshes the lease expiry. Returns an error if this node is not leader.
func (le *LeaderElection) Renew(ctx context.Context) error {
	expires := time.Now().Add(le.ttl)
	res, err := le.db.ExecContext(ctx, `
		UPDATE leader_election SET expires_at = ? WHERE leader_id = ?
	`, expires.UnixNano(), le.nodeID)
	if err != nil {
		return fmt.Errorf("renew lease: %w", err)
	}
	rows, _ := res.RowsAffected()
	if rows == 0 {
		le.setLeader(false, "")
		return fmt.Errorf("not current leader: node %s cannot renew", le.nodeID)
	}
	return nil
}

// Release voluntarily gives up leadership.
func (le *LeaderElection) Release(ctx context.Context) error {
	_, err := le.db.ExecContext(ctx, `
		DELETE FROM leader_election WHERE leader_id = ?
	`, le.nodeID)
	if err != nil {
		return fmt.Errorf("release leader: %w", err)
	}
	le.setLeader(false, "")
	return nil
}

// IsLeader returns whether this node currently believes it is the leader.
// The cached value is updated by TryAcquire, Renew, and Release.
func (le *LeaderElection) IsLeader() bool {
	le.mu.RLock()
	defer le.mu.RUnlock()
	return le.isLeader
}

func (le *LeaderElection) setLeader(leader bool, leaderID string) {
	le.mu.Lock()
	changed := le.isLeader != leader
	le.isLeader = leader
	cb := le.onLeaderChange
	le.mu.Unlock()
	if changed && cb != nil {
		cb(leader, leaderID)
	}
}

func ensureLeaderTable(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS leader_election (
			singleton   INTEGER PRIMARY KEY DEFAULT 1 CHECK (singleton = 1),
			leader_id   TEXT    NOT NULL,
			acquired_at INTEGER NOT NULL,
			expires_at  INTEGER NOT NULL
		)
	`)
	return err
}
