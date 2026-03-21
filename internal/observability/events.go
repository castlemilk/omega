package observability

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// EventType identifies a specific kind of framework event.
type EventType int

const (
	EventCycleCompleted       EventType = iota // A full orchestration cycle finished.
	EventNodePromoted                          // A node's autonomy level was promoted.
	EventNodeDemoted                           // A node's autonomy level was demoted.
	EventAdversarialVeto                       // An adversarial ring vetoed an action.
	EventSafetyViolation                       // A safety-alignment layer raised a violation.
	EventMemoryConsolidation                   // Memory consolidation completed.
	EventImprovementApplied                    // An improvement was applied to a node.
	EventCircuitBreakerTripped                 // A circuit breaker transitioned to OPEN.
	EventDegradationDetected                   // A degradation pattern was detected for a node.
)

// String returns a human-readable event type name.
func (t EventType) String() string {
	switch t {
	case EventCycleCompleted:
		return "CycleCompleted"
	case EventNodePromoted:
		return "NodePromoted"
	case EventNodeDemoted:
		return "NodeDemoted"
	case EventAdversarialVeto:
		return "AdversarialVeto"
	case EventSafetyViolation:
		return "SafetyViolation"
	case EventMemoryConsolidation:
		return "MemoryConsolidation"
	case EventImprovementApplied:
		return "ImprovementApplied"
	case EventCircuitBreakerTripped:
		return "CircuitBreakerTripped"
	case EventDegradationDetected:
		return "DegradationDetected"
	default:
		return "Unknown"
	}
}

// ---------------------------------------------------------------------------
// Typed event structs
// ---------------------------------------------------------------------------

// Event is the envelope carried by the bus.
type Event struct {
	Type      EventType
	OccurredAt time.Time
	Payload   EventPayload
}

// EventPayload is implemented by all concrete event types.
type EventPayload interface {
	eventPayload() // private marker — prevents external implementations
}

// CycleCompletedPayload is emitted when an orchestration cycle finishes.
type CycleCompletedPayload struct {
	Cycle        int64
	DurationSecs float64
	NodeCount    int
	Success      bool
	ErrorText    string
}

func (CycleCompletedPayload) eventPayload() {}

// NodePromotedPayload is emitted when a node gains autonomy.
type NodePromotedPayload struct {
	NodeID   string
	FromLevel float64
	ToLevel   float64
}

func (NodePromotedPayload) eventPayload() {}

// NodeDemotedPayload is emitted when a node loses autonomy.
type NodeDemotedPayload struct {
	NodeID   string
	FromLevel float64
	ToLevel   float64
	Reason    string
}

func (NodeDemotedPayload) eventPayload() {}

// AdversarialVetoPayload is emitted when an adversarial ring vetoes an action.
type AdversarialVetoPayload struct {
	NodeID string
	Ring   int    // 1, 2, or 3
	Reason string
}

func (AdversarialVetoPayload) eventPayload() {}

// SafetyViolationPayload is emitted when an alignment layer raises a violation.
type SafetyViolationPayload struct {
	NodeID     string
	Layer      int    // 1=SafetyEnvelope, 2=ParetoEvaluator, 3=OutcomeBasedScorer
	Constraint string
	Value      float64
	Limit      float64
}

func (SafetyViolationPayload) eventPayload() {}

// MemoryConsolidationPayload is emitted when memory consolidation completes.
type MemoryConsolidationPayload struct {
	EpisodesConsolidated int
	ChangePointDetected  bool
}

func (MemoryConsolidationPayload) eventPayload() {}

// ImprovementAppliedPayload is emitted when an improvement is applied to a node.
type ImprovementAppliedPayload struct {
	NodeID        string
	StrategyName  string
	BeforeMetrics map[string]float64
	AfterMetrics  map[string]float64
}

func (ImprovementAppliedPayload) eventPayload() {}

// CircuitBreakerTrippedPayload is emitted when a circuit breaker opens.
type CircuitBreakerTrippedPayload struct {
	NodeID           string
	ConsecutiveFails int
}

func (CircuitBreakerTrippedPayload) eventPayload() {}

// DegradationDetectedPayload is emitted when a degradation pattern is detected.
type DegradationDetectedPayload struct {
	NodeID    string
	Kind      string  // "performance" or "error_rate"
	Metric    string
	Current   float64
	Baseline  float64
	DropPct   float64
}

func (DegradationDetectedPayload) eventPayload() {}

// ---------------------------------------------------------------------------
// EventBus
// ---------------------------------------------------------------------------

// Subscription represents a registered subscriber.
type Subscription struct {
	id     uint64
	filter map[EventType]struct{} // nil = subscribe to all
	ch     chan Event
}

// EventBus is a typed in-process publish-subscribe bus.
// Publishers call Publish; subscribers call Subscribe.
type EventBus struct {
	mu     sync.RWMutex
	nextID uint64
	subs   map[uint64]*Subscription
	logger *slog.Logger
}

// NewEventBus creates a new EventBus.
func NewEventBus(logger *slog.Logger) *EventBus {
	if logger == nil {
		logger = slog.Default()
	}
	return &EventBus{
		subs:   make(map[uint64]*Subscription),
		logger: logger,
	}
}

// Subscribe returns a channel that receives events matching the given types.
// Pass no types to receive all events.
// bufSize controls the channel buffer; 0 uses a default of 64.
func (b *EventBus) Subscribe(bufSize int, types ...EventType) (ch <-chan Event, cancel func()) {
	if bufSize <= 0 {
		bufSize = 64
	}
	filter := make(map[EventType]struct{}, len(types))
	for _, t := range types {
		filter[t] = struct{}{}
	}
	if len(types) == 0 {
		filter = nil // nil = all events
	}

	sub := &Subscription{
		filter: filter,
		ch:     make(chan Event, bufSize),
	}

	b.mu.Lock()
	b.nextID++
	sub.id = b.nextID
	b.subs[sub.id] = sub
	b.mu.Unlock()

	return sub.ch, func() {
		b.mu.Lock()
		delete(b.subs, sub.id)
		b.mu.Unlock()
		// Drain so blocked publishers can proceed.
		for len(sub.ch) > 0 {
			<-sub.ch
		}
	}
}

// Publish delivers e to all matching subscribers.
// Subscribers that are not keeping up (full channel) are skipped with a log warning.
func (b *EventBus) Publish(e Event) {
	if e.OccurredAt.IsZero() {
		e.OccurredAt = time.Now()
	}

	b.mu.RLock()
	subs := make([]*Subscription, 0, len(b.subs))
	for _, s := range b.subs {
		subs = append(subs, s)
	}
	b.mu.RUnlock()

	for _, s := range subs {
		if s.filter != nil {
			if _, ok := s.filter[e.Type]; !ok {
				continue
			}
		}
		select {
		case s.ch <- e:
		default:
			b.logger.Warn("event bus subscriber channel full, dropping event",
				"event_type", e.Type.String(),
				"subscriber_id", s.id,
			)
		}
	}
}

// PublishCycleCompleted is a convenience wrapper.
func (b *EventBus) PublishCycleCompleted(p CycleCompletedPayload) {
	b.Publish(Event{Type: EventCycleCompleted, Payload: p})
}

// PublishNodePromoted is a convenience wrapper.
func (b *EventBus) PublishNodePromoted(p NodePromotedPayload) {
	b.Publish(Event{Type: EventNodePromoted, Payload: p})
}

// PublishNodeDemoted is a convenience wrapper.
func (b *EventBus) PublishNodeDemoted(p NodeDemotedPayload) {
	b.Publish(Event{Type: EventNodeDemoted, Payload: p})
}

// PublishAdversarialVeto is a convenience wrapper.
func (b *EventBus) PublishAdversarialVeto(p AdversarialVetoPayload) {
	b.Publish(Event{Type: EventAdversarialVeto, Payload: p})
}

// PublishSafetyViolation is a convenience wrapper.
func (b *EventBus) PublishSafetyViolation(p SafetyViolationPayload) {
	b.Publish(Event{Type: EventSafetyViolation, Payload: p})
}

// PublishMemoryConsolidation is a convenience wrapper.
func (b *EventBus) PublishMemoryConsolidation(p MemoryConsolidationPayload) {
	b.Publish(Event{Type: EventMemoryConsolidation, Payload: p})
}

// PublishImprovementApplied is a convenience wrapper.
func (b *EventBus) PublishImprovementApplied(p ImprovementAppliedPayload) {
	b.Publish(Event{Type: EventImprovementApplied, Payload: p})
}

// PublishCircuitBreakerTripped is a convenience wrapper.
func (b *EventBus) PublishCircuitBreakerTripped(p CircuitBreakerTrippedPayload) {
	b.Publish(Event{Type: EventCircuitBreakerTripped, Payload: p})
}

// PublishDegradationDetected is a convenience wrapper.
func (b *EventBus) PublishDegradationDetected(p DegradationDetectedPayload) {
	b.Publish(Event{Type: EventDegradationDetected, Payload: p})
}

// DrainContext runs a subscriber loop until ctx is cancelled.
// handler is called for each event received.
func DrainContext(ctx context.Context, ch <-chan Event, handler func(Event)) {
	for {
		select {
		case <-ctx.Done():
			return
		case e, ok := <-ch:
			if !ok {
				return
			}
			handler(e)
		}
	}
}
