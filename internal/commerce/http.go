package commerce

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"html/template"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/google/uuid"
	"google.golang.org/protobuf/encoding/protojson"
)

type checkoutView struct {
	Title, Amount, Studio, Edition, OfferKey string
	ID, Status, Message                      string
	Receipt                                  *v1.DigitalOrderReceipt
	CanCancel, Awaiting                      bool
}

func statusText(p v1.DigitalPaymentState) (string, string) {
	switch p {
	case paid:
		return "Payment confirmed", "The provider confirmed the quoted amount."
	case expired:
		return "Checkout expired", "The test session ended before payment."
	case cancelled:
		return "Order cancelled", "The provider closed the test checkout."
	case failed:
		return "Payment failed", "The provider could not complete this payment."
	case refunded:
		return "Payment refunded", "The full test amount was returned. Future downloads are closed."
	case disputed:
		return "Payment disputed", "Downloads are on hold while the dispute is reviewed."
	default:
		return "Awaiting payment", "A confirmed provider payment will unlock the edition."
	}
}

func buyerID(r *http.Request) []byte {
	c, err := r.Cookie("omega_poster_test_buyer")
	if err != nil {
		return nil
	}
	b, err := base64.RawURLEncoding.DecodeString(c.Value)
	if err != nil || len(b) != 32 {
		return nil
	}
	sum := sha256.Sum256(b)
	return sum[:]
}

func writeFailure(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrMissing):
		http.Error(w, "Order unavailable.", http.StatusNotFound)
	case errors.Is(err, ErrBlocked):
		http.Error(w, "Download access is closed for this order. Return to the order to see its payment status.", http.StatusForbidden)
	case errors.Is(err, errOfferChanged):
		http.Error(w, "The test offer has changed. Reopen the test edition to review its price.", http.StatusConflict)
	case errors.Is(err, ErrConflict):
		http.Error(w, "The saved order needs reconciliation. Refresh the order.", http.StatusConflict)
	case errors.Is(err, ErrInvalidEvent):
		http.Error(w, "Unverified event.", http.StatusBadRequest)
	default:
		http.Error(w, "The order service could not verify this operation. It can be retried.", http.StatusServiceUnavailable)
	}
}

// Handler serves the loopback test checkout. All private order operations are
// buyer-bound. The provider ingress uses its own signature, independently of
// browser cookies and the success URL.
func (s *Shop) Handler(page *template.Template, title, studio string, preview []byte) http.Handler {
	mux := http.NewServeMux()
	render := func(w http.ResponseWriter, v checkoutView, offer *v1.DigitalOffer) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		v.Title = title
		v.Edition, v.OfferKey = offer.Edition, offerKey(offer)
		code := strings.ToUpper(offer.Currency)
		switch code {
		case "AUD", "CAD", "EUR", "GBP", "USD":
			v.Amount = fmt.Sprintf("%s %d.%02d", code, offer.AmountMinor/100, offer.AmountMinor%100)
		default:
			v.Amount = fmt.Sprintf("%s %d minor units", code, offer.AmountMinor)
		}
		v.Studio = studio
		_ = page.Execute(w, v)
	}
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		if buyerID(r) == nil {
			var token [32]byte
			if _, err := rand.Read(token[:]); err != nil {
				writeFailure(w, err)
				return
			}
			http.SetCookie(w, &http.Cookie{
				Name: "omega_poster_test_buyer", Value: base64.RawURLEncoding.EncodeToString(token[:]), Path: "/",
				HttpOnly: true, Secure: strings.HasPrefix(s.origin, "https://"), SameSite: http.SameSiteLaxMode, MaxAge: 48 * 60 * 60,
			})
		}
		render(w, checkoutView{ID: uuid.NewString()}, s.offer)
	})
	mux.HandleFunc("GET /artwork", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/png")
		_, _ = w.Write(preview)
	})
	mux.HandleFunc("POST /orders", func(w http.ResponseWriter, r *http.Request) {
		if buyerID(r) == nil {
			writeFailure(w, ErrMissing)
			return
		}
		if err := r.ParseForm(); err != nil {
			http.Error(w, "Invalid order form.", 400)
			return
		}
		quoted := r.PostForm.Get("offer")
		target, err := s.start(r.Context(), r.PostForm.Get("id"), buyerID(r), &quoted)
		if err != nil {
			writeFailure(w, err)
			return
		}
		http.Redirect(w, r, target, http.StatusSeeOther)
	})
	owned := func(w http.ResponseWriter, r *http.Request) (string, []byte, bool) {
		id := r.PathValue("id")
		buyer := buyerID(r)
		_, err := uuid.Parse(id)
		if err != nil || buyer == nil {
			writeFailure(w, ErrMissing)
			return "", nil, false
		}
		return id, buyer, true
	}
	mux.HandleFunc("GET /orders/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, b, ok := owned(w, r)
		if !ok {
			return
		}
		receipt, err := s.Receipt(r.Context(), id, b)
		if err != nil {
			writeFailure(w, err)
			return
		}
		status, message := statusText(receipt.Payment)
		if r.URL.Query().Get("returned") == "cancel" && receipt.Payment == pending {
			message = "You left the payment page. This order can still be cancelled or completed."
		}
		render(w, checkoutView{ID: id, Status: status, Message: message, Receipt: receipt, CanCancel: receipt.CheckoutOpen, Awaiting: receipt.Payment == pending}, receipt.Offer)
	})
	mux.HandleFunc("GET /orders/{id}/receipt", func(w http.ResponseWriter, r *http.Request) {
		id, b, ok := owned(w, r)
		if !ok {
			return
		}
		receipt, err := s.Receipt(r.Context(), id, b)
		if err != nil {
			writeFailure(w, err)
			return
		}
		raw, err := (protojson.MarshalOptions{Indent: "  ", EmitDefaultValues: true}).Marshal(receipt)
		if err != nil {
			writeFailure(w, err)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(raw)
	})
	for _, op := range []string{"refresh", "cancel", "replay", "download"} {
		mux.HandleFunc("POST /orders/{id}/"+op, func(w http.ResponseWriter, r *http.Request) {
			id, b, ok := owned(w, r)
			if !ok {
				return
			}
			var err error
			switch op {
			case "refresh":
				err = s.Refresh(r.Context(), id, b)
			case "cancel":
				err = s.Cancel(r.Context(), id, b)
			case "replay":
				if err = r.ParseForm(); err == nil {
					err = s.Replay(r.Context(), id, r.PostForm.Get("event"), b)
				}
			case "download":
				var offer *v1.DigitalOffer
				var data []byte
				offer, data, err = s.Download(r.Context(), id, b)
				if err == nil {
					w.Header().Set("Content-Type", "application/zip")
					w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": offer.ArchiveName}))
					_, _ = w.Write(data)
					return
				}
			}
			if err != nil {
				writeFailure(w, err)
				return
			}
			http.Redirect(w, r, "/orders/"+id, http.StatusSeeOther)
		})
	}
	mux.HandleFunc("POST /stripe/events", func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Invalid event body.", http.StatusRequestEntityTooLarge)
			return
		}
		if err = s.Record(r.Context(), body, r.Header.Get("Stripe-Signature")); err != nil {
			writeFailure(w, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})
	origin, _ := url.Parse(s.origin)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "same-origin")
		w.Header().Set("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self' https://checkout.stripe.com; frame-ancestors 'none'; base-uri 'none'")
		if r.Host != origin.Host {
			http.Error(w, "Unknown checkout origin.", http.StatusForbidden)
			return
		}
		if r.Method == http.MethodPost {
			if r.URL.Path != "/stripe/events" && r.Header.Get("Origin") != s.origin {
				http.Error(w, "This form belongs to another origin.", http.StatusForbidden)
				return
			}
			maxBytes := int64(8192)
			if r.URL.Path == "/stripe/events" {
				maxBytes = 1 << 20
			}
			r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
		}
		mux.ServeHTTP(w, r)
	})
}
