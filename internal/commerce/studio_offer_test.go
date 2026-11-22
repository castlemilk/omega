package commerce

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

type studioPurchase struct {
	id, display   string
	offer         *v1.DigitalOffer
	pack, preview []byte
}

// Exercise the actual Stripe SDK requests, order database and buyer handlers.
// Both test prices describe exactly the same reviewed artwork.
func TestStudioPricesKeepProviderReceiptAndDownload(t *testing.T) {
	collection := os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if collection == "" {
		t.Skip("set OMEGA_POSTER_TEST_COLLECTION for the issued buyer archive")
	}
	const dir = "../../projects/posters/testdata/"
	review, err := os.ReadFile(dir + posters.EditorialEdition + ".json")
	require.NoError(t, err)
	base, pack, preview, err := posters.TestOffer(os.DirFS(collection), review, editorialPosterPacketSHA)
	require.NoError(t, err)
	require.Nil(t, base.StudioOfferSha256)
	// Pre-Studio offer keys are already embedded in Stripe session and intent metadata.
	legacyKey := offerKey(base)
	require.Equal(t, "0c1ab54e8e996fbb5e5b547ec9f8d6ca997935afd11e3fe514422653a8f7fae5", legacyKey)
	baseRaw, err := os.ReadFile(dir + "editorial-test-offer.json")
	require.NoError(t, err)
	defaultQuote := new(v1.PosterTestOffer)
	require.NoError(t, protojson.Unmarshal(baseRaw, defaultQuote))
	var orders []studioPurchase
	for i, price := range []struct {
		amount            int64
		currency, display string
	}{
		{1575, "AUD", "AUD 15.75"}, {2305, "GBP", "GBP 23.05"},
	} {
		q := proto.CloneOf(defaultQuote)
		q.AmountMinor, q.Currency, q.PriceSource = price.amount, price.currency, "seller-draft"
		q.PriceRevision, q.PriceRecordedAt = uint32(i+1), "2026-11-22T09:00:00Z"
		q.SellerDraftSha256 = fingerprint([]byte(price.display + " seller composition"))
		raw, err := protojson.Marshal(q)
		require.NoError(t, err)
		link := "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=test-offer-file&packet=" + editorialPosterPacketSHA + "&offer=" + fingerprint(raw)
		offer, err := posters.VerifyTestOffer(raw, review, link)
		require.NoError(t, err)
		require.NotEqual(t, legacyKey, offerKey(offer))
		orders = append(orders, studioPurchase{uuid.NewString(), price.display, offer, pack, preview})
	}
	checkStudioOrderHistory(t, orders)
}

func TestLaunchReviewKeepsEarlierOfferAndArchive(t *testing.T) {
	dir, collection := os.Getenv("OMEGA_POSTER_LAUNCH_REVIEWS"), os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if dir == "" || collection == "" {
		t.Skip("set the issued launch review pair and collection to replay the two buyer orders")
	}
	var files fs.FS = os.DirFS(collection)
	if caption := os.Getenv("OMEGA_POSTER_CAPTION_FILES"); caption != "" {
		files = posters.WithCaptionFiles(files, os.DirFS(caption))
	}
	var orders []studioPurchase
	for _, label := range []string{"current", "revised"} {
		link, err := os.ReadFile(filepath.Join(dir, label+"-from.txt"))
		require.NoError(t, err)
		checked, packet, err := posters.VerifyLaunchReview(os.DirFS(dir), label+".zip", strings.TrimSpace(string(link)))
		require.NoError(t, err)
		local, pack, preview, err := posters.TestOffer(files, packet, checked.PacketSha256)
		require.NoError(t, err)
		require.Equal(t, checked.Offer.ArchiveSha256, local.ArchiveSha256)
		o := checked.Offer
		display := fmt.Sprintf("%s %d.%02d", strings.ToUpper(o.Currency), o.AmountMinor/100, o.AmountMinor%100)
		orders = append(orders, studioPurchase{uuid.NewString(), display, o, pack, preview})
		t.Logf("%s review %s, packet %s, offer %s, buyer ZIP %s", label, checked.ReviewSha256, checked.PacketSha256, checked.OfferSha256, o.ArchiveSha256)
	}
	checkStudioOrderHistory(t, orders)
}

func checkStudioOrderHistory(t *testing.T, orders []studioPurchase) {
	t.Helper()
	db, ctx := testOrderDB(t), t.Context()
	quotes := map[string]*v1.DigitalOffer{}
	for _, o := range orders {
		quotes[o.id] = o.offer
	}
	base := orders[0].offer
	require.NotEqual(t, offerKey(orders[0].offer), offerKey(orders[1].offer))
	account := "acct_offerprice_" + uuid.NewString()
	var created atomic.Int32
	provider := statementStripe(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/v1/account":
			_ = json.NewEncoder(w).Encode(obj{"id": account})
			return
		case "/v1/refunds":
			_ = json.NewEncoder(w).Encode(obj{"object": "list", "data": []obj{}, "has_more": false})
			return
		}
		var id string
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/v1/checkout/sessions":
			id = r.FormValue("client_reference_id")
		case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/v1/checkout/sessions/cs_test_"):
			id = strings.TrimPrefix(r.URL.Path, "/v1/checkout/sessions/cs_test_")
		default:
			t.Errorf("unexpected provider request %s %s", r.Method, r.URL.Path)
			http.NotFound(w, r)
			return
		}
		offer := quotes[id]
		if offer == nil {
			t.Error("unknown order reached provider")
			http.NotFound(w, r)
			return
		}
		key := offerKey(offer)
		metadata := obj{"omega_order": id, "omega_offer": key}
		record := obj{"id": "cs_test_" + id, "url": "https://checkout.stripe.com/c/pay/" + id, "mode": "payment", "currency": offer.Currency,
			"client_reference_id": id, "amount_total": offer.AmountMinor, "metadata": metadata}
		if r.Method == http.MethodPost {
			if r.FormValue("line_items[0][price_data][currency]") != offer.Currency || r.FormValue("line_items[0][price_data][unit_amount]") != strconv.FormatInt(offer.AmountMinor, 10) ||
				r.FormValue("metadata[omega_offer]") != key || r.FormValue("payment_intent_data[metadata][omega_offer]") != key ||
				r.FormValue("line_items[0][quantity]") != "1" || r.Header.Get("Idempotency-Key") != "omega-order-"+id {
				t.Error("Stripe checkout differs from the posted offer")
			}
			created.Add(1)
		} else {
			record["status"], record["payment_status"] = "complete", "paid"
			charge := obj{"id": "ch_" + id, "payment_intent": "pi_" + id, "paid": true, "captured": true, "amount_captured": offer.AmountMinor, "currency": offer.Currency, "amount_refunded": 0,
				"balance_transaction": balanceFixture("txn_"+strings.ReplaceAll(id, "-", ""), "ch_"+id, "charge", offer.Currency, offer.AmountMinor, 30, time.Now())}
			record["payment_intent"] = obj{"id": "pi_" + id, "status": "succeeded", "amount": offer.AmountMinor, "amount_received": offer.AmountMinor, "currency": offer.Currency, "metadata": metadata, "latest_charge": charge}
		}
		_ = json.NewEncoder(w).Encode(record)
	})
	const origin = "http://127.0.0.1"
	var handler http.Handler
	var cookie *http.Cookie
	request := func(method, route string, form url.Values) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, origin+route, strings.NewReader(form.Encode()))
		if cookie != nil {
			req.AddCookie(cookie)
		}
		if method == http.MethodPost {
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
			req.Header.Set("Origin", origin)
		}
		res := httptest.NewRecorder()
		handler.ServeHTTP(res, req)
		return res
	}
	for i, o := range orders {
		shop, err := Open(ctx, db, account, origin, testSecret, provider, o.offer, o.pack)
		require.NoError(t, err)
		handler = shop.Handler(posters.CheckoutPage, "Signal Studies", "https://studio.example.org", o.preview)
		home := request("GET", "/", nil)
		require.Equal(t, 200, home.Code)
		require.Contains(t, home.Body.String(), o.display+" in test funds")
		require.Contains(t, home.Body.String(), `name="offer" value="`+offerKey(o.offer)+`"`)
		if cookie == nil {
			cookie = home.Result().Cookies()[0]
		}
		if i > 0 {
			oldQuote := offerKey(orders[0].offer)
			for _, form := range []url.Values{{"id": {uuid.NewString()}, "offer": {oldQuote}}, {"id": {uuid.NewString()}}} {
				require.Equal(t, 409, request("POST", "/orders", form).Code)
			}
			require.Equal(t, int32(1), created.Load())
			// Reusing an existing order ID also checks its frozen price, even
			// when the submitted form is the current one on another server.
			require.Equal(t, 409, request("POST", "/orders", url.Values{"id": {orders[0].id}, "offer": {offerKey(o.offer)}}).Code)
			require.Equal(t, 303, request("POST", "/orders", url.Values{"id": {orders[0].id}, "offer": {oldQuote}}).Code)
			require.Equal(t, int32(1), created.Load())
		}
		start := request("POST", "/orders", url.Values{"id": {o.id}, "offer": {offerKey(o.offer)}})
		require.Equal(t, 303, start.Code, start.Body.String())
		require.Equal(t, "https://checkout.stripe.com/c/pay/"+o.id, start.Header().Get("Location"))
		require.Equal(t, 303, request("POST", "/orders/"+o.id+"/refresh", nil).Code)
	}
	for _, o := range orders {
		page := request("GET", "/orders/"+o.id, nil)
		require.Equal(t, 200, page.Code)
		require.Contains(t, page.Body.String(), "<dd>"+o.display+"</dd>")
		download := request("POST", "/orders/"+o.id+"/download", nil)
		require.Equal(t, 200, download.Code)
		require.Equal(t, o.pack, download.Body.Bytes())
		receipt := new(v1.DigitalOrderReceipt)
		require.NoError(t, protojson.Unmarshal(request("GET", "/orders/"+o.id+"/receipt", nil).Body.Bytes(), receipt))
		require.True(t, proto.Equal(o.offer, receipt.Offer))
		require.Equal(t, paid, receipt.Payment)
		require.EqualValues(t, 1, receipt.DownloadsIssued)
	}
	require.Equal(t, int32(2), created.Load())
	day := time.Now().UTC().Format(time.DateOnly)
	statement, err := OperatorStatement(ctx, db, provider, base.BusinessId, base.ProductId, day, day)
	require.NoError(t, err)
	require.Equal(t, "complete", statement.Coverage)
	require.Len(t, statement.Orders, 2)
	for _, row := range statement.Orders {
		offer := quotes[row.OrderId]
		require.NotNil(t, offer)
		require.Equal(t, offer.Currency, row.Currency)
		require.Equal(t, offer.AmountMinor, row.QuotedMinor)
		require.Equal(t, offer.AmountMinor, row.CapturedMinor.Value)
		require.Len(t, row.Movements, 1)
		require.Equal(t, offer.AmountMinor, row.Movements[0].AmountMinor)
	}
	raw, err := StatementJSON(statement)
	require.NoError(t, err)
	var compact bytes.Buffer
	require.NoError(t, json.Compact(&compact, raw))
	t.Logf("Isolated provider statement %s", compact.String())
	t.Logf("Verified %s and %s against Stripe session, payment and settlement. Buyer ZIP %s (%d bytes).", orders[0].display, orders[1].display, base.ArchiveSha256, len(orders[0].pack))
}
