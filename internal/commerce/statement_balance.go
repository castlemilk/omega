package commerce

import (
	"context"
	"encoding/json"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

var balanceID = regexp.MustCompile(`^txn_[a-zA-Z0-9_]{1,150}$`)

// A charge or refund expansion binds this transaction to the order without
// requiring permission to list or retrieve account-wide balance transactions.
func statementMovement(raw json.RawMessage, source, kind, currency string, amount, orderCreated int64) *v1.CommerceBalanceMovement {
	// Presence matters for the three signed amounts: a missing fee cannot
	// be read as a confirmed zero. Stripe may expand source or return its ID.
	var b struct {
		ID, Object, Status, Type, Currency string
		Source                             *stripe.BalanceTransactionSource
		Created                            int64
		Amount, Fee, Net                   *int64
	}
	if json.Unmarshal(raw, &b) != nil || !balanceID.MatchString(b.ID) || b.Object != "balance_transaction" ||
		b.Source == nil || b.Source.ID != source || b.Created <= 0 || b.Created < orderCreated ||
		b.Created > time.Now().Unix() || !validCurrency(b.Currency) || (b.Status != "available" && b.Status != "pending") ||
		b.Amount == nil || b.Fee == nil || b.Net == nil {
		return nil
	}
	gross, fee, net := *b.Amount, *b.Fee, *b.Net
	if kind == "charge" && ((b.Type != "charge" && b.Type != "payment") || gross <= 0) ||
		kind == "refund" && ((b.Type != "refund" && b.Type != "payment_refund") || gross >= 0) ||
		(b.Currency == currency && gross != amount) {
		return nil
	}
	if (fee > 0 && gross < math.MinInt64+fee) || (fee < 0 && gross > math.MaxInt64+fee) || net != gross-fee {
		return nil
	}
	return &v1.CommerceBalanceMovement{Id: b.ID, Kind: kind, OccurredAt: time.Unix(b.Created, 0).UTC().Format(time.RFC3339),
		Currency: b.Currency, AmountMinor: gross, FeeMinor: fee, NetMinor: net}
}

func (p *StripeTest) statementBalance(ctx context.Context, row *v1.CommerceStatementOrder, f fact, created time.Time) error {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	// Dispute debits/reversals are outside this charge/refund statement.
	complete := f.dispute == ""
	seenMovements := make(map[string]bool)
	add := func(raw json.RawMessage, source, kind string, amount int64) {
		m := statementMovement(raw, source, kind, row.Currency, amount, created.Unix())
		if m == nil || seenMovements[m.Id] {
			complete = false
			return
		}
		seenMovements[m.Id] = true
		row.Movements = append(row.Movements, m)
	}
	add(f.chargeBalance, f.charge, "charge", *f.captured)
	params := &stripe.RefundListParams{Charge: stripe.String(f.charge)}
	params.Limit = stripe.Int64(100)
	params.AddExpand("data.balance_transaction")
	seenRefunds := make(map[string]bool)
	var succeeded, nonfinal int64
	allRefunds := true
	refunds := p.client.V1Refunds.List(ctx, params)
	for r, err := range refunds.All(ctx) {
		if statementRateLimited(err) {
			return ErrStatementRateLimited
		}
		if err != nil {
			allRefunds = false
			break
		}
		if r == nil || r.Object != "refund" || !strings.HasPrefix(r.ID, "re_") || seenRefunds[r.ID] || r.Charge == nil || r.Charge.ID != f.charge ||
			(r.PaymentIntent != nil && r.PaymentIntent.ID != f.payment) || string(r.Currency) != row.Currency ||
			r.Amount <= 0 || r.Amount > *f.captured {
			allRefunds = false
			break
		}
		seenRefunds[r.ID] = true
		switch r.Status {
		case "succeeded":
			if r.Amount > *f.captured-succeeded {
				allRefunds = false
				break
			}
			succeeded += r.Amount
			var source struct {
				BalanceTransaction json.RawMessage `json:"balance_transaction"`
			}
			if r.LastResponse != nil {
				_ = json.Unmarshal(r.LastResponse.RawJSON, &source)
			}
			add(source.BalanceTransaction, r.ID, "refund", -r.Amount)
		case "pending", "requires_action":
			if r.Amount > *f.captured-nonfinal {
				allRefunds = false
				break
			}
			nonfinal += r.Amount
			complete = false
		case "failed", "canceled":
			// Some failures have an additional reversal balance transaction.
			if r.BalanceTransaction != nil || r.FailureBalanceTransaction != nil {
				complete = false
			}
		default:
			allRefunds = false
		}
		if !allRefunds {
			break
		}
	}
	// A missing or malformed success response is not a verified empty list.
	var page struct {
		Object  string
		Data    []json.RawMessage
		HasMore *bool `json:"has_more"`
	}
	if resp := refunds.LastResponse(); resp == nil || json.Unmarshal(resp.RawJSON, &page) != nil ||
		page.Object != "list" || page.Data == nil || page.HasMore == nil || *page.HasMore {
		allRefunds = false
	}
	if !allRefunds || succeeded > f.refunded || f.refunded-succeeded > nonfinal {
		// A charge with zero refunds still supplies verified payment amounts
		// if refund enumeration failed. A positive ambiguous refund does not.
		complete = false
		if f.refunded != 0 || succeeded != 0 {
			row.Payment = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_UNSPECIFIED
			row.CapturedMinor, row.RefundedMinor, row.VerifiedAt, row.DisputeStatus = nil, nil, nil, nil
			row.Movements = nil
		}
	} else {
		row.RefundedMinor = wrapperspb.Int64(succeeded)
		if row.Payment == refunded && succeeded != *f.captured {
			row.Payment = paid
			if f.dispute != "" && f.dispute != "won" && f.dispute != "warning_closed" {
				row.Payment = disputed
			}
		}
	}
	sort.Slice(row.Movements, func(i, j int) bool {
		a, b := row.Movements[i], row.Movements[j]
		if a.OccurredAt == b.OccurredAt {
			return a.Id < b.Id
		}
		return a.OccurredAt < b.OccurredAt
	})
	row.BalanceComplete = complete
	return nil
}
