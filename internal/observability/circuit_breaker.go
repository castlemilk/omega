package observability

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"
)

// CircuitState is the state of a circuit breaker.
type CircuitState int

const (
	CircuitClosed   CircuitState = iota // Normal operation; requests flow through.
	CircuitOpen                         // Failure threshold exceeded; requests are rejected immediately.
	CircuitHalfOpen                     // Probe phase; a single request is allowed to test recovery.
)

func (s CircuitState) String() string {
	switch s {
	case CircuitClosed:
		return "CLOSED"
	case CircuitOpen:
		return "OPEN"
	case CircuitHalfOpen:
		return "HALF_OPEN"
	default:
		return "UNKNOWN"
	}
}

// ErrCircuitOpen is returned when a call is rejected because the circuit is open.
var ErrCircuitOpen = errors.New("circuit breaker open: node unavailable")

// CircuitBreakerConfig holds tunable parameters.
type CircuitBreakerConfig struct {
	// FailureThreshold is the number of consecutive failures that trip the circuit.
	FailureThreshold int

	// ResetTimeout is how long the circuit stays OPEN before moving to HALF_OPEN.
	ResetTimeout time.Duration

	// HalfOpenMaxCalls is the number of probe calls allowed in HALF_OPEN state.
	// After this many successes the circuit closes; after any failure it reopens.
	HalfOpenMaxCalls int
}

// DefaultCircuitBreakerConfig returns sensible defaults.
func DefaultCircuitBreakerConfig() CircuitBreakerConfig {
	return CircuitBreakerConfig{
		FailureThreshold: 5,
		ResetTimeout:     30 * time.Second,
		HalfOpenMaxCalls: 1,
	}
}

// CircuitBreaker implements the per-node circuit-breaker pattern.
// It is safe for concurrent use.
type CircuitBreaker struct {
	mu     sync.Mutex
	nodeID string
	cfg    CircuitBreakerConfig
	logger *slog.Logger

	state          CircuitState
	failures       int       // consecutive failures in CLOSED state
	lastFailure    time.Time // when the last failure occurred
	halfOpenCalls  int       // calls allowed in HALF_OPEN
	halfOpenPassed int       // successful probes in HALF_OPEN

	// optional metrics hook — set by Registry
	onStateChange func(nodeID string, from, to CircuitState)
}

// NewCircuitBreaker creates a circuit breaker for a single node.
func NewCircuitBreaker(nodeID string, cfg CircuitBreakerConfig, logger *slog.Logger) *CircuitBreaker {
	if logger == nil {
		logger = slog.Default()
	}
	return &CircuitBreaker{
		nodeID: nodeID,
		cfg:    cfg,
		logger: logger,
		state:  CircuitClosed,
	}
}

// State returns the current circuit state.
func (cb *CircuitBreaker) State() CircuitState {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	return cb.currentState()
}

// currentState updates and returns the state, transitioning OPEN → HALF_OPEN if
// the reset timeout has elapsed. Must be called with cb.mu held.
func (cb *CircuitBreaker) currentState() CircuitState {
	if cb.state == CircuitOpen && time.Since(cb.lastFailure) > cb.cfg.ResetTimeout {
		cb.transition(CircuitHalfOpen)
	}
	return cb.state
}

// Allow returns true if the call should be executed, false if the circuit is open.
// When in HALF_OPEN state it allows up to HalfOpenMaxCalls probes.
func (cb *CircuitBreaker) Allow() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.currentState() {
	case CircuitClosed:
		return true
	case CircuitOpen:
		return false
	case CircuitHalfOpen:
		if cb.halfOpenCalls < cb.cfg.HalfOpenMaxCalls {
			cb.halfOpenCalls++
			return true
		}
		return false
	default:
		return false
	}
}

// RecordSuccess records a successful call. Closes the circuit if in HALF_OPEN
// and enough probes have passed.
func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case CircuitClosed:
		cb.failures = 0
	case CircuitHalfOpen:
		cb.halfOpenPassed++
		if cb.halfOpenPassed >= cb.cfg.HalfOpenMaxCalls {
			cb.transition(CircuitClosed)
		}
	}
}

// RecordFailure records a failed call. Opens the circuit if the failure
// threshold is reached.
func (cb *CircuitBreaker) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.lastFailure = time.Now()

	switch cb.state {
	case CircuitClosed:
		cb.failures++
		if cb.failures >= cb.cfg.FailureThreshold {
			cb.transition(CircuitOpen)
		}
	case CircuitHalfOpen:
		// Any failure in half-open re-opens immediately.
		cb.transition(CircuitOpen)
	}
}

// Do executes fn if the circuit allows it, recording the outcome automatically.
// Returns ErrCircuitOpen if the circuit is open and fn was not called.
func (cb *CircuitBreaker) Do(ctx context.Context, fn func(ctx context.Context) error) error {
	if !cb.Allow() {
		return fmt.Errorf("%w: node=%s", ErrCircuitOpen, cb.nodeID)
	}
	err := fn(ctx)
	if err != nil {
		cb.RecordFailure()
	} else {
		cb.RecordSuccess()
	}
	return err
}

// transition moves the circuit to a new state, logging and invoking the metrics hook.
// Must be called with cb.mu held.
func (cb *CircuitBreaker) transition(to CircuitState) {
	from := cb.state
	if from == to {
		return
	}
	cb.state = to

	// Reset per-state counters.
	switch to {
	case CircuitClosed:
		cb.failures = 0
		cb.halfOpenCalls = 0
		cb.halfOpenPassed = 0
	case CircuitOpen:
		cb.halfOpenCalls = 0
		cb.halfOpenPassed = 0
	case CircuitHalfOpen:
		cb.halfOpenCalls = 0
		cb.halfOpenPassed = 0
	}

	cb.logger.Warn("circuit breaker state change",
		"node_id", cb.nodeID,
		"from", from.String(),
		"to", to.String(),
	)

	if cb.onStateChange != nil {
		cb.onStateChange(cb.nodeID, from, to)
	}
}

// ---------------------------------------------------------------------------
// CircuitBreakerRegistry — manages per-node breakers
// ---------------------------------------------------------------------------

// CircuitBreakerRegistry manages a set of per-node circuit breakers.
// The orchestrator calls Allow/RecordSuccess/RecordFailure before and after
// each node execution.
type CircuitBreakerRegistry struct {
	mu      sync.RWMutex
	breakers map[string]*CircuitBreaker
	cfg     CircuitBreakerConfig
	logger  *slog.Logger
	metrics *Metrics // may be nil
}

// NewCircuitBreakerRegistry creates a registry with a shared default config.
func NewCircuitBreakerRegistry(cfg CircuitBreakerConfig, logger *slog.Logger, m *Metrics) *CircuitBreakerRegistry {
	if logger == nil {
		logger = slog.Default()
	}
	return &CircuitBreakerRegistry{
		breakers: make(map[string]*CircuitBreaker),
		cfg:     cfg,
		logger:  logger,
		metrics: m,
	}
}

// Get returns the circuit breaker for nodeID, creating it lazily if needed.
func (r *CircuitBreakerRegistry) Get(nodeID string) *CircuitBreaker {
	r.mu.RLock()
	cb, ok := r.breakers[nodeID]
	r.mu.RUnlock()
	if ok {
		return cb
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	// Double-check after acquiring write lock.
	if cb, ok = r.breakers[nodeID]; ok {
		return cb
	}
	cb = NewCircuitBreaker(nodeID, r.cfg, r.logger)
	if r.metrics != nil {
		m := r.metrics
		cb.onStateChange = func(nid string, from, to CircuitState) {
			m.SetCircuitBreakerState(nid, float64(to))
		}
	}
	r.breakers[nodeID] = cb
	return cb
}

// Remove deletes the circuit breaker for a node (e.g. when the node is deregistered).
func (r *CircuitBreakerRegistry) Remove(nodeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.breakers, nodeID)
}

// Snapshot returns a map of nodeID → state for diagnostics.
func (r *CircuitBreakerRegistry) Snapshot() map[string]CircuitState {
	r.mu.RLock()
	defer r.mu.RUnlock()
	snap := make(map[string]CircuitState, len(r.breakers))
	for id, cb := range r.breakers {
		snap[id] = cb.State()
	}
	return snap
}
