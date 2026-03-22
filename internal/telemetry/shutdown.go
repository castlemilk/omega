package telemetry

import (
	"context"
	"errors"
)

// Shutdown flushes all pending spans and metric data points and releases
// resources held by the global provider. Call this in a defer at the top of
// main or in your signal handler.
//
// It is safe to call Shutdown before Init — it becomes a no-op in that case.
func Shutdown(ctx context.Context) error {
	p := globalProvider
	if p == nil {
		return nil
	}

	var errs []error
	if err := p.tracerProvider.Shutdown(ctx); err != nil {
		errs = append(errs, err)
	}
	if err := p.meterProvider.Shutdown(ctx); err != nil {
		errs = append(errs, err)
	}
	return errors.Join(errs...)
}
