package commerce

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/stretchr/testify/require"
)

// This gateway is used only for offline regression tests. The checkout URL
// and provider reads remain separate, so a buyer return cannot confirm a sale.
type fixtureGateway struct {
	mu           sync.Mutex
	states       map[string]fact
	creates      int
	loseResponse bool
}

func (f *fixtureGateway) create(_ context.Context, id string, _ *v1.DigitalOffer, origin string) (session, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.states[id]; !ok {
		f.creates++
		f.states[id] = fact{state: pending}
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
	f.states[id] = fact{state: state, payment: "pi_" + id, charge: "ch_" + id, refunded: amount}
}

func (f *fixtureGateway) expire(_ context.Context, sessionID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	for id, state := range f.states {
		if "cs_test_"+id == sessionID && state.state == pending {
			f.states[id] = fact{state: expired}
			return nil
		}
	}
	return errors.New("not an open session")
}

func testShop(t *testing.T, origin string) (*Shop, *fixtureGateway, []byte) {
	t.Helper()
	dsn := os.Getenv("OMEGA_DIGITAL_ORDER_TEST_DSN")
	if dsn == "" {
		t.Skip("run make test-digital-orders for the isolated PostgreSQL suite")
	}
	db, err := sql.Open("pgx", dsn)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })
	g := &fixtureGateway{states: make(map[string]fact)}
	archive := []byte("frozen first edition")
	s, err := Open(t.Context(), db, "acct_fixture_"+uuid.NewString(), origin, testSecret, g, testOffer(archive), archive)
	require.NoError(t, err)
	buyer := bytes.Repeat([]byte{1}, 32)
	return s, g, buyer
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

func TestDigitalOrderBrowser(t *testing.T) {
	if os.Getenv("OMEGA_DIGITAL_ORDER_BROWSER") != "1" {
		t.Skip("run make test-digital-orders for the browser journey")
	}
	server := httptest.NewUnstartedServer(nil)
	defer server.Close()
	origin := "http://" + server.Listener.Addr().String()
	s, g, _ := testShop(t, origin)
	mux := http.NewServeMux()
	mux.Handle("/", s.Handler(posters.CheckoutPage, "Signal Studies", "AUD 12.00", "https://studio.example.org", nil))
	// Local fixtures control authenticated provider reads independently of the buyer browser.
	mux.HandleFunc("POST /fixture/{id}/{result}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if _, err := uuid.Parse(id); err != nil {
			http.Error(w, "invalid order", 400)
			return
		}
		switch r.PathValue("result") {
		case "paid":
			g.set(id, paid, 0)
		case "refund":
			g.set(id, refunded, 1200)
		default:
			http.NotFound(w, r)
			return
		}
		w.WriteHeader(204)
	})
	server.Config.Handler = mux
	server.Start()
	script, err := filepath.Abs("../../scripts/test-digital-order-browser.cjs")
	require.NoError(t, err)
	ctx, cancel := context.WithTimeout(t.Context(), 45*time.Second)
	defer cancel()
	data, err := exec.CommandContext(ctx, "node", script, origin).CombinedOutput()
	require.NoError(t, err, fmt.Sprintf("browser: %s", data))
}
