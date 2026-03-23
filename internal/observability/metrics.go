package observability

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

const namespace = "omega"

// Metrics holds all Prometheus instruments for the Omega framework.
// Call NewMetrics once at startup and share the pointer.
type Metrics struct {
	registry *prometheus.Registry

	// Cycle-level latency distribution (seconds).
	CycleDuration *prometheus.HistogramVec

	// Per-node execution latency distribution (seconds).
	NodeExecutionSeconds *prometheus.HistogramVec

	// Autonomy promotions counted per node.
	AutonomyPromotionsTotal *prometheus.CounterVec

	// Adversarial vetoes counted per node and ring number.
	AdversarialVetoesTotal *prometheus.CounterVec

	// Memory consolidation events.
	MemoryConsolidationsTotal prometheus.Counter

	// Improvement proposals counted per node and outcome (accepted/rejected).
	ImprovementProposalsTotal *prometheus.CounterVec

	// Safety violations counted per alignment layer (1/2/3).
	SafetyViolationsTotal *prometheus.CounterVec

	// Current autonomy level per node (0.0–1.0).
	NodeAutonomyLevel *prometheus.GaugeVec

	// Current error rate per node (0.0–1.0).
	NodeErrorRate *prometheus.GaugeVec

	// Circuit breaker state per node: 0=closed, 1=open, 2=half-open.
	CircuitBreakerState *prometheus.GaugeVec

	// Errors per subsystem (db, handler, core, adversarial, …).
	SubsystemErrorsTotal *prometheus.CounterVec

	// Degradation events per node.
	DegradationEventsTotal *prometheus.CounterVec

	// ── P1-4: standard pipeline observability ────────────────────────────────

	// CyclesTotal counts all completed orchestration cycles.
	CyclesTotal prometheus.Counter

	// NodeExecutionsTotal counts node executions by node name and status (success/error/skipped).
	NodeExecutionsTotal *prometheus.CounterVec

	// NodeExecutionDuration records per-node execution latency in seconds.
	NodeExecutionDuration *prometheus.HistogramVec

	// ErrorsTotal counts errors by node name and error class.
	ErrorsTotal *prometheus.CounterVec

	// IssuesTotal counts detected issues by severity and detector.
	IssuesTotal *prometheus.CounterVec

	// HealthScore is the current system health score (0–100).
	HealthScore prometheus.Gauge
}

// NewMetrics creates and registers all instruments on a fresh isolated registry.
// Use registry.Handler() (or Handler()) to expose the /metrics endpoint.
func NewMetrics() *Metrics {
	reg := prometheus.NewRegistry()

	m := &Metrics{
		registry: reg,

		CycleDuration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "cycle_duration_seconds",
			Help:      "End-to-end duration of a full orchestration cycle.",
			Buckets:   prometheus.DefBuckets,
		}, []string{"status"}),

		NodeExecutionSeconds: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "node_execution_seconds",
			Help:      "Execution latency per node.",
			Buckets:   prometheus.DefBuckets,
		}, []string{"node_id", "status"}),

		AutonomyPromotionsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "autonomy_promotions_total",
			Help:      "Total number of autonomy-level promotions per node.",
		}, []string{"node_id"}),

		AdversarialVetoesTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "adversarial_vetoes_total",
			Help:      "Total number of adversarial vetoes by node and ring.",
		}, []string{"node_id", "ring"}),

		MemoryConsolidationsTotal: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "memory_consolidations_total",
			Help:      "Total number of memory consolidation events.",
		}),

		ImprovementProposalsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "improvement_proposals_total",
			Help:      "Total improvement proposals by node and outcome.",
		}, []string{"node_id", "outcome"}),

		SafetyViolationsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "safety_violations_total",
			Help:      "Total safety violations detected per alignment layer.",
		}, []string{"layer"}),

		NodeAutonomyLevel: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "node_autonomy_level",
			Help:      "Current autonomy level of a node (0.0–1.0).",
		}, []string{"node_id"}),

		NodeErrorRate: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "node_error_rate",
			Help:      "Rolling error rate per node (0.0–1.0).",
		}, []string{"node_id"}),

		CircuitBreakerState: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "circuit_breaker_state",
			Help:      "Circuit breaker state per node: 0=closed 1=open 2=half-open.",
		}, []string{"node_id"}),

		SubsystemErrorsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "subsystem_errors_total",
			Help:      "Total errors counted per subsystem.",
		}, []string{"subsystem"}),

		DegradationEventsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "degradation_events_total",
			Help:      "Total degradation events detected per node.",
		}, []string{"node_id", "kind"}),

		CyclesTotal: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "cycles_total",
			Help:      "Total number of completed orchestration pipeline cycles.",
		}),

		NodeExecutionsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "node_executions_total",
			Help:      "Total node executions by node name and status (success/error/skipped).",
		}, []string{"node_name", "status"}),

		NodeExecutionDuration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "node_execution_duration_seconds",
			Help:      "Per-node execution latency in seconds.",
			Buckets:   prometheus.DefBuckets,
		}, []string{"node_name"}),

		ErrorsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "errors_total",
			Help:      "Total errors by node name and error class.",
		}, []string{"node_name", "error_class"}),

		IssuesTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "issues_total",
			Help:      "Total issues detected by severity and detector.",
		}, []string{"severity", "detector"}),

		HealthScore: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "health_score",
			Help:      "Current system health score (0=unhealthy, 50=degraded, 100=healthy).",
		}),
	}

	reg.MustRegister(
		m.CycleDuration,
		m.NodeExecutionSeconds,
		m.AutonomyPromotionsTotal,
		m.AdversarialVetoesTotal,
		m.MemoryConsolidationsTotal,
		m.ImprovementProposalsTotal,
		m.SafetyViolationsTotal,
		m.NodeAutonomyLevel,
		m.NodeErrorRate,
		m.CircuitBreakerState,
		m.SubsystemErrorsTotal,
		m.DegradationEventsTotal,
		m.CyclesTotal,
		m.NodeExecutionsTotal,
		m.NodeExecutionDuration,
		m.ErrorsTotal,
		m.IssuesTotal,
		m.HealthScore,
		// Standard Go runtime collectors.
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	)

	return m
}

// Handler returns an HTTP handler that serves the Prometheus text exposition format.
// Register it on /metrics in your HTTP mux.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{
		EnableOpenMetrics: true,
	})
}

// RecordCycle records a completed orchestration cycle.
// status should be "success" or "error".
func (m *Metrics) RecordCycle(durationSecs float64, status string) {
	m.CycleDuration.WithLabelValues(status).Observe(durationSecs)
}

// RecordNodeExecution records a node execution.
// status should be "success" or "error".
func (m *Metrics) RecordNodeExecution(nodeID string, durationSecs float64, success bool) {
	status := "success"
	if !success {
		status = "error"
	}
	m.NodeExecutionSeconds.WithLabelValues(nodeID, status).Observe(durationSecs)
}

// RecordAutonomyPromotion increments the promotion counter for a node.
func (m *Metrics) RecordAutonomyPromotion(nodeID string) {
	m.AutonomyPromotionsTotal.WithLabelValues(nodeID).Inc()
}

// RecordAdversarialVeto records a veto by ring number (e.g. "1", "2", "3").
func (m *Metrics) RecordAdversarialVeto(nodeID, ring string) {
	m.AdversarialVetoesTotal.WithLabelValues(nodeID, ring).Inc()
}

// RecordMemoryConsolidation increments the consolidation counter.
func (m *Metrics) RecordMemoryConsolidation() {
	m.MemoryConsolidationsTotal.Inc()
}

// RecordImprovementProposal records a proposal outcome ("accepted" or "rejected").
func (m *Metrics) RecordImprovementProposal(nodeID, outcome string) {
	m.ImprovementProposalsTotal.WithLabelValues(nodeID, outcome).Inc()
}

// RecordSafetyViolation records a safety violation for a given layer ("1", "2", "3").
func (m *Metrics) RecordSafetyViolation(layer string) {
	m.SafetyViolationsTotal.WithLabelValues(layer).Inc()
}

// SetNodeAutonomyLevel updates the autonomy gauge for a node.
func (m *Metrics) SetNodeAutonomyLevel(nodeID string, level float64) {
	m.NodeAutonomyLevel.WithLabelValues(nodeID).Set(level)
}

// SetNodeErrorRate updates the error-rate gauge for a node.
func (m *Metrics) SetNodeErrorRate(nodeID string, rate float64) {
	m.NodeErrorRate.WithLabelValues(nodeID).Set(rate)
}

// SetCircuitBreakerState updates the circuit-breaker-state gauge for a node.
// Use CircuitStateValue constants for the value.
func (m *Metrics) SetCircuitBreakerState(nodeID string, state float64) {
	m.CircuitBreakerState.WithLabelValues(nodeID).Set(state)
}

// RecordSubsystemError increments the error counter for a named subsystem.
func (m *Metrics) RecordSubsystemError(subsystem string) {
	m.SubsystemErrorsTotal.WithLabelValues(subsystem).Inc()
}

// RecordDegradation increments the degradation counter.
// kind should be "performance" or "error_rate".
func (m *Metrics) RecordDegradation(nodeID, kind string) {
	m.DegradationEventsTotal.WithLabelValues(nodeID, kind).Inc()
}

// CircuitStateValue constants for SetCircuitBreakerState.
const (
	CircuitStateValueClosed   float64 = 0
	CircuitStateValueOpen     float64 = 1
	CircuitStateValueHalfOpen float64 = 2
)

// ── P1-4 helpers ──────────────────────────────────────────────────────────────

// IncCycles increments the total completed pipeline cycles counter.
func (m *Metrics) IncCycles() {
	m.CyclesTotal.Inc()
}

// IncNodeExecution increments the per-node execution counter.
// status should be "success", "error", or "skipped".
func (m *Metrics) IncNodeExecution(nodeName, status string) {
	m.NodeExecutionsTotal.WithLabelValues(nodeName, status).Inc()
}

// ObserveNodeDuration records execution latency for a node.
func (m *Metrics) ObserveNodeDuration(nodeName string, secs float64) {
	m.NodeExecutionDuration.WithLabelValues(nodeName).Observe(secs)
}

// IncError increments the error counter for a node and error class.
func (m *Metrics) IncError(nodeName, errorClass string) {
	m.ErrorsTotal.WithLabelValues(nodeName, errorClass).Inc()
}

// IncIssue increments the issue counter for a given severity and detector.
func (m *Metrics) IncIssue(severity, detector string) {
	m.IssuesTotal.WithLabelValues(severity, detector).Inc()
}

// SetHealthScore sets the current system health score (0–100).
func (m *Metrics) SetHealthScore(score float64) {
	m.HealthScore.Set(score)
}
