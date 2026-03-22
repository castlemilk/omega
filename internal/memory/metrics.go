package memory

import (
	"context"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	"github.com/benebsworth/omega/internal/telemetry"
)

// MemoryMetrics holds OTel instruments for the write queue and memory
// consolidation subsystems. Create once with NewMemoryMetrics and wire into
// WriteQueue / AtomicWriter / persistence layer as needed.
type MemoryMetrics struct {
	// WriteQueueDepth is the current number of pending (debounced) writes.
	WriteQueueDepth metric.Int64UpDownCounter

	// WriteLatency measures the duration from Enqueue to successful AtomicWriter.Write.
	WriteLatency metric.Float64Histogram

	// ConsolidationLatency measures the duration of a full consolidation pass.
	ConsolidationLatency metric.Float64Histogram

	// CacheHits counts mtime-cache lookups that found an up-to-date entry.
	CacheHits metric.Int64Counter

	// CacheMisses counts mtime-cache lookups that required a stat syscall.
	CacheMisses metric.Int64Counter

	// ContradictionCount counts contradiction pairs detected during retrieval.
	ContradictionCount metric.Int64Counter
}

// NewMemoryMetrics registers all OTel instruments for the memory subsystem.
// Call once at startup before creating any WriteQueue or persistence objects.
func NewMemoryMetrics() (*MemoryMetrics, error) {
	m := telemetry.Meter()

	depth, err := m.Int64UpDownCounter(
		telemetry.MetricWriteQueueDepth,
		metric.WithDescription("Current number of writes pending in the debounce queue"),
	)
	if err != nil {
		return nil, err
	}

	writeLatency, err := m.Float64Histogram(
		telemetry.MetricWriteLatency,
		metric.WithUnit("s"),
		metric.WithDescription("Latency from WriteQueue.Enqueue to AtomicWriter.Write completion"),
		metric.WithExplicitBucketBoundaries(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 30, 60),
	)
	if err != nil {
		return nil, err
	}

	consolidation, err := m.Float64Histogram(
		telemetry.MetricConsolidationLatency,
		metric.WithUnit("s"),
		metric.WithDescription("Duration of a memory consolidation pass"),
		metric.WithExplicitBucketBoundaries(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
	)
	if err != nil {
		return nil, err
	}

	hits, err := m.Int64Counter(
		telemetry.MetricCacheHits,
		metric.WithDescription("MtimeCache lookups returning a valid cached entry"),
	)
	if err != nil {
		return nil, err
	}

	misses, err := m.Int64Counter(
		telemetry.MetricCacheMisses,
		metric.WithDescription("MtimeCache lookups that required a stat syscall"),
	)
	if err != nil {
		return nil, err
	}

	contradictions, err := m.Int64Counter(
		telemetry.MetricContradictions,
		metric.WithDescription("Number of contradiction pairs detected during episode retrieval"),
	)
	if err != nil {
		return nil, err
	}

	return &MemoryMetrics{
		WriteQueueDepth:      depth,
		WriteLatency:         writeLatency,
		ConsolidationLatency: consolidation,
		CacheHits:            hits,
		CacheMisses:          misses,
		ContradictionCount:   contradictions,
	}, nil
}

// RecordEnqueue increments the write queue depth gauge and should be called
// inside WriteQueue.Enqueue.
func (mm *MemoryMetrics) RecordEnqueue(ctx context.Context) {
	mm.WriteQueueDepth.Add(ctx, 1)
}

// RecordFlush decrements the queue depth and records write latency.
// enqueueTime is the time.Time captured at Enqueue.
func (mm *MemoryMetrics) RecordFlush(ctx context.Context, enqueueTime time.Time, key string, err error) {
	mm.WriteQueueDepth.Add(ctx, -1)
	latency := time.Since(enqueueTime).Seconds()
	attrs := []attribute.KeyValue{
		attribute.String("outcome", outcomeLabel(err)),
		attribute.String("key", key),
	}
	mm.WriteLatency.Record(ctx, latency, metric.WithAttributes(attrs...))
}

// RecordConsolidation records the latency of a consolidation pass.
func (mm *MemoryMetrics) RecordConsolidation(ctx context.Context, latency time.Duration, namespace string) {
	mm.ConsolidationLatency.Record(ctx, latency.Seconds(),
		metric.WithAttributes(
			telemetry.AttrMemoryNamespace.String(namespace),
		),
	)
}

// RecordCacheHit increments the cache-hit counter.
func (mm *MemoryMetrics) RecordCacheHit(ctx context.Context) {
	mm.CacheHits.Add(ctx, 1)
}

// RecordCacheMiss increments the cache-miss counter.
func (mm *MemoryMetrics) RecordCacheMiss(ctx context.Context) {
	mm.CacheMisses.Add(ctx, 1)
}

// RecordContradiction increments the contradiction counter for a namespace/node pair.
func (mm *MemoryMetrics) RecordContradiction(ctx context.Context, nodeID string) {
	mm.ContradictionCount.Add(ctx, 1, metric.WithAttributes(
		telemetry.AttrNodeID.String(nodeID),
	))
}

func outcomeLabel(err error) string {
	if err != nil {
		return "error"
	}
	return "success"
}
