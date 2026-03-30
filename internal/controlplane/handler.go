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
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/heartbeat"
)

// Handler serves the control-plane REST API.
type Handler struct {
	store  *heartbeat.Store
	logger *slog.Logger
}

// New creates a Handler backed by the given heartbeat store.
func New(store *heartbeat.Store, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{store: store, logger: logger}
}

// RegisterRoutes mounts all control-plane endpoints on mux.
func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/heartbeat", h.handleHeartbeat)
	mux.HandleFunc("/api/v1/diagnostics", h.handleDiagnostics)
	mux.HandleFunc("/api/v1/nodes", h.handleNodes)
	mux.HandleFunc("/api/v1/blockers", h.handleBlockers)
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
