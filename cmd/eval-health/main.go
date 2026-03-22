package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/benebsworth/omega/internal/eval"
)

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	fmt.Println("=== Omega Telemetry-Aware Eval ===")
	fmt.Printf("Run at: %s\n\n", time.Now().Format(time.RFC3339))

	// ── 1. Direct SystemHealthFromTelemetry ──────────────────────────────────
	report, _ := eval.SystemHealthFromTelemetry(ctx, "http://localhost:3200", "http://localhost:8889/metrics")

	fmt.Println("--- SystemHealthFromTelemetry ---")
	fmt.Printf("Score:            %.3f / 1.000\n", report.Score)
	fmt.Printf("TraceVolume:      %d traces (last 15 min)\n", report.TraceVolume)
	fmt.Printf("ErrorSpanRate:    %.2f%%\n", report.ErrorSpanRate*100)
	fmt.Printf("P99Latency:       %.4f s\n", report.P99Latency)
	fmt.Printf("MetricsFreshness: %s\n", report.MetricsFreshness.Round(time.Millisecond))
	fmt.Printf("EvaluatedAt:      %s\n", report.EvaluatedAt.Format(time.RFC3339))

	fmt.Println("\nComponent Scores:")
	for k, v := range report.ComponentScores {
		filled := int(v * 20)
		if filled > 20 {
			filled = 20
		}
		bar := strings.Repeat("█", filled) + strings.Repeat("░", 20-filled)
		fmt.Printf("  %-12s [%s] %.3f\n", k, bar, v)
	}

	if len(report.Anomalies) > 0 {
		fmt.Println("\nAnomalies:")
		for _, a := range report.Anomalies {
			fmt.Printf("  ⚠  %s\n", a)
		}
	} else {
		fmt.Println("\nAnomalies: none")
	}

	if len(report.RecommendedActions) > 0 {
		fmt.Println("\nRecommended Actions:")
		for i, a := range report.RecommendedActions {
			fmt.Printf("  %d. %s\n", i+1, a)
		}
	}

	// ── 2. Victoria Eval with Telemetry ──────────────────────────────────────
	fmt.Println("\n--- RunVictoriaEvalWithTelemetry ---")
	provider := eval.NewVectoraDBProvider // use stub for offline eval
	_ = provider

	// Use StubVictoriaProvider since we don't need live DB for this eval
	stubProvider := &eval.StubVictoriaProvider{}
	opts := eval.DefaultTelemetryOptions()
	fullReport := eval.RunVictoriaEvalWithTelemetry(ctx, stubProvider, opts)

	fmt.Printf("Victoria EvalResult Score: %.3f\n", fullReport.EvalResult.Score)
	fmt.Printf("  Passed: %d  Failed: %d\n", fullReport.EvalResult.Passed, fullReport.EvalResult.Failed)
	if len(fullReport.EvalResult.Details) > 0 {
		fmt.Println("  Details:")
		for _, d := range fullReport.EvalResult.Details {
			fmt.Printf("    - %s\n", d)
		}
	}

	fmt.Printf("\nObservability Audit Score: %.3f\n", fullReport.AuditResult.VisibilityScore)
	fmt.Printf("  Observable: %d  Partial: %d  BlackBox: %d\n",
		fullReport.AuditResult.ObservableCount,
		fullReport.AuditResult.PartialCount,
		fullReport.AuditResult.BlackBoxCount,
	)

	if fullReport.Telemetry != nil {
		fmt.Printf("\nTelemetry Health Score: %.3f\n", fullReport.Telemetry.Score)
		fmt.Printf("  TraceVolume:   %d\n", fullReport.Telemetry.TraceVolume)
		fmt.Printf("  ErrorSpanRate: %.2f%%\n", fullReport.Telemetry.ErrorSpanRate*100)
	}

	// ── 3. Full markdown report ───────────────────────────────────────────────
	fmt.Println("\n--- Full Markdown Report ---")
	fmt.Println(fullReport.Markdown())

	fmt.Println("=== Done ===")
}
