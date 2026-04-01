package heartbeat

import (
	"testing"
	"time"
)

func TestLifecycleStore_RecordAndGet(t *testing.T) {
	s := NewLifecycleStore()

	s.RecordEvent(LifecycleEvent{
		NodeID:    "node-a",
		FromState: StateStarting,
		ToState:   StateRunning,
		Reason:    "warmup complete",
		Timestamp: time.Now(),
	})

	events := s.GetEvents("node-a")
	if len(events) != 1 {
		t.Fatalf("want 1 event, got %d", len(events))
	}
	if events[0].ToState != StateRunning {
		t.Errorf("want StateRunning, got %v", events[0].ToState)
	}
}

func TestLifecycleStore_RingOverflow(t *testing.T) {
	s := NewLifecycleStore()
	for i := range lifecycleRingSize + 50 {
		s.RecordEvent(LifecycleEvent{
			NodeID:    "node-b",
			FromState: StateRunning,
			ToState:   StateDegraded,
			Reason:    "test",
			Timestamp: time.Now(),
		})
		_ = i
	}
	events := s.GetEvents("node-b")
	if len(events) != lifecycleRingSize {
		t.Errorf("want ring capped at %d, got %d", lifecycleRingSize, len(events))
	}
}

func TestLifecycleStore_CurrentState(t *testing.T) {
	s := NewLifecycleStore()

	// Unknown node → StateUnknown
	if got := s.CurrentState("absent"); got != StateUnknown {
		t.Errorf("want StateUnknown, got %v", got)
	}

	s.RecordEvent(LifecycleEvent{NodeID: "node-c", ToState: StateStopped, Timestamp: time.Now()})
	if got := s.CurrentState("node-c"); got != StateStopped {
		t.Errorf("want StateStopped, got %v", got)
	}
}

func TestLifecycleStore_UnknownNodeReturnsEmpty(t *testing.T) {
	s := NewLifecycleStore()
	events := s.GetEvents("nonexistent")
	if events == nil {
		t.Error("want empty slice, got nil")
	}
	if len(events) != 0 {
		t.Errorf("want 0 events, got %d", len(events))
	}
}
