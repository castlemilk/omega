package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/spf13/cobra"
)

var (
	runMode     string
	runSymbols  string
	runDryRun   bool
	runInterval int
)

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "Start the Omega orchestrator and poll cycle results",
	RunE:  runOrchestrator,
}

func init() {
	runCmd.Flags().StringVar(&runMode, "mode", "supervised", "Orchestrator mode: pico, supervised, autonomous")
	runCmd.Flags().StringVar(&runSymbols, "symbols", "BTC/USDT,ETH/USDT", "Comma-separated trading symbols")
	runCmd.Flags().BoolVar(&runDryRun, "dry-run", false, "Dry run — start but do not trade")
	runCmd.Flags().IntVar(&runInterval, "interval", 60, "Cycle poll interval in seconds")
}

func runOrchestrator(cmd *cobra.Command, args []string) error {
	client := newOrchestratorClient()
	ctx := context.Background()

	fmt.Printf("Starting Omega orchestrator [mode=%s symbols=%s dry-run=%v]\n", runMode, runSymbols, runDryRun)

	resp, err := client.StartOrchestrator(ctx, connect.NewRequest(&omegav1.StartOrchestratorRequest{
		HeartbeatSecs: int32(runInterval), //nolint:gosec
	}))
	if err != nil {
		return fmt.Errorf("start orchestrator: %w", err)
	}
	fmt.Printf("Orchestrator: %s\n", resp.Msg.Message)
	if !resp.Msg.Started {
		fmt.Println("Orchestrator was already running.")
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(time.Duration(runInterval) * time.Second)
	defer ticker.Stop()

	fmt.Printf("Polling every %ds — press Ctrl+C to stop\n", runInterval)

	for {
		select {
		case <-sigCh:
			fmt.Println("\nShutting down orchestrator...")
			stopResp, err := client.StopOrchestrator(ctx, connect.NewRequest(&omegav1.StopOrchestratorRequest{}))
			if err != nil {
				fmt.Fprintf(os.Stderr, "stop orchestrator: %v\n", err)
			} else {
				fmt.Printf("Orchestrator: %s\n", stopResp.Msg.Message)
			}
			return nil

		case <-ticker.C:
			hb, err := client.TriggerHeartbeat(ctx, connect.NewRequest(&omegav1.TriggerHeartbeatRequest{}))
			if err != nil {
				fmt.Fprintf(os.Stderr, "heartbeat error: %v\n", err)
				continue
			}
			fmt.Printf("[%s] heartbeat: %s\n", time.Now().Format("15:04:05"), hb.Msg.Message)

			health, err := client.GetHealth(ctx, connect.NewRequest(&omegav1.GetHealthRequest{}))
			if err != nil {
				fmt.Fprintf(os.Stderr, "health check error: %v\n", err)
				continue
			}
			h := health.Msg.Health
			fmt.Printf("  status=%-10s score=%.3f nodes=%d cycles=%d open_issues=%d\n",
				h.Status, h.CompositeScore, h.NodeCount, h.TotalCycles, h.OpenIssues)
		}
	}
}
