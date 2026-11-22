package main

import (
	"crypto/ed25519"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/stretchr/testify/require"
)

func TestReporterLeaseReceiptsAndConnectionIsolation(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "pair")
	key, err := reporterKey(dir, true)
	require.NoError(t, err)
	s := localReporterState(dir, key)
	now := time.Now().UTC()
	assertStatus := func(want string) *v1.LocalReporterStatus {
		result, err := s.status(now)
		require.NoError(t, err)
		require.Equal(t, want, result.Outcome)
		return result
	}
	assertStatus("never-run")
	require.NoFileExists(t, s.path)
	old := now
	require.NoError(t, s.begin(now, "2026-09-01", "2026-09-02"))
	assertStatus("checking")
	require.ErrorContains(t, s.begin(now.Add(time.Minute), "2026-09-01", "2026-09-02"), "in progress")
	now = now.Add(reporterLease)
	assertStatus("interrupted")
	from, through := "2026-09-03", "2026-09-04"
	require.NoError(t, s.begin(now, from, through))
	_, err = s.finish(old, now, nil, nil)
	require.ErrorContains(t, err, "newer reporter attempt")
	receipt := &v1.CommerceReporterReceipt{CheckedAt: reporterStamp(now), Outcome: "unchanged", StatementId: "earlier-saved-statement"}
	limit := &commerce.StatementReadLimit{Read: "refunds", Reason: "sandbox-quota"}
	status, err := s.finish(now, now, receipt, errors.Join(errors.New("recheck deferred"), limit))
	require.NoError(t, err)
	require.Equal(t, "recheck-rate-limited", status.Outcome)
	require.Equal(t, receipt.CheckedAt, status.LastReceipt.CheckedAt)
	require.Equal(t, through, status.ReceiptThroughDay)
	require.Empty(t, status.ProviderRetryAt)
	next, err := time.Parse(time.RFC3339Nano, status.NextProviderReadAt)
	require.NoError(t, err)
	require.WithinRange(t, next, now.Add(time.Hour), now.Add(72*time.Minute))
	info, err := os.Stat(s.path)
	require.NoError(t, err)
	require.Equal(t, os.FileMode(0600), info.Mode().Perm())
	_, other, err := ed25519.GenerateKey(nil)
	require.NoError(t, err)
	separate, err := localReporterState(dir, other).status(now)
	require.NoError(t, err)
	require.Equal(t, "never-run", separate.Outcome)
	require.Nil(t, separate.LastReceipt)
	now = next
	require.NoError(t, s.begin(now, from, through))
	_, err = s.finish(now, now, nil, errors.New("sensitive upstream content"))
	require.NoError(t, err)
	status = assertStatus("failed")
	require.Equal(t, receipt.CheckedAt, status.LastReceipt.CheckedAt)
	require.Empty(t, status.NextProviderReadAt)
	require.NotContains(t, status.String(), "sensitive upstream content")
}

func TestReporterBackoffAndUnsafeState(t *testing.T) {
	now := time.Now().UTC()
	for i, delay := range []time.Duration{5, 10, 20, 40, 60, 60, 60} {
		minimum := delay * time.Minute
		next := nextReporterRead(now, uint32(i+1), nil)
		require.WithinRange(t, next, now.Add(minimum), now.Add(minimum+minimum/5))
	}
	limit := &commerce.StatementReadLimit{RetryAt: now.Add(8 * time.Hour)}
	require.Equal(t, limit.RetryAt, nextReporterRead(now, 30, limit))
	dir := filepath.Join(t.TempDir(), "pair")
	key, err := reporterKey(dir, true)
	require.NoError(t, err)
	s := localReporterState(dir, key)
	target := filepath.Join(t.TempDir(), "private")
	require.NoError(t, os.WriteFile(target, []byte("untouched"), 0600))
	require.NoError(t, os.Symlink(target, s.path))
	_, err = s.status(now)
	require.Error(t, err)
	require.Error(t, s.begin(now, "2026-09-03", "2026-09-04"))
	raw, err := os.ReadFile(target)
	require.NoError(t, err)
	require.Equal(t, "untouched", string(raw))
}
