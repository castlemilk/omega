package connectors

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/benebsworth/omega/internal/integrations"
)

const alphaVantageBaseURL = "https://www.alphavantage.co/query"

// AlphaVantage connects to the Alpha Vantage API (requires an API key).
type AlphaVantage struct {
	client *integrations.SharedHTTPClient
	apiKey string
}

// NewAlphaVantage creates an AlphaVantage connector with the given API key.
func NewAlphaVantage(client *integrations.SharedHTTPClient, apiKey string) *AlphaVantage {
	return &AlphaVantage{client: client, apiKey: apiKey}
}

func (a *AlphaVantage) Name() string                { return "alphavantage" }
func (a *AlphaVantage) Category() integrations.Category { return integrations.MarketData }

func (a *AlphaVantage) HealthCheck(ctx context.Context) error {
	resp, err := a.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: alphaVantageBaseURL,
		Params: map[string]string{
			"function": "TIME_SERIES_INTRADAY",
			"symbol":   "IBM",
			"interval": "5min",
			"apikey":   a.apiKey,
		},
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("alphavantage health check: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector.
func (a *AlphaVantage) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	if req.Params == nil {
		req.Params = map[string]string{}
	}
	req.Params["apikey"] = a.apiKey
	return a.client.Do(ctx, req)
}

// DailyTimeSeries holds OHLCV data keyed by date string (YYYY-MM-DD).
type DailyTimeSeries struct {
	MetaData   map[string]string            `json:"Meta Data"`
	TimeSeries map[string]map[string]string `json:"Time Series (Daily)"`
}

// GetDailyPrices retrieves daily adjusted price time series for a stock symbol.
func (a *AlphaVantage) GetDailyPrices(ctx context.Context, symbol string) (*DailyTimeSeries, error) {
	resp, err := a.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: alphaVantageBaseURL,
		Params: map[string]string{
			"function":   "TIME_SERIES_DAILY",
			"symbol":     symbol,
			"outputsize": "compact",
			"apikey":     a.apiKey,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("alphavantage daily_prices: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("alphavantage daily_prices: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var ts DailyTimeSeries
	if err := json.Unmarshal(resp.Body, &ts); err != nil {
		return nil, fmt.Errorf("alphavantage daily_prices decode: %w", err)
	}
	return &ts, nil
}

// GlobalQuote holds the real-time quote data for a symbol.
type GlobalQuote struct {
	Symbol           string `json:"01. symbol"`
	Open             string `json:"02. open"`
	High             string `json:"03. high"`
	Low              string `json:"04. low"`
	Price            string `json:"05. price"`
	Volume           string `json:"06. volume"`
	LatestTradingDay string `json:"07. latest trading day"`
	PreviousClose    string `json:"08. previous close"`
	Change           string `json:"09. change"`
	ChangePercent    string `json:"10. change percent"`
}

// QuoteResponse wraps the Alpha Vantage GLOBAL_QUOTE response.
type QuoteResponse struct {
	GlobalQuote GlobalQuote `json:"Global Quote"`
}

// GetQuote retrieves a real-time quote for a stock symbol.
func (a *AlphaVantage) GetQuote(ctx context.Context, symbol string) (*GlobalQuote, error) {
	resp, err := a.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: alphaVantageBaseURL,
		Params: map[string]string{
			"function": "GLOBAL_QUOTE",
			"symbol":   symbol,
			"apikey":   a.apiKey,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("alphavantage quote: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("alphavantage quote: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var qr QuoteResponse
	if err := json.Unmarshal(resp.Body, &qr); err != nil {
		return nil, fmt.Errorf("alphavantage quote decode: %w", err)
	}
	return &qr.GlobalQuote, nil
}
