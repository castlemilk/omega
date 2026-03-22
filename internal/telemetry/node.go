package telemetry

import (
	"context"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	metricnoop "go.opentelemetry.io/otel/metric/noop"
	"go.opentelemetry.io/otel/trace"
)

// NodeInstrumentation is the interface every Omega node must satisfy to get
// automatic observability. Embed BaseNodeInstrumentation to fulfil it for free.
type NodeInstrumentation interface {
	// StartSpan creates a child span of any span in ctx, tagging it with the
	// node's identity attributes. The returned context carries the new span.
	StartSpan(ctx context.Context, spanName string, opts ...trace.SpanStartOption) (context.Context, trace.Span)

	// RecordExecution records a completed node execution — latency and
	// success/error outcome. Call it at the end of every Execute call.
	RecordExecution(ctx context.Context, latency time.Duration, err error)

	// EmitEvent adds a named event to the current span in ctx.
	EmitEvent(ctx context.Context, name string, attrs ...attribute.KeyValue)
}

// ---------------------------------------------------------------------------
// BaseNodeInstrumentation — embed in every Omega node struct
// ---------------------------------------------------------------------------

// BaseNodeInstrumentation provides a default implementation of
// NodeInstrumentation. Embed it and call InitInstrumentation(nodeName, nodeType)
// before use (typically in the node constructor).
type BaseNodeInstrumentation struct {
	nodeName string
	nodeType string

	tracer          trace.Tracer
	execDuration    metric.Float64Histogram
	execCount       metric.Int64Counter
}

// InitInstrumentation wires up the OTel instruments for this node.
// Must be called before any of the NodeInstrumentation methods.
func (b *BaseNodeInstrumentation) InitInstrumentation(nodeName, nodeType string) {
	b.nodeName = nodeName
	b.nodeType = nodeType
	b.tracer = Tracer()

	m := Meter()
	var err error

	b.execDuration, err = m.Float64Histogram(
		MetricNodeExecutionLatency,
		metric.WithUnit("s"),
		metric.WithDescription("Node execution latency in seconds"),
		metric.WithExplicitBucketBoundaries(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
	)
	if err != nil {
		b.execDuration = metricnoop.Float64Histogram{}
	}

	b.execCount, err = m.Int64Counter(
		"omega.node.executions",
		metric.WithDescription("Total node executions by outcome"),
	)
	if err != nil {
		b.execCount = metricnoop.Int64Counter{}
	}
}

// StartSpan creates a child span tagged with the node's name and type.
func (b *BaseNodeInstrumentation) StartSpan(
	ctx context.Context,
	spanName string,
	opts ...trace.SpanStartOption,
) (context.Context, trace.Span) {
	opts = append(opts, trace.WithAttributes(
		AttrNodeName.String(b.nodeName),
		AttrNodeType.String(b.nodeType),
	))
	return b.tracer.Start(ctx, spanName, opts...)
}

// RecordExecution records execution outcome metrics and sets span status.
func (b *BaseNodeInstrumentation) RecordExecution(ctx context.Context, latency time.Duration, err error) {
	attrs := []attribute.KeyValue{
		AttrNodeName.String(b.nodeName),
		AttrNodeType.String(b.nodeType),
	}

	outcome := "success"
	if err != nil {
		outcome = "error"
		if span := trace.SpanFromContext(ctx); span.IsRecording() {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}
	}
	attrs = append(attrs, attribute.String("outcome", outcome))

	b.execDuration.Record(ctx, latency.Seconds(), metric.WithAttributes(attrs...))
	b.execCount.Add(ctx, 1, metric.WithAttributes(attrs...))
}

// EmitEvent adds a named event with optional attributes to the active span.
func (b *BaseNodeInstrumentation) EmitEvent(ctx context.Context, name string, attrs ...attribute.KeyValue) {
	if span := trace.SpanFromContext(ctx); span.IsRecording() {
		span.AddEvent(name, trace.WithAttributes(attrs...))
	}
}

