package coord

import (
	"context"
	"database/sql"
	"fmt"
	"time"
)

// DistributedLock is a SQLite-backed exclusive lock identified by name.
type DistributedLock struct {
	db       *sql.DB
	lockName string
	holderID string
	ttl      time.Duration
}

// NewDistributedLock creates a DistributedLock and ensures the schema exists.
func NewDistributedLock(db *sql.DB, lockName, holderID string, ttl time.Duration) (*DistributedLock, error) {
	if err := ensureLocksTable(db); err != nil {
		return nil, fmt.Errorf("ensure locks table: %w", err)
	}
	return &DistributedLock{
		db:       db,
		lockName: lockName,
		holderID: holderID,
		ttl:      ttl,
	}, nil
}

// TryAcquire attempts to acquire the lock without blocking.
// Returns true if the lock was acquired.
func (dl *DistributedLock) TryAcquire(ctx context.Context) (bool, error) {
	now := time.Now()
	expires := now.Add(dl.ttl)

	tx, err := dl.db.BeginTx(ctx, nil)
	if err != nil {
		return false, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck

	res, err := tx.ExecContext(ctx, `
		INSERT INTO distributed_locks (lock_name, holder_id, acquired_at, expires_at)
		VALUES (?, ?, ?, ?)
		ON CONFLICT(lock_name) DO UPDATE SET
			holder_id   = excluded.holder_id,
			acquired_at = excluded.acquired_at,
			expires_at  = excluded.expires_at
		WHERE expires_at < ?
	`, dl.lockName, dl.holderID, now.UnixNano(), expires.UnixNano(), now.UnixNano())
	if err != nil {
		return false, fmt.Errorf("upsert lock: %w", err)
	}

	rows, _ := res.RowsAffected()
	if rows == 0 {
		_ = tx.Commit()
		return false, nil
	}
	return true, tx.Commit()
}

// Acquire blocks until the lock is acquired or ctx is cancelled.
// It polls with exponential back-off capped at 500ms.
func (dl *DistributedLock) Acquire(ctx context.Context) error {
	wait := 10 * time.Millisecond
	for {
		ok, err := dl.TryAcquire(ctx)
		if err != nil {
			return err
		}
		if ok {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(wait):
		}
		if wait < 500*time.Millisecond {
			wait *= 2
		}
	}
}

// Release releases the lock. No-op if this node is not the holder.
func (dl *DistributedLock) Release(ctx context.Context) error {
	_, err := dl.db.ExecContext(ctx, `
		DELETE FROM distributed_locks WHERE lock_name = ? AND holder_id = ?
	`, dl.lockName, dl.holderID)
	return err
}

// Barrier waits for exactly n workers to arrive at the same named sync point.
// All waiters are unblocked once the count reaches n.
type Barrier struct {
	db       *sql.DB
	name     string
	workerID string
	n        int
}

// NewBarrier creates a Barrier and ensures the schema exists.
func NewBarrier(db *sql.DB, name, workerID string, n int) (*Barrier, error) {
	if err := ensureBarrierTable(db); err != nil {
		return nil, fmt.Errorf("ensure barrier table: %w", err)
	}
	return &Barrier{db: db, name: name, workerID: workerID, n: n}, nil
}

// Wait registers this worker and blocks until n workers have arrived or ctx is done.
func (b *Barrier) Wait(ctx context.Context) error {
	// Register arrival (idempotent).
	_, err := b.db.ExecContext(ctx, `
		INSERT OR IGNORE INTO barrier_arrivals (barrier_name, worker_id, arrived_at)
		VALUES (?, ?, ?)
	`, b.name, b.workerID, time.Now().UnixNano())
	if err != nil {
		return fmt.Errorf("register arrival: %w", err)
	}

	// Poll until count reaches n.
	for {
		var count int
		if err := b.db.QueryRowContext(ctx, `
			SELECT COUNT(*) FROM barrier_arrivals WHERE barrier_name = ?
		`, b.name).Scan(&count); err != nil {
			return fmt.Errorf("count arrivals: %w", err)
		}
		if count >= b.n {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(20 * time.Millisecond):
		}
	}
}

// Reset removes all arrival records for this barrier (for reuse).
func (b *Barrier) Reset(ctx context.Context) error {
	_, err := b.db.ExecContext(ctx, `DELETE FROM barrier_arrivals WHERE barrier_name = ?`, b.name)
	return err
}

func ensureLocksTable(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS distributed_locks (
			lock_name   TEXT    PRIMARY KEY,
			holder_id   TEXT    NOT NULL,
			acquired_at INTEGER NOT NULL,
			expires_at  INTEGER NOT NULL
		)
	`)
	return err
}

func ensureBarrierTable(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS barrier_arrivals (
			barrier_name TEXT    NOT NULL,
			worker_id    TEXT    NOT NULL,
			arrived_at   INTEGER NOT NULL,
			PRIMARY KEY (barrier_name, worker_id)
		)
	`)
	return err
}
