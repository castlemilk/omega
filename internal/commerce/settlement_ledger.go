package commerce

import (
	"context"
	"database/sql"
	"errors"
	"math/big"
	"sort"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

const (
	processorClearing = v1.SettlementAccount_SETTLEMENT_ACCOUNT_PROCESSOR_CLEARING
	orderReceipts     = v1.SettlementAccount_SETTLEMENT_ACCOUNT_ORDER_RECEIPTS
	processingFees    = v1.SettlementAccount_SETTLEMENT_ACCOUNT_PROCESSING_FEES

	verifiedLineage    = v1.SettlementLineage_SETTLEMENT_LINEAGE_VERIFIED
	noRecordedRefunds  = v1.SettlementLineage_SETTLEMENT_LINEAGE_NO_RECORDED_REFUNDS
	missingLineage     = v1.SettlementLineage_SETTLEMENT_LINEAGE_MISSING_EVIDENCE
	conflictingLineage = v1.SettlementLineage_SETTLEMENT_LINEAGE_CONFLICTING_EVIDENCE
)

// SettlementSourceSink retains the exact, scoped statement bytes used for
// movements and witnesses. An error stops the report before it is returned.
type SettlementSourceSink func(sha256 string, statementJSON []byte) error

// OperatorSettlementLedger reads the isolated test merchant and books its
// observed processor movements in their individual settlement currencies.
func OperatorSettlementLedger(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, month string, save SettlementSourceSink) (*v1.SettlementLedger, error) {
	ledger, _, err := OperatorSettlementLedgerWithMerchant(ctx, db, gateway, business, product, month, save)
	return ledger, err
}

// OperatorSettlementLedgerWithMerchant returns the account that scoped every
// order read for the ledger, including the evidence used to attribute its fees.
func OperatorSettlementLedgerWithMerchant(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, month string, save SettlementSourceSink) (*v1.SettlementLedger, string, error) {
	sources, err := readSettlementSources(ctx, db, gateway, business, product, month, save)
	if err != nil {
		return nil, "", err
	}
	ledger, err := sources.settlementLedger()
	if err != nil {
		return nil, "", err
	}
	return ledger, sources.merchant, nil
}

type settlementPair struct{ charge, refund string }

type settlementWitness struct {
	id, sha256 string
	attested   time.Time
}

// statementBalance checks every refund's actual Stripe charge. Only a
// verified order row containing both expansions can witness their connection.
func (sources *settlementSources) observeWitnesses(row *v1.CommerceStatementOrder, witness settlementWitness) {
	if row.GetVerifiedAt().GetValue() == "" || len(row.Movements) < 2 {
		return
	}
	var charge string
	for _, movement := range row.Movements {
		if movement.Kind == "charge" {
			if charge != "" {
				return
			}
			charge = movement.Id
		}
	}
	if charge == "" {
		return
	}
	for _, movement := range row.Movements {
		if movement.Kind != "refund" {
			continue
		}
		pair := settlementPair{charge, movement.Id}
		prior, ok := sources.witnesses[pair]
		if !ok || witness.attested.Before(prior.attested) || (witness.attested.Equal(prior.attested) && witness.id < prior.id) {
			sources.witnesses[pair] = witness
		}
	}
}

type settlementOrder struct {
	chargeID          string
	conflictingCharge bool
	refunds           map[string]bool
	balanceGap        bool
}

// An identity's conflicting versions can implicate multiple orders or months.
// Index every version before consulting the journal's bookable month entries.
func (sources *settlementSources) settlementOrders() map[string]*settlementOrder {
	orders := make(map[string]*settlementOrder)
	for id, versions := range sources.movements {
		for facts := range versions {
			order := orders[facts.order]
			if order == nil {
				order = &settlementOrder{refunds: make(map[string]bool)}
				orders[facts.order] = order
			}
			switch facts.kind {
			case "charge":
				if len(versions) != 1 || (order.chargeID != "" && order.chargeID != id) {
					order.conflictingCharge = true
				}
				order.chargeID = id
			case "refund":
				order.refunds[id] = true
			}
		}
	}
	for _, gap := range sources.scope.Gaps {
		if order := orders[gap.OrderId]; order != nil && gap.OrderId != "" {
			order.balanceGap = true
		}
	}
	return orders
}

func (sources *settlementSources) uniqueMovement(id string) (journalFacts, *v1.SalesJournalEntry) {
	versions := sources.movements[id]
	if len(versions) == 1 {
		for facts, entry := range versions {
			return facts, entry
		}
	}
	return journalFacts{}, nil
}

// Order, edition, packet and chronology must agree. Partial refunds and
// different processor settlement currencies do not alter this identity test.
func (sources *settlementSources) refundLineage(order *settlementOrder, refundID string) (v1.SettlementLineage, settlementWitness) {
	refund, movement := sources.uniqueMovement(refundID)
	if order.conflictingCharge || movement == nil {
		return conflictingLineage, settlementWitness{}
	}
	if order.chargeID == "" {
		return missingLineage, settlementWitness{}
	}
	charge, original := sources.uniqueMovement(order.chargeID)
	if original == nil || charge.kind != "charge" || refund.kind != "refund" ||
		charge.order != refund.order || charge.edition != refund.edition || charge.packet != refund.packet ||
		charge.occurred.After(refund.occurred) {
		return conflictingLineage, settlementWitness{}
	}
	witness, ok := sources.witnesses[settlementPair{order.chargeID, refundID}]
	if !ok || charge.order == "" || charge.edition == "" || charge.packet == "" {
		return missingLineage, settlementWitness{}
	}
	return verifiedLineage, witness
}

func (w settlementWitness) relation(movement *v1.SalesJournalEntry) *v1.SettlementRelation {
	return &v1.SettlementRelation{Movement: movement, WitnessSourceId: w.id, WitnessSha256: w.sha256}
}

func (sources *settlementSources) traceSettlement(entry *v1.SettlementEntry, order *settlementOrder) {
	if entry.Movement.Kind == "refund" {
		lineage, witness := sources.refundLineage(order, entry.Movement.TransactionId)
		entry.Lineage = lineage
		if lineage == verifiedLineage {
			_, charge := sources.uniqueMovement(order.chargeID)
			entry.Related = append(entry.Related, witness.relation(charge))
		}
		return
	}
	if order.conflictingCharge {
		entry.Lineage = conflictingLineage
		return
	}
	switch {
	case order.balanceGap:
		entry.Lineage = missingLineage
	case len(order.refunds) == 0:
		entry.Lineage = noRecordedRefunds
	default:
		entry.Lineage = verifiedLineage
	}
	for refundID := range order.refunds {
		lineage, witness := sources.refundLineage(order, refundID)
		switch lineage {
		case conflictingLineage:
			entry.Lineage = conflictingLineage
		case missingLineage:
			if entry.Lineage != conflictingLineage {
				entry.Lineage = missingLineage
			}
		case verifiedLineage:
			_, refund := sources.uniqueMovement(refundID)
			entry.Related = append(entry.Related, witness.relation(refund))
		}
	}
	sort.Slice(entry.Related, func(i, j int) bool {
		a, b := entry.Related[i].Movement, entry.Related[j].Movement
		first, _ := time.Parse(time.RFC3339Nano, a.OccurredAt)
		second, _ := time.Parse(time.RFC3339Nano, b.OccurredAt)
		if first.Equal(second) {
			return a.TransactionId < b.TransactionId
		}
		return first.Before(second)
	})
}

type settlementSides struct{ debit, credit big.Int }

type settlementAccounts [processingFees + 1]settlementSides

func (s *settlementSides) post(signedDebit *big.Int) {
	if signedDebit.Sign() > 0 {
		s.debit.Add(&s.debit, signedDebit)
	} else {
		s.credit.Sub(&s.credit, signedDebit)
	}
}

func postSettlement(facts journalFacts) (*settlementAccounts, error) {
	if !validCurrency(facts.currency) || !((facts.kind == "charge" && facts.amount > 0) || (facts.kind == "refund" && facts.amount < 0)) {
		return nil, errors.New("invalid settlement movement kind, currency or gross amount")
	}
	gross, fee, net := big.NewInt(facts.amount), big.NewInt(facts.fee), big.NewInt(facts.net)
	if new(big.Int).Sub(gross, fee).Cmp(net) != 0 {
		return nil, errors.New("the settlement movement's gross, fee and net do not reconcile")
	}
	accounts := new(settlementAccounts)
	accounts[processorClearing].post(net)
	accounts[orderReceipts].post(new(big.Int).Neg(gross))
	accounts[processingFees].post(fee)
	return accounts, nil
}

func (accounts *settlementAccounts) add(entry *settlementAccounts) {
	for account := processorClearing; account <= processingFees; account++ {
		side, line := &accounts[account], &entry[account]
		side.debit.Add(&side.debit, &line.debit)
		side.credit.Add(&side.credit, &line.credit)
	}
}

func (accounts *settlementAccounts) postings() ([]*v1.SettlementPosting, string, string, error) {
	var lines []*v1.SettlementPosting
	var debits, credits big.Int
	for account := processorClearing; account <= processingFees; account++ {
		side := &accounts[account]
		if side.debit.Sign() == 0 && side.credit.Sign() == 0 {
			continue
		}
		lines = append(lines, &v1.SettlementPosting{Account: account, DebitMinor: side.debit.String(), CreditMinor: side.credit.String()})
		debits.Add(&debits, &side.debit)
		credits.Add(&credits, &side.credit)
	}
	if debits.Cmp(&credits) != 0 {
		return nil, "", "", errors.New("the settlement postings do not balance")
	}
	return lines, debits.String(), credits.String(), nil
}

func (sources *settlementSources) settlementLedger() (*v1.SettlementLedger, error) {
	journal, err := sources.salesJournal()
	if err != nil {
		return nil, err
	}
	ledger := &v1.SettlementLedger{Month: journal.Month, BusinessId: journal.BusinessId, ProductId: journal.ProductId, TestMode: journal.TestMode,
		SourceCount: journal.SourceCount, LastCheckedAt: journal.LastCheckedAt, IncompleteEvidence: journal.IncompleteEvidence,
		Conflicts: journal.Conflicts, Gaps: journal.Gaps}
	orders := sources.settlementOrders()
	totals := make(map[string]*settlementAccounts)
	for _, movement := range journal.Entries {
		facts, _ := sources.uniqueMovement(movement.TransactionId)
		accounts, err := postSettlement(facts)
		if err != nil {
			return nil, err
		}
		lines, _, _, err := accounts.postings()
		if err != nil {
			return nil, err
		}
		entry := &v1.SettlementEntry{Movement: movement, Postings: lines}
		sources.traceSettlement(entry, orders[facts.order])
		ledger.Entries = append(ledger.Entries, entry)
		if totals[facts.currency] == nil {
			totals[facts.currency] = new(settlementAccounts)
		}
		totals[facts.currency].add(accounts)
	}
	// The existing journal independently sums signed movement amounts. Its
	// ordered currencies and each clearing account must agree exactly.
	if len(totals) != len(journal.Currencies) {
		return nil, errors.New("settlement ledger and sales journal currencies disagree")
	}
	for _, currency := range journal.Currencies {
		accounts := totals[currency.Currency]
		if accounts == nil {
			return nil, errors.New("a sales journal currency has no settlement accounts")
		}
		lines, debits, credits, err := accounts.postings()
		if err != nil {
			return nil, err
		}
		clearing := &accounts[processorClearing]
		net := new(big.Int).Sub(&clearing.debit, &clearing.credit).String()
		if net != currency.NetMinor {
			return nil, errors.New("the processor clearing account and sales journal net disagree")
		}
		ledger.Currencies = append(ledger.Currencies, &v1.SettlementCurrency{Currency: currency.Currency, Accounts: lines,
			DebitsMinor: debits, CreditsMinor: credits, ProcessorNetMinor: net})
	}
	return ledger, nil
}
