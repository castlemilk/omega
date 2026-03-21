package omegatest

// fixtures.go — factory functions and builders for deterministic test data.
//
// All factory functions produce deterministic output: no random values, no
// time.Now() calls (timestamps use fixed epoch offsets). This keeps test
// failures reproducible.

import (
	"fmt"
	"time"

	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// ---------------------------------------------------------------------------
// Fixed epoch baseline — all test timestamps are offsets from this.
// ---------------------------------------------------------------------------

// testEpoch is the fixed baseline for all test timestamps.
// Using a concrete date avoids "year 2038" surprises in assertions.
var testEpoch = time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

func testTime(offsetSeconds int) time.Time {
	return testEpoch.Add(time.Duration(offsetSeconds) * time.Second)
}

func testUnix(offsetSeconds int) float64 {
	return float64(testTime(offsetSeconds).Unix())
}

// ---------------------------------------------------------------------------
// db.Node factories
// ---------------------------------------------------------------------------

// NewTestNode returns a db.Node with deterministic values. The index parameter
// allows generating distinct nodes: NewTestNode(0), NewTestNode(1), etc.
func NewTestNode(index int) db.Node {
	return db.Node{
		NodeID:           fmt.Sprintf("test-node-%03d", index),
		Name:             fmt.Sprintf("TestNode%d", index),
		Version:          "1.0",
		Capabilities:     []string{"inference", "evaluation"},
		Health:           1.0,
		Status:           "active",
		RegisteredAt:     testUnix(index * 60),
		LastUpdated:      testUnix(index * 60),
		ExecutionsTotal:  0,
		ErrorRate:        0.0,
		AvgLatencyMS:     0.0,
		P95LatencyMS:     0.0,
		ImprovementCount: 0,
	}
}

// ---------------------------------------------------------------------------
// NodeBuilder — fluent builder for db.Node
// ---------------------------------------------------------------------------

// NodeBuilder builds a db.Node step-by-step.
type NodeBuilder struct {
	node db.Node
}

// BuildNode returns a NodeBuilder seeded with NewTestNode(index).
func BuildNode(index int) *NodeBuilder {
	return &NodeBuilder{node: NewTestNode(index)}
}

func (b *NodeBuilder) WithID(id string) *NodeBuilder {
	b.node.NodeID = id
	return b
}

func (b *NodeBuilder) WithName(name string) *NodeBuilder {
	b.node.Name = name
	return b
}

func (b *NodeBuilder) WithVersion(version string) *NodeBuilder {
	b.node.Version = version
	return b
}

func (b *NodeBuilder) WithHealth(health float64) *NodeBuilder {
	b.node.Health = health
	return b
}

func (b *NodeBuilder) WithStatus(status string) *NodeBuilder {
	b.node.Status = status
	return b
}

func (b *NodeBuilder) WithCapabilities(caps ...string) *NodeBuilder {
	b.node.Capabilities = caps
	return b
}

func (b *NodeBuilder) WithExecutions(total int64, errorRate float64) *NodeBuilder {
	b.node.ExecutionsTotal = total
	b.node.ErrorRate = errorRate
	return b
}

func (b *NodeBuilder) WithLatency(avgMS, p95MS float64) *NodeBuilder {
	b.node.AvgLatencyMS = avgMS
	b.node.P95LatencyMS = p95MS
	return b
}

// Build returns the constructed db.Node.
func (b *NodeBuilder) Build() db.Node {
	return b.node
}

// ---------------------------------------------------------------------------
// db.Execution factories
// ---------------------------------------------------------------------------

// NewTestExecution returns a deterministic completed db.Execution.
func NewTestExecution(nodeIndex, execIndex int) db.Execution {
	startedAt := testUnix(nodeIndex*3600 + execIndex*60)
	endedAt := startedAt + 1.5
	durationMS := 1500.0
	return db.Execution{
		ExecID:    fmt.Sprintf("exec-%03d-%03d", nodeIndex, execIndex),
		NodeID:    fmt.Sprintf("test-node-%03d", nodeIndex),
		NodeName:  fmt.Sprintf("TestNode%d", nodeIndex),
		TraceID:   fmt.Sprintf("trace-%03d-%03d", nodeIndex, execIndex),
		SpanID:    fmt.Sprintf("span-%03d-%03d", nodeIndex, execIndex),
		Action:    "cycle",
		StartedAt: startedAt,
		EndedAt:   &endedAt,
		DurationMS: &durationMS,
		Success:   true,
		ErrorText: "",
		Metrics: map[string]float64{
			"accuracy": 0.92,
			"latency":  durationMS,
		},
		Cycle: int64(execIndex),
	}
}

// ---------------------------------------------------------------------------
// CycleResult / PerformanceMetric factories
// ---------------------------------------------------------------------------

// TestCycleResult holds the data representing one completed orchestration cycle
// used in tests.
type TestCycleResult struct {
	Cycle        int
	NodeID       string
	Success      bool
	DurationMS   float64
	Accuracy     float64
	SharpeRatio  float64
	DrawdownPct  float64
}

// NewTestCycleResult returns a deterministic TestCycleResult.
func NewTestCycleResult(nodeIndex, cycle int) TestCycleResult {
	return TestCycleResult{
		Cycle:       cycle,
		NodeID:      fmt.Sprintf("test-node-%03d", nodeIndex),
		Success:     true,
		DurationMS:  float64(100 + cycle*10),
		Accuracy:    0.8 + float64(cycle)*0.01,
		SharpeRatio: 1.2 + float64(cycle)*0.05,
		DrawdownPct: 0.05 - float64(cycle)*0.002,
	}
}

// TestPerformanceMetric holds per-node performance data for tests.
type TestPerformanceMetric struct {
	NodeID      string
	Cycle       int
	Accuracy    float64
	LatencyMS   float64
	ErrorRate   float64
	SharpeRatio float64
	DrawdownPct float64
}

// NewTestPerformanceMetric returns a deterministic TestPerformanceMetric.
func NewTestPerformanceMetric(nodeIndex, cycle int) TestPerformanceMetric {
	return TestPerformanceMetric{
		NodeID:      fmt.Sprintf("test-node-%03d", nodeIndex),
		Cycle:       cycle,
		Accuracy:    0.85 + float64(nodeIndex)*0.01,
		LatencyMS:   150.0 + float64(cycle)*5.0,
		ErrorRate:   0.02 - float64(nodeIndex)*0.001,
		SharpeRatio: 1.5 + float64(nodeIndex)*0.1,
		DrawdownPct: 0.04 - float64(nodeIndex)*0.001,
	}
}

// ---------------------------------------------------------------------------
// PerformanceMetricBuilder
// ---------------------------------------------------------------------------

// PerformanceMetricBuilder builds a TestPerformanceMetric step-by-step.
type PerformanceMetricBuilder struct {
	m TestPerformanceMetric
}

// BuildMetric returns a builder seeded with NewTestPerformanceMetric(nodeIndex, cycle).
func BuildMetric(nodeIndex, cycle int) *PerformanceMetricBuilder {
	return &PerformanceMetricBuilder{m: NewTestPerformanceMetric(nodeIndex, cycle)}
}

func (b *PerformanceMetricBuilder) WithAccuracy(v float64) *PerformanceMetricBuilder {
	b.m.Accuracy = v
	return b
}

func (b *PerformanceMetricBuilder) WithLatencyMS(v float64) *PerformanceMetricBuilder {
	b.m.LatencyMS = v
	return b
}

func (b *PerformanceMetricBuilder) WithErrorRate(v float64) *PerformanceMetricBuilder {
	b.m.ErrorRate = v
	return b
}

func (b *PerformanceMetricBuilder) WithSharpe(v float64) *PerformanceMetricBuilder {
	b.m.SharpeRatio = v
	return b
}

func (b *PerformanceMetricBuilder) WithDrawdown(v float64) *PerformanceMetricBuilder {
	b.m.DrawdownPct = v
	return b
}

// Build returns the constructed TestPerformanceMetric.
func (b *PerformanceMetricBuilder) Build() TestPerformanceMetric {
	return b.m
}

// ---------------------------------------------------------------------------
// core.Episode factories
// ---------------------------------------------------------------------------

// NewTestEpisode returns a deterministic core.Episode for memory tests.
func NewTestEpisode(index int) core.Episode {
	return core.Episode{
		EpisodeID: fmt.Sprintf("ep-%04d", index),
		Timestamp: testTime(index * 30),
		EventType: "test_event",
		Content: map[string]any{
			"index":   index,
			"payload": fmt.Sprintf("content-%d", index),
		},
		Tags:       []string{"test", fmt.Sprintf("batch-%d", index/10)},
		Importance: 0.5 + float64(index%5)*0.1,
		Cycle:      index,
		Namespace:  "test",
	}
}

// ---------------------------------------------------------------------------
// core.MemoryRecord factories
// ---------------------------------------------------------------------------

// NewTestMemoryRecord returns a deterministic core.MemoryRecord.
func NewTestMemoryRecord(index int) core.MemoryRecord {
	return core.NewMemoryRecord(
		fmt.Sprintf("regime-%d", index%3),
		"test_signal",
		map[string]any{
			"index": index,
			"value": float64(index) * 0.1,
		},
		[]string{"test", fmt.Sprintf("group-%d", index%5)},
		0.5+float64(index%5)*0.1,
		false,
	)
}

// ---------------------------------------------------------------------------
// Safety / alignment fixtures
// ---------------------------------------------------------------------------

// TestPortfolio returns a deterministic portfolio map suitable for SafetyEnvelope tests.
// totalWeight sums to 1.0 across 4 assets.
func TestPortfolio(index int) map[string]float64 {
	base := float64(index%5+1) * 0.1
	return map[string]float64{
		"BTC":  0.4 - base,
		"ETH":  0.3,
		"SOL":  0.2 + base,
		"USDC": 0.1,
	}
}

// TestCorrelationMatrix returns a deterministic correlation matrix for 4 assets.
func TestCorrelationMatrix() map[string]map[string]float64 {
	assets := []string{"BTC", "ETH", "SOL", "USDC"}
	m := make(map[string]map[string]float64, len(assets))
	for _, a := range assets {
		m[a] = make(map[string]float64, len(assets))
		for _, b := range assets {
			switch {
			case a == b:
				m[a][b] = 1.0
			case a == "USDC" || b == "USDC":
				m[a][b] = 0.05 // stable coin low correlation
			default:
				m[a][b] = 0.75 // crypto-crypto high correlation
			}
		}
	}
	return m
}

// ---------------------------------------------------------------------------
// Adversarial fixtures
// ---------------------------------------------------------------------------

// TestScenario returns a deterministic adversarial Scenario.
func TestScenario(index int) core.Scenario {
	return core.Scenario{
		ScenarioID:  fmt.Sprintf("scenario-%04d", index),
		Name:        fmt.Sprintf("StressScenario%d", index),
		Description: fmt.Sprintf("Test stress scenario %d", index),
		MarketShocks: map[string]float64{
			"BTC": -0.2 - float64(index)*0.05,
			"ETH": -0.15 - float64(index)*0.03,
		},
		VolMultiplier:        2.0 + float64(index)*0.5,
		CorrelationBreakdown: index%2 == 0,
		Severity:             0.3 + float64(index%7)*0.1,
	}
}
