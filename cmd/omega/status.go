package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/spf13/cobra"
)

var (
	statusJSON  bool
	statusWatch bool
	watchSecs   int
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

	if statusJSON {
		out := map[string]any{
			"health":    healthResp.Msg.Health,
			"nodes":     nodesResp.Msg.Nodes,
			"alignment": alignResp.Msg.Decisions,
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

	return nil
}
