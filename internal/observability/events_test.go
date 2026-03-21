package observability

import (
	"context"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// EventType.String
// ---------------------------------------------------------------------------

func TestEventTypeString(t *testing.T) {
	tests := []struct {
		t    EventType
		want string
	}{
		{EventCycleCompleted, "CycleCompleted"},
		{EventNodePromoted, "NodePromoted"},
		{EventNodeDemoted, "NodeDemoted"},
		{EventAdversarialVeto, "AdversarialVeto"},
		{EventSafetyViolation, "SafetyViolation"},
		{EventMemoryConsolidation, "MemoryConsolidation"},
		{EventImprovementApplied, "ImprovementApplied"},
		{EventCircuitBreakerTripped, "CircuitBreakerTripped"},
		{EventDegradationDetected, "DegradationDetected"},
		{EventType(99), "Unknown"},
	}
	for _, tt := range tests {
		if got := tt.t.String(); got != tt.want {
			t.Errorf("EventType(%d).String() = %q, want %q", tt.t, got, tt.want)
		}
	}
}

// ---------------------------------------------------------------------------
// EventBus — basic pub/sub
// ---------------------------------------------------------------------------

func TestEventBus_SubscribeAll(t *testing.T) {
	bus := NewEventBus(nil)
	ch, cancel := bus.Subscribe(8)
	defer cancel()

	bus.PublishCycleCompleted(CycleCompletedPayload{Cycle: 1, Success: true})

	select {
	case ev := <-ch:
		if ev.Type != EventCycleCompleted {
			t.Fatalf("want CycleCompleted, got %v", ev.Type)
		}
		p, ok := ev.Payload.(CycleCompletedPayload)
		if !ok {
			t.Fatal("payload type mismatch")
		}
		if p.Cycle != 1 {
			t.Fatalf("want cycle=1, got %d", p.Cycle)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for event")
	}
}

func TestEventBus_FilterByType(t *testing.T) {
	bus := NewEventBus(nil)

	// Subscribe only to NodePromoted.
	promotedCh, cancelP := bus.Subscribe(8, EventNodePromoted)
	defer cancelP()

	// Subscribe to all.
	allCh, cancelA := bus.Subscribe(8)
	defer cancelA()

	bus.PublishNodePromoted(NodePromotedPayload{NodeID: "n1", FromLevel: 0.5, ToLevel: 0.7})
	bus.PublishNodeDemoted(NodeDemotedPayload{NodeID: "n2", FromLevel: 0.7, ToLevel: 0.5, Reason: "errors"})

	// promotedCh should receive only the NodePromoted event.
	select {
	case ev := <-promotedCh:
		if ev.Type != EventNodePromoted {
			t.Fatalf("filtered subscriber got wrong type: %v", ev.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("timeout waiting for NodePromoted")
	}

	// Check that NodeDemoted was NOT delivered to promotedCh.
	select {
	case ev := <-promotedCh:
		t.Fatalf("filtered subscriber should not receive NodeDemoted, got %v", ev.Type)
	default:
		// good
	}

	// allCh should receive both.
	received := make(map[EventType]bool)
	deadline := time.After(500 * time.Millisecond)
	for len(received) < 2 {
		select {
		case ev := <-allCh:
			received[ev.Type] = true
		case <-deadline:
			t.Fatalf("all-subscriber only got %v", received)
		}
	}
}

func TestEventBus_OccurredAtSetAutomatically(t *testing.T) {
	bus := NewEventBus(nil)
	ch, cancel := bus.Subscribe(4)
	defer cancel()

	bus.Publish(Event{Type: EventMemoryConsolidation, Payload: MemoryConsolidationPayload{}})

	select {
	case ev := <-ch:
		if ev.OccurredAt.IsZero() {
			t.Fatal("OccurredAt should be set automatically")
		}
	case <-time.After(time.Second):
		t.Fatal("timeout")
	}
}

func TestEventBus_MultipleSubscribers(t *testing.T) {
	bus := NewEventBus(nil)
	const n = 5
	channels := make([]<-chan Event, n)
	cancels := make([]func(), n)
	for i := 0; i < n; i++ {
		channels[i], cancels[i] = bus.Subscribe(4)
		defer cancels[i]()
	}

	bus.PublishMemoryConsolidation(MemoryConsolidationPayload{EpisodesConsolidated: 10})

	for i, ch := range channels {
		select {
		case <-ch:
		case <-time.After(time.Second):
			t.Fatalf("subscriber %d did not receive event", i)
		}
	}
}

func TestEventBus_SlowSubscriberDrop(t *testing.T) {
	bus := NewEventBus(nil)
	// Buffer of 1: the second publish should drop.
	ch, cancel := bus.Subscribe(1)
	defer cancel()

	bus.Publish(Event{Type: EventCycleCompleted, Payload: CycleCompletedPayload{Cycle: 1}})
	bus.Publish(Event{Type: EventCycleCompleted, Payload: CycleCompletedPayload{Cycle: 2}})
	// No panic expected (log warning instead).

	// Drain what was buffered.
	<-ch
}

func TestEventBus_CancelUnsubscribes(t *testing.T) {
	bus := NewEventBus(nil)
	ch, cancel := bus.Subscribe(4)
	cancel() // unsubscribe immediately

	bus.PublishNodePromoted(NodePromotedPayload{NodeID: "n1"})

	select {
	case ev := <-ch:
		// The channel is drained on cancel; receiving here should not happen.
		t.Fatalf("should not receive after cancel, got %v", ev.Type)
	case <-time.After(50 * time.Millisecond):
		// expected
	}
}

// ---------------------------------------------------------------------------
// DrainContext
// ---------------------------------------------------------------------------

func TestDrainContext(t *testing.T) {
	bus := NewEventBus(nil)
	ch, cancel := bus.Subscribe(8)
	defer cancel()

	var received []EventType
	ctx, stop := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		DrainContext(ctx, ch, func(e Event) {
			received = append(received, e.Type)
		})
		close(done)
	}()

	bus.PublishNodePromoted(NodePromotedPayload{NodeID: "n1"})
	bus.PublishNodeDemoted(NodeDemotedPayload{NodeID: "n1"})
	time.Sleep(50 * time.Millisecond)
	stop()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("DrainContext did not stop on ctx cancellation")
	}

	if len(received) != 2 {
		t.Fatalf("want 2 events, got %d", len(received))
	}
}

// ---------------------------------------------------------------------------
// Convenience publish wrappers
// ---------------------------------------------------------------------------

func TestEventBus_AllPublishWrappers(t *testing.T) {
	bus := NewEventBus(nil)
	ch, cancel := bus.Subscribe(16)
	defer cancel()

	publish := []func(){
		func() { bus.PublishCycleCompleted(CycleCompletedPayload{}) },
		func() { bus.PublishNodePromoted(NodePromotedPayload{}) },
		func() { bus.PublishNodeDemoted(NodeDemotedPayload{}) },
		func() { bus.PublishAdversarialVeto(AdversarialVetoPayload{}) },
		func() { bus.PublishSafetyViolation(SafetyViolationPayload{}) },
		func() { bus.PublishMemoryConsolidation(MemoryConsolidationPayload{}) },
		func() { bus.PublishImprovementApplied(ImprovementAppliedPayload{}) },
		func() { bus.PublishCircuitBreakerTripped(CircuitBreakerTrippedPayload{}) },
		func() { bus.PublishDegradationDetected(DegradationDetectedPayload{}) },
	}

	for _, fn := range publish {
		fn()
	}

	received := 0
	deadline := time.After(time.Second)
	for received < len(publish) {
		select {
		case <-ch:
			received++
		case <-deadline:
			t.Fatalf("only received %d/%d events", received, len(publish))
		}
	}
}
