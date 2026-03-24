package polymarket

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

// testServer creates a test HTTP server with a fixed handler and returns a
// Client pointing at it, plus a teardown func.
func testServer(t *testing.T, handler http.Handler) (*Client, func()) {
	t.Helper()
	srv := httptest.NewServer(handler)
	client := NewClient(
		WithGammaURL(srv.URL),
		WithCLOBURL(srv.URL),
		WithDataURL(srv.URL),
	)
	return client, srv.Close
}

// -------------------------------------------------------------------------
// JSON unmarshal tests
// -------------------------------------------------------------------------

func TestMarketUnmarshal(t *testing.T) {
	raw := `{
		"id": "12",
		"conditionId": "0xabc",
		"question": "Will X happen?",
		"slug": "will-x-happen",
		"category": "politics",
		"outcomes": ["Yes","No"],
		"outcomePrices": ["0.72","0.28"],
		"clobTokenIds": ["111","222"],
		"active": true,
		"closed": false,
		"volumeNum": 12345.67,
		"bestBid": 0.71,
		"bestAsk": 0.73,
		"endDate": "2025-01-01T00:00:00Z",
		"createdAt": "2024-01-01T00:00:00Z",
		"updatedAt": "2024-06-01T00:00:00Z"
	}`

	var m Market
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		t.Fatalf("unmarshal Market: %v", err)
	}
	if m.ConditionID != "0xabc" {
		t.Errorf("ConditionID: got %q, want %q", m.ConditionID, "0xabc")
	}
	if m.Question != "Will X happen?" {
		t.Errorf("Question: got %q", m.Question)
	}
	if len(m.Outcomes) != 2 || m.Outcomes[0] != "Yes" {
		t.Errorf("Outcomes: got %v", m.Outcomes)
	}
	if m.BestBid != 0.71 {
		t.Errorf("BestBid: got %v", m.BestBid)
	}
	if m.BestAsk != 0.73 {
		t.Errorf("BestAsk: got %v", m.BestAsk)
	}
}

func TestEventUnmarshal(t *testing.T) {
	raw := `{
		"id": "42",
		"title": "US Elections 2024",
		"slug": "us-elections-2024",
		"active": true,
		"volume": 999999.9,
		"markets": [
			{"id": "1", "question": "Will A win?", "active": true}
		],
		"tags": [{"id": "t1", "label": "Politics", "slug": "politics"}]
	}`

	var e Event
	if err := json.Unmarshal([]byte(raw), &e); err != nil {
		t.Fatalf("unmarshal Event: %v", err)
	}
	if e.ID != "42" {
		t.Errorf("ID: got %q", e.ID)
	}
	if len(e.Markets) != 1 {
		t.Errorf("Markets len: got %d", len(e.Markets))
	}
	if len(e.Tags) != 1 || e.Tags[0].Label != "Politics" {
		t.Errorf("Tags: got %v", e.Tags)
	}
}

func TestOrderBookUnmarshal(t *testing.T) {
	raw := `{
		"market": "0xabc",
		"asset_id": "111",
		"bids": [{"price":"0.70","size":"100"},{"price":"0.69","size":"200"}],
		"asks": [{"price":"0.73","size":"50"}],
		"hash": "h1",
		"timestamp": "1234567890"
	}`

	var ob OrderBook
	if err := json.Unmarshal([]byte(raw), &ob); err != nil {
		t.Fatalf("unmarshal OrderBook: %v", err)
	}
	if len(ob.Bids) != 2 {
		t.Errorf("Bids len: got %d", len(ob.Bids))
	}
	if ob.Bids[0].Price != "0.70" {
		t.Errorf("Bids[0].Price: got %q", ob.Bids[0].Price)
	}
	if len(ob.Asks) != 1 || ob.Asks[0].Size != "50" {
		t.Errorf("Asks: got %v", ob.Asks)
	}
}

func TestTradeUnmarshal(t *testing.T) {
	raw := `{
		"proxyWallet": "0xwallet",
		"side": "BUY",
		"asset": "111",
		"conditionId": "0xabc",
		"size": "10",
		"price": "0.72",
		"timestamp": 1711234567,
		"title": "Will X happen?",
		"outcome": "Yes",
		"outcomeIndex": 0,
		"transactionHash": "0xtxhash"
	}`

	var tr Trade
	if err := json.Unmarshal([]byte(raw), &tr); err != nil {
		t.Fatalf("unmarshal Trade: %v", err)
	}
	if tr.Side != "BUY" {
		t.Errorf("Side: got %q", tr.Side)
	}
	if tr.Price != "0.72" {
		t.Errorf("Price: got %q", tr.Price)
	}
	if tr.Timestamp != 1711234567 {
		t.Errorf("Timestamp: got %d", tr.Timestamp)
	}
}

// -------------------------------------------------------------------------
// HTTP endpoint tests
// -------------------------------------------------------------------------

func TestGetMarkets(t *testing.T) {
	markets := []Market{
		{ID: "1", Question: "Q1", Active: true, ConditionID: "0x1"},
		{ID: "2", Question: "Q2", Active: true, ConditionID: "0x2"},
	}

	var capturedPath string
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedPath = r.URL.Path + "?" + r.URL.RawQuery
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(markets)
	}))
	defer teardown()

	active := true
	got, err := client.GetMarkets(context.Background(), &MarketQuery{Active: &active, Limit: 10})
	if err != nil {
		t.Fatalf("GetMarkets: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("len: got %d, want 2", len(got))
	}
	if got[0].Question != "Q1" {
		t.Errorf("Question: got %q", got[0].Question)
	}
	// Verify query params were sent
	if capturedPath != "/markets?active=true&limit=10" {
		t.Errorf("URL path+query: got %q", capturedPath)
	}
}

func TestGetMarket(t *testing.T) {
	market := Market{ID: "5", ConditionID: "0xfeed", Question: "Single market"}
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]Market{market})
	}))
	defer teardown()

	got, err := client.GetMarket(context.Background(), "0xfeed")
	if err != nil {
		t.Fatalf("GetMarket: %v", err)
	}
	if got.ConditionID != "0xfeed" {
		t.Errorf("ConditionID: got %q", got.ConditionID)
	}
}

func TestGetMarketNotFound(t *testing.T) {
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]Market{})
	}))
	defer teardown()

	_, err := client.GetMarket(context.Background(), "0xmissing")
	if err == nil {
		t.Fatal("expected error for missing market")
	}
}

func TestGetEvents(t *testing.T) {
	events := []Event{{ID: "10", Title: "Ev1"}, {ID: "11", Title: "Ev2"}}

	var capturedQuery string
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedQuery = r.URL.RawQuery
		_ = json.NewEncoder(w).Encode(events)
	}))
	defer teardown()

	closed := false
	got, err := client.GetEvents(context.Background(), &EventQuery{Closed: &closed, Limit: 5, Tag: "politics"})
	if err != nil {
		t.Fatalf("GetEvents: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("len: got %d", len(got))
	}
	if !contains(capturedQuery, "closed=false") {
		t.Errorf("query missing closed param: %q", capturedQuery)
	}
	if !contains(capturedQuery, "tag=politics") {
		t.Errorf("query missing tag param: %q", capturedQuery)
	}
}

func TestGetEvent(t *testing.T) {
	event := Event{ID: "99", Title: "Single Event"}
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/events/99" {
			http.Error(w, "not found", 404)
			return
		}
		_ = json.NewEncoder(w).Encode(event)
	}))
	defer teardown()

	got, err := client.GetEvent(context.Background(), "99")
	if err != nil {
		t.Fatalf("GetEvent: %v", err)
	}
	if got.Title != "Single Event" {
		t.Errorf("Title: got %q", got.Title)
	}
}

func TestGetOrderBook(t *testing.T) {
	ob := OrderBook{
		Market:  "0xmarket",
		AssetID: "token123",
		Bids:    []OrderBookLevel{{Price: "0.68", Size: "500"}},
		Asks:    []OrderBookLevel{{Price: "0.72", Size: "300"}},
	}
	var capturedQuery string
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedQuery = r.URL.RawQuery
		_ = json.NewEncoder(w).Encode(ob)
	}))
	defer teardown()

	got, err := client.GetOrderBook(context.Background(), "token123")
	if err != nil {
		t.Fatalf("GetOrderBook: %v", err)
	}
	if len(got.Bids) != 1 || got.Bids[0].Price != "0.68" {
		t.Errorf("Bids: got %v", got.Bids)
	}
	if !contains(capturedQuery, "token_id=token123") {
		t.Errorf("query: got %q", capturedQuery)
	}
}

func TestGetTrades(t *testing.T) {
	trades := []Trade{
		{Side: "BUY", Price: "0.70", Outcome: "Yes"},
		{Side: "SELL", Price: "0.30", Outcome: "No"},
	}
	var capturedQuery string
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedQuery = r.URL.RawQuery
		_ = json.NewEncoder(w).Encode(trades)
	}))
	defer teardown()

	got, err := client.GetTrades(context.Background(), &TradeQuery{Market: "0xabc", Limit: 20})
	if err != nil {
		t.Fatalf("GetTrades: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("len: got %d", len(got))
	}
	if !contains(capturedQuery, "market=0xabc") {
		t.Errorf("query: got %q", capturedQuery)
	}
	if !contains(capturedQuery, "limit=20") {
		t.Errorf("query: got %q", capturedQuery)
	}
}

// -------------------------------------------------------------------------
// Error handling tests
// -------------------------------------------------------------------------

func TestError404(t *testing.T) {
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not found", 404)
	}))
	defer teardown()

	_, err := client.GetEvents(context.Background(), nil)
	if err == nil {
		t.Fatal("expected error")
	}
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 404 {
		t.Errorf("StatusCode: got %d", apiErr.StatusCode)
	}
}

func TestError429(t *testing.T) {
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(429)
		_, _ = w.Write([]byte("rate limit exceeded"))
	}))
	defer teardown()

	_, err := client.GetMarkets(context.Background(), nil)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.StatusCode != 429 {
		t.Errorf("StatusCode: got %d", apiErr.StatusCode)
	}
}

func TestError500(t *testing.T) {
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		_, _ = w.Write([]byte("internal server error"))
	}))
	defer teardown()

	_, err := client.GetMarkets(context.Background(), nil)
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("expected *APIError, got %T", err)
	}
	if apiErr.StatusCode != 500 {
		t.Errorf("StatusCode: got %d", apiErr.StatusCode)
	}
}

func TestContextCancellation(t *testing.T) {
	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
		_ = json.NewEncoder(w).Encode([]Market{})
	}))
	defer teardown()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()

	_, err := client.GetMarkets(ctx, nil)
	if err == nil {
		t.Fatal("expected timeout error")
	}
}

// -------------------------------------------------------------------------
// Cache test
// -------------------------------------------------------------------------

func TestCaching(t *testing.T) {
	callCount := 0
	markets := []Market{{ID: "1", Question: "Cached?"}}

	client, teardown := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		_ = json.NewEncoder(w).Encode(markets)
	}))
	defer teardown()

	// Enable cache with a long TTL
	client.cache = newResponseCache(1 * time.Minute)

	for i := 0; i < 3; i++ {
		_, err := client.GetMarkets(context.Background(), nil)
		if err != nil {
			t.Fatalf("GetMarkets iter %d: %v", i, err)
		}
	}

	if callCount != 1 {
		t.Errorf("expected 1 HTTP call (cache hit), got %d", callCount)
	}
}

// -------------------------------------------------------------------------
// URL construction test
// -------------------------------------------------------------------------

func TestURLConstruction(t *testing.T) {
	tests := []struct {
		base   string
		params map[string]string
		want   string
	}{
		{
			base:   "https://example.com/markets",
			params: map[string]string{"active": "true", "limit": "10"},
			// url.Values sorts keys alphabetically
			want: "https://example.com/markets?active=true&limit=10",
		},
		{
			base:   "https://example.com/markets",
			params: nil,
			want:   "https://example.com/markets",
		},
	}

	for _, tt := range tests {
		params := make(map[string][]string)
		for k, v := range tt.params {
			params[k] = []string{v}
		}
		got := buildURL(tt.base, params)
		if got != tt.want {
			t.Errorf("buildURL(%q): got %q, want %q", tt.base, got, tt.want)
		}
	}
}

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsStr(s, substr))
}

func containsStr(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
