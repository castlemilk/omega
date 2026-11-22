package commerce

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"errors"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/proto"
)

// OperatorSalesJournal reports independently observed test merchant movements by UTC month.
func OperatorSalesJournal(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, month string) (*v1.SalesJournal, error) {
	sources, err := readSettlementSources(ctx, db, gateway, business, product, month, nil)
	if err != nil {
		return nil, err
	}
	return sources.salesJournal()
}

// Both monthly reports use the same scoped order and Stripe verifier. A
// selected movement can belong to an older order, and any observed movement
// from that order can establish or contradict its lineage across month cuts.
func readSettlementSources(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, month string, save SettlementSourceSink) (*settlementSources, error) {
	now := time.Now().UTC()
	first, err := time.Parse("2006-01", month)
	if err != nil || first.Year() < 1 || first.After(now) {
		return nil, errors.New("choose a current or earlier UTC month in YYYY-MM format")
	}
	if db == nil || gateway == nil || business == "" || product == "" {
		return nil, errors.New("a scoped test merchant and order database are required")
	}
	account, err := gateway.Account(ctx)
	if limit := statementReadLimit(err, "account"); limit != nil {
		return nil, limit
	}
	if err != nil {
		return nil, errors.New("could not verify the test merchant account with Stripe")
	}
	shop := &Shop{db: db, provider: gateway, connection: account + "/" + business}
	rows, err := db.QueryContext(ctx, `SELECT DISTINCT (created_at AT TIME ZONE 'UTC')::date::text AS day
		FROM omega_digital_orders WHERE connection_id=$1 AND created_at < $2 ORDER BY day`, shop.connection, first.AddDate(0, 1, 0))
	if err != nil {
		return nil, errors.New("could not read the scoped order creation dates")
	}
	defer func() { _ = rows.Close() }()
	var days []time.Time
	for rows.Next() {
		var value string
		if err := rows.Scan(&value); err != nil {
			return nil, err
		}
		day, err := time.Parse(time.DateOnly, value)
		if err != nil {
			return nil, err
		}
		days = append(days, day)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sources := newSettlementSources(business, product, month)
	sources.save = save
	sources.merchant = account
	for _, day := range days {
		report, err := shop.statement(ctx, gateway, business, product, day, day.AddDate(0, 0, 1))
		if err != nil {
			return nil, err
		}
		if len(report.Orders) == 0 && report.UnresolvedScopeOrders == 0 {
			continue
		}
		if err := sources.observe(report); err != nil {
			return nil, err
		}
	}
	return sources, nil
}

// The same balance identity and economic facts may appear in several sources.
// Keep a source per distinct version. Identical amounts alone say nothing
// about whether two separate Stripe transactions represent the same movement.
type journalFacts struct {
	order, edition, packet, kind, currency string
	occurred                               time.Time
	amount, fee, net                       int64
}

type settlementSources struct {
	merchant  string
	scope     *v1.SalesJournal
	movements map[string]map[journalFacts]*v1.SalesJournalEntry
	witnesses map[settlementPair]settlementWitness
	save      SettlementSourceSink
}

func newSettlementSources(business, product, month string) *settlementSources {
	return &settlementSources{
		scope:     &v1.SalesJournal{Month: month, BusinessId: business, ProductId: product, TestMode: true},
		movements: make(map[string]map[journalFacts]*v1.SalesJournalEntry),
		witnesses: make(map[settlementPair]settlementWitness),
	}
}

func (sources *settlementSources) observe(s *v1.CommerceStatement) error {
	j := sources.scope
	if !s.TestMode || s.BusinessId != j.BusinessId || s.ProductId != j.ProductId {
		return errors.New("journal source scope mismatch")
	}
	raw, err := StatementJSON(s)
	if err != nil {
		return err
	}
	digest := fmt.Sprintf("%x", sha256.Sum256(raw))
	source := "omega/" + s.FromDay + "/" + digest
	attested, err := time.Parse(time.RFC3339Nano, s.VerifiedAt)
	if err != nil {
		return err
	}
	j.SourceCount++
	last, _ := time.Parse(time.RFC3339Nano, j.LastCheckedAt)
	if attested.After(last) {
		j.LastCheckedAt = s.VerifiedAt
	}
	addGap := func(id string) {
		j.IncompleteEvidence = true
		j.Gaps = append(j.Gaps, &v1.SalesJournalGap{SourceId: source, SourceSha256: digest, OrderId: id})
	}
	if s.UnresolvedScopeOrders > 0 {
		addGap("")
	}
	for _, o := range s.Orders {
		if !o.BalanceComplete {
			addGap(o.OrderId)
		}
		sources.observeWitnesses(o, settlementWitness{source, digest, attested})
		for _, m := range o.Movements {
			when, err := time.Parse(time.RFC3339Nano, m.OccurredAt)
			if err != nil {
				return err
			}
			facts := journalFacts{o.OrderId, o.Edition, o.PacketSha256, m.Kind, m.Currency, when.UTC(), m.AmountMinor, m.FeeMinor, m.NetMinor}
			versions := sources.movements[m.Id]
			if versions == nil {
				versions = make(map[journalFacts]*v1.SalesJournalEntry)
				sources.movements[m.Id] = versions
			}
			if prior := versions[facts]; prior != nil {
				at, _ := time.Parse(time.RFC3339Nano, prior.AttestedAt)
				if at.Before(attested) || (at.Equal(attested) && prior.SourceId <= source) {
					continue
				}
			}
			versions[facts] = &v1.SalesJournalEntry{TransactionId: m.Id, Kind: m.Kind, OccurredAt: when.UTC().Format(time.RFC3339Nano),
				Currency: m.Currency, AmountMinor: strconv.FormatInt(m.AmountMinor, 10), FeeMinor: strconv.FormatInt(m.FeeMinor, 10),
				NetMinor: strconv.FormatInt(m.NetMinor, 10), OrderId: o.OrderId, Edition: o.Edition, PacketSha256: o.PacketSha256,
				SourceId: source, SourceSha256: digest, AttestedAt: s.VerifiedAt}
		}
	}
	if sources.save != nil {
		return sources.save(digest, raw)
	}
	return nil
}

type journalAmounts struct {
	charges, refunds, fees, net big.Int
	count                       uint32
}

func (sources *settlementSources) salesJournal() (*v1.SalesJournal, error) {
	j := proto.CloneOf(sources.scope)
	amounts := make(map[string]*journalAmounts)
	for id, versions := range sources.movements {
		var facts journalFacts
		var entry *v1.SalesJournalEntry
		for f, e := range versions {
			if f.occurred.Format("2006-01") == j.Month {
				facts, entry = f, e
				break
			}
		}
		if entry == nil {
			continue
		}
		if len(versions) > 1 {
			conflict := &v1.SalesJournalConflict{TransactionId: id}
			for _, e := range versions {
				conflict.Versions = append(conflict.Versions, e)
			}
			sort.Slice(conflict.Versions, func(i, k int) bool {
				a, b := conflict.Versions[i], conflict.Versions[k]
				ta, _ := time.Parse(time.RFC3339Nano, a.AttestedAt)
				tb, _ := time.Parse(time.RFC3339Nano, b.AttestedAt)
				if ta.Equal(tb) {
					return a.SourceId < b.SourceId
				}
				return ta.Before(tb)
			})
			j.Conflicts = append(j.Conflicts, conflict)
			continue
		}
		sum := amounts[facts.currency]
		if sum == nil {
			sum = new(journalAmounts)
			amounts[facts.currency] = sum
		}
		switch facts.kind {
		case "charge":
			sum.charges.Add(&sum.charges, big.NewInt(facts.amount))
		case "refund":
			sum.refunds.Sub(&sum.refunds, big.NewInt(facts.amount))
		default:
			return nil, errors.New("unknown settlement movement")
		}
		sum.fees.Add(&sum.fees, big.NewInt(facts.fee))
		sum.net.Add(&sum.net, big.NewInt(facts.net))
		sum.count++
		j.Entries = append(j.Entries, entry)
	}
	for currency, sum := range amounts {
		net := new(big.Int).Sub(&sum.charges, &sum.refunds)
		if net.Sub(net, &sum.fees).Cmp(&sum.net) != 0 {
			return nil, errors.New("the recorded settlement movements do not reconcile")
		}
		j.Currencies = append(j.Currencies, &v1.SalesJournalCurrency{Currency: currency, ChargesMinor: sum.charges.String(),
			RefundsMinor: sum.refunds.String(), FeesMinor: sum.fees.String(), NetMinor: sum.net.String(), MovementCount: sum.count})
	}
	sort.Slice(j.Currencies, func(i, k int) bool { return j.Currencies[i].Currency < j.Currencies[k].Currency })
	sort.Slice(j.Conflicts, func(i, k int) bool { return j.Conflicts[i].TransactionId < j.Conflicts[k].TransactionId })
	sort.Slice(j.Entries, func(i, k int) bool {
		a, b := j.Entries[i], j.Entries[k]
		ta, _ := time.Parse(time.RFC3339Nano, a.OccurredAt)
		tb, _ := time.Parse(time.RFC3339Nano, b.OccurredAt)
		if ta.Equal(tb) {
			return a.TransactionId < b.TransactionId
		}
		return ta.After(tb)
	})
	return j, nil
}
