// attention_router.go — scaled dot-product attention routing for Omega.
//
// Architecture (v2 — Phase 1: hand-initialised weights):
//
//   Attention(Q, K, V) = softmax(Q·Kᵀ / √d_k) · V
//
//   Q  = LinearGoalEncoder.Encode(goal)       → ℝ^d_q
//   K  = NodeProjector.Key(tensor, caps)       → ℝ^{N × d_k}
//   V  = NodeProjector.Value(tensor)           → ℝ^{N × d_v}
//   d_q = d_k = d_v = 32
//
// Trust masking:
//   Nodes with trust_score < minTrustForAutonomous receive a −10.0
//   pre-softmax penalty when the goal requires autonomy. This effectively
//   blocks them without requiring a hard capability check.
//
// Weight dimensions:
//   GoalType one-hot:   5 classes
//   Context metrics:    16 slots (padded / truncated to fixed width)
//   State tensor:       16 dims  (Victoria reference)
//   Capability one-hot: len(AllCapabilities) = 8 currently
//   Trust scalar:       1 dim
//
//   LinearGoalEncoder:  W_type    [5 × 32]
//                       W_metrics [16 × 32]
//                       bias      [32]
//
//   NodeProjector:      W_key   [(16+8+1) × 32]  = [25 × 32]
//                       W_value [(16+1)   × 32]  = [17 × 32]

package coordination

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"sync"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const (
	DimModel       = 32 // d_q = d_k = d_v
	DimGoalType    = 5  // one-hot over GoalType enum (0–4)
	DimContextVec  = 16 // fixed-width context metric vector
	DimStateTensor = 16 // Victoria state tensor dimensions
	DimCapability  = 8  // one-hot over AllCapabilities
	DimTrust       = 1  // scalar trust score

	// DimKeyInput = DimStateTensor + DimCapability + DimTrust
	DimKeyInput = DimStateTensor + DimCapability + DimTrust
	// DimValueInput = DimStateTensor + DimTrust
	DimValueInput = DimStateTensor + DimTrust

	MinTrustForAutonomous float32 = 0.7
	AutonomyTrustPenalty  float32 = -10.0
	LowConfidenceThresh   float32 = 0.6
)

// AllCapabilities is the ordered list used for capability one-hot encoding.
// Order must be stable — adding capabilities extends the list at the end.
var AllCapabilities = []string{
	"signal_generation",
	"risk_assessment",
	"backtesting",
	"data_ingestion",
	"portfolio_optimization",
	"anomaly_detection",
	"forecasting",
	"execution",
}

// ---------------------------------------------------------------------------
// GoalEncoder interface
// ---------------------------------------------------------------------------

// GoalEncoder maps a GoalSpec proto to a query vector in ℝ^DimModel.
type GoalEncoder interface {
	Encode(goal *omegav1.GoalSpec) []float32
}

// ---------------------------------------------------------------------------
// LinearGoalEncoder
// ---------------------------------------------------------------------------

// LinearGoalEncoder is the Phase 1 attention encoder: a simple linear
// projection of goal type (one-hot) and context metrics.
//
//	q = W_type · typeVec + W_metrics · metricsVec + bias
type LinearGoalEncoder struct {
	mu       sync.RWMutex
	WType    [][]float32 // [DimGoalType × DimModel]
	WMetrics [][]float32 // [DimContextVec × DimModel]
	Bias     []float32   // [DimModel]
}

// NewLinearGoalEncoder constructs a hand-initialised encoder using
// Xavier/Glorot uniform initialisation.
//
// Matrices are [DimModel × input_dim] so matVecMul(W, v) → [DimModel].
func NewLinearGoalEncoder() *LinearGoalEncoder {
	rng := rand.New(rand.NewSource(time.Now().UnixNano())) //nolint:gosec
	fanIn := float64(DimGoalType + DimContextVec)
	limit := float32(math.Sqrt(6.0 / fanIn))

	return &LinearGoalEncoder{
		WType:    randomMatrix(rng, DimModel, DimGoalType, limit),    // [32×5]
		WMetrics: randomMatrix(rng, DimModel, DimContextVec, limit),  // [32×16]
		Bias:     make([]float32, DimModel),
	}
}

// Encode implements GoalEncoder.
func (e *LinearGoalEncoder) Encode(goal *omegav1.GoalSpec) []float32 {
	e.mu.RLock()
	defer e.mu.RUnlock()

	typeVec := oneHot(int(goal.Type), DimGoalType)
	metricsVec := normaliseMetrics(goal.Context, DimContextVec)

	q := matVecMul(e.WType, typeVec)          // [DimModel]
	matVecMulAccum(e.WMetrics, metricsVec, q) // q += W_metrics · metricsVec
	addVec(q, e.Bias)
	return q
}

// LoadWeights atomically replaces the encoder weights (for hot-swap).
func (e *LinearGoalEncoder) LoadWeights(wType, wMetrics [][]float32, bias []float32) error {
	if len(wType) != DimModel || len(wMetrics) != DimModel {
		return fmt.Errorf("weight dimension mismatch: wType rows %d (want %d), wMetrics rows %d (want %d)",
			len(wType), DimModel, len(wMetrics), DimModel)
	}
	e.mu.Lock()
	e.WType = wType
	e.WMetrics = wMetrics
	e.Bias = bias
	e.mu.Unlock()
	return nil
}

// ---------------------------------------------------------------------------
// NodeProjector
// ---------------------------------------------------------------------------

// NodeProjector computes Key and Value vectors for a node from its state tensor.
type NodeProjector struct {
	mu     sync.RWMutex
	WKey   [][]float32 // [DimKeyInput × DimModel]
	WValue [][]float32 // [DimValueInput × DimModel]
}

// NewNodeProjector constructs a hand-initialised projector.
//
// Matrices are [DimModel × input_dim] so matVecMul(W, v) → [DimModel].
func NewNodeProjector() *NodeProjector {
	rng := rand.New(rand.NewSource(time.Now().UnixNano() + 1)) //nolint:gosec
	limitK := float32(math.Sqrt(6.0 / float64(DimKeyInput)))
	limitV := float32(math.Sqrt(6.0 / float64(DimValueInput)))

	return &NodeProjector{
		WKey:   randomMatrix(rng, DimModel, DimKeyInput, limitK),    // [32×25]
		WValue: randomMatrix(rng, DimModel, DimValueInput, limitV),  // [32×17]
	}
}

// Key returns a DimModel-dimensional key vector for the given node.
//
//	input = [tensor_values | capability_onehot | trust_score]
//	key   = W_key · input
func (p *NodeProjector) Key(tensor *omegav1.StateTensor, caps []string) []float32 {
	p.mu.RLock()
	defer p.mu.RUnlock()

	stateVec := tensorToFloat32s(tensor, DimStateTensor)
	capVec := capabilityOnehot(caps)
	trust := namedFloat(tensor, "trust_score", 0.5)

	input := make([]float32, 0, DimKeyInput)
	input = append(input, stateVec...)
	input = append(input, capVec...)
	input = append(input, trust)

	return matVecMul(p.WKey, input)
}

// Value returns a DimModel-dimensional value vector for the given node.
//
//	input = [tensor_values | trust_score]
//	value = W_value · input
func (p *NodeProjector) Value(tensor *omegav1.StateTensor) []float32 {
	p.mu.RLock()
	defer p.mu.RUnlock()

	stateVec := tensorToFloat32s(tensor, DimStateTensor)
	trust := namedFloat(tensor, "trust_score", 0.5)

	input := make([]float32, 0, DimValueInput)
	input = append(input, stateVec...)
	input = append(input, trust)

	return matVecMul(p.WValue, input)
}

// LoadWeights atomically replaces the projector weights.
func (p *NodeProjector) LoadWeights(wKey, wValue [][]float32) error {
	if len(wKey) != DimModel || len(wValue) != DimModel {
		return fmt.Errorf("weight dimension mismatch: wKey rows %d (want %d), wValue rows %d (want %d)",
			len(wKey), DimModel, len(wValue), DimModel)
	}
	p.mu.Lock()
	p.WKey = wKey
	p.WValue = wValue
	p.mu.Unlock()
	return nil
}

// ---------------------------------------------------------------------------
// AttentionRouter
// ---------------------------------------------------------------------------

// RoutingResult is the output of a single routing decision.
type RoutingResult struct {
	// PrimaryNode is the node_id with the highest attention weight.
	PrimaryNode string
	// NodeWeights maps node_id → softmax attention weight α_i.
	NodeWeights map[string]float32
	// Confidence is max(α) — below LowConfidenceThresh indicates uncertainty.
	Confidence float32
	// RoutingVector is the weighted sum α·V, persisted for v3 composition discovery.
	RoutingVector []float32
}

// ToProto converts a RoutingResult to the wire type.
func (r *RoutingResult) ToProto() *omegav1.RoutingPlan {
	return &omegav1.RoutingPlan{
		PrimaryNode:   r.PrimaryNode,
		NodeWeights:   r.NodeWeights,
		Confidence:    r.Confidence,
		RoutingVector: r.RoutingVector,
	}
}

// AttentionRouter routes goals to nodes using scaled dot-product attention.
type AttentionRouter struct {
	encoder   GoalEncoder
	projector *NodeProjector
	adapter   *RoutingWeightAdapter // EMA priors — may be nil
}

// NewAttentionRouter creates an AttentionRouter with hand-initialised weights.
func NewAttentionRouter() *AttentionRouter {
	return &AttentionRouter{
		encoder:   NewLinearGoalEncoder(),
		projector: NewNodeProjector(),
	}
}

// NewAttentionRouterWithDeps creates an AttentionRouter with injected dependencies.
func NewAttentionRouterWithDeps(
	enc GoalEncoder,
	proj *NodeProjector,
	adapter *RoutingWeightAdapter,
) *AttentionRouter {
	return &AttentionRouter{
		encoder:   enc,
		projector: proj,
		adapter:   adapter,
	}
}

// Route selects the best node(s) for a goal given the current tensor map.
//
// nodes provides the node_id → capability list mapping.
// tensors provides the latest StateTensor per node_id.
//
// Returns an error only if no candidate nodes are available.
func (r *AttentionRouter) Route(
	goal *omegav1.GoalSpec,
	tensors map[string]*omegav1.StateTensor,
	capabilities map[string][]string,
) (*RoutingResult, error) {
	// Build stable-sorted candidate list
	nodeIDs := sortedKeys(tensors)
	if len(nodeIDs) == 0 {
		return nil, fmt.Errorf("no candidate nodes available")
	}

	// 1. Encode goal → query vector
	q := r.encoder.Encode(goal)

	// 2. Build Key and Value matrices
	keys := make([][]float32, len(nodeIDs))
	values := make([][]float32, len(nodeIDs))
	for i, nid := range nodeIDs {
		tensor := tensors[nid]
		caps := capabilities[nid]
		keys[i] = r.projector.Key(tensor, caps)
		values[i] = r.projector.Value(tensor)
	}

	// 3. Scaled dot-product scores: s_i = Q·K_i / √d_k
	scores := dotProducts(q, keys)
	scale := float32(math.Sqrt(float64(DimModel)))
	for i, nid := range nodeIDs {
		scores[i] /= scale

		// Apply EMA prior modulation (adds a small additive prior)
		if r.adapter != nil {
			prior := r.adapter.PriorFor(nid)
			// Scale prior to centred range: prior ∈ [0,1] → bias ∈ [-0.5, 0.5]
			scores[i] += (prior - 0.5)
		}

		// Trust masking: nodes below trust threshold get penalised pre-softmax
		if goal.RequiresAutonomy {
			trust := namedFloat(tensors[nid], "trust_score", 0.5)
			if trust < MinTrustForAutonomous {
				scores[i] += AutonomyTrustPenalty
			}
		}
	}

	// 4. Softmax → attention weights α
	alpha := softmax(scores)

	// 5. Weighted value sum → routing vector
	routingVec := weightedSum(alpha, values)

	// 6. Find primary node (argmax α)
	primaryIdx := argmax(alpha)
	primary := nodeIDs[primaryIdx]

	nodeWeights := make(map[string]float32, len(nodeIDs))
	for i, nid := range nodeIDs {
		nodeWeights[nid] = alpha[i]
	}

	return &RoutingResult{
		PrimaryNode:   primary,
		NodeWeights:   nodeWeights,
		Confidence:    alpha[primaryIdx],
		RoutingVector: routingVec,
	}, nil
}

// ---------------------------------------------------------------------------
// Linear algebra helpers
// ---------------------------------------------------------------------------

// matVecMul computes m · v → result (new slice).
// m is [rows × cols], v is [cols].
func matVecMul(m [][]float32, v []float32) []float32 {
	rows := len(m)
	out := make([]float32, rows)
	for i, row := range m {
		var acc float32
		for j, w := range row {
			if j < len(v) {
				acc += w * v[j]
			}
		}
		out[i] = acc
	}
	return out
}

// matVecMulAccum adds m · v into dst in-place.
func matVecMulAccum(m [][]float32, v []float32, dst []float32) {
	for i, row := range m {
		for j, w := range row {
			if j < len(v) && i < len(dst) {
				dst[i] += w * v[j]
			}
		}
	}
}

// addVec adds b into a in-place (a += b).
func addVec(a, b []float32) {
	for i := range a {
		if i < len(b) {
			a[i] += b[i]
		}
	}
}

// dotProducts computes q · k_i for each key vector k_i.
func dotProducts(q []float32, keys [][]float32) []float32 {
	scores := make([]float32, len(keys))
	for i, k := range keys {
		var dot float32
		for j := range q {
			if j < len(k) {
				dot += q[j] * k[j]
			}
		}
		scores[i] = dot
	}
	return scores
}

// softmax applies numerically stable softmax.
func softmax(x []float32) []float32 {
	if len(x) == 0 {
		return nil
	}
	maxVal := x[0]
	for _, v := range x[1:] {
		if v > maxVal {
			maxVal = v
		}
	}
	out := make([]float32, len(x))
	var sum float32
	for i, v := range x {
		out[i] = float32(math.Exp(float64(v - maxVal)))
		sum += out[i]
	}
	for i := range out {
		out[i] /= sum
	}
	return out
}

// weightedSum computes Σ alpha_i · V_i.
func weightedSum(alpha []float32, values [][]float32) []float32 {
	if len(values) == 0 {
		return nil
	}
	dim := len(values[0])
	out := make([]float32, dim)
	for i, v := range values {
		w := alpha[i]
		for j, vj := range v {
			out[j] += w * vj
		}
	}
	return out
}

// argmax returns the index of the maximum element.
func argmax(x []float32) int {
	best := 0
	for i := 1; i < len(x); i++ {
		if x[i] > x[best] {
			best = i
		}
	}
	return best
}

// oneHot returns a one-hot vector of length n with index i set.
func oneHot(i, n int) []float32 {
	v := make([]float32, n)
	if i >= 0 && i < n {
		v[i] = 1.0
	}
	return v
}

// normaliseMetrics converts a map of metric values to a fixed-length vector.
// Keys are sorted for stability; the vector is zero-padded to length n.
func normaliseMetrics(ctx map[string]float32, n int) []float32 {
	v := make([]float32, n)
	keys := make([]string, 0, len(ctx))
	for k := range ctx {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for i, k := range keys {
		if i >= n {
			break
		}
		// Normalise to [−1, 1] heuristically; most metrics are [0,1] already.
		v[i] = clampF32(ctx[k], -1.0, 1.0)
	}
	return v
}

// capabilityOnehot encodes a capability list as a multi-hot vector over AllCapabilities.
func capabilityOnehot(caps []string) []float32 {
	v := make([]float32, DimCapability)
	capSet := make(map[string]struct{}, len(caps))
	for _, c := range caps {
		capSet[c] = struct{}{}
	}
	for i, c := range AllCapabilities {
		if _, ok := capSet[c]; ok {
			v[i] = 1.0
		}
	}
	return v
}

// tensorToFloat32s extracts float32 values from a StateTensor.
// Returns a zero-padded vector of length n.
func tensorToFloat32s(t *omegav1.StateTensor, n int) []float32 {
	v := make([]float32, n)
	if t == nil || len(t.Values) == 0 {
		return v
	}
	floats, err := bytesToFloat32s(t.Values)
	if err != nil {
		return v
	}
	for i := 0; i < n && i < len(floats); i++ {
		v[i] = floats[i]
	}
	return v
}

// randomMatrix returns an [rows × cols] matrix with uniform random values in [−limit, limit].
func randomMatrix(rng *rand.Rand, rows, cols int, limit float32) [][]float32 {
	m := make([][]float32, rows)
	for i := range m {
		m[i] = make([]float32, cols)
		for j := range m[i] {
			m[i][j] = (rng.Float32()*2 - 1) * limit
		}
	}
	return m
}

// sortedKeys returns map keys in lexicographic order.
func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// clampF32 clamps a float32 to [lo, hi].
func clampF32(v, lo, hi float32) float32 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
