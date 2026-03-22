package memory_test

import (
	"context"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/memory"
	"github.com/benebsworth/omega/internal/telemetry"
)

func initTelemetry(t *testing.T) {
	t.Helper()
	ctx := context.Background()
	if _, err := telemetry.Init(ctx, telemetry.Config{ServiceName: "test-memory"}); err != nil {
		t.Fatalf("telemetry init: %v", err)
	}
	t.Cleanup(func() {
		ctx2, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		telemetry.Shutdown(ctx2) //nolint:errcheck,gosec
	})
}

func TestNewMemoryMetrics(t *testing.T) {
	initTelemetry(t)
	mm, err := memory.NewMemoryMetrics()
	if err != nil {
		t.Fatalf("NewMemoryMetrics: %v", err)
	}
	if mm == nil {
		t.Fatal("expected non-nil MemoryMetrics")
	}
}

func TestMemoryMetrics_RecordEnqueueFlush(t *testing.T) {
	initTelemetry(t)
	mm, err := memory.NewMemoryMetrics()
	if err != nil {
		t.Fatalf("NewMemoryMetrics: %v", err)
	}

	ctx := context.Background()
	enqueueTime := time.Now().Add(-50 * time.Millisecond)

	// Should not panic.
	mm.RecordEnqueue(ctx)
	mm.RecordFlush(ctx, enqueueTime, "test-key", nil)
}

func TestMemoryMetrics_RecordConsolidation(t *testing.T) {
	initTelemetry(t)
	mm, err := memory.NewMemoryMetrics()
	if err != nil {
		t.Fatalf("NewMemoryMetrics: %v", err)
	}

	ctx := context.Background()
	// Should not panic.
	mm.RecordConsolidation(ctx, 120*time.Millisecond, "victoria")
}

func TestMemoryMetrics_CacheHitMiss(t *testing.T) {
	initTelemetry(t)
	mm, err := memory.NewMemoryMetrics()
	if err != nil {
		t.Fatalf("NewMemoryMetrics: %v", err)
	}

	ctx := context.Background()
	mm.RecordCacheHit(ctx)
	mm.RecordCacheHit(ctx)
	mm.RecordCacheMiss(ctx)
	// No panics = pass.
}

func TestMemoryMetrics_Contradiction(t *testing.T) {
	initTelemetry(t)
	mm, err := memory.NewMemoryMetrics()
	if err != nil {
		t.Fatalf("NewMemoryMetrics: %v", err)
	}

	ctx := context.Background()
	mm.RecordContradiction(ctx, "victoria-node-1")
}
