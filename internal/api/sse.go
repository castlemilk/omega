package api

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/benebsworth/omega/internal/observability"
)

// sseClient represents a single connected SSE consumer.
type sseClient struct {
	ch chan string
}

// SSEHandler serves Server-Sent Events sourced from the EventBus.
// It broadcasts real-time events and periodic metrics snapshots to all
// connected clients, cleaning up automatically on disconnect.
type SSEHandler struct {
	aggregator *MetricsAggregator
	logger     *slog.Logger
	ch         <-chan observability.Event
	cancelSub  func()

	mu      sync.Mutex
	clients map[*sseClient]struct{}
}

// NewSSEHandler creates an SSEHandler.
// The EventBus subscription is registered immediately so no events are missed before Run is called.
func NewSSEHandler(bus *observability.EventBus, agg *MetricsAggregator, logger *slog.Logger) *SSEHandler {
	if logger == nil {
		logger = slog.Default()
	}
	ch, cancel := bus.Subscribe(256)
	return &SSEHandler{
		aggregator: agg,
		logger:     logger,
		ch:         ch,
		cancelSub:  cancel,
		clients:    make(map[*sseClient]struct{}),
	}
}

// RegisterRoutes mounts the SSE endpoint on mux.
func (h *SSEHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/events", h.ServeHTTP)
}

// Run drives the broadcast loop until ctx is done.
func (h *SSEHandler) Run(ctx context.Context) {
	defer h.cancelSub()

	metricsTicker := time.NewTicker(5 * time.Second)
	defer metricsTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case e, ok := <-h.ch:
			if !ok {
				return
			}
			h.dispatchEvent(e)
		case <-metricsTicker.C:
			h.broadcastMetrics()
		}
	}
}

// ServeHTTP upgrades an HTTP connection to an SSE stream.
func (h *SSEHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	client := &sseClient{ch: make(chan string, 64)}
	h.addClient(client)
	defer h.removeClient(client)

	// Send the current metrics snapshot immediately on connect.
	if data, err := json.Marshal(h.aggregator.GetLiveMetrics()); err == nil {
		_, _ = fmt.Fprintf(w, "event: metrics_update\ndata: %s\n\n", data) //nolint:gosec
		flusher.Flush()
	}

	for {
		select {
		case <-r.Context().Done():
			return
		case msg, ok := <-client.ch:
			if !ok {
				return
			}
			fmt.Fprint(w, msg) //nolint:errcheck
			flusher.Flush()
		}
	}
}

// addClient registers a new client under the mutex.
func (h *SSEHandler) addClient(c *sseClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c] = struct{}{}
}

// removeClient deregisters and closes the client channel.
func (h *SSEHandler) removeClient(c *sseClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.clients, c)
	close(c.ch)
}

// broadcast serialises payload as JSON and fans it out to every client.
// Clients whose channel is full are skipped and warned about.
func (h *SSEHandler) broadcast(eventType string, payload any) {
	data, err := json.Marshal(payload)
	if err != nil {
		h.logger.Error("SSE marshal error", "type", eventType, "error", err)
		return
	}
	msg := fmt.Sprintf("event: %s\ndata: %s\n\n", eventType, data)

	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		select {
		case c.ch <- msg:
		default:
			h.logger.Warn("SSE client channel full, dropping event", "type", eventType)
		}
	}
}

// broadcastMetrics fetches the latest metrics snapshot and broadcasts it.
func (h *SSEHandler) broadcastMetrics() {
	h.broadcast("metrics_update", h.aggregator.GetLiveMetrics())
}

// dispatchEvent maps a bus event to its SSE event type and broadcasts it.
func (h *SSEHandler) dispatchEvent(e observability.Event) {
	switch e.Type {
	case observability.EventCycleStarted:
		h.broadcast("cycle_started", e.Payload)
	case observability.EventCycleCompleted:
		h.broadcast("cycle_completed", e.Payload)
	case observability.EventNodePromoted, observability.EventNodeDemoted:
		h.broadcast("node_changed", e.Payload)
	case observability.EventSafetyViolation:
		h.broadcast("safety_violation", e.Payload)
	case observability.EventAdversarialVeto:
		h.broadcast("adversarial_alert", e.Payload)
	case observability.EventImprovementApplied:
		h.broadcast("improvement_triggered", e.Payload)
	}
}
