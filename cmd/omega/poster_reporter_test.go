package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
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

func TestReporterKeysAndSourcePermissions(t *testing.T) {
	if os.Geteuid() < 0 {
		t.Skip("requires POSIX file ownership")
	}
	dir := filepath.Join(t.TempDir(), "private")
	var keys [6]ed25519.PrivateKey
	var errs [6]error
	var group sync.WaitGroup
	for i := range keys {
		group.Go(func() { keys[i], errs[i] = reporterKey(dir, true) })
	}
	group.Wait()
	for i := range keys {
		require.NoError(t, errs[i])
		require.True(t, bytes.Equal(keys[0], keys[i]))
	}
	path := filepath.Join(dir, "signing.seed")
	st, err := os.Stat(path)
	require.NoError(t, err)
	require.Equal(t, os.FileMode(0600), st.Mode().Perm())
	require.EqualValues(t, 32, st.Size())
	require.NoError(t, os.Chmod(path, 0644)) // #nosec G302 -- negative test for an exposed temporary test key
	_, err = reporterKey(dir, true)
	require.Error(t, err)
	require.NoError(t, os.Remove(path))
	require.NoError(t, os.Symlink(filepath.Join(dir, "missing"), path))
	_, err = reporterKey(dir, true)
	require.Error(t, err)
	config := filepath.Join(dir, "source.env")
	for _, tc := range []struct{ key, dsn string }{
		{"sk_live_fixture", "postgres://reader@127.0.0.1/posters"}, {"sk_test_fixture", "postgres://reader@db.example/posters"},
		{"sk_test_fixture", "postgres://reader@127.0.0.1/posters?host=db.example"},
	} {
		body := "OMEGA_POSTER_STRIPE_TEST_KEY=" + tc.key + "\nOMEGA_POSTER_COMMERCE_DATABASE_URL=" + tc.dsn + "\n"
		require.NoError(t, os.WriteFile(config, []byte(body), 0600))
		_, _, err = reporterConnection(config)
		require.Error(t, err)
		require.NotContains(t, err.Error(), tc.key)
		require.NotContains(t, err.Error(), tc.dsn)
	}
}

func TestReporterPeriodAndMacSchedule(t *testing.T) {
	now := time.Date(2026, 1, 1, 2, 0, 0, 0, time.FixedZone("local", 11*3600))
	from, through, err := reporterWindow("", "", 30, false, now)
	require.NoError(t, err)
	require.Equal(t, "2025-12-02", from)
	require.Equal(t, "2025-12-31", through)
	_, _, err = reporterWindow(from, through, 30, true, now)
	require.Error(t, err)
	_, _, err = reporterWindow(from, "", 30, false, now)
	require.Error(t, err)
	_, _, err = reporterWindow("", "", 367, true, now)
	require.Error(t, err)
	dir := filepath.Join(t.TempDir(), "state & application")
	plist := reporterAgentPlist(dir, filepath.Join(dir, "source.env"), "/Applications/Omega & Co/omega", 30)
	require.Contains(t, string(plist), "<integer>300</integer>")
	require.Contains(t, string(plist), "<string>--scheduled</string>")
	require.Contains(t, string(plist), "Omega &amp; Co")
	require.NotContains(t, string(plist), "OMEGA_POSTER_STRIPE_TEST_KEY")
	require.NotContains(t, string(plist), "EnvironmentVariables")
	if _, err = exec.LookPath("plutil"); err == nil {
		path := filepath.Join(t.TempDir(), "reporter.plist")
		require.NoError(t, os.WriteFile(path, plist, 0600))
		result, err := exec.Command("plutil", "-lint", "--", path).CombinedOutput() // #nosec G204 -- local plist validation on a test-owned path
		require.NoError(t, err, string(result))
	}
}

// Go's normal poster CLI already seeded a genuine edition in isolated
// PostgreSQL and bound a local fixture for every Stripe read.
func checkPosterReporterCommand(t *testing.T, dsn, day, orderID string, limitAccount *atomic.Bool, accountReads *atomic.Int32) {
	t.Helper()
	if os.Geteuid() < 0 {
		t.Skip("requires POSIX file ownership")
	}
	dir := filepath.Join(t.TempDir(), "reporter")
	run := func(args ...string) ([]byte, error) {
		var buf bytes.Buffer
		rootCmd.SetOut(&buf)
		rootCmd.SetArgs(append([]string{"posters", "reporter", "--directory", dir}, args...))
		err := rootCmd.ExecuteContext(context.Background())
		return buf.Bytes(), err
	}
	keyText, err := run("init")
	require.NoError(t, err)
	public, err := base64.RawURLEncoding.Strict().DecodeString(strings.TrimSuffix(string(keyText), "\n"))
	require.NoError(t, err)
	require.Len(t, public, ed25519.PublicKeySize)
	config := filepath.Join(dir, "source.env")
	data := "OMEGA_POSTER_STRIPE_TEST_KEY=sk_test_fixture\nOMEGA_POSTER_COMMERCE_DATABASE_URL=" + dsn + "\n"
	require.NoError(t, os.WriteFile(config, []byte(data), 0600)) // #nosec G703 -- path is inside t.TempDir
	_, db, err := reporterConnection(config)
	require.NoError(t, err)
	var readOnly string
	require.NoError(t, db.QueryRow("SHOW default_transaction_read_only").Scan(&readOnly))
	require.Equal(t, "on", readOnly)
	require.NoError(t, db.Close())
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "unused")
	t.Setenv("OMEGA_POSTER_COMMERCE_DATABASE_URL", "unused")
	t.Setenv("OMEGA_POSTER_STRIPE_SIGNING_SECRET", "")
	rechecked := make(chan string, 4)
	activities := make(chan *v1.ReporterCheckIn, 32)
	var received atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		assert.Equal(t, "POST", r.Method)
		raw, readErr := io.ReadAll(r.Body)
		assert.NoError(t, readErr)
		sig, decodeErr := base64.RawURLEncoding.DecodeString(r.Header.Get("X-Omega-Signature"))
		assert.NoError(t, decodeErr)
		if r.URL.Path == "/api/reporters/signal-studies/check-in" {
			msg := fmt.Sprintf("omega-commerce-reporter-check-in-v1\nPOST\n%s\n%s\n%x", posterReporterCheckInEndpoint, r.Header.Get("X-Omega-Issued-At"), sha256.Sum256(raw))
			assert.True(t, ed25519.Verify(public, []byte(msg), sig))
			check := new(v1.ReporterCheckIn)
			assert.NoError(t, protojson.Unmarshal(raw, check))
			assert.Equal(t, posters.StudioBusinessID, check.BusinessId)
			assert.Equal(t, posters.StudioProductID, check.ProductId)
			activities <- check
			_ = json.NewEncoder(w).Encode(map[string]any{"businessId": check.BusinessId, "productId": check.ProductId, "checkedInAt": check.CheckedInAt, "connectionRevision": 7})
			return
		}
		received.Add(1)
		assert.Equal(t, "/api/reporters/signal-studies/statement", r.URL.Path)
		assert.Equal(t, "7", r.Header.Get("X-Omega-Connection-Revision"))
		mode := r.Header.Get("X-Omega-Report-Recovery")
		purpose := "omega-commerce-reporter-v1"
		if mode == "recheck-v1" {
			purpose = "omega-commerce-reporter-recheck-v1"
		}
		message := fmt.Sprintf("%s\nPOST\n%s\n%s\n%x\n7", purpose, posterReporterEndpoint, r.Header.Get("X-Omega-Issued-At"), sha256.Sum256(raw))
		assert.True(t, ed25519.Verify(public, []byte(message), sig))
		var statement v1.CommerceStatement
		assert.NoError(t, protojson.Unmarshal(raw, &statement))
		canonical, marshalErr := commerce.StatementJSON(&statement)
		assert.NoError(t, marshalErr)
		assert.Equal(t, canonical, raw)
		if mode == "1" {
			assert.Empty(t, statement.Orders)
			assert.Equal(t, "empty", statement.Coverage)
			assert.Equal(t, time.Now().UTC().Format(time.DateOnly), statement.FromDay)
		} else if assert.Len(t, statement.Orders, 1) {
			assert.Equal(t, day, statement.FromDay)
			assert.Equal(t, orderID, statement.Orders[0].OrderId)
			assert.EqualValues(t, 1200, statement.Orders[0].CapturedMinor.GetValue())
			assert.EqualValues(t, 300, statement.Orders[0].RefundedMinor.GetValue())
			assert.Len(t, statement.Orders[0].Movements, 2)
		}
		checked, parseErr := time.Parse(time.RFC3339Nano, statement.VerifiedAt)
		assert.NoError(t, parseErr)
		descending := strings.Map(func(r rune) rune {
			if r == '.' {
				return -1
			}
			return '9' - (r - '0')
		}, checked.UTC().Format("20060102150405.000000000"))
		// Fixed-date runs ignore hints, and a historical check may never chain
		// another provider read even when a receiver repeats the headers.
		w.Header().Set("X-Omega-Recheck-From", day)
		w.Header().Set("X-Omega-Recheck-Through", day)
		id := strings.Join([]string{statement.ProductId, descending, statement.FromDay, statement.ThroughDay}, "/")
		if mode == "recheck-v1" && len(statement.Orders) == 1 {
			rechecked <- statement.Orders[0].OrderId
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"outcome": "saved", "statementId": id, "checkedAt": statement.VerifiedAt})
	}))
	defer server.Close()
	target, err := url.Parse(server.URL)
	require.NoError(t, err)
	original := http.DefaultTransport
	http.DefaultTransport = statementTestTransport{target, server.Client().Transport}
	t.Cleanup(func() { http.DefaultTransport = original })
	body, err := run("run", "--from", day, "--through", day)
	require.NoError(t, err)
	var receipt v1.CommerceReporterReceipt
	require.NoError(t, protojson.Unmarshal(body, &receipt))
	require.Equal(t, "saved", receipt.Outcome)
	require.Contains(t, receipt.StatementId, "/"+day+"/"+day)

	// A scheduled process constructs a fresh command on each launch.
	rolling := posterReporterCommand()
	var output bytes.Buffer
	rolling.SetOut(&output)
	rolling.SetArgs([]string{"--directory", dir, "run", "--days", "1"})
	require.NoError(t, rolling.ExecuteContext(t.Context()))
	require.NoError(t, protojson.Unmarshal(output.Bytes(), &receipt))
	today := time.Now().UTC().Format(time.DateOnly)
	require.True(t, strings.HasSuffix(receipt.StatementId, "/"+today+"/"+today))
	require.Len(t, rechecked, 1)
	require.Equal(t, orderID, <-rechecked)
	for _, revision := range []uint32{0, 0, 7} {
		require.NotEmpty(t, activities)
		check := <-activities
		require.Equal(t, "checking", check.Activity)
		require.Equal(t, revision, check.ExpectedConnectionRevision)
	}

	// A distinct process reads the same private state at every scheduled wake.
	// Advance only the scheduler clock. Stripe, Postgres, signing and the
	// receiver use their real fixture endpoints and independently verify bytes.
	now := time.Now().UTC()
	wake := func(args ...string) ([]byte, error) {
		started := time.Now()
		cmd := posterReporterCommandWithClock(func() time.Time {
			if now.After(started) {
				return now.Add(time.Since(started))
			}
			return time.Now().UTC()
		})
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetErr(io.Discard)
		cmd.SilenceUsage = true
		cmd.SetArgs(append([]string{"--directory", dir}, args...))
		err := cmd.ExecuteContext(t.Context())
		return out.Bytes(), err
	}
	readStatus := func() *v1.LocalReporterStatus {
		raw, err := wake("status", "--json")
		require.NoError(t, err)
		require.NotContains(t, string(raw), "private provider detail")
		var state v1.LocalReporterStatus
		require.NoError(t, protojson.Unmarshal(raw, &state))
		return &state
	}
	limitAccount.Store(true)
	t.Cleanup(func() { limitAccount.Store(false) })
	beforeRead, beforeSend := accountReads.Load(), received.Load()
	_, err = wake("run", "--days", "1")
	require.ErrorIs(t, err, commerce.ErrStatementRateLimited)
	state := readStatus()
	require.Equal(t, "rate-limited", state.Outcome)
	require.Equal(t, "account", state.LimitedRead)
	require.Equal(t, "endpoint-rate", state.LimitReason)
	require.Equal(t, receipt.CheckedAt, state.LastReceipt.CheckedAt)
	require.Equal(t, today, state.ReceiptThroughDay)
	next, err := time.Parse(time.RFC3339Nano, state.NextProviderReadAt)
	require.NoError(t, err)
	require.Equal(t, state.ProviderRetryAt, state.NextProviderReadAt)
	require.WithinDuration(t, now.Add(2*time.Hour), next, 30*time.Second)
	now = next.Add(-time.Second)
	body, err = wake("run", "--scheduled", "--days", "1")
	require.NoError(t, err)
	require.Empty(t, body)
	_, err = wake("run", "--from", day, "--through", day)
	require.ErrorIs(t, err, commerce.ErrStatementRateLimited)
	require.Equal(t, state.AttemptAt, readStatus().AttemptAt)
	require.Equal(t, beforeRead+1, accountReads.Load())
	require.Equal(t, beforeSend, received.Load())
	require.Equal(t, "checking", (<-activities).Activity)
	for range 3 {
		require.NotEmpty(t, activities)
		check := <-activities
		require.Equal(t, "provider-wait", check.Activity)
		require.Equal(t, uint32(7), check.ExpectedConnectionRevision)
		require.Equal(t, state.LimitedAttemptAt, check.AttemptAt)
		require.Equal(t, state.NextProviderReadAt, check.NextReadAt)
		require.Equal(t, "rate-limit", check.LimitReason)
		require.False(t, check.Recheck)
	}
	limitAccount.Store(false)
	now = next
	body, err = wake("run", "--from", day, "--through", day)
	require.NoError(t, err)
	require.NoError(t, protojson.Unmarshal(body, &receipt))
	recovered := readStatus()
	require.Equal(t, "acknowledged", recovered.Outcome)
	require.Equal(t, receipt.CheckedAt, recovered.LastReceipt.CheckedAt)
	require.Equal(t, day, recovered.ReceiptThroughDay)
	require.Empty(t, recovered.NextProviderReadAt)
	require.Zero(t, recovered.ConsecutiveLimits)
	require.Equal(t, beforeRead+2, accountReads.Load())
	require.Equal(t, beforeSend+1, received.Load())
}

func TestReporterScheduleInstallUpdateDisableAndResume(t *testing.T) {
	const domain = "gui/502"
	const target = domain + "/" + reporterAgentLabel
	agents := filepath.Join(t.TempDir(), "LaunchAgents")
	var calls []string
	loaded, enabled := false, false
	ctl := func(_ context.Context, args ...string) error {
		calls = append(calls, args[0])
		switch args[0] {
		case "print":
			require.Equal(t, []string{"print", target}, args)
			if !loaded {
				return os.ErrNotExist
			}
		case "enable", "disable":
			require.Equal(t, target, args[1])
			enabled = args[0] == "enable"
		case "bootstrap":
			require.True(t, enabled)
			require.Equal(t, []string{"bootstrap", domain, filepath.Join(agents, reporterAgentLabel+".plist")}, args)
			loaded = true
		case "bootout":
			require.True(t, loaded)
			require.Equal(t, target, args[1])
			loaded = false
		default:
			t.Fatalf("unexpected launchctl call %s", args[0])
		}
		return nil
	}
	install := func(days int) {
		t.Helper()
		p := reporterAgentPlist("/private/reporter", "/private/reporter/source.env", "/bin/omega", days)
		require.NoError(t, configureReporterAgent(t.Context(), ctl, domain, target, agents, p))
		saved, err := os.ReadFile(filepath.Join(agents, reporterAgentLabel+".plist")) // #nosec G304 -- fixed basename under t.TempDir
		require.NoError(t, err)
		require.Equal(t, p, saved)
	}
	install(30)
	require.True(t, loaded)
	require.Equal(t, []string{"print", "enable", "bootstrap"}, calls)
	calls = nil
	install(30)
	require.Equal(t, []string{"print", "enable"}, calls)
	calls = nil
	install(7)
	require.Equal(t, []string{"print", "bootout", "enable", "bootstrap"}, calls)
	require.NoError(t, stopReporterAgent(t.Context(), ctl, target))
	require.False(t, loaded)
	require.False(t, enabled)
	require.NoError(t, stopReporterAgent(t.Context(), ctl, target))
	require.False(t, enabled)
	install(7)
	require.True(t, loaded)
	require.True(t, enabled)
}
