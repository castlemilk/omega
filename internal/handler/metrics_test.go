package handler_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"connectrpc.com/connect"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/handler"
	"github.com/benebsworth/omega/internal/telemetry"
)

func TestNewHandlerMetrics(t *testing.T) {
	// Init a no-op telemetry provider (no OTLP endpoint) so instruments register.
	ctx := context.Background()
	if _, err := telemetry.Init(ctx, telemetry.Config{ServiceName: "test"}); err != nil {
		t.Fatalf("telemetry init: %v", err)
	}
	defer telemetry.Shutdown(ctx) //nolint:errcheck

	hm, err := handler.NewHandlerMetrics()
	if err != nil {
		t.Fatalf("NewHandlerMetrics: %v", err)
	}
	if hm == nil {
		t.Fatal("expected non-nil HandlerMetrics")
	}
}

func TestMetricsInterceptor_Success(t *testing.T) {
	ctx := context.Background()
	if _, err := telemetry.Init(ctx, telemetry.Config{ServiceName: "test"}); err != nil {
		t.Fatalf("telemetry init: %v", err)
	}
	defer telemetry.Shutdown(ctx) //nolint:errcheck

	hm, err := handler.NewHandlerMetrics()
	if err != nil {
		t.Fatalf("NewHandlerMetrics: %v", err)
	}

	// Spin up a real Connect-RPC test server with the Victoria handler
	// (uses an in-memory stub so no actual DB is needed).
	mux := http.NewServeMux()
	path, svcHandler := omegav1connect.NewVictoriaServiceHandler(
		omegav1connect.UnimplementedVictoriaServiceHandler{},
		connect.WithInterceptors(hm.MetricsInterceptor()),
	)
	mux.Handle(path, svcHandler)
	srv := httptest.NewServer(mux)
	defer srv.Close()

	client := omegav1connect.NewVictoriaServiceClient(http.DefaultClient, srv.URL)
	_, err = client.GetPortfolio(ctx, connect.NewRequest(&omegav1.GetPortfolioRequest{}))
	// UnimplementedHandler returns Unimplemented — that is expected.
	var connectErr *connect.Error
	if err != nil && !errors.As(err, &connectErr) {
		t.Fatalf("unexpected non-connect error: %v", err)
	}
	// No panic = interceptor wired correctly.
}

func TestMetricsInterceptor_Error(t *testing.T) {
	ctx := context.Background()
	// Second Init is a no-op (singleton).
	telemetry.Init(ctx, telemetry.Config{ServiceName: "test"}) //nolint:errcheck,gosec

	hm, err := handler.NewHandlerMetrics()
	if err != nil {
		t.Fatalf("NewHandlerMetrics: %v", err)
	}

	// Interceptor should survive and propagate errors from the handler.
	interceptor := hm.MetricsInterceptor()
	inner := connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			return nil, connect.NewError(connect.CodeUnavailable, errors.New("test error"))
		}
	})

	mux := http.NewServeMux()
	path, svcHandler := omegav1connect.NewVictoriaServiceHandler(
		omegav1connect.UnimplementedVictoriaServiceHandler{},
		connect.WithInterceptors(interceptor, inner),
	)
	mux.Handle(path, svcHandler)
	srv := httptest.NewServer(mux)
	defer srv.Close()

	client := omegav1connect.NewVictoriaServiceClient(http.DefaultClient, srv.URL)
	_, err = client.GetPortfolio(ctx, connect.NewRequest(&omegav1.GetPortfolioRequest{}))
	if err == nil {
		t.Fatal("expected error, got nil")
	}
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected connect.Error, got %T: %v", err, err)
	}
}
