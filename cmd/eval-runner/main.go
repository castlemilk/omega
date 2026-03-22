package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/benebsworth/omega/internal/eval"
)

func main() {
	ctx := context.Background()

	opts := eval.DefaultTelemetryOptions()
	if url := os.Getenv("TEMPO_URL"); url != "" {
		opts.TempoURL = url
	}
	if url := os.Getenv("METRICS_URL"); url != "" {
		opts.MetricsURL = url
	}

	result := eval.RunVictoriaEvalWithTelemetry(ctx, &eval.StubVictoriaProvider{}, opts)

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")

	fmt.Println("=== Victoria Eval Report ===")
	_ = enc.Encode(result.VictoriaReport) //nolint:errcheck

	if result.Telemetry != nil {
		fmt.Println("=== Telemetry Health Report ===")
		_ = enc.Encode(result.Telemetry) //nolint:errcheck
	}
}
