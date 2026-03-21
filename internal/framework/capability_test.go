package framework_test

import (
	"testing"

	"github.com/benebsworth/omega/internal/framework"
)

type signalNode struct{ id string }

func (n *signalNode) NodeID() string { return n.id }
func (n *signalNode) Capabilities() []framework.Capability {
	return []framework.Capability{
		framework.CapabilitySignalGeneration,
		framework.CapabilityDataIngestion,
	}
}

type riskNode struct{ id string }

func (n *riskNode) NodeID() string { return n.id }
func (n *riskNode) Capabilities() []framework.Capability {
	return []framework.Capability{
		framework.CapabilityRiskAssessment,
		framework.CapabilityBacktesting,
	}
}

func TestCapabilityRegistry_RegisterAndQuery(t *testing.T) {
	reg := framework.NewCapabilityRegistry()

	n1 := &signalNode{id: "node-1"}
	n2 := &riskNode{id: "node-2"}

	reg.Register(n1)
	reg.Register(n2)

	providers := reg.ProvidersFor(framework.CapabilitySignalGeneration)
	if len(providers) != 1 {
		t.Fatalf("expected 1 provider for SignalGeneration, got %d", len(providers))
	}
	if providers[0].NodeID() != "node-1" {
		t.Fatalf("expected node-1, got %s", providers[0].NodeID())
	}
}

func TestCapabilityRegistry_MultipleProvidersForCapability(t *testing.T) {
	reg := framework.NewCapabilityRegistry()

	a := &signalNode{id: "node-a"}
	b := &signalNode{id: "node-b"}

	reg.Register(a)
	reg.Register(b)

	providers := reg.ProvidersFor(framework.CapabilitySignalGeneration)
	if len(providers) != 2 {
		t.Fatalf("expected 2 providers, got %d", len(providers))
	}
}

func TestCapabilityRegistry_NoProviderReturnsEmpty(t *testing.T) {
	reg := framework.NewCapabilityRegistry()
	providers := reg.ProvidersFor(framework.CapabilityBacktesting)
	if len(providers) != 0 {
		t.Fatalf("expected 0 providers, got %d", len(providers))
	}
}

func TestCapabilityRegistry_HasCapability(t *testing.T) {
	reg := framework.NewCapabilityRegistry()
	reg.Register(&riskNode{id: "n1"})

	if !reg.HasCapability(framework.CapabilityRiskAssessment) {
		t.Fatal("expected HasCapability(RiskAssessment) = true")
	}
	if reg.HasCapability(framework.CapabilitySignalGeneration) {
		t.Fatal("expected HasCapability(SignalGeneration) = false")
	}
}

func TestCapabilityRegistry_Unregister(t *testing.T) {
	reg := framework.NewCapabilityRegistry()
	n := &signalNode{id: "n1"}
	reg.Register(n)
	reg.Unregister("n1")

	if reg.HasCapability(framework.CapabilitySignalGeneration) {
		t.Fatal("expected no capability providers after unregister")
	}
}

func TestCapabilityRegistry_Negotiate(t *testing.T) {
	reg := framework.NewCapabilityRegistry()
	reg.Register(&signalNode{id: "n1"})
	reg.Register(&riskNode{id: "n2"})

	// All requested capabilities are available
	result := reg.Negotiate([]framework.Capability{
		framework.CapabilitySignalGeneration,
		framework.CapabilityRiskAssessment,
	})
	if !result.Satisfied {
		t.Fatalf("expected negotiation satisfied: missing=%v", result.Missing)
	}

	// One missing capability
	result = reg.Negotiate([]framework.Capability{
		framework.CapabilitySignalGeneration,
		framework.CapabilityPortfolioOptimization,
	})
	if result.Satisfied {
		t.Fatal("expected negotiation unsatisfied")
	}
	if len(result.Missing) != 1 || result.Missing[0] != framework.CapabilityPortfolioOptimization {
		t.Fatalf("unexpected missing: %v", result.Missing)
	}
}

func TestCapabilityRegistry_AllCapabilities(t *testing.T) {
	reg := framework.NewCapabilityRegistry()
	reg.Register(&signalNode{id: "n1"})
	reg.Register(&riskNode{id: "n2"})

	caps := reg.AllCapabilities()
	// Should have: SignalGeneration, DataIngestion, RiskAssessment, Backtesting
	if len(caps) < 4 {
		t.Fatalf("expected at least 4 capabilities, got %d: %v", len(caps), caps)
	}
}
