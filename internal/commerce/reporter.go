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
		receipt, retry, err := sendStatement(ctx, client, destination, key, body)
		if err == nil && !reporterReceiptMatches(statement, receipt) {
			return nil, errors.New("the receiver acknowledgement does not match the submitted statement")
		}
		if !retry || attempt == 2 || ctx.Err() != nil {
			return receipt, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Duration(attempt+1) * time.Second):
		}
	}
}

func sendStatement(ctx context.Context, client *http.Client, destination string, key ed25519.PrivateKey, body []byte) (*v1.CommerceReporterReceipt, bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, destination, bytes.NewReader(body))
	if err != nil {
		return nil, false, errors.New("could not construct the signed statement request")
	}
	issued := strconv.FormatInt(time.Now().Unix(), 10)
	message := fmt.Sprintf("omega-commerce-reporter-v1\nPOST\n%s\n%s\n%x", destination, issued, sha256.Sum256(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Omega-Issued-At", issued)
	req.Header.Set("X-Omega-Signature", base64.RawURLEncoding.EncodeToString(ed25519.Sign(key, []byte(message))))
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
	return receipt, false, nil
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
