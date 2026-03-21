package main

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strings"
	"time"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/spf13/cobra"
)

var (
	btStartDate string
	btEndDate   string
	btSymbols   string
	btOutput    string
)

var backtestCmd = &cobra.Command{
	Use:   "backtest",
	Short: "Run a backtest over historical cycles",
	RunE:  runBacktest,
}

func init() {
	backtestCmd.Flags().StringVar(&btStartDate, "start-date", "", "Start date (YYYY-MM-DD)")
	backtestCmd.Flags().StringVar(&btEndDate, "end-date", "", "End date (YYYY-MM-DD)")
	backtestCmd.Flags().StringVar(&btSymbols, "symbols", "BTC/USDT,ETH/USDT", "Comma-separated symbols")
	backtestCmd.Flags().StringVar(&btOutput, "output", "", "Write results JSON to this path")
}

type BacktestResult struct {
	Symbols    []string  `json:"symbols"`
	StartDate  string    `json:"start_date"`
	EndDate    string    `json:"end_date"`
	Cycles     int       `json:"cycles"`
	WinRate    float64   `json:"win_rate"`
	Sharpe     float64   `json:"sharpe"`
	MaxDrawdown float64  `json:"max_drawdown"`
	AvgLatency float64   `json:"avg_latency_ms"`
	RunAt      time.Time `json:"run_at"`
}

func runBacktest(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	symbols := strings.Split(btSymbols, ",")
	fmt.Printf("Running backtest  symbols=%v  start=%s  end=%s\n", symbols, btStartDate, btEndDate)

	// Fetch convergence history as proxy for cycle performance data
	convResp, err := client.GetConvergence(ctx, connect.NewRequest(&omegav1.GetConvergenceRequest{Limit: 500}))
	if err != nil {
		return fmt.Errorf("GetConvergence: %w", err)
	}

	points := convResp.Msg.Points
	if len(points) == 0 {
		fmt.Println("No convergence data found — nothing to backtest.")
		return nil
	}

	// Filter by date range if provided
	var start, end time.Time
	if btStartDate != "" {
		t, err := time.Parse("2006-01-02", btStartDate)
		if err != nil {
			return fmt.Errorf("invalid --start-date: %w", err)
		}
		start = t
	}
	if btEndDate != "" {
		t, err := time.Parse("2006-01-02", btEndDate)
		if err != nil {
			return fmt.Errorf("invalid --end-date: %w", err)
		}
		end = t.Add(24 * time.Hour)
	}

	var filtered []*omegav1.ConvergencePoint
	for _, p := range points {
		if p.Timestamp == nil {
			filtered = append(filtered, p)
			continue
		}
		ts := p.Timestamp.AsTime()
		if !start.IsZero() && ts.Before(start) {
			continue
		}
		if !end.IsZero() && ts.After(end) {
			continue
		}
		filtered = append(filtered, p)
	}

	if len(filtered) == 0 {
		fmt.Println("No cycles found in the specified date range.")
		return nil
	}

	// Compute summary stats from convergence scores
	var scores []float64
	var totalLatency float64
	wins := 0
	for _, p := range filtered {
		scores = append(scores, p.Score)
		totalLatency += p.PipelineMs
		if p.Score > 0.5 {
			wins++
		}
	}

	n := float64(len(scores))
	mean := 0.0
	for _, s := range scores {
		mean += s
	}
	mean /= n

	variance := 0.0
	for _, s := range scores {
		d := s - mean
		variance += d * d
	}
	variance /= n
	stddev := math.Sqrt(variance)

	sharpe := 0.0
	if stddev > 0 {
		sharpe = mean / stddev
	}

	// Max drawdown from score series
	peak := scores[0]
	maxDD := 0.0
	for _, s := range scores {
		if s > peak {
			peak = s
		}
		dd := (peak - s) / peak
		if dd > maxDD {
			maxDD = dd
		}
	}

	result := BacktestResult{
		Symbols:     symbols,
		StartDate:   btStartDate,
		EndDate:     btEndDate,
		Cycles:      len(filtered),
		WinRate:     float64(wins) / n,
		Sharpe:      sharpe,
		MaxDrawdown: maxDD,
		AvgLatency:  totalLatency / n,
		RunAt:       time.Now(),
	}

	fmt.Printf("\n=== Backtest Results ===\n")
	fmt.Printf("  Cycles analyzed: %d\n", result.Cycles)
	fmt.Printf("  Win rate:        %.1f%%\n", result.WinRate*100)
	fmt.Printf("  Sharpe ratio:    %.4f\n", result.Sharpe)
	fmt.Printf("  Max drawdown:    %.2f%%\n", result.MaxDrawdown*100)
	fmt.Printf("  Avg latency:     %.1fms\n", result.AvgLatency)

	if btOutput != "" {
		f, err := os.Create(btOutput) //nolint:gosec
		if err != nil {
			return fmt.Errorf("create output file: %w", err)
		}
		defer func() { _ = f.Close() }()
		enc := json.NewEncoder(f)
		enc.SetIndent("", "  ")
		if err := enc.Encode(result); err != nil {
			return fmt.Errorf("encode results: %w", err)
		}
		fmt.Printf("\nResults written to %s\n", btOutput)
	}

	return nil
}
