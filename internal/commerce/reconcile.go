package commerce

import (
	"context"
	"database/sql"
	"errors"
	"time"
)

// Drain reconciles signed inbox references and polls known orders for a missing
// notification. It can run on multiple processes sharing a database.
func (s *Shop) Drain(ctx context.Context) error {
	rows, err := s.db.QueryContext(ctx, `WITH ready AS (
		SELECT connection_id,id FROM omega_digital_inbox WHERE connection_id=$1 AND status='queued' AND next_attempt<=now()
		ORDER BY next_attempt,id LIMIT 16 FOR UPDATE SKIP LOCKED)
		UPDATE omega_digital_inbox i SET next_attempt=now()+interval '30 seconds',attempts=attempts+1 FROM ready
		WHERE (i.connection_id,i.id)=(ready.connection_id,ready.id) RETURNING i.id,i.attempts`, s.connection)
	if err != nil {
		return err
	}
	type claim struct {
		id      string
		attempt int
	}
	var claims []claim
	for rows.Next() {
		var c claim
		if err = rows.Scan(&c.id, &c.attempt); err != nil {
			rows.Close()
			return err
		}
		claims = append(claims, c)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, c := range claims {
		var orderID string
		err = s.db.QueryRowContext(ctx, `SELECT o.id FROM omega_digital_inbox i JOIN omega_digital_orders o ON o.connection_id=i.connection_id AND `+subjectMatch+`
			WHERE i.connection_id=$1 AND i.id=$2`, s.connection, c.id).Scan(&orderID)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if orderID != "" && s.refresh(ctx, orderID, nil) == nil {
			continue
		}
		delay := time.Duration(min(c.attempt*c.attempt, 60)) * time.Second
		_, err = s.db.ExecContext(ctx, `UPDATE omega_digital_inbox SET status=CASE WHEN attempts>=8 THEN 'needs_review' ELSE 'queued' END,
			next_attempt=now()+($3::int * interval '1 second'),order_id=nullif($4,'')::uuid WHERE connection_id=$1 AND id=$2 AND status='queued' AND attempts=$5`,
			s.connection, c.id, int(delay.Seconds()), orderID, c.attempt)
		if err != nil {
			return err
		}
	}
	rows, err = s.db.QueryContext(ctx, `WITH due AS (
		SELECT id FROM omega_digital_orders WHERE connection_id=$1 AND session_id IS NOT NULL AND next_check<=now()
		AND ((payment IN (1,3) AND created_at>now()-interval '2 days') OR (entitled_at>now()-interval '24 hours'))
		ORDER BY next_check,id LIMIT 8 FOR UPDATE SKIP LOCKED)
		UPDATE omega_digital_orders o SET next_check=now()+interval '1 minute' FROM due WHERE o.connection_id=$1 AND o.id=due.id RETURNING o.id`, s.connection)
	if err != nil {
		return err
	}
	var ids []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, id := range ids {
		if err = s.refresh(ctx, id, nil); err != nil && ctx.Err() != nil {
			return ctx.Err()
		}
	}
	return nil
}

func (s *Shop) Replay(ctx context.Context, id, eventID string, buyer []byte) error {
	if len(buyer) != 32 {
		return ErrMissing
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = s.order(ctx, tx, id, buyer, true); err != nil {
		return err
	}
	r, err := tx.ExecContext(ctx, `UPDATE omega_digital_inbox i SET status='queued',attempts=0,next_attempt=now()
		FROM omega_digital_orders o WHERE o.connection_id=i.connection_id AND o.connection_id=$1 AND o.id=$2 AND i.id=$3
		AND i.status='needs_review' AND `+subjectMatch, s.connection, id, eventID)
	if err != nil {
		return err
	}
	n, err := r.RowsAffected()
	if err != nil {
		return err
	}
	if n != 1 {
		return ErrConflict
	}
	return tx.Commit()
}
