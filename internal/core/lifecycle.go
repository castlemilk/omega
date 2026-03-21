// Package core — lifecycle.go
//
// LifecycleManager implements a state machine for node lifecycle management.
//
// Valid state transitions:
//
//	Initializing → Active | Terminated
//	Active       → Draining | Suspended | Terminated
//	Draining     → Suspended | Terminated
//	Suspended    → Active | Terminated
//	Terminated   → (terminal — no further transitions)
package core

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/framework"
)

// ---------------------------------------------------------------------------
// NodeLifecycleState — state machine states
// ---------------------------------------------------------------------------

// NodeLifecycleState represents a node's lifecycle stage.
type NodeLifecycleState int

const (
	// StateInitializing is the entry state: node registered but not yet active.
	StateInitializing NodeLifecycleState = iota

	// StateActive means the node is healthy and participating in cycles.
	StateActive

	// StateDraining means the node is finishing its current cycle and will not
	// accept new work. Transitions to Suspended or Terminated.
	StateDraining

	// StateSuspended means the node is paused but retains its config.
	// It can be resumed (→ Active) or removed (→ Terminated).
	StateSuspended

	// StateTerminated is the terminal state. No transitions are possible.
	StateTerminated
)

// String returns a human-readable name for a lifecycle state.
func (s NodeLifecycleState) String() string {
	switch s {
	case StateInitializing:
		return "Initializing"
	case StateActive:
		return "Active"
	case StateDraining:
		return "Draining"
	case StateSuspended:
		return "Suspended"
	case StateTerminated:
		return "Terminated"
	default:
		return fmt.Sprintf("NodeLifecycleState(%d)", int(s))
	}
}

// ValidTransitions maps each state to the set of states it may transition to.
// Attempting any other transition returns an error.
var ValidTransitions = map[NodeLifecycleState][]NodeLifecycleState{
	StateInitializing: {StateActive, StateTerminated},
	StateActive:       {StateDraining, StateSuspended, StateTerminated},
	StateDraining:     {StateSuspended, StateTerminated},
	StateSuspended:    {StateActive, StateTerminated},
	StateTerminated:   {}, // terminal
}

// ---------------------------------------------------------------------------
// NodeLifecycleEvent — published on every successful state transition
// ---------------------------------------------------------------------------

// TopicNodeLifecycle is the framework.EventBus topic for lifecycle transitions.
const TopicNodeLifecycle = "lifecycle.node.transition"

// NodeLifecycleEvent is the payload published when a node transitions states.
type NodeLifecycleEvent struct {
	NodeID     string
	From       NodeLifecycleState
	To         NodeLifecycleState
	Reason     string
	OccurredAt time.Time
}

// ---------------------------------------------------------------------------
// LifecycleManager
// ---------------------------------------------------------------------------

// LifecycleManager tracks per-node lifecycle states and enforces valid
// transitions. All methods are safe for concurrent use.
type LifecycleManager struct {
	mu     sync.Mutex
	states map[string]NodeLifecycleState
	bus    *framework.EventBus
}

// NewLifecycleManager creates a LifecycleManager. bus may be nil.
func NewLifecycleManager(bus *framework.EventBus) *LifecycleManager {
	return &LifecycleManager{
		states: make(map[string]NodeLifecycleState),
		bus:    bus,
	}
}

// Initialize registers a node at StateInitializing.
// Returns an error if the node is already tracked.
func (m *LifecycleManager) Initialize(nodeID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.states[nodeID]; exists {
		return fmt.Errorf("lifecycle: node %q already initialised", nodeID)
	}
	m.states[nodeID] = StateInitializing
	m.publish(nodeID, NodeLifecycleState(-1), StateInitializing, "registered")
	return nil
}

// Transition moves nodeID from its current state to `to`.
// Returns an error if the transition is not in ValidTransitions.
func (m *LifecycleManager) Transition(nodeID string, to NodeLifecycleState, reason string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	from, exists := m.states[nodeID]
	if !exists {
		return fmt.Errorf("lifecycle: node %q not found", nodeID)
	}

	if !isValidTransition(from, to) {
		return fmt.Errorf("lifecycle: node %q invalid transition %s → %s",
			nodeID, from, to)
	}

	m.states[nodeID] = to
	m.publish(nodeID, from, to, reason)
	return nil
}

// State returns the current lifecycle state of nodeID.
// Returns StateInitializing and false if the node is not tracked.
func (m *LifecycleManager) State(nodeID string) (NodeLifecycleState, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.states[nodeID]
	return s, ok
}

// Snapshot returns a copy of the current state map.
func (m *LifecycleManager) Snapshot() map[string]NodeLifecycleState {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make(map[string]NodeLifecycleState, len(m.states))
	for k, v := range m.states {
		out[k] = v
	}
	return out
}

// GracefulDrain stops a node from receiving new work, waits for it to finish
// its current cycle (bounded by ctx), then transitions it to StateSuspended.
//
// The drain sequence:
//  1. Transition Active → Draining  (so the orchestrator skips it next cycle)
//  2. Deregister from orch          (removes it from the node registry)
//  3. Transition Draining → Suspended
func (m *LifecycleManager) GracefulDrain(ctx context.Context, nodeID string, orch *Orchestrator) error {
	// Step 1: mark as Draining so it is skipped in any cycle starting after this.
	if err := m.Transition(nodeID, StateDraining, "graceful drain requested"); err != nil {
		return err
	}

	// Step 2: deregister from the orchestrator — this stops execution immediately.
	// We do this in a goroutine so we can respect ctx cancellation.
	done := make(chan error, 1)
	go func() {
		orch.Deregister(nodeID)
		done <- nil
	}()

	select {
	case err := <-done:
		if err != nil {
			return fmt.Errorf("lifecycle: drain deregister failed for %q: %w", nodeID, err)
		}
	case <-ctx.Done():
		// Context expired; still attempt to deregister but report the timeout.
		orch.Deregister(nodeID)
		return fmt.Errorf("lifecycle: drain timed out for %q: %w", nodeID, ctx.Err())
	}

	// Step 3: transition to Suspended.
	return m.Transition(nodeID, StateSuspended, "drain complete")
}

// ---------------------------------------------------------------------------
// internal helpers
// ---------------------------------------------------------------------------

func isValidTransition(from, to NodeLifecycleState) bool {
	allowed, ok := ValidTransitions[from]
	if !ok {
		return false
	}
	for _, s := range allowed {
		if s == to {
			return true
		}
	}
	return false
}

func (m *LifecycleManager) publish(nodeID string, from, to NodeLifecycleState, reason string) {
	if m.bus == nil {
		return
	}
	m.bus.Publish(framework.Event{
		Topic: TopicNodeLifecycle,
		Payload: NodeLifecycleEvent{
			NodeID:     nodeID,
			From:       from,
			To:         to,
			Reason:     reason,
			OccurredAt: time.Now(),
		},
	})
}
