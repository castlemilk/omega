package observability

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"runtime"
	"runtime/debug"
	"time"
)

// ---------------------------------------------------------------------------
// Runtime diagnostics
// ---------------------------------------------------------------------------

// RuntimeDiagnostics captures Go runtime internals.
type RuntimeDiagnostics struct {
	NumGoroutine int    `json:"num_goroutine"`
	NumCPU       int    `json:"num_cpu"`
	GOMAXPROCS   int    `json:"gomaxprocs"`

	// Memory stats
	HeapAllocBytes   uint64 `json:"heap_alloc_bytes"`
	HeapSysBytes     uint64 `json:"heap_sys_bytes"`
	HeapInuseBytes   uint64 `json:"heap_inuse_bytes"`
	HeapObjectsCount uint64 `json:"heap_objects_count"`
	StackInuseBytes  uint64 `json:"stack_inuse_bytes"`
	TotalAllocBytes  uint64 `json:"total_alloc_bytes"`

	// GC stats
	NumGC        uint32        `json:"num_gc"`
	LastGCPause  time.Duration `json:"last_gc_pause_ns"`
	LastGCAt     time.Time     `json:"last_gc_at"`
	GCCPUFraction float64      `json:"gc_cpu_fraction"`
}

// collectRuntime gathers current runtime metrics.
func collectRuntime() RuntimeDiagnostics {
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)

	var lastGCAt time.Time
	if ms.LastGC > 0 {
		lastGCAt = time.Unix(0, int64(ms.LastGC)) //nolint:gosec
	}

	return RuntimeDiagnostics{
		NumGoroutine:     runtime.NumGoroutine(),
		NumCPU:           runtime.NumCPU(),
		GOMAXPROCS:       runtime.GOMAXPROCS(0),
		HeapAllocBytes:   ms.HeapAlloc,
		HeapSysBytes:     ms.HeapSys,
		HeapInuseBytes:   ms.HeapInuse,
		HeapObjectsCount: ms.HeapObjects,
		StackInuseBytes:  ms.StackInuse,
		TotalAllocBytes:  ms.TotalAlloc,
		NumGC:            ms.NumGC,
		LastGCPause:      time.Duration(ms.PauseNs[(ms.NumGC+255)%256]), //nolint:gosec // runtime GC pause fits in int64
		LastGCAt:         lastGCAt,
		GCCPUFraction:    ms.GCCPUFraction,
	}
}

// ---------------------------------------------------------------------------
// Build info
// ---------------------------------------------------------------------------

// BuildInfo captures the module version and VCS info embedded by go build.
type BuildInfo struct {
	GoVersion string `json:"go_version"`
	Module    string `json:"module"`
	Version   string `json:"version"`
	Revision  string `json:"revision"`
	DirtyBuild bool  `json:"dirty_build"`
}

func collectBuildInfo() BuildInfo {
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return BuildInfo{GoVersion: runtime.Version()}
	}
	info := BuildInfo{
		GoVersion: bi.GoVersion,
		Module:    bi.Main.Path,
		Version:   bi.Main.Version,
	}
	for _, s := range bi.Settings {
		switch s.Key {
		case "vcs.revision":
			info.Revision = s.Value
		case "vcs.modified":
			info.DirtyBuild = s.Value == "true"
		}
	}
	return info
}

// ---------------------------------------------------------------------------
// Node diagnostics
// ---------------------------------------------------------------------------

// NodeDiagnostics holds per-node runtime observations.
type NodeDiagnostics struct {
	NodeID        string        `json:"node_id"`
	LastCycleAt   time.Time     `json:"last_cycle_at"`
	ErrorRate     float64       `json:"error_rate"`
	AutonomyLevel float64       `json:"autonomy_level"`
	CircuitState  string        `json:"circuit_state"`
	CycleCount    int64         `json:"cycle_count"`
	AvgLatencyMs  float64       `json:"avg_latency_ms"`
}

// NodeDiagnosticsProvider can be implemented by the orchestrator to surface
// live node state for diagnostics.
type NodeDiagnosticsProvider interface {
	NodeDiagnostics(ctx context.Context) []NodeDiagnostics
}

// ---------------------------------------------------------------------------
// Framework diagnostics
// ---------------------------------------------------------------------------

// FrameworkDiagnostics holds subsystem-level observations.
type FrameworkDiagnostics struct {
	DBStateHealthy  bool   `json:"db_state_healthy"`
	DBMemoryHealthy bool   `json:"db_memory_healthy"`
	EventQueueDepth int    `json:"event_queue_depth"` // sum of all subscriber backlog
	ActiveNodes     int    `json:"active_nodes"`
}

// FrameworkDiagnosticsProvider can be implemented by the API layer.
type FrameworkDiagnosticsProvider interface {
	FrameworkDiagnostics(ctx context.Context) FrameworkDiagnostics
}

// ---------------------------------------------------------------------------
// DiagnosticsReport — full snapshot
// ---------------------------------------------------------------------------

// DiagnosticsReport is the full diagnostic snapshot returned by the HTTP endpoint.
type DiagnosticsReport struct {
	CollectedAt time.Time            `json:"collected_at"`
	Build       BuildInfo            `json:"build"`
	Runtime     RuntimeDiagnostics   `json:"runtime"`
	Nodes       []NodeDiagnostics    `json:"nodes,omitempty"`
	Framework   *FrameworkDiagnostics `json:"framework,omitempty"`
	CircuitBreakers map[string]string `json:"circuit_breakers,omitempty"`
}

// ---------------------------------------------------------------------------
// DiagnosticsCollector
// ---------------------------------------------------------------------------

// DiagnosticsCollector assembles the full diagnostics report.
type DiagnosticsCollector struct {
	nodeProvider NodeDiagnosticsProvider      // optional
	fwProvider   FrameworkDiagnosticsProvider // optional
	cbRegistry   *CircuitBreakerRegistry      // optional
	logger       *slog.Logger
}

// NewDiagnosticsCollector creates a collector. All arguments are optional (may be nil).
func NewDiagnosticsCollector(
	nodeProvider NodeDiagnosticsProvider,
	fwProvider FrameworkDiagnosticsProvider,
	cbRegistry *CircuitBreakerRegistry,
	logger *slog.Logger,
) *DiagnosticsCollector {
	if logger == nil {
		logger = slog.Default()
	}
	return &DiagnosticsCollector{
		nodeProvider: nodeProvider,
		fwProvider:   fwProvider,
		cbRegistry:   cbRegistry,
		logger:       logger,
	}
}

// Collect assembles a fresh DiagnosticsReport.
func (d *DiagnosticsCollector) Collect(ctx context.Context) *DiagnosticsReport {
	report := &DiagnosticsReport{
		CollectedAt: time.Now(),
		Build:       collectBuildInfo(),
		Runtime:     collectRuntime(),
	}

	if d.nodeProvider != nil {
		report.Nodes = d.nodeProvider.NodeDiagnostics(ctx)
	}

	if d.fwProvider != nil {
		fw := d.fwProvider.FrameworkDiagnostics(ctx)
		report.Framework = &fw
	}

	if d.cbRegistry != nil {
		snap := d.cbRegistry.Snapshot()
		report.CircuitBreakers = make(map[string]string, len(snap))
		for nodeID, state := range snap {
			report.CircuitBreakers[nodeID] = state.String()
		}
	}

	d.logger.Debug("diagnostics collected",
		"goroutines", report.Runtime.NumGoroutine,
		"heap_mb", report.Runtime.HeapAllocBytes>>20,
	)
	return report
}

// ---------------------------------------------------------------------------
// HTTP handler
// ---------------------------------------------------------------------------

// DiagnosticsHandler exposes /debug/diagnostics over HTTP.
type DiagnosticsHandler struct {
	collector *DiagnosticsCollector
}

// NewDiagnosticsHandler wraps a DiagnosticsCollector as an HTTP handler.
func NewDiagnosticsHandler(c *DiagnosticsCollector) *DiagnosticsHandler {
	return &DiagnosticsHandler{collector: c}
}

// RegisterRoutes mounts /debug/diagnostics on mux.
func (h *DiagnosticsHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/debug/diagnostics", h.handle)
}

func (h *DiagnosticsHandler) handle(w http.ResponseWriter, r *http.Request) {
	report := h.collector.Collect(r.Context())
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	if err := enc.Encode(report); err != nil {
		slog.Error("diagnostics encode error", "err", err)
	}
}
