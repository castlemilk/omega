package commerce

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"mime"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// This gateway is used only for offline regression tests. The checkout URL
// and provider reads remain separate, so a buyer return cannot confirm a sale.
type fixtureGateway struct {
	mu           sync.Mutex
	states       map[string]fact
	creates      int
	loseResponse bool
}

const editorialPosterPacketSHA = "8e343a7789b0994d4093682e0849842929e47709dfe4121157670649ed19d33d"
const captionPosterPacketSHA = "2a68ff21008e8554f9d4278a9a758c84d85526e69a08c593fc8c829bf7ec55b6"

func (f *fixtureGateway) create(_ context.Context, id string, _ *v1.DigitalOffer, origin string) (session, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.states[id]; !ok {
		f.creates++
		f.states[id] = fact{state: pending, open: true}
	}
	if f.loseResponse {
		f.loseResponse = false
		return session{}, errors.New("provider connection lost")
	}
	return session{"cs_test_" + id, origin + "/orders/" + id}, nil
}

func (f *fixtureGateway) check(_ context.Context, order, sessionID string, _ *v1.DigitalOffer) (fact, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	state, ok := f.states[order]
	if !ok || sessionID != "cs_test_"+order {
		return fact{}, errors.New("unknown provider order")
	}
	return state, nil
}

func (f *fixtureGateway) set(id string, state v1.DigitalPaymentState, amount int64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	next := fact{state: state, payment: "pi_" + id, refunded: amount}
	next.open = state == pending || state == failed
	if !next.open {
		next.charge = "ch_" + id
	}
	f.states[id] = next
}

func (f *fixtureGateway) expire(_ context.Context, sessionID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	for id, state := range f.states {
		if "cs_test_"+id == sessionID && state.open {
			f.states[id] = fact{state: expired}
			return nil
		}
	}
	return errors.New("not an open session")
}

func testOrderDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("OMEGA_DIGITAL_ORDER_TEST_DSN")
	if dsn == "" {
		t.Skip("run make test-digital-orders for the isolated PostgreSQL suite")
	}
	db, err := sql.Open("pgx", dsn)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func testShop(t *testing.T, origin string) (*Shop, *fixtureGateway, []byte) {
	t.Helper()
	db := testOrderDB(t)
	g := &fixtureGateway{states: make(map[string]fact)}
	archive := []byte("frozen first edition")
	s, err := Open(t.Context(), db, "acct_fixture_"+uuid.NewString(), origin, testSecret, g, testOffer(archive), archive)
	require.NoError(t, err)
	buyer := bytes.Repeat([]byte{1}, 32)
	return s, g, buyer
}

func TestOrdersKeepReviewedPosterEditions(t *testing.T) {
	dir := os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if dir == "" {
		t.Skip("set OMEGA_POSTER_TEST_COLLECTION to test both Studio editions with their actual files")
	}
	var collection fs.FS = os.DirFS(dir)
	db := testOrderDB(t)
	ctx := t.Context()
	account := "acct_fixture_" + uuid.NewString()
	gateway := &fixtureGateway{states: make(map[string]fact)}
	const origin = "http://127.0.0.1"
	var checkout *Shop
	var handler http.Handler
	var buyer *http.Cookie
	request := func(method, route string, form url.Values) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, origin+route, strings.NewReader(form.Encode()))
		if buyer != nil {
			req.AddCookie(buyer)
		}
		if method == http.MethodPost {
			req.Header.Set("Origin", origin)
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		}
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		return response
	}
	type purchase struct {
		id, label string
		want      *v1.DigitalOffer
	}
	type selection struct{ edition, packetSHA, pack, preview, lead, label string }
	cases := []selection{
		{posters.OriginalEdition, "18d06477efdfa9c34ebc6dfa08986457618faaf7afb32c0d2c8c38191c584afa", "signal-studies-print-candidate.zip", "print-1.png", "Harmonic sum", "Download the six PDFs"},
		{posters.EditorialEdition, editorialPosterPacketSHA, "reader-proof-01/signal-studies.zip", "print-2.png", "Phase portrait", "Download the print ZIP"},
	}
	if downloads := os.Getenv("OMEGA_POSTER_CAPTION_FILES"); downloads != "" {
		collection = posters.WithCaptionFiles(collection, os.DirFS(downloads))
		cases = append(cases, selection{posters.CaptionEdition, captionPosterPacketSHA, "caption-01/signal-studies.zip", "print-2.png", "Phase portrait", "Download the print ZIP"})
	}
	orders := make([]purchase, 0, len(cases))
	for _, tc := range cases {
		packet, err := os.ReadFile("../../projects/posters/testdata/" + tc.edition + ".json")
		require.NoError(t, err)
		offer, pack, preview, err := posters.TestOffer(collection, packet, tc.packetSHA)
		require.NoError(t, err)
		wantPack, err := fs.ReadFile(collection, tc.pack)
		require.NoError(t, err)
		wantPreview, err := fs.ReadFile(collection, tc.preview)
		require.NoError(t, err)
		require.Equal(t, wantPack, pack)
		require.Equal(t, wantPreview, preview)
		require.Equal(t, filepath.Base(tc.pack), offer.ArchiveName)
		require.Equal(t, tc.packetSHA, offer.PacketSha256)
		require.Equal(t, tc.edition, offer.Edition)
		require.Equal(t, int64(1200), offer.AmountMinor)
		require.Equal(t, "aud", offer.Currency)
		require.Equal(t, "private-test-download-v1", offer.Licence)
		checkout, err = Open(ctx, db, account, origin, testSecret, gateway, offer, pack)
		require.NoError(t, err)
		handler = checkout.Handler(posters.CheckoutPage, "Signal Studies", "https://studio.example.org", preview)
		home := request(http.MethodGet, "/", nil)
		require.Equal(t, http.StatusOK, home.Code)
		require.Contains(t, home.Body.String(), `alt="`+tc.lead+", the A4 print")
		require.Equal(t, wantPreview, request(http.MethodGet, "/artwork", nil).Body.Bytes())
		if buyer == nil {
			cookies := home.Result().Cookies()
			require.Len(t, cookies, 1)
			buyer = cookies[0]
		}
		id := uuid.NewString()
		require.Equal(t, http.StatusSeeOther, request(http.MethodPost, "/orders", url.Values{"id": {id}}).Code)
		gateway.set(id, paid, 0)
		require.Equal(t, http.StatusSeeOther, request(http.MethodPost, "/orders/"+id+"/refresh", nil).Code)
		orders = append(orders, purchase{id, tc.label, offer})
	}
	// Reopen every order through the checkout that now serves the latest ZIP.
	distinct := make(map[string]bool)
	for _, order := range orders {
		require.False(t, distinct[offerKey(order.want)])
		distinct[offerKey(order.want)] = true
		page := request(http.MethodGet, "/orders/"+order.id, nil)
		require.Equal(t, http.StatusOK, page.Code)
		require.Contains(t, page.Body.String(), "<button>"+order.label+"</button>")
		response := request(http.MethodPost, "/orders/"+order.id+"/download", nil)
		require.Equal(t, http.StatusOK, response.Code)
		_, params, err := mime.ParseMediaType(response.Header().Get("Content-Disposition"))
		require.NoError(t, err)
		require.Equal(t, order.want.ArchiveName, params["filename"])
		require.Equal(t, order.want.ArchiveSha256, fingerprint(response.Body.Bytes()))
		receipt, err := checkout.currentReceipt(ctx, posters.StudioProductID, order.id)
		require.NoError(t, err)
		require.True(t, proto.Equal(order.want, receipt.Offer))
		require.EqualValues(t, 1, receipt.DownloadsIssued)
	}
}

func TestOrderOwnershipRetriesAndFrozenEdition(t *testing.T) {
	ctx := t.Context()
	s, g, buyer := testShop(t, "http://127.0.0.1")
	id := uuid.NewString()
	g.loseResponse = true
	_, err := s.Start(ctx, id, buyer)
	require.Error(t, err)
	r, err := s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, pending, r.Payment)
	require.Empty(t, r.ProviderSessionId)
	var wg sync.WaitGroup
	starts := make(chan error, 4)
	for range 4 {
		wg.Add(1)
		go func() { defer wg.Done(); _, err := s.Start(ctx, id, buyer); starts <- err }()
	}
	wg.Wait()
	close(starts)
	for err := range starts {
		require.NoError(t, err)
	}
	require.Equal(t, 1, g.creates)
	for _, stranger := range [][]byte{nil, bytes.Repeat([]byte{2}, 32)} {
		_, err = s.Receipt(ctx, id, stranger)
		require.ErrorIs(t, err, ErrMissing)
		require.ErrorIs(t, s.Refresh(ctx, id, stranger), ErrMissing)
		require.ErrorIs(t, s.Cancel(ctx, id, stranger), ErrMissing)
		require.ErrorIs(t, s.Replay(ctx, id, "evt_one", stranger), ErrMissing)
		_, _, err = s.Download(ctx, id, stranger)
		require.ErrorIs(t, err, ErrMissing)
		_, err = s.Start(ctx, id, stranger)
		require.ErrorIs(t, err, ErrMissing)
	}
	_, _, err = s.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
	// A signed "completed" event alone cannot change the provider's pending order.
	wire := sessionEvent("evt_one", "cs_test_"+id, "checkout.session.completed", time.Now().Unix())
	require.ErrorIs(t, s.Record(ctx, wire, "bad"), ErrInvalidEvent)
	require.NoError(t, s.Record(ctx, wire, signAt(wire, time.Now())))
	require.NoError(t, s.Record(ctx, wire, signAt(wire, time.Now())))
	require.NoError(t, s.Drain(ctx))
	r, err = s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.False(t, r.DownloadAvailable)
	require.Len(t, r.Events, 1)
	conflict := sessionEvent("evt_one", "cs_test_other", "checkout.session.completed", time.Now().Unix())
	require.ErrorIs(t, s.Record(ctx, conflict, signAt(conflict, time.Now())), ErrConflict)
	// A fresh deployment adopts a new offer. Existing orders retain the old file.
	next := []byte("new bytes")
	offer := testOffer(next)
	offer.Edition = "second"
	account := s.connection[:len(s.connection)-len("/"+offer.BusinessId)]
	restarted, err := Open(ctx, s.db, account, s.origin, testSecret, g, offer, next)
	require.NoError(t, err)
	g.set(id, paid, 0)
	actual, data, err := restarted.Download(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, "first", actual.Edition)
	require.Equal(t, []byte("frozen first edition"), data)
	r, err = restarted.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, "entitlement-"+id, r.EntitlementId)
	require.EqualValues(t, 1, r.DownloadsIssued)
	g.set(id, paid, 300)
	require.NoError(t, restarted.Refresh(ctx, id, buyer))
	r, err = restarted.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.EqualValues(t, 300, r.RefundedMinor)
	require.True(t, r.DownloadAvailable)
	g.set(id, refunded, 1200)
	_, _, err = restarted.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
	// A later delivery of an older payment notification reads the current refund.
	older := sessionEvent("evt_late", "cs_test_"+id, "checkout.session.completed", time.Now().Add(-time.Hour).Unix())
	require.NoError(t, s.Record(ctx, older, signAt(older, time.Now())))
	require.NoError(t, s.Drain(ctx))
	r, err = s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, refunded, r.Payment)
	require.False(t, r.DownloadAvailable)
	require.EqualValues(t, 1, r.DownloadsIssued)
	require.Len(t, r.Events, 2)
	operator, err := restarted.currentReceipt(ctx, offer.ProductId, id)
	require.NoError(t, err)
	require.Equal(t, r.EntitlementId, operator.EntitlementId)
	require.Equal(t, refunded, operator.Payment)
	_, err = restarted.currentReceipt(ctx, "another-product", id)
	require.ErrorIs(t, err, ErrMissing)
	g.set(id, paid, 0)
	require.ErrorIs(t, s.Refresh(ctx, id, buyer), ErrConflict)
}

func TestOrderCancellationExpiryAndEventRecovery(t *testing.T) {
	ctx := t.Context()
	s, g, buyer := testShop(t, "http://127.0.0.1")
	id := uuid.NewString()
	_, err := s.Start(ctx, id, buyer)
	require.NoError(t, err)
	require.NoError(t, s.Cancel(ctx, id, buyer))
	require.NoError(t, s.Cancel(ctx, id, buyer))
	_, _, err = s.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
	r, err := s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, cancelled, r.Payment)
	id = uuid.NewString()
	_, err = s.Start(ctx, id, buyer)
	require.NoError(t, err)
	g.set(id, failed, 0)
	_, _, err = s.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
	g.set(id, paid, 0)
	require.NoError(t, s.Refresh(ctx, id, buyer))
	_, err = s.db.ExecContext(ctx, `UPDATE omega_digital_orders SET entitled_at=now()-interval '25 hours' WHERE connection_id=$1 AND id=$2`, s.connection, id)
	require.NoError(t, err)
	_, _, err = s.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
	rec, err := s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.False(t, rec.DownloadAvailable)
	require.NotEmpty(t, rec.DownloadExpiresAt)
	raw := sessionEvent("evt_review", "cs_test_"+id, "checkout.session.completed", time.Now().Unix())
	require.NoError(t, s.Record(ctx, raw, signAt(raw, time.Now())))
	g.set(id, pending, 0)
	_, err = s.db.ExecContext(ctx, `UPDATE omega_digital_inbox SET attempts=7 WHERE connection_id=$1 AND id='evt_review'`, s.connection)
	require.NoError(t, err)
	require.NoError(t, s.Drain(ctx))
	r, err = s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, "needs_review", r.Events[0].ProcessingStatus)
	require.ErrorIs(t, s.Replay(ctx, id, "evt_wrong", buyer), ErrConflict)
	require.NoError(t, s.Replay(ctx, id, "evt_review", buyer))
	g.set(id, paid, 0)
	require.NoError(t, s.Drain(ctx))
	r, err = s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, "processed", r.Events[0].ProcessingStatus)
}

func TestFirstDeclineCanResumeAndCancelOriginalCheckout(t *testing.T) {
	ctx := t.Context()
	s, g, buyer := testShop(t, "http://127.0.0.1")
	id := uuid.NewString()
	location, err := s.Start(ctx, id, buyer)
	require.NoError(t, err)
	g.set(id, failed, 0)
	body := []byte(fmt.Sprintf(`{"id":"evt_decline","object":"event","livemode":false,"type":"payment_intent.payment_failed","created":%d,"data":{"object":{"id":"pi_%s","object":"payment_intent","metadata":{"omega_order":"%s","omega_offer":"%s"}}}}`, time.Now().Unix(), id, id, s.offerID))
	require.NoError(t, s.Record(ctx, body, signAt(body, time.Now())))
	require.NoError(t, s.Drain(ctx))
	r, err := s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, failed, r.Payment)
	require.True(t, r.CheckoutOpen)
	require.Empty(t, r.EntitlementId)
	require.Len(t, r.Events, 1)
	require.Equal(t, "processed", r.Events[0].ProcessingStatus)
	again, err := s.Start(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, location, again)
	require.Equal(t, 1, g.creates)
	require.NoError(t, s.Cancel(ctx, id, buyer))
	r, err = s.Receipt(ctx, id, buyer)
	require.NoError(t, err)
	require.Equal(t, cancelled, r.Payment)
	require.False(t, r.CheckoutOpen)
	require.Empty(t, r.EntitlementId)
	_, _, err = s.Download(ctx, id, buyer)
	require.ErrorIs(t, err, ErrBlocked)
}

func TestDigitalOrderBrowser(t *testing.T) {
	if os.Getenv("OMEGA_DIGITAL_ORDER_BROWSER") != "1" {
		t.Skip("run make test-digital-orders for the browser journey")
	}
	server := httptest.NewUnstartedServer(nil)
	defer server.Close()
	origin := "http://" + server.Listener.Addr().String()
	archive := []byte("frozen first edition")
	offer := testOffer(archive)
	var preview []byte
	if dir := os.Getenv("OMEGA_POSTER_TEST_COLLECTION"); dir != "" {
		var collection fs.FS = os.DirFS(dir)
		edition, packetSHA := posters.EditorialEdition, editorialPosterPacketSHA
		if downloads := os.Getenv("OMEGA_POSTER_CAPTION_FILES"); downloads != "" {
			collection = posters.WithCaptionFiles(collection, os.DirFS(downloads))
			edition, packetSHA = posters.CaptionEdition, captionPosterPacketSHA
		}
		raw, err := os.ReadFile("../../projects/posters/testdata/" + edition + ".json")
		require.NoError(t, err)
		offer, archive, preview, err = posters.TestOffer(collection, raw, packetSHA)
		require.NoError(t, err)
	}
	// Exercise a non-default price on each buyer screen through to the receipt.
	offer.AmountMinor, offer.Currency = 1955, "cad"
	g := &fixtureGateway{states: make(map[string]fact)}
	s, err := Open(t.Context(), testOrderDB(t), "acct_fixture_"+uuid.NewString(), origin, testSecret, g, offer, archive)
	require.NoError(t, err)
	mux := http.NewServeMux()
	mux.Handle("/", s.Handler(posters.CheckoutPage, "Signal Studies", "https://studio.example.org", preview))
	// Local fixtures control authenticated provider reads independently of the buyer browser.
	mux.HandleFunc("POST /fixture/{id}/{result}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if _, err := uuid.Parse(id); err != nil {
			http.Error(w, "invalid order", 400)
			return
		}
		switch r.PathValue("result") {
		case "decline":
			g.set(id, failed, 0)
		case "paid":
			g.set(id, paid, 0)
		case "refund":
			g.set(id, refunded, offer.AmountMinor)
		default:
			http.NotFound(w, r)
			return
		}
		w.WriteHeader(204)
	})
	server.Config.Handler = mux
	server.Start()
	ctx, cancel := context.WithTimeout(t.Context(), 45*time.Second)
	defer cancel()
	expected, err := protojson.Marshal(offer)
	require.NoError(t, err)
	input, err := json.Marshal(map[string]any{"origin": origin, "offer": json.RawMessage(expected)})
	require.NoError(t, err)
	cmd := exec.CommandContext(ctx, "node", "../../scripts/test-digital-order-browser.cjs")
	cmd.Stdin = bytes.NewReader(input)
	data, err := cmd.CombinedOutput()
	require.NoError(t, err, fmt.Sprintf("browser: %s", data))
}
