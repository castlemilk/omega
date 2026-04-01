// Package controlplane — REST handler that aggregates heartbeats and exposes
// dashboard-friendly JSON endpoints for the React frontend.
//
// Endpoints (all under /api/v1/):
//
//	POST /api/v1/heartbeat       — inbound heartbeat from Python nodes (JSON)
//	POST /api/v1/diagnostics     — inbound training diagnostics from Python (JSON)
//	GET  /api/v1/nodes           — list all node statuses
//	GET  /api/v1/diagnostics     — latest training diagnostics
//	GET  /api/v1/blockers        — active blockers across all nodes
package controlplane

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/heartbeat"
	"github.com/benebsworth/omega/internal/observability"
)

// Handler serves the control-plane REST API.
type Handler struct {
	store     *heartbeat.Store
	lifecycle *heartbeat.LifecycleStore       // optional; nil = lifecycle endpoints return 503
	decisions *heartbeat.DecisionStore        // optional; nil = decision endpoints return 503
	scorer    *observability.NodeHealthScorer // optional; nil = health endpoint uses default scorer
	startTime time.Time
	logger    *slog.Logger
}

// New creates a Handler backed by the given heartbeat store.
func New(store *heartbeat.Store, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{store: store, logger: logger, startTime: time.Now()}
}

// WithLifecycleStore attaches a lifecycle store to the handler.
func (h *Handler) WithLifecycleStore(ls *heartbeat.LifecycleStore) *Handler {
	h.lifecycle = ls
	return h
}

// WithDecisionStore attaches a decision store to the handler.
func (h *Handler) WithDecisionStore(ds *heartbeat.DecisionStore) *Handler {
	h.decisions = ds
	return h
}

// WithScorer attaches a NodeHealthScorer to the handler.
func (h *Handler) WithScorer(scorer *observability.NodeHealthScorer) *Handler {
	h.scorer = scorer
	return h
}

// RegisterRoutes mounts all control-plane endpoints on mux.
func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/heartbeat", h.handleHeartbeat)
	mux.HandleFunc("/api/v1/diagnostics", h.handleDiagnostics)
	mux.HandleFunc("/api/v1/nodes", h.handleNodes)
	mux.HandleFunc("/api/v1/blockers", h.handleBlockers)

	// Node observability — lifecycle events
	mux.HandleFunc("POST /api/v1/nodes/{id}/lifecycle", h.handlePostLifecycle)
	mux.HandleFunc("GET /api/v1/nodes/{id}/lifecycle", h.handleGetLifecycle)

	// Node observability — decision traces
	mux.HandleFunc("POST /api/v1/nodes/{id}/decisions", h.handlePostDecision)
	mux.HandleFunc("GET /api/v1/nodes/{id}/decisions", h.handleGetDecisions)
	mux.HandleFunc("GET /api/v1/nodes/{id}/decisions/{cycle}", h.handleGetDecisionByCycle)

	// Node observability — health score
	mux.HandleFunc("GET /api/v1/nodes/{id}/health", h.handleNodeHealth)

	// Platform-level aggregated view
	mux.HandleFunc("GET /api/v1/platform/status", h.handlePlatformStatus)
}

// ── JSON request/response types ──────────────────────────────────────────────

// heartbeatPayload is the JSON body accepted by POST /api/v1/heartbeat.
type heartbeatPayload struct {
	NodeID   string            `json:"node_id"`
	NodeType string            `json:"node_type"`
	Health   string            `json:"health"`   // "healthy" | "degraded" | "stale" | "dead"
	Metrics  map[string]string `json:"metrics"`
	Blockers []string          `json:"blockers"`
}

// diagnosticsPayload is the JSON body accepted by POST /api/v1/diagnostics.
type diagnosticsPayload struct {
	NodeID               string             `json:"node_id"`
	Cycle                int32              `json:"cycle"`
	Regime               string             `json:"regime"`
	DataFreshnessSeconds float32            `json:"data_freshness_seconds"`
	ActiveSignals        int32              `json:"active_signals"`
	TotalSignals         int32              `json:"total_signals"`
	SitOut               bool               `json:"sit_out"`
	SitOutReason         string             `json:"sit_out_reason"`
	OpenTrades           int32              `json:"open_trades"`
	ClosedTrades         int32              `json:"closed_trades"`
	Pnl                  float32            `json:"pnl"`
	Longs                int32              `json:"longs"`
	Shorts               int32              `json:"shorts"`
	Blockers             []string           `json:"blockers"`
	TickerConvictions    map[string]float64 `json:"ticker_convictions"`
}

// nodeStatusJSON is the outbound JSON shape for GET /api/v1/nodes.
type nodeStatusJSON struct {
	NodeID   string            `json:"node_id"`
	NodeType string            `json:"node_type"`
	Health   string            `json:"health"`
	LastSeen string            `json:"last_seen"`  // RFC3339
	Metrics  map[string]string `json:"metrics"`
	Blockers []string          `json:"blockers"`
	Stale    bool              `json:"stale"`
}

// diagnosticsJSON is the outbound JSON shape for GET /api/v1/diagnostics.
type diagnosticsJSON struct {
	NodeID               string             `json:"node_id"`
	Cycle                int32              `json:"cycle"`
	Regime               string             `json:"regime"`
	DataFreshnessSeconds float32            `json:"data_freshness_seconds"`
	ActiveSignals        int32              `json:"active_signals"`
	TotalSignals         int32              `json:"total_signals"`
	SitOut               bool               `json:"sit_out"`
	SitOutReason         string             `json:"sit_out_reason"`
	OpenTrades           int32              `json:"open_trades"`
	ClosedTrades         int32              `json:"closed_trades"`
	Pnl                  float32            `json:"pnl"`
	Longs                int32              `json:"longs"`
	Shorts               int32              `json:"shorts"`
	Blockers             []string           `json:"blockers"`
	TickerConvictions    map[string]float64 `json:"ticker_convictions"`
	Timestamp            string             `json:"timestamp"`
}

// ── Route handlers ────────────────────────────────────────────────────────────

// handleHeartbeat accepts POST for inbound heartbeats from Python nodes.
func (h *Handler) handleHeartbeat(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		h.receiveHeartbeat(w, r)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// handleDiagnostics routes GET (read latest) and POST (receive new) requests.
func (h *Handler) handleDiagnostics(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		h.receiveDiagnostics(w, r)
	case http.MethodGet:
		h.getDiagnostics(w, r)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// handleNodes serves GET /api/v1/nodes.
func (h *Handler) handleNodes(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	entries := h.store.ListNodes()
	out := make([]nodeStatusJSON, 0, len(entries))
	for _, e := range entries {
		lastSeen := ""
		if !e.LastSeen.IsZero() {
			lastSeen = e.LastSeen.UTC().Format(time.RFC3339)
		}
		blockers := e.Blockers
		if blockers == nil {
			blockers = []string{}
		}
		out = append(out, nodeStatusJSON{
			NodeID:   e.NodeID,
			NodeType: e.NodeType,
			Health:   healthName(e.Health),
			LastSeen: lastSeen,
			Metrics:  e.Metrics,
			Blockers: blockers,
			Stale:    heartbeat.IsStale(e),
		})
	}
	writeJSON(w, out)
}

// handleBlockers serves GET /api/v1/blockers.
func (h *Handler) handleBlockers(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, h.store.GetBlockers())
}

// ── Inbound write helpers ─────────────────────────────────────────────────────

func (h *Handler) receiveHeartbeat(w http.ResponseWriter, r *http.Request) {
	var p heartbeatPayload
	if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
		http.Error(w, "invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	if p.NodeID == "" {
		http.Error(w, "node_id required", http.StatusBadRequest)
		return
	}

	hb := &omegav1.Heartbeat{
		NodeId:   p.NodeID,
		NodeType: p.NodeType,
		Health:   parseHealth(p.Health),
		Metrics:  p.Metrics,
		Blockers: p.Blockers,
	}
	h.store.RecordHeartbeat(hb)

	writeJSON(w, map[string]any{"acknowledged": true, "server_time": time.Now().UTC().Format(time.RFC3339)})
}

func (h *Handler) receiveDiagnostics(w http.ResponseWriter, r *http.Request) {
	var p diagnosticsPayload
	if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
		http.Error(w, "invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	d := &omegav1.TrainingDiagnostics{
		NodeId:               p.NodeID,
		Cycle:                p.Cycle,
		Regime:               p.Regime,
		DataFreshnessSeconds: p.DataFreshnessSeconds,
		ActiveSignals:        p.ActiveSignals,
		TotalSignals:         p.TotalSignals,
		SitOut:               p.SitOut,
		SitOutReason:         p.SitOutReason,
		OpenTrades:           p.OpenTrades,
		ClosedTrades:         p.ClosedTrades,
		Pnl:                  p.Pnl,
		Longs:                p.Longs,
		Shorts:               p.Shorts,
		Blockers:             p.Blockers,
		TickerConvictions:    p.TickerConvictions,
	}
	h.store.RecordDiagnostics(d)

	writeJSON(w, map[string]any{"acknowledged": true, "server_time": time.Now().UTC().Format(time.RFC3339)})
}

func (h *Handler) getDiagnostics(w http.ResponseWriter, r *http.Request) {
	d := h.store.GetDiagnostics()
	if d == nil {
		writeJSON(w, map[string]any{"available": false})
		return
	}

	convictions := map[string]float64{}
	for k, v := range d.TickerConvictions {
		convictions[k] = v
	}
	blockers := d.Blockers
	if blockers == nil {
		blockers = []string{}
	}

	ts := ""
	if d.Timestamp != nil {
		ts = d.Timestamp.AsTime().UTC().Format(time.RFC3339)
	}

	writeJSON(w, diagnosticsJSON{
		NodeID:               d.NodeId,
		Cycle:                d.Cycle,
		Regime:               d.Regime,
		DataFreshnessSeconds: d.DataFreshnessSeconds,
		ActiveSignals:        d.ActiveSignals,
		TotalSignals:         d.TotalSignals,
		SitOut:               d.SitOut,
		SitOutReason:         d.SitOutReason,
		OpenTrades:           d.OpenTrades,
		ClosedTrades:         d.ClosedTrades,
		Pnl:                  d.Pnl,
		Longs:                d.Longs,
		Shorts:               d.Shorts,
		Blockers:             blockers,
		TickerConvictions:    convictions,
		Timestamp:            ts,
	})
}

// ── New observability JSON types ──────────────────────────────────────────────

// lifecycleEventJSON is one lifecycle event in API responses.
type lifecycleEventJSON struct {
	FromState string `json:"from_state"`
	ToState   string `json:"to_state"`
	Reason    string `json:"reason"`
	Timestamp string `json:"timestamp"`
}

// lifecycleResponse is returned by GET /api/v1/nodes/{id}/lifecycle.
type lifecycleResponse struct {
	NodeID string               `json:"node_id"`
	Events []lifecycleEventJSON `json:"events"`
}

// lifecyclePayload is accepted by POST /api/v1/nodes/{id}/lifecycle.
type lifecyclePayload struct {
	FromState string `json:"from_state"`
	ToState   string `json:"to_state"`
	Reason    string `json:"reason"`
}

// decisionEntryJSON is one decision in API responses.
type decisionEntryJSON struct {
	Cycle        int32  `json:"cycle"`
	ReceivedAt   string `json:"received_at"`
	SnapshotJSON string `json:"snapshot_json"`
}

// decisionsResponse is returned by GET /api/v1/nodes/{id}/decisions.
type decisionsResponse struct {
	NodeID    string              `json:"node_id"`
	Decisions []decisionEntryJSON `json:"decisions"`
}

// decisionPayload is accepted by POST /api/v1/nodes/{id}/decisions.
type decisionPayload struct {
	Cycle        int32  `json:"cycle"`
	SnapshotJSON string `json:"snapshot_json"`
}

// nodeHealthJSON is returned by GET /api/v1/nodes/{id}/health.
type nodeHealthJSON struct {
	NodeID     string                           `json:"node_id"`
	Score      int                              `json:"score"`
	Components observability.NodeHealthComponents `json:"components"`
	State      string                           `json:"state"`
	ComputedAt string                           `json:"computed_at"`
}

// platformNodeJSON is one node entry in GET /api/v1/platform/status.
type platformNodeJSON struct {
	NodeID   string `json:"node_id"`
	Score    int    `json:"score"`
	State    string `json:"state"`
	LastSeen string `json:"last_seen"`
}

// platformAlertJSON is one alert in GET /api/v1/platform/status.
type platformAlertJSON struct {
	NodeID    string `json:"node_id"`
	AlertType string `json:"alert_type"`
	Message   string `json:"message"`
}

// platformStatusJSON is returned by GET /api/v1/platform/status.
type platformStatusJSON struct {
	Nodes         []platformNodeJSON  `json:"nodes"`
	Alerts        []platformAlertJSON `json:"alerts"`
	TotalTrades   int                 `json:"total_trades"`
	TotalPnL      float64             `json:"total_pnl"`
	UptimeSeconds float64             `json:"uptime_seconds"`
	AsOf          string              `json:"as_of"`
}

// ── Lifecycle handlers ────────────────────────────────────────────────────────

func (h *Handler) handlePostLifecycle(w http.ResponseWriter, r *http.Request) {
	if h.lifecycle == nil {
		http.Error(w, "lifecycle store not configured", http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("id")
	var p lifecyclePayload
	if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
		http.Error(w, "invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	h.lifecycle.RecordEvent(heartbeat.LifecycleEvent{
		NodeID:    nodeID,
		FromState: parseLifecycleState(p.FromState),
		ToState:   parseLifecycleState(p.ToState),
		Reason:    p.Reason,
		Timestamp: time.Now(),
	})
	writeJSON(w, map[string]any{"acknowledged": true})
}

func (h *Handler) handleGetLifecycle(w http.ResponseWriter, r *http.Request) {
	if h.lifecycle == nil {
		http.Error(w, "lifecycle store not configured", http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("id")
	events := h.lifecycle.GetEvents(nodeID)
	out := make([]lifecycleEventJSON, 0, len(events))
	for _, ev := range events {
		out = append(out, lifecycleEventJSON{
			FromState: ev.FromState.String(),
			ToState:   ev.ToState.String(),
			Reason:    ev.Reason,
			Timestamp: ev.Timestamp.UTC().Format(time.RFC3339),
		})
	}
	writeJSON(w, lifecycleResponse{NodeID: nodeID, Events: out})
}

// ── Decision handlers ─────────────────────────────────────────────────────────

func (h *Handler) handlePostDecision(w http.ResponseWriter, r *http.Request) {
	if h.decisions == nil {
		http.Error(w, "decision store not configured", http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("id")
	var p decisionPayload
	if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
		http.Error(w, "invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}
	h.decisions.RecordDecision(heartbeat.DecisionEntry{
		NodeID:       nodeID,
		Cycle:        p.Cycle,
		ReceivedAt:   time.Now(),
		SnapshotJSON: p.SnapshotJSON,
	})
	writeJSON(w, map[string]any{"acknowledged": true})
}

func (h *Handler) handleGetDecisions(w http.ResponseWriter, r *http.Request) {
	if h.decisions == nil {
		http.Error(w, "decision store not configured", http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("id")
	entries := h.decisions.GetDecisions(nodeID)
	out := make([]decisionEntryJSON, 0, len(entries))
	for _, e := range entries {
		out = append(out, decisionEntryJSON{
			Cycle:        e.Cycle,
			ReceivedAt:   e.ReceivedAt.UTC().Format(time.RFC3339),
			SnapshotJSON: e.SnapshotJSON,
		})
	}
	writeJSON(w, decisionsResponse{NodeID: nodeID, Decisions: out})
}

func (h *Handler) handleGetDecisionByCycle(w http.ResponseWriter, r *http.Request) {
	if h.decisions == nil {
		http.Error(w, "decision store not configured", http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("id")
	cycleStr := r.PathValue("cycle")
	cycleN, err := strconv.ParseInt(cycleStr, 10, 32)
	if err != nil {
		http.Error(w, "invalid cycle: "+cycleStr, http.StatusBadRequest)
		return
	}
	entry, ok := h.decisions.GetDecisionByCycle(nodeID, int32(cycleN))
	if !ok {
		http.Error(w, "cycle not found", http.StatusNotFound)
		return
	}
	writeJSON(w, decisionEntryJSON{
		Cycle:        entry.Cycle,
		ReceivedAt:   entry.ReceivedAt.UTC().Format(time.RFC3339),
		SnapshotJSON: entry.SnapshotJSON,
	})
}

// ── Health handler ────────────────────────────────────────────────────────────

func (h *Handler) handleNodeHealth(w http.ResponseWriter, r *http.Request) {
	nodeID := r.PathValue("id")
	entry, ok := h.store.GetNode(nodeID)
	if !ok {
		http.Error(w, "node not found", http.StatusNotFound)
		return
	}
	scorer := h.scorer
	if scorer == nil {
		scorer = observability.NewNodeHealthScorer()
	}
	result := scorer.Score(entry)
	writeJSON(w, nodeHealthJSON{
		NodeID:     result.NodeID,
		Score:      result.Score.Total,
		Components: result.Score,
		State:      result.State,
		ComputedAt: result.ComputedAt.UTC().Format(time.RFC3339),
	})
}

// ── Platform status handler ───────────────────────────────────────────────────

func (h *Handler) handlePlatformStatus(w http.ResponseWriter, r *http.Request) {
	scorer := h.scorer
	if scorer == nil {
		scorer = observability.NewNodeHealthScorer()
	}

	entries := h.store.ListNodes()
	nodes := make([]platformNodeJSON, 0, len(entries))
	alerts := []platformAlertJSON{}
	totalTrades := 0
	totalPnL := 0.0
	now := time.Now()

	for _, e := range entries {
		result := scorer.Score(e)
		lastSeen := ""
		if !e.LastSeen.IsZero() {
			lastSeen = e.LastSeen.UTC().Format(time.RFC3339)
		}
		nodes = append(nodes, platformNodeJSON{
			NodeID:   e.NodeID,
			Score:    result.Score.Total,
			State:    result.State,
			LastSeen: lastSeen,
		})

		totalTrades += cpIntMetric(e.Metrics, "closed_trades")
		totalPnL += cpFloatMetric(e.Metrics, "pnl")

		// Stale alert
		if !e.LastSeen.IsZero() && now.Sub(e.LastSeen) > heartbeat.StaleAfter {
			alerts = append(alerts, platformAlertJSON{
				NodeID:    e.NodeID,
				AlertType: "STALE_NODE",
				Message:   "no heartbeat for >" + heartbeat.StaleAfter.String(),
			})
		}
		// Degraded health alert
		if result.Score.Total < 40 {
			alerts = append(alerts, platformAlertJSON{
				NodeID:    e.NodeID,
				AlertType: "DEGRADED_HEALTH",
				Message:   "health score " + strconv.Itoa(result.Score.Total) + "/100",
			})
		}
		// No-trade alert (active node with zero closed trades)
		if cpIntMetric(e.Metrics, "closed_trades") == 0 &&
			!e.LastSeen.IsZero() && now.Sub(e.LastSeen) < heartbeat.StaleAfter {
			alerts = append(alerts, platformAlertJSON{
				NodeID:    e.NodeID,
				AlertType: "NO_TRADES",
				Message:   "node active but zero closed trades",
			})
		}
	}

	writeJSON(w, platformStatusJSON{
		Nodes:         nodes,
		Alerts:        alerts,
		TotalTrades:   totalTrades,
		TotalPnL:      totalPnL,
		UptimeSeconds: now.Sub(h.startTime).Seconds(),
		AsOf:          now.UTC().Format(time.RFC3339),
	})
}

// ── Lifecycle state parser ────────────────────────────────────────────────────

func parseLifecycleState(s string) heartbeat.LifecycleState {
	switch s {
	case "STARTING":
		return heartbeat.StateStarting
	case "WARMING_UP":
		return heartbeat.StateWarmingUp
	case "RUNNING":
		return heartbeat.StateRunning
	case "DEGRADED":
		return heartbeat.StateDegraded
	case "STOPPED":
		return heartbeat.StateStopped
	default:
		return heartbeat.StateUnknown
	}
}

// ── Extra metric helpers ──────────────────────────────────────────────────────

func cpIntMetric(m map[string]string, key string) int {
	v, ok := m[key]
	if !ok {
		return 0
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return 0
	}
	return n
}

func cpFloatMetric(m map[string]string, key string) float64 {
	v, ok := m[key]
	if !ok {
		return 0
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return 0
	}
	return f
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("controlplane: JSON encode error", "err", err)
	}
}

func healthName(h omegav1.NodeHealth) string {
	switch h {
	case omegav1.NodeHealth_NODE_HEALTH_HEALTHY:
		return "healthy"
	case omegav1.NodeHealth_NODE_HEALTH_DEGRADED:
		return "degraded"
	case omegav1.NodeHealth_NODE_HEALTH_STALE:
		return "stale"
	case omegav1.NodeHealth_NODE_HEALTH_DEAD:
		return "dead"
	default:
		return "unknown"
	}
}

func parseHealth(s string) omegav1.NodeHealth {
	switch s {
	case "healthy":
		return omegav1.NodeHealth_NODE_HEALTH_HEALTHY
	case "degraded":
		return omegav1.NodeHealth_NODE_HEALTH_DEGRADED
	case "stale":
		return omegav1.NodeHealth_NODE_HEALTH_STALE
	case "dead":
		return omegav1.NodeHealth_NODE_HEALTH_DEAD
	default:
		return omegav1.NodeHealth_NODE_HEALTH_HEALTHY
	}
}
