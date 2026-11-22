package commerce

import (
	"math"
	"strings"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestProductionCostFeeEvidenceAndAtomicRefresh(t *testing.T) {
	book := openTestCostBook(t)
	row := ledgerRow("order-1", ledgerMovement("txn_charge", "charge", "usd", aprilMovement, 1000, 61),
		ledgerMovement("txn_refund", "refund", "usd", aprilMovement, -250, 0))
	row.ArchiveSha256 = strings.Repeat("b", 64)
	original := ledgerSource("2026-07-01T03:00:00Z", row)
	prepare := func(source *v1.CommerceStatement) (*v1.SettlementLedger, map[string][]byte) {
		raw, err := StatementJSON(source)
		require.NoError(t, err)
		return ledgerForMonth(t, "2026-04", source), map[string][]byte{fingerprint(raw): raw}
	}
	ledger, docs := prepare(original)
	require.NoError(t, book.RecordTestFees("acct_isolated", ledger, docs))
	state, err := book.Statement("biz", "poster", "2026-04", true)
	require.NoError(t, err)
	require.Len(t, state.Items, 2)
	require.Equal(t, "610000", state.Subtotals[0].AmountMicros)
	require.Equal(t, uint32(2), state.Subtotals[0].Items)
	for _, item := range state.Items {
		require.Equal(t, row.ArchiveSha256, item.Allocations[0].Target.ArtifactSha256)
		require.NotNil(t, item.ProductMicros)
		found, err := book.Export(item.EvidenceSha256, true)
		require.NoError(t, err)
		require.Equal(t, docs[item.EvidenceSha256], found)
	}
	refreshed := proto.CloneOf(original)
	refreshed.VerifiedAt = "2026-07-02T03:00:00Z"
	ledger, docs = prepare(refreshed)
	require.NoError(t, book.RecordTestFees("acct_isolated", ledger, docs))
	again, err := book.Statement("biz", "poster", "2026-04", true)
	require.NoError(t, err)
	require.True(t, proto.Equal(state, again))
	// The same fee on a different gross charge is a conflict. A genuinely
	// new order earlier in the batch cannot be left partially imported.
	changed := proto.CloneOf(refreshed)
	changed.Orders[0].Movements[0].AmountMinor++
	changed.Orders[0].Movements[0].NetMinor++
	second := ledgerRow("order-2", ledgerMovement("txn_new", "charge", "usd", "2026-04-04T15:00:00Z", 200, 6))
	second.ArchiveSha256 = strings.Repeat("c", 64)
	changed.Orders = append(changed.Orders, second)
	ledger, docs = prepare(changed)
	require.Equal(t, "txn_new", ledger.Entries[0].Movement.TransactionId)
	require.ErrorContains(t, book.RecordTestFees("acct_isolated", ledger, docs), "new fee differs")
	after, err := book.Statement("biz", "poster", "2026-04", true)
	require.NoError(t, err)
	require.True(t, proto.Equal(state, after))
	ledger, docs = prepare(refreshed)
	ledger.Entries[0].Movement.AttestedAt = "2026-07-03T03:00:00Z"
	require.ErrorContains(t, book.RecordTestFees("acct_isolated", ledger, docs), "differs from its exact")
	ledger, docs = prepare(refreshed)
	ledger.Entries[0].Movement.FeeMinor = "50"
	require.ErrorContains(t, book.RecordTestFees("acct_isolated", ledger, docs), "differs from its exact")
	ledger, docs = prepare(refreshed)
	ledger.TestMode = false
	require.Error(t, book.RecordTestFees("acct_isolated", ledger, docs))
	ledger.TestMode = true
	require.Error(t, book.RecordTestFees("acct_isolated", ledger, nil))
	real, err := book.Statement("biz", "poster", "2026-04", false)
	require.NoError(t, err)
	require.Empty(t, real.Items)
}

func TestProductionCostFeeCurrencyUnits(t *testing.T) {
	for code, want := range map[string]int64{"usd": 10000, "aud": 10000, "jpy": 1000000, "mga": 1000000, "ugx": 10000, "isk": 10000, "kwd": 1000, "tnd": 1000} {
		cost, err := stripeFeeMicros(code, 1)
		require.NoError(t, err)
		require.Equal(t, want, cost, code)
		cost, err = stripeFeeMicros(code, -1)
		require.NoError(t, err)
		require.Equal(t, -want, cost, code)
	}
	_, err := stripeFeeMicros("usd", math.MaxInt64)
	require.Error(t, err)
	_, err = stripeFeeMicros("zzz", 10)
	require.Error(t, err)
}
