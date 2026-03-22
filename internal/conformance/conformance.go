// Package conformance provides a framework for running conformance tests
// against Omega autonomy levels to verify expected behaviour boundaries.
package conformance

import (
	"fmt"
	"time"
)

// AutonomyLevel mirrors the middleware autonomy levels for test targeting.
type AutonomyLevel int

const (
	// LevelPICO targets read-only, passive observation mode.
	LevelPICO AutonomyLevel = iota
	// LevelSupervised targets human-gated action mode.
	LevelSupervised
	// LevelAutonomous targets fully autonomous operation mode.
	LevelAutonomous
)

// String returns the human-readable name of the autonomy level.
func (l AutonomyLevel) String() string {
	switch l {
	case LevelPICO:
		return "PICO"
	case LevelSupervised:
		return "SUPERVISED"
	case LevelAutonomous:
		return "AUTONOMOUS"
	default:
		return fmt.Sprintf("AutonomyLevel(%d)", int(l))
	}
}

// ConformanceTest describes a single conformance check.
type ConformanceTest struct {
	Name             string
	Description      string
	AutonomyLevel    AutonomyLevel
	ExpectedBehavior string
	TestFunc         func() (passed bool, details string)
}

// ConformanceResult holds the outcome of a single conformance test.
type ConformanceResult struct {
	TestName string
	Passed   bool
	Details  string
	Duration time.Duration
}

// ConformanceSuite holds a collection of conformance tests.
type ConformanceSuite struct {
	tests []ConformanceTest
}

// NewConformanceSuite creates an empty ConformanceSuite.
func NewConformanceSuite() *ConformanceSuite {
	return &ConformanceSuite{}
}

// Add registers a conformance test with the suite.
func (s *ConformanceSuite) Add(t ConformanceTest) {
	s.tests = append(s.tests, t)
}

// Run executes all tests whose AutonomyLevel matches level and returns the results.
func (s *ConformanceSuite) Run(level AutonomyLevel) []ConformanceResult {
	var results []ConformanceResult
	for _, t := range s.tests {
		if t.AutonomyLevel != level {
			continue
		}
		start := time.Now()
		passed, details := t.TestFunc()
		results = append(results, ConformanceResult{
			TestName: t.Name,
			Passed:   passed,
			Details:  details,
			Duration: time.Since(start),
		})
	}
	return results
}

// RunAll executes every test in the suite regardless of autonomy level.
func (s *ConformanceSuite) RunAll() []ConformanceResult {
	var results []ConformanceResult
	for _, t := range s.tests {
		start := time.Now()
		passed, details := t.TestFunc()
		results = append(results, ConformanceResult{
			TestName: t.Name,
			Passed:   passed,
			Details:  details,
			Duration: time.Since(start),
		})
	}
	return results
}
