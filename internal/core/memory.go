// Package core implements the Omega orchestration core.
// memory.go — MemoryKernel, Episode, SemanticMemory, NodeMemory.
//
// Architecture mirrors the Python memory.py design:
//
//	WorkingMemory  ≈ prefrontal cortex / active attention (in-process, ephemeral)
//	EpisodicStore  ≈ hippocampus / autobiographical memory  (Postgres)
//	SemanticStore  ≈ neocortex / general knowledge          (Postgres)
//
// Go owns all Postgres writes; Python BOCPD math is kept in Python and called
// via the ChangePointDetector bridge interface.
package core

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const (
	memDecayRate          = 0.05  // per-cycle episodic importance decay factor
	memSemanticDecayRate  = 0.02  // per-cycle semantic confidence decay (unreinforced)
	memMinImportance      = 0.05  // prune episodes below this
	memMaxEpisodes        = 500   // cap on total episodes in Postgres
	memMaxSemantic        = 200   // cap on semantic memories in Postgres
	memConsolidationEvery = 5     // consolidate every N cycles
	memSemanticReinforceδ = 0.1   // how much new evidence bumps confidence
)

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

// Episode is a timestamped record of something that happened.
type Episode struct {
	EpisodeID string
	Timestamp time.Time
	EventType string // e.g. "signal_generated", "portfolio_built", "feedback"
	Content   map[string]any
	Tags      []string
	Importance float64 // 0.0–1.0; decays over time
	Cycle     int
	Namespace string
}

// SemanticMemory is a learned generalisation extracted from episodes.
type SemanticMemory struct {
	MemoryID      string
	Concept       string  // e.g. "btc_momentum_signal"
	Content       string  // human-readable description of the pattern
	Confidence    float64 // 0.0–1.0; reinforced by new matching episodes
	EvidenceCount int
	LastReinforced time.Time
	Tags          []string
	Namespace     string
}

// ---------------------------------------------------------------------------
// Working memory entry (TTL-aware)
// ---------------------------------------------------------------------------

type workingEntry struct {
	value   any
	setAt   time.Time
	ttl     time.Duration
}

func (e workingEntry) expired() bool {
	return time.Since(e.setAt) > e.ttl
}

// ---------------------------------------------------------------------------
// MemoryKernel
// ---------------------------------------------------------------------------

// MemoryKernel is the central memory system.  It owns all Postgres writes for
// the memory subsystem.  The working-memory map is in-process only.
type MemoryKernel struct {
	mu           sync.Mutex
	db           *sql.DB
	working      map[string]workingEntry
	currentCycle int
}

// NewMemoryKernel wraps the shared Postgres database and returns a
// ready-to-use MemoryKernel. Schema is managed by internal/db/db.go.
func NewMemoryKernel(db *sql.DB) (*MemoryKernel, error) {
	k := &MemoryKernel{
		db:      db,
		working: make(map[string]workingEntry),
	}
	slog.Info("MemoryKernel initialised")
	return k, nil
}

// ---------------------------------------------------------------------------
// Working memory
// ---------------------------------------------------------------------------

// SetWorking stores a value in working memory (current cycle only, not persisted).
func (k *MemoryKernel) SetWorking(key string, value any) {
	k.mu.Lock()
	k.working[key] = workingEntry{value: value, setAt: time.Now(), ttl: 24 * time.Hour}
	k.mu.Unlock()
}

// GetWorking retrieves a value from working memory.
func (k *MemoryKernel) GetWorking(key string) (any, bool) {
	k.mu.Lock()
	defer k.mu.Unlock()
	e, ok := k.working[key]
	if !ok || e.expired() {
		delete(k.working, key)
		return nil, false
	}
	return e.value, true
}

// ClearWorking clears all working memory entries.
func (k *MemoryKernel) ClearWorking() {
	k.mu.Lock()
	k.working = make(map[string]workingEntry)
	k.mu.Unlock()
}

// WorkingSnapshot returns a copy of all (non-expired) working memory entries.
func (k *MemoryKernel) WorkingSnapshot() map[string]any {
	k.mu.Lock()
	defer k.mu.Unlock()
	out := make(map[string]any, len(k.working))
	for k2, e := range k.working {
		if !e.expired() {
			out[k2] = e.value
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// Episodic memory
// ---------------------------------------------------------------------------

// EpisodeFilter specifies search criteria for RetrieveEpisodes.
type EpisodeFilter struct {
	EventType     string
	Tags          []string
	MinImportance float64
	SinceCycle    int  // 0 = no filter
	Namespace     string
	Limit         int
}

// StoreEpisode writes a new episode to SQLite and returns its episode_id.
func (k *MemoryKernel) StoreEpisode(ctx context.Context, ep Episode) (string, error) {
	if ep.EpisodeID == "" {
		ep.EpisodeID = uuid.New().String()
	}
	if ep.Timestamp.IsZero() {
		ep.Timestamp = time.Now()
	}
	if ep.Namespace == "" {
		ep.Namespace = "global"
	}
	ep.Importance = clamp(ep.Importance, 0, 1)

	contentJSON, err := json.Marshal(ep.Content)
	if err != nil {
		return "", fmt.Errorf("marshal content: %w", err)
	}
	tagsJSON, err := json.Marshal(ep.Tags)
	if err != nil {
		return "", fmt.Errorf("marshal tags: %w", err)
	}

	_, err = k.db.ExecContext(ctx, `
		INSERT INTO episodes
		  (episode_id, timestamp, cycle, event_type, content, tags, importance, namespace)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		ep.EpisodeID,
		ep.Timestamp.Unix(),
		ep.Cycle,
		ep.EventType,
		string(contentJSON),
		string(tagsJSON),
		ep.Importance,
		ep.Namespace,
	)
	if err != nil {
		return "", fmt.Errorf("insert episode: %w", err)
	}
	return ep.EpisodeID, nil
}

// RetrieveEpisodes returns episodes matching f, ordered by importance desc.
func (k *MemoryKernel) RetrieveEpisodes(ctx context.Context, f EpisodeFilter) ([]Episode, error) {
	if f.Limit <= 0 {
		f.Limit = 10
	}

	qb := strings.Builder{}
	argN := 1
	args := []any{f.MinImportance}
	fmt.Fprintf(&qb, "SELECT episode_id, timestamp, cycle, event_type, content::text, tags::text, importance, namespace FROM episodes WHERE importance >= $%d", argN)
	argN++

	if f.EventType != "" {
		fmt.Fprintf(&qb, " AND event_type = $%d", argN)
		args = append(args, f.EventType)
		argN++
	}
	if f.SinceCycle > 0 {
		fmt.Fprintf(&qb, " AND cycle >= $%d", argN)
		args = append(args, f.SinceCycle)
		argN++
	}
	if f.Namespace != "" {
		fmt.Fprintf(&qb, " AND namespace = $%d", argN)
		args = append(args, f.Namespace)
		argN++
	}
	// Fetch extra to allow tag post-filtering
	fmt.Fprintf(&qb, " ORDER BY importance DESC, timestamp DESC LIMIT $%d", argN)
	args = append(args, f.Limit*3)

	rows, err := k.db.QueryContext(ctx, qb.String(), args...)
	if err != nil {
		return nil, fmt.Errorf("query episodes: %w", err)
	}
	defer func() { _ = rows.Close() }()

	var out []Episode
	for rows.Next() && len(out) < f.Limit {
		var ep Episode
		var ts float64
		var contentJSON, tagsJSON string
		if err := rows.Scan(&ep.EpisodeID, &ts, &ep.Cycle, &ep.EventType, &contentJSON, &tagsJSON, &ep.Importance, &ep.Namespace); err != nil {
			return nil, fmt.Errorf("scan episode: %w", err)
		}
		ep.Timestamp = time.Unix(int64(ts), 0)

		if err := json.Unmarshal([]byte(contentJSON), &ep.Content); err != nil {
			ep.Content = map[string]any{}
		}
		if err := json.Unmarshal([]byte(tagsJSON), &ep.Tags); err != nil {
			ep.Tags = []string{}
		}

		if len(f.Tags) > 0 && !anyTagMatch(ep.Tags, f.Tags) {
			continue
		}
		out = append(out, ep)
	}
	return out, rows.Err()
}

// EpisodeCount returns the total number of episodes in the store.
func (k *MemoryKernel) EpisodeCount(ctx context.Context) (int, error) {
	var n int
	err := k.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM episodes").Scan(&n)
	return n, err
}

// ---------------------------------------------------------------------------
// Semantic memory
// ---------------------------------------------------------------------------

// SemanticFilter specifies search criteria for RetrieveSemantic.
type SemanticFilter struct {
	Concept       string
	Tags          []string
	QueryText     string
	MinConfidence float64
	Namespace     string
	Limit         int
}

// StoreSemantic stores or reinforces a semantic memory. Returns memory_id.
func (k *MemoryKernel) StoreSemantic(ctx context.Context, sm SemanticMemory) (string, error) {
	if sm.Namespace == "" {
		sm.Namespace = "global"
	}
	tagsJSON, _ := json.Marshal(sm.Tags)
	now := float64(time.Now().UnixMilli()) / 1000

	// Check for existing entry in this namespace
	var existingID string
	var existingConf float64
	var existingCount int
	err := k.db.QueryRowContext(ctx,
		"SELECT memory_id, confidence, evidence_count FROM semantic_memories WHERE concept = $1 AND namespace = $2",
		sm.Concept, sm.Namespace,
	).Scan(&existingID, &existingConf, &existingCount)

	if err == nil {
		// Reinforce
		newConf := clamp(existingConf+sm.Confidence*memSemanticReinforceδ, 0, 1)
		_, err = k.db.ExecContext(ctx, `
			UPDATE semantic_memories
			SET content = $1, confidence = $2, evidence_count = $3, last_reinforced = $4, tags = $5
			WHERE concept = $6 AND namespace = $7`,
			sm.Content, newConf, existingCount+1, now, string(tagsJSON),
			sm.Concept, sm.Namespace,
		)
		return existingID, err
	}

	// Insert new
	if sm.MemoryID == "" {
		sm.MemoryID = uuid.New().String()
	}
	_, err = k.db.ExecContext(ctx, `
		INSERT INTO semantic_memories
		  (memory_id, concept, content, confidence, evidence_count, last_reinforced, tags, namespace)
		VALUES ($1, $2, $3, $4, 1, $5, $6, $7)`,
		sm.MemoryID, sm.Concept, sm.Content, clamp(sm.Confidence, 0, 1), now, string(tagsJSON), sm.Namespace,
	)
	return sm.MemoryID, err
}

// RetrieveSemantic returns semantic memories matching f, ordered by confidence desc.
func (k *MemoryKernel) RetrieveSemantic(ctx context.Context, f SemanticFilter) ([]SemanticMemory, error) {
	if f.Limit <= 0 {
		f.Limit = 5
	}
	if f.MinConfidence == 0 {
		f.MinConfidence = 0.1
	}

	qb := strings.Builder{}
	argN := 1
	args := []any{f.MinConfidence}
	fmt.Fprintf(&qb, "SELECT memory_id, concept, content, confidence, evidence_count, last_reinforced, tags::text, namespace FROM semantic_memories WHERE confidence >= $%d", argN)
	argN++

	if f.Namespace != "" {
		fmt.Fprintf(&qb, " AND namespace = $%d", argN)
		args = append(args, f.Namespace)
		argN++
	}
	fmt.Fprintf(&qb, " ORDER BY confidence DESC LIMIT $%d", argN)
	args = append(args, f.Limit*3)

	rows, err := k.db.QueryContext(ctx, qb.String(), args...)
	if err != nil {
		return nil, fmt.Errorf("query semantic: %w", err)
	}
	defer func() { _ = rows.Close() }()

	var out []SemanticMemory
	for rows.Next() && len(out) < f.Limit {
		var sm SemanticMemory
		var lr float64
		var tagsJSON string
		if err := rows.Scan(&sm.MemoryID, &sm.Concept, &sm.Content, &sm.Confidence, &sm.EvidenceCount, &lr, &tagsJSON, &sm.Namespace); err != nil {
			return nil, fmt.Errorf("scan semantic: %w", err)
		}
		sm.LastReinforced = time.Unix(int64(lr), 0)
		if err := json.Unmarshal([]byte(tagsJSON), &sm.Tags); err != nil {
			sm.Tags = []string{}
		}

		// Post-filters
		if f.Concept != "" && !strings.Contains(strings.ToLower(sm.Concept), strings.ToLower(f.Concept)) {
			continue
		}
		if len(f.Tags) > 0 && !anyTagMatch(sm.Tags, f.Tags) {
			continue
		}
		if f.QueryText != "" {
			q := strings.ToLower(f.QueryText)
			if !strings.Contains(strings.ToLower(sm.Concept), q) &&
				!strings.Contains(strings.ToLower(sm.Content), q) &&
				!anyTagContains(sm.Tags, q) {
				continue
			}
		}
		out = append(out, sm)
	}
	return out, rows.Err()
}

// ReinforceSemantic strengthens confidence for an existing semantic memory.
// Returns false if the concept was not found.
func (k *MemoryKernel) ReinforceSemantic(ctx context.Context, concept string, delta float64) (bool, error) {
	res, err := k.db.ExecContext(ctx, `
		UPDATE semantic_memories
		SET confidence = MIN(1.0, confidence + $1),
		    last_reinforced = $2,
		    evidence_count = evidence_count + 1
		WHERE concept = $3`,
		delta, float64(time.Now().UnixMilli())/1000, concept,
	)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

// ---------------------------------------------------------------------------
// Ratings
// ---------------------------------------------------------------------------

// RateMemory records a quality rating for a memory entry.
func (k *MemoryKernel) RateMemory(ctx context.Context, memoryID string, quality float64, namespace string) error {
	if namespace == "" {
		namespace = "global"
	}
	_, err := k.db.ExecContext(ctx, `
		INSERT INTO memory_ratings (rating_id, memory_id, namespace, quality, rated_at)
		VALUES ($1, $2, $3, $4, $5)`,
		uuid.New().String(), memoryID, namespace, clamp(quality, 0, 1), float64(time.Now().UnixMilli())/1000,
	)
	return err
}

// ---------------------------------------------------------------------------
// Lifecycle — BeginCycle / EndCycle
// ---------------------------------------------------------------------------

// BeginCycle is called at the start of each heartbeat cycle.
// It clears working memory, applies decay, and optionally consolidates.
func (k *MemoryKernel) BeginCycle(ctx context.Context, cycle int) error {
	k.mu.Lock()
	k.currentCycle = cycle
	k.mu.Unlock()

	k.ClearWorking()

	if err := k.decayAndPrune(ctx); err != nil {
		slog.Warn("memory decay/prune error", "err", err)
	}

	if cycle > 0 && cycle%memConsolidationEvery == 0 {
		concepts, err := k.Consolidate(ctx, "")
		if err != nil {
			slog.Warn("memory consolidation error", "err", err)
		} else if len(concepts) > 0 {
			slog.Info("cycle consolidation", "cycle", cycle, "patterns", len(concepts))
		}
	}
	return nil
}

// EndCycle stores a cycle summary episode.
func (k *MemoryKernel) EndCycle(ctx context.Context, cycle int, summary map[string]any) (string, error) {
	return k.StoreEpisode(ctx, Episode{
		EventType:  "cycle_summary",
		Content:    summary,
		Tags:       []string{"cycle_end", fmt.Sprintf("cycle_%d", cycle)},
		Importance: 0.8,
		Cycle:      cycle,
		Namespace:  "global",
	})
}

// ---------------------------------------------------------------------------
// Consolidation
// ---------------------------------------------------------------------------

// Consolidate extracts patterns from recent episodes and stores them as
// semantic memories.  Returns the list of concepts created/updated.
func (k *MemoryKernel) Consolidate(ctx context.Context, namespace string) ([]string, error) {
	k.mu.Lock()
	cycle := k.currentCycle
	k.mu.Unlock()

	filter := EpisodeFilter{
		EventType:     "signal_outcome",
		Limit:         50,
		MinImportance: 0.1,
		SinceCycle:    max(0, cycle-20),
		Namespace:     namespace,
	}
	recent, err := k.RetrieveEpisodes(ctx, filter)
	if err != nil || len(recent) == 0 {
		return nil, err
	}

	type outcomes struct {
		returns []float64
	}
	signalOutcomes := map[string]*outcomes{}
	tickerCount := map[string]int{}

	for _, ep := range recent {
		ticker, _ := ep.Content["ticker"].(string)
		sigType, _ := ep.Content["signal_type"].(string)
		if sigType == "" {
			sigType = "composite"
		}
		outcome, _ := ep.Content["outcome"].(float64)

		if ticker != "" {
			tickerCount[ticker]++
		}
		key := sigType
		if ticker != "" {
			key = ticker + ":" + sigType
		}
		if signalOutcomes[key] == nil {
			signalOutcomes[key] = &outcomes{}
		}
		signalOutcomes[key].returns = append(signalOutcomes[key].returns, outcome)
	}

	storeNS := namespace
	if storeNS == "" {
		storeNS = "global"
	}
	concepts := make([]string, 0, len(signalOutcomes))

	for key, o := range signalOutcomes {
		if len(o.returns) < 3 {
			continue
		}
		hitRate := 0.0
		avgReturn := 0.0
		for _, r := range o.returns {
			avgReturn += r
			if r > 0 {
				hitRate++
			}
		}
		hitRate /= float64(len(o.returns))
		avgReturn /= float64(len(o.returns))

		var concept, contentStr string
		var tags []string
		if strings.Contains(key, ":") {
			parts := strings.SplitN(key, ":", 2)
			ticker, sigType := parts[0], parts[1]
			concept = fmt.Sprintf("%s_%s_pattern", strings.ToLower(ticker), sigType)
			tags = []string{strings.ToLower(ticker), sigType}
		} else {
			concept = key + "_pattern"
			tags = []string{key}
		}

		var conf float64
		switch {
		case hitRate > 0.6:
			contentStr = fmt.Sprintf("%s signal has %.0f%% hit rate over %d samples (avg return %+.3f%%). Momentum persists.",
				key, hitRate*100, len(o.returns), avgReturn*100)
			conf = hitRate
		case hitRate < 0.4:
			contentStr = fmt.Sprintf("%s signal has poor hit rate %.0f%% over %d samples. Consider reducing weight.",
				key, hitRate*100, len(o.returns))
			conf = 0.3
		default:
			continue
		}

		if _, err := k.StoreSemantic(ctx, SemanticMemory{
			Concept:    concept,
			Content:    contentStr,
			Confidence: conf,
			Tags:       tags,
			Namespace:  storeNS,
		}); err != nil {
			slog.Warn("consolidation store semantic error", "concept", concept, "err", err)
			continue
		}
		concepts = append(concepts, concept)
	}

	// Top-appearing tickers
	type kv struct{ k string; v int }
	sorted := make([]kv, 0, len(tickerCount))
	for k, v := range tickerCount {
		sorted = append(sorted, kv{k, v})
	}
	// simple insertion sort (small N)
	for i := 1; i < len(sorted); i++ {
		for j := i; j > 0 && sorted[j].v > sorted[j-1].v; j-- {
			sorted[j], sorted[j-1] = sorted[j-1], sorted[j]
		}
	}
	top := sorted
	if len(top) > 3 {
		top = top[:3]
	}
	for _, kv := range top {
		if kv.v < 3 {
			continue
		}
		concept := strings.ToLower(kv.k) + "_trending"
		contentStr := fmt.Sprintf("%s appeared in %d recent signal episodes — strong interest.", kv.k, kv.v)
		if _, err := k.StoreSemantic(ctx, SemanticMemory{
			Concept:    concept,
			Content:    contentStr,
			Confidence: 0.6,
			Tags:       []string{strings.ToLower(kv.k)},
			Namespace:  storeNS,
		}); err == nil {
			concepts = append(concepts, concept)
		}
	}

	if len(concepts) > 0 {
		slog.Info("memory consolidation", "updated_concepts", len(concepts))
	}
	return concepts, nil
}

// ---------------------------------------------------------------------------
// Decay & Prune
// ---------------------------------------------------------------------------

func (k *MemoryKernel) decayAndPrune(ctx context.Context) error {
	// Decay episodic importance
	if _, err := k.db.ExecContext(ctx, "UPDATE episodes SET importance = importance * $1", 1.0-memDecayRate); err != nil {
		return fmt.Errorf("decay episodes: %w", err)
	}

	// Prune low-importance episodes
	if _, err := k.db.ExecContext(ctx, "DELETE FROM episodes WHERE importance < $1", memMinImportance); err != nil {
		return fmt.Errorf("prune episodes: %w", err)
	}

	// Cap total episodes
	total, _ := k.EpisodeCount(ctx)
	if total > memMaxEpisodes {
		excess := total - memMaxEpisodes
		_, err := k.db.ExecContext(ctx, `
			DELETE FROM episodes WHERE episode_id IN (
				SELECT episode_id FROM episodes ORDER BY importance ASC, timestamp ASC LIMIT $1
			)`, excess)
		if err != nil {
			return fmt.Errorf("cap episodes: %w", err)
		}
	}

	// Decay semantic confidence for unreinforced memories
	k.mu.Lock()
	cycle := k.currentCycle
	k.mu.Unlock()
	ageThreshold := float64(time.Now().Unix()) - float64(cycle*30+60)
	if _, err := k.db.ExecContext(ctx,
		"UPDATE semantic_memories SET confidence = confidence * $1 WHERE last_reinforced < $2",
		1.0-memSemanticDecayRate, ageThreshold,
	); err != nil {
		return fmt.Errorf("decay semantic: %w", err)
	}

	// Prune weak semantic memories (keep at least 10)
	var semCount int
	_ = k.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM semantic_memories").Scan(&semCount)
	if semCount > 10 {
		if _, err := k.db.ExecContext(ctx,
			"DELETE FROM semantic_memories WHERE confidence < $1 AND evidence_count < 3",
			memMinImportance,
		); err != nil {
			return fmt.Errorf("prune semantic: %w", err)
		}
	}

	return nil
}

// ---------------------------------------------------------------------------
// Query interface
// ---------------------------------------------------------------------------

// MemoryQueryResult is the structured result of a Query call.
type MemoryQueryResult struct {
	Question string
	Semantic []SemanticSnippet
	Episodes []EpisodeSnippet
}

// SemanticSnippet is a lightweight view of a semantic memory for query results.
type SemanticSnippet struct {
	Concept    string
	Content    string
	Confidence float64
}

// EpisodeSnippet is a lightweight view of an episode for query results.
type EpisodeSnippet struct {
	EventType  string
	Content    map[string]any
	Importance float64
	Cycle      int
}

// Query performs a keyword search against all memory stores.
func (k *MemoryKernel) Query(ctx context.Context, question string, limit int, namespace string) (MemoryQueryResult, error) {
	words := significantWords(question)

	seen := map[string]bool{}
	var semantics []SemanticSnippet
	for _, w := range words[:min(3, len(words))] {
		results, err := k.RetrieveSemantic(ctx, SemanticFilter{QueryText: w, Limit: 3, Namespace: namespace})
		if err != nil {
			continue
		}
		for _, sm := range results {
			if !seen[sm.MemoryID] {
				seen[sm.MemoryID] = true
				semantics = append(semantics, SemanticSnippet{Concept: sm.Concept, Content: sm.Content, Confidence: sm.Confidence})
			}
		}
	}
	if len(semantics) > limit {
		semantics = semantics[:limit]
	}

	var tagCandidates []string
	for _, w := range words {
		if len(w) > 3 {
			tagCandidates = append(tagCandidates, w)
		}
	}
	eps, err := k.RetrieveEpisodes(ctx, EpisodeFilter{Tags: tagCandidates[:min(3, len(tagCandidates))], Limit: limit, Namespace: namespace})
	if err != nil {
		return MemoryQueryResult{}, err
	}

	snippets := make([]EpisodeSnippet, 0, len(eps))
	for _, ep := range eps {
		snippets = append(snippets, EpisodeSnippet{EventType: ep.EventType, Content: ep.Content, Importance: ep.Importance, Cycle: ep.Cycle})
	}

	return MemoryQueryResult{Question: question, Semantic: semantics, Episodes: snippets}, nil
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

// MemorySummary is a status snapshot of the memory kernel.
type MemorySummary struct {
	CurrentCycle      int
	WorkingMemoryKeys []string
	EpisodicCount     int
	SemanticCount     int
	TopSemanticConcepts []SemanticSnippet
}

// Summary returns a status snapshot of the memory kernel.
func (k *MemoryKernel) Summary(ctx context.Context) MemorySummary {
	epCount, _ := k.EpisodeCount(ctx)

	var semCount int
	_ = k.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM semantic_memories").Scan(&semCount)

	ws := k.WorkingSnapshot()
	wkeys := make([]string, 0, len(ws))
	for k2 := range ws {
		wkeys = append(wkeys, k2)
	}

	rows, _ := k.db.QueryContext(ctx, "SELECT concept, confidence FROM semantic_memories ORDER BY confidence DESC LIMIT 5")
	var top []SemanticSnippet
	if rows != nil {
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var s SemanticSnippet
			_ = rows.Scan(&s.Concept, &s.Confidence)
			top = append(top, s)
		}
	}

	k.mu.Lock()
	cycle := k.currentCycle
	k.mu.Unlock()

	return MemorySummary{
		CurrentCycle:        cycle,
		WorkingMemoryKeys:   wkeys,
		EpisodicCount:       epCount,
		SemanticCount:       semCount,
		TopSemanticConcepts: top,
	}
}

// ---------------------------------------------------------------------------
// NodeMemory — per-node namespaced facade
// ---------------------------------------------------------------------------

// NodeMemory is a per-node memory facade with namespace isolation.
// Each node gets its own NodeMemory; reads/writes never bleed into other nodes.
type NodeMemory struct {
	kernel    *MemoryKernel
	namespace string
	mu        sync.Mutex
	working   map[string]workingEntry
}

// GetNodeMemory returns a NodeMemory scoped to nodeName.
func (k *MemoryKernel) GetNodeMemory(nodeName string) *NodeMemory {
	return &NodeMemory{
		kernel:    k,
		namespace: nodeName,
		working:   make(map[string]workingEntry),
	}
}

// Namespace returns the node's namespace identifier.
func (n *NodeMemory) Namespace() string { return n.namespace }

// Remember stores a value in per-node working memory with a TTL.
func (n *NodeMemory) Remember(key string, value any, ttl time.Duration) {
	n.mu.Lock()
	n.working[key] = workingEntry{value: value, setAt: time.Now(), ttl: ttl}
	n.mu.Unlock()
}

// Recall retrieves from per-node working memory, returning (value, ok).
func (n *NodeMemory) Recall(key string) (any, bool) {
	n.mu.Lock()
	defer n.mu.Unlock()
	e, ok := n.working[key]
	if !ok || e.expired() {
		delete(n.working, key)
		return nil, false
	}
	return e.value, true
}

// ForgetWorking removes a specific working memory entry.
func (n *NodeMemory) ForgetWorking(key string) {
	n.mu.Lock()
	delete(n.working, key)
	n.mu.Unlock()
}

// FlushExpired evicts all expired working memory entries and returns the count.
func (n *NodeMemory) FlushExpired() int {
	n.mu.Lock()
	defer n.mu.Unlock()
	var expired []string
	for k, e := range n.working {
		if e.expired() {
			expired = append(expired, k)
		}
	}
	for _, k := range expired {
		delete(n.working, k)
	}
	return len(expired)
}

// WorkingKeys returns active (non-expired) keys.
func (n *NodeMemory) WorkingKeys() []string {
	n.FlushExpired()
	n.mu.Lock()
	defer n.mu.Unlock()
	keys := make([]string, 0, len(n.working))
	for k := range n.working {
		keys = append(keys, k)
	}
	return keys
}

// StoreEpisode stores a namespaced episode.
func (n *NodeMemory) StoreEpisode(ctx context.Context, eventType string, content map[string]any, tags []string, importance float64, cycle int) (string, error) {
	return n.kernel.StoreEpisode(ctx, Episode{
		EventType:  eventType,
		Content:    content,
		Tags:       tags,
		Importance: importance,
		Cycle:      cycle,
		Namespace:  n.namespace,
	})
}

// RetrieveEpisodes returns namespaced episodes matching the filter.
func (n *NodeMemory) RetrieveEpisodes(ctx context.Context, f EpisodeFilter) ([]Episode, error) {
	f.Namespace = n.namespace
	return n.kernel.RetrieveEpisodes(ctx, f)
}

// StoreSemantic stores or reinforces a namespaced semantic memory.
func (n *NodeMemory) StoreSemantic(ctx context.Context, concept, content string, confidence float64, tags []string) (string, error) {
	return n.kernel.StoreSemantic(ctx, SemanticMemory{
		Concept:    concept,
		Content:    content,
		Confidence: confidence,
		Tags:       tags,
		Namespace:  n.namespace,
	})
}

// RetrieveSemantic returns namespaced semantic memories matching the filter.
func (n *NodeMemory) RetrieveSemantic(ctx context.Context, f SemanticFilter) ([]SemanticMemory, error) {
	f.Namespace = n.namespace
	return n.kernel.RetrieveSemantic(ctx, f)
}

// Rate records a quality rating for a memory entry.
func (n *NodeMemory) Rate(ctx context.Context, memoryID string, quality float64) error {
	return n.kernel.RateMemory(ctx, memoryID, quality, n.namespace)
}

// Search performs a keyword search across episodic + semantic tiers.
func (n *NodeMemory) Search(ctx context.Context, query string, limit int) (MemoryQueryResult, error) {
	return n.kernel.Query(ctx, query, limit, n.namespace)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func anyTagMatch(haystack, needles []string) bool {
	for _, n := range needles {
		for _, h := range haystack {
			if h == n {
				return true
			}
		}
	}
	return false
}

func anyTagContains(tags []string, q string) bool {
	for _, t := range tags {
		if strings.Contains(strings.ToLower(t), q) {
			return true
		}
	}
	return false
}

func significantWords(s string) []string {
	var words []string
	for _, w := range strings.Fields(strings.ToLower(s)) {
		if len(w) > 2 {
			words = append(words, w)
		}
	}
	return words
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
