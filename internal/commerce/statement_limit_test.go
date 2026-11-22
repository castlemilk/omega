package commerce

import (
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v87"
)

func TestStatementRetryTime(t *testing.T) {
	now := time.Date(2026, 11, 22, 12, 0, 1, 123, time.UTC)
	later := now.Truncate(time.Second).Add(48 * time.Hour)
	require.Equal(t, now.Add(3*time.Hour), providerRetryTime("10800", now))
	require.Equal(t, later, providerRetryTime(later.Format(http.TimeFormat), now))
	require.Equal(t, 9999, providerRetryTime("999999999999999999999999", now).Year())
	for _, invalid := range []string{"", "+12", "-1", "1.5", "in an hour", now.Add(-time.Minute).Format(http.TimeFormat)} {
		require.True(t, providerRetryTime(invalid, now).IsZero(), invalid)
	}
}

func TestStatementLimitsOnlyExposeKnownMetadata(t *testing.T) {
	upstream := &stripe.Error{HTTPStatusCode: 429, Msg: "Rate limit in this sandbox. Claim the sandbox using private material"}
	upstream.LastResponse = &stripe.APIResponse{Header: http.Header{"Stripe-Rate-Limited-Reason": {"private material"}}}
	limit := statementReadLimit(fmt.Errorf("wrapped: %w", upstream), "order")
	require.Equal(t, "sandbox-quota", limit.Reason)
	require.ErrorIs(t, limit, ErrStatementRateLimited)
	require.NotContains(t, limit.Error(), "private material")
	upstream.Msg = "other private material"
	require.Empty(t, statementReadLimit(upstream, "refunds").Reason)
	upstream.Code = stripe.ErrorCodeLockTimeout
	require.Nil(t, statementReadLimit(upstream, "order"))
	upstream.HTTPStatusCode = 403
	require.Nil(t, statementReadLimit(upstream, "account"))
}
