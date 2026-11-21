// Package commerce implements verified digital fulfilment. A connection's
// merchant identity is assigned by deployment, never supplied by a buyer.
package commerce

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stripe/stripe-go/v87"
	"github.com/stripe/stripe-go/v87/webhook"
	"google.golang.org/protobuf/proto"
)

const (
	pending   = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_PENDING
	paid      = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_PAID
	failed    = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_FAILED
	expired   = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_EXPIRED
	refunded  = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_REFUNDED
	disputed  = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_DISPUTED
	cancelled = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_CANCELLED
)

type (
	session struct{ id, url string }
	fact    struct {
		state                    v1.DigitalPaymentState
		payment, charge, dispute string
		refunded                 int64
	}
)

type event struct {
	id, kind, subject, ref string
	created                int64
}

type Provider interface {
	create(context.Context, string, *v1.DigitalOffer, string) (session, error)
	check(context.Context, string, string, *v1.DigitalOffer) (fact, error)
	expire(context.Context, string) error
}

type StripeTest struct {
	client      *stripe.Client
	integration string
}

func NewStripeTest(key string) (*StripeTest, error) {
	if !strings.HasPrefix(key, "sk_test_") && !strings.HasPrefix(key, "rk_test_") && !strings.HasPrefix(key, "rkcs_test_") {
		return nil, errors.New("a Stripe test credential is required")
	}
	return &StripeTest{client: stripe.NewClient(key), integration: "omega_posters_qknjbsva"}, nil
}

func (p *StripeTest) Account(ctx context.Context) (string, error) {
	a, err := p.client.V1Accounts.Retrieve(ctx, &stripe.AccountRetrieveParams{})
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(a.ID, "acct_") {
		return "", errors.New("unrecognised test merchant account")
	}
	return a.ID, nil
}

func fingerprint(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func offerKey(offer *v1.DigitalOffer) string {
	// DigitalOffer has no maps or unordered repeated fields.
	data, _ := proto.MarshalOptions{Deterministic: true}.Marshal(offer)
	return fingerprint(data)
}

func (p *StripeTest) create(ctx context.Context, id string, offer *v1.DigitalOffer, origin string) (session, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	meta := map[string]string{"omega_order": id, "omega_offer": offerKey(offer)}
	params := &stripe.CheckoutSessionCreateParams{
		Mode: stripe.String("payment"), ClientReferenceID: stripe.String(id), Metadata: meta,
		SuccessURL: stripe.String(origin + "/orders/" + id), CancelURL: stripe.String(origin + "/orders/" + id + "?returned=cancel"),
		IntegrationIdentifier: stripe.String(p.integration),
		PaymentIntentData:     &stripe.CheckoutSessionCreatePaymentIntentDataParams{Metadata: meta},
		LineItems: []*stripe.CheckoutSessionCreateLineItemParams{{
			Quantity: stripe.Int64(1),
			PriceData: &stripe.CheckoutSessionCreateLineItemPriceDataParams{
				Currency:   stripe.String(offer.Currency),
				UnitAmount: stripe.Int64(offer.AmountMinor), ProductData: &stripe.CheckoutSessionCreateLineItemPriceDataProductDataParams{Name: stripe.String("Digital print bundle · sandbox")},
			},
		}},
	}
	params.SetIdempotencyKey("omega-order-" + id)
	s, err := p.client.V1CheckoutSessions.Create(ctx, params)
	if err != nil {
		return session{}, err
	}
	link, err := url.Parse(s.URL)
	if s.Livemode || s.Mode != "payment" || !strings.HasPrefix(s.ID, "cs_test_") || s.ClientReferenceID != id || s.Metadata["omega_order"] != id || s.Metadata["omega_offer"] != offerKey(offer) ||
		s.AmountTotal != offer.AmountMinor || string(s.Currency) != offer.Currency || err != nil || link.Scheme != "https" || link.Host != "checkout.stripe.com" || link.User != nil {
		return session{}, errors.New("unexpected provider session for this test order")
	}
	return session{s.ID, s.URL}, nil
}

func (p *StripeTest) expire(ctx context.Context, id string) error {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	_, err := p.client.V1CheckoutSessions.Expire(ctx, id, &stripe.CheckoutSessionExpireParams{})
	return err
}

func (p *StripeTest) check(ctx context.Context, order, id string, offer *v1.DigitalOffer) (fact, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	params := &stripe.CheckoutSessionRetrieveParams{}
	params.AddExpand("payment_intent.latest_charge")
	s, err := p.client.V1CheckoutSessions.Retrieve(ctx, id, params)
	if err != nil {
		return fact{}, err
	}
	if s.Livemode || s.ID != id || !strings.HasPrefix(s.ID, "cs_test_") || s.Mode != "payment" ||
		s.ClientReferenceID != order || s.Metadata["omega_order"] != order || s.Metadata["omega_offer"] != offerKey(offer) ||
		s.AmountTotal != offer.AmountMinor || string(s.Currency) != offer.Currency {
		return fact{}, errors.New("provider session differs from this order and offer")
	}
	f := fact{state: pending}
	if s.Status == "expired" {
		f.state = expired
	}
	pi := s.PaymentIntent
	if pi == nil {
		return f, nil
	}
	if pi.Livemode || pi.ID == "" || pi.Metadata["omega_order"] != order || pi.Metadata["omega_offer"] != offerKey(offer) ||
		pi.Amount != offer.AmountMinor || string(pi.Currency) != offer.Currency {
		return fact{}, errors.New("provider payment differs from the order")
	}
	f.payment = pi.ID
	if pi.LastPaymentError != nil || pi.Status == "canceled" {
		f.state = failed
	}
	c := pi.LatestCharge
	if s.Status != "complete" || s.PaymentStatus != "paid" || pi.Status != "succeeded" || pi.AmountReceived != offer.AmountMinor {
		return f, nil
	}
	if c == nil || c.Livemode || !c.Paid || !c.Captured || c.ID == "" || c.PaymentIntent == nil || c.PaymentIntent.ID != pi.ID ||
		c.AmountCaptured != offer.AmountMinor || string(c.Currency) != offer.Currency || c.AmountRefunded < 0 || c.AmountRefunded > c.AmountCaptured {
		return fact{}, errors.New("the captured charge does not match the quoted order")
	}
	f.charge = c.ID
	f.refunded = c.AmountRefunded
	f.state = paid
	if c.Disputed {
		var count int
		for dispute, err := range p.client.V1Disputes.List(ctx, &stripe.DisputeListParams{Charge: stripe.String(c.ID)}).All(ctx) {
			if err != nil {
				return fact{}, err
			}
			if dispute.Livemode || dispute.Charge == nil || dispute.Charge.ID != c.ID {
				return fact{}, errors.New("unexpected dispute scope")
			}
			count++
			// A confirmed loss or active dispute restricts further downloads.
			// A warning closed without a formal dispute has no remaining hold.
			if f.state != disputed {
				f.dispute = string(dispute.Status)
			}
			if dispute.Status != "won" && dispute.Status != "warning_closed" {
				f.dispute = string(dispute.Status)
				f.state = disputed
			}
		}
		if count == 0 {
			return fact{}, errors.New("dispute outcome is pending reconciliation")
		}
	}
	if f.refunded == offer.AmountMinor {
		f.state = refunded
	}
	return f, nil
}

func readEvent(raw []byte, signature, secret string, now time.Time) (event, error) {
	if err := webhook.ValidatePayloadWithTolerance(raw, signature, secret, 5*time.Minute); err != nil {
		return event{}, errors.New("invalid provider signature")
	}
	var timestamp int64
	for _, part := range strings.Split(signature, ",") {
		if strings.HasPrefix(part, "t=") {
			timestamp, _ = strconv.ParseInt(strings.TrimPrefix(part, "t="), 10, 64)
		}
	}
	if timestamp <= 0 || timestamp > now.Add(5*time.Minute).Unix() {
		return event{}, errors.New("invalid provider timestamp")
	}
	// We persist only the provider reference. Current financial state is read
	// independently with this connection's credential and exact order scope.
	var e struct {
		ID      string `json:"id"`
		Type    string `json:"type"`
		Object  string `json:"object"`
		Live    *bool  `json:"livemode"`
		Account string `json:"account"`
		Created int64  `json:"created"`
		Data    struct {
			Object struct {
				ID      string          `json:"id"`
				Type    string          `json:"object"`
				Payment json.RawMessage `json:"payment_intent"`
				Charge  json.RawMessage `json:"charge"`
			} `json:"object"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &e); err != nil || e.Object != "event" || !strings.HasPrefix(e.ID, "evt_") || len(e.ID) > 200 ||
		e.Live == nil || *e.Live || e.Account != "" || e.Created <= 0 {
		return event{}, errors.New("invalid direct sandbox event")
	}
	out := event{id: e.ID, kind: e.Type, created: e.Created}
	obj := e.Data.Object
	switch e.Type {
	case "checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed", "checkout.session.expired":
		if obj.Type == "checkout.session" {
			out.subject, out.ref = "session", obj.ID
		}
	case "charge.refunded", "charge.succeeded":
		if obj.Type == "charge" {
			out.subject, out.ref = "payment", stripeRef(obj.Payment)
		}
	case "charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed", "refund.created", "refund.updated", "refund.failed":
		if obj.Type == "dispute" || obj.Type == "refund" {
			out.subject, out.ref = "payment", stripeRef(obj.Payment)
			if out.ref == "" {
				out.subject, out.ref = "charge", stripeRef(obj.Charge)
			}
		}
	default:
		return event{}, nil
	}
	required := map[string]string{"session": "cs_test_", "payment": "pi_", "charge": "ch_"}[out.subject]
	if required == "" || len(out.ref) > 200 || !strings.HasPrefix(out.ref, required) {
		return event{}, fmt.Errorf("missing reference for %s", e.Type)
	}
	return out, nil
}

func stripeRef(raw json.RawMessage) string {
	var id string
	if json.Unmarshal(raw, &id) == nil {
		return id
	}
	var obj struct {
		ID string `json:"id"`
	}
	_ = json.Unmarshal(raw, &obj)
	return obj.ID
}
