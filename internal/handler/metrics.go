package handler

import (
	"context"
	"errors"
	"strings"
	"time"

	"connectrpc.com/connect"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"

	"github.com/benebsworth/omega/internal/telemetry"
)

// HandlerMetrics holds the OTel instruments used by the Connect-RPC interceptor.
// Create once with NewHandlerMetrics and pass to MetricsInterceptor.
type HandlerMetrics struct {
	tracer         trace.Tracer
	requestDuration metric.Float64Histogram  // by method
	requestCount    metric.Int64Counter       // by method + status
	errorCount      metric.Int64Counter       // by method
	activeRequests  metric.Int64UpDownCounter // gauge: in-flight RPCs
}

// NewHandlerMetrics creates and registers all OTel instruments for the
// Connect-RPC handler layer. Call once at startup.
func NewHandlerMetrics() (*HandlerMetrics, error) {
	m := telemetry.Meter()

	duration, err := m.Float64Histogram(
		telemetry.MetricHandlerRequestDuration,
		metric.WithUnit("s"),
		metric.WithDescription("Connect-RPC handler request duration in seconds"),
		metric.WithExplicitBucketBoundaries(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
	)
	if err != nil {
		return nil, err
	}

	reqCount, err := m.Int64Counter(
		telemetry.MetricHandlerRequestCount,
		metric.WithDescription("Total Connect-RPC requests by method and status"),
	)
	if err != nil {
		return nil, err
	}

	errCount, err := m.Int64Counter(
		telemetry.MetricHandlerErrorCount,
		metric.WithDescription("Total Connect-RPC errors by method"),
	)
	if err != nil {
		return nil, err
	}

	active, err := m.Int64UpDownCounter(
		telemetry.MetricHandlerActiveRequests,
		metric.WithDescription("Number of in-flight Connect-RPC requests"),
	)
	if err != nil {
		return nil, err
	}

	return &HandlerMetrics{
		tracer:          telemetry.Tracer(),
		requestDuration: duration,
		requestCount:    reqCount,
		errorCount:      errCount,
		activeRequests:  active,
	}, nil
}

// MetricsInterceptor returns a Connect-RPC interceptor that records span and
// metric data for every unary RPC call.
//
// Wire it in via connect.WithInterceptors(hm.MetricsInterceptor()) when
// constructing service handlers.
func (hm *HandlerMetrics) MetricsInterceptor() connect.UnaryInterceptorFunc {
	return connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			procedure := req.Spec().Procedure // e.g. "/omega.v1.OrchestratorService/Execute"
			method := shortMethod(procedure)
			service := shortService(procedure)

			baseAttrs := []attribute.KeyValue{
				telemetry.AttrRPCMethod.String(method),
				telemetry.AttrRPCService.String(service),
			}

			// Start span
			ctx, span := hm.tracer.Start(ctx, telemetry.SpanRPCHandler,
				trace.WithAttributes(baseAttrs...),
				trace.WithSpanKind(trace.SpanKindServer),
			)
			defer span.End()

			// Track in-flight requests
			hm.activeRequests.Add(ctx, 1, metric.WithAttributes(baseAttrs...))
			defer hm.activeRequests.Add(ctx, -1, metric.WithAttributes(baseAttrs...))

			start := time.Now()
			resp, err := next(ctx, req)
			latency := time.Since(start)

			statusCode := "ok"
			if err != nil {
				var connectErr *connect.Error
				if errors.As(err, &connectErr) {
					statusCode = connectErr.Code().String()
				} else {
					statusCode = "internal"
				}
				span.RecordError(err)
				span.SetStatus(codes.Error, err.Error())

				hm.errorCount.Add(ctx, 1, metric.WithAttributes(baseAttrs...))
			} else {
				span.SetStatus(codes.Ok, "")
			}

			resultAttrs := append(baseAttrs, telemetry.AttrRPCStatus.String(statusCode))
			hm.requestDuration.Record(ctx, latency.Seconds(), metric.WithAttributes(resultAttrs...))
			hm.requestCount.Add(ctx, 1, metric.WithAttributes(resultAttrs...))

			return resp, err
		}
	})
}

// shortMethod extracts the RPC method name from a full procedure string.
// "/omega.v1.OrchestratorService/Execute" → "Execute"
func shortMethod(procedure string) string {
	if idx := strings.LastIndex(procedure, "/"); idx >= 0 {
		return procedure[idx+1:]
	}
	return procedure
}

// shortService extracts the service name from a full procedure string.
// "/omega.v1.OrchestratorService/Execute" → "OrchestratorService"
func shortService(procedure string) string {
	parts := strings.Split(strings.TrimPrefix(procedure, "/"), "/")
	if len(parts) >= 1 {
		svc := parts[0]
		// drop package prefix, keep simple name
		if dot := strings.LastIndex(svc, "."); dot >= 0 {
			return svc[dot+1:]
		}
		return svc
	}
	return procedure
}
