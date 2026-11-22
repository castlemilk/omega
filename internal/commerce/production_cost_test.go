package commerce

import (
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func openTestCostBook(t *testing.T) *ProductionCostBook {
	t.Helper()
	b, err := OpenProductionCostBook(filepath.Join(t.TempDir(), "costs.db"), false, os.OpenFile)
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, b.Close()) })
	return b
}

func costSample() (*v1.ProductionCostReceipt, []byte) {
	evidence := []byte("Source line 187, service day 2026-11-16, explicitly simulated.")
	target := func(product, run string, points uint32) *v1.ProductionCostTarget {
		return &v1.ProductionCostTarget{BusinessId: "press", ProductId: product, RunId: run, ExperimentId: "proof", Edition: "second", ArtifactSha256: fingerprint([]byte(run)), ShareBps: points}
	}
	return &v1.ProductionCostReceipt{
		Provider: "printer", Account: "press-test", LineId: "187", Simulated: proto.Bool(true), ServiceDate: "2026-11-16",
		Stage: costEstimated, Category: v1.ProductionCostCategory_PRODUCTION_COST_CATEGORY_PRODUCTION,
		Currency: "AUD", AmountMicros: proto.Int64(10001), EvidenceSha256: fingerprint(evidence),
		Description: "Colour proof quote", AllocationBasis: "Shares of the proof sheet",
		Targets: []*v1.ProductionCostTarget{target("other", "c", 3333), target("posters", "a", 3334), target("posters", "b", 3333)},
	}, evidence
}

func TestProductionCostWaterfallAndCorrections(t *testing.T) {
	book := openTestCostBook(t)
	receipt, support := costSample()
	first, err := book.Record(receipt, support)
	require.NoError(t, err)
	slices.Reverse(receipt.Targets)
	again, err := book.Record(receipt, support)
	require.NoError(t, err)
	require.Equal(t, first, again)
	for _, sample := range []struct {
		product     string
		total       int64
		allocations int
	}{{"posters", 6668, 2}, {"other", 3333, 1}} {
		statement, err := book.Statement("press", sample.product, "2026-11", true)
		require.NoError(t, err)
		require.Len(t, statement.Items, 1)
		item := statement.Items[0]
		require.Len(t, item.Allocations, sample.allocations)
		require.Equal(t, sample.total, item.GetProductMicros())
		require.Equal(t, uint32(3), item.SourceTargetCount)
		require.Equal(t, fmt.Sprint(sample.total), statement.Subtotals[0].AmountMicros)
		for _, a := range item.Allocations {
			require.Equal(t, sample.product, a.Target.ProductId)
		}
	}
	raw, err := book.Export(first, false)
	require.NoError(t, err)
	require.Equal(t, first, fingerprint(raw))
	original := new(v1.ProductionCostReceipt)
	require.NoError(t, protojson.Unmarshal(raw, original))
	raw, err = book.Export(original.EvidenceSha256, true)
	require.NoError(t, err)
	require.Equal(t, support, raw)

	// Move the same source from quote to reserved, then to a settled credit
	// in its corrected service month. Replaying the initial input is harmless.
	prev := first
	for _, stage := range []v1.ProductionCostStage{costReserved, costIncurred, costSettled} {
		receipt.Stage = stage
		receipt.PreviousReceiptSha256 = prev
		receipt.RevisionReason = "Updated supplier document"
		if stage == costSettled {
			receipt.ServiceDate = "2026-12-01"
			receipt.AmountMicros = proto.Int64(-101)
		}
		doc := []byte(stage.String())
		receipt.EvidenceSha256 = fingerprint(doc)
		prev, err = book.Record(receipt, doc)
		require.NoError(t, err)
	}
	again, err = book.Record(original, support)
	require.NoError(t, err)
	require.Equal(t, first, again)
	stale := proto.CloneOf(original)
	stale.PreviousReceiptSha256 = first
	stale.RevisionReason = "Earlier competing correction"
	_, err = book.Record(stale, support)
	require.ErrorContains(t, err, "different current")
	prior, err := book.Statement("press", "posters", "2026-11", true)
	require.NoError(t, err)
	require.Empty(t, prior.Items)
	closed, err := book.Statement("press", "posters", "2026-12", true)
	require.NoError(t, err)
	require.Len(t, closed.Subtotals, 1)
	require.Equal(t, costSettled, closed.Subtotals[0].Stage)
	require.Equal(t, "-67", closed.Subtotals[0].AmountMicros)
	require.Equal(t, prev, closed.Items[0].ReceiptSha256)
	observed, err := book.Statement("press", "posters", "2026-12", false)
	require.NoError(t, err)
	require.Empty(t, observed.Items)
	receipt.Stage = costWithdrawn
	receipt.AmountMicros = nil
	receipt.PreviousReceiptSha256 = prev
	receipt.RevisionReason = "Supplier withdrew the credit"
	doc := []byte("Withdrawal notice")
	receipt.EvidenceSha256 = fingerprint(doc)
	_, err = book.Record(receipt, doc)
	require.NoError(t, err)
	closed, err = book.Statement("press", "posters", "2026-12", true)
	require.NoError(t, err)
	require.Nil(t, closed.Items[0].ProductMicros)
	require.Empty(t, closed.Subtotals)
}

func TestProductionCostObservationRetriesAndConcurrentCorrections(t *testing.T) {
	book := openTestCostBook(t)
	r, support := costSample()
	r.Stage = costProvisional
	r.AmountMicros = nil
	r.Currency = ""
	r.Simulated = proto.Bool(false)
	type result struct {
		hash string
		err  error
	}
	var roots [12]result
	var goroutines sync.WaitGroup
	for i := range roots {
		goroutines.Go(func() { roots[i].hash, roots[i].err = book.Observe(r, support) })
	}
	goroutines.Wait()
	for _, out := range roots {
		require.NoError(t, out.err)
		require.Equal(t, roots[0].hash, out.hash)
	}
	current, err := book.Statement("press", "posters", "2026-11", false)
	require.NoError(t, err)
	require.Equal(t, uint32(1), current.ProvisionalItems)
	require.Nil(t, current.Items[0].ProductMicros)
	require.Empty(t, current.Subtotals)
	var revisions [12]result
	for i := range revisions {
		goroutines.Go(func() {
			revision := proto.CloneOf(r)
			revision.Stage = costIncurred
			revision.Currency = "USD"
			revision.AmountMicros = proto.Int64(int64(i))
			revision.PreviousReceiptSha256 = roots[0].hash
			revision.RevisionReason = "Received the bill"
			doc := []byte(fmt.Sprintf("invoice %d", i))
			revision.EvidenceSha256 = fingerprint(doc)
			revisions[i].hash, revisions[i].err = book.Record(revision, doc)
		})
	}
	goroutines.Wait()
	success := 0
	for _, out := range revisions {
		if out.err == nil {
			success++
		} else {
			require.ErrorContains(t, out.err, "different current")
		}
	}
	require.Equal(t, 1, success)
	r.ServiceDate = "2026-12-02"
	digest, err := book.Observe(r, support)
	require.NoError(t, err)
	require.Equal(t, roots[0].hash, digest)
	r.Targets[0].RunId = "other-run"
	_, err = book.Observe(r, support)
	require.ErrorContains(t, err, "different observation")
	next, err := book.Statement("press", "posters", "2026-12", false)
	require.NoError(t, err)
	require.Empty(t, next.Items)
	current, err = book.Statement("press", "posters", "2026-11", false)
	require.NoError(t, err)
	require.Zero(t, current.ProvisionalItems)
	require.Equal(t, costIncurred, current.Items[0].Stage)
	require.NotNil(t, current.Items[0].ProductMicros)
}

func TestProductionCostValidationAndDatedRates(t *testing.T) {
	book := openTestCostBook(t)
	r, support := costSample()
	r.AmountMicros = proto.Int64(30)
	r.Rate = &v1.ProductionCostRate{Unit: "sheet", Units: 3, PriceMicrosPerUnit: proto.Uint64(10), EffectiveFrom: "2026-11-16", EffectiveThrough: "2026-11-16"}
	_, err := book.Record(r, support)
	require.NoError(t, err)
	reject := []func(*v1.ProductionCostReceipt){
		func(v *v1.ProductionCostReceipt) { v.Simulated = nil },
		func(v *v1.ProductionCostReceipt) { v.ServiceDate = "2026-02-30" },
		func(v *v1.ProductionCostReceipt) { v.AmountMicros = nil },
		func(v *v1.ProductionCostReceipt) { v.AmountMicros = proto.Int64(31) },
		func(v *v1.ProductionCostReceipt) { v.Rate.PriceMicrosPerUnit = nil },
		func(v *v1.ProductionCostReceipt) { v.Rate.EffectiveFrom = "2026-11-17" },
		func(v *v1.ProductionCostReceipt) { v.Rate.EffectiveThrough = "2026-11-15" },
		func(v *v1.ProductionCostReceipt) { v.Currency = "aud" },
		func(v *v1.ProductionCostReceipt) { v.Stage = costSettled },
		func(v *v1.ProductionCostReceipt) { v.Stage = costProvisional },
		func(v *v1.ProductionCostReceipt) { v.Stage = costWithdrawn },
		func(v *v1.ProductionCostReceipt) { v.Category = 900 },
		func(v *v1.ProductionCostReceipt) { v.Targets[0].ShareBps-- },
		func(v *v1.ProductionCostReceipt) { v.Targets[0] = v.Targets[2] },
		func(v *v1.ProductionCostReceipt) { v.Targets[0].ArtifactSha256 = "unknown" },
		func(v *v1.ProductionCostReceipt) { v.Targets[0].RunId = "" },
		func(v *v1.ProductionCostReceipt) { v.EvidenceSha256 = strings.Repeat("0", 64) },
		func(v *v1.ProductionCostReceipt) { v.PreviousReceiptSha256 = "missing" },
	}
	for i, change := range reject {
		modified := proto.CloneOf(r)
		change(modified)
		_, err := book.Record(modified, support)
		require.Errorf(t, err, "invalid case %d", i)
	}
	r.LineId = "confirmed-zero"
	r.Stage = costIncurred
	r.AmountMicros = proto.Int64(0)
	r.Rate = nil
	_, err = book.Record(r, support)
	require.NoError(t, err)
	r.LineId = "next-price"
	r.Stage = costEstimated
	r.ServiceDate = "2026-11-17"
	r.Rate = &v1.ProductionCostRate{Unit: "sheet", Units: 3, PriceMicrosPerUnit: proto.Uint64(20), EffectiveFrom: "2026-11-17"}
	r.AmountMicros = proto.Int64(60)
	_, err = book.Record(r, support)
	require.NoError(t, err)
	statement, err := book.Statement("press", "posters", "2026-11", true)
	require.NoError(t, err)
	require.Len(t, statement.Subtotals, 2)
	require.Equal(t, "60", statement.Subtotals[0].AmountMicros)
	require.Equal(t, "0", statement.Subtotals[1].AmountMicros)
	require.Equal(t, costIncurred, statement.Subtotals[1].Stage)
}

func TestProductionCostAllocationExtremes(t *testing.T) {
	sample, _ := costSample()
	for _, n := range []int64{0, 1, -1, 2, -2, 3333, math.MinInt64, math.MaxInt64} {
		allocations := costShares(n, sample.Targets)
		sum := new(big.Int)
		for _, share := range allocations {
			sum.Add(sum, big.NewInt(share))
		}
		require.Equal(t, big.NewInt(n).String(), sum.String())
		only := proto.CloneOf(sample.Targets[0])
		only.ShareBps = 10000
		require.Equal(t, []int64{n}, costShares(n, []*v1.ProductionCostTarget{only}))
	}
	book := openTestCostBook(t)
	sample.Targets = sample.Targets[1:2]
	sample.Targets[0].ShareBps = 10000
	sample.AmountMicros = proto.Int64(math.MaxInt64)
	for _, id := range []string{"one", "two"} {
		sample.LineId = id
		_, err := book.Record(sample, []byte("Source line 187, service day 2026-11-16, explicitly simulated."))
		require.NoError(t, err)
	}
	statement, err := book.Statement("press", "posters", "2026-11", true)
	require.NoError(t, err)
	require.Equal(t, "18446744073709551614", statement.Subtotals[0].AmountMicros)
}
