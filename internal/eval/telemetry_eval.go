package eval

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ── TelemetryHealthCheck ──────────────────────────────────────────────────────

// HealthReport is the result of querying the live observability stack.
type HealthReport struct {
	// Overall score 0–1 aggregated from component scores.
	Score float64

	// ComponentScores maps component name → 0–1 score.
	ComponentScores map[string]float64

	// TraceVolume is the number of traces found in the Tempo query window.
	TraceVolume int

	// ErrorSpanRate is the fraction of spans with an error status (0–1).
	ErrorSpanRate float64

	// P99Latency is the 99th-percentile root-span duration in seconds.
	// Zero when no traces are present.
	P99Latency float64

	// MetricsFreshness is the age of the most recent metric scrape.
	// Zero when the metrics endpoint is unreachable.
	MetricsFreshness time.Duration

	// Anomalies is a list of human-readable anomaly descriptions.
	Anomalies []string

	// RecommendedActions lists follow-up actions keyed by priority.
	RecommendedActions []string

	// EvaluatedAt is when the health check ran.
	EvaluatedAt time.Time
}

// TelemetryHealthCheck queries the live OTel/Tempo stack and returns a
// HealthReport. tempoURL is the Tempo HTTP API base (e.g. "http://localhost:3200").
// metricsURL is the OTel Collector Prometheus endpoint (e.g. "http://localhost:8889/metrics").
type TelemetryHealthCheck struct {
	TempoURL   string
	MetricsURL string
	HTTPClient *http.Client
}

// NewTelemetryHealthCheck returns a TelemetryHealthCheck with a default HTTP client.
func NewTelemetryHealthCheck(tempoURL, metricsURL string) *TelemetryHealthCheck {
	return &TelemetryHealthCheck{
		TempoURL:   tempoURL,
		MetricsURL: metricsURL,
		HTTPClient: &http.Client{Timeout: 10 * time.Second},
	}
}

// tempoSearchResult mirrors the Tempo /api/search JSON response (subset).
type tempoSearchResult struct {
	Traces []tempoTrace `json:"traces"`
}

type tempoTrace struct {
	TraceID           string  `json:"traceID"`
	RootServiceName   string  `json:"rootServiceName"`
	RootTraceName     string  `json:"rootTraceName"`
	StartTimeUnixNano string  `json:"startTimeUnixNano"`
	DurationMs        float64 `json:"durationMs"`
	SpanSet           *struct {
		Spans []struct {
			StatusCode string `json:"statusCode"`
		} `json:"spans"`
	} `json:"spanSet,omitempty"`
}

// queryTempo calls GET /api/search on the Tempo HTTP API and returns raw traces.
func (t *TelemetryHealthCheck) queryTempo(ctx context.Context) (*tempoSearchResult, error) {
	url := fmt.Sprintf("%s/api/search?limit=100&start=%d&end=%d",
		strings.TrimRight(t.TempoURL, "/"),
		time.Now().Add(-15*time.Minute).Unix(),
		time.Now().Unix(),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("build tempo request: %w", err)
	}
	resp, err := t.HTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("tempo search: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("tempo search returned HTTP %d", resp.StatusCode)
	}
	var result tempoSearchResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode tempo response: %w", err)
	}
	return &result, nil
}

// queryMetrics fetches the raw Prometheus metrics text from the OTel Collector.
func (t *TelemetryHealthCheck) queryMetrics(ctx context.Context) (string, time.Time, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, t.MetricsURL, nil)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("build metrics request: %w", err)
	}
	req.Header.Set("Accept", "text/plain")
	resp, err := t.HTTPClient.Do(req)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("metrics fetch: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", time.Time{}, fmt.Errorf("metrics endpoint returned HTTP %d", resp.StatusCode)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // 1 MiB cap
	if err != nil {
		return "", time.Time{}, fmt.Errorf("read metrics body: %w", err)
	}
	return string(b), time.Now(), nil
}

// analyseTraces derives TraceVolume, ErrorSpanRate and P99Latency from Tempo results.
func analyseTraces(result *tempoSearchResult) (volume int, errorRate float64, p99 float64) {
	if result == nil || len(result.Traces) == 0 {
		return 0, 0, 0
	}
	volume = len(result.Traces)

	var totalSpans, errorSpans int
	durations := make([]float64, 0, volume)

	for _, tr := range result.Traces {
		durations = append(durations, tr.DurationMs)
		if tr.SpanSet != nil {
			for _, sp := range tr.SpanSet.Spans {
				totalSpans++
				if sp.StatusCode == "STATUS_CODE_ERROR" || sp.StatusCode == "2" {
					errorSpans++
				}
			}
		}
	}

	if totalSpans > 0 {
		errorRate = float64(errorSpans) / float64(totalSpans)
	}

	// Simple p99 approximation: sort inline via selection.
	p99 = percentile99(durations) / 1000.0 // ms → seconds
	return volume, errorRate, p99
}

// percentile99 returns the 99th-percentile value from an unsorted slice.
func percentile99(vals []float64) float64 {
	if len(vals) == 0 {
		return 0
	}
	// Insertion sort (small slices expected).
	sorted := make([]float64, len(vals))
	copy(sorted, vals)
	for i := 1; i < len(sorted); i++ {
		for j := i; j > 0 && sorted[j] < sorted[j-1]; j-- {
			sorted[j], sorted[j-1] = sorted[j-1], sorted[j]
		}
	}
	idx := int(float64(len(sorted)-1) * 0.99)
	return sorted[idx]
}

// Run executes the full telemetry health check and returns a HealthReport.
func (t *TelemetryHealthCheck) Run(ctx context.Context) HealthReport {
	report := HealthReport{
		ComponentScores: make(map[string]float64),
		EvaluatedAt:     time.Now().UTC(),
	}

	// ── Tempo: trace volume, error rate, latency ───────────────────────────
	tempoScore := 0.0
	tempoResult, err := t.queryTempo(ctx)
	if err != nil {
		report.Anomalies = append(report.Anomalies, fmt.Sprintf("Tempo unreachable: %v", err))
		report.RecommendedActions = append(report.RecommendedActions, "Start OTel stack: make otel-up")
	} else {
		vol, errRate, p99 := analyseTraces(tempoResult)
		report.TraceVolume = vol
		report.ErrorSpanRate = errRate
		report.P99Latency = p99

		// Score: full marks if traces flowing, error rate < 5%, p99 < 2s.
		tempoScore = 1.0
		if vol == 0 {
			tempoScore -= 0.4
			report.Anomalies = append(report.Anomalies, "No traces found in last 15 minutes — is the service instrumented?")
			report.RecommendedActions = append(report.RecommendedActions, "Set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 and restart omega-api")
		}
		if errRate > 0.05 {
			penalty := errRate * 0.5
			if penalty > 0.5 {
				penalty = 0.5
			}
			tempoScore -= penalty
			report.Anomalies = append(report.Anomalies, fmt.Sprintf("High error span rate: %.1f%%", errRate*100))
			report.RecommendedActions = append(report.RecommendedActions, "Investigate error spans in Grafana Tempo datasource")
		}
		if p99 > 2.0 {
			tempoScore -= 0.2
			report.Anomalies = append(report.Anomalies, fmt.Sprintf("P99 latency %.2fs exceeds 2s threshold", p99))
			report.RecommendedActions = append(report.RecommendedActions, "Profile handler latency — check memory write queue depth")
		}
		if tempoScore < 0 {
			tempoScore = 0
		}
	}
	report.ComponentScores["tempo"] = tempoScore

	// ── OTel Collector: metrics freshness ─────────────────────────────────
	metricsScore := 0.0
	_, scrapeTime, err := t.queryMetrics(ctx)
	if err != nil {
		report.Anomalies = append(report.Anomalies, fmt.Sprintf("OTel Collector metrics unreachable: %v", err))
		report.RecommendedActions = append(report.RecommendedActions, "Check OTel Collector is running: make otel-logs")
	} else {
		report.MetricsFreshness = time.Since(scrapeTime)
		metricsScore = 1.0
		if report.MetricsFreshness > 2*time.Minute {
			metricsScore = 0.5
			report.Anomalies = append(report.Anomalies, fmt.Sprintf("Metrics stale: last scrape %s ago", report.MetricsFreshness.Round(time.Second)))
		}
	}
	report.ComponentScores["metrics"] = metricsScore

	// ── Overall score ──────────────────────────────────────────────────────
	var sum float64
	for _, s := range report.ComponentScores {
		sum += s
	}
	if len(report.ComponentScores) > 0 {
		report.Score = sum / float64(len(report.ComponentScores))
	}

	return report
}

// ── SystemHealthFromTelemetry ─────────────────────────────────────────────────

// SystemHealthFromTelemetry is a convenience wrapper that instantiates a
// TelemetryHealthCheck and calls Run.
func SystemHealthFromTelemetry(ctx context.Context, tempoURL, metricsURL string) (HealthReport, error) {
	chk := NewTelemetryHealthCheck(tempoURL, metricsURL)
	report := chk.Run(ctx)
	return report, nil
}

// ── Integration with RunVictoriaEval ─────────────────────────────────────────

// TelemetryOptions controls whether RunVictoriaEvalWithTelemetry queries the
// live observability stack during the eval run.
type TelemetryOptions struct {
	// Enabled activates the telemetry-aware mode.
	Enabled bool

	// TempoURL is the Tempo HTTP API base URL (default: http://localhost:3200).
	TempoURL string

	// MetricsURL is the OTel Collector Prometheus endpoint (default: http://localhost:8889/metrics).
	MetricsURL string
}

// DefaultTelemetryOptions returns TelemetryOptions pointing at the local stack.
func DefaultTelemetryOptions() TelemetryOptions {
	return TelemetryOptions{
		Enabled:    true,
		TempoURL:   "http://localhost:3200",
		MetricsURL: "http://localhost:8889/metrics",
	}
}

// VictoriaReportWithTelemetry extends VictoriaReport with an optional
// HealthReport from the live observability stack.
type VictoriaReportWithTelemetry struct {
	VictoriaReport
	Telemetry *HealthReport // nil when telemetry is disabled or the stack is unreachable.
}

// RunVictoriaEvalWithTelemetry runs the standard eval suite and optionally
// augments it with a live telemetry health check.
func RunVictoriaEvalWithTelemetry(ctx context.Context, provider VictoriaProvider, opts TelemetryOptions) VictoriaReportWithTelemetry {
	base := RunVictoriaEval(provider)
	result := VictoriaReportWithTelemetry{VictoriaReport: base}

	if !opts.Enabled {
		return result
	}

	tempoURL := opts.TempoURL
	if tempoURL == "" {
		tempoURL = "http://localhost:3200"
	}
	metricsURL := opts.MetricsURL
	if metricsURL == "" {
		metricsURL = "http://localhost:8889/metrics"
	}

	hr, _ := SystemHealthFromTelemetry(ctx, tempoURL, metricsURL)
	result.Telemetry = &hr
	return result
}
