package commerce

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const (
	maxStatementOrders = 500
	maxBusinessRows    = 10000
	maxStatementBytes  = 160000
)

var statementEdition = regexp.MustCompile(`^[a-zA-Z0-9._-]{1,100}$`)

// ErrStatementRateLimited defers the whole check. An interrupted provider
// read cannot establish a change to any previously reported order or balance.
var ErrStatementRateLimited = errors.New("Stripe is rate-limiting test order reads. Retry the statement later")

func statementRateLimited(err error) bool {
	var provider *stripe.Error
	return errors.As(err, &provider) && provider.HTTPStatusCode == http.StatusTooManyRequests && provider.Code != stripe.ErrorCodeLockTimeout
}

// StatementJSON includes empty arrays and zero counts, while absent money and
// timestamps retain protobuf presence. The final newline is part of the export.
func StatementJSON(statement *v1.CommerceStatement) ([]byte, error) {
	raw, err := (protojson.MarshalOptions{EmitDefaultValues: true}).Marshal(statement)
	if err != nil {
		return nil, err
	}
	var out bytes.Buffer
	if err := json.Indent(&out, raw, "", "  "); err != nil {
		return nil, err
	}
	out.WriteByte('\n')
	if out.Len() > maxStatementBytes {
		return nil, fmt.Errorf("the statement exceeds %d bytes; export a shorter order period", maxStatementBytes)
	}
	return out.Bytes(), nil
}

// StatementWindow returns the inclusive UTC start and exclusive end of an accepted order period.
func StatementWindow(from, through string, now time.Time) (time.Time, time.Time, error) {
	first, err := time.Parse(time.DateOnly, from)
	last, lastErr := time.Parse(time.DateOnly, through)
	if err != nil || lastErr != nil || first.Year() < 1 || last.Before(first) ||
		last.After(now.UTC()) || last.After(first.AddDate(0, 0, 365)) {
		return time.Time{}, time.Time{}, errors.New("choose an inclusive UTC window of 1–366 days in YYYY-MM-DD format ending today or earlier")
	}
	return first, last.AddDate(0, 0, 1), nil
}

func validDigest(s string) bool {
	if len(s) != 64 || strings.ToLower(s) != s {
		return false
	}
	_, err := hex.DecodeString(s)
	return err == nil
}

func validCurrency(s string) bool {
	return len(s) == 3 && strings.IndexFunc(s, func(r rune) bool { return r < 'a' || r > 'z' }) == -1
}

// A damaged offer cannot establish which product owns a row. Only its count
// leaves the account/business boundary. Other identifiable products are skipped.
func (s *Shop) statementCohort(ctx context.Context, business, product string, first, end time.Time) ([]order, uint32, error) {
	asOf := time.Now()
	rows, err := s.db.QueryContext(ctx, `SELECT o.id,o.created_at,o.offer_key,f.definition,coalesce(o.session_id,''),
		o.payment_id,o.charge_id,o.payment,o.refunded,o.entitled_at,o.downloads
		FROM omega_digital_orders o LEFT JOIN omega_digital_offers f USING (connection_id,offer_key)
		WHERE o.connection_id=$1 AND o.created_at >= $2 AND o.created_at < $3
		ORDER BY o.created_at,o.id LIMIT $4`, s.connection, first, end, maxBusinessRows+1)
	if err != nil {
		return nil, 0, errors.New("the scoped order database could not be read")
	}
	defer func() { _ = rows.Close() }()
	var cohort []order
	var unknown uint32
	for scanned := 0; rows.Next(); scanned++ {
		if scanned == maxBusinessRows {
			return nil, 0, fmt.Errorf("the business window exceeds %d orders; select a smaller date range", maxBusinessRows)
		}
		var a order
		var definition []byte
		var downloads int32
		if err := rows.Scan(&a.id, &a.created, &a.offerID, &definition, &a.session, &a.payment, &a.charge, &a.state, &a.refunded, &a.entitled, &downloads); err != nil {
			return nil, 0, err
		}
		a.offer = new(v1.DigitalOffer)
		if err := proto.Unmarshal(definition, a.offer); err != nil || offerKey(a.offer) != a.offerID ||
			a.offer.BusinessId != business || a.offer.ProductId == "" {
			unknown++
			continue
		}
		if a.offer.ProductId != product {
			continue
		}
		if !statementEdition.MatchString(a.offer.Edition) || !validDigest(a.offer.PacketSha256) || !validDigest(a.offer.ArchiveSha256) ||
			!validCurrency(a.offer.Currency) || a.offer.AmountMinor <= 0 || downloads < 0 || a.created.After(asOf) {
			unknown++
			continue
		}
		if len(cohort) == maxStatementOrders {
			return nil, 0, fmt.Errorf("the product window exceeds %d orders; select a smaller date range", maxStatementOrders)
		}
		a.downloads = uint32(downloads)
		cohort = append(cohort, a)
	}
	return cohort, unknown, rows.Err()
}

// OperatorStatement reads only the account selected by its test credential.
// The window selects orders by creation time; later refunds and downloads
// belong to their original order. Each provider read is independent.
func OperatorStatement(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, from, through string) (*v1.CommerceStatement, error) {
	first, end, err := StatementWindow(from, through, time.Now())
	if err != nil {
		return nil, err
	}
	if db == nil || gateway == nil || business == "" || product == "" {
		return nil, errors.New("a scoped test merchant and order database are required")
	}
	account, err := gateway.Account(ctx)
	if statementRateLimited(err) {
		return nil, ErrStatementRateLimited
	}
	if err != nil {
		return nil, errors.New("could not verify the test merchant account with Stripe")
	}
	s := &Shop{db: db, provider: gateway, connection: account + "/" + business}
	return s.statement(ctx, gateway, business, product, first, end)
}

func (s *Shop) statement(ctx context.Context, gateway *StripeTest, business, product string, first, end time.Time) (*v1.CommerceStatement, error) {
	cohort, unknown, err := s.statementCohort(ctx, business, product, first, end)
	if err != nil {
		return nil, err
	}
	report := &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", BusinessId: business, ProductId: product,
		TestMode: true, FromDay: first.Format(time.DateOnly), ThroughDay: end.AddDate(0, 0, -1).Format(time.DateOnly), UnresolvedScopeOrders: unknown, Coverage: "complete"}
	movementCounts := make(map[string]int)
	for _, a := range cohort {
		row, err := s.statementOrder(ctx, gateway, a)
		if err != nil {
			return nil, err
		}
		report.Orders = append(report.Orders, row)
		for _, m := range row.Movements {
			movementCounts[m.Id]++
		}
		if row.VerifiedAt == nil || !row.BalanceComplete || row.UnresolvedEvents != 0 || row.Payment == pending || row.Payment == disputed {
			report.Coverage = "partial"
		}
	}
	// A Stripe movement can only belong to one order. Preserve independent
	// evidence when corrupt or contradictory provider links claim it twice.
	for _, row := range report.Orders {
		movements := row.Movements[:0]
		for _, m := range row.Movements {
			if movementCounts[m.Id] != 1 {
				row.BalanceComplete = false
				report.Coverage = "partial"
				continue
			}
			movements = append(movements, m)
		}
		row.Movements = movements
	}
	if unknown != 0 {
		report.Coverage = "partial"
	} else if len(cohort) == 0 {
		report.Coverage = "empty"
	}
	report.VerifiedAt = time.Now().UTC().Format(time.RFC3339Nano)
	return report, nil
}

func (s *Shop) statementOrder(ctx context.Context, gateway *StripeTest, a order) (*v1.CommerceStatementOrder, error) {
	row := &v1.CommerceStatementOrder{OrderId: a.id, CreatedAt: a.created.UTC().Format(time.RFC3339Nano),
		Edition: a.offer.Edition, PacketSha256: a.offer.PacketSha256, ArchiveSha256: a.offer.ArchiveSha256,
		Currency: a.offer.Currency, QuotedMinor: a.offer.AmountMinor, DownloadsIssued: a.downloads}
	f, err := a.checkedFact(ctx, gateway.statementFact)
	if statementRateLimited(err) {
		return nil, ErrStatementRateLimited
	}
	if err == nil && f.captured != nil && knownDispute(f.dispute) {
		row.Payment = f.state
		row.CapturedMinor = wrapperspb.Int64(*f.captured)
		row.RefundedMinor = wrapperspb.Int64(f.refunded)
		if f.dispute != "" {
			row.DisputeStatus = wrapperspb.String(f.dispute)
		}
		row.BalanceComplete = f.charge == ""
		if f.charge != "" {
			if err := gateway.statementBalance(ctx, row, f, a.created); err != nil {
				return nil, err
			}
		}
		if row.CapturedMinor != nil {
			row.VerifiedAt = wrapperspb.String(time.Now().UTC().Format(time.RFC3339Nano))
		}
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	// Include a signed event for a newly identified charge/payment even when
	// the checkout worker has not yet persisted that provider reference.
	err = s.db.QueryRowContext(ctx, `SELECT count(*) FILTER (WHERE i.status='processed'),count(*) FILTER (WHERE i.status<>'processed')
		FROM omega_digital_orders o JOIN omega_digital_inbox i ON i.connection_id=o.connection_id
		WHERE o.connection_id=$1 AND o.id=$2 AND (i.order_id=o.id OR (i.order_id IS NULL AND (`+subjectMatch+`
			OR (i.subject_kind='payment' AND i.subject_id=nullif($3,'')) OR (i.subject_kind='charge' AND i.subject_id=nullif($4,'')))))`,
		s.connection, a.id, f.payment, f.charge).Scan(&row.ProcessedEvents, &row.UnresolvedEvents)
	if err != nil {
		return nil, err
	}
	return row, nil
}

func knownDispute(status string) bool {
	switch status {
	case "", "warning_needs_response", "warning_under_review", "warning_closed", "needs_response", "under_review", "won", "lost", "prevented":
		return true
	default:
		return false
	}
}
