package handler_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/handler"
	"github.com/benebsworth/omega/internal/integrations"
	"github.com/benebsworth/omega/internal/integrations/connectors"
)

// ── mock connectors ───────────────────────────────────────────────────────────

type mockBinance struct {
	price     *connectors.TickerPrice
	klines    []connectors.Kline
	orderBook *connectors.OrderBook
	err       error
}

func (m *mockBinance) GetPrice(_ context.Context, _ string) (*connectors.TickerPrice, error) {
	return m.price, m.err
}

func (m *mockBinance) GetKlines(_ context.Context, _, _ string, _ int) ([]connectors.Kline, error) {
	return m.klines, m.err
}

func (m *mockBinance) GetOrderBook(_ context.Context, _ string, _ int) (*connectors.OrderBook, error) {
	return m.orderBook, m.err
}

type mockCoinGecko struct {
	prices  map[string]map[string]float64
	markets []connectors.CoinMarket
	err     error
}

func (m *mockCoinGecko) GetPrice(_ context.Context, _ []string, _ []string) (map[string]map[string]float64, error) {
	return m.prices, m.err
}

func (m *mockCoinGecko) GetMarkets(_ context.Context, _ string, _, _ int) ([]connectors.CoinMarket, error) {
	return m.markets, m.err
}

// ── test helpers ──────────────────────────────────────────────────────────────

func newDataHandlerWithMocks(b handler.BinanceConnector, cg handler.CoinGeckoConnector) *handler.DataHandler {
	reg := integrations.NewConnectorRegistry()
	return handler.NewDataWithMocks(reg, b, cg)
}

func setupDataServer(t *testing.T, h *handler.DataHandler) (omegav1connect.DataServiceClient, func()) {
	t.Helper()
	mux := http.NewServeMux()
	path, svc := omegav1connect.NewDataServiceHandler(h)
	mux.Handle(path, svc)
	srv := httptest.NewServer(mux)
	client := omegav1connect.NewDataServiceClient(http.DefaultClient, srv.URL)
	return client, srv.Close
}

// ── GetOHLCV ──────────────────────────────────────────────────────────────────

func TestDataHandler_GetOHLCV_Success(t *testing.T) {
	mb := &mockBinance{
		klines: []connectors.Kline{
			{OpenTime: 1000, Open: "50000.0", High: "51000.0", Low: "49000.0", Close: "50500.0", Volume: "100.0", CloseTime: 2000},
			{OpenTime: 2000, Open: "50500.0", High: "52000.0", Low: "50000.0", Close: "51000.0", Volume: "200.0", CloseTime: 3000},
		},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(mb, nil))
	defer cleanup()

	resp, err := client.GetOHLCV(context.Background(), connect.NewRequest(&omegav1.GetOHLCVRequest{
		Symbol:   "BTCUSDT",
		Interval: omegav1.OHLCVInterval_OHLCV_INTERVAL_1H,
		Limit:    2,
	}))
	if err != nil {
		t.Fatalf("GetOHLCV: %v", err)
	}
	if len(resp.Msg.Klines) != 2 {
		t.Errorf("expected 2 klines, got %d", len(resp.Msg.Klines))
	}
	if resp.Msg.Symbol != "BTCUSDT" {
		t.Errorf("expected symbol BTCUSDT, got %s", resp.Msg.Symbol)
	}
	if resp.Msg.Exchange != "binance" {
		t.Errorf("expected exchange binance, got %s", resp.Msg.Exchange)
	}
	if resp.Msg.Klines[0].Open != 50000.0 {
		t.Errorf("expected open 50000.0, got %f", resp.Msg.Klines[0].Open)
	}
}

func TestDataHandler_GetOHLCV_NilConnector(t *testing.T) {
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, nil))
	defer cleanup()

	_, err := client.GetOHLCV(context.Background(), connect.NewRequest(&omegav1.GetOHLCVRequest{
		Symbol: "BTCUSDT",
	}))
	if err == nil {
		t.Fatal("expected error when binance is nil")
	}
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("expected CodeUnavailable, got %s", connect.CodeOf(err))
	}
}

// ── GetTicker ─────────────────────────────────────────────────────────────────

func TestDataHandler_GetTicker_Binance(t *testing.T) {
	mb := &mockBinance{
		price: &connectors.TickerPrice{Symbol: "BTCUSDT", Price: "49500.50"},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(mb, nil))
	defer cleanup()

	resp, err := client.GetTicker(context.Background(), connect.NewRequest(&omegav1.GetTickerRequest{
		Symbol:   "BTCUSDT",
		Exchange: "binance",
	}))
	if err != nil {
		t.Fatalf("GetTicker: %v", err)
	}
	if resp.Msg.Price != 49500.50 {
		t.Errorf("expected price 49500.50, got %f", resp.Msg.Price)
	}
	if resp.Msg.Exchange != "binance" {
		t.Errorf("expected exchange binance, got %s", resp.Msg.Exchange)
	}
}

func TestDataHandler_GetTicker_CoinGecko(t *testing.T) {
	mcg := &mockCoinGecko{
		prices: map[string]map[string]float64{
			"bitcoin": {"usd": 48000.0},
		},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, mcg))
	defer cleanup()

	resp, err := client.GetTicker(context.Background(), connect.NewRequest(&omegav1.GetTickerRequest{
		Symbol:   "bitcoin",
		Exchange: "coingecko",
	}))
	if err != nil {
		t.Fatalf("GetTicker: %v", err)
	}
	if resp.Msg.Price != 48000.0 {
		t.Errorf("expected price 48000.0, got %f", resp.Msg.Price)
	}
	if resp.Msg.Exchange != "coingecko" {
		t.Errorf("expected exchange coingecko, got %s", resp.Msg.Exchange)
	}
}

func TestDataHandler_GetTicker_CoinGecko_NotFound(t *testing.T) {
	mcg := &mockCoinGecko{
		prices: map[string]map[string]float64{},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, mcg))
	defer cleanup()

	_, err := client.GetTicker(context.Background(), connect.NewRequest(&omegav1.GetTickerRequest{
		Symbol:   "unknowncoin",
		Exchange: "coingecko",
	}))
	if err == nil {
		t.Fatal("expected CodeNotFound error")
	}
	if connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("expected CodeNotFound, got %s", connect.CodeOf(err))
	}
}

// ── GetOrderBook ──────────────────────────────────────────────────────────────

func TestDataHandler_GetOrderBook_Success(t *testing.T) {
	mb := &mockBinance{
		orderBook: &connectors.OrderBook{
			LastUpdateID: 12345,
			Bids:         [][]string{{"50000.0", "1.5"}, {"49999.0", "2.0"}},
			Asks:         [][]string{{"50001.0", "1.0"}, {"50002.0", "3.0"}},
		},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(mb, nil))
	defer cleanup()

	resp, err := client.GetOrderBook(context.Background(), connect.NewRequest(&omegav1.GetOrderBookRequest{
		Symbol: "BTCUSDT",
		Depth:  2,
	}))
	if err != nil {
		t.Fatalf("GetOrderBook: %v", err)
	}
	if resp.Msg.LastUpdateId != 12345 {
		t.Errorf("expected lastUpdateId 12345, got %d", resp.Msg.LastUpdateId)
	}
	if len(resp.Msg.Bids) != 2 {
		t.Errorf("expected 2 bids, got %d", len(resp.Msg.Bids))
	}
	if len(resp.Msg.Asks) != 2 {
		t.Errorf("expected 2 asks, got %d", len(resp.Msg.Asks))
	}
	if resp.Msg.Bids[0].Price != 50000.0 {
		t.Errorf("expected bid price 50000.0, got %f", resp.Msg.Bids[0].Price)
	}
}

// ── ListDataSources ───────────────────────────────────────────────────────────

func TestDataHandler_ListDataSources_Empty(t *testing.T) {
	reg := integrations.NewConnectorRegistry()
	h := handler.NewData(reg, nil, nil)
	client, cleanup := setupDataServer(t, h)
	defer cleanup()

	resp, err := client.ListDataSources(context.Background(), connect.NewRequest(&omegav1.ListDataSourcesRequest{}))
	if err != nil {
		t.Fatalf("ListDataSources: %v", err)
	}
	if len(resp.Msg.Sources) != 0 {
		t.Errorf("expected empty sources for empty registry, got %d", len(resp.Msg.Sources))
	}
}

// ── GetMarketOverview ─────────────────────────────────────────────────────────

func TestDataHandler_GetMarketOverview_Success(t *testing.T) {
	mcg := &mockCoinGecko{
		markets: []connectors.CoinMarket{
			{ID: "bitcoin", Symbol: "btc", Name: "Bitcoin", CurrentPrice: 50000.0, MarketCap: 1e12, MarketCapRank: 1, TotalVolume: 5e10, PriceChangePercentage24h: 2.5},
			{ID: "ethereum", Symbol: "eth", Name: "Ethereum", CurrentPrice: 3000.0, MarketCap: 3e11, MarketCapRank: 2, TotalVolume: 2e10, PriceChangePercentage24h: 1.2},
		},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, mcg))
	defer cleanup()

	resp, err := client.GetMarketOverview(context.Background(), connect.NewRequest(&omegav1.GetMarketOverviewRequest{
		VsCurrency: "usd",
		Limit:      2,
	}))
	if err != nil {
		t.Fatalf("GetMarketOverview: %v", err)
	}
	if len(resp.Msg.Coins) != 2 {
		t.Errorf("expected 2 coins, got %d", len(resp.Msg.Coins))
	}
	if resp.Msg.VsCurrency != "usd" {
		t.Errorf("expected vs_currency usd, got %s", resp.Msg.VsCurrency)
	}
	if resp.Msg.Coins[0].Id != "bitcoin" {
		t.Errorf("expected first coin bitcoin, got %s", resp.Msg.Coins[0].Id)
	}
	if resp.Msg.Coins[0].CurrentPrice != 50000.0 {
		t.Errorf("expected price 50000.0, got %f", resp.Msg.Coins[0].CurrentPrice)
	}
}

func TestDataHandler_GetMarketOverview_DefaultCurrency(t *testing.T) {
	mcg := &mockCoinGecko{
		markets: []connectors.CoinMarket{
			{ID: "bitcoin", Symbol: "btc", Name: "Bitcoin", CurrentPrice: 50000.0},
		},
	}
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, mcg))
	defer cleanup()

	resp, err := client.GetMarketOverview(context.Background(), connect.NewRequest(&omegav1.GetMarketOverviewRequest{}))
	if err != nil {
		t.Fatalf("GetMarketOverview: %v", err)
	}
	if resp.Msg.VsCurrency != "usd" {
		t.Errorf("expected default vs_currency usd, got %s", resp.Msg.VsCurrency)
	}
}

func TestDataHandler_GetMarketOverview_NilConnector(t *testing.T) {
	client, cleanup := setupDataServer(t, newDataHandlerWithMocks(nil, nil))
	defer cleanup()

	_, err := client.GetMarketOverview(context.Background(), connect.NewRequest(&omegav1.GetMarketOverviewRequest{}))
	if err == nil {
		t.Fatal("expected error when coingecko is nil")
	}
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("expected CodeUnavailable, got %s", connect.CodeOf(err))
	}
}
