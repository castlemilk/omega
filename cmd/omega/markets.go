package main

import (
	"context"
	"fmt"
	"strings"

	"github.com/benebsworth/omega/internal/polymarket"
	"github.com/spf13/cobra"
)

var marketsCmd = &cobra.Command{
	Use:   "markets",
	Short: "Polymarket prediction market data",
}

var marketsListCmd = &cobra.Command{
	Use:   "list",
	Short: "List active Polymarket markets",
	RunE:  marketsList,
}

var marketsListCategory string
var marketsListLimit int

func init() {
	marketsCmd.AddCommand(marketsListCmd)
	marketsListCmd.Flags().StringVar(&marketsListCategory, "category", "", "Filter by category (e.g. politics, crypto, sports)")
	marketsListCmd.Flags().IntVar(&marketsListLimit, "limit", 20, "Maximum number of markets to return")
}

func marketsList(_ *cobra.Command, _ []string) error {
	client := polymarket.NewClient(
		polymarket.WithCacheTTL(30*1e9), // 30s cache
	)

	active := true
	opts := &polymarket.MarketQuery{
		Active:   &active,
		Limit:    marketsListLimit,
		Category: marketsListCategory,
	}

	markets, err := client.GetMarkets(context.Background(), opts)
	if err != nil {
		return fmt.Errorf("polymarket: %w", err)
	}

	if len(markets) == 0 {
		fmt.Println("No active markets found.")
		return nil
	}

	fmt.Printf("%-60s  %12s  %8s  %8s\n", "QUESTION", "VOLUME", "YES", "NO")
	fmt.Println(strings.Repeat("-", 96))

	for _, m := range markets {
		yes, no := parsePrices(m)
		question := m.Question
		if len(question) > 58 {
			question = question[:55] + "..."
		}
		fmt.Printf("%-60s  %12.0f  %8.3f  %8.3f\n",
			question,
			m.VolumeNum,
			yes,
			no,
		)
	}

	return nil
}

// parsePrices extracts YES/NO prices from OutcomePrices.
// OutcomePrices is a slice of stringified floats parallel to Outcomes.
func parsePrices(m polymarket.Market) (yes, no float64) {
	for i, outcome := range m.Outcomes {
		if i >= len(m.OutcomePrices) {
			break
		}
		var price float64
		_, _ = fmt.Sscanf(m.OutcomePrices[i], "%f", &price)
		switch strings.ToLower(outcome) {
		case "yes":
			yes = price
		case "no":
			no = price
		}
	}
	return
}
