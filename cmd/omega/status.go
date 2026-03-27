package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/spf13/cobra"
)

var (
	statusJSON         bool
	statusWatch        bool
	watchSecs          int
	statusIntelligence bool
)

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show system health, node states, and alignment decisions",
	RunE:  showStatus,
}

func init() {
	statusCmd.Flags().BoolVar(&statusJSON, "json", false, "Output as JSON")
	statusCmd.Flags().BoolVar(&statusWatch, "watch", false, "Continuously poll status")
	statusCmd.Flags().IntVar(&watchSecs, "interval", 5, "Watch poll interval in seconds")
	statusCmd.Flags().BoolVar(&statusIntelligence, "intelligence", false, "Show intelligence layer metrics")
}

func showStatus(cmd *cobra.Command, args []string) error {
	if statusWatch {
		ticker := time.NewTicker(time.Duration(watchSecs) * time.Second)
		defer ticker.Stop()
		for {
			if err := printStatus(); err != nil {
				fmt.Fprintf(os.Stderr, "error: %v\n", err)
			}
			<-ticker.C
		}
	}
	return printStatus()
}

func printStatus() error {
	client := newOrchestratorClient()
	ctx := context.Background()

	healthResp, err := client.GetHealth(ctx, connect.NewRequest(&omegav1.GetHealthRequest{}))
	if err != nil {
		return fmt.Errorf("GetHealth: %w", err)
	}

	nodesResp, err := client.ListNodes(ctx, connect.NewRequest(&omegav1.ListNodesRequest{}))
	if err != nil {
		return fmt.Errorf("ListNodes: %w", err)
	}

	alignResp, err := client.GetAlignmentDecisions(ctx, connect.NewRequest(&omegav1.GetAlignmentDecisionsRequest{Limit: 5}))
	if err != nil {
		return fmt.Errorf("GetAlignmentDecisions: %w", err)
	}

	cycleResp, _ := client.GetLastCycleResult(ctx, connect.NewRequest(&omegav1.GetLastCycleResultRequest{}))

	if statusJSON {
		out := map[string]any{
			"health":     healthResp.Msg.Health,
			"nodes":      nodesResp.Msg.Nodes,
			"alignment":  alignResp.Msg.Decisions,
			"last_cycle": nil,
		}
		if cycleResp != nil {
			out["last_cycle"] = cycleResp.Msg
		}
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(out)
	}

	h := healthResp.Msg.Health
	fmt.Printf("=== System Health ===\n")
	fmt.Printf("  Status:          %s\n", h.Status)
	fmt.Printf("  Composite Score: %.3f\n", h.CompositeScore)
	fmt.Printf("  Avg Node Health: %.3f\n", h.AvgNodeHealth)
	fmt.Printf("  Nodes:           %d\n", h.NodeCount)
	fmt.Printf("  Total Cycles:    %d\n", h.TotalCycles)
	fmt.Printf("  Open Issues:     %d (errors: %d)\n", h.OpenIssues, h.ErrorIssues)
	fmt.Printf("  Uptime:          %.0fs\n", h.UptimeSeconds)

	fmt.Printf("\n=== Nodes (%d) ===\n", len(nodesResp.Msg.Nodes))
	for _, n := range nodesResp.Msg.Nodes {
		fmt.Printf("  %-30s  status=%-10s  health=%.3f  execs=%d  err_rate=%.2f%%  p95=%.1fms\n",
			n.Name, n.Status, n.Health, n.ExecutionsTotal, n.ErrorRate*100, n.P95LatencyMs)
	}

	if len(alignResp.Msg.Decisions) > 0 {
		fmt.Printf("\n=== Recent Alignment Decisions ===\n")
		for _, d := range alignResp.Msg.Decisions {
			approved := "DENIED"
			if d.Approved {
				approved = "APPROVED"
			}
			ts := ""
			if d.RecordedAt != nil {
				ts = d.RecordedAt.AsTime().Format("2006-01-02 15:04:05")
			}
			fmt.Printf("  [cycle %4d] %-8s  subsystem=%-20s  %s\n",
				d.Cycle, approved, d.TargetSubsystem, ts)
			for _, r := range d.Reasons {
				fmt.Printf("               - %s\n", r)
			}
		}
	}

	if cycleResp != nil && cycleResp.Msg.HasResult {
		fmt.Printf("\n=== Last Cycle (cycle %d, %.0fms) ===\n",
			cycleResp.Msg.Cycle, cycleResp.Msg.TotalDurationMs)
		for _, s := range cycleResp.Msg.StepResults {
			status := "ok"
			detail := fmt.Sprintf("%.0fms", s.DurationMs)
			if !s.Success {
				status = "FAIL"
				detail = s.Error
			}
			fmt.Printf("  %-30s  %s  (%s)\n", s.Name, status, detail)
		}
	}

	if statusIntelligence {
		if err := printIntelligenceMetrics(client); err != nil {
			fmt.Fprintf(os.Stderr, "warning: intelligence metrics unavailable: %v\n", err)
		}
	}

	return nil
}

func printIntelligenceMetrics(client omegav1connect.OrchestratorServiceClient) error {
	ctx := context.Background()
	resp, err := client.GetIntelligenceMetrics(ctx, connect.NewRequest(&omegav1.GetIntelligenceMetricsRequest{
		LastNCycles: 100,
	}))
	if err != nil {
		return err
	}
	m := resp.Msg

	passing := 0
	for _, c := range m.Checks {
		if c.Passing {
			passing++
		}
	}

	provider := m.BrainProvider
	if provider == "" {
		provider = "nobrain"
	}

	fmt.Printf("\n=== Intelligence Layer Status (last %d cycles) ===\n", m.CyclesAnalyzed)
	fmt.Printf("  Brain provider:    %s\n", provider)
	fmt.Printf("  Brain calls:       %d (%.2f/cycle)\n", m.BrainCallsTotal, m.BrainCallsPerCycle)
	fmt.Printf("  Improve calls:     %d (%d accepted)\n", m.ImproveCallsTotal, m.ImproveAcceptedTotal)
	if m.SignalVersionLatest != "" {
		fmt.Printf("  Signal version:    %s\n", m.SignalVersionLatest)
	}
	if len(m.NewSignalsUnlocked) > 0 {
		fmt.Printf("  New signals:       %v\n", m.NewSignalsUnlocked)
	}
	fmt.Printf("\n  Memory:\n")
	fmt.Printf("    Episodes:          %d\n", m.EpisodesTotal)
	fmt.Printf("    Semantic patterns: %d\n", m.SemanticPatternsTotal)
	fmt.Printf("    Shared memory:     %d\n", m.SharedMemoryTotal)
	fmt.Printf("    Utilization:       %.0f%%\n", m.MemoryUtilizationPct*100)
	fmt.Printf("    Cross-project:     %.0f%%\n", m.CrossProjectRatio*100)
	fmt.Printf("\n  Intelligence score:  %.3f (%d/8 checks passing)\n",
		m.IntelligenceScoreLatest, passing)
	for _, c := range m.Checks {
		mark := "✅"
		if !c.Passing {
			mark = "❌"
		}
		fmt.Printf("    %s %s\n", mark, c.Name)
		if c.Detail != "" {
			fmt.Printf("       %s\n", c.Detail)
		}
	}
	return nil
}
