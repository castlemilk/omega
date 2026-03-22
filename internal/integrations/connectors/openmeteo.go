package connectors

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/benebsworth/omega/internal/integrations"
)

const openMeteoBaseURL = "https://api.open-meteo.com/v1"

// OpenMeteo connects to the Open-Meteo weather API (free, no auth).
type OpenMeteo struct {
	client *integrations.SharedHTTPClient
}

// NewOpenMeteo creates an OpenMeteo connector.
func NewOpenMeteo(client *integrations.SharedHTTPClient) *OpenMeteo {
	return &OpenMeteo{client: client}
}

func (o *OpenMeteo) Name() string                { return "openmeteo" }
func (o *OpenMeteo) Category() integrations.Category { return integrations.Alternative }

func (o *OpenMeteo) HealthCheck(ctx context.Context) error {
	resp, err := o.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: openMeteoBaseURL + "/forecast",
		Params: map[string]string{
			"latitude":  "0",
			"longitude": "0",
			"daily":     "temperature_2m_max",
		},
	})
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("openmeteo health check: HTTP %d", resp.StatusCode)
	}
	return nil
}

// Fetch implements DataConnector.
func (o *OpenMeteo) Fetch(ctx context.Context, req *integrations.FetchRequest) (*integrations.FetchResponse, error) {
	return o.client.Do(ctx, req)
}

// ForecastDaily holds the daily forecast data returned by Open-Meteo.
type ForecastDaily struct {
	Time   []string             `json:"time"`
	Values map[string][]float64 // keyed by requested daily variable name
}

// ForecastResponse wraps the Open-Meteo forecast API response.
type ForecastResponse struct {
	Latitude             float64        `json:"latitude"`
	Longitude            float64        `json:"longitude"`
	GenerationtimeMs     float64        `json:"generationtime_ms"`
	UTCOffsetSeconds     int            `json:"utc_offset_seconds"`
	Timezone             string         `json:"timezone"`
	TimezoneAbbreviation string         `json:"timezone_abbreviation"`
	Elevation            float64        `json:"elevation"`
	DailyUnits           map[string]string `json:"daily_units"`
	Daily                json.RawMessage   `json:"daily"`
}

// GetForecast retrieves daily weather forecasts for a geographic location.
// daily is a list of variable names, e.g. ["temperature_2m_max", "precipitation_sum"].
func (o *OpenMeteo) GetForecast(ctx context.Context, latitude, longitude float64, daily []string) (*ForecastResponse, error) {
	resp, err := o.client.Do(ctx, &integrations.FetchRequest{
		Endpoint: openMeteoBaseURL + "/forecast",
		Params: map[string]string{
			"latitude":  fmt.Sprintf("%g", latitude),
			"longitude": fmt.Sprintf("%g", longitude),
			"daily":     strings.Join(daily, ","),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("openmeteo forecast: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("openmeteo forecast: HTTP %d: %s", resp.StatusCode, resp.Body)
	}
	var forecast ForecastResponse
	if err := json.Unmarshal(resp.Body, &forecast); err != nil {
		return nil, fmt.Errorf("openmeteo forecast decode: %w", err)
	}
	return &forecast, nil
}
