package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/registry"
	"github.com/spf13/cobra"
)

var nodesCmd = &cobra.Command{
	Use:   "nodes",
	Short: "Manage registered nodes",
	RunE:  nodesList, // default: list all nodes
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

// catalog subcommands — operate on the static compile-time catalog, no live server needed.

var nodesCatalogCmd = &cobra.Command{
	Use:   "catalog [name]",
	Short: "Browse the static node catalog (no server required)",
	Long: `Display the compile-time catalog of all Omega node types.

Without arguments, prints a summary table of all nodes.
With a node name, prints full detail for that node.

Filter by project or type with flags:
  omega nodes catalog --project victoria
  omega nodes catalog --type signal
  omega nodes catalog --level 3`,
	Args: cobra.MaximumNArgs(1),
	RunE: nodesCatalog,
}

var nodesCatalogExportCmd = &cobra.Command{
	Use:   "export",
	Short: "Write docs/node_registry.md and data/node_registry.json from the catalog",
	RunE:  nodesCatalogExport,
}

var (
	catalogFilterProject string
	catalogFilterType    string
	catalogFilterLevel   int
)

func init() {
	nodesCmd.AddCommand(nodesListCmd)
	nodesCmd.AddCommand(nodesGetCmd)
	nodesCmd.AddCommand(nodesPromoteCmd)
	nodesCmd.AddCommand(nodesDemoteCmd)
	nodesCmd.AddCommand(nodesCatalogCmd)
	nodesCatalogCmd.AddCommand(nodesCatalogExportCmd)

	nodesCatalogCmd.Flags().StringVar(&catalogFilterProject, "project", "", "Filter by project: victoria | polymarket | shared | platform")
	nodesCatalogCmd.Flags().StringVar(&catalogFilterType, "type", "", "Filter by type: signal | strategy | risk | memory | reasoning | execution | platform")
	nodesCatalogCmd.Flags().IntVar(&catalogFilterLevel, "level", -1, "Filter by minimum autonomy level (0–4)")
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

// ── catalog handlers ──────────────────────────────────────────────────────────

func nodesCatalog(cmd *cobra.Command, args []string) error {
	// Detail view for a named node.
	if len(args) == 1 {
		entry := registry.ByName(args[0])
		if entry == nil {
			return fmt.Errorf("node %q not found in catalog", args[0])
		}
		fmt.Print(registry.FormatDetail(*entry))
		return nil
	}

	// Apply filters.
	entries := registry.Catalog
	switch {
	case catalogFilterProject != "":
		entries = registry.ByProject(catalogFilterProject)
	case catalogFilterType != "":
		entries = registry.ByType(catalogFilterType)
	case catalogFilterLevel >= 0:
		entries = registry.ByAutonomyLevel(catalogFilterLevel)
	}

	// If filters are set, build a synthetic filter string for FormatTable.
	filter := catalogFilterProject
	if filter == "" {
		filter = catalogFilterType
	}

	// When filters are set manually, just print from the filtered slice directly.
	if catalogFilterLevel >= 0 && filter == "" {
		// Print using FormatDetail-style summary for level filter.
		fmt.Printf("Nodes at autonomy level >= L%d (%d total):\n\n", catalogFilterLevel, len(entries))
		for _, e := range entries {
			ic := "—"
			if e.CurrentIC != nil {
				ic = fmt.Sprintf("%.3f", *e.CurrentIC)
			}
			fmt.Printf("  %-30s  L%d  %-10s  IC=%-8s  %s\n", e.Name, e.AutonomyLevel, e.Project, ic, e.Purpose)
		}
		return nil
	}

	fmt.Printf("Omega Node Catalog — %s\n\n", registry.Summary())
	fmt.Print(registry.FormatTable(filter))
	return nil
}

func nodesCatalogExport(cmd *cobra.Command, args []string) error {
	// Resolve repo root relative to the binary's location. In dev, the binary
	// is typically run from the repo root via `go run ./cmd/omega`, so use the
	// working directory.
	root, err := repoRoot()
	if err != nil {
		return fmt.Errorf("catalog export: %w", err)
	}

	if err := registry.WriteFiles(root); err != nil {
		return err
	}

	fmt.Printf("✓ docs/node_registry.md written\n")
	fmt.Printf("✓ data/node_registry.json written\n")
	fmt.Printf("  %d nodes exported\n", len(registry.Catalog))
	return nil
}

// repoRoot returns the repository root directory. It walks up from the
// executable's source file (available via runtime.Caller) looking for go.mod.
// Falls back to the working directory when not running via `go run`.
func repoRoot() (string, error) {
	// Try working directory first — correct when invoked as `go run ./cmd/omega`
	// or from a built binary placed at the repo root.
	if wd, err := os.Getwd(); err == nil {
		if _, err := os.Stat(filepath.Join(wd, "go.mod")); err == nil {
			return wd, nil
		}
	}
	// Walk up from caller source location (works with `go run`).
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return "", fmt.Errorf("could not determine source location; run from repo root")
	}
	dir := filepath.Dir(file)
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", fmt.Errorf("could not find go.mod — run omega from the repo root")
}
