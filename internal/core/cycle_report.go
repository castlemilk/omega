package core

import (
	"time"

	omegaerrs "github.com/benebsworth/omega/internal/errors"
)

// ---------------------------------------------------------------------------
// CycleReport — aggregated output of RunFullCycle
// ---------------------------------------------------------------------------

// PerNodeReport captures the full per-node outcome for one cycle.
type PerNodeReport struct {
	NodeID string

	// Execution
	Executed      bool
	Skipped       bool
	SkipReason    string
	ExecutionErr  string
	ErrorClass    omegaerrs.ErrorClass // structured classification of ExecutionErr
	ErrorCode     string               // machine-readable sub-code
	IsRetryable   bool
	Duration      time.Duration

	// Safety
	SafetyPassed     bool
	SafetyViolations []string

	// Adversarial
	AdversarialFlagged  bool
	AdversarialScore    float64
	ProposalBlocked     bool // true when adversarial score > threshold (score < 0.6) — proposal rejected
	Ring2Triggered      bool
	Ring3Triggered      bool

	// Debate gate
	DebateVerdict string // "BUY" / "SELL" / "HOLD" / "" (skipped)

	// Autonomy
	AutonomyLevel AutonomyLevel
}

// CycleSummary is the rolled-up count view across all nodes.
type CycleSummary struct {
	TotalNodes int
	Passed     int
	Failed     int
	Skipped    int
	Duration   time.Duration
}

// AdversarialAlert is emitted when Ring 1 disagreement exceeds the threshold
// for a node.
type AdversarialAlert struct {
	NodeID          string
	MaxDisagreement float64
	Ring2Triggered  bool
	Ring3Triggered  bool
}

// AutonomyChange records a promotion or demotion that happened during the cycle.
type AutonomyChange struct {
	NodeID    string
	FromLevel AutonomyLevel
	ToLevel   AutonomyLevel
	Reason    string
}

// ImprovementAction records what the improvement engine did for a node.
type ImprovementAction struct {
	NodeID      string
	Triggered   bool
	Promoted    bool
	FromVersion int
	ToVersion   int
	Improvement float64
	Err         string
}

// CycleReport is the return value of RunFullCycle.  It aggregates outputs from
// every subsystem that participated in the cycle.
type CycleReport struct {
	CycleID  int64
	Summary  CycleSummary
	PerNode  map[string]*PerNodeReport

	// Aggregated cross-node outputs
	SafetyViolations  []string
	AdversarialAlerts []AdversarialAlert
	AutonomyChanges   []AutonomyChange
	ImprovementActions []ImprovementAction
}
