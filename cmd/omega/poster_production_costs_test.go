//go:build unix

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func runPosterCosts(args ...string) ([]byte, error) {
	cmd := posterProductionCostsCommand()
	cmd.SilenceUsage = true
	cmd.SilenceErrors = true
	var output bytes.Buffer
	cmd.SetOut(&output)
	cmd.SetErr(&output)
	cmd.SetArgs(args)
	err := cmd.Execute()
	return output.Bytes(), err
}

func TestPosterProductionCostsOwnerJourney(t *testing.T) {
	dir := t.TempDir()
	book := filepath.Join(dir, "costs.db")
	missing := filepath.Join(dir, "missing", "costs.db")
	_, err := runPosterCosts("statement", "--book", missing)
	require.Error(t, err)
	_, err = os.Stat(missing)
	require.ErrorIs(t, err, os.ErrNotExist)
	packet, err := os.ReadFile("../../projects/posters/testdata/signal-studies-editorial-01.json")
	require.NoError(t, err)
	var review struct{ Candidate json.RawMessage }
	require.NoError(t, json.Unmarshal(packet, &review))
	var candidate v1.PosterReleaseCandidate
	require.NoError(t, protojson.Unmarshal(review.Candidate, &candidate))
	body, err := posters.StableJSON(&candidate)
	require.NoError(t, err)
	body = append(body, '\n')
	day := time.Date(2026, 11, 22, 18, 35, 0, 0, time.FixedZone("UTC+11", 11*60*60))
	first, err := recordPosterPreparation(book, "press-check-01", "cover-proof", &candidate, body, day)
	require.NoError(t, err)
	next, err := recordPosterPreparation(book, "press-check-01", "cover-proof", &candidate, body, day.AddDate(0, 0, 10))
	require.NoError(t, err)
	require.Equal(t, first, next)
	get := func(command string, args ...string) []byte {
		out, err := runPosterCosts(append([]string{command, "--book", book}, args...)...)
		require.NoError(t, err)
		return out
	}
	readStatement := func(mode ...string) *v1.ProductionCostStatement {
		raw := get("statement", append([]string{"--month", "2026-11"}, mode...)...)
		v := new(v1.ProductionCostStatement)
		require.NoError(t, protojson.Unmarshal(raw, v))
		return v
	}
	actual := readStatement()
	require.Equal(t, uint32(1), actual.ProvisionalItems)
	require.Len(t, actual.Items, 1)
	require.Nil(t, actual.Items[0].ProductMicros)
	require.Equal(t, candidate.PrintPack.Sha256, actual.Items[0].Allocations[0].Target.ArtifactSha256)
	require.Equal(t, body, get("evidence", actual.Items[0].EvidenceSha256))
	require.Empty(t, readStatement("--simulated").Items)
	rawReceipt := get("receipt", first)
	require.Equal(t, first, fmt.Sprintf("%x", sha256.Sum256(rawReceipt)))
	receipt := new(v1.ProductionCostReceipt)
	require.NoError(t, protojson.Unmarshal(rawReceipt, receipt))
	// A separate simulated invoice follows the regular owner entry point.
	support := []byte("Test document. Print and compute services: AUD 2.40.")
	file := filepath.Join(dir, "test-invoice.txt")
	require.NoError(t, os.WriteFile(file, support, 0600))
	receipt.Provider = "proof-services"
	receipt.Account = "test-desk"
	receipt.LineId = "invoice-123/1"
	receipt.EvidenceSha256 = fmt.Sprintf("%x", sha256.Sum256(support))
	receipt.Simulated = proto.Bool(true)
	receipt.Stage = v1.ProductionCostStage_PRODUCTION_COST_STAGE_INCURRED
	receipt.Currency = "AUD"
	receipt.AmountMicros = proto.Int64(2400000)
	path := filepath.Join(dir, "claim.json")
	write := func() {
		raw, err := protojson.Marshal(receipt)
		require.NoError(t, err)
		require.NoError(t, os.WriteFile(path, raw, 0600))
	}
	write()
	claim := strings.TrimSpace(string(get("record", path, file)))
	require.Equal(t, claim, strings.TrimSpace(string(get("record", path, file))))
	trial := readStatement("--simulated")
	require.Len(t, trial.Subtotals, 1)
	require.Equal(t, "2400000", trial.Subtotals[0].AmountMicros)
	require.Equal(t, support, get("evidence", trial.Items[0].EvidenceSha256))
	receipt.AmountMicros = proto.Int64(0)
	receipt.Stage = v1.ProductionCostStage_PRODUCTION_COST_STAGE_SETTLED
	receipt.PreviousReceiptSha256 = claim
	receipt.RevisionReason = "The supplier waived the simulated charge"
	updated := []byte("Test credit notice. Final cost AUD 0.00.")
	receipt.EvidenceSha256 = fmt.Sprintf("%x", sha256.Sum256(updated))
	write()
	_, err = runPosterCosts("record", "--book", book, path, file)
	require.ErrorContains(t, err, "evidence bytes")
	require.Equal(t, "2400000", readStatement("--simulated").Subtotals[0].AmountMicros)
	require.NoError(t, os.WriteFile(file, updated, 0600))
	corrected := strings.TrimSpace(string(get("record", path, file)))
	require.NotEqual(t, claim, corrected)
	trial = readStatement("--simulated")
	require.Len(t, trial.Items, 1)
	require.NotNil(t, trial.Items[0].ProductMicros)
	require.Equal(t, "0", trial.Subtotals[0].AmountMicros)
	require.Equal(t, claim, trial.Items[0].PreviousReceiptSha256)
	require.Equal(t, first, readStatement().Items[0].ReceiptSha256)
	require.NotEmpty(t, get("receipt", claim))
	receipt.Targets[0].ProductId = "some-other-product"
	write()
	_, err = runPosterCosts("record", "--book", book, path, file)
	require.ErrorContains(t, err, "no allocation to Signal Studies")
	info, err := os.Stat(book)
	require.NoError(t, err)
	require.Equal(t, os.FileMode(0600), info.Mode().Perm())
	link := filepath.Join(dir, "link.db")
	require.NoError(t, os.Symlink(book, link))
	_, err = runPosterCosts("statement", "--book", link)
	require.Error(t, err)
	require.NoError(t, os.Chmod(book, 0644))
	_, err = runPosterCosts("statement", "--book", book)
	require.ErrorContains(t, err, "0600")
}
