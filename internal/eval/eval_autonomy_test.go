package eval

import (
	"context"
	"testing"

	"github.com/benebsworth/omega/internal/core"
)

func TestAutonomyPromotion_InsufficientCycles(t *testing.T) {
	tests := []struct {
		name         string
		cycles       int
		metrics      map[string]float64
		wantApproved bool
	}{
		{
			name:         "zero_cycles_blocked",
			cycles:       0,
			metrics:      GoodMetrics(),
			wantApproved: false,
		},
		{
			name:         "nine_cycles_blocked",
			cycles:       9,
			metrics:      GoodMetrics(),
			wantApproved: false,
		},
		{
			name:         "ten_cycles_approved",
			cycles:       10,
			metrics:      GoodMetrics(),
			wantApproved: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := NewAutonomyHarness()
			ctx := context.Background()
			h.FeedSuccessfulCycles("node", tt.cycles, 1, tt.metrics)
			result := h.AttemptPromotion(ctx, "node", core.AutonomyLevelSupervised, tt.metrics, int64(tt.cycles+1))
			if result.Approved != tt.wantApproved {
				t.Errorf("Approved=%v want=%v reasons=%v", result.Approved, tt.wantApproved, result.Reasons)
			}
		})
	}
}

func TestAutonomyPromotion_SharpeThreshold(t *testing.T) {
	tests := []struct {
		name         string
		metrics      map[string]float64
		wantApproved bool
	}{
		{
			name:         "sharpe_above_threshold",
			metrics:      map[string]float64{"sharpe": 0.6},
			wantApproved: true,
		},
		{
			name:         "sharpe_exactly_threshold_allowed",
			metrics:      map[string]float64{"sharpe": 0.5},
			wantApproved: true, // code checks sharpe < 0.5; sharpe=0.5 passes
		},
		{
			name:         "sharpe_below_threshold",
			metrics:      map[string]float64{"sharpe": 0.3},
			wantApproved: false,
		},
		{
			name:         "no_sharpe_key_passes",
			metrics:      map[string]float64{"pnl": 0.05},
			wantApproved: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := NewAutonomyHarness()
			ctx := context.Background()
			h.FeedSuccessfulCycles("node", 10, 1, tt.metrics)
			result := h.AttemptPromotion(ctx, "node", core.AutonomyLevelSupervised, tt.metrics, 11)
			if result.Approved != tt.wantApproved {
				t.Errorf("Approved=%v want=%v reasons=%v", result.Approved, tt.wantApproved, result.Reasons)
			}
		})
	}
}

func TestAutonomyPromotion_OneStepAtATime(t *testing.T) {
	h := NewAutonomyHarness()
	ctx := context.Background()
	h.FeedSuccessfulCycles("node", 10, 1, GoodMetrics())

	// Request jump from Manual directly to Full — should only grant Supervised.
	result := h.AttemptPromotion(ctx, "node", core.AutonomyLevelFull, GoodMetrics(), 11)
	if !result.Approved {
		t.Fatalf("expected approval, got reasons: %v", result.Reasons)
	}
	if result.GrantedLevel != core.AutonomyLevelSupervised {
		t.Errorf("GrantedLevel=%v want=Supervised", result.GrantedLevel)
	}
}

func TestAutonomyPromotion_NonMonotoneRejected(t *testing.T) {
	h := NewAutonomyHarness()
	ctx := context.Background()
	h.FeedSuccessfulCycles("node", 10, 1, GoodMetrics())

	// Promote to Supervised.
	r1, cycle := h.PromoteThroughLevel(ctx, "node", core.AutonomyLevelSupervised, GoodMetrics(), 1)
	if !r1.Approved {
		t.Fatalf("first promotion failed: %v", r1.Reasons)
	}

	// Request same level again — should be rejected.
	result := h.AttemptPromotion(ctx, "node", core.AutonomyLevelSupervised, GoodMetrics(), cycle)
	if result.Approved {
		t.Error("re-promotion to same level should be rejected")
	}
}

func TestAutonomyLifecycle_FullPromotion(t *testing.T) {
	h := NewAutonomyHarness()
	result := h.RunFullLifecycle(context.Background(), "lifecycle_node")

	// First 3 promotions (Manual→Supervised, Supervised→Semi, Semi→Full) must succeed.
	for i, r := range result.PromotionResults[:3] {
		if !r.Approved {
			t.Errorf("promotion[%d] rejected: %v", i, r.Reasons)
		}
	}

	// Final level is Manual (demotion was applied).
	if result.FinalLevel != core.AutonomyLevelManual {
		t.Errorf("FinalLevel=%v want=Manual", result.FinalLevel)
	}

	// 4th result (post-demotion re-promotion) must be blocked.
	if result.PromotionResults[3].Approved {
		t.Error("post-demotion re-promotion should be blocked")
	}

	// History should contain 4 events: 3 promotions + 1 demotion.
	if len(result.History) != 4 {
		t.Errorf("history len=%d want=4", len(result.History))
	}
}

func TestAutonomyLifecycle_AutonomousRequiresSustainedExcellence(t *testing.T) {
	// Verify that reaching Full autonomy requires three consecutive 10-cycle promotion windows.
	h := NewAutonomyHarness()
	ctx := context.Background()
	nodeID := "autonomous_node"
	good := GoodMetrics()
	var cycle int64 = 1

	// Manual → Supervised
	r1, c1 := h.PromoteThroughLevel(ctx, nodeID, core.AutonomyLevelSupervised, good, cycle)
	if !r1.Approved {
		t.Fatalf("Supervised promotion failed: %v", r1.Reasons)
	}
	cycle = c1

	// Supervised → Semi
	r2, c2 := h.PromoteThroughLevel(ctx, nodeID, core.AutonomyLevelSemi, good, cycle)
	if !r2.Approved {
		t.Fatalf("Semi promotion failed: %v", r2.Reasons)
	}
	cycle = c2

	// Attempt Full before completing 10 cycles at Semi — must be blocked.
	blocked := h.AttemptPromotion(ctx, nodeID, core.AutonomyLevelFull, good, cycle)
	if blocked.Approved {
		t.Error("Full promotion should require 10 cycles at Semi, but was approved prematurely")
	}

	// Complete the 10 cycles at Semi level then promote.
	h.FeedSuccessfulCycles(nodeID, 10, cycle, good)
	cycle += 10
	r3 := h.AttemptPromotion(ctx, nodeID, core.AutonomyLevelFull, good, cycle)
	if !r3.Approved {
		t.Fatalf("Full promotion failed after sufficient cycles: %v", r3.Reasons)
	}
	if h.Manager.GetLevel(nodeID).Level != core.AutonomyLevelFull {
		t.Error("expected Full autonomy level")
	}
}

func TestAutonomyHistory_NewestFirst(t *testing.T) {
	h := NewAutonomyHarness()
	ctx := context.Background()
	nodeID := "history_node"
	good := GoodMetrics()
	var cycle int64 = 1

	r1, c1 := h.PromoteThroughLevel(ctx, nodeID, core.AutonomyLevelSupervised, good, cycle)
	if !r1.Approved {
		t.Fatal("promotion failed")
	}
	r2, _ := h.PromoteThroughLevel(ctx, nodeID, core.AutonomyLevelSemi, good, c1)
	if !r2.Approved {
		t.Fatal("second promotion failed")
	}

	hist := h.Manager.GetHistory(nodeID, 0)
	if len(hist) < 2 {
		t.Fatalf("expected ≥2 history entries, got %d", len(hist))
	}
	if hist[0].ToLevel <= hist[1].ToLevel {
		t.Errorf("history not newest-first: hist[0].To=%v hist[1].To=%v", hist[0].ToLevel, hist[1].ToLevel)
	}
}
