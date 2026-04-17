package heartbeat

import (
	"testing"
	"time"
)

func TestDecisionStore_RecordAndGet(t *testing.T) {
	s := NewDecisionStore()

	s.RecordDecision(DecisionEntry{
		NodeID:       "node-a",
		Cycle:        1,
		ReceivedAt:   time.Now(),
		SnapshotJSON: `{"cycle":1,"regime":"bull"}`,
	})

	decisions := s.GetDecisions("node-a")
	if len(decisions) != 1 {
		t.Fatalf("want 1 decision, got %d", len(decisions))
	}
	if decisions[0].Cycle != 1 {
		t.Errorf("want cycle 1, got %d", decisions[0].Cycle)
	}
}

func TestDecisionStore_BoundedQueue(t *testing.T) {
	s := NewDecisionStore()
	for i := range decisionQueueSize + 20 {
		s.RecordDecision(DecisionEntry{
			NodeID:       "node-b",
			Cycle:        int32(i + 1), //nolint:gosec // bounded by decisionQueueSize+20
			ReceivedAt:   time.Now(),
			SnapshotJSON: `{}`,
		})
	}
	decisions := s.GetDecisions("node-b")
	if len(decisions) != decisionQueueSize {
		t.Errorf("want %d decisions (capped), got %d", decisionQueueSize, len(decisions))
	}
	// Oldest entries evicted — first entry should be cycle 21
	if decisions[0].Cycle != 21 {
		t.Errorf("want oldest cycle 21, got %d", decisions[0].Cycle)
	}
}

func TestDecisionStore_GetByCycle(t *testing.T) {
	s := NewDecisionStore()
	s.RecordDecision(DecisionEntry{NodeID: "node-c", Cycle: 10, ReceivedAt: time.Now(), SnapshotJSON: `{"x":1}`})
	s.RecordDecision(DecisionEntry{NodeID: "node-c", Cycle: 11, ReceivedAt: time.Now(), SnapshotJSON: `{"x":2}`})

	entry, ok := s.GetDecisionByCycle("node-c", 10)
	if !ok {
		t.Fatal("want found=true for cycle 10")
	}
	if entry.SnapshotJSON != `{"x":1}` {
		t.Errorf("wrong snapshot: %q", entry.SnapshotJSON)
	}

	_, notFound := s.GetDecisionByCycle("node-c", 999)
	if notFound {
		t.Error("want found=false for missing cycle 999")
	}
}

func TestDecisionStore_UnknownNode(t *testing.T) {
	s := NewDecisionStore()
	d := s.GetDecisions("ghost")
	if d == nil {
		t.Error("want empty slice, got nil")
	}
}
