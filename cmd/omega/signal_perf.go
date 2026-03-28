package main

import (
	"fmt"
	"sort"

	"github.com/spf13/cobra"
)

var signalPerfCmd = &cobra.Command{
	Use:   "signal-perf",
	Short: "Show signal performance leaderboard (IC, hit-rate, value-added, stability)",
	Long: `Queries the signal_performance table written by the Python SignalPerformanceTracker
and prints a ranked leaderboard of all tracked signals.

Columns
  Signal      signal name
  Composite   weighted score: 0.4*|IC| + 0.3*HitRate + 0.2*Stability + 0.1*VA
  IC          information coefficient (Pearson correlation with forward return)
  HitRate     % cycles where signal direction matched a profitable trade
  ValueAdded  PnL contribution vs flat (equal-weight) portfolio baseline
  Stability   lag-1 autocorrelation [0,1]; high = persistent, low = noisy
  Cycle       most recent cycle number this row was computed for`,
	RunE: showSignalPerf,
}

func showSignalPerf(cmd *cobra.Command, args []string) error {
	sqlDB, vdb, err := openVictoriaDB()
	if err != nil {
		return fmt.Errorf("postgres: %w", err)
	}
	defer sqlDB.Close() //nolint:errcheck,gosec

	rows, err := vdb.GetSignalPerformance()
	if err != nil {
		return fmt.Errorf("GetSignalPerformance: %w", err)
	}

	if len(rows) == 0 {
		fmt.Println("No signal performance data found.")
		fmt.Println("Run at least one training cycle to populate signal_performance.")
		return nil
	}

	// Sort by composite_score descending
	sort.Slice(rows, func(i, j int) bool {
		return rows[i].CompositeScore > rows[j].CompositeScore
	})

	// Compute average quality for the footer
	var totalComposite float64
	for _, r := range rows {
		totalComposite += r.CompositeScore
	}
	avgQuality := totalComposite / float64(len(rows))

	// Header
	fmt.Printf("\n%-24s  %-9s  %-8s  %-8s  %-12s  %-9s  %s\n",
		"Signal", "Composite", "IC", "HitRate", "ValueAdded", "Stability", "Cycle")
	fmt.Println("────────────────────────────────────────────────────────────────────────────────────────")

	for rank, r := range rows {
		medal := "  "
		switch rank {
		case 0:
			medal = "🥇"
		case 1:
			medal = "🥈"
		case 2:
			medal = "🥉"
		}
		// Fallback to plain markers when terminal doesn't support emoji
		if medal != "  " {
			_ = medal // used below
		}

		icStr := colorFloat(r.IC, 4)
		hrStr := fmt.Sprintf("%.3f", r.HitRate)
		vaStr := colorValueAdded(r.ValueAdded)
		stabStr := fmt.Sprintf("%.3f", r.Stability)
		compStr := fmt.Sprintf("%.4f", r.CompositeScore)

		fmt.Printf("%-24s  %-9s  %-8s  %-8s  %-12s  %-9s  %d\n",
			r.SignalName, compStr, icStr, hrStr, vaStr, stabStr, r.Cycle)
	}

	fmt.Println("────────────────────────────────────────────────────────────────────────────────────────")
	fmt.Printf("Total: %d signals  |  avg composite: %.4f  |  ensemble quality: %.1f%%\n",
		len(rows), avgQuality, avgQuality*200)
	fmt.Println()
	return nil
}

// colorFloat formats a float with sign for display in a terminal-friendly way.
func colorFloat(v float64, decimals int) string {
	format := fmt.Sprintf("%+.%df", decimals)
	return fmt.Sprintf(format, v)
}

// colorValueAdded formats value_added with a + prefix for positive values.
func colorValueAdded(v float64) string {
	if v >= 0 {
		return fmt.Sprintf("+%.4f", v)
	}
	return fmt.Sprintf("%.4f", v)
}
