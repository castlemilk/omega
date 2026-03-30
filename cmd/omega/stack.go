package main

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

var stackNoFrontend bool

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "Start the full Omega stack (API + bridge + frontend)",
	Long: `Start all three layers of the Omega stack as managed subprocesses:

  [bridge]   Python pipeline server   — port 9090
  [api]      Go Connect-RPC API       — port 8080
  [frontend] React dev server         — port 5173

Each layer's stdout/stderr is prefixed with its label. SIGINT or SIGTERM
terminates all subprocesses gracefully.`,
	RunE: runStack,
}

func init() {
	runCmd.Flags().BoolVar(&stackNoFrontend, "no-frontend", false, "Start only API + bridge (skip the React dev server)")
}

// prefixLines reads lines from r and writes them to w with a label prefix.
// Runs until r is closed; intended to be called in a goroutine.
func prefixLines(label string, r io.Reader, w io.Writer) {
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		fmt.Fprintf(w, "%s %s\n", label, scanner.Text()) //nolint:errcheck,gosec
	}
}

func runStack(_ *cobra.Command, _ []string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		fmt.Fprintln(os.Stderr, "\nShutting down Omega stack…")
		cancel()
	}()

	env := os.Environ()
	errCh := make(chan error, 3)

	var procs []*exec.Cmd

	// ── Python bridge ──────────────────────────────────────────────────────────
	bridgeLabel := "\033[36m[bridge]\033[0m"
	fmt.Printf("%s starting Python pipeline server on :9090…\n", bridgeLabel)
	bridgeCmd := exec.CommandContext(ctx, "python3", "-m", "omega.bridge.server_main")
	bridgeCmd.Env = append(append([]string{}, env...), "OMEGA_PIPELINE_PORT=9090")
	bridgeOut, _ := bridgeCmd.StdoutPipe()
	bridgeErr, _ := bridgeCmd.StderrPipe()
	if err := bridgeCmd.Start(); err != nil {
		return fmt.Errorf("start bridge: %w", err)
	}
	procs = append(procs, bridgeCmd)
	go prefixLines(bridgeLabel, bridgeOut, os.Stdout)
	go prefixLines(bridgeLabel, bridgeErr, os.Stderr)
	go func() {
		if err := bridgeCmd.Wait(); err != nil && ctx.Err() == nil {
			errCh <- fmt.Errorf("bridge exited unexpectedly: %w", err)
		}
	}()

	if err := waitHTTP(ctx, "http://localhost:9090/health", 30*time.Second, bridgeLabel); err != nil {
		fmt.Printf("%s not ready (%v) — continuing anyway\n", bridgeLabel, err)
	} else {
		fmt.Printf("%s ready\n", bridgeLabel)
	}

	// ── Go API ─────────────────────────────────────────────────────────────────
	apiLabel := "\033[32m[api]\033[0m"
	fmt.Printf("%s starting Go API server on :8080…\n", apiLabel)
	apiCmd := exec.CommandContext(ctx, "go", "run", "./cmd/omega-api")
	apiCmd.Env = append(append([]string{}, env...), "OMEGA_PYTHON_PIPELINE_ADDR=http://localhost:9090")
	apiOut, _ := apiCmd.StdoutPipe()
	apiErr, _ := apiCmd.StderrPipe()
	if err := apiCmd.Start(); err != nil {
		cancel()
		killAll(procs)
		return fmt.Errorf("start api: %w", err)
	}
	procs = append(procs, apiCmd)
	go prefixLines(apiLabel, apiOut, os.Stdout)
	go prefixLines(apiLabel, apiErr, os.Stderr)
	go func() {
		if err := apiCmd.Wait(); err != nil && ctx.Err() == nil {
			errCh <- fmt.Errorf("api exited unexpectedly: %w", err)
		}
	}()

	if err := waitHTTP(ctx, "http://localhost:8080/healthz", 90*time.Second, apiLabel); err != nil {
		fmt.Printf("%s not ready (%v) — continuing anyway\n", apiLabel, err)
	} else {
		fmt.Printf("%s ready\n", apiLabel)
	}

	// ── React frontend ─────────────────────────────────────────────────────────
	if !stackNoFrontend {
		feLabel := "\033[35m[frontend]\033[0m"
		fmt.Printf("%s starting React dev server on :5173…\n", feLabel)
		feCmd := exec.CommandContext(ctx, "npm", "run", "dev")
		feCmd.Dir = "dashboard"
		feCmd.Env = env
		feOut, _ := feCmd.StdoutPipe()
		feErr, _ := feCmd.StderrPipe()
		if err := feCmd.Start(); err != nil {
			cancel()
			killAll(procs)
			return fmt.Errorf("start frontend: %w", err)
		}
		procs = append(procs, feCmd)
		go prefixLines(feLabel, feOut, os.Stdout)
		go prefixLines(feLabel, feErr, os.Stderr)
		go func() {
			if err := feCmd.Wait(); err != nil && ctx.Err() == nil {
				errCh <- fmt.Errorf("frontend exited unexpectedly: %w", err)
			}
		}()

		if err := waitHTTP(ctx, "http://localhost:5173", 60*time.Second, feLabel); err != nil {
			fmt.Printf("%s not ready (%v) — continuing anyway\n", feLabel, err)
		} else {
			fmt.Printf("%s ready\n", feLabel)
		}
	}

	fmt.Println()
	fmt.Println("\033[1;32m✓ Omega stack running\033[0m")
	fmt.Println("  API:      http://localhost:8080")
	fmt.Println("  Bridge:   http://localhost:9090")
	if !stackNoFrontend {
		fmt.Println("  Frontend: http://localhost:5173")
	}
	fmt.Println("\nPress Ctrl+C to stop all processes.")

	select {
	case <-ctx.Done():
	case err := <-errCh:
		fmt.Fprintf(os.Stderr, "\nStack error: %v\n", err)
		cancel()
	}

	killAll(procs)
	return nil
}

// waitHTTP polls url until it returns a non-5xx response or timeout elapses.
func waitHTTP(ctx context.Context, url string, timeout time.Duration, label string) error {
	client := &http.Client{Timeout: 2 * time.Second}
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		resp, err := client.Get(url) //nolint:gosec,noctx
		if err == nil {
			_ = resp.Body.Close()
			return nil
		}
		fmt.Printf("%s waiting for %s…\n", label, url)
		time.Sleep(2 * time.Second)
	}
	return fmt.Errorf("timeout waiting for %s", url)
}

// killAll sends SIGTERM to all processes that are still running.
func killAll(procs []*exec.Cmd) {
	for _, p := range procs {
		if p != nil && p.Process != nil {
			_ = p.Process.Signal(syscall.SIGTERM)
		}
	}
}
