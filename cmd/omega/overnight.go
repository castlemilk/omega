package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

var (
	overnightBatches   int
	overnightBatchSize int
	overnightMode      string
	overnightConfig    string
)

var overnightCmd = &cobra.Command{
	Use:   "run-overnight",
	Short: "Run the overnight training scheduler (batched Python pipeline)",
	Long: `Launches the Python overnight training scheduler which runs training
in batches of --batch-size cycles, checking PnL and profit factor after
each batch. Pauses with a CRITICAL alert on 2 consecutive negative-PnL batches.

Graceful shutdown: send SIGTERM or touch /tmp/omega_stop.`,
	RunE: runOvernight,
}

func init() {
	overnightCmd.Flags().IntVar(&overnightBatches, "batches", 10, "Number of batches to run")
	overnightCmd.Flags().IntVar(&overnightBatchSize, "batch-size", 200, "Cycles per batch")
	overnightCmd.Flags().StringVar(&overnightMode, "mode", "pico", "Orchestrator mode: pico, supervised, autonomous")
	overnightCmd.Flags().StringVar(&overnightConfig, "config", "", "Path to omega.yml config (optional)")
}

func runOvernight(cmd *cobra.Command, args []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Build Python command args.
	pyArgs := []string{
		"-m", "omega.core.overnight_runner",
		"--batches", strconv.Itoa(overnightBatches),
		"--batch-size", strconv.Itoa(overnightBatchSize),
		"--mode", overnightMode,
	}
	if overnightConfig != "" {
		pyArgs = append(pyArgs, "--config", overnightConfig)
	}

	// Remove any stale stop file before launch.
	stopFile := "/tmp/omega_stop"
	if _, err := os.Stat(stopFile); err == nil {
		fmt.Fprintf(os.Stderr, "warn: removing stale stop file %s\n", stopFile)
		_ = os.Remove(stopFile)
	}

	proc := exec.CommandContext(ctx, "python", pyArgs...) //nolint:gosec // CLI-invoked training runner; pyArgs composed from flags
	proc.Stdout = os.Stdout
	proc.Stderr = os.Stderr

	fmt.Printf(
		"[run-overnight] Starting: %d batch(es) × %d cycles  mode=%s\n",
		overnightBatches, overnightBatchSize, overnightMode,
	)
	fmt.Printf("[run-overnight] Stop anytime: kill -TERM <pid>  or  touch %s\n\n", stopFile)

	if err := proc.Start(); err != nil {
		return fmt.Errorf("failed to start overnight runner: %w", err)
	}

	// Forward SIGTERM/SIGINT to the child process for graceful shutdown.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	waitCh := make(chan error, 1)
	go func() {
		waitCh <- proc.Wait()
	}()

	startTime := time.Now()

	for {
		select {
		case sig := <-sigCh:
			fmt.Printf("\n[run-overnight] Signal %v received — forwarding to overnight runner...\n", sig)
			if proc.Process != nil {
				_ = proc.Process.Signal(sig)
			}
			// Give the child 30s to finish the current cycle gracefully.
			select {
			case err := <-waitCh:
				elapsed := time.Since(startTime)
				fmt.Printf("[run-overnight] Runner exited after %s\n", elapsed.Round(time.Second))
				return normaliseExitErr(err)
			case <-time.After(30 * time.Second):
				fmt.Fprintf(os.Stderr, "[run-overnight] Timeout waiting for graceful shutdown — killing\n")
				_ = proc.Process.Kill()
				<-waitCh
				return fmt.Errorf("overnight runner killed after timeout")
			}

		case err := <-waitCh:
			elapsed := time.Since(startTime)
			fmt.Printf("\n[run-overnight] Runner finished in %s\n", elapsed.Round(time.Second))
			return normaliseExitErr(err)
		}
	}
}

// normaliseExitErr converts a non-zero exit code into an informative error,
// while treating exit 1 (paused/warned) as a non-fatal signal.
func normaliseExitErr(err error) error {
	if err == nil {
		return nil
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		code := exitErr.ExitCode()
		switch code {
		case 1:
			// Overnight runner paused due to consecutive losses — not a crash.
			fmt.Println("[run-overnight] Overnight run paused: check data/overnight_results.json for details.")
			return nil
		default:
			return fmt.Errorf("overnight runner exited with code %d", code)
		}
	}
	return err
}
