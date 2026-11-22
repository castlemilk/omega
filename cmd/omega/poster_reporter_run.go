package main

import (
	"context"
	"errors"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
)

func reporterHeartbeat(now time.Time, revision uint32, waiting *v1.LocalReporterStatus) *v1.ReporterCheckIn {
	check := &v1.ReporterCheckIn{BusinessId: posters.StudioBusinessID, ProductId: posters.StudioProductID,
		CheckedInAt: reporterStamp(now), Activity: "checking", ExpectedConnectionRevision: revision}
	if waiting == nil {
		return check
	}
	check.Activity, check.NextReadAt = "provider-wait", waiting.NextProviderReadAt
	check.AttemptAt = waiting.LimitedAttemptAt
	if check.AttemptAt == "" {
		// Existing local records identify the actual run that encountered the limit.
		check.AttemptAt = waiting.AttemptAt
	}
	check.Recheck = waiting.Outcome == "recheck-rate-limited"
	switch waiting.LimitReason {
	case "sandbox-quota":
		check.LimitReason = "sandbox-quota"
	case "rate-limit", "global-rate", "global-concurrency", "endpoint-rate", "endpoint-concurrency", "resource-specific":
		check.LimitReason = "rate-limit"
	}
	return check
}

func runReporterCheck(parent context.Context, state reporterState, from, through string, clock func() time.Time,
	connect func(context.Context, *v1.ReporterCheckIn) (*v1.ReporterCheckInReceipt, error),
	send func(context.Context, uint32, func(context.Context, uint32) error) (*v1.CommerceReporterReceipt, error),
) (receipt *v1.CommerceReporterReceipt, result error) {
	lease := clock()
	status, err := state.claim(lease)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := state.release(lease); err != nil {
			// A scheduled wake must surface a failed local save even during a wait.
			result = err
		}
	}()
	ctx, cancel := context.WithTimeout(parent, reporterRunTimeout)
	defer cancel()
	contact := func(ctx context.Context, expected uint32, waiting *v1.LocalReporterStatus) (uint32, error) {
		check := reporterHeartbeat(clock(), expected, waiting)
		ack, err := connect(ctx, check)
		if err == nil && (ack.GetConnectionRevision() == 0 || (expected != 0 && ack.ConnectionRevision != expected) ||
			ack.BusinessId != check.BusinessId || ack.ProductId != check.ProductId || ack.CheckedInAt != check.CheckedInAt) {
			err = errors.New("Studio did not acknowledge this reporter connection")
		}
		var revision uint32
		if err == nil {
			revision = ack.ConnectionRevision
		}
		return revision, errors.Join(err, state.noteCheckIn(lease, check, revision))
	}
	reportWait := func(status *v1.LocalReporterStatus) error {
		if _, err := contact(ctx, status.LimitConnectionRevision, status); err != nil {
			return err
		}
		return &reporterWait{commerce.ErrStatementRateLimited, status.NextProviderReadAt}
	}
	if status.NextProviderReadAt != "" {
		next, _ := time.Parse(time.RFC3339Nano, status.NextProviderReadAt) // Validated by claim.
		if clock().Before(next) {
			return nil, reportWait(status)
		}
	}
	revision, err := contact(ctx, 0, nil)
	if err != nil {
		return nil, err
	}
	if err := state.startRead(lease, clock(), from, through); err != nil {
		return nil, err
	}
	receipt, result = send(ctx, revision, func(ctx context.Context, expected uint32) error {
		_, err := contact(ctx, expected, nil)
		return err
	})
	if receipt == nil && result == nil {
		result = errors.New("Studio did not acknowledge the check")
	}
	saved, err := state.finish(lease, clock(), receipt, result, revision)
	if err != nil {
		return receipt, err
	}
	if errors.Is(result, commerce.ErrStatementRateLimited) {
		return receipt, reportWait(saved)
	}
	return receipt, result
}
