package core

import "time"

// ---------------------------------------------------------------------------
// Typed orchestrator event structs
//
// These are the domain-level events emitted by the Orchestrator during its
// lifecycle.  They are published onto observability.EventBus and can be
// consumed by any subscriber (metrics, logging, external webhooks, etc.).
// ---------------------------------------------------------------------------

// CycleStartedEvent is emitted at the beginning of each orchestration cycle.
type CycleStartedEvent struct {
	CycleID     int64
	Timestamp   time.Time
	ActiveNodes []string // node IDs that will participate in this cycle
}

// CycleCompletedEvent is emitted when a full orchestration cycle finishes.
type CycleCompletedEvent struct {
	CycleID  int64
	Duration time.Duration
	// Results maps node ID → execution outcome (true = success).
	Results map[string]bool
	// Errors maps node ID → error text for nodes that failed.
	Errors map[string]string
}

// NodeStateChangedEvent is emitted whenever a node's operational state changes
// (e.g. registered, promoted, demoted, skipped).
type NodeStateChangedEvent struct {
	NodeID   string
	OldState string
	NewState string
	Reason   string
}

// SafetyViolationEvent is emitted when a safety gate fires for a node.
type SafetyViolationEvent struct {
	NodeID   string
	Gate     string // name of the safety gate
	Severity string // "soft" | "hard"
	Details  string
}

// AdversarialAlertEvent is emitted when an adversarial ring raises an alert.
type AdversarialAlertEvent struct {
	Ring      int    // 1, 2, or 3
	NodeID    string
	Score     float64
	Threshold float64
}

// ImprovementTriggeredEvent is emitted when an improvement strategy is
// scheduled for a node.
type ImprovementTriggeredEvent struct {
	NodeID     string
	Strategy   string
	Parameters map[string]any
}

// CircuitStateChangedEvent is emitted when a node's circuit breaker changes state.
type CircuitStateChangedEvent struct {
	NodeID   string
	OldState string // "CLOSED" | "OPEN" | "HALF_OPEN"
	NewState string
	Reason   string
}
