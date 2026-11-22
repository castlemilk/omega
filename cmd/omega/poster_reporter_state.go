package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"errors"
	"fmt"
	"io/fs"
	"math/rand/v2"
	"path/filepath"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	bolt "go.etcd.io/bbolt"
	"google.golang.org/protobuf/proto"
)

const reporterRunTimeout = 6 * time.Minute
const reporterLease = reporterRunTimeout + time.Minute

var reporterBucket = []byte("local-reporter/v1")
var errReporterInProgress = errors.New("another order check is already in progress")

// Both an early wake and a newly deferred check have a durable retry time.
// The scheduler can finish normally. A manual caller still receives an error
// and cannot mistake an empty response for a statement receipt.
type reporterWait struct {
	cause error
	next  string
}

func (w *reporterWait) Error() string {
	return fmt.Sprintf("%s. Next eligible check %s", w.cause, w.next)
}
func (w *reporterWait) Unwrap() error { return w.cause }

// Opening the database just for a transaction leaves status readable while
// the provider or Studio is responding. A killed process has a bounded lease.
type reporterState struct {
	path string
	pair [sha256.Size]byte
}

func localReporterState(dir string, key ed25519.PrivateKey) reporterState {
	return reporterState{filepath.Join(dir, "checks.db"), sha256.Sum256(key.Public().(ed25519.PublicKey))}
}

func (s reporterState) transact(change func(*v1.LocalReporterStatus) error) (*v1.LocalReporterStatus, error) {
	status := &v1.LocalReporterStatus{Outcome: "never-run"}
	db, err := bolt.Open(s.path, 0600, &bolt.Options{ReadOnly: change == nil, Timeout: 2 * time.Second, OpenFile: openPrivateDataFile})
	if change == nil && errors.Is(err, fs.ErrNotExist) {
		return status, nil
	}
	if err != nil {
		return nil, errors.New("could not open the private reporting status file")
	}
	defer func() { _ = db.Close() }()
	use := db.View
	if change != nil {
		use = db.Update
	}
	err = use(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(reporterBucket)
		if bucket != nil {
			if raw := bucket.Get(s.pair[:]); raw != nil {
				if err := proto.Unmarshal(raw, status); err != nil || status.Outcome == "" {
					return errors.New("could not read this connection’s saved reporting status")
				}
			}
		}
		if change == nil {
			return nil
		}
		if err := change(status); err != nil {
			return err
		}
		if bucket == nil {
			var err error
			if bucket, err = tx.CreateBucket(reporterBucket); err != nil {
				return err
			}
		}
		raw, err := proto.Marshal(status)
		if err != nil {
			return err
		}
		return bucket.Put(s.pair[:], raw)
	})
	return status, err
}

func reporterStamp(at time.Time) string { return at.UTC().Format(time.RFC3339Nano) }

func (s reporterState) status(now time.Time) (*v1.LocalReporterStatus, error) {
	status, err := s.transact(nil)
	if err != nil {
		return nil, err
	}
	if status.Outcome == "checking" {
		started, err := time.Parse(time.RFC3339Nano, status.AttemptAt)
		if err != nil {
			return nil, errors.New("invalid saved reporter attempt time")
		}
		if !now.Before(started.Add(reporterLease)) {
			status.Outcome = "interrupted"
		}
	}
	return status, nil
}

// Claim the whole wake, including a cooldown heartbeat, before contacting Studio.
// The previous provider attempt remains intact until current authority is proven.
func (s reporterState) claim(now time.Time) (*v1.LocalReporterStatus, error) {
	return s.transact(func(status *v1.LocalReporterStatus) error {
		lease := status.WakeLeaseAt
		if lease == "" && status.Outcome == "checking" {
			lease = status.AttemptAt // A reporter started by the previous binary.
		}
		if lease != "" {
			started, err := time.Parse(time.RFC3339Nano, lease)
			if err != nil {
				return errors.New("invalid saved reporter attempt time")
			}
			if now.Before(started.Add(reporterLease)) {
				return errReporterInProgress
			}
		}
		if status.NextProviderReadAt != "" {
			if _, err := time.Parse(time.RFC3339Nano, status.NextProviderReadAt); err != nil ||
				(status.Outcome != "rate-limited" && status.Outcome != "recheck-rate-limited") {
				return errors.New("invalid saved Stripe retry time")
			}
		}
		status.WakeLeaseAt = reporterStamp(now)
		return nil
	})
}

func (s reporterState) owned(lease time.Time, change func(*v1.LocalReporterStatus)) (*v1.LocalReporterStatus, error) {
	return s.transact(func(status *v1.LocalReporterStatus) error {
		if status.WakeLeaseAt != reporterStamp(lease) {
			return errors.New("a newer reporter wake owns this check")
		}
		change(status)
		return nil
	})
}

func (s reporterState) release(lease time.Time) error {
	_, err := s.owned(lease, func(status *v1.LocalReporterStatus) { status.WakeLeaseAt = "" })
	return err
}

func (s reporterState) noteCheckIn(lease time.Time, check *v1.ReporterCheckIn, revision uint32) error {
	_, err := s.owned(lease, func(status *v1.LocalReporterStatus) {
		status.LastCheckInAt = check.CheckedInAt
		status.CheckInOutcome = "unconfirmed"
		if revision != 0 {
			status.CheckInOutcome = "confirmed"
			if check.Activity == "provider-wait" && status.LimitConnectionRevision == 0 {
				status.LimitConnectionRevision = revision
			}
		}
	})
	return err
}

func (s reporterState) startRead(lease, now time.Time, from, through string) error {
	_, err := s.owned(lease, func(status *v1.LocalReporterStatus) {
		status.Outcome, status.AttemptAt, status.FinishedAt = "checking", reporterStamp(now), ""
		status.FromDay, status.ThroughDay = from, through
		status.NextProviderReadAt, status.ProviderRetryAt, status.LimitReason, status.LimitedRead = "", "", "", ""
		status.LimitConnectionRevision, status.LimitedAttemptAt = 0, ""
	})
	return err
}

func nextReporterRead(now time.Time, count uint32, limit *commerce.StatementReadLimit) time.Time {
	wait := min(5*time.Minute<<min(count-1, 4), time.Hour)
	if limit != nil && limit.Reason == "sandbox-quota" {
		wait = time.Hour
	}
	// Jitter is scheduling noise, not a secret. Spread retries up to 20%.
	next := now.Add(wait + time.Duration(rand.Int64N(int64(wait/5)))) // #nosec G404
	if limit != nil && limit.RetryAt.After(next) {
		next = limit.RetryAt
	}
	return next
}

func (s reporterState) finish(lease, now time.Time, receipt *v1.CommerceReporterReceipt, result error, revision uint32) (*v1.LocalReporterStatus, error) {
	return s.owned(lease, func(status *v1.LocalReporterStatus) {
		status.FinishedAt = reporterStamp(now)
		if receipt != nil {
			status.LastReceipt = receipt
			status.ReceiptFromDay, status.ReceiptThroughDay = status.FromDay, status.ThroughDay
		}
		switch {
		case errors.Is(result, commerce.ErrStatementRateLimited):
			status.Outcome = "rate-limited"
			status.LimitConnectionRevision = revision
			status.LimitedAttemptAt = reporterStamp(now)
			if receipt != nil {
				status.Outcome = "recheck-rate-limited"
			}
			if status.ConsecutiveLimits < ^uint32(0) {
				status.ConsecutiveLimits++
			}
			var limit *commerce.StatementReadLimit
			if errors.As(result, &limit) {
				status.LimitedRead, status.LimitReason = limit.Read, limit.Reason
				if !limit.ObservedAt.IsZero() {
					status.LimitedAttemptAt = reporterStamp(limit.ObservedAt)
				}
				if !limit.RetryAt.IsZero() {
					status.ProviderRetryAt = reporterStamp(limit.RetryAt)
				}
			}
			status.NextProviderReadAt = reporterStamp(nextReporterRead(now, status.ConsecutiveLimits, limit))
		case result != nil && receipt != nil:
			status.Outcome = "recheck-pending"
			status.ConsecutiveLimits = 0
		case result != nil:
			status.Outcome = "failed"
			status.ConsecutiveLimits = 0
		default:
			status.Outcome = "acknowledged"
			status.ConsecutiveLimits = 0
		}
	})
}
