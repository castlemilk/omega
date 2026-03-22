package eval

import (
	"strings"
	"testing"

	"github.com/benebsworth/omega/internal/db"
)

// ── VictoriaProvider tests ────────────────────────────────────────────────────

func TestStubVictoriaProvider_IsLive(t *testing.T) {
	p := &StubVictoriaProvider{}
	if p.IsLive() {
		t.Error("StubVictoriaProvider.IsLive() must return false")
	}
	if p.Source() != "stub" {
		t.Errorf("Source() = %q, want %q", p.Source(), "stub")
	}
}

func TestStubVictoriaProvider_Snapshot(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, err := p.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot() error: %v", err)
	}
	if !snap.Available {
		t.Error("stub snapshot must report Available=true")
	}
	if snap.Portfolio == nil {
		t.Fatal("stub snapshot must include Portfolio")
	}
	if snap.Portfolio.Sharpe <= 0 {
		t.Errorf("stub Sharpe=%.3f, want > 0", snap.Portfolio.Sharpe)
	}
	if len(snap.Signals) == 0 {
		t.Error("stub snapshot must include at least one signal")
	}
	if snap.BacktestStats == nil {
		t.Error("stub snapshot must include BacktestStats")
	}
	if snap.RiskMetrics == nil {
		t.Error("stub snapshot must include RiskMetrics")
	}
	if len(snap.EquityCurve) == 0 {
		t.Error("stub snapshot must include EquityCurve points")
	}
}

func TestStubVictoriaProvider_EquityCurveMonotonic(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, _ := p.Snapshot()
	for i := 1; i < len(snap.EquityCurve); i++ {
		if snap.EquityCurve[i].I != i {
			t.Errorf("equity curve index mismatch at position %d: got I=%d", i, snap.EquityCurve[i].I)
		}
	}
}

func TestStubVictoriaProvider_SignalWeightsSum(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, _ := p.Snapshot()
	total := 0.0
	for _, sig := range snap.Signals {
		total += sig.Weight
	}
	if total < 0.95 || total > 1.05 {
		t.Errorf("signal weights sum=%.3f, want ~1.0", total)
	}
}

// ── VictoriaEvalSuite tests ───────────────────────────────────────────────────

func TestVictoriaEvalSuite_Name(t *testing.T) {
	suite := NewVictoriaEvalSuite(&StubVictoriaProvider{})
	if suite.Name() != "victoria" {
		t.Errorf("Name() = %q, want %q", suite.Name(), "victoria")
	}
}

func TestVictoriaEvalSuite_RunWithStub(t *testing.T) {
	suite := NewVictoriaEvalSuite(&StubVictoriaProvider{})
	result := suite.Run()

	if result.Passed+result.Failed == 0 {
		t.Error("Run() produced no checks")
	}
	if result.Score < 0 || result.Score > 1 {
		t.Errorf("Score=%.3f outside [0,1]", result.Score)
	}
	// Stub data is designed to pass the majority of checks.
	if result.Score < 0.7 {
		t.Errorf("Score=%.2f too low for stub data (want >= 0.7); failures:\n%s",
			result.Score, strings.Join(result.Details, "\n"))
	}
	if len(result.Details) == 0 {
		t.Error("Run() produced no detail lines")
	}
}

func TestVictoriaEvalSuite_FailsOnNegativeSharpe(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, _ := p.Snapshot()
	snap.Portfolio.Sharpe = -0.5
	snap.PnL.Sharpe = -0.5

	suite := NewVictoriaEvalSuite(&fixedProvider{snap: snap})
	result := suite.Run()

	hasFailSharpe := false
	for _, d := range result.Details {
		if strings.HasPrefix(d, "FAIL sharpe_positive") || strings.HasPrefix(d, "FAIL sharpe_threshold") {
			hasFailSharpe = true
		}
	}
	if !hasFailSharpe {
		t.Errorf("expected sharpe failure in details; got:\n%s", strings.Join(result.Details, "\n"))
	}
}

func TestVictoriaEvalSuite_FailsOnHighDrawdown(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, _ := p.Snapshot()
	snap.PnL.MaxDD = 0.45 // 45% — over 25% limit

	suite := NewVictoriaEvalSuite(&fixedProvider{snap: snap})
	result := suite.Run()

	hasFailDD := false
	for _, d := range result.Details {
		if strings.HasPrefix(d, "FAIL max_drawdown") {
			hasFailDD = true
		}
	}
	if !hasFailDD {
		t.Errorf("expected max_drawdown failure; got:\n%s", strings.Join(result.Details, "\n"))
	}
}

func TestVictoriaEvalSuite_FailsOnOverfitting(t *testing.T) {
	p := &StubVictoriaProvider{}
	snap, _ := p.Snapshot()
	// OOS Sharpe is only 40% of IS Sharpe — severe overfitting.
	snap.BacktestStats.SharpeIS = 2.0
	snap.BacktestStats.SharpeOOS = 0.8

	suite := NewVictoriaEvalSuite(&fixedProvider{snap: snap})
	result := suite.Run()

	hasFailOOS := false
	for _, d := range result.Details {
		if strings.HasPrefix(d, "FAIL is_oos_gap") {
			hasFailOOS = true
		}
	}
	if !hasFailOOS {
		t.Errorf("expected is_oos_gap failure; got:\n%s", strings.Join(result.Details, "\n"))
	}
}

func TestVictoriaEvalSuite_SkipsWhenUnavailable(t *testing.T) {
	suite := NewVictoriaEvalSuite(&emptyProvider{})
	result := suite.Run()

	if result.Failed != 1 || result.Passed != 0 {
		t.Errorf("expected 1 failure for unavailable DB, got passed=%d failed=%d", result.Passed, result.Failed)
	}
	if len(result.Details) == 0 || !strings.HasPrefix(result.Details[0], "SKIP") {
		t.Errorf("expected SKIP detail; got %v", result.Details)
	}
}

func TestVictoriaEvalSuite_ImplementsEvalHarness(t *testing.T) {
	var _ EvalHarness = NewVictoriaEvalSuite(&StubVictoriaProvider{})
}

// ── ObservabilityAudit tests ──────────────────────────────────────────────────

func TestObservabilityAudit_Name(t *testing.T) {
	a := &ObservabilityAudit{}
	if a.Name() != "observability-audit" {
		t.Errorf("Name() = %q, want %q", a.Name(), "observability-audit")
	}
}

func TestObservabilityAudit_Run(t *testing.T) {
	a := &ObservabilityAudit{}
	result := a.Run()

	if result.Score < 0 || result.Score > 1 {
		t.Errorf("Score=%.3f outside [0,1]", result.Score)
	}
	if result.Passed+result.Failed == 0 {
		t.Error("audit produced no packages")
	}
	if len(result.Details) == 0 {
		t.Error("audit produced no detail lines")
	}

	// Should have a visibility summary line.
	hasSummary := false
	for _, d := range result.Details {
		if strings.Contains(d, "Visibility:") {
			hasSummary = true
		}
	}
	if !hasSummary {
		t.Error("audit details missing Visibility summary line")
	}
}

func TestObservabilityAudit_RunAudit_Coverage(t *testing.T) {
	a := &ObservabilityAudit{}
	audit := a.RunAudit()

	if len(audit.Packages) < 10 {
		t.Errorf("audit covers only %d packages, want >= 10", len(audit.Packages))
	}
	// Must have at least one of each status.
	statuses := map[ObsStatus]int{}
	for _, p := range audit.Packages {
		statuses[p.Status]++
	}
	if statuses[ObsObservable] == 0 {
		t.Error("audit has no Observable packages")
	}
	if statuses[ObsPartial] == 0 {
		t.Error("audit has no Partial packages")
	}
	if statuses[ObsBlackBox] == 0 {
		t.Error("audit has no BlackBox packages")
	}
}

func TestObservabilityAudit_VisibilityScore(t *testing.T) {
	a := &ObservabilityAudit{}
	audit := a.RunAudit()

	if audit.VisibilityScore < 0 || audit.VisibilityScore > 1 {
		t.Errorf("VisibilityScore=%.3f outside [0,1]", audit.VisibilityScore)
	}
	// We expect a low-to-moderate score given the black boxes identified.
	// At least some packages should be unobserved.
	if audit.VisibilityScore == 1.0 {
		t.Error("VisibilityScore=1.0 is implausible — likely a catalog error")
	}
}

func TestObservabilityAudit_AllPackagesHaveNotes(t *testing.T) {
	a := &ObservabilityAudit{}
	audit := a.RunAudit()
	for _, p := range audit.Packages {
		if p.Notes == "" {
			t.Errorf("package %q has empty Notes", p.Package)
		}
	}
}

func TestObservabilityAudit_ImplementsEvalHarness(t *testing.T) {
	var _ EvalHarness = &ObservabilityAudit{}
}

// ── RunVictoriaEval / Markdown tests ─────────────────────────────────────────

func TestRunVictoriaEval_ProducesReport(t *testing.T) {
	report := RunVictoriaEval(&StubVictoriaProvider{})

	if report.EvalResult.Passed+report.EvalResult.Failed == 0 {
		t.Error("RunVictoriaEval produced no eval checks")
	}
	if report.AuditResult.ObservableCount+report.AuditResult.PartialCount+report.AuditResult.BlackBoxCount == 0 {
		t.Error("RunVictoriaEval produced no audit packages")
	}
	if report.ProviderSource != "stub" {
		t.Errorf("ProviderSource=%q, want %q", report.ProviderSource, "stub")
	}
	if report.ProviderLive {
		t.Error("stub provider must report ProviderLive=false")
	}
}

func TestVictoriaReport_Markdown_Sections(t *testing.T) {
	report := RunVictoriaEval(&StubVictoriaProvider{})
	md := report.Markdown()

	sections := []string{
		"# Victoria Eval Report",
		"## Signal & Portfolio Quality",
		"## Observability Audit",
		"## Improvement Candidates",
		"## Missing Instrumentation",
	}
	for _, section := range sections {
		if !strings.Contains(md, section) {
			t.Errorf("markdown missing section %q", section)
		}
	}
}

func TestVictoriaReport_Markdown_ScorePresent(t *testing.T) {
	report := RunVictoriaEval(&StubVictoriaProvider{})
	md := report.Markdown()

	if !strings.Contains(md, "Score:") {
		t.Error("markdown missing Score line")
	}
	if !strings.Contains(md, "Visibility Score:") {
		t.Error("markdown missing Visibility Score line")
	}
}

func TestVictoriaReport_Markdown_ImprovementCandidates(t *testing.T) {
	report := RunVictoriaEval(&StubVictoriaProvider{})
	md := report.Markdown()

	// Must list at least the known black-box handlers.
	if !strings.Contains(md, "internal/handler") {
		t.Error("markdown missing internal/handler improvement candidate")
	}
}

// ── Test helpers ──────────────────────────────────────────────────────────────

// fixedProvider wraps a pre-built snapshot for targeted failure tests.
type fixedProvider struct {
	snap *VictoriaSnapshot
}

func (f *fixedProvider) Snapshot() (*VictoriaSnapshot, error) { return f.snap, nil }
func (f *fixedProvider) IsLive() bool                        { return false }
func (f *fixedProvider) Source() string                      { return "fixed" }

// emptyProvider simulates a live DB that has no data yet.
type emptyProvider struct{}

func (e *emptyProvider) Snapshot() (*VictoriaSnapshot, error) {
	return &VictoriaSnapshot{
		Source:    "live-db",
		Available: false,
		Portfolio: &db.VectoraPortfolio{},
		PnL:       &db.VectoraPnL{},
	}, nil
}
func (e *emptyProvider) IsLive() bool   { return true }
func (e *emptyProvider) Source() string { return "/tmp/vectora_state.db" }
