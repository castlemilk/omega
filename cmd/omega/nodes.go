package main

import (
	"context"
	"fmt"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/spf13/cobra"
)

var nodesCmd = &cobra.Command{
	Use:   "nodes",
	Short: "Manage registered nodes",
}

var nodesListCmd = &cobra.Command{
	Use:   "list",
	Short: "List registered nodes with status and health",
	RunE:  nodesList,
}

var nodesGetCmd = &cobra.Command{
	Use:   "get <node-id>",
	Short: "Get detailed info for a specific node",
	Args:  cobra.ExactArgs(1),
	RunE:  nodesGet,
}

var nodesPromoteCmd = &cobra.Command{
	Use:   "promote <node-id>",
	Short: "Submit positive feedback to promote a node's autonomy",
	Args:  cobra.ExactArgs(1),
	RunE:  nodesPromote,
}

var nodesDemoteCmd = &cobra.Command{
	Use:   "demote <node-id>",
	Short: "Submit corrective feedback to demote a node's autonomy",
	Args:  cobra.ExactArgs(1),
	RunE:  nodesDemote,
}

func init() {
	nodesCmd.AddCommand(nodesListCmd)
	nodesCmd.AddCommand(nodesGetCmd)
	nodesCmd.AddCommand(nodesPromoteCmd)
	nodesCmd.AddCommand(nodesDemoteCmd)
}

func nodesList(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	resp, err := client.ListNodes(ctx, connect.NewRequest(&omegav1.ListNodesRequest{}))
	if err != nil {
		return fmt.Errorf("ListNodes: %w", err)
	}

	nodes := resp.Msg.Nodes
	if len(nodes) == 0 {
		fmt.Println("No nodes registered.")
		return nil
	}

	fmt.Printf("%-36s  %-30s  %-8s  %-10s  %6s  %8s  %10s\n",
		"NODE ID", "NAME", "VERSION", "STATUS", "HEALTH", "EXECS", "IMPROVEMENTS")
	fmt.Printf("%s\n", repeat("-", 115))
	for _, n := range nodes {
		fmt.Printf("%-36s  %-30s  %-8s  %-10s  %6.3f  %8d  %10d\n",
			n.NodeId, n.Name, n.Version, n.Status, n.Health, n.ExecutionsTotal, n.ImprovementCount)
	}

	return nil
}

func nodesGet(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	resp, err := client.GetNode(ctx, connect.NewRequest(&omegav1.GetNodeRequest{NodeId: args[0]}))
	if err != nil {
		return fmt.Errorf("GetNode: %w", err)
	}

	n := resp.Msg.Node
	fmt.Printf("=== Node: %s ===\n", n.Name)
	fmt.Printf("  ID:           %s\n", n.NodeId)
	fmt.Printf("  Version:      %s\n", n.Version)
	fmt.Printf("  Status:       %s\n", n.Status)
	fmt.Printf("  Health:       %.3f\n", n.Health)
	fmt.Printf("  Executions:   %d  (err rate: %.2f%%)\n", n.ExecutionsTotal, n.ErrorRate*100)
	fmt.Printf("  Avg latency:  %.1fms  p95: %.1fms\n", n.AvgLatencyMs, n.P95LatencyMs)
	fmt.Printf("  Improvements: %d\n", n.ImprovementCount)
	if len(n.Capabilities) > 0 {
		fmt.Printf("  Capabilities: %v\n", n.Capabilities)
	}

	if len(resp.Msg.RecentExecutions) > 0 {
		fmt.Printf("\n  Recent executions:\n")
		for _, e := range resp.Msg.RecentExecutions {
			status := "ok"
			if !e.Success {
				status = "FAIL"
			}
			fmt.Printf("    [cycle %4d] %-6s  %-20s  %.1fms\n",
				e.Cycle, status, e.Action, e.DurationMs)
		}
	}

	return nil
}

func nodesPromote(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	nodeID := args[0]
	resp, err := client.SubmitFeedback(ctx, connect.NewRequest(&omegav1.SubmitFeedbackRequest{
		TargetNode: nodeID,
		Text:       "promote: manual autonomy increase via CLI",
	}))
	if err != nil {
		return fmt.Errorf("SubmitFeedback: %w", err)
	}
	if resp.Msg.Ok {
		fmt.Printf("Node %s promoted (feedback submitted).\n", nodeID)
	} else {
		fmt.Printf("Feedback submitted for %s, but server returned ok=false.\n", nodeID)
	}
	return nil
}

func nodesDemote(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	nodeID := args[0]
	resp, err := client.SubmitFeedback(ctx, connect.NewRequest(&omegav1.SubmitFeedbackRequest{
		TargetNode: nodeID,
		Text:       "demote: manual autonomy reduction via CLI",
	}))
	if err != nil {
		return fmt.Errorf("SubmitFeedback: %w", err)
	}
	if resp.Msg.Ok {
		fmt.Printf("Node %s demoted (feedback submitted).\n", nodeID)
	} else {
		fmt.Printf("Feedback submitted for %s, but server returned ok=false.\n", nodeID)
	}
	return nil
}

func repeat(s string, n int) string {
	result := ""
	for i := 0; i < n; i++ {
		result += s
	}
	return result
}
