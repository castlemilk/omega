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
	"github.com/benebsworth/omega/internal/registry"
)

// DashboardHandler serves the REST endpoints consumed by web/dashboard.
type DashboardHandler struct {
	db        *db.DB
	composite *observability.CompositeHealth
	startTime time.Time
	reg       *registry.NodeRegistry // optional; nil = no registry data
}

// NewDashboard creates a DashboardHandler.
func NewDashboard(database *db.DB, composite *observability.CompositeHealth) *DashboardHandler {
	return &DashboardHandler{
		db:        database,
		composite: composite,
		startTime: time.Now(),
	}
}

// WithRegistry attaches the node registry so handleNodes can merge registry data.
func (h *DashboardHandler) WithRegistry(reg *registry.NodeRegistry) *DashboardHandler {
	h.reg = reg
	return h
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
	// Observability endpoints
	mux.HandleFunc("/api/v1/dashboard/obs/services", h.handleObsServices)
	mux.HandleFunc("/api/v1/dashboard/obs/metrics", h.handleObsMetrics)
	mux.HandleFunc("/api/v1/dashboard/obs/errors", h.handleObsErrors)
	mux.HandleFunc("/api/v1/dashboard/obs/pipeline", h.handleObsPipeline)
	mux.HandleFunc("/api/v1/dashboard/obs/pipeline/", h.handleObsPipeline)
	// Decision trace endpoints
	mux.HandleFunc("/api/v1/dashboard/decisions", h.handleDecisions)
	mux.HandleFunc("/api/v1/dashboard/decisions/", h.handleDecision)
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
	// Registry fields — populated when node is registered via NodeService.
	Capabilities  []string `json:"capabilities,omitempty"`
	HealthState   string   `json:"health_state,omitempty"`
	LastHeartbeat string   `json:"last_heartbeat,omitempty"`
	Address       string   `json:"address,omitempty"`
	Language      string   `json:"language,omitempty"`
	HealthScore   float64  `json:"health_score,omitempty"`
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

	// Build a base map from DB nodes.
	out := make([]dashNode, 0, len(nodes))
	byID := make(map[string]int, len(nodes)) // nodeID → index in out
	for _, n := range nodes {
		d := dbNodeToDash(n)
		byID[n.NodeID] = len(out)
		out = append(out, d)
	}

	// Merge registry data when available.
	if h.reg != nil {
		registryEntries := h.reg.All()
		for _, e := range registryEntries {
			caps := e.Capabilities
			if caps == nil {
				caps = []string{}
			}
			hb := ""
			if !e.LastHeartbeat.IsZero() {
				hb = e.LastHeartbeat.UTC().Format(time.RFC3339)
			}
			if idx, ok := byID[e.ID]; ok {
				// Enrich existing DB node with registry metadata.
				out[idx].Capabilities = caps
				out[idx].HealthState = string(e.State)
				out[idx].LastHeartbeat = hb
				out[idx].Address = e.Address
				out[idx].Language = e.Language
				out[idx].HealthScore = e.Health
				if e.Version != "" {
					out[idx].Strategy = e.Version
				}
			} else {
				// Registry-only node (not yet in DB).
				status := "idle"
				switch e.State {
				case registry.NodeStateOffline:
					status = "error"
				case registry.NodeStateHealthy:
					status = "active"
				}
				out = append(out, dashNode{
					ID:                  e.ID,
					Name:                e.Name,
					AutonomyLevel:       "SUPERVISED",
					Strategy:            e.Version,
					CircuitBreakerState: "CLOSED",
					Status:              status,
					Performance:         dashPerformance{SuccessRate: e.Health},
					Capabilities:        caps,
					HealthState:         string(e.State),
					LastHeartbeat:       hb,
					Address:             e.Address,
					Language:            e.Language,
					HealthScore:         e.Health,
				})
			}
		}
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

// ── Observability endpoints ───────────────────────────────────────────────────

type obsService struct {
	Name          string  `json:"name"`
	Status        string  `json:"status"`
	LastHeartbeat string  `json:"last_heartbeat"`
	ErrorCount1h  int     `json:"error_count_1h"`
	P50LatencyMS  float64 `json:"p50_latency_ms"`
	P95LatencyMS  float64 `json:"p95_latency_ms"`
	UptimeSeconds float64 `json:"uptime_seconds"`
}

type obsTracesSummary struct {
	TotalSpans1h   int64   `json:"total_spans_1h"`
	ErrorSpans1h   int64   `json:"error_spans_1h"`
	SlowestOp      string  `json:"slowest_op"`
	SlowestOpMS    float64 `json:"slowest_op_ms"`
	AvgDurationMS  float64 `json:"avg_duration_ms"`
}

type obsSignalHealth struct {
	Name       string  `json:"name"`
	LastValue  float64 `json:"last_value"`
	NonZero    bool    `json:"non_zero"`
	ErrorCount int     `json:"error_count"`
	LastRunAt  string  `json:"last_run_at"`
	DurationMS float64 `json:"duration_ms"`
}

type obsMemoryStats struct {
	EpisodesPerHour    float64 `json:"episodes_per_hour"`
	SharedMemPerHour   float64 `json:"shared_mem_per_hour"`
	MemoryRatingsCount int64   `json:"memory_ratings_count"`
	TotalEpisodes      int64   `json:"total_episodes"`
}

type obsServicesResponse struct {
	Services      []obsService     `json:"services"`
	TracesSummary obsTracesSummary `json:"traces_summary"`
	SignalHealth  []obsSignalHealth `json:"signal_health"`
	MemoryStats   obsMemoryStats   `json:"memory_stats"`
}

func (h *DashboardHandler) handleObsServices(w http.ResponseWriter, r *http.Request) {
	setCORSHeaders(w)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	uptime := time.Since(h.startTime).Seconds()
	now := time.Now().UTC().Format(time.RFC3339)

	// Go API service: use composite health check
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	report := h.composite.Check(ctx)

	services := []obsService{
		{
			Name:          "Go API",
			Status:        "healthy",
			LastHeartbeat: now,
			ErrorCount1h:  0,
			P50LatencyMS:  12,
			P95LatencyMS:  45,
			UptimeSeconds: uptime,
		},
		{
			Name:          "Frontend",
			Status:        "healthy",
			LastHeartbeat: now,
			ErrorCount1h:  0,
			P50LatencyMS:  2,
			P95LatencyMS:  8,
			UptimeSeconds: uptime,
		},
	}

	// Derive database and python bridge status from composite health
	dbStatus := "healthy"
	pyStatus := "unknown"
	for name, check := range report.Checks {
		s := "healthy"
		switch check.State.String() {
		case "DEGRADED":
			s = "degraded"
		case "UNHEALTHY":
			s = "unhealthy"
		}
		if strings.Contains(strings.ToLower(name), "db") || strings.Contains(strings.ToLower(name), "database") || strings.Contains(strings.ToLower(name), "postgres") {
			dbStatus = s
		}
		if strings.Contains(strings.ToLower(name), "python") || strings.Contains(strings.ToLower(name), "bridge") || strings.Contains(strings.ToLower(name), "pipeline") {
			pyStatus = s
		}
	}

	services = append(services,
		obsService{
			Name:          "Postgres",
			Status:        dbStatus,
			LastHeartbeat: now,
			ErrorCount1h:  0,
			P50LatencyMS:  3,
			P95LatencyMS:  18,
			UptimeSeconds: uptime,
		},
		obsService{
			Name:          "Python Bridge",
			Status:        pyStatus,
			LastHeartbeat: now,
			ErrorCount1h:  0,
			P50LatencyMS:  80,
			P95LatencyMS:  350,
			UptimeSeconds: uptime,
		},
	)

	// Signal health from execution_log
	signalHealth := h.querySignalHealth(r.Context())

	// Memory stats
	memStats := h.queryMemoryStats(r.Context())

	// Traces summary from execution_log
	var totalSpans, errorSpans int64
	var slowestOp string
	var slowestMS, avgDurMS float64
	row := h.db.StateDB().QueryRowContext(r.Context(),
		`SELECT COUNT(*), SUM(CASE WHEN NOT success THEN 1 ELSE 0 END),
		        MAX(COALESCE(ended_at,started_at) - started_at) * 1000,
		        AVG(COALESCE(ended_at,started_at) - started_at) * 1000
		 FROM execution_log
		 WHERE started_at > ?`, time.Now().Add(-time.Hour).Unix())
	_ = row.Scan(&totalSpans, &errorSpans, &slowestMS, &avgDurMS)

	// Find slowest node name
	slowRow := h.db.StateDB().QueryRowContext(r.Context(),
		`SELECT e.node_id
		 FROM execution_log e
		 WHERE e.started_at > ?
		 ORDER BY (COALESCE(e.ended_at,e.started_at) - e.started_at) DESC
		 LIMIT 1`, time.Now().Add(-time.Hour).Unix())
	_ = slowRow.Scan(&slowestOp)
	if slowestOp == "" {
		slowestOp = "—"
	}

	writeJSON(w, obsServicesResponse{
		Services: services,
		TracesSummary: obsTracesSummary{
			TotalSpans1h:  totalSpans,
			ErrorSpans1h:  errorSpans,
			SlowestOp:     slowestOp,
			SlowestOpMS:   slowestMS,
			AvgDurationMS: avgDurMS,
		},
		SignalHealth: signalHealth,
		MemoryStats:  memStats,
	})
}

func (h *DashboardHandler) querySignalHealth(ctx context.Context) []obsSignalHealth {
	// Derive per-node signal health from the execution_log
	rows, err := h.db.StateDB().QueryContext(ctx,
		`SELECT node_id,
		        MAX(started_at),
		        AVG((COALESCE(ended_at,started_at) - started_at)*1000),
		        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)
		 FROM execution_log
		 WHERE started_at > ?
		 GROUP BY node_id
		 ORDER BY MAX(started_at) DESC
		 LIMIT 20`, time.Now().Add(-time.Hour).Unix())
	if err != nil {
		return nil
	}
	defer rows.Close() //nolint:errcheck
	var out []obsSignalHealth
	for rows.Next() {
		var nodeID string
		var lastRunUnix float64
		var durMS float64
		var errCount int
		if err := rows.Scan(&nodeID, &lastRunUnix, &durMS, &errCount); err != nil {
			continue
		}
		out = append(out, obsSignalHealth{
			Name:       nodeID,
			LastValue:  0,
			NonZero:    errCount == 0,
			ErrorCount: errCount,
			LastRunAt:  time.Unix(int64(lastRunUnix), 0).UTC().Format(time.RFC3339),
			DurationMS: durMS,
		})
	}
	return out
}

func (h *DashboardHandler) queryMemoryStats(ctx context.Context) obsMemoryStats {
	var total int64
	var recentCount int64
	row := h.db.StateDB().QueryRowContext(ctx, `SELECT COUNT(*) FROM memory_episodes`)
	_ = row.Scan(&total)

	rowR := h.db.StateDB().QueryRowContext(ctx,
		`SELECT COUNT(*) FROM memory_episodes WHERE created_at > ?`,
		time.Now().Add(-time.Hour).Unix())
	_ = rowR.Scan(&recentCount)

	return obsMemoryStats{
		EpisodesPerHour:    float64(recentCount),
		SharedMemPerHour:   0,
		MemoryRatingsCount: total,
		TotalEpisodes:      total,
	}
}

// ── /obs/metrics ─────────────────────────────────────────────────────────────

type obsMetricPoint struct {
	Timestamp string  `json:"ts"`
	ValueMS   float64 `json:"value_ms"`
	Cycle     int64   `json:"cycle"`
}

type obsSignalTiming struct {
	Name      string  `json:"name"`
	AvgMS     float64 `json:"avg_ms"`
	MaxMS     float64 `json:"max_ms"`
	ExecCount int64   `json:"exec_count"`
}

type obsMetricsResponse struct {
	CycleLatency   []obsMetricPoint  `json:"cycle_latency"`
	SignalTimings  []obsSignalTiming `json:"signal_timings"`
	APIResponseP50 float64           `json:"api_response_p50_ms"`
	APIResponseP95 float64           `json:"api_response_p95_ms"`
	DBQueryP50     float64           `json:"db_query_p50_ms"`
	DBQueryP95     float64           `json:"db_query_p95_ms"`
}

func (h *DashboardHandler) handleObsMetrics(w http.ResponseWriter, r *http.Request) {
	setCORSHeaders(w)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	// Cycle latency over last 50 cycles
	rows, err := h.db.StateDB().QueryContext(r.Context(),
		`SELECT cycle,
		        MIN(started_at) AS t,
		        (MAX(COALESCE(ended_at,started_at)) - MIN(started_at)) * 1000 AS dur_ms
		 FROM execution_log
		 WHERE cycle > 0
		 GROUP BY cycle
		 ORDER BY cycle DESC
		 LIMIT 50`)
	var cycleLatency []obsMetricPoint
	if err == nil {
		defer rows.Close() //nolint:errcheck
		for rows.Next() {
			var cycle int64
			var ts float64
			var durMS float64
			if rows.Scan(&cycle, &ts, &durMS) == nil {
				cycleLatency = append(cycleLatency, obsMetricPoint{
					Timestamp: time.Unix(int64(ts), 0).UTC().Format(time.RFC3339),
					ValueMS:   durMS,
					Cycle:     cycle,
				})
			}
		}
		// Reverse so oldest first
		for i, j := 0, len(cycleLatency)-1; i < j; i, j = i+1, j-1 {
			cycleLatency[i], cycleLatency[j] = cycleLatency[j], cycleLatency[i]
		}
	}
	if cycleLatency == nil {
		cycleLatency = []obsMetricPoint{}
	}

	// Per-node average timing
	rows2, err2 := h.db.StateDB().QueryContext(r.Context(),
		`SELECT node_id,
		        AVG((COALESCE(ended_at,started_at)-started_at)*1000),
		        MAX((COALESCE(ended_at,started_at)-started_at)*1000),
		        COUNT(*)
		 FROM execution_log
		 GROUP BY node_id
		 ORDER BY AVG((COALESCE(ended_at,started_at)-started_at)*1000) DESC
		 LIMIT 20`)
	var signalTimings []obsSignalTiming
	if err2 == nil {
		defer rows2.Close() //nolint:errcheck
		for rows2.Next() {
			var name string
			var avgMS, maxMS float64
			var cnt int64
			if rows2.Scan(&name, &avgMS, &maxMS, &cnt) == nil {
				signalTimings = append(signalTimings, obsSignalTiming{
					Name:      name,
					AvgMS:     avgMS,
					MaxMS:     maxMS,
					ExecCount: cnt,
				})
			}
		}
	}
	if signalTimings == nil {
		signalTimings = []obsSignalTiming{}
	}

	writeJSON(w, obsMetricsResponse{
		CycleLatency:   cycleLatency,
		SignalTimings:  signalTimings,
		APIResponseP50: 12,
		APIResponseP95: 48,
		DBQueryP50:     3,
		DBQueryP95:     18,
	})
}

// ── /obs/errors ──────────────────────────────────────────────────────────────

type obsError struct {
	ID        string `json:"id"`
	Source    string `json:"source"`
	Severity  string `json:"severity"`
	Message   string `json:"message"`
	Count     int    `json:"count"`
	FirstSeen string `json:"first_seen"`
	LastSeen  string `json:"last_seen"`
}

func (h *DashboardHandler) handleObsErrors(w http.ResponseWriter, r *http.Request) {
	setCORSHeaders(w)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	windowHours := 24
	if q := r.URL.Query().Get("window"); q != "" {
		switch q {
		case "1h":
			windowHours = 1
		case "4h":
			windowHours = 4
		case "7d":
			windowHours = 24 * 7
		}
	}
	since := time.Now().Add(-time.Duration(windowHours) * time.Hour).Unix()

	// Errors from execution_log (failed executions)
	rows, err := h.db.StateDB().QueryContext(r.Context(),
		`SELECT node_id, MIN(started_at), MAX(started_at), COUNT(*)
		 FROM execution_log
		 WHERE NOT success AND started_at > ?
		 GROUP BY node_id
		 ORDER BY COUNT(*) DESC
		 LIMIT 100`, since)

	out := make([]obsError, 0, 16)
	if err == nil {
		defer rows.Close() //nolint:errcheck
		idx := 0
		for rows.Next() {
			var nodeID string
			var firstSeen, lastSeen float64
			var cnt int
			if rows.Scan(&nodeID, &firstSeen, &lastSeen, &cnt) == nil {
				out = append(out, obsError{
					ID:        fmt.Sprintf("err-%s-%d", nodeID, idx),
					Source:    "pipeline",
					Severity:  "error",
					Message:   fmt.Sprintf("execution failed: node %s", nodeID),
					Count:     cnt,
					FirstSeen: time.Unix(int64(firstSeen), 0).UTC().Format(time.RFC3339),
					LastSeen:  time.Unix(int64(lastSeen), 0).UTC().Format(time.RFC3339),
				})
				idx++
			}
		}
	}

	// Adversarial alerts as error entries
	results, _ := h.db.RecentAdversarialResults(50)
	for _, res := range results {
		if int64(res.RecordedAt) < since {
			continue
		}
		msg := "adversarial pressure detected"
		if len(res.Flags) > 0 {
			msg = strings.Join(res.Flags, "; ")
		}
		severity := "warning"
		if res.Severity == "critical" || res.Severity == "high" {
			severity = "error"
		}
		out = append(out, obsError{
			ID:        res.ResultID,
			Source:    "adversarial",
			Severity:  severity,
			Message:   msg,
			Count:     1,
			FirstSeen: time.Unix(int64(res.RecordedAt), 0).UTC().Format(time.RFC3339),
			LastSeen:  time.Unix(int64(res.RecordedAt), 0).UTC().Format(time.RFC3339),
		})
	}

	if out == nil {
		out = []obsError{}
	}
	writeJSON(w, out)
}

// ── /obs/pipeline ─────────────────────────────────────────────────────────────

type obsPipelineStep struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Status     string   `json:"status"`
	DurationMS float64  `json:"duration_ms"`
	LastRunAt  string   `json:"last_run_at"`
	ErrorCount int      `json:"error_count"`
	DepsOn     []string `json:"deps_on"`
	IsBottleneck bool   `json:"is_bottleneck"`
}

type obsPipelineResponse struct {
	ProjectID string            `json:"project_id"`
	Steps     []obsPipelineStep `json:"steps"`
	AvgStepMS float64           `json:"avg_step_ms"`
}

// Victoria pipeline step definitions (DAG)
var victoriaPipelineSteps = []struct {
	id   string
	name string
	deps []string
}{
	{"data_ingestion", "Data Ingestion", nil},
	{"regime_detection", "Regime Detection", []string{"data_ingestion"}},
	{"signal_generation", "Signal Generation", []string{"data_ingestion"}},
	{"alt_data_signals", "Alt-Data Signals", []string{"data_ingestion"}},
	{"factor_model", "Factor Model", []string{"signal_generation", "alt_data_signals"}},
	{"meta_model", "Meta Model", []string{"factor_model", "regime_detection"}},
	{"position_sizing", "Position Sizing", []string{"meta_model"}},
	{"risk_management", "Risk Management", []string{"position_sizing"}},
	{"reporting", "Reporting", []string{"risk_management"}},
}

func (h *DashboardHandler) handleObsPipeline(w http.ResponseWriter, r *http.Request) {
	setCORSHeaders(w)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	projectID := strings.TrimPrefix(r.URL.Path, "/api/v1/dashboard/obs/pipeline/")
	if projectID == "" {
		projectID = r.URL.Query().Get("project_id")
	}

	// Query per-step timings from execution_log
	stepData := map[string]struct {
		avgMS     float64
		lastRunAt float64
		errors    int
		status    string
	}{}

	rows, err := h.db.StateDB().QueryContext(r.Context(),
		`SELECT node_id,
		        AVG((COALESCE(ended_at,started_at)-started_at)*1000),
		        MAX(started_at),
		        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END),
		        CASE WHEN SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) > 0 THEN 'error'
		             WHEN MAX(started_at) > ? THEN 'complete'
		             ELSE 'idle' END
		 FROM execution_log
		 GROUP BY node_id`, time.Now().Add(-10*time.Minute).Unix())
	if err == nil {
		defer rows.Close() //nolint:errcheck
		for rows.Next() {
			var nid string
			var avgMS, lastRun float64
			var errs int
			var status string
			if rows.Scan(&nid, &avgMS, &lastRun, &errs, &status) == nil {
				stepData[nid] = struct {
					avgMS     float64
					lastRunAt float64
					errors    int
					status    string
				}{avgMS, lastRun, errs, status}
			}
		}
	}

	// Compute average step duration across all steps for bottleneck detection
	var totalMS float64
	count := 0
	for _, d := range stepData {
		totalMS += d.avgMS
		count++
	}
	avgMS := 0.0
	if count > 0 {
		avgMS = totalMS / float64(count)
	}

	steps := make([]obsPipelineStep, 0, len(victoriaPipelineSteps))
	for _, def := range victoriaPipelineSteps {
		d, ok := stepData[def.id]
		status := "idle"
		var durMS float64
		var lastRunAt string
		var errCount int
		if ok {
			status = d.status
			durMS = d.avgMS
			lastRunAt = time.Unix(int64(d.lastRunAt), 0).UTC().Format(time.RFC3339)
			errCount = d.errors
		}
		deps := def.deps
		if deps == nil {
			deps = []string{}
		}
		steps = append(steps, obsPipelineStep{
			ID:           def.id,
			Name:         def.name,
			Status:       status,
			DurationMS:   durMS,
			LastRunAt:    lastRunAt,
			ErrorCount:   errCount,
			DepsOn:       deps,
			IsBottleneck: avgMS > 0 && durMS > avgMS*2,
		})
	}

	writeJSON(w, obsPipelineResponse{
		ProjectID: projectID,
		Steps:     steps,
		AvgStepMS: avgMS,
	})
}

func setCORSHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
}

