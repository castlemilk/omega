package observability

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// collectRuntime
// ---------------------------------------------------------------------------

func TestCollectRuntime_NonZero(t *testing.T) {
	d := collectRuntime()
	if d.NumGoroutine <= 0 {
		t.Fatalf("NumGoroutine should be positive, got %d", d.NumGoroutine)
	}
	if d.NumCPU <= 0 {
		t.Fatalf("NumCPU should be positive, got %d", d.NumCPU)
	}
	if d.GOMAXPROCS <= 0 {
		t.Fatalf("GOMAXPROCS should be positive, got %d", d.GOMAXPROCS)
	}
	if d.HeapAllocBytes == 0 {
		t.Fatal("HeapAllocBytes should be non-zero")
	}
}

// ---------------------------------------------------------------------------
// collectBuildInfo
// ---------------------------------------------------------------------------

func TestCollectBuildInfo_GoVersion(t *testing.T) {
	bi := collectBuildInfo()
	if bi.GoVersion == "" {
		t.Fatal("GoVersion should not be empty")
	}
}

// ---------------------------------------------------------------------------
// DiagnosticsCollector
// ---------------------------------------------------------------------------

func TestDiagnosticsCollector_NoProviders(t *testing.T) {
	c := NewDiagnosticsCollector(nil, nil, nil, nil)
	r := c.Collect(context.Background())
	if r == nil {
		t.Fatal("Collect returned nil")
	}
	if r.CollectedAt.IsZero() {
		t.Fatal("CollectedAt should not be zero")
	}
	if r.Runtime.NumGoroutine <= 0 {
		t.Fatal("Runtime.NumGoroutine should be positive")
	}
	if r.Nodes != nil {
		t.Fatal("Nodes should be nil when no node provider")
	}
	if r.Framework != nil {
		t.Fatal("Framework should be nil when no fw provider")
	}
}

func TestDiagnosticsCollector_WithNodeProvider(t *testing.T) {
	provider := &staticNodeProvider{nodes: []NodeDiagnostics{
		{NodeID: "n1", AutonomyLevel: 0.8},
		{NodeID: "n2", AutonomyLevel: 0.6},
	}}
	c := NewDiagnosticsCollector(provider, nil, nil, nil)
	r := c.Collect(context.Background())
	if len(r.Nodes) != 2 {
		t.Fatalf("want 2 nodes, got %d", len(r.Nodes))
	}
}

func TestDiagnosticsCollector_WithFrameworkProvider(t *testing.T) {
	provider := &staticFrameworkProvider{diag: FrameworkDiagnostics{
		DBStateHealthy:  true,
		DBMemoryHealthy: true,
		ActiveNodes:     5,
	}}
	c := NewDiagnosticsCollector(nil, provider, nil, nil)
	r := c.Collect(context.Background())
	if r.Framework == nil {
		t.Fatal("Framework should not be nil when fw provider set")
	}
	if !r.Framework.DBStateHealthy {
		t.Fatal("DBStateHealthy should be true")
	}
}

func TestDiagnosticsCollector_WithCircuitBreakers(t *testing.T) {
	reg := NewCircuitBreakerRegistry(testCfg(1, time.Hour), nil, nil)
	reg.Get("alpha").RecordFailure() // OPEN (reset timeout=1h so stays OPEN)
	reg.Get("beta")                  // CLOSED

	c := NewDiagnosticsCollector(nil, nil, reg, nil)
	r := c.Collect(context.Background())

	if r.CircuitBreakers["alpha"] != "OPEN" {
		t.Fatalf("alpha should be OPEN, got %q", r.CircuitBreakers["alpha"])
	}
	if r.CircuitBreakers["beta"] != "CLOSED" {
		t.Fatalf("beta should be CLOSED, got %q", r.CircuitBreakers["beta"])
	}
}

// ---------------------------------------------------------------------------
// DiagnosticsHandler HTTP
// ---------------------------------------------------------------------------

func TestDiagnosticsHandler_ReturnsJSON(t *testing.T) {
	c := NewDiagnosticsCollector(nil, nil, nil, nil)
	h := NewDiagnosticsHandler(c)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/debug/diagnostics", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if ct := w.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("want application/json, got %q", ct)
	}

	var report DiagnosticsReport
	if err := json.Unmarshal(w.Body.Bytes(), &report); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if report.Runtime.NumGoroutine <= 0 {
		t.Fatal("decoded runtime should have positive goroutine count")
	}
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

type staticNodeProvider struct {
	nodes []NodeDiagnostics
}

func (p *staticNodeProvider) NodeDiagnostics(_ context.Context) []NodeDiagnostics {
	return p.nodes
}

type staticFrameworkProvider struct {
	diag FrameworkDiagnostics
}

func (p *staticFrameworkProvider) FrameworkDiagnostics(_ context.Context) FrameworkDiagnostics {
	return p.diag
}
