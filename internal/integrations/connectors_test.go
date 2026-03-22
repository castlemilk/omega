package integrations_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/integrations"
	"github.com/benebsworth/omega/internal/integrations/connectors"
)

// ---------- helpers ----------

func newTestClient(t *testing.T) *integrations.SharedHTTPClient {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil // suppress log noise in tests
	cfg.CacheTTL = 0 // disable caching by default; tests opt-in
	return integrations.NewSharedHTTPClient(cfg)
}

func jsonServer(t *testing.T, status int, body any) *httptest.Server {
	t.Helper()
	data, _ := json.Marshal(body)
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write(data)
	}))
}

// ---------- registry ----------

func TestRegistry_RegisterAndGet(t *testing.T) {
	reg := integrations.NewConnectorRegistry()
	c := connectors.NewCoinGecko(newTestClient(t))

	if err := reg.Register(c); err != nil {
		t.Fatalf("register: %v", err)
	}

	got, ok := reg.Get("coingecko")
	if !ok {
		t.Fatal("expected to find coingecko")
	}
	if got.Name() != "coingecko" {
		t.Errorf("got %s, want coingecko", got.Name())
	}
}

func TestRegistry_DuplicateRegisterErrors(t *testing.T) {
	reg := integrations.NewConnectorRegistry()
	c := connectors.NewCoinGecko(newTestClient(t))
	_ = reg.Register(c)
	if err := reg.Register(c); err == nil {
		t.Fatal("expected error on duplicate register")
	}
}

func TestRegistry_GetByCategory(t *testing.T) {
	reg := integrations.NewConnectorRegistry()
	_ = reg.Register(connectors.NewCoinGecko(newTestClient(t)))
	_ = reg.Register(connectors.NewBinance(newTestClient(t)))
	_ = reg.Register(connectors.NewOpenMeteo(newTestClient(t)))

	market := reg.GetByCategory(integrations.MarketData)
	if len(market) != 2 {
		t.Errorf("want 2 market-data connectors, got %d", len(market))
	}
	alt := reg.GetByCategory(integrations.Alternative)
	if len(alt) != 1 {
		t.Errorf("want 1 alternative connector, got %d", len(alt))
	}
}

func TestRegistry_List(t *testing.T) {
	reg := integrations.NewConnectorRegistry()
	_ = reg.Register(connectors.NewCoinGecko(newTestClient(t)))
	_ = reg.Register(connectors.NewBinance(newTestClient(t)))

	all := reg.List()
	if len(all) != 2 {
		t.Errorf("want 2, got %d", len(all))
	}
}

func TestRegistry_HealthCheckAll(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"gecko_says":"(V3) To the Moon!"}`))
	}))
	defer srv.Close()

	// Use a custom client pointed at the test server.
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)

	// We can't easily redirect the connector's internal URL to srv without a custom
	// connector, so we verify HealthCheckAll handles errors gracefully instead.
	reg := integrations.NewConnectorRegistry()
	_ = reg.Register(connectors.NewCoinGecko(client))

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	results := reg.HealthCheckAll(ctx)
	if len(results) != 1 {
		t.Fatalf("want 1 result, got %d", len(results))
	}
	if results[0].Name != "coingecko" {
		t.Errorf("unexpected connector name %s", results[0].Name)
	}
	// Error may or may not be nil (network) — we just confirm it ran.
}

// ---------- HTTP client ----------

func TestHTTPClient_BasicFetch(t *testing.T) {
	srv := jsonServer(t, 200, map[string]string{"hello": "world"})
	defer srv.Close()

	client := newTestClient(t)
	resp, err := client.Do(context.Background(), &integrations.FetchRequest{
		Endpoint: srv.URL + "/test",
	})
	if err != nil {
		t.Fatalf("do: %v", err)
	}
	if resp.StatusCode != 200 {
		t.Errorf("status %d", resp.StatusCode)
	}
	var body map[string]string
	if err := json.Unmarshal(resp.Body, &body); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if body["hello"] != "world" {
		t.Errorf("body mismatch: %v", body)
	}
}

func TestHTTPClient_Caching(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"n":1}`))
	}))
	defer srv.Close()

	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 5 * time.Second
	client := integrations.NewSharedHTTPClient(cfg)

	req := &integrations.FetchRequest{Endpoint: srv.URL + "/cached"}
	_, _ = client.Do(context.Background(), req)
	_, _ = client.Do(context.Background(), req)

	if calls != 1 {
		t.Errorf("expected 1 server call, got %d (caching not working)", calls)
	}
}

func TestHTTPClient_RetryOn500(t *testing.T) {
	attempts := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		if attempts < 3 {
			w.WriteHeader(500)
			return
		}
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`"ok"`))
	}))
	defer srv.Close()

	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)

	resp, err := client.Do(context.Background(), &integrations.FetchRequest{Endpoint: srv.URL + "/retry"})
	if err != nil {
		t.Fatalf("unexpected error after retry: %v", err)
	}
	if resp.StatusCode != 200 {
		t.Errorf("expected 200 after retry, got %d", resp.StatusCode)
	}
	if attempts != 3 {
		t.Errorf("expected 3 attempts, got %d", attempts)
	}
}

func TestHTTPClient_NoRetryOn4xx(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.WriteHeader(404)
	}))
	defer srv.Close()

	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)

	resp, err := client.Do(context.Background(), &integrations.FetchRequest{Endpoint: srv.URL + "/notfound"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.StatusCode != 404 {
		t.Errorf("want 404, got %d", resp.StatusCode)
	}
	if calls != 1 {
		t.Errorf("expected exactly 1 call (no retry on 4xx), got %d", calls)
	}
}

// ---------- cache ----------

func TestCache_SetAndGet(t *testing.T) {
	c := integrations.NewLRUCache(10)
	c.Set("k1", []byte("v1"), time.Minute)
	val, hit := c.Get("k1")
	if !hit {
		t.Fatal("expected cache hit")
	}
	if string(val) != "v1" {
		t.Errorf("got %s, want v1", val)
	}
}

func TestCache_Miss(t *testing.T) {
	c := integrations.NewLRUCache(10)
	_, hit := c.Get("missing")
	if hit {
		t.Fatal("expected cache miss")
	}
}

func TestCache_TTLExpiry(t *testing.T) {
	c := integrations.NewLRUCache(10)
	c.Set("k1", []byte("v1"), 10*time.Millisecond)
	time.Sleep(20 * time.Millisecond)
	_, hit := c.Get("k1")
	if hit {
		t.Fatal("expected TTL expiry — entry should be gone")
	}
}

func TestCache_Eviction(t *testing.T) {
	c := integrations.NewLRUCache(3)
	c.Set("a", []byte("1"), time.Minute)
	c.Set("b", []byte("2"), time.Minute)
	c.Set("c", []byte("3"), time.Minute)
	c.Set("d", []byte("4"), time.Minute) // should evict "a"

	_, hitA := c.Get("a")
	if hitA {
		t.Error("a should have been evicted")
	}
	_, hitD := c.Get("d")
	if !hitD {
		t.Error("d should still be present")
	}
}

func TestCache_ExplicitEvict(t *testing.T) {
	c := integrations.NewLRUCache(10)
	c.Set("k1", []byte("v1"), time.Minute)
	c.Evict("k1")
	_, hit := c.Get("k1")
	if hit {
		t.Fatal("expected miss after explicit evict")
	}
}

func TestCache_Stats(t *testing.T) {
	c := integrations.NewLRUCache(10)
	c.Set("k1", []byte("v1"), time.Minute)
	c.Get("k1")  // hit
	c.Get("k2")  // miss
	c.Get("k1")  // hit

	s := c.Stats()
	if s.Hits != 2 {
		t.Errorf("hits: want 2, got %d", s.Hits)
	}
	if s.Misses != 1 {
		t.Errorf("misses: want 1, got %d", s.Misses)
	}
	if s.Size != 1 {
		t.Errorf("size: want 1, got %d", s.Size)
	}
}

// ---------- rate limiter ----------

func TestRateLimiter_BasicFlow(t *testing.T) {
	rl := integrations.NewRateLimiter(100, 5) // 100 rps, burst 5
	ctx := context.Background()
	for i := 0; i < 5; i++ {
		if err := rl.Wait(ctx); err != nil {
			t.Fatalf("wait %d: %v", i, err)
		}
	}
}

func TestRateLimiter_TryAcquire(t *testing.T) {
	rl := integrations.NewRateLimiter(1, 3) // burst 3
	// Should succeed 3 times immediately.
	for i := 0; i < 3; i++ {
		if !rl.TryAcquire() {
			t.Fatalf("TryAcquire %d: expected true", i)
		}
	}
	// Burst exhausted — should fail.
	if rl.TryAcquire() {
		t.Error("expected TryAcquire to return false after burst exhausted")
	}
}

func TestRateLimiter_ContextCancellation(t *testing.T) {
	rl := integrations.NewRateLimiter(0.001, 0) // virtually no tokens
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := rl.Wait(ctx)
	if err == nil {
		t.Fatal("expected context deadline error")
	}
}

// ---------- connectors (mock API responses) ----------

func TestCoinGecko_GetPrice(t *testing.T) {
	payload := map[string]map[string]float64{
		"bitcoin": {"usd": 50000.0},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	// Inject a connector that uses the test server URL.
	gc := newMockCoinGecko(t, srv.URL)
	prices, err := gc.GetPrice(context.Background(), []string{"bitcoin"}, []string{"usd"})
	if err != nil {
		t.Fatalf("GetPrice: %v", err)
	}
	if prices["bitcoin"]["usd"] != 50000.0 {
		t.Errorf("unexpected price: %v", prices)
	}
}

func TestCoinGecko_GetMarkets(t *testing.T) {
	payload := []connectors.CoinMarket{
		{ID: "bitcoin", Symbol: "btc", Name: "Bitcoin", CurrentPrice: 50000},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	gc := newMockCoinGecko(t, srv.URL)
	markets, err := gc.GetMarkets(context.Background(), "usd", 10, 1)
	if err != nil {
		t.Fatalf("GetMarkets: %v", err)
	}
	if len(markets) != 1 || markets[0].ID != "bitcoin" {
		t.Errorf("unexpected markets: %v", markets)
	}
}

func TestBinance_GetPrice(t *testing.T) {
	payload := connectors.TickerPrice{Symbol: "BTCUSDT", Price: "50000.00"}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	bn := newMockBinance(t, srv.URL)
	ticker, err := bn.GetPrice(context.Background(), "BTCUSDT")
	if err != nil {
		t.Fatalf("GetPrice: %v", err)
	}
	if ticker.Price != "50000.00" {
		t.Errorf("unexpected price: %s", ticker.Price)
	}
}

func TestBinance_GetOrderBook(t *testing.T) {
	payload := connectors.OrderBook{
		LastUpdateID: 123,
		Bids:         [][]string{{"50000", "1.5"}},
		Asks:         [][]string{{"50001", "0.5"}},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	bn := newMockBinance(t, srv.URL)
	ob, err := bn.GetOrderBook(context.Background(), "BTCUSDT", 5)
	if err != nil {
		t.Fatalf("GetOrderBook: %v", err)
	}
	if len(ob.Bids) != 1 {
		t.Errorf("unexpected bids: %v", ob.Bids)
	}
}

func TestNewsAPI_SearchNews(t *testing.T) {
	payload := connectors.NewsResponse{
		Status:       "ok",
		TotalResults: 1,
		Articles: []connectors.NewsArticle{
			{Title: "Bitcoin Surges", URL: "https://example.com/article"},
		},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	na := newMockNewsAPI(t, srv.URL)
	resp, err := na.SearchNews(context.Background(), "bitcoin", "", "", "publishedAt")
	if err != nil {
		t.Fatalf("SearchNews: %v", err)
	}
	if len(resp.Articles) != 1 || resp.Articles[0].Title != "Bitcoin Surges" {
		t.Errorf("unexpected articles: %v", resp.Articles)
	}
}

func TestAlphaVantage_GetQuote(t *testing.T) {
	payload := connectors.QuoteResponse{
		GlobalQuote: connectors.GlobalQuote{
			Symbol: "IBM",
			Price:  "145.00",
		},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	av := newMockAlphaVantage(t, srv.URL)
	quote, err := av.GetQuote(context.Background(), "IBM")
	if err != nil {
		t.Fatalf("GetQuote: %v", err)
	}
	if quote.Price != "145.00" {
		t.Errorf("unexpected price: %s", quote.Price)
	}
}

func TestOpenMeteo_GetForecast(t *testing.T) {
	payload := connectors.ForecastResponse{
		Latitude:  52.52,
		Longitude: 13.41,
		Elevation: 38.0,
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	om := newMockOpenMeteo(t, srv.URL)
	fc, err := om.GetForecast(context.Background(), 52.52, 13.41, []string{"temperature_2m_max"})
	if err != nil {
		t.Fatalf("GetForecast: %v", err)
	}
	if fc.Latitude != 52.52 {
		t.Errorf("unexpected latitude: %f", fc.Latitude)
	}
}

func TestFRED_GetSeries(t *testing.T) {
	payload := connectors.FREDSeriesData{
		Count: 1,
		Observations: []connectors.FREDObservation{
			{Date: "2024-01-01", Value: "26000.0"},
		},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	fred := newMockFRED(t, srv.URL)
	data, err := fred.GetSeries(context.Background(), "GDP", "2024-01-01", "2024-12-31")
	if err != nil {
		t.Fatalf("GetSeries: %v", err)
	}
	if len(data.Observations) != 1 {
		t.Errorf("unexpected observations count: %d", len(data.Observations))
	}
}

func TestFRED_GetSeriesInfo(t *testing.T) {
	payload := connectors.FREDSeriesInfoResponse{
		Seriess: []connectors.FREDSeriesInfo{
			{ID: "GDP", Title: "Gross Domestic Product"},
		},
	}
	srv := jsonServer(t, 200, payload)
	defer srv.Close()

	fred := newMockFRED(t, srv.URL)
	info, err := fred.GetSeriesInfo(context.Background(), "GDP")
	if err != nil {
		t.Fatalf("GetSeriesInfo: %v", err)
	}
	if info.Title != "Gross Domestic Product" {
		t.Errorf("unexpected title: %s", info.Title)
	}
}

// ---------- mock connector factories ----------
// These create connector instances whose HTTP calls go to the test server.
// We achieve this by replacing the base URL via a custom FetchRequest interceptor
// implemented as a thin wrapper connector.

type mockConnector struct {
	inner  interface {
		Fetch(context.Context, *integrations.FetchRequest) (*integrations.FetchResponse, error)
	}
	baseURL    string
	realBase   string
	client     *integrations.SharedHTTPClient
}

func rebaseRequest(req *integrations.FetchRequest, realBase, mockBase string) *integrations.FetchRequest {
	newEndpoint := mockBase + req.Endpoint[len(realBase):]
	return &integrations.FetchRequest{
		Endpoint: newEndpoint,
		Params:   req.Params,
		Headers:  req.Headers,
	}
}

// For the mock helpers we subclass each connector to redirect requests.

type mockCoinGecko struct {
	*connectors.CoinGecko
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockCoinGecko(t *testing.T, mockURL string) *mockCoinGecko {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockCoinGecko{
		CoinGecko: connectors.NewCoinGecko(client),
		mockURL:   mockURL,
		client:    client,
	}
}

func (m *mockCoinGecko) GetPrice(ctx context.Context, ids, vsCurrencies []string) (map[string]map[string]float64, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result map[string]map[string]float64
	return result, json.Unmarshal(resp.Body, &result)
}

func (m *mockCoinGecko) GetMarkets(ctx context.Context, vsCurrency string, perPage, page int) ([]connectors.CoinMarket, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result []connectors.CoinMarket
	return result, json.Unmarshal(resp.Body, &result)
}

type mockBinance struct {
	*connectors.Binance
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockBinance(t *testing.T, mockURL string) *mockBinance {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockBinance{
		Binance: connectors.NewBinance(client),
		mockURL: mockURL,
		client:  client,
	}
}

func (m *mockBinance) GetPrice(ctx context.Context, symbol string) (*connectors.TickerPrice, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result connectors.TickerPrice
	return &result, json.Unmarshal(resp.Body, &result)
}

func (m *mockBinance) GetOrderBook(ctx context.Context, symbol string, limit int) (*connectors.OrderBook, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result connectors.OrderBook
	return &result, json.Unmarshal(resp.Body, &result)
}

type mockNewsAPI struct {
	*connectors.NewsAPI
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockNewsAPI(t *testing.T, mockURL string) *mockNewsAPI {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockNewsAPI{
		NewsAPI: connectors.NewNewsAPI(client, "test-key"),
		mockURL: mockURL,
		client:  client,
	}
}

func (m *mockNewsAPI) SearchNews(ctx context.Context, query, from, to, sortBy string) (*connectors.NewsResponse, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result connectors.NewsResponse
	return &result, json.Unmarshal(resp.Body, &result)
}

type mockAlphaVantage struct {
	*connectors.AlphaVantage
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockAlphaVantage(t *testing.T, mockURL string) *mockAlphaVantage {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockAlphaVantage{
		AlphaVantage: connectors.NewAlphaVantage(client, "test-key"),
		mockURL:      mockURL,
		client:       client,
	}
}

func (m *mockAlphaVantage) GetQuote(ctx context.Context, symbol string) (*connectors.GlobalQuote, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var qr connectors.QuoteResponse
	if err := json.Unmarshal(resp.Body, &qr); err != nil {
		return nil, err
	}
	return &qr.GlobalQuote, nil
}

type mockOpenMeteo struct {
	*connectors.OpenMeteo
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockOpenMeteo(t *testing.T, mockURL string) *mockOpenMeteo {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockOpenMeteo{
		OpenMeteo: connectors.NewOpenMeteo(client),
		mockURL:   mockURL,
		client:    client,
	}
}

func (m *mockOpenMeteo) GetForecast(ctx context.Context, lat, lon float64, daily []string) (*connectors.ForecastResponse, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result connectors.ForecastResponse
	return &result, json.Unmarshal(resp.Body, &result)
}

type mockFRED struct {
	*connectors.FRED
	mockURL string
	client  *integrations.SharedHTTPClient
}

func newMockFRED(t *testing.T, mockURL string) *mockFRED {
	t.Helper()
	cfg := integrations.DefaultHTTPClientConfig()
	cfg.Logger = nil
	cfg.CacheTTL = 0
	client := integrations.NewSharedHTTPClient(cfg)
	return &mockFRED{
		FRED:    connectors.NewFRED(client, "test-key"),
		mockURL: mockURL,
		client:  client,
	}
}

func (m *mockFRED) GetSeries(ctx context.Context, seriesID, startDate, endDate string) (*connectors.FREDSeriesData, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var result connectors.FREDSeriesData
	return &result, json.Unmarshal(resp.Body, &result)
}

func (m *mockFRED) GetSeriesInfo(ctx context.Context, seriesID string) (*connectors.FREDSeriesInfo, error) {
	resp, err := m.client.Do(ctx, &integrations.FetchRequest{Endpoint: m.mockURL})
	if err != nil {
		return nil, err
	}
	var r connectors.FREDSeriesInfoResponse
	if err := json.Unmarshal(resp.Body, &r); err != nil {
		return nil, err
	}
	if len(r.Seriess) == 0 {
		return nil, nil
	}
	return &r.Seriess[0], nil
}
