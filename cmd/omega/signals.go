package main

import (
	"fmt"
	"sort"

	"github.com/spf13/cobra"
)

var signalsCmd = &cobra.Command{
	Use:   "signals",
	Short: "List active signals sorted by IC descending",
	RunE:  showSignals,
}

func showSignals(cmd *cobra.Command, args []string) error {
	sqlDB, vdb, err := openVictoriaDB()
	if err != nil {
		return fmt.Errorf("postgres: %w", err)
	}
	defer sqlDB.Close() //nolint:errcheck,gosec

	signals, err := vdb.GetSignals()
	if err != nil {
		return fmt.Errorf("GetSignals: %w", err)
	}

	// Sort by AvgIC descending.
	sort.Slice(signals, func(i, j int) bool {
		return signals[i].AvgIC > signals[j].AvgIC
	})

	if len(signals) == 0 {
		fmt.Println("No signals found in postgres.")
		return nil
	}

	fmt.Printf("%-32s  %-10s  %-10s  %-14s  %-6s\n",
		"Signal", "IC", "Weight", "Last Value", "Trend")
	fmt.Printf("%s\n", "──────────────────────────────────────────────────────────────────────────────")
	for _, s := range signals {
		trend := s.Trend
		if trend == "" {
			trend = "—"
		}
		fmt.Printf("%-32s  %-10.4f  %-10.4f  %-14.6f  %s\n",
			s.Name, s.AvgIC, s.Weight, s.CurrentValue, trend)
	}
	fmt.Printf("\nTotal: %d signals\n", len(signals))
	return nil
}
