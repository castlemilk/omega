package memory

import (
	"encoding/json"
	"fmt"
	"math"
	"time"
)

// ---------------------------------------------------------------------------
// Fact
// ---------------------------------------------------------------------------

// Fact is a piece of general knowledge stored in semantic memory.
// Confidence decays over time when the fact is not accessed.
type Fact struct {
	Key          string    `json:"key"`
	Value        string    `json:"value"`
	Confidence   float64   `json:"confidence"`   // 0.0 – 1.0
	Source       string    `json:"source"`
	CreatedAt    time.Time `json:"created_at"`
	LastAccessed time.Time `json:"last_accessed"`
	DecayRate    float64   `json:"decay_rate"` // per-hour exponential decay rate
}

// ---------------------------------------------------------------------------
// SemanticStore
// ---------------------------------------------------------------------------

// SemanticStore persists Fact values via an AtomicWriter.
// Confidence decays exponentially based on time since last access.
type SemanticStore struct {
	writer *AtomicWriter
}

const semanticKey = "semantic.json"

// NewSemanticStore creates a SemanticStore backed by writer.
func NewSemanticStore(writer *AtomicWriter) *SemanticStore {
	return &SemanticStore{writer: writer}
}

// Store saves or updates a Fact.  If a Fact with the same Key already exists
// it is overwritten.  CreatedAt is preserved on update; LastAccessed is set to now.
func (s *SemanticStore) Store(fact Fact) error {
	if fact.Key == "" {
		return fmt.Errorf("semantic store: fact key must not be empty")
	}
	now := time.Now()
	if fact.CreatedAt.IsZero() {
		fact.CreatedAt = now
	}
	fact.LastAccessed = now
	if fact.DecayRate <= 0 {
		fact.DecayRate = 0.01 // default: slow decay
	}
	fact.Confidence = clampF(fact.Confidence, 0, 1)

	facts, err := s.load()
	if err != nil {
		return err
	}

	// Preserve CreatedAt if key already exists.
	for i, f := range facts {
		if f.Key == fact.Key {
			fact.CreatedAt = f.CreatedAt
			facts[i] = fact
			return s.save(facts)
		}
	}
	facts = append(facts, fact)
	return s.save(facts)
}

// Retrieve returns the Fact for key after applying confidence decay since
// LastAccessed.  The decayed Fact is persisted back to disk.
func (s *SemanticStore) Retrieve(key string) (*Fact, error) {
	facts, err := s.load()
	if err != nil {
		return nil, err
	}

	now := time.Now()
	for i, f := range facts {
		if f.Key != key {
			continue
		}

		// Apply exponential decay: C' = C * exp(-rate * hours_elapsed)
		hours := now.Sub(f.LastAccessed).Hours()
		if hours > 0 && f.DecayRate > 0 {
			f.Confidence *= math.Exp(-f.DecayRate * hours)
			f.Confidence = clampF(f.Confidence, 0, 1)
		}
		f.LastAccessed = now
		facts[i] = f

		// Persist the updated decay.
		_ = s.save(facts)
		return &f, nil
	}
	return nil, fmt.Errorf("semantic retrieve: key %q not found", key)
}

// Prune removes all Facts whose current (decayed) Confidence is below
// minConfidence.  Returns the number of removed facts.
func (s *SemanticStore) Prune(minConfidence float64) (int, error) {
	facts, err := s.load()
	if err != nil {
		return 0, err
	}

	now := time.Now()
	kept := facts[:0]
	removed := 0
	for _, f := range facts {
		hours := now.Sub(f.LastAccessed).Hours()
		current := f.Confidence * math.Exp(-f.DecayRate*hours)
		if current >= minConfidence {
			kept = append(kept, f)
		} else {
			removed++
		}
	}

	if removed == 0 {
		return 0, nil
	}
	return removed, s.save(kept)
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

func (s *SemanticStore) load() ([]Fact, error) {
	data, err := s.writer.Read(semanticKey)
	if err != nil {
		if isNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("semantic load: %w", err)
	}
	var facts []Fact
	if err := json.Unmarshal(data, &facts); err != nil {
		return nil, fmt.Errorf("semantic unmarshal: %w", err)
	}
	return facts, nil
}

func (s *SemanticStore) save(facts []Fact) error {
	data, err := json.Marshal(facts)
	if err != nil {
		return fmt.Errorf("semantic marshal: %w", err)
	}
	return s.writer.Write(semanticKey, data)
}

func clampF(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
