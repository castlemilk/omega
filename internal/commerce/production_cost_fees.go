package commerce

import (
	"bytes"
	"errors"
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	bolt "go.etcd.io/bbolt"
	"golang.org/x/text/currency"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// Stripe uses API minor units for charge and refund balance movements. ISK
// and UGX retain the two-decimal API representation. Payout limits do not
// apply to these movements. See https://docs.stripe.com/currencies.
func stripeFeeMicros(code string, fee int64) (int64, error) {
	unit, err := currency.ParseISO(code)
	if err != nil || unit.String() == "XXX" {
		return 0, errors.New("unrecognised Stripe settlement currency")
	}
	factor := int64(10000)
	switch code {
	case "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "vnd", "vuv", "xaf", "xof", "xpf":
		factor = 1000000
	case "bhd", "jod", "kwd", "omr", "tnd":
		factor = 1000
	}
	result := new(big.Int).Mul(big.NewInt(fee), big.NewInt(factor))
	if !result.IsInt64() {
		return 0, errors.New("Stripe fee exceeds the cost amount range")
	}
	return result.Int64(), nil
}

type feeWitness struct {
	order, edition, packet, artifact, observedAt string
	movement                                     *v1.CommerceBalanceMovement
}

func feeWitnesses(raw []byte, business, product string) (map[string]feeWitness, error) {
	s := new(v1.CommerceStatement)
	if err := protojson.Unmarshal(raw, s); err != nil {
		return nil, err
	}
	if s.Schema != "omega.commerce-statement/v1" || !s.TestMode || s.BusinessId != business || s.ProductId != product {
		return nil, errors.New("fee evidence must identify this product and the isolated test merchant statement")
	}
	moves := map[string]feeWitness{}
	for _, order := range s.Orders {
		if len(order.GetMovements()) == 0 {
			continue
		}
		if order.GetVerifiedAt().GetValue() == "" || !costDigest.MatchString(order.ArchiveSha256) || !costDigest.MatchString(order.PacketSha256) {
			return nil, errors.New("a fee is missing its verified order and release archive")
		}
		for _, m := range order.Movements {
			if m == nil || !strings.HasPrefix(m.Id, "txn_") || !validCurrency(m.Currency) ||
				!((m.Kind == "charge" && m.AmountMinor > 0) || (m.Kind == "refund" && m.AmountMinor < 0)) {
				return nil, errors.New("a fee source contains an invalid balance movement")
			}
			net := new(big.Int).Sub(big.NewInt(m.AmountMinor), big.NewInt(m.FeeMinor))
			if net.Cmp(big.NewInt(m.NetMinor)) != 0 {
				return nil, errors.New("fee source amount, fee and net do not reconcile")
			}
			if _, ok := moves[m.Id]; ok {
				return nil, errors.New("the source repeats a balance transaction")
			}
			moves[m.Id] = feeWitness{order.OrderId, order.Edition, order.PacketSha256, order.ArchiveSha256, s.VerifiedAt, m}
		}
	}
	return moves, nil
}

func (f feeWitness) matches(other feeWitness) bool {
	return f.order == other.order && f.edition == other.edition && f.packet == other.packet && f.artifact == other.artifact && proto.Equal(f.movement, other.movement)
}

func (f feeWitness) receipt(entry *v1.SalesJournalEntry, account, business, product, month string) (*v1.ProductionCostReceipt, error) {
	m := f.movement
	when, err := time.Parse(time.RFC3339Nano, entry.OccurredAt)
	if err != nil {
		return nil, err
	}
	sourceTime, err := time.Parse(time.RFC3339Nano, m.GetOccurredAt())
	if err != nil || f.observedAt != entry.AttestedAt || !sourceTime.Equal(when) || when.UTC().Format("2006-01") != month || m.Id != entry.TransactionId ||
		m.Kind != entry.Kind || m.Currency != entry.Currency || f.order != entry.OrderId || f.edition != entry.Edition || f.packet != entry.PacketSha256 ||
		strconv.FormatInt(m.AmountMinor, 10) != entry.AmountMinor || strconv.FormatInt(m.FeeMinor, 10) != entry.FeeMinor || strconv.FormatInt(m.NetMinor, 10) != entry.NetMinor {
		return nil, errors.New("the ledger movement differs from its exact order statement")
	}
	fee, err := stripeFeeMicros(m.Currency, m.FeeMinor)
	if err != nil {
		return nil, err
	}
	return &v1.ProductionCostReceipt{
		Provider: "stripe-test", Account: account, LineId: m.Id, Simulated: proto.Bool(true),
		ServiceDate: when.UTC().Format(time.DateOnly), Category: v1.ProductionCostCategory_PRODUCTION_COST_CATEGORY_CHANNEL, Stage: costIncurred,
		Currency: strings.ToUpper(m.Currency), AmountMicros: &fee, EvidenceSha256: entry.SourceSha256,
		SourceObservedAt: entry.AttestedAt,
		Description:      "Processor fee on the isolated test " + m.Kind + ".",
		AllocationBasis:  "The balance transaction belongs to one order for this edition.",
		Targets:          []*v1.ProductionCostTarget{{BusinessId: business, ProductId: product, RunId: f.order, Edition: f.edition, ArtifactSha256: f.artifact, ShareBps: 10000}},
	}, nil
}

// RecordTestFees attaches the first matching provider statement to each
// balance identity. Fresh verifications can carry a different attestation
// time. All other movement facts and the original order must still match.
func (book *ProductionCostBook) RecordTestFees(account string, ledger *v1.SettlementLedger, documents map[string][]byte) error {
	if ledger == nil || !ledger.TestMode || !strings.HasPrefix(account, "acct_") || !costID.MatchString(account) || !costID.MatchString(ledger.BusinessId) || !costID.MatchString(ledger.ProductId) {
		return errors.New("fee attribution requires a scoped, verified test merchant and ledger")
	}
	if len(ledger.Conflicts) > 0 {
		return errors.New("conflicting balance transactions need review before recording this batch of fees")
	}
	type observedFee struct {
		receipt *v1.ProductionCostReceipt
		witness feeWitness
	}
	observed := make([]observedFee, 0, len(ledger.Entries))
	cache := map[string]map[string]feeWitness{}
	witnesses := func(sha string, raw []byte) (map[string]feeWitness, error) {
		if saved, ok := cache[sha]; ok {
			return saved, nil
		}
		if !costDigest.MatchString(sha) || len(raw) == 0 || len(raw) > MaxCostEvidenceBytes || fingerprint(raw) != sha {
			return nil, errors.New("missing or changed source statement for a processor fee")
		}
		saved, err := feeWitnesses(raw, ledger.BusinessId, ledger.ProductId)
		if err != nil {
			return nil, err
		}
		cache[sha] = saved
		return saved, nil
	}
	for _, entry := range ledger.Entries {
		movement := entry.GetMovement()
		if movement == nil {
			return errors.New("missing processor movement")
		}
		items, err := witnesses(movement.SourceSha256, documents[movement.SourceSha256])
		if err != nil {
			return err
		}
		found, ok := items[movement.TransactionId]
		if !ok {
			return errors.New("the processor fee is absent from its source statement")
		}
		r, err := found.receipt(movement, account, ledger.BusinessId, ledger.ProductId, ledger.Month)
		if err != nil {
			return err
		}
		observed = append(observed, observedFee{r, found})
	}
	return book.db.Update(func(tx *bolt.Tx) error {
		for _, fee := range observed {
			r := fee.receipt
			if heads := tx.Bucket(headBucket); heads != nil {
				if current := heads.Get(costSourceKey(r)); current != nil {
					receipts, sources := tx.Bucket(receiptBucket), tx.Bucket(sourceBucket)
					if receipts == nil || sources == nil {
						return errors.New("saved processor fee evidence is missing")
					}
					raw := receipts.Get(current)
					if !bytes.Equal(current, []byte(fingerprint(raw))) {
						return errors.New("stored fee receipt has changed")
					}
					prior := new(v1.ProductionCostReceipt)
					if err := protojson.Unmarshal(raw, prior); err != nil {
						return err
					}
					previousSource := sources.Get([]byte(prior.EvidenceSha256))
					if previousSource == nil || fingerprint(previousSource) != prior.EvidenceSha256 {
						return errors.New("stored fee evidence is missing or has changed")
					}
					old, err := witnesses(prior.EvidenceSha256, previousSource)
					if err != nil {
						return err
					}
					// The original source and correction chain stay in the book.
					prior.EvidenceSha256 = r.EvidenceSha256
					prior.SourceObservedAt = r.SourceObservedAt
					prior.PreviousReceiptSha256 = ""
					prior.RevisionReason = ""
					if !proto.Equal(prior, r) || !fee.witness.matches(old[r.LineId]) {
						return fmt.Errorf("the new fee differs from recorded receipt %s; review this source line", current)
					}
					continue
				}
			}
			if _, err := saveCostReceipt(tx, r, documents[r.EvidenceSha256], false); err != nil {
				return err
			}
		}
		return nil
	})
}
