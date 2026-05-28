package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

// trainRouterCmd trains the AttentionRouter. Help text includes a dev-only default
// Postgres URL with placeholder credentials; suppressing G101 (false positive).
//
//nolint:gosec // G101: placeholder credentials in help-text default URL
var trainRouterCmd = &cobra.Command{
	Use:   "train-router",
	Short: "Train the AttentionRouter from coordination outcome history",
	Long: `Reads coordination_outcomes from Postgres, computes per-node EMA quality
weights, and writes data/router_weights.json that the Go router loads on startup.

Runs scripts/train_router.py via the Python bridge. Requires DATABASE_URL to be
set (or defaults to postgresql://omega:omega@localhost:5432/omega).

After training, the weights file is summarised on stdout.`,
	RunE: runTrainRouter,
}

func init() {
	rootCmd.AddCommand(trainRouterCmd)
}

func runTrainRouter(cmd *cobra.Command, args []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		fmt.Fprintln(os.Stderr, "\nInterrupted.")
		cancel()
	}()

	script := "scripts/train_router.py"
	if _, err := os.Stat(script); err != nil {
		return fmt.Errorf("cannot find %s — run omega from the repo root", script)
	}

	fmt.Println("Training AttentionRouter from coordination outcome history...")
	fmt.Println()

	proc := exec.CommandContext(ctx, "python3", script)
	proc.Stdout = os.Stdout
	proc.Stderr = os.Stderr
	proc.Env = os.Environ()

	if err := proc.Run(); err != nil {
		if ctx.Err() != nil {
			return nil // interrupted by user
		}
		return fmt.Errorf("train_router.py: %w", err)
	}

	printRouterWeightsSummary()
	return nil
}

// printRouterWeightsSummary reads data/router_weights.json and prints a table.
func printRouterWeightsSummary() {
	data, err := os.ReadFile("data/router_weights.json")
	if err != nil {
		// Script already printed its own output; nothing more to do.
		return
	}

	var weights struct {
		TrainedAt   string             `json:"trained_at"`
		NOutcomes   int                `json:"n_outcomes"`
		NodeWeights map[string]float64 `json:"node_weights"`
		GoalTypeBias []float64         `json:"goal_type_bias"`
		Meta        struct {
			NFailures     int     `json:"n_failures"`
			MeanQuality   float64 `json:"mean_quality"`
			MedianQuality float64 `json:"median_quality"`
			NNodes        int     `json:"n_nodes"`
		} `json:"meta"`
		NodeStats map[string]struct {
			EMA  float64 `json:"ema"`
			N    int     `json:"n"`
			Mean float64 `json:"mean"`
		} `json:"node_stats"`
	}
	if err := json.Unmarshal(data, &weights); err != nil {
		return
	}

	ts := weights.TrainedAt
	if t, err := time.Parse(time.RFC3339, ts); err == nil {
		ts = t.Local().Format("2006-01-02 15:04:05")
	}

	fmt.Printf("\n=== AttentionRouter Weights Summary ===\n")
	fmt.Printf("  Trained at:   %s\n", ts)
	fmt.Printf("  Outcomes:     %d  (failures: %d)\n", weights.NOutcomes, weights.Meta.NFailures)
	fmt.Printf("  Mean quality: %.4f  median: %.4f\n", weights.Meta.MeanQuality, weights.Meta.MedianQuality)
	fmt.Printf("  Nodes:        %d\n", weights.Meta.NNodes)

	if len(weights.NodeStats) > 0 {
		fmt.Printf("\n  %-30s  %7s  %5s  %7s\n", "Node", "EMA", "N", "Mean")
		fmt.Printf("  %s\n", repeat("-", 56))

		// Sort by EMA descending using a simple approach
		type nodeRow struct {
			name string
			ema  float64
			n    int
			mean float64
		}
		var rows []nodeRow
		for name, stats := range weights.NodeStats {
			rows = append(rows, nodeRow{name, stats.EMA, stats.N, stats.Mean})
		}
		// Bubble sort (small N, keeps deps minimal)
		for i := range rows {
			for j := i + 1; j < len(rows); j++ {
				if rows[j].ema > rows[i].ema {
					rows[i], rows[j] = rows[j], rows[i]
				}
			}
		}
		for _, r := range rows {
			bar := ""
			filled := int(r.ema * 20)
			for k := 0; k < filled; k++ {
				bar += "█"
			}
			fmt.Printf("  %-30s  %7.4f  %5d  %7.4f  %s\n", r.name, r.ema, r.n, r.mean, bar)
		}
	}

	if len(weights.GoalTypeBias) > 0 {
		fmt.Printf("\n  GoalType bias (0-4): %v\n", weights.GoalTypeBias)
	}

	fmt.Printf("\n  Saved → data/router_weights.json\n")
}
