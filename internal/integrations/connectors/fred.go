package connectors

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/benebsworth/omega/internal/integrations"
)

const fredBaseURL = "https://api.stlouisfed.org/fred"

// FRED connects to the Federal Reserve Economic Data API (requires an API key).
type FRED struct {
	client *integrations.SharedHTTPClient
	apiKey string
}

// NewFRED creates a FRED connector with the given API key.
func NewFRED(client *integrations.SharedHTTPClient, apiKey string) *FRED {
	return &FRED{client: client, apiKey: apiKey}
}

func (f *FRED) Name() string                { return "fred" }
func (f *FRED) Category() integrations.Category { return integrations.Macro }

func (f *FRED) HealthCheck(ctx context.Context) error {
	resp, err := f.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: fredBaseURL + "/series",
		Params: map[string]string{
			"series_id":    "GDP",
			"api_key":      f.apiKey,
			"file_type":    "json",
		},
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("fred health check: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector.
func (f *FRED) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	if req.Params == nil {
		req.Params = map[string]string{}
	}
	req.Params["api_key"] = f.apiKey
	req.Params["file_type"] = "json"
	return f.client.Do(ctx, req)
}

// FREDObservation is a single data point from a FRED series.
type FREDObservation struct {
	RealtimeStart string `json:"realtime_start"`
	RealtimeEnd   string `json:"realtime_end"`
	Date          string `json:"date"`
	Value         string `json:"value"`
}

// FREDSeriesData holds the observation list from the FRED series/observations endpoint.
type FREDSeriesData struct {
	RealtimeStart    string            `json:"realtime_start"`
	RealtimeEnd      string            `json:"realtime_end"`
	ObservationStart string            `json:"observation_start"`
	ObservationEnd   string            `json:"observation_end"`
	Units            string            `json:"units"`
	OutputType       int               `json:"output_type"`
	Count            int               `json:"count"`
	Observations     []FREDObservation `json:"observations"`
}

// GetSeries retrieves observations for a FRED economic data series.
// startDate and endDate are YYYY-MM-DD strings. Pass empty string to omit.
func (f *FRED) GetSeries(ctx context.Context, seriesID, startDate, endDate string) (*FREDSeriesData, error) {
	params := map[string]string{
		"series_id": seriesID,
		"api_key":   f.apiKey,
		"file_type": "json",
	}
	if startDate != "" {
		params["observation_start"] = startDate
	}
	if endDate != "" {
		params["observation_end"] = endDate
	}

	resp, err := f.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: fredBaseURL + "/series/observations",
		Params:   params,
	})
	if err != nil {
		return nil, fmt.Errorf("fred get_series: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("fred get_series: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var data FREDSeriesData
	if err := json.Unmarshal(resp.Body, &data); err != nil {
		return nil, fmt.Errorf("fred get_series decode: %w", err)
	}
	return &data, nil
}

// FREDSeriesInfo holds metadata about a FRED series.
type FREDSeriesInfo struct {
	ID                     string `json:"id"`
	RealtimeStart          string `json:"realtime_start"`
	RealtimeEnd            string `json:"realtime_end"`
	Title                  string `json:"title"`
	ObservationStart       string `json:"observation_start"`
	ObservationEnd         string `json:"observation_end"`
	Frequency              string `json:"frequency"`
	FrequencyShort         string `json:"frequency_short"`
	Units                  string `json:"units"`
	SeasonalAdjustment     string `json:"seasonal_adjustment"`
	LastUpdated            string `json:"last_updated"`
	Popularity             int    `json:"popularity"`
}

// FREDSeriesInfoResponse wraps the FRED series endpoint response.
type FREDSeriesInfoResponse struct {
	Seriess []FREDSeriesInfo `json:"seriess"`
}

// GetSeriesInfo retrieves metadata for a FRED series.
func (f *FRED) GetSeriesInfo(ctx context.Context, seriesID string) (*FREDSeriesInfo, error) {
	resp, err := f.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: fredBaseURL + "/series",
		Params: map[string]string{
			"series_id": seriesID,
			"api_key":   f.apiKey,
			"file_type": "json",
		},
	})
	if err != nil {
		return nil, fmt.Errorf("fred get_series_info: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("fred get_series_info: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var r FREDSeriesInfoResponse
	if err := json.Unmarshal(resp.Body, &r); err != nil {
		return nil, fmt.Errorf("fred get_series_info decode: %w", err)
	}
	if len(r.Seriess) == 0 {
		return nil, fmt.Errorf("fred get_series_info: no series found for %s", seriesID)
	}
	return &r.Seriess[0], nil
}
