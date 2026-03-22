package telemetry

import (
	"context"
	"fmt"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"

)

// Config controls the OTel provider initialisation.
type Config struct {
	// OtlpEndpoint is the base URL of the OTLP HTTP collector, e.g.
	// "http://localhost:4318". Leave empty to use a no-op exporter.
	OtlpEndpoint string

	// ServiceName identifies this process in traces and metrics.
	// Defaults to "omega".
	ServiceName string

	// ServiceVersion is embedded in every resource.
	// Defaults to "0.1.0".
	ServiceVersion string

	// ResourceAttrs are extra resource-level attributes that are attached to
	// every span and metric data point produced by this process.
	ResourceAttrs []attribute.KeyValue

	// SampleRate controls head-based trace sampling (0.0–1.0).
	// Defaults to 1.0 (sample everything).
	SampleRate float64

	// MetricExportInterval controls how often metrics are pushed to the
	// collector. Defaults to 15 s.
	MetricExportInterval time.Duration
}

func (c *Config) applyDefaults() {
	if c.ServiceName == "" {
		c.ServiceName = "omega"
	}
	if c.ServiceVersion == "" {
		c.ServiceVersion = "0.1.0"
	}
	if c.SampleRate <= 0 {
		c.SampleRate = 1.0
	}
	if c.MetricExportInterval <= 0 {
		c.MetricExportInterval = 15 * time.Second
	}
}

// Provider holds references to the initialized TracerProvider and MeterProvider
// and exposes convenience accessors used throughout the framework.
type Provider struct {
	tracer        trace.Tracer
	meter         metric.Meter
	tracerProvider *sdktrace.TracerProvider
	meterProvider  *sdkmetric.MeterProvider
}

// Tracer returns the framework-level tracer. Prefer package-level Tracer() for
// code that doesn't hold a *Provider reference.
func (p *Provider) Tracer() trace.Tracer { return p.tracer }

// Meter returns the framework-level meter.
func (p *Provider) Meter() metric.Meter { return p.meter }

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

var (
	globalOnce     sync.Once
	globalProvider *Provider
)

// Init initialises the global OTel providers exactly once.
// Subsequent calls are no-ops. Call Shutdown to flush on process exit.
func Init(ctx context.Context, cfg Config) (*Provider, error) {
	cfg.applyDefaults()

	var initErr error
	globalOnce.Do(func() {
		p, err := newProvider(ctx, cfg)
		if err != nil {
			initErr = err
			return
		}
		globalProvider = p
		otel.SetTracerProvider(p.tracerProvider)
		otel.SetMeterProvider(p.meterProvider)
	})
	if initErr != nil {
		return nil, initErr
	}
	return globalProvider, nil
}

// Global returns the singleton provider. Returns nil before Init is called.
func Global() *Provider { return globalProvider }

// Tracer is a package-level shortcut that returns the global tracer.
// Safe to call before Init — returns a no-op tracer in that case.
func Tracer() trace.Tracer {
	return otel.GetTracerProvider().Tracer("github.com/benebsworth/omega")
}

// Meter is a package-level shortcut that returns the global meter.
func Meter() metric.Meter {
	return otel.GetMeterProvider().Meter("github.com/benebsworth/omega")
}

// ---------------------------------------------------------------------------
// Internal construction
// ---------------------------------------------------------------------------

func newProvider(ctx context.Context, cfg Config) (*Provider, error) {
	res, err := buildResource(cfg)
	if err != nil {
		return nil, fmt.Errorf("telemetry: build resource: %w", err)
	}

	tp, err := buildTracerProvider(ctx, cfg, res)
	if err != nil {
		return nil, fmt.Errorf("telemetry: build tracer provider: %w", err)
	}

	mp, err := buildMeterProvider(ctx, cfg, res)
	if err != nil {
		return nil, fmt.Errorf("telemetry: build meter provider: %w", err)
	}

	const instrScope = "github.com/benebsworth/omega"
	return &Provider{
		tracer:         tp.Tracer(instrScope),
		meter:          mp.Meter(instrScope),
		tracerProvider: tp,
		meterProvider:  mp,
	}, nil
}

func buildResource(cfg Config) (*resource.Resource, error) {
	attrs := append(
		[]attribute.KeyValue{
			semconv.ServiceName(cfg.ServiceName),
			semconv.ServiceVersion(cfg.ServiceVersion),
		},
		cfg.ResourceAttrs...,
	)
	// Use resource.Default()'s schema URL to avoid merge conflicts.
	custom := resource.NewWithAttributes(resource.Default().SchemaURL(), attrs...)
	return resource.Merge(resource.Default(), custom)
}

func buildTracerProvider(ctx context.Context, cfg Config, res *resource.Resource) (*sdktrace.TracerProvider, error) {
	var exp sdktrace.SpanExporter

	if cfg.OtlpEndpoint != "" {
		e, err := otlptracehttp.New(ctx,
			otlptracehttp.WithEndpointURL(cfg.OtlpEndpoint+"/v1/traces"),
			otlptracehttp.WithInsecure(),
		)
		if err != nil {
			return nil, err
		}
		exp = e
	} else {
		// No-op exporter — traces are still created for context propagation
		// but not sent anywhere. Useful in development / tests.
		exp = &noopSpanExporter{}
	}

	sampler := sdktrace.TraceIDRatioBased(cfg.SampleRate)
	if cfg.SampleRate >= 1.0 {
		sampler = sdktrace.AlwaysSample()
	}

	return sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.ParentBased(sampler)),
	), nil
}

func buildMeterProvider(ctx context.Context, cfg Config, res *resource.Resource) (*sdkmetric.MeterProvider, error) {
	if cfg.OtlpEndpoint != "" {
		exp, err := otlpmetrichttp.New(ctx,
			otlpmetrichttp.WithEndpointURL(cfg.OtlpEndpoint+"/v1/metrics"),
			otlpmetrichttp.WithInsecure(),
		)
		if err != nil {
			return nil, err
		}
		return sdkmetric.NewMeterProvider(
			sdkmetric.WithResource(res),
			sdkmetric.WithReader(
				sdkmetric.NewPeriodicReader(exp,
					sdkmetric.WithInterval(cfg.MetricExportInterval),
				),
			),
		), nil
	}

	// No-op: metrics are recorded in-memory but never exported.
	return sdkmetric.NewMeterProvider(sdkmetric.WithResource(res)), nil
}

// ---------------------------------------------------------------------------
// noopSpanExporter — used when no OTLP endpoint is configured
// ---------------------------------------------------------------------------

type noopSpanExporter struct{}

func (noopSpanExporter) ExportSpans(_ context.Context, _ []sdktrace.ReadOnlySpan) error { return nil }
func (noopSpanExporter) Shutdown(_ context.Context) error                               { return nil }
