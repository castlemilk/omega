// Package heartbeat — in-memory ring-buffer store for node heartbeats and
// training diagnostics. Thread-safe, no database required.
package heartbeat

import (
	"fmt"
	"sync"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	// ringSize is the number of raw Heartbeat messages kept per node.
	ringSize = 50
	// StaleAfter is the duration after which a silent node is marked STALE.
	StaleAfter = 60 * time.Second
)

// NodeEntry is the live state of a single node as seen by the heartbeat store.
type NodeEntry struct {
	NodeID   string
	NodeType string
	Health   omegav1.NodeHealth
	LastSeen time.Time
	Metrics  map[string]string
	Blockers []string

	// ring buffer of raw heartbeats (unexported; accessed only within package)
	ring [ringSize]*omegav1.Heartbeat
	head int
	count int
}

// Store holds all node entries and the latest training diagnostics.
type Store struct {
	mu          sync.RWMutex
	nodes       map[string]*NodeEntry
	diagnostics *omegav1.TrainingDiagnostics
}

// New creates an empty, ready-to-use Store.
func New() *Store {
	return &Store{nodes: make(map[string]*NodeEntry)}
}

// RecordHeartbeat stores a heartbeat and updates the node's live state.
func (s *Store) RecordHeartbeat(hb *omegav1.Heartbeat) {
	s.mu.Lock()
	defer s.mu.Unlock()

	entry, ok := s.nodes[hb.NodeId]
	if !ok {
		entry = &NodeEntry{NodeID: hb.NodeId}
		s.nodes[hb.NodeId] = entry
	}

	entry.NodeType = hb.NodeType
	entry.Health = hb.Health
	entry.LastSeen = time.Now()
	entry.Metrics = hb.Metrics
	entry.Blockers = hb.Blockers

	// advance ring buffer
	entry.ring[entry.head] = hb
	entry.head = (entry.head + 1) % ringSize
	if entry.count < ringSize {
		entry.count++
	}
}

// RecordDiagnostics stores training diagnostics and derives a synthetic
// heartbeat for the node identified by d.NodeId.
func (s *Store) RecordDiagnostics(d *omegav1.TrainingDiagnostics) {
	s.mu.Lock()
	defer s.mu.Unlock()

	d.Timestamp = timestamppb.Now()
	s.diagnostics = d

	if d.NodeId == "" {
		return
	}

	entry, ok := s.nodes[d.NodeId]
	if !ok {
		entry = &NodeEntry{NodeID: d.NodeId}
		s.nodes[d.NodeId] = entry
	}

	entry.NodeType = "TRAINING_LOOP"
	entry.LastSeen = time.Now()
	entry.Blockers = d.Blockers

	health := omegav1.NodeHealth_NODE_HEALTH_HEALTHY
	if len(d.Blockers) > 0 {
		health = omegav1.NodeHealth_NODE_HEALTH_DEGRADED
	}
	entry.Health = health

	entry.Metrics = map[string]string{
		"cycle":         fmt.Sprintf("%d", d.Cycle),
		"regime":        d.Regime,
		"sit_out":       fmt.Sprintf("%t", d.SitOut),
		"sit_out_reason": d.SitOutReason,
		"open_trades":   fmt.Sprintf("%d", d.OpenTrades),
		"closed_trades": fmt.Sprintf("%d", d.ClosedTrades),
		"pnl":           fmt.Sprintf("%.2f", d.Pnl),
		"active_signals": fmt.Sprintf("%d", d.ActiveSignals),
		"total_signals": fmt.Sprintf("%d", d.TotalSignals),
	}
}

// GetNode returns the live state for a node by ID.
func (s *Store) GetNode(nodeID string) (*NodeEntry, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	e, ok := s.nodes[nodeID]
	return e, ok
}

// ListNodes returns all known nodes with stale detection applied.
// Callers receive a snapshot — mutations to the returned entries do NOT affect
// the store.
func (s *Store) ListNodes() []*NodeEntry {
	s.mu.RLock()
	defer s.mu.RUnlock()

	now := time.Now()
	result := make([]*NodeEntry, 0, len(s.nodes))
	for _, e := range s.nodes {
		snap := *e // copy so callers can't mutate stored state
		if now.Sub(snap.LastSeen) > StaleAfter {
			snap.Health = omegav1.NodeHealth_NODE_HEALTH_STALE
		}
		result = append(result, &snap)
	}
	return result
}

// GetBlockers returns a map of node_id → []blocker for all non-stale nodes
// that have at least one active blocker.
func (s *Store) GetBlockers() map[string][]string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	now := time.Now()
	out := make(map[string][]string)
	for id, e := range s.nodes {
		if now.Sub(e.LastSeen) > StaleAfter {
			continue
		}
		if len(e.Blockers) > 0 {
			out[id] = append([]string(nil), e.Blockers...)
		}
	}
	return out
}

// GetDiagnostics returns the most recently stored training diagnostics, or nil
// if none have been received yet.
func (s *Store) GetDiagnostics() *omegav1.TrainingDiagnostics {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.diagnostics
}

// IsStale returns true when the node has not reported within StaleAfter.
func IsStale(e *NodeEntry) bool {
	return !e.LastSeen.IsZero() && time.Since(e.LastSeen) > StaleAfter
}
