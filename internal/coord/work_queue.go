package coord

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/google/uuid"
)

const (
	maxAttempts    = 5
	baseBackoff    = time.Second
	statusPending  = "pending"
	statusClaimed  = "claimed"
	statusDone     = "done"
	statusDead     = "dead"
)

// WorkItem represents a unit of work in the distributed queue.
type WorkItem struct {
	ID          string
	Type        string
	Payload     json.RawMessage
	Priority    int
	CreatedAt   time.Time
	ClaimedBy   string
	ClaimedAt   *time.Time
	Attempts    int
	NextRetryAt time.Time
	Status      string
	FailReason  string
}

// WorkQueue is a SQLite-backed distributed work queue with atomic claim semantics.
type WorkQueue struct {
	db *sql.DB
}

// NewWorkQueue creates a WorkQueue and ensures the schema exists.
func NewWorkQueue(db *sql.DB) (*WorkQueue, error) {
	if err := ensureWorkQueueTable(db); err != nil {
		return nil, fmt.Errorf("ensure work_queue table: %w", err)
	}
	return &WorkQueue{db: db}, nil
}

// Enqueue adds a new item to the queue.
func (wq *WorkQueue) Enqueue(item WorkItem) error {
	if item.ID == "" {
		item.ID = uuid.New().String()
	}
	if item.CreatedAt.IsZero() {
		item.CreatedAt = time.Now()
	}
	payload, err := json.Marshal(item.Payload)
	if err != nil {
		return fmt.Errorf("marshal payload: %w", err)
	}
	_, err = wq.db.Exec(`
		INSERT INTO work_queue
			(id, type, payload, priority, created_at, attempts, next_retry_at, status)
		VALUES (?, ?, ?, ?, ?, 0, ?, ?)
	`, item.ID, item.Type, string(payload), item.Priority,
		item.CreatedAt.UnixNano(), item.CreatedAt.UnixNano(), statusPending)
	return err
}

// Dequeue atomically claims the highest-priority pending item eligible for processing.
// Returns nil, nil when the queue is empty.
func (wq *WorkQueue) Dequeue(ctx context.Context, workerID string) (*WorkItem, error) {
	now := time.Now()

	tx, err := wq.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck

	var item WorkItem
	var createdNano, nextRetryNano int64
	var claimedNano sql.NullInt64
	var payloadStr string

	err = tx.QueryRowContext(ctx, `
		SELECT id, type, payload, priority, created_at, claimed_by, claimed_at,
		       attempts, next_retry_at, status
		FROM work_queue
		WHERE status = ? AND next_retry_at <= ?
		ORDER BY priority DESC, created_at ASC
		LIMIT 1
	`, statusPending, now.UnixNano()).Scan(
		&item.ID, &item.Type, &payloadStr, &item.Priority,
		&createdNano, &item.ClaimedBy, &claimedNano,
		&item.Attempts, &nextRetryNano, &item.Status,
	)
	if err == sql.ErrNoRows {
		_ = tx.Commit()
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("select item: %w", err)
	}

	claimedAt := now
	_, err = tx.ExecContext(ctx, `
		UPDATE work_queue
		SET status = ?, claimed_by = ?, claimed_at = ?, attempts = attempts + 1
		WHERE id = ? AND status = ?
	`, statusClaimed, workerID, now.UnixNano(), item.ID, statusPending)
	if err != nil {
		return nil, fmt.Errorf("claim item: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	item.CreatedAt = time.Unix(0, createdNano)
	item.NextRetryAt = time.Unix(0, nextRetryNano)
	item.ClaimedBy = workerID
	item.ClaimedAt = &claimedAt
	item.Attempts++
	item.Status = statusClaimed
	item.Payload = json.RawMessage(payloadStr)
	return &item, nil
}

// Complete marks an item as successfully processed.
func (wq *WorkQueue) Complete(itemID string) error {
	_, err := wq.db.Exec(`
		UPDATE work_queue SET status = ? WHERE id = ? AND status = ?
	`, statusDone, itemID, statusClaimed)
	return err
}

// Fail marks an item as failed. If it has exceeded maxAttempts it moves to the
// dead-letter queue; otherwise it is re-queued with exponential backoff.
func (wq *WorkQueue) Fail(itemID, reason string) error {
	tx, err := wq.db.Begin()
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck

	var attempts int
	if err := tx.QueryRow(`SELECT attempts FROM work_queue WHERE id = ?`, itemID).Scan(&attempts); err != nil {
		return fmt.Errorf("query attempts: %w", err)
	}

	var newStatus string
	var nextRetry int64
	if attempts >= maxAttempts {
		newStatus = statusDead
		nextRetry = time.Now().UnixNano()
	} else {
		newStatus = statusPending
		backoff := time.Duration(math.Pow(2, float64(attempts-1))) * baseBackoff
		nextRetry = time.Now().Add(backoff).UnixNano()
	}

	_, err = tx.Exec(`
		UPDATE work_queue
		SET status = ?, fail_reason = ?, next_retry_at = ?, claimed_by = '', claimed_at = NULL
		WHERE id = ?
	`, newStatus, reason, nextRetry, itemID)
	if err != nil {
		return err
	}
	return tx.Commit()
}

// DeadLetterItems returns all items in the dead-letter queue.
func (wq *WorkQueue) DeadLetterItems(ctx context.Context) ([]WorkItem, error) {
	rows, err := wq.db.QueryContext(ctx, `
		SELECT id, type, payload, priority, created_at, claimed_by, attempts, fail_reason
		FROM work_queue WHERE status = ? ORDER BY created_at ASC
	`, statusDead)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck

	var items []WorkItem
	for rows.Next() {
		var it WorkItem
		var createdNano int64
		var payloadStr string
		if err := rows.Scan(&it.ID, &it.Type, &payloadStr, &it.Priority,
			&createdNano, &it.ClaimedBy, &it.Attempts, &it.FailReason); err != nil {
			return nil, err
		}
		it.CreatedAt = time.Unix(0, createdNano)
		it.Payload = json.RawMessage(payloadStr)
		it.Status = statusDead
		items = append(items, it)
	}
	return items, rows.Err()
}

func ensureWorkQueueTable(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS work_queue (
			id            TEXT    PRIMARY KEY,
			type          TEXT    NOT NULL,
			payload       TEXT    NOT NULL DEFAULT '{}',
			priority      INTEGER NOT NULL DEFAULT 0,
			created_at    INTEGER NOT NULL,
			claimed_by    TEXT    NOT NULL DEFAULT '',
			claimed_at    INTEGER,
			attempts      INTEGER NOT NULL DEFAULT 0,
			next_retry_at INTEGER NOT NULL DEFAULT 0,
			status        TEXT    NOT NULL DEFAULT 'pending',
			fail_reason   TEXT    NOT NULL DEFAULT ''
		);
		CREATE INDEX IF NOT EXISTS idx_wq_status_retry
			ON work_queue (status, next_retry_at, priority DESC, created_at ASC);
	`)
	return err
}
