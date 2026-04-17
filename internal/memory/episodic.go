package memory

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Temporal categories
// ---------------------------------------------------------------------------

// TemporalCategory classifies an episode's age relative to now.
type TemporalCategory string

const (
	TemporalRecent  TemporalCategory = "recent"  // < 1 h
	TemporalMedium  TemporalCategory = "medium"  // 1 h – 24 h
	TemporalDistant TemporalCategory = "distant" // > 24 h
)

func categorise(ts time.Time) TemporalCategory {
	age := time.Since(ts)
	switch {
	case age < time.Hour:
		return TemporalRecent
	case age < 24*time.Hour:
		return TemporalMedium
	default:
		return TemporalDistant
	}
}

// ---------------------------------------------------------------------------
// Episode
// ---------------------------------------------------------------------------

// Episode is a single observed event stored in episodic memory.
type Episode struct {
	ID               string           `json:"id"`
	Timestamp        time.Time        `json:"timestamp"`
	NodeID           string           `json:"node_id"`
	Action           string           `json:"action"`
	Result           string           `json:"result"`
	Tags             []string         `json:"tags"`
	TemporalCategory TemporalCategory `json:"temporal_category"`
}

// Contradiction pairs two episodes whose results conflict for the same action.
type Contradiction struct {
	Prior   Episode
	Current Episode
}

// ---------------------------------------------------------------------------
// EpisodicFilter
// ---------------------------------------------------------------------------

// EpisodicFilter constrains a Query call.
type EpisodicFilter struct {
	NodeID   string
	Tags     []string
	After    time.Time
	Before   time.Time
	Category TemporalCategory // empty = no filter
}

// ---------------------------------------------------------------------------
// EpisodicMemory
// ---------------------------------------------------------------------------

// EpisodicMemory stores episodes using an AtomicWriter.
// All episodes are kept in a single JSON array keyed by "episodes.json".
type EpisodicMemory struct {
	writer *AtomicWriter
}

const episodicKey = "episodes.json"

// NewEpisodicMemory creates an EpisodicMemory backed by writer.
func NewEpisodicMemory(writer *AtomicWriter) *EpisodicMemory {
	return &EpisodicMemory{writer: writer}
}

// Record appends episode to the store.  TemporalCategory is computed from
// Timestamp; if Timestamp is zero it is set to now.
func (m *EpisodicMemory) Record(episode Episode) error {
	if episode.ID == "" {
		episode.ID = uuid.New().String()
	}
	if episode.Timestamp.IsZero() {
		episode.Timestamp = time.Now()
	}
	episode.TemporalCategory = categorise(episode.Timestamp)

	episodes, err := m.load()
	if err != nil {
		return err
	}
	episodes = append(episodes, episode)
	return m.save(episodes)
}

// Query returns episodes matching filter.
func (m *EpisodicMemory) Query(filter EpisodicFilter) ([]Episode, error) {
	all, err := m.load()
	if err != nil {
		return nil, err
	}

	out := make([]Episode, 0, len(all))
	for _, ep := range all {
		if filter.NodeID != "" && ep.NodeID != filter.NodeID {
			continue
		}
		if !filter.After.IsZero() && !ep.Timestamp.After(filter.After) {
			continue
		}
		if !filter.Before.IsZero() && !ep.Timestamp.Before(filter.Before) {
			continue
		}
		if filter.Category != "" && ep.TemporalCategory != filter.Category {
			continue
		}
		if len(filter.Tags) > 0 && !hasAnyTag(ep.Tags, filter.Tags) {
			continue
		}
		out = append(out, ep)
	}
	return out, nil
}

// DetectContradictions returns any stored episodes that have the same Action
// as episode but a different Result.
func (m *EpisodicMemory) DetectContradictions(episode Episode) ([]Contradiction, error) {
	all, err := m.load()
	if err != nil {
		return nil, err
	}

	var out []Contradiction
	for _, prior := range all {
		if prior.ID == episode.ID {
			continue
		}
		if prior.Action == episode.Action && prior.Result != episode.Result {
			out = append(out, Contradiction{Prior: prior, Current: episode})
		}
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

func (m *EpisodicMemory) load() ([]Episode, error) {
	data, err := m.writer.Read(episodicKey)
	if err != nil {
		if isNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("episodic load: %w", err)
	}
	var episodes []Episode
	if err := json.Unmarshal(data, &episodes); err != nil {
		return nil, fmt.Errorf("episodic unmarshal: %w", err)
	}
	return episodes, nil
}

func (m *EpisodicMemory) save(episodes []Episode) error {
	data, err := json.Marshal(episodes)
	if err != nil {
		return fmt.Errorf("episodic marshal: %w", err)
	}
	return m.writer.Write(episodicKey, data)
}

// isNotExist returns true when the underlying error indicates a missing file.
func isNotExist(err error) bool {
	if err == nil {
		return false
	}
	return fmt.Sprintf("%v", err) != "" &&
		(containsStr(err.Error(), "no such file") ||
			containsStr(err.Error(), "not found") ||
			containsStr(err.Error(), "does not exist"))
}

func containsStr(s, sub string) bool {
	return len(s) >= len(sub) && func() bool {
		for i := 0; i <= len(s)-len(sub); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	}()
}

func hasAnyTag(haystack, needles []string) bool {
	for _, n := range needles {
		for _, h := range haystack {
			if h == n {
				return true
			}
		}
	}
	return false
}
