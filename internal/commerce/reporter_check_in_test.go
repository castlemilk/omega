package commerce

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
)

func TestReporterCheckInRequiresExactScopeTimeAndGeneration(t *testing.T) {
	pub, key, err := ed25519.GenerateKey(nil)
	require.NoError(t, err)
	const stamp = "2026-11-22T00:01:02.123456789Z"
	const good = `{"businessId":"business","productId":"product","checkedInAt":"` + stamp + `","connectionRevision":17}`
	var answer atomic.Value
	answer.Store(good)
	var hits atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		assert.Equal(t, "POST", r.Method)
		assert.Equal(t, "application/json", r.Header.Get("Content-Type"))
		assert.Empty(t, r.Header.Get("X-Omega-Connection-Revision"))
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		issued := r.Header.Get("X-Omega-Issued-At")
		at, _ := time.Parse(time.RFC3339Nano, stamp)
		assert.Equal(t, strconv.FormatInt(at.Unix(), 10), issued)
		sig, err := base64.RawURLEncoding.Strict().DecodeString(r.Header.Get("X-Omega-Signature"))
		assert.NoError(t, err)
		message := fmt.Sprintf("omega-commerce-reporter-check-in-v1\nPOST\nhttps://%s%s\n%s\n%x", r.Host, r.URL.Path, issued, sha256.Sum256(body))
		assert.True(t, ed25519.Verify(pub, []byte(message), sig))
		var request v1.ReporterCheckIn
		assert.NoError(t, protojson.Unmarshal(body, &request))
		assert.Equal(t, uint32(17), request.ExpectedConnectionRevision)
		switch value := answer.Load().(string); value {
		case "redirect":
			http.Redirect(w, r, "/elsewhere", http.StatusTemporaryRedirect)
		case "denied":
			http.Error(w, "secret upstream material", 403)
		default:
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, value)
		}
	}))
	defer server.Close()
	orig := http.DefaultTransport
	http.DefaultTransport = server.Client().Transport
	t.Cleanup(func() { http.DefaultTransport = orig })
	check := &v1.ReporterCheckIn{BusinessId: "business", ProductId: "product", CheckedInAt: stamp, Activity: "checking", ExpectedConnectionRevision: 17}
	url := server.URL + "/check-in"
	receipt, err := CheckInReporter(t.Context(), url, key, check)
	require.NoError(t, err)
	require.Equal(t, uint32(17), receipt.ConnectionRevision)
	for _, raw := range []string{strings.Replace(good, "business\"", "other\"", 1), strings.Replace(good, "product\"", "other\"", 1),
		strings.Replace(good, ".123456789Z", "Z", 1), strings.Replace(good, ":17", ":18", 1), strings.Replace(good, ":17", ":0", 1),
		strings.Replace(good, ":17", ":\"17\"", 1), strings.Replace(good, ":17", ":4294967296", 1),
		strings.Replace(good, "businessId", "business_id", 1), strings.Replace(good, ":17", ":17,\"connectionRevision\":17", 1),
		strings.Replace(good, ":17", ":17,\"unknown\":1", 1), "{}", strings.Repeat("X", 2050), "denied", "redirect"} {
		answer.Store(raw)
		before := hits.Load()
		_, err = CheckInReporter(t.Context(), url, key, check)
		require.Error(t, err)
		require.NotContains(t, err.Error(), "secret")
		require.Equal(t, before+1, hits.Load())
	}
	before := hits.Load()
	for _, dst := range []string{strings.Replace(url, "https:", "http:", 1), url + "?q=private", url + "#", strings.Replace(url, "//", "//owner@", 1)} {
		_, err := CheckInReporter(t.Context(), dst, key, check)
		require.Error(t, err)
	}
	for _, bad := range []string{"private provider message", "global-concurrency"} {
		wait := &v1.ReporterCheckIn{BusinessId: "business", ProductId: "product", CheckedInAt: stamp, Activity: "provider-wait",
			AttemptAt: "2026-11-22T00:00:00Z", NextReadAt: "2026-11-22T01:00:00Z", LimitReason: bad}
		_, err := CheckInReporter(t.Context(), url, key, wait)
		require.Error(t, err)
	}
	require.Equal(t, before, hits.Load())
	// The new path must never become the legacy unbound form, including in a caller error.
	_, err = SubmitPairedStatement(context.Background(), url, key, nil, 0, nil, nil)
	require.Error(t, err)
	require.Equal(t, before, hits.Load())
}

func TestPairedReporterCannotRetryARefusedGenerationAsLegacy(t *testing.T) {
	_, key, err := ed25519.GenerateKey(nil)
	require.NoError(t, err)
	const day, previous, checked = "2026-11-21", "2026-11-20", "2026-11-21T02:00:00.000Z"
	statement := func(d string) *v1.CommerceStatement {
		return &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", TestMode: true, Coverage: "empty", BusinessId: "business", ProductId: "product", FromDay: d, ThroughDay: d, VerifiedAt: checked}
	}
	var current, requests atomic.Uint32
	current.Store(5)
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		revision := r.Header.Get("X-Omega-Connection-Revision")
		assert.Equal(t, "4", revision)
		if revision != strconv.FormatUint(uint64(current.Load()), 10) {
			w.WriteHeader(http.StatusConflict)
			return
		}
		w.Header().Set("X-Omega-Recheck-From", previous)
		w.Header().Set("X-Omega-Recheck-Through", previous)
		_, _ = fmt.Fprintf(w, `{"outcome":"saved","statementId":"product/79738878979999999999999/%s/%s","checkedAt":"%s"}`, day, day, checked)
	}))
	defer server.Close()
	orig := http.DefaultTransport
	http.DefaultTransport = server.Client().Transport
	t.Cleanup(func() { http.DefaultTransport = orig })
	receipt, err := SubmitPairedStatement(t.Context(), server.URL+"/statement", key, statement(day), 4, nil, nil)
	require.Nil(t, receipt)
	require.ErrorContains(t, err, "409")
	require.EqualValues(t, 1, requests.Load())
	current.Store(4)
	renewed := false
	receipt, err = SubmitPairedStatement(t.Context(), server.URL+"/statement", key, statement(day), 4, func(_ context.Context, a, b string) (*v1.CommerceStatement, error) {
		require.True(t, renewed)
		current.Store(5) // Studio reconnects while the historical provider read is in flight.
		return statement(a), nil
	}, func(_ context.Context, revision uint32) error {
		require.Equal(t, current.Load(), revision)
		renewed = true
		return nil
	})
	require.NotNil(t, receipt)
	require.Equal(t, checked, receipt.CheckedAt)
	require.ErrorContains(t, err, "409")
	require.EqualValues(t, 3, requests.Load())
}
