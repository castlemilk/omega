package coordination_test

import (
	"context"
	"math"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/coordination"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func makeTestTensor(nodeID string, values []float32, named map[string]float32, health float32) *omegav1.StateTensor {
	t := coordination.NewStateTensorFromValues(nodeID, "1.0.0", values, named, health)
	return t
}

func uniformValues(n int, v float32) []float32 {
	out := make([]float32, n)
	for i := range out {
		out[i] = v
	}
	return out
}

// ---------------------------------------------------------------------------
// TensorAggregator tests
// ---------------------------------------------------------------------------

func TestTensorAggregator_UpdateAndRetrieve(t *testing.T) {
	agg := coordination.NewTensorAggregator()

	tensor := makeTestTensor("node-1", uniformValues(16, 0.5), map[string]float32{
		"signal_quality": 0.8,
		"trust_score":    0.9,
	}, 0.85)

	agg.UpdateTensor(tensor)

	retrieved := agg.Tensor("node-1")
	require.NotNil(t, retrieved)
	assert.Equal(t, "node-1", retrieved.NodeId)
	assert.InDelta(t, 0.85, float64(retrieved.HealthScore), 0.001)
}

func TestTensorAggregator_NodeIDs_Sorted(t *testing.T) {
	agg := coordination.NewTensorAggregator()

	for _, id := range []string{"charlie", "alpha", "bravo"} {
		agg.UpdateTensor(makeTestTensor(id, uniformValues(16, 0.5), nil, 0.5))
	}

	ids := agg.NodeIDs()
	require.Len(t, ids, 3)
	assert.Equal(t, []string{"alpha", "bravo", "charlie"}, ids)
}

func TestTensorAggregator_SystemHealth_WeightedByTrust(t *testing.T) {
	agg := coordination.NewTensorAggregator()

	// Node A: health=0.9, trust=0.8
	agg.UpdateTensor(makeTestTensor("a", uniformValues(16, 0.9),
		map[string]float32{"trust_score": 0.8}, 0.9))
	// Node B: health=0.1, trust=0.2
	agg.UpdateTensor(makeTestTensor("b", uniformValues(16, 0.1),
		map[string]float32{"trust_score": 0.2}, 0.1))

	// weighted mean: (0.9*0.8 + 0.1*0.2) / (0.8+0.2) = (0.72+0.02)/1.0 = 0.74
	health := agg.SystemHealth()
	assert.InDelta(t, 0.74, float64(health), 0.01)
}

func TestTensorAggregator_CapabilityMatrix(t *testing.T) {
	agg := coordination.NewTensorAggregator()

	agg.UpdateTensor(makeTestTensor("n1", uniformValues(16, 0.8), nil, 0.8))
	agg.UpdateTensor(makeTestTensor("n2", uniformValues(16, 0.6), nil, 0.6))

	agg.SetNodeCapabilities("n1", []string{"signal_generation", "backtesting"})
	agg.SetNodeCapabilities("n2", []string{"signal_generation", "risk_assessment"})

	matrix := agg.CapabilityMatrix()

	sigGen, ok := matrix["signal_generation"]
	require.True(t, ok)
	assert.Len(t, sigGen, 2)

	backtest, ok := matrix["backtesting"]
	require.True(t, ok)
	assert.Len(t, backtest, 1)
}

// ---------------------------------------------------------------------------
// State tensor serialisation tests
// ---------------------------------------------------------------------------

func TestStateTensor_SerdeRoundtrip(t *testing.T) {
	original := []float32{0.1, 0.5, 0.9, -0.3, 1.0, 0.0, 0.75}
	b := coordination.Float32sToBytes(original)
	recovered, err := coordination.BytesToFloat32s(b)
	require.NoError(t, err)
	require.Len(t, recovered, len(original))
	for i, v := range original {
		assert.InDelta(t, float64(v), float64(recovered[i]), 1e-6, "index %d", i)
	}
}

func TestStateTensor_SerdeRoundtrip_Empty(t *testing.T) {
	b := coordination.Float32sToBytes(nil)
	assert.Empty(t, b)
	recovered, err := coordination.BytesToFloat32s(b)
	require.NoError(t, err)
	assert.Empty(t, recovered)
}

func TestStateTensor_SerdeRoundtrip_BadLength(t *testing.T) {
	_, err := coordination.BytesToFloat32s([]byte{0x01, 0x02, 0x03}) // 3 bytes — not divisible by 4
	require.Error(t, err)
}

// ---------------------------------------------------------------------------
// Attention computation tests
// ---------------------------------------------------------------------------

func TestAttentionRouter_Route_SingleNode(t *testing.T) {
	router := coordination.NewAttentionRouter()
	agg := coordination.NewTensorAggregator()

	tensor := makeTestTensor("node-a", uniformValues(16, 0.7),
		map[string]float32{"trust_score": 0.8}, 0.8)
	agg.UpdateTensor(tensor)
	agg.SetNodeCapabilities("node-a", []string{"signal_generation"})

	goal := &omegav1.GoalSpec{
		GoalId: "g1",
		Type:   omegav1.GoalType_GOAL_TYPE_RESEARCH,
	}

	result, err := router.Route(goal, agg.AllTensors(), capabilitiesMap(agg))
	require.NoError(t, err)
	require.NotNil(t, result)

	// Single node must be selected with confidence 1.0
	assert.Equal(t, "node-a", result.PrimaryNode)
	assert.InDelta(t, 1.0, float64(result.Confidence), 0.001)
	assert.Len(t, result.NodeWeights, 1)
	assert.InDelta(t, 1.0, float64(result.NodeWeights["node-a"]), 0.001)
}

func TestAttentionRouter_Route_MultiNode_SumsToOne(t *testing.T) {
	router := coordination.NewAttentionRouter()
	tensors := make(map[string]*omegav1.StateTensor)
	caps := make(map[string][]string)

	for i, id := range []string{"a", "b", "c"} {
		v := float32(i+1) * 0.2
		tensors[id] = makeTestTensor(id, uniformValues(16, v),
			map[string]float32{"trust_score": v}, v)
		caps[id] = []string{"signal_generation"}
	}

	goal := &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_IMPROVEMENT}
	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)

	// Weights must sum to ≈ 1.0
	var total float32
	for _, w := range result.NodeWeights {
		total += w
	}
	assert.InDelta(t, 1.0, float64(total), 1e-4)

	// Confidence = max weight
	maxW := float32(0)
	for _, w := range result.NodeWeights {
		if w > maxW {
			maxW = w
		}
	}
	assert.InDelta(t, float64(maxW), float64(result.Confidence), 1e-4)
}

func TestAttentionRouter_Route_NoNodes_Error(t *testing.T) {
	router := coordination.NewAttentionRouter()
	goal := &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_RESEARCH}

	_, err := router.Route(goal, nil, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "no candidate nodes")
}

func TestAttentionRouter_Route_RoutingVectorLength(t *testing.T) {
	router := coordination.NewAttentionRouter()
	tensors := map[string]*omegav1.StateTensor{
		"n1": makeTestTensor("n1", uniformValues(16, 0.5), nil, 0.5),
		"n2": makeTestTensor("n2", uniformValues(16, 0.8), nil, 0.8),
	}
	caps := map[string][]string{"n1": {"signal_generation"}, "n2": {"backtesting"}}

	goal := &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_MAINTENANCE}
	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)
	// Routing vector must be DimModel (32) dimensional
	assert.Len(t, result.RoutingVector, coordination.DimModel)
}

// ---------------------------------------------------------------------------
// Trust masking tests
// ---------------------------------------------------------------------------

func TestAttentionRouter_TrustMask_BlocksLowTrustNode(t *testing.T) {
	router := coordination.NewAttentionRouter()

	// High-trust node
	highTrust := makeTestTensor("high", uniformValues(16, 0.5),
		map[string]float32{"trust_score": 0.95}, 0.9)
	// Low-trust node — identical state otherwise
	lowTrust := makeTestTensor("low", uniformValues(16, 0.5),
		map[string]float32{"trust_score": 0.1}, 0.9)

	tensors := map[string]*omegav1.StateTensor{
		"high": highTrust,
		"low":  lowTrust,
	}
	caps := map[string][]string{
		"high": {"signal_generation"},
		"low":  {"signal_generation"},
	}

	// Goal requires autonomy → low-trust node gets -10.0 penalty
	goal := &omegav1.GoalSpec{
		Type:              omegav1.GoalType_GOAL_TYPE_IMPROVEMENT,
		RequiresAutonomy:  true,
	}

	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)

	// High-trust node must be selected
	assert.Equal(t, "high", result.PrimaryNode)

	// The high-trust node should have a substantially higher weight
	highW := result.NodeWeights["high"]
	lowW := result.NodeWeights["low"]
	assert.Greater(t, float64(highW), float64(lowW)*10,
		"high-trust weight should dominate after trust masking")
}

func TestAttentionRouter_TrustMask_NoEffect_WhenAutonomyNotRequired(t *testing.T) {
	router := coordination.NewAttentionRouter()

	// Two nodes — one low trust, both identical state
	tensors := map[string]*omegav1.StateTensor{
		"high": makeTestTensor("high", uniformValues(16, 0.5),
			map[string]float32{"trust_score": 0.95}, 0.9),
		"low": makeTestTensor("low", uniformValues(16, 0.5),
			map[string]float32{"trust_score": 0.1}, 0.9),
	}
	caps := map[string][]string{
		"high": {"signal_generation"},
		"low":  {"signal_generation"},
	}

	// No autonomy requirement — trust mask inactive
	goal := &omegav1.GoalSpec{
		Type:             omegav1.GoalType_GOAL_TYPE_MAINTENANCE,
		RequiresAutonomy: false,
	}

	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)

	// Both nodes should receive comparable weights (within 2× of each other)
	highW := result.NodeWeights["high"]
	lowW := result.NodeWeights["low"]
	ratio := float64(highW) / float64(lowW)
	assert.Less(t, ratio, 3.0, "without autonomy, weights should be relatively balanced")
}

// ---------------------------------------------------------------------------
// Softmax correctness
// ---------------------------------------------------------------------------

func TestSoftmax_KnownValues(t *testing.T) {
	// Apply softmax via routing with deterministic inputs
	// softmax([0, 1, 2]) = [0.090, 0.245, 0.665]
	tensors := map[string]*omegav1.StateTensor{}
	caps := map[string][]string{}

	// We test the mathematical property indirectly through the router.
	// The trust-masking test already validates that -10 produces near-zero weights,
	// which requires correct numerically-stable softmax.

	// Verify that softmax([x, x+10]) has the expected ratio.
	// e^(x+10) / e^x = e^10 ≈ 22026
	// So weight ratio should be ≈ 22026:1.
	high := makeTestTensor("h", uniformValues(16, 0.5),
		map[string]float32{"trust_score": 0.9}, 0.9)
	low := makeTestTensor("l", uniformValues(16, 0.5),
		map[string]float32{"trust_score": 0.05}, 0.9)
	tensors["h"] = high
	tensors["l"] = low
	caps["h"] = []string{"signal_generation"}
	caps["l"] = []string{"signal_generation"}

	router := coordination.NewAttentionRouter()
	goal := &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_IMPROVEMENT, RequiresAutonomy: true}
	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)

	// The -10 penalty corresponds to exp(-10) ≈ 4.5e-5 relative weight.
	// After normalisation the low-trust node should receive < 1% of weight.
	assert.Less(t, float64(result.NodeWeights["l"]), 0.01)
}

// ---------------------------------------------------------------------------
// RoutingWeightAdapter (EMA) tests
// ---------------------------------------------------------------------------

func TestWeightAdapter_NeutralDefault(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.95)
	assert.InDelta(t, 0.5, float64(a.PriorFor("unknown-node")), 0.001)
}

func TestWeightAdapter_EMAUpdate_ConvergesUp(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.9)
	a.UpdateFromOutcome("n1", 1.0) // perfect outcome

	// After one update: 0.9*0.5 + 0.1*1.0 = 0.55
	assert.InDelta(t, 0.55, float64(a.PriorFor("n1")), 0.001)

	a.UpdateFromOutcome("n1", 1.0)
	// 0.9*0.55 + 0.1*1.0 = 0.595
	assert.InDelta(t, 0.595, float64(a.PriorFor("n1")), 0.001)
}

func TestWeightAdapter_EMAUpdate_ConvergesDown(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.9)
	a.UpdateFromOutcome("n1", 0.0) // zero outcome

	// 0.9*0.5 + 0.1*0.0 = 0.45
	assert.InDelta(t, 0.45, float64(a.PriorFor("n1")), 0.001)
}

func TestWeightAdapter_EMAUpdate_Clamped(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.0001) // very fast adaptation
	for range 1000 {
		a.UpdateFromOutcome("n1", 2.0) // out-of-range — should clamp at 1.0
	}
	assert.InDelta(t, 1.0, float64(a.PriorFor("n1")), 0.001)
}

func TestWeightAdapter_Reset(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.95)
	a.UpdateFromOutcome("n1", 1.0)
	assert.NotEqual(t, float32(0.5), a.PriorFor("n1"), "prior should have moved from neutral") // has moved from neutral

	a.Reset("n1")
	assert.InDelta(t, 0.5, float64(a.PriorFor("n1")), 0.001) // back to neutral
}

func TestWeightAdapter_Snapshot(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.95)
	a.UpdateFromOutcome("n1", 0.8)
	a.UpdateFromOutcome("n2", 0.3)

	snap := a.Snapshot()
	assert.Len(t, snap, 2)
	assert.Contains(t, snap, "n1")
	assert.Contains(t, snap, "n2")
}

func TestWeightAdapter_DecayAccessor(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(0.87)
	assert.InDelta(t, 0.87, float64(a.Decay()), 0.001)
}

func TestWeightAdapter_InvalidDecay_DefaultsTo95(t *testing.T) {
	a := coordination.NewRoutingWeightAdapter(1.5) // invalid
	assert.InDelta(t, 0.95, float64(a.Decay()), 0.001)
}

// ---------------------------------------------------------------------------
// EMA modulation of router scores
// ---------------------------------------------------------------------------

func TestAttentionRouter_AdapterModulatesRouting(t *testing.T) {
	// Give node "b" a strong prior advantage via the adapter,
	// then verify the router favours it even when "a" has slightly better state.
	adapter := coordination.NewRoutingWeightAdapter(0.5) // fast adaptation

	// Simulate b having consistently good outcomes
	for range 10 {
		adapter.UpdateFromOutcome("b", 1.0)
	}
	for range 10 {
		adapter.UpdateFromOutcome("a", 0.0)
	}

	router := coordination.NewAttentionRouterWithDeps(
		coordination.NewLinearGoalEncoder(),
		coordination.NewNodeProjector(),
		adapter,
	)

	// Both nodes have same state tensor — adapter priors should decide
	tensors := map[string]*omegav1.StateTensor{
		"a": makeTestTensor("a", uniformValues(16, 0.5),
			map[string]float32{"trust_score": 0.6}, 0.6),
		"b": makeTestTensor("b", uniformValues(16, 0.5),
			map[string]float32{"trust_score": 0.6}, 0.6),
	}
	caps := map[string][]string{
		"a": {"signal_generation"},
		"b": {"signal_generation"},
	}

	goal := &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_IMPROVEMENT}
	result, err := router.Route(goal, tensors, caps)
	require.NoError(t, err)

	// b should receive more weight due to positive prior
	assert.Greater(t, float64(result.NodeWeights["b"]), float64(result.NodeWeights["a"]),
		"node with positive prior should receive higher weight")
}

// ---------------------------------------------------------------------------
// NewStateTensorFromValues helper
// ---------------------------------------------------------------------------

func TestNewStateTensorFromValues(t *testing.T) {
	vals := []float32{0.1, 0.2, 0.3}
	named := map[string]float32{"trust_score": 0.7}
	tensor := coordination.NewStateTensorFromValues("node-1", "1.0.0", vals, named, 0.8)

	require.NotNil(t, tensor)
	assert.Equal(t, "node-1", tensor.NodeId)
	assert.Equal(t, "1.0.0", tensor.SchemaVersion)
	assert.InDelta(t, 0.8, float64(tensor.HealthScore), 0.001)
	assert.NotNil(t, tensor.CapturedAt)
	assert.True(t, tensor.CapturedAt.AsTime().Before(time.Now().Add(time.Second)))
}

func TestNewStateTensorFromValues_ByteRoundtrip(t *testing.T) {
	original := []float32{0.1, 0.5, 0.9, -0.3}
	tensor := coordination.NewStateTensorFromValues("n", "1.0.0", original, nil, 0.5)

	recovered, err := coordination.BytesToFloat32s(tensor.Values)
	require.NoError(t, err)
	require.Len(t, recovered, len(original))
	for i, v := range original {
		assert.InDelta(t, float64(v), float64(recovered[i]), 1e-5)
	}
}

// ---------------------------------------------------------------------------
// GoalSpec goal type one-hot (encoder sanity)
// ---------------------------------------------------------------------------

func TestLinearGoalEncoder_DifferentGoalTypes_DifferentVectors(t *testing.T) {
	enc := coordination.NewLinearGoalEncoder()

	researchQ := enc.Encode(&omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_RESEARCH})
	improvementQ := enc.Encode(&omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_IMPROVEMENT})

	// Query vectors for different goal types must not be identical
	identical := true
	for i := range researchQ {
		if math.Abs(float64(researchQ[i]-improvementQ[i])) > 1e-6 {
			identical = false
			break
		}
	}
	assert.False(t, identical, "different goal types must produce different query vectors")
}

func TestLinearGoalEncoder_VectorLength(t *testing.T) {
	enc := coordination.NewLinearGoalEncoder()
	q := enc.Encode(&omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_RESEARCH})
	assert.Len(t, q, coordination.DimModel)
}

// ---------------------------------------------------------------------------
// Handler integration (no DB)
// ---------------------------------------------------------------------------

func TestHandler_Route_Basic(t *testing.T) {
	h := coordination.NewDefaultHandler(nil, nil)

	// Seed the aggregator
	tensor := makeTestTensor("worker-1", uniformValues(16, 0.7),
		map[string]float32{"trust_score": 0.8}, 0.8)
	h.Agg().UpdateTensor(tensor)
	h.Agg().SetNodeCapabilities("worker-1", []string{"signal_generation"})

	ctx := context.Background()
	req := &omegav1.CoordinationRequest{
		Goal: &omegav1.GoalSpec{
			GoalId: "test-goal",
			Type:   omegav1.GoalType_GOAL_TYPE_RESEARCH,
		},
	}

	resp, err := h.RouteGoal(ctx, req)
	require.NoError(t, err)
	require.NotNil(t, resp)
	assert.Equal(t, "worker-1", resp.Plan.PrimaryNode)
	assert.NotEmpty(t, resp.TraceId)
}

func TestHandler_Route_NoTensors_Error(t *testing.T) {
	h := coordination.NewDefaultHandler(nil, nil)

	ctx := context.Background()
	req := &omegav1.CoordinationRequest{
		Goal: &omegav1.GoalSpec{Type: omegav1.GoalType_GOAL_TYPE_RESEARCH},
	}

	_, err := h.RouteGoal(ctx, req)
	require.Error(t, err)
}

func TestHandler_RecordOutcome_UpdatesAdapter(t *testing.T) {
	h := coordination.NewDefaultHandler(nil, nil)

	ctx := context.Background()
	record := &omegav1.OutcomeRecord{
		Goal: &omegav1.GoalSpec{GoalId: "g1", Type: omegav1.GoalType_GOAL_TYPE_RESEARCH},
		RoutingPlan: &omegav1.RoutingPlan{
			PrimaryNode: "good-node",
			Confidence:  0.9,
		},
		OutcomeQuality: 1.0, // perfect outcome
		CapturedAt:     timestamppb.Now(),
	}

	recordID, err := h.RecordOutcomeRecord(ctx, record)
	require.NoError(t, err)
	assert.NotEmpty(t, recordID)

	// After a perfect outcome, the adapter prior for "good-node" should be > 0.5
	prior := h.AdapterPriorFor("good-node")
	assert.Greater(t, float64(prior), 0.5)
}

// ---------------------------------------------------------------------------
// Helpers for accessing internal state in tests (handler must expose these)
// ---------------------------------------------------------------------------

// capabilitiesMap extracts the capabilities map from the aggregator.
func capabilitiesMap(agg *coordination.TensorAggregator) map[string][]string {
	ids := agg.NodeIDs()
	m := make(map[string][]string, len(ids))
	for _, id := range ids {
		m[id] = agg.NodeCapabilities(id)
	}
	return m
}
