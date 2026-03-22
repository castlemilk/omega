package connectors

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/benebsworth/omega/internal/integrations"
)

const binanceBaseURL = "https://api.binance.com/api/v3"

// Binance is a public API connector for Binance market data (no auth required).
type Binance struct {
	client *integrations.SharedHTTPClient
}

// NewBinance creates a Binance connector.
func NewBinance(client *integrations.SharedHTTPClient) *Binance {
	return &Binance{client: client}
}

func (b *Binance) Name() string                { return "binance" }
func (b *Binance) Category() integrations.Category { return integrations.MarketData }

func (b *Binance) HealthCheck(ctx context.Context) error {
	resp, err := b.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: binanceBaseURL + "/ping",
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("binance ping: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector.
func (b *Binance) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	return b.client.Do(ctx, req)
}

// TickerPrice holds the current price for a symbol.
type TickerPrice struct {
	Symbol string `json:"symbol"`
	Price  string `json:"price"`
}

// GetPrice retrieves the latest price for a trading symbol (e.g. "BTCUSDT").
func (b *Binance) GetPrice(ctx context.Context, symbol string) (*TickerPrice, error) {
	resp, err := b.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: binanceBaseURL + "/ticker/price",
		Params:   map[string]string{"symbol": symbol},
	})
	if err != nil {
		return nil, fmt.Errorf("binance get_price: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("binance get_price: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var ticker TickerPrice
	if err := json.Unmarshal(resp.Body, &ticker); err != nil {
		return nil, fmt.Errorf("binance get_price decode: %w", err)
	}
	return &ticker, nil
}

// Kline represents a single OHLCV candlestick.
// Fields are ordered as returned by the Binance API.
type Kline struct {
	OpenTime  int64
	Open      string
	High      string
	Low       string
	Close     string
	Volume    string
	CloseTime int64
}

// GetKlines retrieves OHLCV candlestick data.
// interval examples: "1m", "5m", "1h", "1d"
func (b *Binance) GetKlines(ctx context.Context, symbol, interval string, limit int) ([]Kline, error) {
	resp, err := b.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: binanceBaseURL + "/klines",
		Params: map[string]string{
			"symbol":   symbol,
			"interval": interval,
			"limit":    fmt.Sprintf("%d", limit),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("binance klines: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("binance klines: HTTP %d: %s", resp.StatusCode, resp.Body)
	}

	// Binance returns a [][]any; we parse only the fields we need.
	var raw [][]json.RawMessage
	if err := json.Unmarshal(resp.Body, &raw); err != nil {
		return nil, fmt.Errorf("binance klines decode: %w", err)
	}

	klines := make([]Kline, 0, len(raw))
	for _, row := range raw {
		if len(row) < 7 {
			continue
		}
		var k Kline
		_ = json.Unmarshal(row[0], &k.OpenTime)
		_ = json.Unmarshal(row[1], &k.Open)
		_ = json.Unmarshal(row[2], &k.High)
		_ = json.Unmarshal(row[3], &k.Low)
		_ = json.Unmarshal(row[4], &k.Close)
		_ = json.Unmarshal(row[5], &k.Volume)
		_ = json.Unmarshal(row[6], &k.CloseTime)
		klines = append(klines, k)
	}
	return klines, nil
}

// OrderBook holds the current bids and asks for a symbol.
type OrderBook struct {
	LastUpdateID int64      `json:"lastUpdateId"`
	Bids         [][]string `json:"bids"` // [[price, qty], ...]
	Asks         [][]string `json:"asks"`
}

// GetOrderBook retrieves the order book depth for a symbol.
// limit controls how many price levels to return (max 5000).
func (b *Binance) GetOrderBook(ctx context.Context, symbol string, limit int) (*OrderBook, error) {
	resp, err := b.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: binanceBaseURL + "/depth",
		Params: map[string]string{
			"symbol": symbol,
			"limit":  fmt.Sprintf("%d", limit),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("binance order_book: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("binance order_book: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var ob OrderBook
	if err := json.Unmarshal(resp.Body, &ob); err != nil {
		return nil, fmt.Errorf("binance order_book decode: %w", err)
	}
	return &ob, nil
}
