package commerce

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/google/uuid"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// Archived native statements predate a merchant-ID field in their public
// export. Resolve their merchant from the local immutable orders and offers.
// Never ask the operator to guess a merchant or treat a file as a fresh read.
func (book *ProductionCostBook) RecoverTestFees(ctx context.Context, db *sql.DB, business, product string, ledger *v1.SettlementLedger, documents map[string][]byte) error {
	if db == nil || ledger == nil || !ledger.TestMode || ledger.BusinessId != business || ledger.ProductId != product || !costID.MatchString(business) || !costID.MatchString(product) {
		return errors.New("the archived test ledger must belong to the selected business and product")
	}
	if int(ledger.SourceCount) != len(documents) {
		return errors.New("supply the exact source statements used by this ledger")
	}
	type binding struct{ edition, packet, archive string }
	orders := map[string]binding{}
	sources := newSettlementSources(business, product, ledger.Month)
	for digest, raw := range documents {
		if len(raw) == 0 || len(raw) > MaxCostEvidenceBytes || fingerprint(raw) != digest {
			return errors.New("archived statement differs from its digest")
		}
		statement := new(v1.CommerceStatement)
		if err := protojson.Unmarshal(raw, statement); err != nil {
			return err
		}
		if statement.Schema != "omega.commerce-statement/v1" || !statement.TestMode || statement.BusinessId != business || statement.ProductId != product {
			return errors.New("archive includes a statement outside this test product")
		}
		canonical, err := StatementJSON(statement)
		if err != nil || !bytes.Equal(canonical, raw) {
			return errors.New("use the exact statement bytes exported by the native ledger")
		}
		for _, o := range statement.Orders {
			if _, err := uuid.Parse(o.GetOrderId()); err != nil {
				return errors.New("invalid order identity in archived statement")
			}
			b := binding{o.Edition, o.PacketSha256, o.ArchiveSha256}
			if other, ok := orders[o.OrderId]; ok && other != b {
				return errors.New("archived sources disagree about an order's edition")
			}
			orders[o.OrderId] = b
		}
		if err := sources.observe(statement); err != nil {
			return err
		}
	}
	reconstructed, err := sources.settlementLedger()
	if err != nil {
		return err
	}
	if !proto.Equal(reconstructed, ledger) {
		return errors.New("the archived order statements do not reproduce the complete supplied ledger")
	}
	if len(ledger.Entries) == 0 && len(ledger.Conflicts) == 0 {
		return nil
	}
	if len(orders) == 0 {
		return errors.New("missing local order attribution for this archive")
	}
	ids := make([]string, 0, len(orders))
	for id := range orders {
		ids = append(ids, id)
	}
	// The statement is an immutable snapshot. A single relational query sees
	// all matching offers in one database snapshot and reads no buyer fields.
	rows, err := db.QueryContext(ctx, `SELECT o.connection_id, o.id::text, o.offer_key, f.definition
		FROM omega_digital_orders o JOIN omega_digital_offers f USING(connection_id,offer_key)
		WHERE split_part(o.connection_id,'/',2)=$1 AND o.id::text=ANY($2::text[])`, business, ids)
	if err != nil {
		return errors.New("could not read local test orders for the archived ledger")
	}
	defer rows.Close()
	seen := map[string]bool{}
	var account string
	for rows.Next() {
		var connection, id, key string
		var definition []byte
		if err := rows.Scan(&connection, &id, &key, &definition); err != nil {
			return err
		}
		merchant, scope, ok := strings.Cut(connection, "/")
		o := new(v1.DigitalOffer)
		b := orders[id]
		if !ok || scope != business || !strings.HasPrefix(merchant, "acct_") || seen[id] || (account != "" && account != merchant) ||
			proto.Unmarshal(definition, o) != nil || offerKey(o) != key || o.BusinessId != business || o.ProductId != product ||
			o.Edition != b.edition || o.PacketSha256 != b.packet || o.ArchiveSha256 != b.archive {
			return errors.New("the archived order conflicts with its local merchant, product or release files")
		}
		account = merchant
		seen[id] = true
	}
	if err := rows.Err(); err != nil {
		return err
	}
	if len(seen) != len(orders) {
		return fmt.Errorf("only %d of %d archived orders match local immutable offers", len(seen), len(orders))
	}
	return book.RecordTestFees(account, ledger, documents)
}
