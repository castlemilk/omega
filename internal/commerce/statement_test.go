package commerce

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func statementStripe(t *testing.T, serve http.HandlerFunc) *StripeTest {
	t.Helper()
	server := httptest.NewServer(serve)
	t.Cleanup(server.Close)
	backends := stripe.NewBackendsWithConfig(&stripe.BackendConfig{URL: stripe.String(server.URL), HTTPClient: server.Client(), MaxNetworkRetries: stripe.Int64(0), LeveledLogger: &stripe.LeveledLogger{Level: stripe.LevelNull}})
	return &StripeTest{client: stripe.NewClient("sk_test_fixture", stripe.WithBackends(backends))}
}

func balanceFixture(id, source, kind, currency string, amount, fee int64, created time.Time) obj {
	return obj{"id": id, "object": "balance_transaction", "source": source, "type": kind, "currency": currency,
		"amount": amount, "fee": fee, "net": amount - fee, "created": created.Unix(), "status": "pending"}
}

func TestStatementRefundAndSettlementEvidence(t *testing.T) {
	now := time.Now().Add(-time.Minute)
	type facts struct {
		charge, refund, refundBalance obj
		chargeRefunded                int64
	}
	for _, tc := range []struct {
		name      string
		change    func(*facts)
		complete  bool
		movements int
		refunded  int64 // negative implies unknown
	}{
		{"complete converted charge and partial refund", func(*facts) {}, true, 2, 300},
		{"known full refund without balance", func(f *facts) {
			f.refund["amount"] = int64(1200)
			f.chargeRefunded = 1200
			delete(f.refund, "balance_transaction")
		}, false, 1, 1200},
		{"unavailable fee", func(f *facts) { delete(f.charge, "fee") }, false, 1, 300},
		{"mismatched balance source", func(f *facts) { f.charge["source"] = "ch_other" }, false, 1, 300},
		{"invalid net", func(f *facts) { f.refundBalance["net"] = -500 }, false, 1, 300},
		{"balance before order", func(f *facts) { f.charge["created"] = now.Unix() - 99 }, false, 1, 300},
		{"inconsistent same currency", func(f *facts) { f.charge["currency"] = "aud" }, false, 1, 300},
		{"failed refund with balance reference", func(f *facts) { f.refund["status"] = "failed"; f.chargeRefunded = 0 }, false, 1, 0},
		{"pending refund", func(f *facts) { f.refund["status"] = "pending" }, false, 1, 0},
		{"unrelated refund", func(f *facts) { f.refund["charge"] = "ch_other" }, false, 0, -1},
		{"refund API unavailable", func(f *facts) { f.refund = nil }, false, 0, -1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := facts{balanceFixture("txn_charge", "ch_one", "charge", "usd", 780, 19, now),
				obj{"object": "refund", "id": "re_one", "status": "succeeded", "currency": "aud", "amount": int64(300), "charge": "ch_one", "payment_intent": "pi_one", "balance_transaction": "txn_refund"},
				balanceFixture("txn_refund", "re_one", "refund", "usd", -195, 0, now), 300}
			tc.change(&f)
			if _, ok := f.refund["balance_transaction"]; ok {
				f.refund["balance_transaction"] = f.refundBalance
			}
			chargeRaw, err := json.Marshal(f.charge)
			require.NoError(t, err)
			client := statementStripe(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				switch r.URL.Path {
				case "/v1/refunds":
					if r.URL.Query().Get("charge") != "ch_one" || r.URL.Query().Get("expand[0]") != "data.balance_transaction" {
						t.Error("refund request escaped charge scope")
					}
					if f.refund == nil {
						w.WriteHeader(http.StatusForbidden)
						_ = json.NewEncoder(w).Encode(obj{"error": obj{"type": "permission_error", "message": "restricted sandbox permission"}})
						return
					}
					_ = json.NewEncoder(w).Encode(obj{"object": "list", "data": []obj{f.refund}, "has_more": false})
				default:
					http.NotFound(w, r)
				}
			})
			amountRefunded := f.chargeRefunded
			capture := int64(1200)
			payment := paid
			if amountRefunded == capture {
				payment = refunded
			}
			row := &v1.CommerceStatementOrder{Currency: "aud", CapturedMinor: wrapperspb.Int64(capture), RefundedMinor: wrapperspb.Int64(amountRefunded), Payment: payment, VerifiedAt: wrapperspb.String(now.Format(time.RFC3339))}
			client.statementBalance(t.Context(), row, fact{captured: &capture, charge: "ch_one", payment: "pi_one", chargeBalance: chargeRaw, refunded: amountRefunded, state: payment}, now)
			require.Equal(t, tc.complete, row.BalanceComplete)
			require.Len(t, row.Movements, tc.movements)
			if tc.refunded < 0 {
				require.Nil(t, row.RefundedMinor)
				require.Nil(t, row.CapturedMinor)
				require.Nil(t, row.VerifiedAt)
				return
			}
			require.Equal(t, tc.refunded, row.RefundedMinor.Value)
			require.Equal(t, capture, row.CapturedMinor.Value)
			if tc.complete {
				require.Equal(t, []string{"txn_charge", "txn_refund"}, []string{row.Movements[0].Id, row.Movements[1].Id})
				require.Equal(t, "usd", row.Movements[0].Currency)
				require.Equal(t, int64(761), row.Movements[0].NetMinor)
				require.Equal(t, "aud", row.Currency)
			}
		})
	}
}

func TestStatementScopesOrdersAndPreservesUnknowns(t *testing.T) {
	ctx := t.Context()
	shop, fixture, buyer := testShop(t, "http://127.0.0.1")
	account := strings.Split(shop.connection, "/")[0]
	offer := testOffer([]byte("frozen first edition"))
	first := uuid.NewString()
	privateValue := uuid.NewString()
	_, err := shop.Start(ctx, first, buyer)
	require.NoError(t, err)
	openOrder := func(edition, product, merchant string) string {
		pack := []byte(edition)
		o := testOffer(pack)
		o.Edition = edition
		o.ProductId = product
		store, err := Open(ctx, shop.db, merchant, shop.origin, testSecret, fixture, o, pack)
		require.NoError(t, err)
		id := uuid.NewString()
		_, err = store.Start(ctx, id, buyer)
		require.NoError(t, err)
		return id
	}
	second := openOrder("second", offer.ProductId, account)
	other := openOrder("other", "other-product", account)
	outsider := openOrder("unrelated", offer.ProductId, "acct_unrelated_"+uuid.NewString())
	corrupt := openOrder("damaged", offer.ProductId, account)
	before := openOrder("prior", offer.ProductId, account)
	day := time.Now().UTC().AddDate(0, 0, -2).Truncate(24 * time.Hour)
	_, err = shop.db.ExecContext(ctx, `UPDATE omega_digital_orders SET created_at=$2 WHERE connection_id=$1`, shop.connection, day)
	require.NoError(t, err)
	_, err = shop.db.ExecContext(ctx, `UPDATE omega_digital_orders SET created_at=$3 WHERE connection_id=$1 AND id IN ($2)`, shop.connection, before, day.Add(-time.Nanosecond*1000))
	require.NoError(t, err)
	_, err = shop.db.ExecContext(ctx, `UPDATE omega_digital_orders SET downloads=3 WHERE connection_id=$1 AND id=$2`, shop.connection, first)
	require.NoError(t, err)
	_, err = shop.db.ExecContext(ctx, `UPDATE omega_digital_offers SET definition='bad'::bytea WHERE connection_id=$1 AND offer_key=(SELECT offer_key FROM omega_digital_orders WHERE connection_id=$1 AND id=$2)`, shop.connection, corrupt)
	require.NoError(t, err)
	_, err = shop.db.ExecContext(ctx, `INSERT INTO omega_digital_inbox(connection_id,id,event_type,subject_kind,subject_id,observed_at,status) VALUES
		($1,'evt_processed','charge.succeeded','session',$2,1,'processed'),($1,'evt_unresolved','charge.refunded','charge','ch_paid',2,'needs_review')`, shop.connection, "cs_test_"+first)
	require.NoError(t, err)
	client := statementStripe(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		var value any
		switch r.URL.Path {
		case "/v1/account":
			value = obj{"id": account, "object": "account"}
		case "/v1/checkout/sessions/cs_test_" + first:
			meta := obj{"omega_order": first, "omega_offer": offerKey(offer)}
			charge := obj{"id": "ch_paid", "paid": true, "captured": true, "amount_captured": 1200, "amount_refunded": 0, "currency": "aud", "payment_intent": "pi_paid", "balance_transaction": balanceFixture("txn_paid", "ch_paid", "charge", "aud", 1200, 40, day)}
			pi := obj{"id": "pi_paid", "status": "succeeded", "amount": 1200, "amount_received": 1200, "currency": "aud", "metadata": meta, "latest_charge": charge}
			value = obj{"id": "cs_test_" + first, "mode": "payment", "status": "complete", "payment_status": "paid", "currency": "aud", "amount_total": 1200, "client_reference_id": first, "metadata": meta, "payment_intent": pi, "customer_email": "private@example.org", "client_secret": privateValue}
		case "/v1/checkout/sessions/cs_test_" + second:
			w.WriteHeader(http.StatusForbidden)
			_ = json.NewEncoder(w).Encode(obj{"error": obj{"type": "permission_error", "message": "unavailable"}})
			return
		case "/v1/refunds":
			value = obj{"object": "list", "data": []obj{}, "has_more": false}
		default:
			t.Errorf("unexpected provider request %s", r.URL.Path)
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(value)
	})
	on := day.Format(time.DateOnly)
	report, err := OperatorStatement(ctx, shop.db, client, offer.BusinessId, offer.ProductId, on, on)
	require.NoError(t, err)
	require.Equal(t, "partial", report.Coverage)
	require.EqualValues(t, 1, report.UnresolvedScopeOrders)
	require.Len(t, report.Orders, 2)
	require.Less(t, report.Orders[0].OrderId, report.Orders[1].OrderId)
	for _, row := range report.Orders {
		if row.OrderId == first {
			require.Equal(t, paid, row.Payment)
			require.EqualValues(t, 1200, row.CapturedMinor.Value)
			require.NotNil(t, row.RefundedMinor)
			require.EqualValues(t, 0, row.RefundedMinor.Value)
			require.EqualValues(t, 3, row.DownloadsIssued)
			require.EqualValues(t, 1, row.ProcessedEvents)
			require.EqualValues(t, 1, row.UnresolvedEvents)
			require.True(t, row.BalanceComplete)
			require.Len(t, row.Movements, 1)
		} else {
			require.Equal(t, second, row.OrderId)
			require.Equal(t, "second", row.Edition)
			require.Nil(t, row.VerifiedAt)
			require.Nil(t, row.CapturedMinor)
			require.Nil(t, row.RefundedMinor)
			require.False(t, row.BalanceComplete)
		}
	}
	body, err := StatementJSON(report)
	require.NoError(t, err)
	var compact bytes.Buffer
	require.NoError(t, json.Compact(&compact, body))
	raw := compact.Bytes()
	for _, hidden := range []string{other, outsider, corrupt, before, privateValue, "private@example.org", "cs_test_", "pi_paid", "ch_paid", account} {
		require.NotContains(t, string(raw), hidden)
	}
	require.Contains(t, string(raw), `"capturedMinor":"1200"`)
	require.Contains(t, string(raw), `"refundedMinor":"0"`)
	require.Contains(t, string(raw), `"movements":[]`)
	require.Equal(t, 1, bytes.Count(raw, []byte(`"capturedMinor"`)))
	empty := day.AddDate(0, 0, 1).Format(time.DateOnly)
	report, err = OperatorStatement(ctx, shop.db, client, offer.BusinessId, offer.ProductId, empty, empty)
	require.NoError(t, err)
	require.Empty(t, report.Orders)
	require.Equal(t, "empty", report.Coverage)
	report, err = OperatorStatement(ctx, shop.db, client, offer.BusinessId, "other-product-not-in-database", on, on)
	require.NoError(t, err)
	require.Empty(t, report.Orders)
	require.Equal(t, "partial", report.Coverage)
}

func TestStatementPagedRefundsAndDisputedBalance(t *testing.T) {
	created := time.Now().UTC().Add(-time.Hour)
	capture := int64(1200)
	charge, err := json.Marshal(balanceFixture("txn_charge", "ch_one", "charge", "aud", capture, 20, created))
	require.NoError(t, err)
	f := fact{state: disputed, captured: &capture, charge: "ch_one", payment: "pi_one", chargeBalance: charge, refunded: 400, dispute: "under_review"}
	client := statementStripe(t, func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()
		if r.URL.Path != "/v1/refunds" || query.Get("charge") != f.charge || query.Get("expand[0]") != "data.balance_transaction" {
			t.Errorf("unexpected refund request %s", r.URL)
			http.NotFound(w, r)
			return
		}
		var id string
		var more bool
		var when time.Time
		switch query.Get("starting_after") {
		case "":
			id, more, when = "re_later", true, created.Add(20*time.Second)
		case "re_later":
			id, when = "re_earlier", created.Add(10*time.Second)
		default:
			t.Error("repeated or invalid pagination cursor")
			http.NotFound(w, r)
			return
		}
		refund := obj{"object": "refund", "id": id, "charge": f.charge, "amount": 200, "status": "succeeded", "currency": "aud",
			"balance_transaction": balanceFixture("txn_"+id, id, "refund", "aud", -200, 0, when)}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(obj{"object": "list", "has_more": more, "data": []obj{refund}})
	})
	row := &v1.CommerceStatementOrder{Currency: "aud", Payment: disputed, CapturedMinor: wrapperspb.Int64(capture), RefundedMinor: wrapperspb.Int64(400)}
	client.statementBalance(t.Context(), row, f, created)
	require.False(t, row.BalanceComplete)
	require.Equal(t, disputed, row.Payment)
	require.EqualValues(t, 400, row.RefundedMinor.Value)
	require.Len(t, row.Movements, 3)
	require.Equal(t, []string{"txn_charge", "txn_re_earlier", "txn_re_later"}, []string{row.Movements[0].Id, row.Movements[1].Id, row.Movements[2].Id})
}

func TestStatementWindowAndLimits(t *testing.T) {
	now := time.Date(2024, 12, 31, 12, 0, 0, 0, time.UTC)
	first, end, err := statementWindow("2024-01-01", "2024-12-31", now)
	require.NoError(t, err)
	require.Equal(t, time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC), first)
	require.Equal(t, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), end)
	for _, span := range [][2]string{{"2024-02-30", "2024-12-31"}, {"2024-02-01", "2024-01-01"}, {"2023-12-31", "2024-12-31"}, {"2024-01-01", "2025-01-01"}, {"2024-1-1", "2024-01-01"}} {
		_, _, err := statementWindow(span[0], span[1], now)
		require.Error(t, err)
	}
	_, err = StatementJSON(&v1.CommerceStatement{BusinessId: strings.Repeat("a", maxStatementBytes)})
	require.ErrorContains(t, err, "shorter order period")
}

func TestStatementExcessCohortFailsBeforeAnyOrderIsReturned(t *testing.T) {
	shop, _, _ := testShop(t, "http://127.0.0.1")
	ctx := t.Context()
	day := time.Now().UTC().AddDate(0, 0, -1).Truncate(24 * time.Hour)
	_, err := shop.db.ExecContext(ctx, `INSERT INTO omega_digital_orders(connection_id,id,buyer_hash,offer_key,created_at)
		SELECT f.connection_id, gen_random_uuid(),'private'::bytea,f.offer_key,$2
		FROM omega_digital_offers f CROSS JOIN generate_series(1,$3::int) WHERE f.connection_id=$1`,
		shop.connection, day, maxStatementOrders+1)
	require.NoError(t, err)
	offer := testOffer([]byte("frozen first edition"))
	orders, _, err := shop.statementCohort(ctx, offer.BusinessId, offer.ProductId, day, day.AddDate(0, 0, 1))
	require.ErrorContains(t, err, "product window exceeds")
	require.Nil(t, orders)
}
