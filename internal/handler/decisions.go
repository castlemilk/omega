package handler

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/benebsworth/omega/internal/db"
)

// handleDecisions serves GET /api/v1/dashboard/decisions?limit=N
// Returns the latest N decision snapshots ordered by cycle desc.
func (h *DashboardHandler) handleDecisions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	limit := 50
	if l := r.URL.Query().Get("limit"); l != "" {
		if n, err := strconv.Atoi(l); err == nil && n > 0 && n <= 500 {
			limit = n
		}
	}

	vdb := db.NewVictoria(h.db.StateDB())
	snapshots, err := vdb.GetDecisionSnapshots(limit)
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	type responseRow struct {
		ID         int64           `json:"id"`
		Cycle      int             `json:"cycle"`
		Version    string          `json:"version"`
		Regime     string          `json:"regime"`
		SitOut     string          `json:"sit_out"`
		RecordedAt string          `json:"recorded_at"`
		Payload    json.RawMessage `json:"payload"`
	}

	rows := make([]responseRow, 0, len(snapshots))
	for _, s := range snapshots {
		rows = append(rows, responseRow{
			ID:         s.ID,
			Cycle:      s.Cycle,
			Version:    s.Version,
			Regime:     s.Regime,
			SitOut:     s.SitOut,
			RecordedAt: s.RecordedAt,
			Payload:    s.Payload,
		})
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"decisions": rows,
		"count":     len(rows),
	})
}

// handleDecision serves GET /api/v1/dashboard/decisions/{cycle}
// Returns the full decision snapshot for a specific cycle.
func (h *DashboardHandler) handleDecision(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract cycle from path: /api/v1/dashboard/decisions/{cycle}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/dashboard/decisions/"), "/")
	if len(parts) == 0 || parts[0] == "" {
		http.Error(w, "cycle required", http.StatusBadRequest)
		return
	}
	cycle, err := strconv.Atoi(parts[0])
	if err != nil {
		http.Error(w, "invalid cycle", http.StatusBadRequest)
		return
	}

	vdb := db.NewVictoria(h.db.StateDB())
	snap, err := vdb.GetDecisionSnapshotByCycle(cycle)
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if snap == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"id":          snap.ID,
		"cycle":       snap.Cycle,
		"version":     snap.Version,
		"regime":      snap.Regime,
		"sit_out":     snap.SitOut,
		"recorded_at": snap.RecordedAt,
		"payload":     snap.Payload,
	})
}
