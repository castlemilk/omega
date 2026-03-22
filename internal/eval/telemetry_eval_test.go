package eval

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// ── helpers ───────────────────────────────────────────────────────────────────

func newTempoServer(t *testing.T, result tempoSearchResult) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/search" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(result)
	}))
}

func newMetricsServer(t *testing.T, body string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		_, _ = w.Write([]byte(body))
	}))
}

// ── TelemetryHealthCheck.Run ──────────────────────────────────────────────────

func TestTelemetryHealthCheck_NoTraces(t *testing.T) {
	tempoSrv := newTempoServer(t, tempoSearchResult{Traces: nil})
	defer tempoSrv.Close()
	metricsSrv := newMetricsServer(t, "# HELP omega_handler_requests_total Total requests.\n")
	defer metricsSrv.Close()

	chk := &TelemetryHealthCheck{
		TempoURL:   tempoSrv.URL,
		MetricsURL: metricsSrv.URL,
		HTTPClient: &http.Client{Timeout: 5 * time.Second},
	}

	report := chk.Run(context.Background())

	if report.TraceVolume != 0 {
		t.Errorf("expected TraceVolume=0, got %d", report.TraceVolume)
	}
	if report.Score <= 0 {
		t.Errorf("expected Score > 0 when metrics reachable, got %.3f", report.Score)
	}
	found := false
	for _, a := range report.Anomalies {
		if len(a) > 0 {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected at least one anomaly for zero traces")
	}
}

func TestTelemetryHealthCheck_HealthyStack(t *testing.T) {
	// Build traces with low latency and no errors.
	traces := make([]tempoTrace, 20)
	for i := range traces {
		traces[i] = tempoTrace{
			TraceID:         "abc123",
			RootServiceName: "omega",
			DurationMs:      float64(50 + i*5), // 50–145 ms
		}
	}
	tempoSrv := newTempoServer(t, tempoSearchResult{Traces: traces})
	defer tempoSrv.Close()
	metricsSrv := newMetricsServer(t, "# HELP omega_handler_requests_total Total requests\nomega_handler_requests_total 1234\n")
	defer metricsSrv.Close()

	chk := &TelemetryHealthCheck{
		TempoURL:   tempoSrv.URL,
		MetricsURL: metricsSrv.URL,
		HTTPClient: &http.Client{Timeout: 5 * time.Second},
	}

	report := chk.Run(context.Background())

	if report.TraceVolume != 20 {
		t.Errorf("expected TraceVolume=20, got %d", report.TraceVolume)
	}
	if report.Score < 0.8 {
		t.Errorf("expected Score >= 0.8 for healthy stack, got %.3f", report.Score)
	}
	if report.ErrorSpanRate != 0 {
		t.Errorf("expected ErrorSpanRate=0, got %.4f", report.ErrorSpanRate)
	}
	// p99 of 20 latencies (50..145ms in 5ms steps): 99th percentile → idx=19 → 145ms → 0.145s
	if report.P99Latency > 2.0 {
		t.Errorf("expected P99Latency < 2s, got %.3f", report.P99Latency)
	}
	if len(report.Anomalies) != 0 {
		t.Errorf("expected no anomalies, got: %v", report.Anomalies)
	}
}

func TestTelemetryHealthCheck_HighErrorRate(t *testing.T) {
	traces := []tempoTrace{
		{
			TraceID: "err1", DurationMs: 300,
			SpanSet: &struct {
				Spans []struct {
					StatusCode string `json:"statusCode"`
				} `json:"spans"`
			}{
				Spans: []struct {
					StatusCode string `json:"statusCode"`
				}{
					{StatusCode: "STATUS_CODE_ERROR"},
					{StatusCode: "STATUS_CODE_ERROR"},
					{StatusCode: "STATUS_CODE_OK"},
				},
			},
		},
	}
	tempoSrv := newTempoServer(t, tempoSearchResult{Traces: traces})
	defer tempoSrv.Close()
	metricsSrv := newMetricsServer(t, "")
	defer metricsSrv.Close()

	chk := &TelemetryHealthCheck{
		TempoURL:   tempoSrv.URL,
		MetricsURL: metricsSrv.URL,
		HTTPClient: &http.Client{Timeout: 5 * time.Second},
	}

	report := chk.Run(context.Background())

	if report.ErrorSpanRate < 0.5 {
		t.Errorf("expected ErrorSpanRate >= 0.5 (2/3 spans errored), got %.4f", report.ErrorSpanRate)
	}
	// Score should be penalised.
	if report.ComponentScores["tempo"] > 0.7 {
		t.Errorf("expected tempo score penalised, got %.3f", report.ComponentScores["tempo"])
	}
}

func TestTelemetryHealthCheck_TempoUnreachable(t *testing.T) {
	metricsSrv := newMetricsServer(t, "# metrics\n")
	defer metricsSrv.Close()

	chk := &TelemetryHealthCheck{
		TempoURL:   "http://127.0.0.1:19999", // nothing listening
		MetricsURL: metricsSrv.URL,
		HTTPClient: &http.Client{Timeout: 500 * time.Millisecond},
	}

	report := chk.Run(context.Background())

	if report.ComponentScores["tempo"] != 0 {
		t.Errorf("expected tempo score=0 when unreachable, got %.3f", report.ComponentScores["tempo"])
	}
	if len(report.Anomalies) == 0 {
		t.Error("expected anomaly when Tempo is unreachable")
	}
	// Metrics should still succeed.
	if report.ComponentScores["metrics"] != 1.0 {
		t.Errorf("expected metrics score=1.0, got %.3f", report.ComponentScores["metrics"])
	}
}

func TestTelemetryHealthCheck_BothUnreachable(t *testing.T) {
	chk := &TelemetryHealthCheck{
		TempoURL:   "http://127.0.0.1:19998",
		MetricsURL: "http://127.0.0.1:19997",
		HTTPClient: &http.Client{Timeout: 500 * time.Millisecond},
	}

	report := chk.Run(context.Background())

	if report.Score != 0 {
		t.Errorf("expected Score=0 when both unreachable, got %.3f", report.Score)
	}
	if len(report.RecommendedActions) == 0 {
		t.Error("expected recommended actions when stack is down")
	}
}

// ── analyseTraces ─────────────────────────────────────────────────────────────

func TestAnalyseTraces_Empty(t *testing.T) {
	v, e, p := analyseTraces(nil)
	if v != 0 || e != 0 || p != 0 {
		t.Errorf("empty input: got vol=%d err=%.4f p99=%.4f", v, e, p)
	}
	v, e, p = analyseTraces(&tempoSearchResult{})
	if v != 0 || e != 0 || p != 0 {
		t.Errorf("empty traces: got vol=%d err=%.4f p99=%.4f", v, e, p)
	}
}

func TestAnalyseTraces_Latency(t *testing.T) {
	traces := make([]tempoTrace, 100)
	for i := range traces {
		traces[i] = tempoTrace{DurationMs: float64(i + 1)} // 1–100 ms
	}
	_, _, p99 := analyseTraces(&tempoSearchResult{Traces: traces})
	// p99 of 1..100ms → 99th percentile index = 98 → 99ms → 0.099s
	expected := 0.099
	if p99 < expected-0.01 || p99 > expected+0.01 {
		t.Errorf("expected p99 ≈ %.3f, got %.3f", expected, p99)
	}
}

// ── percentile99 ──────────────────────────────────────────────────────────────

func TestPercentile99(t *testing.T) {
	vals := []float64{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
	p := percentile99(vals)
	// idx = int(9 * 0.99) = 8 → value 9
	if p != 9 {
		t.Errorf("expected 9, got %.1f", p)
	}
}

func TestPercentile99_Single(t *testing.T) {
	if p := percentile99([]float64{42}); p != 42 {
		t.Errorf("expected 42, got %.1f", p)
	}
}

// ── SystemHealthFromTelemetry ─────────────────────────────────────────────────

func TestSystemHealthFromTelemetry(t *testing.T) {
	tempoSrv := newTempoServer(t, tempoSearchResult{Traces: []tempoTrace{
		{TraceID: "t1", DurationMs: 80},
		{TraceID: "t2", DurationMs: 90},
	}})
	defer tempoSrv.Close()
	metricsSrv := newMetricsServer(t, "# metrics\n")
	defer metricsSrv.Close()

	report, err := SystemHealthFromTelemetry(context.Background(), tempoSrv.URL, metricsSrv.URL)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if report.TraceVolume != 2 {
		t.Errorf("expected TraceVolume=2, got %d", report.TraceVolume)
	}
	if report.EvaluatedAt.IsZero() {
		t.Error("EvaluatedAt should not be zero")
	}
}

// ── RunVictoriaEvalWithTelemetry ──────────────────────────────────────────────

func TestRunVictoriaEvalWithTelemetry_Disabled(t *testing.T) {
	result := RunVictoriaEvalWithTelemetry(
		context.Background(),
		&StubVictoriaProvider{},
		TelemetryOptions{Enabled: false},
	)
	if result.Telemetry != nil {
		t.Error("expected nil Telemetry when disabled")
	}
}

func TestRunVictoriaEvalWithTelemetry_Enabled(t *testing.T) {
	tempoSrv := newTempoServer(t, tempoSearchResult{Traces: []tempoTrace{
		{TraceID: "x", DurationMs: 50},
	}})
	defer tempoSrv.Close()
	metricsSrv := newMetricsServer(t, "# metrics\n")
	defer metricsSrv.Close()

	result := RunVictoriaEvalWithTelemetry(
		context.Background(),
		&StubVictoriaProvider{},
		TelemetryOptions{
			Enabled:    true,
			TempoURL:   tempoSrv.URL,
			MetricsURL: metricsSrv.URL,
		},
	)
	if result.Telemetry == nil {
		t.Fatal("expected non-nil Telemetry when enabled")
	}
	if result.Telemetry.EvaluatedAt.IsZero() {
		t.Error("EvaluatedAt should not be zero")
	}
}
