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

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/bridge"
	"github.com/spf13/cobra"

	_ "github.com/jackc/pgx/v5/stdlib"
)

var (
	trainCycles int
	trainSleep  time.Duration
)

var trainCmd = &cobra.Command{
	Use:   "train",
	Short: "Run Victoria training cycles via the Python pipeline bridge",
	Long: `Start the Python bridge server (if not already running), then drive
--cycles training cycles, sleeping --sleep between each one.
Progress is streamed to stdout and persisted to data/training_progress.json.
Press Ctrl+C to stop early; a summary table is always printed at the end.`,
	RunE: runTrain,
}

func init() {
	trainCmd.Flags().IntVar(&trainCycles, "cycles", 100, "Number of training cycles to run")
	trainCmd.Flags().DurationVar(&trainSleep, "sleep", 30*time.Second, "Sleep between cycles")
}

// trainProgress is the JSON structure written to data/training_progress.json.
type trainProgress struct {
	StartedAt        string             `json:"started_at"`
	CyclesTotal      int                `json:"cycles_total"`
	CyclesCompleted  int                `json:"cycles_completed"`
	LastMetrics      map[string]float64 `json:"last_metrics,omitempty"`
	CompletedAt      string             `json:"completed_at,omitempty"`
	InterruptedAt    string             `json:"interrupted_at,omitempty"`
}

func runTrain(cmd *cobra.Command, args []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Intercept SIGINT / SIGTERM so we can flush progress before exit.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	bridgeClient := bridge.NewPipelineClient("")
	bridgeProc, err := ensurePythonBridge(ctx, bridgeClient)
	if err != nil {
		return fmt.Errorf("python bridge: %w", err)
	}
	if bridgeProc != nil {
		defer func() {
			bridgeProc.Process.Kill() //nolint:errcheck,gosec
			bridgeProc.Wait()        //nolint:errcheck,gosec
		}()
	}

	progress := &trainProgress{
		StartedAt:   time.Now().UTC().Format(time.RFC3339),
		CyclesTotal: trainCycles,
	}
	if err := saveProgress(progress); err != nil {
		fmt.Fprintf(os.Stderr, "warn: could not write progress file: %v\n", err)
	}

	fmt.Printf("Training: %d cycles, %s sleep between each\n\n", trainCycles, trainSleep)

	overallStart := time.Now()
	interrupted := false

loop:
	for i := range trainCycles {
		select {
		case <-sigCh:
			interrupted = true
			break loop
		default:
		}

		cycleNum := int64(i + 1)
		cycleStart := time.Now()
		fmt.Printf("[%s] cycle %d/%d  ", time.Now().Format("15:04:05"), cycleNum, trainCycles)

		resp, err := bridgeClient.ExecuteStep(ctx, &omegav1.ExecuteStepRequest{
			StepId:    fmt.Sprintf("train_%d", cycleNum),
			StepName:  "TrainingCycle",
			NodeType:  "VICTORIA",
			Cycle:     cycleNum,
		})
		switch {
		case err != nil:
			fmt.Printf("ERROR: %v\n", err)
		case !resp.Success:
			fmt.Printf("FAIL: %s  (%.0fms)\n", resp.ErrorText, resp.DurationMs)
		default:
			fmt.Printf("ok  (%.0fms)", resp.DurationMs)
			if len(resp.Metrics) > 0 {
				fmt.Printf("  metrics:")
				for k, v := range resp.Metrics {
					fmt.Printf(" %s=%.4f", k, v)
				}
				progress.LastMetrics = resp.Metrics
			}
			fmt.Println()
		}

		progress.CyclesCompleted = i + 1
		if err := saveProgress(progress); err != nil {
			fmt.Fprintf(os.Stderr, "warn: progress write: %v\n", err)
		}

		elapsed := time.Since(cycleStart)
		remaining := trainSleep - elapsed
		if remaining > 0 && i < trainCycles-1 {
			select {
			case <-sigCh:
				interrupted = true
				break loop
			case <-time.After(remaining):
			}
		}
	}

	// Mark completion in progress file.
	now := time.Now().UTC().Format(time.RFC3339)
	if interrupted {
		progress.InterruptedAt = now
		fmt.Printf("\n\nInterrupted after %d/%d cycles (%.0fs elapsed)\n",
			progress.CyclesCompleted, trainCycles, time.Since(overallStart).Seconds())
	} else {
		progress.CompletedAt = now
		fmt.Printf("\n\nCompleted %d cycles in %.0fs\n",
			trainCycles, time.Since(overallStart).Seconds())
	}
	if err := saveProgress(progress); err != nil {
		fmt.Fprintf(os.Stderr, "warn: final progress write: %v\n", err)
	}

	printTrainSummary()
	return nil
}

// ensurePythonBridge pings the bridge and, if unreachable, starts it as a
// subprocess. Returns the *exec.Cmd when a new process was started (nil if
// already running). Blocks until the bridge responds or times out.
func ensurePythonBridge(ctx context.Context, client *bridge.PipelineClient) (*exec.Cmd, error) {
	if ok, _ := client.Ping(ctx); ok {
		fmt.Printf("Python bridge already running at %s\n", client.Addr())
		return nil, nil
	}

	fmt.Printf("Starting Python bridge at %s...\n", client.Addr())
	proc := exec.CommandContext(ctx, "python", "-m", "omega.bridge.server_main")
	proc.Stdout = os.Stderr
	proc.Stderr = os.Stderr
	if err := proc.Start(); err != nil {
		return nil, fmt.Errorf("start python -m omega.bridge.server_main: %w", err)
	}

	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		time.Sleep(500 * time.Millisecond)
		if ok, _ := client.Ping(ctx); ok {
			fmt.Printf("Bridge ready.\n")
			return proc, nil
		}
	}
	proc.Process.Kill() //nolint:errcheck,gosec
	return nil, fmt.Errorf("python bridge did not become ready within 30s")
}

// saveProgress marshals progress to data/training_progress.json.
func saveProgress(p *trainProgress) error {
	if err := os.MkdirAll("data", 0o750); err != nil {
		return err
	}
	b, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile("data/training_progress.json", b, 0o600)
}

// printTrainSummary opens Postgres and prints a summary table of trade stats.
func printTrainSummary() {
	sqlDB, vdb, err := openVictoriaDB()
	if err != nil {
		fmt.Fprintf(os.Stderr, "\nwarn: could not connect to postgres for summary (%v)\n", err)
		return
	}
	defer sqlDB.Close() //nolint:errcheck,gosec

	fmt.Printf("\n=== Training Summary ===\n")

	pnl, err := vdb.GetPnL()
	if err == nil {
		fmt.Printf("  PnL (realised):   $%.2f\n", pnl.RealisedPnL)
		fmt.Printf("  Win rate:         %.1f%%\n", pnl.WinRate*100)
		fmt.Printf("  Sharpe:           %.3f\n", pnl.Sharpe)
		fmt.Printf("  Max drawdown:     %.1f%%\n", pnl.MaxDD*100)
		fmt.Printf("  Ann. return:      %.1f%%\n", pnl.AnnReturn*100)
	}

	trades, err := vdb.GetTrades("", "", 1000)
	if err == nil {
		fmt.Printf("  Total trades:     %d\n", len(trades))
	}

	signals, err := vdb.GetSignals()
	if err == nil {
		active := 0
		for _, s := range signals {
			if s.CurrentValue != 0 {
				active++
			}
		}
		fmt.Printf("  Active signals:   %d / %d\n", active, len(signals))
	}
}
