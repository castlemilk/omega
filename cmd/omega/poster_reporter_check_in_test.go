package main

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
)

func TestReporterRefusesBeforeOpeningCredentialsAndConcurrentWakeIsQuiet(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "reporter")
	key, err := reporterKey(dir, true)
	require.NoError(t, err)
	var probes atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/api/reporters/signal-studies/check-in", r.URL.Path)
		probes.Add(1)
		http.Error(w, "private remote message", http.StatusForbidden)
	}))
	defer server.Close()
	target, err := url.Parse(server.URL)
	require.NoError(t, err)
	orig := http.DefaultTransport
	http.DefaultTransport = statementTestTransport{target, server.Client().Transport}
	t.Cleanup(func() { http.DefaultTransport = orig })
	run := func() error {
		cmd := posterReporterCommand()
		cmd.SilenceUsage = true
		cmd.SetErr(io.Discard)
		cmd.SetOut(io.Discard)
		cmd.SetArgs([]string{"--directory", dir, "run", "--scheduled", "--days", "1"})
		return cmd.ExecuteContext(t.Context())
	}
	// There is deliberately no source.env. A read before authority would produce a file error.
	err = run()
	require.ErrorContains(t, err, "HTTP 403")
	require.NotContains(t, err.Error(), "source")
	require.NotContains(t, err.Error(), "private remote message")
	s := localReporterState(dir, key)
	status, err := s.status(time.Now())
	require.NoError(t, err)
	require.Equal(t, "unconfirmed", status.CheckInOutcome)
	require.Empty(t, status.AttemptAt)
	require.Nil(t, status.LastReceipt)
	at := time.Now()
	_, err = s.claim(at)
	require.NoError(t, err)
	require.NoError(t, run())
	require.EqualValues(t, 1, probes.Load())
	require.NoError(t, s.release(at))
}

func TestReporterCanReportAnExistingCooldownWithoutInventingItsRevision(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "legacy")
	key, err := reporterKey(dir, true)
	require.NoError(t, err)
	local := localReporterState(dir, key)
	now := time.Now().UTC()
	then, next := reporterStamp(now.Add(-time.Minute)), reporterStamp(now.Add(time.Hour))
	_, err = local.transact(func(s *v1.LocalReporterStatus) error {
		// These are the fields written by the previous Mac reporter.
		s.Outcome, s.AttemptAt, s.NextProviderReadAt = "recheck-rate-limited", then, next
		s.LastReceipt = &v1.CommerceReporterReceipt{StatementId: "earlier-real-receipt"}
		return nil
	})
	require.NoError(t, err)
	for _, expectation := range []uint32{0, 4} {
		checked := false
		receipt, err := runReporterCheck(t.Context(), local, "2026-11-20", "2026-11-20", func() time.Time { return now },
			func(_ context.Context, c *v1.ReporterCheckIn) (*v1.ReporterCheckInReceipt, error) {
				checked = true
				require.Equal(t, expectation, c.ExpectedConnectionRevision)
				require.Equal(t, "provider-wait", c.Activity)
				require.Equal(t, then, c.AttemptAt)
				require.Equal(t, next, c.NextReadAt)
				require.True(t, c.Recheck)
				require.Empty(t, c.LimitReason)
				return &v1.ReporterCheckInReceipt{BusinessId: c.BusinessId, ProductId: c.ProductId, CheckedInAt: c.CheckedInAt, ConnectionRevision: 4}, nil
			}, func(context.Context, uint32, func(context.Context, uint32) error) (*v1.CommerceReporterReceipt, error) {
				t.Fatal("a cooldown opened the provider source")
				return nil, nil
			})
		require.ErrorIs(t, err, commerce.ErrStatementRateLimited)
		require.Nil(t, receipt)
		require.True(t, checked)
		now = now.Add(time.Minute)
	}
	s, err := local.status(now)
	require.NoError(t, err)
	require.Equal(t, "earlier-real-receipt", s.LastReceipt.StatementId)
}

func TestReporterGenerationAndProviderWaitAcrossRealTLSWakes(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "paired")
	key, err := reporterKey(dir, true)
	require.NoError(t, err)
	public := key.Public().(ed25519.PublicKey)
	const from, through, earlier = "2026-11-22", "2026-11-22", "2026-11-20"
	current := time.Date(2026, 11, 22, 11, 0, 0, 123_000_000, time.UTC)
	revision := atomic.Uint32{}
	revision.Store(7)
	var reconnectAfterOrdinary, rejectWait, limitHistory atomic.Bool
	var primaryReads, historicalReads, normalSends, historicalSends atomic.Int32
	checks := make(chan *v1.ReporterCheckIn, 32)
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		body, e := io.ReadAll(r.Body)
		assert.NoError(t, e)
		destination := "https://" + r.Host + r.URL.EscapedPath()
		issued := r.Header.Get("X-Omega-Issued-At")
		signature, e := base64.RawURLEncoding.Strict().DecodeString(r.Header.Get("X-Omega-Signature"))
		assert.NoError(t, e)
		if r.URL.Path == "/check-in" {
			msg := fmt.Sprintf("omega-commerce-reporter-check-in-v1\nPOST\n%s\n%s\n%x", destination, issued, sha256.Sum256(body))
			assert.True(t, ed25519.Verify(public, []byte(msg), signature))
			check := new(v1.ReporterCheckIn)
			assert.NoError(t, protojson.Unmarshal(body, check))
			checks <- check
			if (check.ExpectedConnectionRevision != 0 && check.ExpectedConnectionRevision != revision.Load()) || (check.Activity == "provider-wait" && rejectWait.Load()) {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"businessId": check.BusinessId, "productId": check.ProductId, "checkedInAt": check.CheckedInAt, "connectionRevision": revision.Load()})
			return
		}
		assert.Equal(t, "/statement", r.URL.Path)
		mode := r.Header.Get("X-Omega-Report-Recovery")
		gen := r.Header.Get("X-Omega-Connection-Revision")
		assert.Equal(t, strconv.FormatUint(uint64(revision.Load()), 10), gen)
		purpose := "omega-commerce-reporter-v1"
		if mode == "recheck-v1" {
			purpose = "omega-commerce-reporter-recheck-v1"
			historicalSends.Add(1)
		} else {
			normalSends.Add(1)
			w.Header().Set("X-Omega-Recheck-From", earlier)
			w.Header().Set("X-Omega-Recheck-Through", earlier)
		}
		msg := fmt.Sprintf("%s\nPOST\n%s\n%s\n%x\n%s", purpose, destination, issued, sha256.Sum256(body), gen)
		assert.True(t, ed25519.Verify(public, []byte(msg), signature))
		statement := new(v1.CommerceStatement)
		assert.NoError(t, protojson.Unmarshal(body, statement))
		at, e := time.Parse(time.RFC3339Nano, statement.VerifiedAt)
		assert.NoError(t, e)
		desc := strings.Map(func(c rune) rune {
			if c == '.' {
				return -1
			}
			return '9' - (c - '0')
		}, at.UTC().Format("20060102150405.000000000"))
		id := strings.Join([]string{statement.ProductId, desc, statement.FromDay, statement.ThroughDay}, "/")
		if mode != "recheck-v1" && reconnectAfterOrdinary.CompareAndSwap(true, false) {
			revision.Add(1)
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"outcome": "saved", "checkedAt": statement.VerifiedAt, "statementId": id})
	}))
	defer server.Close()
	orig := http.DefaultTransport
	http.DefaultTransport = server.Client().Transport
	t.Cleanup(func() { http.DefaultTransport = orig })
	state := func() reporterState { return localReporterState(dir, key) }
	get := func() *v1.LocalReporterStatus { s, e := state().status(current); require.NoError(t, e); return s }
	connect := func(ctx context.Context, c *v1.ReporterCheckIn) (*v1.ReporterCheckInReceipt, error) {
		return commerce.CheckInReporter(ctx, server.URL+"/check-in", key, c)
	}
	window := func(a, b string) *v1.CommerceStatement {
		return &v1.CommerceStatement{BusinessId: posters.StudioBusinessID, ProductId: posters.StudioProductID, Schema: "omega.commerce-statement/v1", TestMode: true, Coverage: "empty", FromDay: a, ThroughDay: b, VerifiedAt: reporterStamp(current)}
	}
	send := func(ctx context.Context, gen uint32, renew func(context.Context, uint32) error) (*v1.CommerceReporterReceipt, error) {
		primaryReads.Add(1)
		return commerce.SubmitPairedStatement(ctx, server.URL+"/statement", key, window(from, through), gen, func(_ context.Context, a, b string) (*v1.CommerceStatement, error) {
			historicalReads.Add(1)
			if limitHistory.Load() {
				return nil, &commerce.StatementReadLimit{Read: "refunds", Reason: "sandbox-quota", ObservedAt: current, RetryAt: current.Add(3 * time.Hour)}
			}
			return window(a, b), nil
		}, renew)
	}
	run := func() (*v1.CommerceReporterReceipt, error) {
		return runReporterCheck(t.Context(), state(), from, through, func() time.Time { return current }, connect, send)
	}
	expect := func(activity string, gen uint32) *v1.ReporterCheckIn {
		t.Helper()
		require.NotEmpty(t, checks)
		c := <-checks
		require.Equal(t, activity, c.Activity)
		require.Equal(t, gen, c.ExpectedConnectionRevision)
		return c
	}

	reconnectAfterOrdinary.Store(true)
	first, e := run()
	require.ErrorContains(t, e, "HTTP 403")
	require.NotNil(t, first)
	require.EqualValues(t, 0, historicalReads.Load())
	require.Equal(t, "recheck-pending", get().Outcome)
	expect("checking", 0)
	expect("checking", 7)

	current = current.Add(time.Minute)
	limitHistory.Store(true)
	rejectWait.Store(true)
	second, e := run()
	require.ErrorContains(t, e, "HTTP 403")
	require.NotNil(t, second)
	var waiting *reporterWait
	require.False(t, errors.As(e, &waiting))
	saved := get()
	require.Equal(t, second.StatementId, saved.LastReceipt.StatementId)
	require.Equal(t, "recheck-rate-limited", saved.Outcome)
	require.Equal(t, "unconfirmed", saved.CheckInOutcome)
	require.Equal(t, uint32(8), saved.LimitConnectionRevision)
	expect("checking", 0)
	expect("checking", 8)
	report := expect("provider-wait", 8)
	require.True(t, report.Recheck)
	require.Equal(t, "sandbox-quota", report.LimitReason)
	require.Equal(t, saved.LimitedAttemptAt, report.AttemptAt)
	require.Equal(t, saved.NextProviderReadAt, report.NextReadAt)

	current = current.Add(5 * time.Minute)
	rejectWait.Store(false)
	r, e := run()
	require.Nil(t, r)
	require.ErrorAs(t, e, &waiting)
	c := expect("provider-wait", 8)
	require.Equal(t, report.AttemptAt, c.AttemptAt)
	require.Equal(t, report.NextReadAt, c.NextReadAt)
	revision.Store(9)
	current = current.Add(time.Minute)
	r, e = run()
	require.Nil(t, r)
	require.ErrorContains(t, e, "HTTP 403")
	expect("provider-wait", 8)
	require.Equal(t, saved.NextProviderReadAt, get().NextProviderReadAt)
	require.Equal(t, second.StatementId, get().LastReceipt.StatementId)
	require.EqualValues(t, 2, primaryReads.Load())
	require.EqualValues(t, 1, historicalReads.Load())
	require.Zero(t, historicalSends.Load())

	current, e = time.Parse(time.RFC3339Nano, saved.NextProviderReadAt)
	require.NoError(t, e)
	limitHistory.Store(false)
	last, e := run()
	require.NoError(t, e)
	require.NotNil(t, last)
	expect("checking", 0)
	expect("checking", 9)
	require.Empty(t, checks)
	require.Equal(t, "acknowledged", get().Outcome)
	require.Empty(t, get().NextProviderReadAt)
	require.EqualValues(t, 3, normalSends.Load())
	require.EqualValues(t, 1, historicalSends.Load())
	require.Equal(t, last.StatementId, get().LastReceipt.StatementId)
}
