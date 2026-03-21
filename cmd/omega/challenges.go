package main

import (
	"context"
	"fmt"
	"strings"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/spf13/cobra"
)

var (
	challengeSeverity string
	challengeStatus   string
)

var challengesCmd = &cobra.Command{
	Use:   "challenges",
	Short: "List active DA challenges",
	RunE:  listChallenges,
}

func init() {
	challengesCmd.Flags().StringVar(&challengeSeverity, "severity", "", "Filter by severity: critical, high, medium, low")
	challengesCmd.Flags().StringVar(&challengeStatus, "status", "", "Filter by status: open, resolved, accepted")
}

func listChallenges(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	resp, err := client.GetChallenges(ctx, connect.NewRequest(&omegav1.GetChallengesRequest{
		StatusFilter: challengeStatus,
	}))
	if err != nil {
		return fmt.Errorf("GetChallenges: %w", err)
	}

	challenges := resp.Msg.Challenges

	// Client-side severity filter
	if challengeSeverity != "" {
		filtered := challenges[:0]
		for _, c := range challenges {
			if strings.EqualFold(c.Severity, challengeSeverity) {
				filtered = append(filtered, c)
			}
		}
		challenges = filtered
	}

	if len(challenges) == 0 {
		fmt.Println("No challenges found.")
		return nil
	}

	fmt.Printf("=== Challenges (%d) ===\n", len(challenges))
	for _, c := range challenges {
		created := ""
		if c.CreatedAt != nil {
			created = c.CreatedAt.AsTime().Format("2006-01-02 15:04:05")
		}
		fmt.Printf("  [%-8s] %-10s  subsystem=%-20s  %s\n",
			c.Severity, c.Status, c.TargetSubsystem, created)
		fmt.Printf("           %s\n", c.Description)
		fmt.Println()
	}

	return nil
}
