package observability

import (
	"io"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestNewMetrics_NoRegistrationPanic(t *testing.T) {
	// Should not panic on double-registration because each call creates its own registry.
	m1 := NewMetrics()
	m2 := NewMetrics()
	if m1 == nil || m2 == nil {
		t.Fatal("NewMetrics returned nil")
	}
}

func TestMetrics_RecordCycle(t *testing.T) {
	m := NewMetrics()
	// Should not panic.
	m.RecordCycle(1.23, "success")
	m.RecordCycle(0.05, "error")
}

func TestMetrics_RecordNodeExecution(t *testing.T) {
	m := NewMetrics()
	m.RecordNodeExecution("node-1", 0.5, true)
	m.RecordNodeExecution("node-1", 0.9, false)
}

func TestMetrics_RecordAutonomyPromotion(t *testing.T) {
	m := NewMetrics()
	m.RecordAutonomyPromotion("node-1")
	m.RecordAutonomyPromotion("node-1")
}

func TestMetrics_RecordAdversarialVeto(t *testing.T) {
	m := NewMetrics()
	m.RecordAdversarialVeto("node-1", "1")
	m.RecordAdversarialVeto("node-2", "3")
}

func TestMetrics_RecordMemoryConsolidation(t *testing.T) {
	m := NewMetrics()
	m.RecordMemoryConsolidation()
}

func TestMetrics_RecordImprovementProposal(t *testing.T) {
	m := NewMetrics()
	m.RecordImprovementProposal("node-1", "accepted")
	m.RecordImprovementProposal("node-2", "rejected")
}

func TestMetrics_RecordSafetyViolation(t *testing.T) {
	m := NewMetrics()
	m.RecordSafetyViolation("1")
	m.RecordSafetyViolation("2")
	m.RecordSafetyViolation("3")
}

func TestMetrics_GaugeSetters(t *testing.T) {
	m := NewMetrics()
	m.SetNodeAutonomyLevel("node-1", 0.75)
	m.SetNodeErrorRate("node-1", 0.05)
	m.SetCircuitBreakerState("node-1", CircuitStateValueOpen)
}

func TestMetrics_Handler_ExposesMetrics(t *testing.T) {
	m := NewMetrics()
	// Seed every metric so Prometheus emits the series in the exposition.
	m.RecordCycle(1.5, "success")
	m.RecordNodeExecution("node-1", 0.5, true)
	m.RecordAutonomyPromotion("node-1")
	m.RecordAdversarialVeto("node-1", "1")
	m.RecordMemoryConsolidation()
	m.RecordImprovementProposal("node-1", "accepted")
	m.RecordSafetyViolation("1")
	m.SetNodeAutonomyLevel("node-1", 0.8)
	m.SetNodeErrorRate("node-1", 0.02)
	m.SetCircuitBreakerState("node-1", CircuitStateValueClosed)
	m.RecordSubsystemError("db")
	m.RecordDegradation("node-1", "performance")

	req := httptest.NewRequest("GET", "/metrics", nil)
	w := httptest.NewRecorder()
	m.Handler().ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("want 200, got %d", w.Code)
	}

	body, _ := io.ReadAll(w.Body)
	text := string(body)

	expectedMetrics := []string{
		"omega_cycle_duration_seconds",
		"omega_autonomy_promotions_total",
		"omega_node_autonomy_level",
		"omega_node_execution_seconds",
		"omega_adversarial_vetoes_total",
		"omega_memory_consolidations_total",
		"omega_improvement_proposals_total",
		"omega_safety_violations_total",
		"omega_node_error_rate",
		"omega_circuit_breaker_state",
		"omega_subsystem_errors_total",
		"omega_degradation_events_total",
	}

	for _, metric := range expectedMetrics {
		if !strings.Contains(text, metric) {
			t.Errorf("expected metric %q not found in /metrics output", metric)
		}
	}
}

func TestMetrics_RecordDegradation(t *testing.T) {
	m := NewMetrics()
	m.RecordDegradation("node-1", "performance")
	m.RecordDegradation("node-1", "error_rate")
}

func TestMetrics_RecordSubsystemError(t *testing.T) {
	m := NewMetrics()
	m.RecordSubsystemError("db")
	m.RecordSubsystemError("handler")
}

func TestCircuitStateValueConstants(t *testing.T) {
	if CircuitStateValueClosed != 0 {
		t.Fatalf("CircuitStateValueClosed should be 0, got %v", CircuitStateValueClosed)
	}
	if CircuitStateValueOpen != 1 {
		t.Fatalf("CircuitStateValueOpen should be 1, got %v", CircuitStateValueOpen)
	}
	if CircuitStateValueHalfOpen != 2 {
		t.Fatalf("CircuitStateValueHalfOpen should be 2, got %v", CircuitStateValueHalfOpen)
	}
}
