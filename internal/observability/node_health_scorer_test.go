package observability

import (
	"testing"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/heartbeat"
)

func freshEntry(metrics map[string]string, health omegav1.NodeHealth) *heartbeat.NodeEntry {
	return &heartbeat.NodeEntry{
		NodeID:   "test-node",
		NodeType: "TRAINING_LOOP",
		Health:   health,
		LastSeen: time.Now(),
		Metrics:  metrics,
	}
}

func TestNodeHealthScorer_HealthyNode(t *testing.T) {
	scorer := NewNodeHealthScorer()
	entry := freshEntry(map[string]string{
		"closed_trades":  "10",
		"active_signals": "8",
		"total_signals":  "10",
		"regime":         "bull",
	}, omegav1.NodeHealth_NODE_HEALTH_HEALTHY)

	result := scorer.Score(entry)
	if result.Score.Total < 60 {
		t.Errorf("healthy node: want score ≥ 60, got %d", result.Score.Total)
	}
	if result.State != "healthy" {
		t.Errorf("want state 'healthy', got %q", result.State)
	}
}

func TestNodeHealthScorer_StaleNode(t *testing.T) {
	scorer := NewNodeHealthScorer()
	entry := &heartbeat.NodeEntry{
		NodeID:   "stale-node",
		Health:   omegav1.NodeHealth_NODE_HEALTH_STALE,
		LastSeen: time.Now().Add(-5 * time.Minute), // 5 minutes stale
		Metrics:  map[string]string{},
	}

	result := scorer.Score(entry)
	if result.Score.HeartbeatFreshness != 0 {
		t.Errorf("stale node: want heartbeat_freshness=0, got %d", result.Score.HeartbeatFreshness)
	}
	if result.State != "critical" {
		t.Errorf("want state 'critical', got %q", result.State)
	}
}

func TestNodeHealthScorer_AllComponentsPresent(t *testing.T) {
	scorer := NewNodeHealthScorer()
	entry := freshEntry(map[string]string{
		"closed_trades":  "5",
		"active_signals": "6",
		"total_signals":  "10",
		"regime":         "bear",
	}, omegav1.NodeHealth_NODE_HEALTH_HEALTHY)

	result := scorer.Score(entry)

	total := result.Score.HeartbeatFreshness +
		result.Score.ErrorRate +
		result.Score.TradeActivity +
		result.Score.SignalDiversity +
		result.Score.RegimeStability

	if result.Score.Total != total {
		t.Errorf("total %d ≠ sum of components %d", result.Score.Total, total)
	}
	if result.Score.Total < 0 || result.Score.Total > 100 {
		t.Errorf("total score out of range [0,100]: %d", result.Score.Total)
	}
}

func TestNodeHealthScorer_NoTrades(t *testing.T) {
	scorer := NewNodeHealthScorer()
	entry := freshEntry(map[string]string{
		"closed_trades":  "0",
		"active_signals": "5",
		"total_signals":  "10",
		"regime":         "unknown",
	}, omegav1.NodeHealth_NODE_HEALTH_HEALTHY)

	result := scorer.Score(entry)
	if result.Score.TradeActivity != 0 {
		t.Errorf("want trade_activity=0 with no trades, got %d", result.Score.TradeActivity)
	}
}
