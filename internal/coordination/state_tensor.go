// Package coordination implements the Coordination Layer v2 — attention-based routing.
//
// state_tensor.go provides:
//   - TensorAggregator: in-memory map of node_id → latest StateTensor
//   - TensorPublisher: interface for publishing tensors on heartbeat (Postgres or other)
//   - PostgresTensorPublisher: Postgres LISTEN/NOTIFY implementation
package coordination

import (
	"context"
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// ---------------------------------------------------------------------------
// TensorPublisher — abstract pub/sub interface
// ---------------------------------------------------------------------------

// TensorPublisher abstracts the transport used to broadcast state tensors from
// nodes to the coordinator. Implementations must be safe for concurrent use.
type TensorPublisher interface {
	// Publish sends a state tensor snapshot to all subscribers.
	// Implementations must not block the caller; use a buffered channel or
	// goroutine-per-publish as needed.
	Publish(ctx context.Context, tensor *omegav1.StateTensor) error

	// Subscribe returns a channel that receives tensors as they arrive.
	// The channel is closed when ctx is cancelled.
	Subscribe(ctx context.Context) (<-chan *omegav1.StateTensor, error)
}

// ---------------------------------------------------------------------------
// PostgresTensorPublisher — LISTEN/NOTIFY implementation
// ---------------------------------------------------------------------------

const pgChannelStateTensor = "omega_state_tensor"

// PostgresTensorPublisher publishes state tensors using Postgres LISTEN/NOTIFY.
//
// The payload is a compact JSON envelope:
//
//	{"node_id": "...", "schema_version": "...", "values": <base64>, "health_score": 0.87, ...}
//
// Consumers who want the full raw tensor subscribe via Subscribe(); the in-process
// TensorAggregator directly calls Publish() and updates its own cache without going
// through NOTIFY to avoid round-tripping.
type PostgresTensorPublisher struct {
	db *sql.DB
}

// NewPostgresTensorPublisher creates a publisher backed by the given *sql.DB.
// The DB must be a Postgres connection pool (not SQLite).
func NewPostgresTensorPublisher(db *sql.DB) *PostgresTensorPublisher {
	return &PostgresTensorPublisher{db: db}
}

type tensorEnvelope struct {
	NodeID        string             `json:"node_id"`
	SchemaVersion string             `json:"schema_version"`
	Values        []float32          `json:"values"`
	Named         map[string]float32 `json:"named"`
	HealthScore   float32            `json:"health_score"`
	CapturedAt    int64              `json:"captured_at_ns"` // Unix nanoseconds
}

func (p *PostgresTensorPublisher) Publish(ctx context.Context, tensor *omegav1.StateTensor) error {
	env := tensorEnvelope{
		NodeID:        tensor.NodeId,
		SchemaVersion: tensor.SchemaVersion,
		Named:         tensor.Named,
		HealthScore:   tensor.HealthScore,
		CapturedAt:    time.Now().UnixNano(),
	}

	// Deserialise raw bytes → float32 slice for JSON
	values, err := bytesToFloat32s(tensor.Values)
	if err != nil {
		return fmt.Errorf("decode tensor values: %w", err)
	}
	env.Values = values

	payload, err := json.Marshal(env)
	if err != nil {
		return fmt.Errorf("marshal tensor envelope: %w", err)
	}

	_, err = p.db.ExecContext(ctx, `SELECT pg_notify($1, $2)`, pgChannelStateTensor, string(payload))
	return err
}

// Subscribe opens a new DB connection, issues LISTEN, and delivers tensors on
// the returned channel until ctx is cancelled.
func (p *PostgresTensorPublisher) Subscribe(ctx context.Context) (<-chan *omegav1.StateTensor, error) {
	ch := make(chan *omegav1.StateTensor, 64)

	conn, err := p.db.Conn(ctx)
	if err != nil {
		return nil, fmt.Errorf("acquire connection for LISTEN: %w", err)
	}

	if _, err := conn.ExecContext(ctx, "LISTEN "+pgChannelStateTensor); err != nil {
		conn.Close() //nolint:errcheck,gosec
		return nil, fmt.Errorf("LISTEN %s: %w", pgChannelStateTensor, err)
	}

	go func() {
		defer close(ch)
		defer conn.Close() //nolint:errcheck

		for {
			select {
			case <-ctx.Done():
				return
			default:
			}

			// Use raw connection to poll for notifications.
			// Because database/sql doesn't expose NOTIFY natively, we poll
			// with a short-timeout query that unblocks the listener.
			var payload string
			err := conn.QueryRowContext(ctx, `SELECT pg_notification_queue_usage()`).Scan(&payload)
			if err != nil {
				// Context cancelled or connection lost — exit cleanly.
				return
			}

			// Poll notifications via pg_try_advisory_lock trick is complex.
			// For now, sleep briefly and re-check — production use should
			// use a raw pgx connection with conn.WaitForNotification().
			time.Sleep(50 * time.Millisecond)
		}
	}()

	return ch, nil
}

// ---------------------------------------------------------------------------
// TensorAggregator — in-memory map of latest tensors per node
// ---------------------------------------------------------------------------

// TensorAggregator maintains the latest StateTensor for every node.
// The coordinator calls UpdateTensor() on every heartbeat and reads
// the aggregated view when routing.
type TensorAggregator struct {
	mu      sync.RWMutex
	tensors map[string]*omegav1.StateTensor // node_id → latest tensor
	schemas map[string]*omegav1.StateTensorSchema // node_type → schema
	// nodeCapabilities maps node_id → capability list (set externally)
	nodeCapabilities map[string][]string
}

// NewTensorAggregator creates an empty TensorAggregator.
func NewTensorAggregator() *TensorAggregator {
	return &TensorAggregator{
		tensors:          make(map[string]*omegav1.StateTensor),
		schemas:          make(map[string]*omegav1.StateTensorSchema),
		nodeCapabilities: make(map[string][]string),
	}
}

// RegisterSchema registers a node type schema for capability matrix queries.
func (a *TensorAggregator) RegisterSchema(schema *omegav1.StateTensorSchema) {
	a.mu.Lock()
	a.schemas[schema.NodeType] = schema
	a.mu.Unlock()
}

// SetNodeCapabilities updates the capability list for a node.
func (a *TensorAggregator) SetNodeCapabilities(nodeID string, caps []string) {
	a.mu.Lock()
	a.nodeCapabilities[nodeID] = caps
	a.mu.Unlock()
}

// UpdateTensor stores the latest tensor for a node.
func (a *TensorAggregator) UpdateTensor(tensor *omegav1.StateTensor) {
	a.mu.Lock()
	a.tensors[tensor.NodeId] = tensor
	a.mu.Unlock()
}

// Tensor returns the latest tensor for a node, or nil if not present.
func (a *TensorAggregator) Tensor(nodeID string) *omegav1.StateTensor {
	a.mu.RLock()
	t := a.tensors[nodeID]
	a.mu.RUnlock()
	return t
}

// AllTensors returns a snapshot of all current tensors, keyed by node_id.
func (a *TensorAggregator) AllTensors() map[string]*omegav1.StateTensor {
	a.mu.RLock()
	out := make(map[string]*omegav1.StateTensor, len(a.tensors))
	for k, v := range a.tensors {
		out[k] = v
	}
	a.mu.RUnlock()
	return out
}

// NodeIDs returns a sorted list of all node IDs with known tensors.
func (a *TensorAggregator) NodeIDs() []string {
	a.mu.RLock()
	ids := make([]string, 0, len(a.tensors))
	for id := range a.tensors {
		ids = append(ids, id)
	}
	a.mu.RUnlock()
	sort.Strings(ids)
	return ids
}

// NodeCapabilities returns the capabilities for a given node ID.
func (a *TensorAggregator) NodeCapabilities(nodeID string) []string {
	a.mu.RLock()
	caps := a.nodeCapabilities[nodeID]
	a.mu.RUnlock()
	return caps
}

// SystemHealth computes a weighted mean health score across all nodes.
// Nodes with a higher trust_score receive more weight.
func (a *TensorAggregator) SystemHealth() float32 {
	a.mu.RLock()
	tensors := a.tensors
	a.mu.RUnlock()

	var weightedSum, weightSum float32
	for _, t := range tensors {
		trust := namedFloat(t, "trust_score", 0.5)
		weightedSum += t.HealthScore * trust
		weightSum += trust
	}
	if weightSum == 0 {
		return 0
	}
	return weightedSum / weightSum
}

// CapabilityMatrix returns a map of capability → []healthScore, one per node
// that advertises that capability. Used by the router to build the Keys matrix.
func (a *TensorAggregator) CapabilityMatrix() map[string][]float32 {
	a.mu.RLock()
	tensors := a.tensors
	caps := a.nodeCapabilities
	a.mu.RUnlock()

	result := make(map[string][]float32)
	for nodeID, t := range tensors {
		for _, cap := range caps[nodeID] {
			result[cap] = append(result[cap], t.HealthScore)
		}
	}
	return result
}

// ---------------------------------------------------------------------------
// Wire: subscribe to publisher and keep aggregator current
// ---------------------------------------------------------------------------

// StartListening subscribes to the publisher and feeds tensors into the
// aggregator until ctx is cancelled. Run in a goroutine.
func StartListening(ctx context.Context, pub TensorPublisher, agg *TensorAggregator) error {
	ch, err := pub.Subscribe(ctx)
	if err != nil {
		return fmt.Errorf("subscribe to tensor publisher: %w", err)
	}
	go func() {
		for t := range ch {
			agg.UpdateTensor(t)
		}
	}()
	return nil
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func namedFloat(t *omegav1.StateTensor, key string, def float32) float32 {
	if t == nil || t.Named == nil {
		return def
	}
	if v, ok := t.Named[key]; ok {
		return v
	}
	return def
}

// BytesToFloat32s decodes a little-endian float32 byte array.
func BytesToFloat32s(b []byte) ([]float32, error) {
	if len(b)%4 != 0 {
		return nil, fmt.Errorf("byte slice length %d not divisible by 4", len(b))
	}
	n := len(b) / 4
	out := make([]float32, n)
	for i := range out {
		bits := binary.LittleEndian.Uint32(b[i*4 : i*4+4])
		out[i] = math.Float32frombits(bits)
	}
	return out, nil
}

// Float32sToBytes encodes a float32 slice as a little-endian byte array.
func Float32sToBytes(vals []float32) []byte {
	b := make([]byte, len(vals)*4)
	for i, v := range vals {
		binary.LittleEndian.PutUint32(b[i*4:i*4+4], math.Float32bits(v))
	}
	return b
}

// keep unexported aliases for internal callers
func bytesToFloat32s(b []byte) ([]float32, error) { return BytesToFloat32s(b) }
func float32sToBytes(vals []float32) []byte        { return Float32sToBytes(vals) }

// NewStateTensorFromValues constructs a StateTensor proto from raw float32 values
// plus a named map and health score.
func NewStateTensorFromValues(
	nodeID string,
	schemaVersion string,
	values []float32,
	named map[string]float32,
	healthScore float32,
) *omegav1.StateTensor {
	return &omegav1.StateTensor{
		NodeId:        nodeID,
		SchemaVersion: schemaVersion,
		CapturedAt:    timestamppb.Now(),
		Values:        float32sToBytes(values),
		Named:         named,
		HealthScore:   healthScore,
	}
}
