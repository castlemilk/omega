package commerce

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

// SubmitStatement only sends evidence obtained by the test statement exporter.
// Each retry signs the same body; a lost acknowledgement may already be saved.
func SubmitStatement(ctx context.Context, destination string, key ed25519.PrivateKey, statement *v1.CommerceStatement) (*v1.CommerceReporterReceipt, error) {
	response, err := submitStatement(ctx, destination, key, statement, "")
	if err != nil {
		return nil, err
	}
	return response.receipt, nil
}

type statementResponse struct {
	receipt *v1.CommerceReporterReceipt
	headers http.Header
}

// SubmitRollingStatement lets Studio request one recheck of dates on which this
// connection previously reported partial coverage. A fixed-date send never
// negotiates further work. The normal receipt survives a failed follow-up.
func SubmitRollingStatement(ctx context.Context, destination string, key ed25519.PrivateKey, statement *v1.CommerceStatement,
	read func(context.Context, string, string) (*v1.CommerceStatement, error),
) (*v1.CommerceReporterReceipt, error) {
	response, err := submitStatement(ctx, destination, key, statement, "1")
	if err != nil {
		return nil, err
	}
	from, through := response.headers.Values("X-Omega-Recheck-From"), response.headers.Values("X-Omega-Recheck-Through")
	if len(from) == 0 && len(through) == 0 {
		return response.receipt, nil
	}
	if len(from) != 1 || len(through) != 1 || read == nil || !validRecheckWindow(statement, from[0], through[0]) {
		return response.receipt, errors.New("the reporting period was saved, but the requested recheck did not match an earlier reporting window")
	}
	previous, err := read(ctx, from[0], through[0])
	if err != nil {
		return response.receipt, fmt.Errorf("the reporting period was saved; its earlier dates still need verification: %w", err)
	}
	if previous == nil || previous.FromDay != from[0] || previous.ThroughDay != through[0] ||
		previous.BusinessId != statement.BusinessId || previous.ProductId != statement.ProductId {
		return response.receipt, errors.New("the reporting period was saved, but the recheck produced a different product or period")
	}
	if _, err := submitStatement(ctx, destination, key, previous, "recheck-v1"); err != nil {
		return response.receipt, fmt.Errorf("the reporting period was saved; the earlier statement was not acknowledged: %w", err)
	}
	return response.receipt, nil
}

func validRecheckWindow(statement *v1.CommerceStatement, from, through string) bool {
	now, err := time.Parse(time.RFC3339Nano, statement.VerifiedAt)
	if err != nil {
		return false
	}
	first, end, err := StatementWindow(from, through, now)
	start, stop, normalErr := StatementWindow(statement.FromDay, statement.ThroughDay, now)
	return statement.Coverage != "partial" && err == nil && normalErr == nil && first.Before(start) && !end.After(stop) && end.Sub(first) <= stop.Sub(start)
}

func submitStatement(ctx context.Context, destination string, key ed25519.PrivateKey, statement *v1.CommerceStatement, recoveryMode string) (*statementResponse, error) {
	target, err := url.Parse(destination)
	if err != nil || target.Scheme != "https" || target.Host == "" || target.Path == "" || target.User != nil ||
		target.RawQuery != "" || target.Fragment != "" || target.ForceQuery || len(key) != ed25519.PrivateKeySize {
		return nil, errors.New("invalid reporter destination or signing key")
	}
	if statement == nil || statement.Schema != "omega.commerce-statement/v1" || !statement.TestMode {
		return nil, errors.New("the reporter requires a test order statement")
	}
	body, err := StatementJSON(statement)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	for attempt := 0; ; attempt++ {
		response, retry, err := sendStatement(ctx, client, destination, key, body, recoveryMode)
		if err == nil && !reporterReceiptMatches(statement, response.receipt) {
			return nil, errors.New("the receiver acknowledgement does not match the submitted statement")
		}
		if !retry || attempt == 2 || ctx.Err() != nil {
			return response, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Duration(attempt+1) * time.Second):
		}
	}
}

func sendStatement(ctx context.Context, client *http.Client, destination string, key ed25519.PrivateKey, body []byte, recoveryMode string) (*statementResponse, bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, destination, bytes.NewReader(body))
	if err != nil {
		return nil, false, errors.New("could not construct the signed statement request")
	}
	issued := strconv.FormatInt(time.Now().Unix(), 10)
	purpose := "omega-commerce-reporter-v1"
	if recoveryMode == "recheck-v1" {
		purpose = "omega-commerce-reporter-recheck-v1"
	}
	message := fmt.Sprintf("%s\nPOST\n%s\n%s\n%x", purpose, destination, issued, sha256.Sum256(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Omega-Issued-At", issued)
	req.Header.Set("X-Omega-Signature", base64.RawURLEncoding.EncodeToString(ed25519.Sign(key, []byte(message))))
	if recoveryMode != "" {
		req.Header.Set("X-Omega-Report-Recovery", recoveryMode)
	}
	res, err := client.Do(req)
	if err != nil {
		return nil, true, errors.New("could not reach the statement receiver")
	}
	defer func() { _ = res.Body.Close() }()
	if res.StatusCode != http.StatusOK {
		retry := res.StatusCode == http.StatusRequestTimeout || res.StatusCode == http.StatusTooManyRequests || res.StatusCode >= 500
		return nil, retry, fmt.Errorf("the statement receiver returned HTTP %d", res.StatusCode)
	}
	const maxReceipt = 2048
	data, err := io.ReadAll(io.LimitReader(res.Body, maxReceipt+1))
	receipt := new(v1.CommerceReporterReceipt)
	if err != nil || len(data) > maxReceipt || protojson.Unmarshal(data, receipt) != nil ||
		(receipt.Outcome != "saved" && receipt.Outcome != "unchanged") {
		return nil, false, errors.New("the receiver did not confirm a valid statement receipt")
	}
	return &statementResponse{receipt: receipt, headers: res.Header}, false, nil
}

// A later observation may reuse the previous saved facts for this exact
// product and window. The check time still acknowledges this submission.
func reporterReceiptMatches(statement *v1.CommerceStatement, receipt *v1.CommerceReporterReceipt) bool {
	if receipt.CheckedAt != statement.VerifiedAt || !strings.HasSuffix(receipt.CheckedAt, "Z") {
		return false
	}
	verified, err := time.Parse(time.RFC3339Nano, statement.VerifiedAt)
	suffix, ok := strings.CutPrefix(receipt.StatementId, statement.ProductId+"/")
	parts := strings.Split(suffix, "/")
	if err != nil || !ok || statement.ProductId == "" || len(parts) != 3 || len(parts[0]) != 23 ||
		parts[1] != statement.FromDay || parts[2] != statement.ThroughDay {
		return false
	}
	// Studio encodes UTC as YYYYMMDDhhmmss plus nine fractional digits,
	// replacing each digit with its complement so newer rows sort first.
	stamp := []byte(parts[0])
	for i, c := range stamp {
		if c < '0' || c > '9' {
			return false
		}
		stamp[i] = '9' - (c - '0')
	}
	saved, err := time.Parse("20060102150405.000000000", string(stamp[:14])+"."+string(stamp[14:]))
	if err != nil || saved.Format(time.DateOnly) < statement.ThroughDay {
		return false
	}
	return (receipt.Outcome == "saved" && saved.Equal(verified)) ||
		(receipt.Outcome == "unchanged" && !saved.After(verified))
}
