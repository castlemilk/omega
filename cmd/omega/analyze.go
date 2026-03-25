package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/brain"
	"github.com/spf13/cobra"
)

var analyzeCmd = &cobra.Command{
	Use:   "analyze",
	Short: "Use LLM to interpret current system state and signal health",
	Long: `Reads health score, signal state, and recent cycle results from the API,
then calls the brain (DEEP tier) to produce a human-readable analysis.

Requires ANTHROPIC_API_KEY to be set. Falls back to a plain status dump if the
key is missing.`,
	RunE: runAnalyze,
}

func init() {
	rootCmd.AddCommand(analyzeCmd)
}

func runAnalyze(cmd *cobra.Command, args []string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	client := newOrchestratorClient()
	apiURL := getAPIURL()

	// ── Gather state ──────────────────────────────────────────────────────────
	healthResp, err := client.GetHealth(ctx, connect.NewRequest(&omegav1.GetHealthRequest{}))
	if err != nil {
		return fmt.Errorf("GetHealth: %w", err)
	}
	nodesResp, err := client.ListNodes(ctx, connect.NewRequest(&omegav1.ListNodesRequest{}))
	if err != nil {
		return fmt.Errorf("ListNodes: %w", err)
	}
	cycleResp, _ := client.GetLastCycleResult(ctx, connect.NewRequest(&omegav1.GetLastCycleResultRequest{}))

	// Grab Prometheus health score text
	promScore := fetchPrometheusScore(apiURL)

	// ── Build summary for the LLM ─────────────────────────────────────────────
	h := healthResp.Msg.Health
	var sb strings.Builder
	fmt.Fprintf(&sb, "=== Omega System State ===\n")
	fmt.Fprintf(&sb, "Status: %s  CompositeScore: %.3f  AvgNodeHealth: %.3f\n",
		h.Status, h.CompositeScore, h.AvgNodeHealth)
	fmt.Fprintf(&sb, "Nodes: %d  TotalCycles: %d  OpenIssues: %d (errors: %d)\n",
		h.NodeCount, h.TotalCycles, h.OpenIssues, h.ErrorIssues)
	if promScore != "" {
		fmt.Fprintf(&sb, "Prometheus health_score: %s\n", promScore)
	}

	fmt.Fprintf(&sb, "\n=== Node Status ===\n")
	for _, n := range nodesResp.Msg.Nodes {
		fmt.Fprintf(&sb, "  %-30s  status=%-10s  health=%.3f  execs=%d  err_rate=%.2f%%  p95=%.1fms\n",
			n.Name, n.Status, n.Health, n.ExecutionsTotal, n.ErrorRate*100, n.P95LatencyMs)
	}

	if cycleResp != nil && cycleResp.Msg.HasResult {
		fmt.Fprintf(&sb, "\n=== Last Cycle (cycle %d, %.0fms) ===\n",
			cycleResp.Msg.Cycle, cycleResp.Msg.TotalDurationMs)
		for _, s := range cycleResp.Msg.StepResults {
			status := "ok"
			detail := fmt.Sprintf("%.0fms", s.DurationMs)
			if !s.Success {
				status = "FAIL"
				detail = s.Error
			}
			fmt.Fprintf(&sb, "  %-30s  %s  (%s)\n", s.Name, status, detail)
		}
	}

	stateSummary := sb.String()

	// ── Print raw state ───────────────────────────────────────────────────────
	fmt.Print(stateSummary)

	// ── LLM analysis ─────────────────────────────────────────────────────────
	b := brain.New()
	if !b.IsAvailable() {
		fmt.Println("\n[brain] ANTHROPIC_API_KEY not set — skipping LLM analysis.")
		return nil
	}

	prompt := fmt.Sprintf(`You are an expert in algorithmic trading systems and AI orchestration.
Below is the current runtime state of the Omega crypto signal pipeline:

%s

Provide a concise analysis (3-5 bullet points) covering:
1. Overall system health and any concerns
2. Signal pipeline performance (latency, error rates)
3. Whether the current regime suggests opportunity or caution
4. One concrete recommendation to improve performance or reduce risk

Be specific and data-driven. Use the numbers provided.`, stateSummary)

	fmt.Println("\n=== LLM Analysis (DEEP) ===")
	fmt.Println("Consulting brain...")

	analysis, err := b.Consult(ctx, prompt, brain.DEEP)
	if err != nil {
		return fmt.Errorf("brain consult: %w", err)
	}

	fmt.Println(analysis)
	return nil
}

// fetchPrometheusScore grabs the omega_health_score value from /metrics.
func fetchPrometheusScore(baseURL string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/metrics", nil)
	if err != nil {
		return ""
	}
	resp, err := http.DefaultClient.Do(req) //nolint:gosec // URL is operator-controlled API base
	if err != nil {
		return ""
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(resp.Body)
	for _, line := range strings.Split(string(body), "\n") {
		if strings.HasPrefix(line, "omega_health_score ") {
			parts := strings.Fields(line)
			if len(parts) >= 2 {
				return parts[1]
			}
		}
	}
	return ""
}
