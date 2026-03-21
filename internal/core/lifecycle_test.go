package core

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/framework"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func newLifecycle(t *testing.T) (*LifecycleManager, *framework.EventBus) {
	t.Helper()
	bus := framework.NewEventBus()
	lm := NewLifecycleManager(bus)
	return lm, bus
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

func TestLifecycleManager_Initialize_Success(t *testing.T) {
	lm, _ := newLifecycle(t)

	if err := lm.Initialize("node-1"); err != nil {
		t.Fatalf("Initialize: %v", err)
	}

	state, ok := lm.State("node-1")
	if !ok {
		t.Fatal("node-1 should be tracked after Initialize")
	}
	if state != StateInitializing {
		t.Errorf("state: got %s want Initializing", state)
	}
}

func TestLifecycleManager_Initialize_Duplicate(t *testing.T) {
	lm, _ := newLifecycle(t)

	if err := lm.Initialize("node-1"); err != nil {
		t.Fatalf("first Initialize: %v", err)
	}
	if err := lm.Initialize("node-1"); err == nil {
		t.Fatal("expected error for duplicate Initialize")
	}
}

// ---------------------------------------------------------------------------
// Valid transitions
// ---------------------------------------------------------------------------

func TestLifecycleManager_ValidTransitions(t *testing.T) {
	tests := []struct {
		name  string
		path  []NodeLifecycleState
		valid bool
	}{
		{"Initializing→Active", []NodeLifecycleState{StateInitializing, StateActive}, true},
		{"Initializing→Terminated", []NodeLifecycleState{StateInitializing, StateTerminated}, true},
		{"Active→Draining", []NodeLifecycleState{StateInitializing, StateActive, StateDraining}, true},
		{"Active→Suspended", []NodeLifecycleState{StateInitializing, StateActive, StateSuspended}, true},
		{"Active→Terminated", []NodeLifecycleState{StateInitializing, StateActive, StateTerminated}, true},
		{"Draining→Suspended", []NodeLifecycleState{StateInitializing, StateActive, StateDraining, StateSuspended}, true},
		{"Draining→Terminated", []NodeLifecycleState{StateInitializing, StateActive, StateDraining, StateTerminated}, true},
		{"Suspended→Active", []NodeLifecycleState{StateInitializing, StateActive, StateSuspended, StateActive}, true},
		{"Suspended→Terminated", []NodeLifecycleState{StateInitializing, StateActive, StateSuspended, StateTerminated}, true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			lm, _ := newLifecycle(t)
			nodeID := "test-node"

			if err := lm.Initialize(nodeID); err != nil {
				t.Fatalf("Initialize: %v", err)
			}

			// Walk through the state path (skip the first state which is set by Initialize).
			for _, to := range tc.path[1:] {
				if err := lm.Transition(nodeID, to, "test"); err != nil {
					if tc.valid {
						t.Fatalf("unexpected transition error: %v", err)
					}
					return
				}
			}

			if !tc.valid {
				t.Fatal("expected a transition error but got none")
			}

			final := tc.path[len(tc.path)-1]
			got, _ := lm.State(nodeID)
			if got != final {
				t.Errorf("final state: got %s want %s", got, final)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Invalid transitions
// ---------------------------------------------------------------------------

func TestLifecycleManager_InvalidTransitions(t *testing.T) {
	tests := []struct {
		name string
		from NodeLifecycleState
		to   NodeLifecycleState
	}{
		{"Initializing→Draining", StateInitializing, StateDraining},
		{"Initializing→Suspended", StateInitializing, StateSuspended},
		{"Terminated→Active", StateTerminated, StateActive},
		{"Terminated→Draining", StateTerminated, StateDraining},
		{"Draining→Initializing", StateDraining, StateInitializing},
		{"Draining→Active", StateDraining, StateActive},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			lm, _ := newLifecycle(t)
			nodeID := "test-node"

			// Get to the 'from' state.
			if err := lm.Initialize(nodeID); err != nil {
				t.Fatalf("Initialize: %v", err)
			}
			if tc.from != StateInitializing {
				// Walk to the desired 'from' state via the valid path.
				path := validPathTo(tc.from)
				for _, s := range path {
					_ = lm.Transition(nodeID, s, "setup")
				}
			}

			if err := lm.Transition(nodeID, tc.to, "invalid"); err == nil {
				t.Fatalf("expected transition error %s → %s but got nil", tc.from, tc.to)
			}
		})
	}
}

// validPathTo returns the sequence of states from Initializing to the target.
func validPathTo(target NodeLifecycleState) []NodeLifecycleState {
	switch target {
	case StateActive:
		return []NodeLifecycleState{StateActive}
	case StateDraining:
		return []NodeLifecycleState{StateActive, StateDraining}
	case StateSuspended:
		return []NodeLifecycleState{StateActive, StateSuspended}
	case StateTerminated:
		return []NodeLifecycleState{StateTerminated}
	default:
		return nil
	}
}

// ---------------------------------------------------------------------------
// Transition emits events
// ---------------------------------------------------------------------------

func TestLifecycleManager_TransitionEmitsEvent(t *testing.T) {
	lm, bus := newLifecycle(t)

	var received []NodeLifecycleEvent
	var mu sync.Mutex
	id := bus.Subscribe(TopicNodeLifecycle, func(e framework.Event) {
		if ev, ok := e.Payload.(NodeLifecycleEvent); ok {
			mu.Lock()
			received = append(received, ev)
			mu.Unlock()
		}
	})
	defer bus.Unsubscribe(TopicNodeLifecycle, id)

	_ = lm.Initialize("n1")
	_ = lm.Transition("n1", StateActive, "boot")
	_ = lm.Transition("n1", StateDraining, "shutdown")

	// Wait for event delivery.
	deadline := time.Now().Add(200 * time.Millisecond)
	for time.Now().Before(deadline) {
		mu.Lock()
		n := len(received)
		mu.Unlock()
		if n >= 3 { // Initialize + 2 transitions
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	mu.Lock()
	defer mu.Unlock()

	if len(received) < 2 {
		t.Fatalf("expected at least 2 lifecycle events, got %d", len(received))
	}
}

// ---------------------------------------------------------------------------
// Transition: unknown node
// ---------------------------------------------------------------------------

func TestLifecycleManager_Transition_UnknownNode(t *testing.T) {
	lm, _ := newLifecycle(t)
	if err := lm.Transition("ghost", StateActive, "test"); err == nil {
		t.Fatal("expected error for unknown node")
	}
}

// ---------------------------------------------------------------------------
// GracefulDrain
// ---------------------------------------------------------------------------

func TestLifecycleManager_GracefulDrain_TransitionsThroughDrainingToSuspended(t *testing.T) {
	engine, _, orch := newReconfigFixture(t)
	lm, _ := newLifecycle(t)

	if err := engine.AddNode(nodeConfigFor("drain-me")); err != nil {
		t.Fatalf("AddNode: %v", err)
	}
	if err := lm.Initialize("drain-me"); err != nil {
		t.Fatalf("Initialize: %v", err)
	}
	if err := lm.Transition("drain-me", StateActive, "boot"); err != nil {
		t.Fatalf("Transition to Active: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	if err := lm.GracefulDrain(ctx, "drain-me", orch); err != nil {
		t.Fatalf("GracefulDrain: %v", err)
	}

	state, _ := lm.State("drain-me")
	if state != StateSuspended {
		t.Errorf("state after drain: got %s want Suspended", state)
	}
}

func TestLifecycleManager_GracefulDrain_ContextCancelled(t *testing.T) {
	_, _, orch := newReconfigFixture(t)
	lm, _ := newLifecycle(t)

	_ = lm.Initialize("cancel-node")
	_ = lm.Transition("cancel-node", StateActive, "boot")

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // already cancelled

	// Drain should still complete (deregister is non-blocking) but may return
	// ctx.Err. Either way the node should end up Draining or Suspended.
	_ = lm.GracefulDrain(ctx, "cancel-node", orch)

	state, ok := lm.State("cancel-node")
	if !ok {
		t.Fatal("node should still be tracked")
	}
	if state != StateSuspended && state != StateDraining {
		t.Errorf("state: got %s, want Suspended or Draining", state)
	}
}

// ---------------------------------------------------------------------------
// Snapshot
// ---------------------------------------------------------------------------

func TestLifecycleManager_Snapshot(t *testing.T) {
	lm, _ := newLifecycle(t)

	_ = lm.Initialize("a")
	_ = lm.Initialize("b")
	_ = lm.Transition("a", StateActive, "boot")

	snap := lm.Snapshot()
	if snap["a"] != StateActive {
		t.Errorf("snapshot a: got %s want Active", snap["a"])
	}
	if snap["b"] != StateInitializing {
		t.Errorf("snapshot b: got %s want Initializing", snap["b"])
	}
}

// ---------------------------------------------------------------------------
// Concurrent transitions
// ---------------------------------------------------------------------------

func TestLifecycleManager_ConcurrentTransitions(t *testing.T) {
	lm, _ := newLifecycle(t)
	const nodes = 50
	var wg sync.WaitGroup

	for i := 0; i < nodes; i++ {
		id := fmt.Sprintf("node-%d", i)
		_ = lm.Initialize(id)
	}

	for i := 0; i < nodes; i++ {
		wg.Add(1)
		id := fmt.Sprintf("node-%d", i)
		go func() {
			defer wg.Done()
			_ = lm.Transition(id, StateActive, "concurrent")
		}()
	}
	wg.Wait()

	snap := lm.Snapshot()
	for i := 0; i < nodes; i++ {
		id := fmt.Sprintf("node-%d", i)
		if snap[id] != StateActive {
			t.Errorf("node %s: got %s want Active", id, snap[id])
		}
	}
}
