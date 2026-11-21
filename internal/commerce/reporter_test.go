package commerce

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
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
)

func TestReporterSignsAndRetriesExactlyTheExportedBytes(t *testing.T) {
	public, key, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	statement := &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", TestMode: true, Coverage: "empty", ProductId: "product", FromDay: "2026-11-01", ThroughDay: "2026-11-21", VerifiedAt: "2026-11-21T02:00:00.000Z"}
	body, err := StatementJSON(statement)
	require.NoError(t, err)
	var calls atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "POST", r.Method)
		assert.Equal(t, "application/json", r.Header.Get("Content-Type"))
		got, readErr := io.ReadAll(r.Body)
		assert.NoError(t, readErr)
		assert.Equal(t, body, got)
		issued := r.Header.Get("X-Omega-Issued-At")
		unix, parseErr := strconv.ParseInt(issued, 10, 64)
		assert.NoError(t, parseErr)
		assert.InDelta(t, time.Now().Unix(), unix, 5)
		destination := "https://" + r.Host + r.URL.EscapedPath()
		sig, parseErr := base64.RawURLEncoding.Strict().DecodeString(r.Header.Get("X-Omega-Signature"))
		assert.NoError(t, parseErr)
		message := fmt.Sprintf("omega-commerce-reporter-v1\nPOST\n%s\n%s\n%x", destination, issued, sha256.Sum256(body))
		assert.True(t, ed25519.Verify(public, []byte(message), sig))
		assert.False(t, ed25519.Verify(public, []byte(message+"\n"), sig))
		if calls.Add(1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_, _ = io.WriteString(w, `{"outcome":"unchanged","statementId":"product/79738878984040999999999/2026-11-01/2026-11-21","checkedAt":"2026-11-21T02:00:00.000Z"}`)
	}))
	defer server.Close()
	original := http.DefaultTransport
	http.DefaultTransport = server.Client().Transport
	t.Cleanup(func() { http.DefaultTransport = original })
	receipt, err := SubmitStatement(t.Context(), server.URL+"/statement", key, statement)
	require.NoError(t, err)
	require.Equal(t, "unchanged", receipt.Outcome)
	require.EqualValues(t, 2, calls.Load())
}

func TestReporterRejectsRedirectsAndPrivateErrorBodies(t *testing.T) {
	_, key, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	statement := &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", TestMode: true}
	var hits, mode atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect-target" {
			hits.Add(1)
			return
		}
		switch mode.Load() {
		case 0:
			http.Redirect(w, r, "/redirect-target", http.StatusTemporaryRedirect)
		case 1:
			http.Error(w, "never display private source material", http.StatusForbidden)
		case 2:
			_, _ = io.Copy(w, bytes.NewReader(bytes.Repeat([]byte("x"), 3000)))
		case 3:
			_, _ = io.WriteString(w, `{"outcome":"saved","statementId":"has\ncontrols","checkedAt":"bad"}`)
		}
	}))
	defer server.Close()
	orig := http.DefaultTransport
	http.DefaultTransport = server.Client().Transport
	t.Cleanup(func() { http.DefaultTransport = orig })
	for i := int32(0); i < 4; i++ {
		mode.Store(i)
		_, err = SubmitStatement(t.Context(), server.URL+"/send", key, statement)
		require.Error(t, err)
		require.NotContains(t, err.Error(), "private source material")
		require.NotContains(t, err.Error(), "controls")
	}
	require.Zero(t, hits.Load())
	_, err = SubmitStatement(t.Context(), strings.Replace(server.URL, "https:", "http:", 1)+"/send", key, statement)
	require.Error(t, err)
	statement.TestMode = false
	_, err = SubmitStatement(t.Context(), server.URL+"/send", key, statement)
	require.Error(t, err)
}

func TestReporterReceiptMustMatchSubmittedWindowAndVerificationTime(t *testing.T) {
	const checked = "2026-11-21T02:00:00.000Z"
	const earlier = "79738878984040999999999"
	const exact = "79738878979999999999999"
	const future = "79738878979998999999999"
	const period = "/2026-11-01/2026-11-21"
	statement := &v1.CommerceStatement{ProductId: "product", FromDay: "2026-11-01", ThroughDay: "2026-11-21", VerifiedAt: checked}
	for _, tc := range []struct {
		name, outcome, id, at string
		valid                 bool
	}{
		{"saved exact", "saved", "product/" + exact + period, checked, true},
		{"unchanged exact replay", "unchanged", "product/" + exact + period, checked, true},
		{"unchanged prior", "unchanged", "product/" + earlier + period, checked, true},
		{"changed check time", "unchanged", "product/" + earlier + period, "2026-11-21T01:59:59Z", false},
		{"saved old source", "saved", "product/" + earlier + period, checked, false},
		{"future checkpoint", "unchanged", "product/" + future + period, checked, false},
		{"other product", "saved", "else/" + exact + period, checked, false},
		{"other window", "saved", "product/" + exact + "/2026-11-02/2026-11-21", checked, false},
		{"malformed descending digits", "unchanged", "product/79738878000000999999999" + period, checked, false},
		{"short descending digits", "saved", "product/123" + period, checked, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.valid, reporterReceiptMatches(statement, &v1.CommerceReporterReceipt{Outcome: tc.outcome, StatementId: tc.id, CheckedAt: tc.at}))
		})
	}
}
