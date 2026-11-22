package commerce

import (
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/stripe/stripe-go/v87"
)

// StatementReadLimit carries only recognized scheduling information. Raw Stripe
// errors can contain portions of a credential or a private sandbox claim URL.
type StatementReadLimit struct {
	Read    string
	Reason  string
	RetryAt time.Time
}

func (l *StatementReadLimit) Error() string { return ErrStatementRateLimited.Error() }
func (l *StatementReadLimit) Unwrap() error { return ErrStatementRateLimited }

func statementReadLimit(err error, read string) *StatementReadLimit {
	var provider *stripe.Error
	if !errors.As(err, &provider) || provider.HTTPStatusCode != http.StatusTooManyRequests || provider.Code == stripe.ErrorCodeLockTimeout {
		return nil
	}
	limit := &StatementReadLimit{Read: read}
	if response := provider.LastResponse; response != nil {
		switch reason := response.Header.Get("Stripe-Rate-Limited-Reason"); reason {
		case "global-rate", "global-concurrency", "endpoint-rate", "endpoint-concurrency", "resource-specific":
			limit.Reason = reason
		}
		limit.RetryAt = providerRetryTime(response.Header.Get("Retry-After"), time.Now().UTC())
	}
	message := strings.ToLower(provider.Msg)
	if limit.Reason == "" && strings.Contains(message, "sandbox") && strings.Contains(message, "rate limit") &&
		(strings.Contains(message, "unclaimed") || strings.Contains(message, "claim the") || strings.Contains(message, "claim your")) {
		limit.Reason = "sandbox-quota"
	}
	return limit
}

func providerRetryTime(value string, now time.Time) time.Time {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}
	}
	if strings.Trim(value, "0123456789") == "" {
		seconds, err := strconv.ParseUint(value, 10, 64)
		last := time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC)
		if err != nil || seconds >= uint64(last.Unix()-now.Unix()) {
			return last
		}
		return time.Unix(now.Unix()+int64(seconds), int64(now.Nanosecond())).UTC()
	}
	at, err := http.ParseTime(value)
	if err == nil && at.After(now) {
		return at.UTC()
	}
	return time.Time{}
}
