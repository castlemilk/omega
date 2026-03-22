package connectors

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/benebsworth/omega/internal/integrations"
)

const coinGeckoBaseURL = "https://api.coingecko.com/api/v3"

// CoinGecko is a free, no-auth connector for CoinGecko market data.
type CoinGecko struct {
	client *integrations.SharedHTTPClient
}

// NewCoinGecko creates a CoinGecko connector using the provided HTTP client.
func NewCoinGecko(client *integrations.SharedHTTPClient) *CoinGecko {
	return &CoinGecko{client: client}
}

func (c *CoinGecko) Name() string                { return "coingecko" }
func (c *CoinGecko) Category() integrations.Category { return integrations.MarketData }

func (c *CoinGecko) HealthCheck(ctx context.Context) error {
	resp, err := c.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: coinGeckoBaseURL + "/ping",
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("coingecko ping: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector for raw endpoint access.
func (c *CoinGecko) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	return c.client.Do(ctx, req)
}

// CoinPrice holds price data for a single coin.
type CoinPrice struct {
	ID     string             `json:"id"`
	Prices map[string]float64 // vsCurrency -> price
}

// GetPrice returns the current price for one or more coin IDs in the requested currencies.
func (c *CoinGecko) GetPrice(ctx context.Context, ids []string, vsCurrencies []string) (map[string]map[string]float64, error) {
	resp, err := c.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: coinGeckoBaseURL + "/simple/price",
		Params: map[string]string{
			"ids":           strings.Join(ids, ","),
			"vs_currencies": strings.Join(vsCurrencies, ","),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("coingecko get_price: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("coingecko get_price: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var result map[string]map[string]float64
	if err := json.Unmarshal(resp.Body, &result); err != nil {
		return nil, fmt.Errorf("coingecko get_price decode: %w", err)
	}
	return result, nil
}

// MarketChartPoint is a [timestamp_ms, value] pair from the CoinGecko market chart API.
type MarketChartPoint [2]float64

// MarketChart holds price, market cap, and volume time series.
type MarketChart struct {
	Prices       []MarketChartPoint `json:"prices"`
	MarketCaps   []MarketChartPoint `json:"market_caps"`
	TotalVolumes []MarketChartPoint `json:"total_volumes"`
}

// GetMarketChart retrieves historical price data for a coin.
// days can be "1", "7", "30", "max", etc.
func (c *CoinGecko) GetMarketChart(ctx context.Context, id, vsCurrency, days string) (*MarketChart, error) {
	resp, err := c.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: fmt.Sprintf("%s/coins/%s/market_chart", coinGeckoBaseURL, id),
		Params: map[string]string{
			"vs_currency": vsCurrency,
			"days":        days,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("coingecko market_chart: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("coingecko market_chart: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var chart MarketChart
	if err := json.Unmarshal(resp.Body, &chart); err != nil {
		return nil, fmt.Errorf("coingecko market_chart decode: %w", err)
	}
	return &chart, nil
}

// CoinMarket holds a single row from the CoinGecko markets endpoint.
type CoinMarket struct {
	ID                           string  `json:"id"`
	Symbol                       string  `json:"symbol"`
	Name                         string  `json:"name"`
	CurrentPrice                 float64 `json:"current_price"`
	MarketCap                    float64 `json:"market_cap"`
	MarketCapRank                int     `json:"market_cap_rank"`
	TotalVolume                  float64 `json:"total_volume"`
	PriceChangePercentage24h     float64 `json:"price_change_percentage_24h"`
}

// GetMarkets returns a paginated list of coins ordered by market cap.
func (c *CoinGecko) GetMarkets(ctx context.Context, vsCurrency string, perPage, page int) ([]CoinMarket, error) {
	resp, err := c.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: coinGeckoBaseURL + "/coins/markets",
		Params: map[string]string{
			"vs_currency": vsCurrency,
			"order":       "market_cap_desc",
			"per_page":    fmt.Sprintf("%d", perPage),
			"page":        fmt.Sprintf("%d", page),
			"sparkline":   "false",
		},
	})
	if err != nil {
		return nil, fmt.Errorf("coingecko markets: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("coingecko markets: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var markets []CoinMarket
	if err := json.Unmarshal(resp.Body, &markets); err != nil {
		return nil, fmt.Errorf("coingecko markets decode: %w", err)
	}
	return markets, nil
}
