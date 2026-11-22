package commerce

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"math"
	"math/big"
	"math/rand/v2"
	"strings"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const aprilMovement = "2026-04-02T15:00:00Z"

func ledgerMovement(id, kind, currency, occurred string, gross, fee int64) *v1.CommerceBalanceMovement {
	return &v1.CommerceBalanceMovement{Id: id, Kind: kind, Currency: currency, OccurredAt: occurred,
		AmountMinor: gross, FeeMinor: fee, NetMinor: gross - fee}
}

func ledgerRow(order string, movements ...*v1.CommerceBalanceMovement) *v1.CommerceStatementOrder {
	return &v1.CommerceStatementOrder{OrderId: order, Edition: "editorial", PacketSha256: strings.Repeat("a", 64),
		VerifiedAt: wrapperspb.String("2026-07-01T00:00:00Z"), BalanceComplete: true, Movements: movements}
}

func ledgerSource(attested string, rows ...*v1.CommerceStatementOrder) *v1.CommerceStatement {
	return &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", BusinessId: "biz", ProductId: "poster", TestMode: true,
		FromDay: "2026-03-01", ThroughDay: "2026-03-01", VerifiedAt: attested, Orders: rows}
}

func ledgerForMonth(t *testing.T, month string, reports ...*v1.CommerceStatement) *v1.SettlementLedger {
	t.Helper()
	sources := newSettlementSources("biz", "poster", month)
	for _, source := range reports {
		require.NoError(t, sources.observe(source))
	}
	result, err := sources.settlementLedger()
	require.NoError(t, err)
	return result
}

func ledgerEntry(t *testing.T, result *v1.SettlementLedger, id string) *v1.SettlementEntry {
	t.Helper()
	for _, entry := range result.Entries {
		if entry.Movement.TransactionId == id {
			return entry
		}
	}
	require.FailNow(t, "missing booked movement", "%s", id)
	return nil
}

func ledgerSourceHash(t *testing.T, s *v1.CommerceStatement) string {
	t.Helper()
	raw, err := StatementJSON(s)
	require.NoError(t, err)
	return fmt.Sprintf("%x", sha256.Sum256(raw))
}

func TestSettlementLedgerCrossMonthWitnessAndPartialRefunds(t *testing.T) {
	charge := ledgerMovement("charge", "charge", "usd", "2026-03-31T23:59:59Z", 1000, 35)
	a := ledgerMovement("refund-a", "refund", "usd", aprilMovement, -71, 0)
	b := ledgerMovement("refund-b", "refund", "jpy", aprilMovement, -122, -1)
	c := ledgerMovement("refund-c", "refund", "usd", "2026-05-01T00:00:00Z", -34, 0)
	chargeOnly := ledgerSource("2026-07-01T01:00:00Z", ledgerRow("order", charge))
	refundOnly := ledgerSource("2026-07-01T02:00:00Z", ledgerRow("order", b, a))
	both := ledgerSource("2026-07-02T01:00:00Z", ledgerRow("order", c, charge, b, a))
	tied := proto.CloneOf(both)
	tied.Orders[0].ProcessedEvents++
	later := proto.CloneOf(both)
	later.VerifiedAt = "2026-07-02T01:00:00.000000001Z"
	// The same movements were published several times. Only the first
	// common witness, including its source-ID tie-breaker, proves each pair.
	reports := []*v1.CommerceStatement{later, tied, refundOnly, both, chargeOnly}
	witnessHash := min(ledgerSourceHash(t, both), ledgerSourceHash(t, tied))
	witnessID := "omega/" + both.FromDay + "/" + witnessHash
	march := ledgerForMonth(t, "2026-03", reports...)
	require.Len(t, march.Entries, 1)
	chargeEntry := march.Entries[0]
	require.Equal(t, verifiedLineage, chargeEntry.Lineage)
	require.Equal(t, ledgerSourceHash(t, chargeOnly), chargeEntry.Movement.SourceSha256)
	require.Len(t, chargeEntry.Related, 3)
	for i, id := range []string{"refund-a", "refund-b", "refund-c"} {
		relation := chargeEntry.Related[i]
		require.Equal(t, id, relation.Movement.TransactionId)
		require.Equal(t, witnessID, relation.WitnessSourceId)
		require.Equal(t, witnessHash, relation.WitnessSha256)
	}
	require.Equal(t, uint32(len(reports)), march.SourceCount)
	require.Equal(t, later.VerifiedAt, march.LastCheckedAt)
	require.Equal(t, "965", march.Currencies[0].ProcessorNetMinor)

	april := ledgerForMonth(t, "2026-04", reports...)
	require.Len(t, april.Entries, 2)
	require.False(t, april.IncompleteEvidence)
	require.Empty(t, april.Conflicts)
	for _, entry := range april.Entries {
		require.Equal(t, verifiedLineage, entry.Lineage)
		require.Equal(t, ledgerSourceHash(t, refundOnly), entry.Movement.SourceSha256)
		require.Len(t, entry.Related, 1)
		relation := entry.Related[0]
		require.True(t, proto.Equal(chargeEntry.Movement, relation.Movement))
		require.Equal(t, witnessHash, relation.WitnessSha256)
		require.Equal(t, witnessID, relation.WitnessSourceId)
	}
	require.Len(t, april.Currencies, 2)
	require.Equal(t, "jpy", april.Currencies[0].Currency)
	require.Equal(t, "-121", april.Currencies[0].ProcessorNetMinor)
	require.Equal(t, "usd", april.Currencies[1].Currency)
	require.Equal(t, "-71", april.Currencies[1].ProcessorNetMinor)
	require.True(t, proto.Equal(april, ledgerForMonth(t, "2026-04", chargeOnly, both, refundOnly, tied, later)))
}

func TestSettlementLedgerContradictoryOrAbsentOriginal(t *testing.T) {
	charge := ledgerMovement("charge", "charge", "usd", "2026-04-01T00:00:00Z", 1000, 35)
	refund := ledgerMovement("refund", "refund", "usd", aprilMovement, -71, 0)
	row := func(m ...*v1.CommerceBalanceMovement) *v1.CommerceStatementOrder { return ledgerRow("order", m...) }
	changedEdition, changedPacket := row(refund), row(refund)
	changedEdition.Edition = "other"
	changedPacket.PacketSha256 = strings.Repeat("b", 64)
	otherCharge := ledgerMovement("second-charge", "charge", "usd", "2026-05-01T00:00:00Z", 1000, 35)
	differentVersion := proto.CloneOf(otherCharge)
	differentVersion.Id = charge.Id
	premature := proto.CloneOf(refund)
	premature.OccurredAt = "2026-04-01T00:00:00.000000001Z"
	lateCharge := proto.CloneOf(charge)
	lateCharge.OccurredAt = "2026-04-01T00:00:00.000000002Z"
	unverified := row(charge, refund)
	unverified.VerifiedAt = nil
	for _, tc := range []struct {
		name      string
		rows      []*v1.CommerceStatementOrder
		lineage   v1.SettlementLineage
		booked    int
		conflicts int
	}{
		{"orphan", []*v1.CommerceStatementOrder{row(refund)}, missingLineage, 1, 0},
		{"charge and refund in distinct rows", []*v1.CommerceStatementOrder{row(charge), row(refund)}, missingLineage, 2, 0},
		{"equal amounts on another order", []*v1.CommerceStatementOrder{ledgerRow("unrelated", charge), row(refund)}, missingLineage, 2, 0},
		{"no verified row", []*v1.CommerceStatementOrder{unverified}, missingLineage, 2, 0},
		{"edition disagrees", []*v1.CommerceStatementOrder{row(charge), changedEdition}, conflictingLineage, 2, 0},
		{"packet disagrees", []*v1.CommerceStatementOrder{row(charge), changedPacket}, conflictingLineage, 2, 0},
		{"refund predates original", []*v1.CommerceStatementOrder{row(lateCharge, premature)}, conflictingLineage, 2, 0},
		{"two charge identities across months", []*v1.CommerceStatementOrder{row(charge, refund), row(otherCharge)}, conflictingLineage, 2, 0},
		{"multiple charge identities in same row", []*v1.CommerceStatementOrder{row(charge, refund, otherCharge)}, conflictingLineage, 2, 0},
		{"another version outside month", []*v1.CommerceStatementOrder{row(charge, refund), row(differentVersion)}, conflictingLineage, 1, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			report := ledgerSource("2026-07-01T01:00:00Z", tc.rows...)
			result := ledgerForMonth(t, "2026-04", report)
			require.Len(t, result.Entries, tc.booked)
			require.Len(t, result.Conflicts, tc.conflicts)
			require.False(t, result.IncompleteEvidence)
			got := ledgerEntry(t, result, "refund")
			require.Equal(t, tc.lineage, got.Lineage)
			require.Empty(t, got.Related)
			require.NotEmpty(t, got.Postings)
			for _, entry := range result.Entries {
				if entry.Movement.Kind == "charge" && entry.Movement.OrderId == got.Movement.OrderId {
					require.Equal(t, tc.lineage, entry.Lineage)
					require.Empty(t, entry.Related)
				}
			}
			if tc.conflicts != 0 {
				require.Equal(t, charge.Id, result.Conflicts[0].TransactionId)
				require.Len(t, result.Conflicts[0].Versions, 2)
				require.Equal(t, "-71", result.Currencies[0].ProcessorNetMinor)
			}
		})
	}
}

func TestSettlementLedgerRetainsGoodRelationsBesideGapsAndConflicts(t *testing.T) {
	charge := ledgerMovement("charge", "charge", "usd", aprilMovement, 2000, 40)
	good := ledgerMovement("refund-observed", "refund", "usd", aprilMovement, -400, 0)
	separate := ledgerMovement("refund-no-witness", "refund", "usd", aprilMovement, -300, 0)
	pair := ledgerSource("2026-07-01T01:00:00Z", ledgerRow("order", good, charge))
	other := ledgerSource("2026-07-02T01:00:00Z", ledgerRow("order", separate))
	withGap := ledgerForMonth(t, "2026-04", pair, other)
	require.False(t, withGap.IncompleteEvidence)
	require.Equal(t, missingLineage, ledgerEntry(t, withGap, "charge").Lineage)
	require.Equal(t, missingLineage, ledgerEntry(t, withGap, separate.Id).Lineage)
	require.Equal(t, verifiedLineage, ledgerEntry(t, withGap, good.Id).Lineage)
	require.Len(t, ledgerEntry(t, withGap, "charge").Related, 1)

	changed := proto.CloneOf(other)
	changed.VerifiedAt = "2026-07-03T01:00:00Z"
	changed.Orders[0].BalanceComplete = false
	changed.Orders[0].Movements[0].OccurredAt = "2026-05-01T00:00:00Z"
	for _, month := range []string{"2026-04", "2026-05"} {
		result := ledgerForMonth(t, month, pair, other, changed)
		require.True(t, result.IncompleteEvidence)
		require.Len(t, result.Gaps, 1)
		require.Equal(t, "order", result.Gaps[0].OrderId)
		require.Equal(t, ledgerSourceHash(t, changed), result.Gaps[0].SourceSha256)
		require.Len(t, result.Conflicts, 1)
		require.Equal(t, separate.Id, result.Conflicts[0].TransactionId)
		require.Len(t, result.Conflicts[0].Versions, 2)
		if month == "2026-05" {
			require.Empty(t, result.Entries)
			require.Empty(t, result.Currencies)
			continue
		}
		require.Len(t, result.Entries, 2)
		entry := ledgerEntry(t, result, "charge")
		require.Equal(t, conflictingLineage, entry.Lineage)
		require.Len(t, entry.Related, 1)
		require.Equal(t, good.Id, entry.Related[0].Movement.TransactionId)
		require.Equal(t, ledgerSourceHash(t, pair), entry.Related[0].WitnessSha256)
		require.Equal(t, "1560", result.Currencies[0].ProcessorNetMinor)
	}
	onlyCharge := ledgerSource("2026-07-04T01:00:00Z", ledgerRow("order", charge))
	onlyCharge.UnresolvedScopeOrders = 1
	result := ledgerForMonth(t, "2026-04", onlyCharge)
	require.True(t, result.IncompleteEvidence)
	require.Equal(t, noRecordedRefunds, result.Entries[0].Lineage)
	onlyCharge.Orders[0].BalanceComplete = false
	result = ledgerForMonth(t, "2026-04", onlyCharge)
	require.Equal(t, missingLineage, result.Entries[0].Lineage)
}

func TestSettlementLedgerExactPostingsAndLargeTotals(t *testing.T) {
	c1 := ledgerMovement("large-one", "charge", "usd", aprilMovement, math.MaxInt64, 0)
	c2 := ledgerMovement("large-two", "charge", "usd", aprilMovement, math.MaxInt64, 0)
	c3 := ledgerMovement("negative-net", "charge", "usd", aprilMovement, 5, 10)
	r3 := ledgerMovement("fee-rebate", "refund", "usd", aprilMovement, -2, -8)
	source := ledgerSource("2026-07-01T01:00:00Z", ledgerRow("a", c1), ledgerRow("b", c2), ledgerRow("c", c3, r3))
	result := ledgerForMonth(t, "2026-04", source)
	require.Len(t, result.Currencies, 1)
	currency := result.Currencies[0]
	require.Equal(t, "18446744073709551615", currency.ProcessorNetMinor)
	require.Equal(t, "18446744073709551632", currency.DebitsMinor)
	require.Equal(t, currency.DebitsMinor, currency.CreditsMinor)
	want := func(account v1.SettlementAccount, dr, cr string) *v1.SettlementPosting {
		return &v1.SettlementPosting{Account: account, DebitMinor: dr, CreditMinor: cr}
	}
	require.Equal(t, []*v1.SettlementPosting{
		want(processorClearing, "18446744073709551620", "5"),
		want(orderReceipts, "2", "18446744073709551619"),
		want(processingFees, "10", "8"),
	}, currency.Accounts)
	require.Equal(t, []*v1.SettlementPosting{want(processorClearing, "0", "5"), want(orderReceipts, "0", "5"), want(processingFees, "10", "0")},
		ledgerEntry(t, result, c3.Id).Postings)
	require.Equal(t, []*v1.SettlementPosting{want(processorClearing, "6", "0"), want(orderReceipts, "2", "0"), want(processingFees, "0", "8")},
		ledgerEntry(t, result, r3.Id).Postings)
	require.Len(t, ledgerEntry(t, result, c1.Id).Postings, 2)

	// Opposite per-entry errors cancel at the currency level. Each individual
	// movement must also satisfy its signed economic identity.
	c1.NetMinor--
	c2.FeeMinor = 1
	sources := newSettlementSources("biz", "poster", "2026-04")
	require.NoError(t, sources.observe(source))
	_, err := sources.salesJournal()
	require.NoError(t, err)
	_, err = sources.settlementLedger()
	require.Error(t, err)
	for _, bad := range []journalFacts{
		{kind: "charge", currency: "usd", amount: -1, net: -1},
		{kind: "refund", currency: "usd", amount: 1, net: 1},
		{kind: "charge", currency: "usd"},
		{kind: "other", currency: "usd", amount: 1, net: 1},
	} {
		_, err := postSettlement(bad)
		require.Error(t, err)
	}
}

func TestSettlementLedgerRandomizedConservation(t *testing.T) {
	// Deliberately cross currencies, negative fees, opposite net signs and
	// zero net. Independently sum each entry and currency from the raw facts.
	rng := rand.New(rand.NewPCG(28, 73))
	sources := newSettlementSources("biz", "poster", "2026-04")
	type expected struct{ debits, credits, net big.Int }
	byCurrency := make(map[string]*expected)
	for i := range 160 {
		currency := []string{"aud", "jpy", "usd"}[rng.IntN(3)]
		kind := "charge"
		gross := int64(rng.IntN(5000) + 1)
		if i%2 == 0 {
			kind, gross = "refund", -gross
		}
		fee := int64(rng.IntN(14001) - 7000)
		if i%13 == 0 {
			fee = gross
		}
		m := ledgerMovement(fmt.Sprintf("txn-%d", i), kind, currency, aprilMovement, gross, fee)
		row := ledgerRow(fmt.Sprintf("order-%d", i), m)
		first := ledgerSource("2026-07-01T01:00:00Z", row)
		later := ledgerSource("2026-07-02T01:00:00Z", row)
		require.NoError(t, sources.observe(later))
		require.NoError(t, sources.observe(first))
		e := byCurrency[currency]
		if e == nil {
			e = new(expected)
			byCurrency[currency] = e
		}
		e.net.Add(&e.net, big.NewInt(m.NetMinor))
		for _, signed := range []int64{m.NetMinor, -gross, fee} {
			if signed > 0 {
				e.debits.Add(&e.debits, big.NewInt(signed))
			} else {
				e.credits.Sub(&e.credits, big.NewInt(signed))
			}
		}
	}
	result, err := sources.settlementLedger()
	require.NoError(t, err)
	require.Len(t, result.Entries, 160)
	for _, entry := range result.Entries {
		last := v1.SettlementAccount_SETTLEMENT_ACCOUNT_UNSPECIFIED
		var difference big.Int
		for _, line := range entry.Postings {
			require.Greater(t, int(line.Account), int(last))
			last = line.Account
			dr, ok := new(big.Int).SetString(line.DebitMinor, 10)
			require.True(t, ok)
			cr, ok := new(big.Int).SetString(line.CreditMinor, 10)
			require.True(t, ok)
			require.GreaterOrEqual(t, dr.Sign(), 0)
			require.GreaterOrEqual(t, cr.Sign(), 0)
			require.NotEqual(t, dr.Sign(), cr.Sign())
			difference.Add(&difference, dr).Sub(&difference, cr)
		}
		require.Zero(t, difference.Sign())
	}
	require.Len(t, result.Currencies, len(byCurrency))
	for _, total := range result.Currencies {
		e := byCurrency[total.Currency]
		require.Equal(t, e.net.String(), total.ProcessorNetMinor)
		require.Equal(t, e.debits.String(), total.DebitsMinor)
		require.Equal(t, e.credits.String(), total.CreditsMinor)
	}
}

func TestSettlementSourceSinkReceivesExactValidatedBytesAndPropagatesFailures(t *testing.T) {
	report := ledgerSource("2026-07-01T01:00:00Z", ledgerRow("order", ledgerMovement("charge", "charge", "usd", aprilMovement, 100, 3)))
	sources := newSettlementSources("biz", "poster", "2026-04")
	raw, err := StatementJSON(report)
	require.NoError(t, err)
	wantErr := errors.New("could not preserve a private source")
	var calls int
	sources.save = func(digest string, body []byte) error {
		calls++
		require.Equal(t, fmt.Sprintf("%x", sha256.Sum256(raw)), digest)
		require.Equal(t, raw, body)
		return wantErr
	}
	wrong := proto.CloneOf(report)
	wrong.TestMode = false
	require.Error(t, sources.observe(wrong))
	wrong = proto.CloneOf(report)
	wrong.Orders[0].Movements[0].OccurredAt = "invalid"
	require.Error(t, sources.observe(wrong))
	require.Zero(t, calls)
	require.ErrorIs(t, sources.observe(report), wantErr)
	require.Equal(t, 1, calls)
}
