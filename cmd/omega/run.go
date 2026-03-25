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
	runCycles   int
)

var cycleCmd = &cobra.Command{
	Use:   "cycle",
	Short: "Start the Omega orchestrator and poll cycle results",
	RunE:  runOrchestrator,
}

func init() {
	cycleCmd.Flags().StringVar(&runMode, "mode", "supervised", "Orchestrator mode: pico, supervised, autonomous")
	cycleCmd.Flags().StringVar(&runSymbols, "symbols", "BTC/USDT,ETH/USDT", "Comma-separated trading symbols")
	cycleCmd.Flags().BoolVar(&runDryRun, "dry-run", false, "Dry run — start but do not trade")
	cycleCmd.Flags().IntVar(&runInterval, "interval", 60, "Cycle poll interval in seconds")
	cycleCmd.Flags().IntVar(&runCycles, "cycles", 0, "Run N cycles synchronously and print per-step results, then exit")
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

	// --cycles N: run N cycles synchronously, print per-step results, then exit.
	if runCycles > 0 {
		return runNCycles(ctx, client, runCycles)
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

// runNCycles triggers exactly n synchronous cycles and prints per-step results.
func runNCycles(ctx context.Context, client interface {
	TriggerHeartbeat(context.Context, *connect.Request[omegav1.TriggerHeartbeatRequest]) (*connect.Response[omegav1.TriggerHeartbeatResponse], error)
}, n int) error {
	fmt.Printf("Running %d cycle(s)...\n\n", n)
	overallStart := time.Now()

	for i := range n {
		cycleStart := time.Now()
		fmt.Printf("── Cycle %d/%d ─────────────────────────────────────────────────\n", i+1, n)

		hb, err := client.TriggerHeartbeat(ctx, connect.NewRequest(&omegav1.TriggerHeartbeatRequest{}))
		if err != nil {
			fmt.Fprintf(os.Stderr, "  cycle %d error: %v\n", i+1, err)
			continue
		}
		// Message already contains per-step lines formatted by TriggerHeartbeat.
		fmt.Println(hb.Msg.Message)
		fmt.Printf("  wall time: %.0fms\n", float64(time.Since(cycleStart).Milliseconds()))
		fmt.Println()
	}

	fmt.Printf("═══════════════════════════════════════════════════════════════\n")
	fmt.Printf("Total: %d cycle(s) in %.0fms\n", n, float64(time.Since(overallStart).Milliseconds()))
	return nil
}
