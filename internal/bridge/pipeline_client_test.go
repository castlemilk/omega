package bridge_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/bridge"
)

// ── Mock server helpers ────────────────────────────────────────────────────────

type mockHandler struct {
	responses map[string]mockResponse
	received  []string
	headers   []http.Header
}

type mockResponse struct {
	body       map[string]any
	statusCode int
}

func (m *mockHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	m.received = append(m.received, r.URL.Path)
	m.headers = append(m.headers, r.Header.Clone())

	method := r.URL.Path[len("/omega.v1.PipelineService/"):]
	resp, ok := m.responses[method]
	if !ok {
		http.Error(w, "unknown method", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if resp.statusCode != 0 {
		w.WriteHeader(resp.statusCode)
	}
	_ = json.NewEncoder(w).Encode(resp.body)
}

func newMockServer(t *testing.T, responses map[string]mockResponse) (*httptest.Server, *mockHandler) {
	t.Helper()
	h := &mockHandler{responses: responses}
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv, h
}

// ── Tests ──────────────────────────────────────────────────────────────────────

func TestPing_ReturnsTrue(t *testing.T) {
	srv, _ := newMockServer(t, map[string]mockResponse{
		"Ping": {body: map[string]any{"ok": true, "version": "0.1.0"}, statusCode: 200},
	})
	client := bridge.NewPipelineClient(srv.URL)
	ok, err := client.Ping(context.Background())
	if err != nil {
		t.Fatalf("Ping returned error: %v", err)
	}
	if !ok {
		t.Error("expected Ping to return ok=true")
	}
}

func TestPing_ServerError(t *testing.T) {
	srv, _ := newMockServer(t, map[string]mockResponse{
		"Ping": {body: map[string]any{"code": "internal", "message": "oops"}, statusCode: 500},
	})
	client := bridge.NewPipelineClient(srv.URL)
	_, err := client.Ping(context.Background())
	if err == nil {
		t.Fatal("expected Ping to return an error on 500 response")
	}
}

func TestExecuteStep_Success(t *testing.T) {
	srv, mock := newMockServer(t, map[string]mockResponse{
		"ExecuteStep": {
			body: map[string]any{
				"success":  true,
				"nodeId":   "node-123",
				"nodeName": "DataIngestion",
				"metrics":  map[string]any{"records": 100.0},
				"durationMs": 42.5,
			},
			statusCode: 200,
		},
	})

	client := bridge.NewPipelineClient(srv.URL)
	resp, err := client.ExecuteStep(context.Background(), &omegav1.ExecuteStepRequest{
		StepId:   "step_1",
		StepName: "DataIngestion",
		NodeType: "DATA_INGESTION",
		Cycle:    5,
	})
	if err != nil {
		t.Fatalf("ExecuteStep returned error: %v", err)
	}
	if !resp.Success {
		t.Errorf("expected success=true, got false")
	}
	if resp.NodeId != "node-123" {
		t.Errorf("expected node_id=node-123, got %q", resp.NodeId)
	}
	if resp.DurationMs != 42.5 {
		t.Errorf("expected duration_ms=42.5, got %f", resp.DurationMs)
	}
	if len(mock.received) != 1 || mock.received[0] != "/omega.v1.PipelineService/ExecuteStep" {
		t.Errorf("unexpected request paths: %v", mock.received)
	}
}

func TestExecuteStep_NoTraceparentWithoutActiveSpan(t *testing.T) {
	srv, mock := newMockServer(t, map[string]mockResponse{
		"ExecuteStep": {body: map[string]any{"success": true}, statusCode: 200},
	})

	client := bridge.NewPipelineClient(srv.URL)
	// context.Background() has no OTel span — traceparent must NOT be injected.
	_, err := client.ExecuteStep(context.Background(), &omegav1.ExecuteStepRequest{
		NodeType: "DATA_INGESTION",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(mock.headers) == 0 {
		t.Fatal("no request headers captured")
	}
	if tp := mock.headers[0].Get("traceparent"); tp != "" {
		t.Errorf("expected no traceparent header without active span, got %q", tp)
	}
}

func TestAddr_DefaultsToLocalhost9090(t *testing.T) {
	t.Setenv("OMEGA_PYTHON_PIPELINE_ADDR", "")
	c := bridge.NewPipelineClient("")
	if c.Addr() != "http://localhost:9090" {
		t.Errorf("expected default addr, got %q", c.Addr())
	}
}

func TestAddr_ExplicitArgTakesPrecedence(t *testing.T) {
	t.Setenv("OMEGA_PYTHON_PIPELINE_ADDR", "http://env-addr:9999")
	c := bridge.NewPipelineClient("http://explicit:8888")
	if c.Addr() != "http://explicit:8888" {
		t.Errorf("expected explicit addr, got %q", c.Addr())
	}
}

func TestAddr_EnvFallback(t *testing.T) {
	_ = os.Setenv("OMEGA_PYTHON_PIPELINE_ADDR", "http://env-addr:9999")
	t.Cleanup(func() { os.Unsetenv("OMEGA_PYTHON_PIPELINE_ADDR") }) //nolint:errcheck
	c := bridge.NewPipelineClient("")
	if c.Addr() != "http://env-addr:9999" {
		t.Errorf("expected env addr, got %q", c.Addr())
	}
}
