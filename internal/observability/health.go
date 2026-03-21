// Package observability provides health checking, metrics collection, circuit breaking,
// event streaming, diagnostics, and degradation detection for the Omega framework.
// It is the system's immune system — monitoring itself, detecting degradation early,
// and surfacing issues proactively.
package observability

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"sync"
	"time"
)

// HealthState represents the health state of a subsystem.
type HealthState int

const (
	HealthStateUnknown   HealthState = iota
	HealthStateHealthy               // All checks pass.
	HealthStateDegraded              // Non-critical checks failing; service is functional but impaired.
	HealthStateUnhealthy             // Critical checks failing; service is not functioning correctly.
)

// String returns the canonical uppercase string representation.
func (h HealthState) String() string {
	switch h {
	case HealthStateHealthy:
		return "HEALTHY"
	case HealthStateDegraded:
		return "DEGRADED"
	case HealthStateUnhealthy:
		return "UNHEALTHY"
	default:
		return "UNKNOWN"
	}
}

// MarshalJSON implements json.Marshaler.
func (h HealthState) MarshalJSON() ([]byte, error) {
	return json.Marshal(h.String())
}

// HealthStatus is the result of a single health check.
type HealthStatus struct {
	State     HealthState    `json:"state"`
	Message   string         `json:"message,omitempty"`
	Details   map[string]any `json:"details,omitempty"`
	CheckedAt time.Time      `json:"checked_at"`
}

// HealthChecker is implemented by every subsystem that can report its own health.
type HealthChecker interface {
	// Name returns a stable identifier used in composite health reports.
	Name() string
	// Check runs the health probe. Implementations must respect ctx cancellation.
	Check(ctx context.Context) HealthStatus
}

// HealthCheckerFunc is a function adapter for HealthChecker.
type HealthCheckerFunc struct {
	name string
	fn   func(ctx context.Context) HealthStatus
}

// NewHealthCheckerFunc wraps a function as a HealthChecker.
func NewHealthCheckerFunc(name string, fn func(ctx context.Context) HealthStatus) HealthChecker {
	return &HealthCheckerFunc{name: name, fn: fn}
}

func (h *HealthCheckerFunc) Name() string { return h.name }
func (h *HealthCheckerFunc) Check(ctx context.Context) HealthStatus {
	return h.fn(ctx)
}

// CompositeHealth aggregates health checks from all registered subsystems.
// The composite state is the worst state among all children.
type CompositeHealth struct {
	mu       sync.RWMutex
	checkers []HealthChecker
	logger   *slog.Logger
}

// NewCompositeHealth creates an empty CompositeHealth.
func NewCompositeHealth(logger *slog.Logger) *CompositeHealth {
	if logger == nil {
		logger = slog.Default()
	}
	return &CompositeHealth{logger: logger}
}

// Register adds a health checker. Safe to call concurrently and after server start.
func (c *CompositeHealth) Register(checker HealthChecker) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.checkers = append(c.checkers, checker)
}

// CompositeHealthReport holds the results of all checks.
type CompositeHealthReport struct {
	State     HealthState               `json:"state"`
	CheckedAt time.Time                 `json:"checked_at"`
	Checks    map[string]*HealthStatus  `json:"checks"`
}

// Check runs all registered checks concurrently and aggregates the results.
// The composite state is the worst individual state.
func (c *CompositeHealth) Check(ctx context.Context) *CompositeHealthReport {
	c.mu.RLock()
	checkers := make([]HealthChecker, len(c.checkers))
	copy(checkers, c.checkers)
	c.mu.RUnlock()

	type result struct {
		name   string
		status HealthStatus
	}

	results := make(chan result, len(checkers))
	for _, ch := range checkers {
		ch := ch
		go func() {
			s := ch.Check(ctx)
			results <- result{name: ch.Name(), status: s}
		}()
	}

	report := &CompositeHealthReport{
		State:     HealthStateHealthy,
		CheckedAt: time.Now(),
		Checks:    make(map[string]*HealthStatus, len(checkers)),
	}

	if len(checkers) == 0 {
		report.State = HealthStateUnknown
		return report
	}

	for range checkers {
		r := <-results
		s := r.status
		report.Checks[r.name] = &s
		if s.State > report.State {
			report.State = s.State
		}
	}

	c.logger.Debug("composite health checked",
		"state", report.State.String(),
		"num_checks", len(checkers),
	)
	return report
}

// HealthHandler serves the composite health report.
type HealthHandler struct {
	composite *CompositeHealth
}

// NewHealthHandler creates an HTTP handler backed by the given composite health checker.
func NewHealthHandler(c *CompositeHealth) *HealthHandler {
	return &HealthHandler{composite: c}
}

// RegisterRoutes registers /healthz (liveness) and /readyz (readiness) on mux.
func (h *HealthHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/healthz", h.handleLiveness)
	mux.HandleFunc("/readyz", h.handleReadiness)
}

// handleLiveness returns 200 if the process is alive (not UNHEALTHY).
// Kubernetes liveness probes restart the container on non-200.
func (h *HealthHandler) handleLiveness(w http.ResponseWriter, r *http.Request) {
	report := h.composite.Check(r.Context())

	w.Header().Set("Content-Type", "application/json")
	if report.State == HealthStateUnhealthy {
		w.WriteHeader(http.StatusServiceUnavailable)
	} else {
		w.WriteHeader(http.StatusOK)
	}
	_ = json.NewEncoder(w).Encode(report)
}

// handleReadiness returns 200 only when state is HEALTHY or DEGRADED (serving traffic).
// Kubernetes readiness probes remove the pod from service on non-200.
func (h *HealthHandler) handleReadiness(w http.ResponseWriter, r *http.Request) {
	report := h.composite.Check(r.Context())

	w.Header().Set("Content-Type", "application/json")
	switch report.State {
	case HealthStateHealthy, HealthStateDegraded:
		w.WriteHeader(http.StatusOK)
	default:
		w.WriteHeader(http.StatusServiceUnavailable)
	}
	_ = json.NewEncoder(w).Encode(report)
}

// ---------------------------------------------------------------------------
// Built-in checkers
// ---------------------------------------------------------------------------

// DBHealthChecker checks that a database ping succeeds within a timeout.
type DBHealthChecker struct {
	name    string
	pingFn  func(ctx context.Context) error
	timeout time.Duration
}

// NewDBHealthChecker creates a checker that calls pingFn and expects it to
// return within timeout. pingFn should call db.PingContext or equivalent.
func NewDBHealthChecker(name string, pingFn func(ctx context.Context) error, timeout time.Duration) HealthChecker {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	return &DBHealthChecker{name: name, pingFn: pingFn, timeout: timeout}
}

func (d *DBHealthChecker) Name() string { return d.name }

func (d *DBHealthChecker) Check(ctx context.Context) HealthStatus {
	ctx, cancel := context.WithTimeout(ctx, d.timeout)
	defer cancel()

	start := time.Now()
	err := d.pingFn(ctx)
	elapsed := time.Since(start)

	if err != nil {
		return HealthStatus{
			State:     HealthStateUnhealthy,
			Message:   err.Error(),
			Details:   map[string]any{"latency_ms": elapsed.Milliseconds()},
			CheckedAt: time.Now(),
		}
	}
	return HealthStatus{
		State:     HealthStateHealthy,
		Details:   map[string]any{"latency_ms": elapsed.Milliseconds()},
		CheckedAt: time.Now(),
	}
}
