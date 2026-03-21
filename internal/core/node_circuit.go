package core

import (
	"log/slog"
	"sync"

	"github.com/benebsworth/omega/internal/observability"
)

// NodeCircuitManager wraps observability.CircuitBreakerRegistry with
// orchestrator-aware behaviour: it emits events onto an EventBus whenever a
// breaker transitions state, allowing the orchestrator to react and log.
type NodeCircuitManager struct {
	mu         sync.Mutex
	registry   *observability.CircuitBreakerRegistry
	bus        *observability.EventBus
	lastStates map[string]observability.CircuitState
	logger     *slog.Logger
}

// NewNodeCircuitManager creates a NodeCircuitManager.
func NewNodeCircuitManager(
	cfg observability.CircuitBreakerConfig,
	metrics *observability.Metrics,
	bus *observability.EventBus,
	logger *slog.Logger,
) *NodeCircuitManager {
	if logger == nil {
		logger = slog.Default()
	}
	return &NodeCircuitManager{
		registry:   observability.NewCircuitBreakerRegistry(cfg, logger, metrics),
		bus:        bus,
		lastStates: make(map[string]observability.CircuitState),
		logger:     logger,
	}
}

// AllowExecution returns true if the node's circuit is not open.
// The OPEN → HALF_OPEN timeout transition happens automatically inside
// the CircuitBreaker.Allow() call.
func (m *NodeCircuitManager) AllowExecution(nodeID string) bool {
	cb := m.registry.Get(nodeID)
	// Snapshot state before Allow(), which may trigger OPEN→HALF_OPEN.
	m.mu.Lock()
	prev, seen := m.lastStates[nodeID]
	m.mu.Unlock()

	allowed := cb.Allow()

	cur := cb.State()
	if seen && prev != cur {
		m.publishStateChange(nodeID, prev, cur, "timeout elapsed: moving to HALF_OPEN")
	}
	if !seen {
		m.mu.Lock()
		m.lastStates[nodeID] = cur
		m.mu.Unlock()
	}

	return allowed
}

// RecordSuccess records a successful node execution and publishes a
// CircuitBreakerTripped event if the circuit just closed (HALF_OPEN → CLOSED).
func (m *NodeCircuitManager) RecordSuccess(nodeID string) {
	cb := m.registry.Get(nodeID)
	prev := cb.State()
	cb.RecordSuccess()
	cur := cb.State()
	if prev != cur {
		m.publishStateChange(nodeID, prev, cur, "node execution succeeded")
	}
	m.setLastState(nodeID, cur)
}

// RecordFailure records a failed node execution and publishes a
// CircuitBreakerTripped event if the circuit just opened.
func (m *NodeCircuitManager) RecordFailure(nodeID string) {
	cb := m.registry.Get(nodeID)
	prev := cb.State()
	cb.RecordFailure()
	cur := cb.State()
	if prev != cur {
		m.publishStateChange(nodeID, prev, cur, "node execution failed")
	}
	m.setLastState(nodeID, cur)
}

// State returns the current circuit state for nodeID.
func (m *NodeCircuitManager) State(nodeID string) observability.CircuitState {
	return m.registry.Get(nodeID).State()
}

// Snapshot returns a map of nodeID → circuit state for diagnostics.
func (m *NodeCircuitManager) Snapshot() map[string]observability.CircuitState {
	return m.registry.Snapshot()
}

// Remove deletes the circuit breaker for a deregistered node.
func (m *NodeCircuitManager) Remove(nodeID string) {
	m.registry.Remove(nodeID)
	m.mu.Lock()
	delete(m.lastStates, nodeID)
	m.mu.Unlock()
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func (m *NodeCircuitManager) setLastState(nodeID string, s observability.CircuitState) {
	m.mu.Lock()
	m.lastStates[nodeID] = s
	m.mu.Unlock()
}

func (m *NodeCircuitManager) publishStateChange(
	nodeID string,
	from, to observability.CircuitState,
	reason string,
) {
	m.setLastState(nodeID, to)

	m.logger.Warn("circuit breaker state changed",
		"node_id", nodeID,
		"from", from.String(),
		"to", to.String(),
		"reason", reason,
	)

	if m.bus == nil {
		return
	}

	// For an OPEN transition, emit the dedicated CircuitBreakerTripped event.
	if to == observability.CircuitOpen {
		m.bus.PublishCircuitBreakerTripped(observability.CircuitBreakerTrippedPayload{
			NodeID: nodeID,
		})
		return
	}

	// For all other transitions (HALF_OPEN, CLOSED) emit a generic event so
	// subscribers can track full state machine progression.
	m.bus.Publish(observability.Event{
		Type: observability.EventCircuitBreakerTripped,
		Payload: observability.CircuitBreakerTrippedPayload{
			NodeID: nodeID,
		},
	})
}
