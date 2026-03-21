// Package core provides the AutonomyManager which tracks per-node autonomy levels
// and promotion history in memory (no external DB required).
package core

import (
	"context"
	"sync"
	"time"
)

// AutonomyLevel mirrors the proto enum values so callers don't import the proto package.
type AutonomyLevel int32

const (
	AutonomyLevelUnspecified AutonomyLevel = 0
	AutonomyLevelManual      AutonomyLevel = 1 // All decisions require human approval
	AutonomyLevelSupervised  AutonomyLevel = 2 // Runs autonomously; results reviewed post-hoc
	AutonomyLevelSemi        AutonomyLevel = 3 // Runs autonomously; only anomalies reviewed
	AutonomyLevelFull        AutonomyLevel = 4 // Fully autonomous; self-correcting
)

// PromotionEvent records a single level change.
type PromotionEvent struct {
	NodeID     string
	FromLevel  AutonomyLevel
	ToLevel    AutonomyLevel
	Trigger    string
	Cycle      int64
	RecordedAt time.Time
}

// NodeAutonomyState tracks per-node state.
type NodeAutonomyState struct {
	Level         AutonomyLevel
	Confidence    float64
	CyclesAtLevel int64
	Since         time.Time
	Metrics       map[string]float64
	LastSuccess   bool
	LastRecorded  time.Time
}

// PromotionResult is the decision output of RequestPromotion.
type PromotionResult struct {
	Approved     bool
	GrantedLevel AutonomyLevel
	Reasons      []string
}

// AutonomyManager manages autonomy levels and promotion history for all nodes.
type AutonomyManager struct {
	mu      sync.RWMutex
	states  map[string]*NodeAutonomyState
	history map[string][]PromotionEvent // keyed by nodeID
}

// NewAutonomyManager creates a new manager with empty state.
func NewAutonomyManager() *AutonomyManager {
	return &AutonomyManager{
		states:  make(map[string]*NodeAutonomyState),
		history: make(map[string][]PromotionEvent),
	}
}

// RecordCycleMetrics stores per-node performance metrics for a cycle.
func (m *AutonomyManager) RecordCycleMetrics(nodeID string, cycle int64, metrics map[string]float64, success bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	st := m.getOrInit(nodeID)
	for k, v := range metrics {
		st.Metrics[k] = v
	}
	st.LastSuccess = success
	st.LastRecorded = time.Now()
	if success {
		st.CyclesAtLevel++
	}
}

// GetLevel returns the current autonomy level and associated metadata for a node.
func (m *AutonomyManager) GetLevel(nodeID string) *NodeAutonomyState {
	m.mu.RLock()
	defer m.mu.RUnlock()
	st, ok := m.states[nodeID]
	if !ok {
		return &NodeAutonomyState{
			Level:      AutonomyLevelManual,
			Confidence: 0,
			Since:      time.Now(),
			Metrics:    make(map[string]float64),
		}
	}
	// return a copy
	cp := *st
	mCopy := make(map[string]float64, len(st.Metrics))
	for k, v := range st.Metrics {
		mCopy[k] = v
	}
	cp.Metrics = mCopy
	return &cp
}

// RequestPromotion evaluates whether a node should be promoted based on its metrics
// and the requested level. Uses a simple heuristic: require sufficient cycles at
// current level, a success rate above threshold, and a monotone level request.
func (m *AutonomyManager) RequestPromotion(_ context.Context, nodeID string, requestedLevel AutonomyLevel, supportingMetrics map[string]float64, cycle int64) PromotionResult {
	m.mu.RLock()
	st := m.getOrInitRO(nodeID)
	m.mu.RUnlock()

	if requestedLevel <= st.Level {
		return PromotionResult{
			Approved:     false,
			GrantedLevel: st.Level,
			Reasons:      []string{"requested level is not higher than current level"},
		}
	}

	// Require at minimum 10 cycles at current level, and sharpe > 0.5 if available.
	if st.CyclesAtLevel < 10 {
		return PromotionResult{
			Approved:     false,
			GrantedLevel: st.Level,
			Reasons:      []string{"insufficient cycles at current level (need ≥ 10)"},
		}
	}

	sharpe, hasSharpe := supportingMetrics["sharpe"]
	if hasSharpe && sharpe < 0.5 {
		return PromotionResult{
			Approved:     false,
			GrantedLevel: st.Level,
			Reasons:      []string{"sharpe ratio below threshold (need ≥ 0.5)"},
		}
	}

	// Approve only one level at a time.
	granted := st.Level + 1
	if granted > requestedLevel {
		granted = requestedLevel
	}
	return PromotionResult{
		Approved:     true,
		GrantedLevel: granted,
		Reasons:      []string{"performance criteria met"},
	}
}

// RecordPromotion persists a confirmed level change.
func (m *AutonomyManager) RecordPromotion(nodeID string, fromLevel, toLevel AutonomyLevel, trigger string, cycle int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	st := m.getOrInit(nodeID)
	st.Level = toLevel
	st.CyclesAtLevel = 0
	st.Since = time.Now()
	m.history[nodeID] = append(m.history[nodeID], PromotionEvent{
		NodeID:     nodeID,
		FromLevel:  fromLevel,
		ToLevel:    toLevel,
		Trigger:    trigger,
		Cycle:      cycle,
		RecordedAt: time.Now(),
	})
}

// GetHistory returns the promotion/demotion history for a node, newest-first,
// capped at limit (0 means all).
func (m *AutonomyManager) GetHistory(nodeID string, limit int) []PromotionEvent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	hist := m.history[nodeID]
	if len(hist) == 0 {
		return nil
	}
	// return a reversed copy (newest first)
	out := make([]PromotionEvent, len(hist))
	for i, e := range hist {
		out[len(hist)-1-i] = e
	}
	if limit > 0 && limit < len(out) {
		out = out[:limit]
	}
	return out
}

// getOrInit returns (or creates) the NodeAutonomyState for nodeID. Must be called under write lock.
func (m *AutonomyManager) getOrInit(nodeID string) *NodeAutonomyState {
	st, ok := m.states[nodeID]
	if !ok {
		st = &NodeAutonomyState{
			Level:   AutonomyLevelManual,
			Since:   time.Now(),
			Metrics: make(map[string]float64),
		}
		m.states[nodeID] = st
	}
	return st
}

// getOrInitRO returns (or creates) the NodeAutonomyState under read lock (safe because
// it only reads). If missing it returns a zero value without storing.
func (m *AutonomyManager) getOrInitRO(nodeID string) NodeAutonomyState {
	st, ok := m.states[nodeID]
	if !ok {
		return NodeAutonomyState{
			Level:   AutonomyLevelManual,
			Metrics: make(map[string]float64),
		}
	}
	return *st
}
