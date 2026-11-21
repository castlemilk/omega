package commerce

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stripe/stripe-go/v87"
	"github.com/stripe/stripe-go/v87/webhook"
)

const testSecret = "whsec_local_commerce_test"

func testOffer(archive []byte) *v1.DigitalOffer {
	return &v1.DigitalOffer{
		BusinessId: "fixture-business", ProductId: "fixture-product", Edition: "first",
		PacketSha256: fingerprint([]byte("review")), ArchiveSha256: fingerprint(archive), ArchiveName: "edition.zip",
		AmountMinor: 1200, Currency: "aud", Licence: "test-download",
	}
}

// Stripe's signed endpoint sends a reference. Even a valid event cannot
// contribute an amount or become proof of payment on its own.
func sessionEvent(eventID, sessionID, kind string, created int64) []byte {
	b, _ := json.Marshal(map[string]any{
		"id": eventID, "type": kind, "object": "event", "livemode": false, "created": created,
		"data": map[string]any{"object": map[string]any{"id": sessionID, "object": "checkout.session"}},
	})
	return b
}

func signAt(payload []byte, when time.Time) string {
	return webhook.GenerateTestSignedPayload(&webhook.UnsignedPayload{Payload: payload, Secret: testSecret, Timestamp: when}).Header
}

func TestSignedEventScopeAndAge(t *testing.T) {
	now := time.Now()
	raw := sessionEvent("evt_one", "cs_test_one", "checkout.session.completed", now.Unix())
	h := signAt(raw, now)
	got, err := readEvent(raw, h, testSecret, now)
	if err != nil || got.ref != "cs_test_one" || got.kind != "checkout.session.completed" {
		t.Fatalf("read: %+v, %v", got, err)
	}
	for _, tc := range []struct{ name, replace, with string }{
		{"live", `"livemode":false`, `"livemode":true`},
		{"missing mode", `"livemode":false,`, ""},
		{"connect account", `"livemode":false`, `"account":"acct_another","livemode":false`},
		{"wrong subject", "cs_test_one", "cs_live_unknown"},
		{"wrong event type for object", "checkout.session.completed", "charge.refunded"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			b := []byte(strings.Replace(string(raw), tc.replace, tc.with, 1))
			if _, err := readEvent(b, signAt(b, now), testSecret, now); err == nil {
				t.Fatal("invalid event accepted")
			}
		})
	}
	for _, timestamp := range []time.Time{now.Add(-7 * time.Minute), now.Add(7 * time.Minute)} {
		if _, err := readEvent(raw, signAt(raw, timestamp), testSecret, now); err == nil {
			t.Fatal("event outside signature window accepted")
		}
	}
	if _, err := readEvent(append(raw, ' '), h, testSecret, now); err == nil {
		t.Fatal("altered payload accepted")
	}
	if _, err := readEvent(raw, h, "whsec_another", now); err == nil {
		t.Fatal("other connection accepted")
	}
	ignored := sessionEvent("evt_other", "cs_test_one", "unhandled.type", now.Unix())
	if e, err := readEvent(ignored, signAt(ignored, now), testSecret, now); err != nil || e.id != "" {
		t.Fatalf("unsubscribed event: %+v %v", e, err)
	}
}

func TestStripeRejectsLiveCredentials(t *testing.T) {
	for _, key := range []string{"", "sk_live_example", "rk_live_example", "pk_test_example"} {
		if _, err := NewStripeTest(key); err == nil {
			t.Fatal("non-test server credential accepted")
		}
	}
}

type obj = map[string]any

func TestStripeRetrievesAndChecksOriginalPayment(t *testing.T) {
	offer := testOffer([]byte("original archive"))
	metadata := obj{"omega_order": "order", "omega_offer": offerKey(offer)}
	type transaction struct {
		session, intent, charge obj
		dispute                 string
	}
	tests := []struct {
		name      string
		alter     func(*transaction)
		state     v1.DigitalPaymentState
		wantError bool
	}{
		{"captured", func(*transaction) {}, paid, false},
		{"open checkout", func(x *transaction) {
			x.session["payment_intent"] = nil
			x.session["status"] = "open"
			x.session["payment_status"] = "unpaid"
		}, pending, false},
		{"failed payment", func(x *transaction) {
			x.session["status"] = "open"
			x.intent["status"] = "requires_payment_method"
			x.intent["last_payment_error"] = obj{"code": "card_declined"}
		}, failed, false},
		{"expired", func(x *transaction) {
			x.session["payment_intent"] = nil
			x.session["status"] = "expired"
			x.session["payment_status"] = "unpaid"
		}, expired, false},
		{"expired after decline", func(x *transaction) {
			x.session["status"] = "expired"
			x.session["payment_status"] = "unpaid"
			x.intent["status"] = "canceled"
			x.intent["last_payment_error"] = obj{"code": "card_declined"}
		}, expired, false},
		{"partial refund", func(x *transaction) { x.charge["amount_refunded"] = 200 }, paid, false},
		{"full refund", func(x *transaction) { x.charge["amount_refunded"] = 1200 }, refunded, false},
		{"open dispute", func(x *transaction) { x.charge["disputed"] = true; x.dispute = "needs_response" }, disputed, false},
		{"won dispute", func(x *transaction) { x.charge["disputed"] = true; x.dispute = "won" }, paid, false},
		{"lost dispute", func(x *transaction) { x.charge["disputed"] = true; x.dispute = "lost" }, disputed, false},
		{"wrong session scope", func(x *transaction) { x.session["client_reference_id"] = "other" }, 0, true},
		{"wrong edition", func(x *transaction) { x.intent["metadata"] = obj{"omega_order": "order", "omega_offer": "other"} }, 0, true},
		{"wrong currency", func(x *transaction) { x.session["currency"] = "usd" }, 0, true},
		{"wrong total", func(x *transaction) { x.session["amount_total"] = 900 }, 0, true},
		{"other charge", func(x *transaction) { x.charge["payment_intent"] = "pi_other" }, 0, true},
		{"short capture", func(x *transaction) { x.charge["amount_captured"] = 900 }, 0, true},
		{"live charge", func(x *transaction) { x.charge["livemode"] = true }, 0, true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			charge := obj{"id": "ch_one", "paid": true, "captured": true, "amount_captured": 1200, "currency": "aud", "payment_intent": "pi_one"}
			intent := obj{"id": "pi_one", "status": "succeeded", "amount": 1200, "amount_received": 1200, "currency": "aud", "metadata": metadata, "latest_charge": charge}
			state := transaction{session: obj{"id": "cs_test_one", "mode": "payment", "status": "complete", "payment_status": "paid", "currency": "aud", "amount_total": 1200, "client_reference_id": "order", "metadata": metadata, "payment_intent": intent}, intent: intent, charge: charge}
			tc.alter(&state)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				switch r.URL.Path {
				case "/v1/checkout/sessions/cs_test_one":
					if r.URL.Query().Get("expand[0]") != "payment_intent.latest_charge" {
						t.Error("charge not expanded")
					}
					_ = json.NewEncoder(w).Encode(state.session)
				case "/v1/disputes":
					if r.URL.Query().Get("charge") != "ch_one" {
						t.Error("dispute scope")
					}
					_ = json.NewEncoder(w).Encode(obj{"object": "list", "data": []obj{{"id": "dp_one", "charge": "ch_one", "status": state.dispute}}})
				default:
					http.NotFound(w, r)
				}
			}))
			defer server.Close()
			backend := stripe.NewBackendsWithConfig(&stripe.BackendConfig{URL: stripe.String(server.URL), HTTPClient: server.Client()})
			p := &StripeTest{client: stripe.NewClient("sk_test_example", stripe.WithBackends(backend))}
			f, err := p.check(t.Context(), "order", "cs_test_one", offer)
			if (err != nil) != tc.wantError || (!tc.wantError && f.state != tc.state) {
				t.Fatalf("result %+v, %v", f, err)
			}
		})
	}
}
