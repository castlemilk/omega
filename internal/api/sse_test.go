package api

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

// streamResponseWriter implements http.ResponseWriter + http.Flusher using an
// io.Pipe so that reads and writes can happen concurrently in different goroutines.
type streamResponseWriter struct {
	header http.Header
	pw     *io.PipeWriter
	Reader *io.PipeReader
}

func newStreamResponseWriter() *streamResponseWriter {
	pr, pw := io.Pipe()
	return &streamResponseWriter{
		header: make(http.Header),
		pw:     pw,
		Reader: pr,
	}
}

func (s *streamResponseWriter) Header() http.Header             { return s.header }
func (s *streamResponseWriter) WriteHeader(_ int)               {}
func (s *streamResponseWriter) Write(b []byte) (int, error)     { return s.pw.Write(b) }
func (s *streamResponseWriter) Flush()                          {}
func (s *streamResponseWriter) Close() { _ = s.pw.Close() }

// waitForLine reads from rdr until a line containing substr is found, or the
// deadline is reached.
func waitForLine(t *testing.T, rdr *io.PipeReader, substr string, deadline time.Duration) string {
	t.Helper()
	found := make(chan string, 1)
	go func() {
		scanner := bufio.NewScanner(rdr)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.Contains(line, substr) {
				found <- line
				return
			}
		}
	}()
	select {
	case line := <-found:
		return line
	case <-time.After(deadline):
		t.Errorf("timed out waiting for SSE line containing %q", substr)
		return ""
	}
}

func newTestSSESetup(t *testing.T) (*SSEHandler, *MetricsAggregator, *observability.EventBus, context.CancelFunc) {
	t.Helper()
	bus := observability.NewEventBus(nil)
	agg := NewMetricsAggregator(bus)
	h := NewSSEHandler(bus, agg, nil)

	ctx, cancel := context.WithCancel(context.Background())
	go agg.Run(ctx)
	go h.Run(ctx)

	return h, agg, bus, cancel
}

func TestSSEHandler_headers(t *testing.T) {
	h, _, _, cancel := newTestSSESetup(t)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithTimeout(req.Context(), 100*time.Millisecond)
	defer reqCancel()
	req = req.WithContext(reqCtx)

	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req)

	if ct := rw.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want text/event-stream", ct)
	}
	if cc := rw.Header().Get("Cache-Control"); cc != "no-cache" {
		t.Errorf("Cache-Control = %q, want no-cache", cc)
	}
	if conn := rw.Header().Get("Connection"); conn != "keep-alive" {
		t.Errorf("Connection = %q, want keep-alive", conn)
	}
}

func TestSSEHandler_initialMetricsSnapshot(t *testing.T) {
	h, _, _, cancel := newTestSSESetup(t)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithTimeout(req.Context(), 300*time.Millisecond)
	defer reqCancel()
	req = req.WithContext(reqCtx)

	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req)

	body := rw.Body.String()
	if !strings.Contains(body, "event: metrics_update") {
		t.Errorf("expected initial metrics_update event, got:\n%s", body)
	}
	if !strings.Contains(body, `"cycles_per_minute_1m"`) {
		t.Errorf("expected cycles_per_minute_1m field in metrics JSON, got:\n%s", body)
	}
}

func TestSSEHandler_broadcastEvent(t *testing.T) {
	h, _, bus, cancel := newTestSSESetup(t)
	defer cancel()

	srw := newStreamResponseWriter()

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithCancel(req.Context())
	req = req.WithContext(reqCtx)

	go h.ServeHTTP(srw, req)

	// Give the handler time to register the client and send the initial snapshot.
	time.Sleep(80 * time.Millisecond)

	bus.Publish(observability.Event{
		Type:    observability.EventCycleStarted,
		Payload: observability.CycleStartedPayload{Cycle: 1, ActiveNodes: []string{"n1"}},
	})

	waitForLine(t, srw.Reader, "event: cycle_started", 400*time.Millisecond)
	reqCancel()
}

func TestSSEHandler_eventTypes(t *testing.T) {
	tests := []struct {
		name        string
		eventType   observability.EventType
		wantSSEType string
		payload     observability.EventPayload
	}{
		{
			name:        "cycle_started",
			eventType:   observability.EventCycleStarted,
			wantSSEType: "cycle_started",
			payload:     observability.CycleStartedPayload{Cycle: 1},
		},
		{
			name:        "cycle_completed",
			eventType:   observability.EventCycleCompleted,
			wantSSEType: "cycle_completed",
			payload:     observability.CycleCompletedPayload{Cycle: 1, DurationSecs: 1.0},
		},
		{
			name:        "node_promoted",
			eventType:   observability.EventNodePromoted,
			wantSSEType: "node_changed",
			payload:     observability.NodePromotedPayload{NodeID: "n1", FromLevel: 1, ToLevel: 2},
		},
		{
			name:        "node_demoted",
			eventType:   observability.EventNodeDemoted,
			wantSSEType: "node_changed",
			payload:     observability.NodeDemotedPayload{NodeID: "n1", FromLevel: 2, ToLevel: 1},
		},
		{
			name:        "safety_violation",
			eventType:   observability.EventSafetyViolation,
			wantSSEType: "safety_violation",
			payload:     observability.SafetyViolationPayload{NodeID: "n1", Layer: 1, Constraint: "c"},
		},
		{
			name:        "adversarial_alert",
			eventType:   observability.EventAdversarialVeto,
			wantSSEType: "adversarial_alert",
			payload:     observability.AdversarialVetoPayload{NodeID: "n1", Ring: 1, Reason: "r"},
		},
		{
			name:        "improvement_triggered",
			eventType:   observability.EventImprovementApplied,
			wantSSEType: "improvement_triggered",
			payload: observability.ImprovementAppliedPayload{
				NodeID: "n1", StrategyName: "s",
				BeforeMetrics: map[string]float64{"x": 1},
				AfterMetrics:  map[string]float64{"x": 2},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bus := observability.NewEventBus(nil)
			agg := NewMetricsAggregator(bus)
			h := NewSSEHandler(bus, agg, nil)

			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			go agg.Run(ctx)
			go h.Run(ctx)

			srw := newStreamResponseWriter()
			req := httptest.NewRequest(http.MethodGet, "/events", nil)
			reqCtx, reqCancel := context.WithCancel(req.Context())
			req = req.WithContext(reqCtx)
			go h.ServeHTTP(srw, req)

			// Wait for client registration + initial snapshot.
			time.Sleep(80 * time.Millisecond)

			bus.Publish(observability.Event{Type: tt.eventType, Payload: tt.payload})

			waitForLine(t, srw.Reader, "event: "+tt.wantSSEType, 400*time.Millisecond)
			reqCancel()
		})
	}
}

func TestSSEHandler_clientCleanupOnDisconnect(t *testing.T) {
	h, _, _, cancel := newTestSSESetup(t)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithTimeout(req.Context(), 80*time.Millisecond)
	defer reqCancel()
	req = req.WithContext(reqCtx)

	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req) // blocks until context cancelled

	h.mu.Lock()
	nClients := len(h.clients)
	h.mu.Unlock()
	if nClients != 0 {
		t.Errorf("expected 0 clients after disconnect, got %d", nClients)
	}
}

func TestSSEHandler_metricsUpdateEventFormat(t *testing.T) {
	h, _, _, cancel := newTestSSESetup(t)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithTimeout(req.Context(), 200*time.Millisecond)
	defer reqCancel()
	req = req.WithContext(reqCtx)

	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req)

	body := rw.Body.String()
	lines := strings.Split(body, "\n")

	var foundEvent, foundData bool
	for i, line := range lines {
		if strings.HasPrefix(line, "event: metrics_update") {
			foundEvent = true
			// The next non-empty line should be the data line.
			for j := i + 1; j < len(lines); j++ {
				if strings.HasPrefix(lines[j], "data: ") {
					jsonPart := strings.TrimPrefix(lines[j], "data: ")
					var m LiveMetrics
					if err := json.Unmarshal([]byte(jsonPart), &m); err != nil {
						t.Errorf("metrics_update data is not valid LiveMetrics JSON: %v\nraw: %s", err, jsonPart)
					}
					foundData = true
					break
				}
			}
			break
		}
	}
	if !foundEvent {
		t.Error("did not find 'event: metrics_update' line")
	}
	if !foundData {
		t.Error("did not find 'data:' line after 'event: metrics_update'")
	}
}

func TestSSEHandler_RegisterRoutes(t *testing.T) {
	bus := observability.NewEventBus(nil)
	agg := NewMetricsAggregator(bus)
	h := NewSSEHandler(bus, agg, nil)

	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodGet, "/events", nil)
	reqCtx, reqCancel := context.WithTimeout(req.Context(), 80*time.Millisecond)
	defer reqCancel()
	req = req.WithContext(reqCtx)

	rw := httptest.NewRecorder()
	mux.ServeHTTP(rw, req)

	if rw.Code == http.StatusNotFound {
		t.Error("expected /events to be registered, got 404")
	}
}

func TestSSEHandler_multipleClients(t *testing.T) {
	h, _, bus, cancel := newTestSSESetup(t)
	defer cancel()

	const nClients = 3
	writers := make([]*streamResponseWriter, nClients)
	cancels := make([]context.CancelFunc, nClients)

	for i := 0; i < nClients; i++ {
		srw := newStreamResponseWriter()
		writers[i] = srw
		req := httptest.NewRequest(http.MethodGet, "/events", nil)
		ctx, c := context.WithCancel(req.Context()) //nolint:gosec // cancel stored in cancels[] and invoked at line ~345
		cancels[i] = c
		req = req.WithContext(ctx)
		go h.ServeHTTP(srw, req)
	}

	time.Sleep(100 * time.Millisecond)

	h.mu.Lock()
	count := len(h.clients)
	h.mu.Unlock()
	if count != nClients {
		t.Errorf("expected %d connected clients, got %d", nClients, count)
	}

	bus.Publish(observability.Event{
		Type:    observability.EventCycleStarted,
		Payload: observability.CycleStartedPayload{Cycle: 99},
	})

	for i, srw := range writers {
		waitForLine(t, srw.Reader, "event: cycle_started", 400*time.Millisecond)
		cancels[i]()
	}
}
