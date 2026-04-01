// node_health_scorer.go — computes a 0–100 health score for a node based on
// heartbeat freshness, error state, trade activity, signal diversity, and
// regime stability.
package observability

import (
	"strconv"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/heartbeat"
)

// NodeHealthComponents holds the 0–20 score for each of the five health dimensions.
// The Total field is always the sum of all components (0–100).
type NodeHealthComponents struct {
	HeartbeatFreshness int `json:"heartbeat_freshness"` // 0–20
	ErrorRate          int `json:"error_rate"`          // 0–20
	TradeActivity      int `json:"trade_activity"`      // 0–20
	SignalDiversity    int `json:"signal_diversity"`    // 0–20
	RegimeStability    int `json:"regime_stability"`    // 0–20
	Total              int `json:"total"`               // 0–100
}

// NodeHealthResult is the output of NodeHealthScorer.Score.
type NodeHealthResult struct {
	NodeID     string               `json:"node_id"`
	Score      NodeHealthComponents `json:"components"`
	State      string               `json:"state"`       // "healthy" | "degraded" | "critical"
	ComputedAt time.Time            `json:"computed_at"`
}

// NodeHealthScorer computes health scores for node entries.
type NodeHealthScorer struct{}

// NewNodeHealthScorer returns a ready-to-use scorer.
func NewNodeHealthScorer() *NodeHealthScorer { return &NodeHealthScorer{} }

// Score computes a NodeHealthResult for the given NodeEntry snapshot.
// Each component is scored 0–20; Total is their sum (0–100).
func (s *NodeHealthScorer) Score(entry *heartbeat.NodeEntry) NodeHealthResult {
	c := NodeHealthComponents{}

	// ── Heartbeat freshness (0–20) ────────────────────────────────────────────
	// 20 = seen within last 10s; 0 = not seen in 60s+
	if !entry.LastSeen.IsZero() {
		age := time.Since(entry.LastSeen)
		switch {
		case age < 10*time.Second:
			c.HeartbeatFreshness = 20
		case age < 20*time.Second:
			c.HeartbeatFreshness = 16
		case age < 30*time.Second:
			c.HeartbeatFreshness = 10
		case age < heartbeat.StaleAfter:
			c.HeartbeatFreshness = 4
		default:
			c.HeartbeatFreshness = 0
		}
	}

	// ── Error rate (0–20) ─────────────────────────────────────────────────────
	// Penalise DEGRADED/STALE/DEAD health; healthy nodes get full marks unless
	// they have active blockers.
	switch entry.Health {
	case omegav1.NodeHealth_NODE_HEALTH_HEALTHY:
		blockerPenalty := len(entry.Blockers) * 4
		if blockerPenalty > 20 {
			blockerPenalty = 20
		}
		c.ErrorRate = 20 - blockerPenalty
	case omegav1.NodeHealth_NODE_HEALTH_DEGRADED:
		c.ErrorRate = 8
	default: // STALE, DEAD, UNSPECIFIED
		c.ErrorRate = 0
	}

	// ── Trade activity (0–20) ─────────────────────────────────────────────────
	// Based on cumulative closed_trades in node metrics.
	// 20 = ≥10 trades; 0 = no trades at all.
	if ct := nodeHealthIntMetric(entry.Metrics, "closed_trades"); ct > 0 {
		switch {
		case ct >= 10:
			c.TradeActivity = 20
		case ct >= 5:
			c.TradeActivity = 14
		case ct >= 2:
			c.TradeActivity = 8
		default:
			c.TradeActivity = 4
		}
	}

	// ── Signal diversity (0–20) ───────────────────────────────────────────────
	// active_signals / total_signals ratio; 20 = ≥70% active.
	total := nodeHealthIntMetric(entry.Metrics, "total_signals")
	active := nodeHealthIntMetric(entry.Metrics, "active_signals")
	if total > 0 {
		ratio := float64(active) / float64(total)
		switch {
		case ratio >= 0.7:
			c.SignalDiversity = 20
		case ratio >= 0.5:
			c.SignalDiversity = 14
		case ratio >= 0.3:
			c.SignalDiversity = 8
		default:
			c.SignalDiversity = 2
		}
	}

	// ── Regime stability (0–20) ───────────────────────────────────────────────
	// Known, non-uncertain regime = full marks.
	regime := entry.Metrics["regime"]
	switch regime {
	case "bull", "bear", "sideways", "trending", "ranging":
		c.RegimeStability = 20
	case "uncertain", "transitioning":
		c.RegimeStability = 8
	case "", "unknown":
		c.RegimeStability = 0
	default:
		c.RegimeStability = 14 // custom regime name — partial credit
	}

	c.Total = c.HeartbeatFreshness + c.ErrorRate + c.TradeActivity +
		c.SignalDiversity + c.RegimeStability

	return NodeHealthResult{
		NodeID:     entry.NodeID,
		Score:      c,
		State:      scoreToState(c.Total),
		ComputedAt: time.Now(),
	}
}

// scoreToState converts a 0–100 score to a human-readable state label.
func scoreToState(score int) string {
	switch {
	case score >= 60:
		return "healthy"
	case score >= 30:
		return "degraded"
	default:
		return "critical"
	}
}

// nodeHealthIntMetric parses an integer from a node metrics map, returning 0 on failure.
func nodeHealthIntMetric(m map[string]string, key string) int {
	v, ok := m[key]
	if !ok {
		return 0
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return 0
	}
	return n
}
