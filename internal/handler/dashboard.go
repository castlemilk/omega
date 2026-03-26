// Package handler — REST dashboard handler for the web dashboard.
// Serves /api/v1/dashboard/* endpoints that the React frontend consumes.
package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/observability"
)

// DashboardHandler serves the REST endpoints consumed by web/dashboard.
type DashboardHandler struct {
	db        *db.DB
	composite *observability.CompositeHealth
	startTime time.Time
}

// NewDashboard creates a DashboardHandler.
func NewDashboard(database *db.DB, composite *observability.CompositeHealth) *DashboardHandler {
	return &DashboardHandler{
		db:        database,
		composite: composite,
		startTime: time.Now(),
	}
}

// RegisterRoutes mounts all dashboard endpoints on mux.
func (h *DashboardHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/dashboard/status", h.handleStatus)
	mux.HandleFunc("/api/v1/dashboard/nodes", h.handleNodes)
	mux.HandleFunc("/api/v1/dashboard/nodes/", h.handleNode)
	mux.HandleFunc("/api/v1/dashboard/cycles", h.handleCycles)
	mux.HandleFunc("/api/v1/dashboard/cycles/", h.handleCycle)
	mux.HandleFunc("/api/v1/dashboard/adversarial/alerts", h.handleAdversarialAlerts)
	mux.HandleFunc("/api/v1/dashboard/improvements", h.handleImprovements)
	mux.HandleFunc("/api/v1/dashboard/health", h.handleHealth)
	mux.HandleFunc("/api/v1/dashboard/events/stream", h.handleEventsStream)
}

// ── JSON response types (mirror web/dashboard/src/lib/api.ts) ─────────────────

type dashSystemStatus struct {
	Status               string             `json:"status"`
	TotalNodes           int64              `json:"total_nodes"`
	ActiveCycles         int64              `json:"active_cycles"`
	UptimeSeconds        float64            `json:"uptime_seconds"`
	AutonomyDistribution map[string]float64 `json:"autonomy_distribution"`
}

type dashNode struct {
	ID                  string          `json:"id"`
	Name                string          `json:"name"`
	AutonomyLevel       string          `json:"autonomy_level"`
	Strategy            string          `json:"strategy"`
	CircuitBreakerState string          `json:"circuit_breaker_state"`
	LastExecution       string          `json:"last_execution"`
	Status              string          `json:"status"`
	Performance         dashPerformance `json:"performance"`
}

type dashPerformance struct {
	AvgDurationMS   float64 `json:"avg_duration_ms"`
	SuccessRate     float64 `json:"success_rate"`
	TotalExecutions int64   `json:"total_executions"`
}

type dashCycle struct {
	ID                string  `json:"id"`
	StartedAt         string  `json:"started_at"`
	EndedAt           string  `json:"ended_at"`
	DurationMS        float64 `json:"duration_ms"`
	NodesExecuted     int     `json:"nodes_executed"`
	SafetyViolations  int     `json:"safety_violations"`
	AdversarialAlerts int     `json:"adversarial_alerts"`
	Improvements      int     `json:"improvements"`
	Status            string  `json:"status"`
}

type dashAdversarialAlert struct {
	ID        string `json:"id"`
	Ring      int32  `json:"ring"`
	Severity  string `json:"severity"`
	NodeID    string `json:"node_id"`
	Message   string `json:"message"`
	Timestamp string `json:"timestamp"`
}

type dashImprovement struct {
	ID               string  `json:"id"`
	NodeID           string  `json:"node_id"`
	StrategyFrom     string  `json:"strategy_from"`
	StrategyTo       string  `json:"strategy_to"`
	Timestamp        string  `json:"timestamp"`
	RolledBack       bool    `json:"rolled_back"`
	ImprovementDelta float64 `json:"improvement_delta"`
}

type dashComponentHealth struct {
	Name      string  `json:"name"`
	Status    string  `json:"status"`
	LatencyMS float64 `json:"latency_ms"`
	LastCheck string  `json:"last_check"`
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		http.Error(w, "encode error", http.StatusInternalServerError)
	}
}

// ── Handlers ──────────────────────────────────────────────────────────────────

func (h *DashboardHandler) handleStatus(w http.ResponseWriter, r *http.Request) {
	health, err := h.db.SystemHealth()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	status := "healthy"
	switch strings.ToUpper(health.Status) {
	case "UNHEALTHY":
		status = "critical"
	case "DEGRADED":
		status = "degraded"
	}

	writeJSON(w, dashSystemStatus{
		Status:        status,
		TotalNodes:    health.NodeCount,
		ActiveCycles:  health.TotalCycles,
		UptimeSeconds: time.Since(h.startTime).Seconds(),
		AutonomyDistribution: map[string]float64{
			"SUPERVISED": float64(health.NodeCount),
			"PICO":       0,
			"AUTONOMOUS": 0,
		},
	})
}

func (h *DashboardHandler) handleNodes(w http.ResponseWriter, r *http.Request) {
	nodes, err := h.db.AllNodes()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	out := make([]dashNode, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, dbNodeToDash(n))
	}
	writeJSON(w, out)
}

func (h *DashboardHandler) handleNode(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/dashboard/nodes/")
	if id == "" {
		h.handleNodes(w, r)
		return
	}
	n, err := h.db.GetNode(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	writeJSON(w, dbNodeToDash(n))
}

func dbNodeToDash(n *db.Node) dashNode {
	status := n.Status
	if status == "" {
		status = "idle"
	}
	lastExec := ""
	if n.LastExecution != nil {
		lastExec = time.Unix(int64(n.LastExecution.StartedAt), 0).UTC().Format(time.RFC3339)
	}
	successRate := 1.0 - n.ErrorRate
	if successRate < 0 {
		successRate = 0
	}
	return dashNode{
		ID:                  n.NodeID,
		Name:                n.Name,
		AutonomyLevel:       "SUPERVISED",
		Strategy:            n.Version,
		CircuitBreakerState: "CLOSED",
		LastExecution:       lastExec,
		Status:              status,
		Performance: dashPerformance{
			AvgDurationMS:   n.AvgLatencyMS,
			SuccessRate:     successRate,
			TotalExecutions: n.ExecutionsTotal,
		},
	}
}

func (h *DashboardHandler) handleCycles(w http.ResponseWriter, r *http.Request) {
	type cycleRow struct {
		cycle     int64
		startedAt float64
		endedAt   float64
		count     int
		errors    int
	}
	rows, err := h.db.StateDB().QueryContext(r.Context(), //nolint:gosec
		`SELECT cycle,
		       MIN(started_at),
		       MAX(COALESCE(ended_at, started_at)),
		       COUNT(*),
		       SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)
		FROM execution_log
		WHERE cycle > 0
		GROUP BY cycle
		ORDER BY cycle DESC
		LIMIT 50`)
	if err != nil {
		writeJSON(w, []dashCycle{})
		return
	}
	defer rows.Close() //nolint:errcheck

	out := make([]dashCycle, 0)
	for rows.Next() {
		var cr cycleRow
		if err := rows.Scan(&cr.cycle, &cr.startedAt, &cr.endedAt, &cr.count, &cr.errors); err != nil {
			continue
		}
		startT := time.Unix(int64(cr.startedAt), 0).UTC()
		endT := time.Unix(int64(cr.endedAt), 0).UTC()
		durMS := endT.Sub(startT).Seconds() * 1000
		status := "completed"
		if cr.errors > 0 {
			status = "failed"
		}
		out = append(out, dashCycle{
			ID:                fmt.Sprintf("cycle-%d", cr.cycle),
			StartedAt:         startT.Format(time.RFC3339),
			EndedAt:           endT.Format(time.RFC3339),
			DurationMS:        durMS,
			NodesExecuted:     cr.count,
			SafetyViolations:  0,
			AdversarialAlerts: 0,
			Improvements:      0,
			Status:            status,
		})
	}
	writeJSON(w, out)
}

func (h *DashboardHandler) handleCycle(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/dashboard/cycles/")
	if id == "" {
		h.handleCycles(w, r)
		return
	}
	http.Error(w, "not implemented", http.StatusNotImplemented)
}

func (h *DashboardHandler) handleAdversarialAlerts(w http.ResponseWriter, r *http.Request) {
	results, err := h.db.RecentAdversarialResults(20)
	if err != nil {
		writeJSON(w, []dashAdversarialAlert{})
		return
	}
	out := make([]dashAdversarialAlert, 0, len(results))
	for _, res := range results {
		msg := "adversarial pressure detected"
		if len(res.Flags) > 0 {
			msg = strings.Join(res.Flags, "; ")
		}
		out = append(out, dashAdversarialAlert{
			ID:        res.ResultID,
			Ring:      res.Ring,
			Severity:  res.Severity,
			NodeID:    "",
			Message:   msg,
			Timestamp: time.Unix(int64(res.RecordedAt), 0).UTC().Format(time.RFC3339),
		})
	}
	writeJSON(w, out)
}

func (h *DashboardHandler) handleImprovements(w http.ResponseWriter, r *http.Request) {
	imps, err := h.db.GetImprovements("", 50)
	if err != nil {
		writeJSON(w, []dashImprovement{})
		return
	}
	out := make([]dashImprovement, 0, len(imps))
	for _, imp := range imps {
		delta := 0.0
		if after, ok := imp.AfterMetrics["health"]; ok {
			if before, ok2 := imp.BeforeMetrics["health"]; ok2 {
				delta = after - before
			}
		}
		out = append(out, dashImprovement{
			ID:               imp.ImproveID,
			NodeID:           imp.NodeID,
			StrategyFrom:     imp.FromVersion,
			StrategyTo:       imp.ToVersion,
			Timestamp:        time.Unix(int64(imp.RecordedAt), 0).UTC().Format(time.RFC3339),
			RolledBack:       false,
			ImprovementDelta: delta,
		})
	}
	writeJSON(w, out)
}

func (h *DashboardHandler) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	report := h.composite.Check(ctx)

	out := make([]dashComponentHealth, 0, len(report.Checks))
	for name, status := range report.Checks {
		dashStatus := "healthy"
		switch status.State.String() {
		case "DEGRADED":
			dashStatus = "degraded"
		case "UNHEALTHY":
			dashStatus = "unhealthy"
		}
		out = append(out, dashComponentHealth{
			Name:      name,
			Status:    dashStatus,
			LatencyMS: 0,
			LastCheck: status.CheckedAt.UTC().Format(time.RFC3339),
		})
	}
	writeJSON(w, out)
}

func (h *DashboardHandler) handleEventsStream(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	// Initial connected event.
	fmt.Fprintf(w, "event: connected\ndata: {\"message\":\"connected\"}\n\n") //nolint:errcheck
	flusher.Flush()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
			health, _ := h.db.SystemHealth()
			if health == nil {
				continue
			}
			data, _ := json.Marshal(map[string]any{
				"type":      "heartbeat",
				"timestamp": time.Now().UTC().Format(time.RFC3339),
				"message":   fmt.Sprintf("cycles=%d nodes=%d", health.TotalCycles, health.NodeCount),
				"severity":  "info",
			})
			fmt.Fprintf(w, "event: heartbeat\ndata: %s\n\n", data) //nolint:errcheck
			flusher.Flush()
		}
	}
}

