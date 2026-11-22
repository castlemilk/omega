package commerce

import (
	"math"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestSalesJournalBalanceIdentityAndExactSettlement(t *testing.T) {
	report := &v1.CommerceStatement{BusinessId: "biz", ProductId: "product", TestMode: true, FromDay: "2026-03-01", ThroughDay: "2026-03-01",
		VerifiedAt: "2026-05-01T00:01:00Z", Orders: []*v1.CommerceStatementOrder{{OrderId: "order-1", Edition: "first", BalanceComplete: true,
			Movements: []*v1.CommerceBalanceMovement{
				{Id: "one", Kind: "charge", Currency: "usd", OccurredAt: "2026-04-03T01:02:03Z", AmountMinor: math.MaxInt64, NetMinor: math.MaxInt64},
				{Id: "two", Kind: "charge", Currency: "usd", OccurredAt: "2026-04-03T01:02:03Z", AmountMinor: math.MaxInt64, NetMinor: math.MaxInt64},
				{Id: "foreign", Kind: "charge", Currency: "jpy", OccurredAt: "2026-04-03T01:02:03.000000001Z", AmountMinor: 5, FeeMinor: 1, NetMinor: 4},
				{Id: "refund", Kind: "refund", Currency: "usd", OccurredAt: "2026-04-01T00:00:00Z", AmountMinor: -25, FeeMinor: -1, NetMinor: -24},
				{Id: "elsewhere", Kind: "charge", Currency: "usd", OccurredAt: "2026-03-31T23:59:59Z", AmountMinor: 100, NetMinor: 100},
			}}}}
	later := proto.CloneOf(report)
	later.VerifiedAt = "2026-05-02T00:01:00Z"
	later.Orders[0].Movements[0].OccurredAt = "2026-04-03T01:02:03.000Z"
	sources := newSettlementSources("biz", "product", "2026-04")
	require.NoError(t, sources.observe(later))
	require.NoError(t, sources.observe(report))
	result, err := sources.salesJournal()
	require.NoError(t, err)
	require.Empty(t, result.Conflicts)
	require.False(t, result.IncompleteEvidence)
	require.Len(t, result.Entries, 4)
	require.Equal(t, "foreign", result.Entries[0].TransactionId)
	require.Equal(t, report.VerifiedAt, result.Entries[1].AttestedAt)
	require.Len(t, result.Currencies, 2)
	require.Equal(t, "jpy", result.Currencies[0].Currency)
	usd := result.Currencies[1]
	require.Equal(t, "18446744073709551614", usd.ChargesMinor)
	require.Equal(t, "25", usd.RefundsMinor)
	require.Equal(t, "-1", usd.FeesMinor)
	require.Equal(t, "18446744073709551590", usd.NetMinor)

	changed := proto.CloneOf(report)
	changed.Orders[0].BalanceComplete = false
	changed.Orders[0].Movements[0].OccurredAt = "2026-03-31T23:59:59.999999999Z"
	changed.VerifiedAt = "2026-05-03T00:01:00Z"
	for _, selected := range []string{"2026-03", "2026-04"} {
		sources := newSettlementSources("biz", "product", selected)
		require.NoError(t, sources.observe(changed))
		require.NoError(t, sources.observe(report))
		result, err := sources.salesJournal()
		require.NoError(t, err)
		require.True(t, result.IncompleteEvidence)
		require.Equal(t, "order-1", result.Gaps[0].OrderId)
		require.Len(t, result.Conflicts, 1)
		require.Equal(t, "one", result.Conflicts[0].TransactionId)
		require.Len(t, result.Conflicts[0].Versions, 2)
		for _, e := range result.Entries {
			require.NotEqual(t, "one", e.TransactionId)
		}
	}
}
