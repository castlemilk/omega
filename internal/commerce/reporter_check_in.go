package commerce

import (
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

var reporterUTC = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$`)

func reporterTime(value string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339Nano, value)
	return t, err == nil && reporterUTC.MatchString(value)
}

// CheckInReporter authorizes only the supplied operation. A receipt must echo
// the exact scoped request and identify an active, positive connection revision.
func CheckInReporter(ctx context.Context, destination string, key ed25519.PrivateKey, check *v1.ReporterCheckIn) (*v1.ReporterCheckInReceipt, error) {
	if !validReporterDestination(destination, key) || strings.Contains(destination, "#") || check.GetBusinessId() == "" || check.GetProductId() == "" {
		return nil, errors.New("invalid reporter check-in destination, signing key or scope")
	}
	when, valid := reporterTime(check.CheckedInAt)
	if !valid {
		return nil, errors.New("invalid reporter check-in time")
	}
	switch check.Activity {
	case "checking":
		if check.AttemptAt != "" || check.NextReadAt != "" || check.LimitReason != "" || check.Recheck {
			return nil, errors.New("a checking activity cannot include a provider wait")
		}
	case "provider-wait":
		tried, ok := reporterTime(check.AttemptAt)
		next, okNext := reporterTime(check.NextReadAt)
		if !ok || !okNext || tried.After(when) || !next.After(tried) ||
			(check.LimitReason != "" && check.LimitReason != "sandbox-quota" && check.LimitReason != "rate-limit") {
			return nil, errors.New("invalid reporter provider-wait evidence")
		}
	default:
		return nil, errors.New("invalid reporter check-in activity")
	}
	body, err := protojson.Marshal(check)
	if err != nil {
		return nil, errors.New("could not encode reporter check-in")
	}
	req, err := signedReporterRequest(ctx, destination, "omega-commerce-reporter-check-in-v1", key, body, when, 0)
	if err != nil {
		return nil, err
	}
	response, err := reporterHTTPClient().Do(req)
	if err != nil {
		return nil, errors.New("could not reach Studio to confirm the reporter connection")
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Studio did not confirm the reporter connection (HTTP %d)", response.StatusCode)
	}
	const limit = 2048
	raw, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	receipt := new(v1.ReporterCheckInReceipt)
	var fields map[string]json.RawMessage
	var revision uint32
	if err != nil || len(raw) > limit || protojson.Unmarshal(raw, receipt) != nil || json.Unmarshal(raw, &fields) != nil || len(fields) != 4 ||
		fields["businessId"] == nil || fields["productId"] == nil || fields["checkedInAt"] == nil || json.Unmarshal(fields["connectionRevision"], &revision) != nil ||
		revision == 0 || receipt.ConnectionRevision != revision || receipt.BusinessId != check.BusinessId || receipt.ProductId != check.ProductId ||
		receipt.CheckedInAt != check.CheckedInAt || (check.ExpectedConnectionRevision != 0 && revision != check.ExpectedConnectionRevision) {
		return nil, errors.New("Studio did not confirm the same scope, check time and connection revision")
	}
	return receipt, nil
}
