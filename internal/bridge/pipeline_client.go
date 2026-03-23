// Package bridge provides the Go-side client for the Python PipelineService.
//
// Python runs a ThreadingHTTPServer on a configurable port speaking the
// Connect-RPC JSON protocol. This client speaks that same protocol, injecting
// the active OpenTelemetry span as a W3C traceparent header so distributed
// traces span both runtimes.
package bridge

import (
	"context"
	"net/http"
	"os"

	"connectrpc.com/connect"
	"go.opentelemetry.io/otel/trace"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
)

const defaultPythonAddr = "http://localhost:9090"

// PipelineClient calls the Python PipelineService over Connect-RPC JSON.
// It is safe for concurrent use.
type PipelineClient struct {
	client omegav1connect.PipelineServiceClient
	addr   string
}

// NewPipelineClient creates a client pointing at the Python pipeline server.
// addr is used as-is when non-empty; otherwise $OMEGA_PYTHON_PIPELINE_ADDR
// is consulted; the hard-coded default is http://localhost:9090.
func NewPipelineClient(addr string) *PipelineClient {
	if addr == "" {
		addr = os.Getenv("OMEGA_PYTHON_PIPELINE_ADDR")
	}
	if addr == "" {
		addr = defaultPythonAddr
	}
	client := omegav1connect.NewPipelineServiceClient(
		&http.Client{},
		addr,
		connect.WithProtoJSON(), // Python server speaks Connect-RPC JSON
	)
	return &PipelineClient{client: client, addr: addr}
}

// ExecuteStep sends a pipeline step execution request to the Python server.
//
// The W3C traceparent header is constructed from the active OTel span in ctx
// and forwarded so Python can correlate spans back to the Go trace.
func (c *PipelineClient) ExecuteStep(
	ctx context.Context,
	req *omegav1.ExecuteStepRequest,
) (*omegav1.ExecuteStepResponse, error) {
	connectReq := connect.NewRequest(req)
	injectTraceparent(ctx, connectReq.Header())
	resp, err := c.client.ExecuteStep(ctx, connectReq)
	if err != nil {
		return nil, err
	}
	return resp.Msg, nil
}

// Ping checks that the Python pipeline server is reachable and healthy.
func (c *PipelineClient) Ping(ctx context.Context) (bool, error) {
	resp, err := c.client.Ping(ctx, connect.NewRequest(&omegav1.PingRequest{}))
	if err != nil {
		return false, err
	}
	return resp.Msg.Ok, nil
}

// Addr returns the configured Python pipeline server address.
func (c *PipelineClient) Addr() string { return c.addr }

// injectTraceparent writes a W3C traceparent header derived from the active
// OTel span in ctx. It is a no-op when no valid span is present.
//
//	traceparent: 00-{traceID}-{spanID}-01
func injectTraceparent(ctx context.Context, h http.Header) {
	span := trace.SpanFromContext(ctx)
	if !span.SpanContext().IsValid() {
		return
	}
	sc := span.SpanContext()
	h.Set("traceparent", "00-"+sc.TraceID().String()+"-"+sc.SpanID().String()+"-01")
}
