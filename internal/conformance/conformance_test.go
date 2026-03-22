package conformance

import (
	"strings"
	"testing"
)

func TestSuiteRunFiltersLevel(t *testing.T) {
	s := NewConformanceSuite()
	s.Add(ConformanceTest{
		Name:          "pico/test",
		AutonomyLevel: LevelPICO,
		TestFunc:      func() (bool, string) { return true, "ok" },
	})
	s.Add(ConformanceTest{
		Name:          "supervised/test",
		AutonomyLevel: LevelSupervised,
		TestFunc:      func() (bool, string) { return true, "ok" },
	})

	results := s.Run(LevelPICO)
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0].TestName != "pico/test" {
		t.Errorf("unexpected test name: %s", results[0].TestName)
	}
}

func TestSuiteRunAll(t *testing.T) {
	s := NewConformanceSuite()
	for _, level := range []AutonomyLevel{LevelPICO, LevelSupervised, LevelAutonomous} {
		level := level
		s.Add(ConformanceTest{
			Name:          level.String() + "/test",
			AutonomyLevel: level,
			TestFunc:      func() (bool, string) { return true, "ok" },
		})
	}

	results := s.RunAll()
	if len(results) != 3 {
		t.Fatalf("expected 3 results, got %d", len(results))
	}
}

func TestBuiltinPICOTests(t *testing.T) {
	s := BuiltinSuite()
	results := s.Run(LevelPICO)
	if len(results) == 0 {
		t.Fatal("expected PICO tests, got none")
	}
	for _, r := range results {
		if !r.Passed {
			t.Errorf("PICO test %q failed: %s", r.TestName, r.Details)
		}
	}
}

func TestBuiltinSupervisedTests(t *testing.T) {
	s := BuiltinSuite()
	results := s.Run(LevelSupervised)
	if len(results) == 0 {
		t.Fatal("expected SUPERVISED tests, got none")
	}
	for _, r := range results {
		if !r.Passed {
			t.Errorf("SUPERVISED test %q failed: %s", r.TestName, r.Details)
		}
	}
}

func TestBuiltinAutonomousTests(t *testing.T) {
	s := BuiltinSuite()
	results := s.Run(LevelAutonomous)
	if len(results) == 0 {
		t.Fatal("expected AUTONOMOUS tests, got none")
	}
	for _, r := range results {
		if !r.Passed {
			t.Errorf("AUTONOMOUS test %q failed: %s", r.TestName, r.Details)
		}
	}
}

func TestGenerateReport(t *testing.T) {
	results := []ConformanceResult{
		{TestName: "foo/pass", Passed: true, Details: "all good"},
		{TestName: "foo/fail", Passed: false, Details: "something broke"},
	}
	report := GenerateReport(results)
	if !strings.Contains(report, "PASS") {
		t.Error("report missing PASS indicator")
	}
	if !strings.Contains(report, "FAIL") {
		t.Error("report missing FAIL indicator")
	}
	if !strings.Contains(report, "Failures") {
		t.Error("report missing Failures section")
	}
}

func TestCompareReports(t *testing.T) {
	old := []ConformanceResult{
		{TestName: "foo/stable", Passed: true},
		{TestName: "foo/regressed", Passed: true},
		{TestName: "foo/improved", Passed: false},
	}
	updated := []ConformanceResult{
		{TestName: "foo/stable", Passed: true},
		{TestName: "foo/regressed", Passed: false},
		{TestName: "foo/improved", Passed: true},
	}

	diff := CompareReports(old, updated)
	if !strings.Contains(diff, "Regressions") {
		t.Error("expected Regressions section")
	}
	if !strings.Contains(diff, "Improvements") {
		t.Error("expected Improvements section")
	}
}

func TestAutonomyLevelString(t *testing.T) {
	cases := []struct {
		level AutonomyLevel
		want  string
	}{
		{LevelPICO, "PICO"},
		{LevelSupervised, "SUPERVISED"},
		{LevelAutonomous, "AUTONOMOUS"},
		{AutonomyLevel(99), "AutonomyLevel(99)"},
	}
	for _, c := range cases {
		if got := c.level.String(); got != c.want {
			t.Errorf("String() = %q, want %q", got, c.want)
		}
	}
}
