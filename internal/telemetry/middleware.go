package telemetry

import (
	"context"
	"fmt"
	"strconv"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	"github.com/benebsworth/omega/internal/middleware"
)

// TraceMiddleware wraps every middleware chain execution in an OTel span.
// It propagates context so that all downstream spans are children of the
// cycle-level root span created by the orchestrator.
//
// Usage:
//
//	chain := middleware.NewChain(handler,
//	    telemetry.NewTraceMiddleware(),   // outermost
//	    metricsMiddleware,
//	    loopDetection,
//	    ...
//	)
type TraceMiddleware struct {
	tracer trace.Tracer
}

// NewTraceMiddleware returns a TraceMiddleware using the global tracer.
func NewTraceMiddleware() *TraceMiddleware {
	return &TraceMiddleware{tracer: Tracer()}
}

// Process implements middleware.Middleware.
func (t *TraceMiddleware) Process(
	ctx context.Context,
	req *middleware.ExecutionRequest,
	next middleware.NextFunc,
) (*middleware.ExecutionResponse, error) {
	attrs := []attribute.KeyValue{
		AttrNodeID.String(req.NodeID),
		AttrAction.String(req.Action),
		AttrDepth.Int(req.Depth),
		AttrAutonomyLevel.String(fmt.Sprintf("%d", req.AutonomyLevel)),
	}
	if cycleID, ok := req.Metadata["cycle_id"]; ok {
		attrs = append(attrs, AttrCycleID.String(cycleID))
	}

	ctx, span := t.tracer.Start(ctx, SpanNodeExecution,
		trace.WithAttributes(attrs...),
		trace.WithSpanKind(trace.SpanKindInternal),
	)
	defer span.End()

	resp, err := next(ctx, req)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		span.SetAttributes(AttrErrorKind.String("execution_error"))
		return resp, err
	}

	if resp != nil && resp.Error != "" {
		span.SetStatus(codes.Error, resp.Error)
		span.SetAttributes(attribute.String("outcome", "error"))
	} else {
		span.SetStatus(codes.Ok, "")
		span.SetAttributes(attribute.String("outcome", "success"))
	}

	if resp != nil {
		span.SetAttributes(attribute.String("duration_ms",
			strconv.FormatInt(resp.Duration.Milliseconds(), 10),
		))
	}

	return resp, nil
}
