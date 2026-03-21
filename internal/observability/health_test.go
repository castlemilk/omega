package observability

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// HealthState
// ---------------------------------------------------------------------------

func TestHealthStateString(t *testing.T) {
	tests := []struct {
		state HealthState
		want  string
	}{
		{HealthStateUnknown, "UNKNOWN"},
		{HealthStateHealthy, "HEALTHY"},
		{HealthStateDegraded, "DEGRADED"},
		{HealthStateUnhealthy, "UNHEALTHY"},
		{HealthState(99), "UNKNOWN"},
	}
	for _, tt := range tests {
		if got := tt.state.String(); got != tt.want {
			t.Errorf("HealthState(%d).String() = %q, want %q", tt.state, got, tt.want)
		}
	}
}

func TestHealthStateMarshalJSON(t *testing.T) {
	b, err := json.Marshal(HealthStateHealthy)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != `"HEALTHY"` {
		t.Errorf("unexpected JSON: %s", b)
	}
}

// ---------------------------------------------------------------------------
// HealthCheckerFunc
// ---------------------------------------------------------------------------

func TestHealthCheckerFunc(t *testing.T) {
	called := false
	hc := NewHealthCheckerFunc("test-db", func(ctx context.Context) HealthStatus {
		called = true
		return HealthStatus{State: HealthStateHealthy, CheckedAt: time.Now()}
	})
	if hc.Name() != "test-db" {
		t.Fatalf("Name() = %q, want test-db", hc.Name())
	}
	s := hc.Check(context.Background())
	if !called {
		t.Fatal("check function not called")
	}
	if s.State != HealthStateHealthy {
		t.Fatalf("state = %v, want HEALTHY", s.State)
	}
}

// ---------------------------------------------------------------------------
// CompositeHealth
// ---------------------------------------------------------------------------

func makeChecker(name string, state HealthState) HealthChecker {
	return NewHealthCheckerFunc(name, func(_ context.Context) HealthStatus {
		return HealthStatus{State: state, CheckedAt: time.Now()}
	})
}

func TestCompositeHealth_NoCheckers(t *testing.T) {
	c := NewCompositeHealth(nil)
	r := c.Check(context.Background())
	if r.State != HealthStateUnknown {
		t.Fatalf("want UNKNOWN for empty composite, got %v", r.State)
	}
}

func TestCompositeHealth_AllHealthy(t *testing.T) {
	c := NewCompositeHealth(nil)
	c.Register(makeChecker("a", HealthStateHealthy))
	c.Register(makeChecker("b", HealthStateHealthy))
	r := c.Check(context.Background())
	if r.State != HealthStateHealthy {
		t.Fatalf("want HEALTHY, got %v", r.State)
	}
	if len(r.Checks) != 2 {
		t.Fatalf("want 2 checks, got %d", len(r.Checks))
	}
}

func TestCompositeHealth_WorstStateWins(t *testing.T) {
	tests := []struct {
		name   string
		states []HealthState
		want   HealthState
	}{
		{"healthy+degraded=degraded", []HealthState{HealthStateHealthy, HealthStateDegraded}, HealthStateDegraded},
		{"healthy+unhealthy=unhealthy", []HealthState{HealthStateHealthy, HealthStateUnhealthy}, HealthStateUnhealthy},
		{"degraded+unhealthy=unhealthy", []HealthState{HealthStateDegraded, HealthStateUnhealthy}, HealthStateUnhealthy},
		{"all healthy=healthy", []HealthState{HealthStateHealthy, HealthStateHealthy}, HealthStateHealthy},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := NewCompositeHealth(nil)
			for i, s := range tt.states {
				c.Register(makeChecker(string(rune('a'+i)), s))
			}
			r := c.Check(context.Background())
			if r.State != tt.want {
				t.Errorf("want %v, got %v", tt.want, r.State)
			}
		})
	}
}

func TestCompositeHealth_ConcurrentRegister(t *testing.T) {
	names := []string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"}
	c := NewCompositeHealth(nil)
	done := make(chan struct{})
	for _, name := range names {
		go func(n string) {
			c.Register(makeChecker(n, HealthStateHealthy))
			done <- struct{}{}
		}(name)
	}
	for range names {
		<-done
	}
	r := c.Check(context.Background())
	if len(r.Checks) != len(names) {
		t.Fatalf("want %d checks, got %d", len(names), len(r.Checks))
	}
}

// ---------------------------------------------------------------------------
// HTTP endpoints
// ---------------------------------------------------------------------------

func TestHealthHandler_Liveness_Healthy(t *testing.T) {
	c := NewCompositeHealth(nil)
	c.Register(makeChecker("db", HealthStateHealthy))
	h := NewHealthHandler(c)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
}

func TestHealthHandler_Liveness_Unhealthy(t *testing.T) {
	c := NewCompositeHealth(nil)
	c.Register(makeChecker("db", HealthStateUnhealthy))
	h := NewHealthHandler(c)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("want 503, got %d", w.Code)
	}
}

func TestHealthHandler_Readiness_Degraded(t *testing.T) {
	c := NewCompositeHealth(nil)
	c.Register(makeChecker("node", HealthStateDegraded))
	h := NewHealthHandler(c)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	// Degraded = still ready to serve traffic.
	if w.Code != http.StatusOK {
		t.Fatalf("want 200 for DEGRADED readiness, got %d", w.Code)
	}
}

func TestHealthHandler_Readiness_Unknown(t *testing.T) {
	c := NewCompositeHealth(nil) // no checkers → UNKNOWN
	h := NewHealthHandler(c)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("want 503 for UNKNOWN readiness, got %d", w.Code)
	}
}

// ---------------------------------------------------------------------------
// DBHealthChecker
// ---------------------------------------------------------------------------

func TestDBHealthChecker_Success(t *testing.T) {
	hc := NewDBHealthChecker("state-db", func(_ context.Context) error {
		return nil
	}, time.Second)
	s := hc.Check(context.Background())
	if s.State != HealthStateHealthy {
		t.Fatalf("want HEALTHY, got %v", s.State)
	}
}

func TestDBHealthChecker_Failure(t *testing.T) {
	hc := NewDBHealthChecker("state-db", func(_ context.Context) error {
		return errors.New("connection refused")
	}, time.Second)
	s := hc.Check(context.Background())
	if s.State != HealthStateUnhealthy {
		t.Fatalf("want UNHEALTHY, got %v", s.State)
	}
	if s.Message == "" {
		t.Fatal("want non-empty Message on failure")
	}
}

func TestDBHealthChecker_Timeout(t *testing.T) {
	hc := NewDBHealthChecker("state-db", func(ctx context.Context) error {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(5 * time.Second):
			return nil
		}
	}, 50*time.Millisecond)

	start := time.Now()
	s := hc.Check(context.Background())
	elapsed := time.Since(start)

	if s.State != HealthStateUnhealthy {
		t.Fatalf("want UNHEALTHY on timeout, got %v", s.State)
	}
	if elapsed > 500*time.Millisecond {
		t.Fatalf("check took too long: %v (timeout=50ms)", elapsed)
	}
}
