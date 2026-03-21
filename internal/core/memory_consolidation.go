package core

// memory_consolidation.go — ConsolidationPipeline, MemoryIndex, DecayManager,
// ImportanceScorer.
//
// Go owns scheduling and lifecycle.  The actual BOCPD changepoint math stays in
// Python and is called via the ChangePointDetector bridge interface.

import (
	"log/slog"
	"math"
	"sync"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Bridge interface — Python implements BOCPD on the other side
// ---------------------------------------------------------------------------

// ChangePointDetector is called by the consolidation pipeline to detect regime
// shifts in a stream of importance values.  Python implements this via
// Connect-RPC; in tests a stub can be injected.
type ChangePointDetector interface {
	// DetectChangePoints returns the indices in values where changepoints were
	// detected.  Returns nil if none detected or if the detector is unavailable.
	DetectChangePoints(values []float64) ([]int, error)
}

// ---------------------------------------------------------------------------
// MemoryRecord
// ---------------------------------------------------------------------------

// MemoryRecord is a single memory entry that may live in short-term or
// long-term storage.
type MemoryRecord struct {
	MemoryID     string
	CreatedAt    time.Time
	LastAccessed time.Time
	Importance   float64 // 0.0–1.0
	RegimeTag    string
	SignalType   string
	Content      map[string]any
	Tags         []string
	IsLandmark   bool  // if true, protected from decay below LandmarkFloor
	AccessCount  int
	Consolidated bool // true once promoted to long-term store
}

// NewMemoryRecord constructs a MemoryRecord with sensible defaults.
func NewMemoryRecord(regimeTag, signalType string, content map[string]any, tags []string, importance float64, isLandmark bool) MemoryRecord {
	now := time.Now()
	return MemoryRecord{
		MemoryID:     uuid.New().String(),
		CreatedAt:    now,
		LastAccessed: now,
		Importance:   clamp(importance, 0, 1),
		RegimeTag:    regimeTag,
		SignalType:   signalType,
		Content:      content,
		Tags:         tags,
		IsLandmark:   isLandmark,
	}
}

// ---------------------------------------------------------------------------
// MemoryIndex — fast in-memory lookup
// ---------------------------------------------------------------------------

const bucketSeconds = 86_400 // one day

// MemoryIndex is an in-memory inverted index for fast lookup by regime tag,
// signal type, or time range.
type MemoryIndex struct {
	mu       sync.RWMutex
	byRegime map[string]map[string]struct{}
	bySignal map[string]map[string]struct{}
	byTime   map[int64]map[string]struct{} // day bucket → IDs
}

// NewMemoryIndex initialises an empty MemoryIndex.
func NewMemoryIndex() *MemoryIndex {
	return &MemoryIndex{
		byRegime: make(map[string]map[string]struct{}),
		bySignal: make(map[string]map[string]struct{}),
		byTime:   make(map[int64]map[string]struct{}),
	}
}

func (idx *MemoryIndex) Add(r MemoryRecord) {
	idx.mu.Lock()
	defer idx.mu.Unlock()
	addToSet(idx.byRegime, r.RegimeTag, r.MemoryID)
	addToSet(idx.bySignal, r.SignalType, r.MemoryID)
	bucket := r.CreatedAt.Unix() / bucketSeconds
	addToSet64(idx.byTime, bucket, r.MemoryID)
}

func (idx *MemoryIndex) Remove(r MemoryRecord) {
	idx.mu.Lock()
	defer idx.mu.Unlock()
	removeFromSet(idx.byRegime, r.RegimeTag, r.MemoryID)
	removeFromSet(idx.bySignal, r.SignalType, r.MemoryID)
	bucket := r.CreatedAt.Unix() / bucketSeconds
	removeFromSet64(idx.byTime, bucket, r.MemoryID)
}

// ByRegime returns a copy of IDs for the given regime tag.
func (idx *MemoryIndex) ByRegime(tag string) map[string]struct{} {
	idx.mu.RLock()
	defer idx.mu.RUnlock()
	return copySet(idx.byRegime[tag])
}

// BySignal returns a copy of IDs for the given signal type.
func (idx *MemoryIndex) BySignal(sigType string) map[string]struct{} {
	idx.mu.RLock()
	defer idx.mu.RUnlock()
	return copySet(idx.bySignal[sigType])
}

// ByTimeRange returns IDs for records created between start and end.
func (idx *MemoryIndex) ByTimeRange(start, end time.Time) map[string]struct{} {
	idx.mu.RLock()
	defer idx.mu.RUnlock()
	startBucket := start.Unix() / bucketSeconds
	endBucket := end.Unix() / bucketSeconds
	out := map[string]struct{}{}
	for b := startBucket; b <= endBucket; b++ {
		for id := range idx.byTime[b] {
			out[id] = struct{}{}
		}
	}
	return out
}

// Intersect returns the intersection of multiple ID sets.
func Intersect(sets ...map[string]struct{}) map[string]struct{} {
	if len(sets) == 0 {
		return nil
	}
	result := copySet(sets[0])
	for _, s := range sets[1:] {
		for id := range result {
			if _, ok := s[id]; !ok {
				delete(result, id)
			}
		}
	}
	return result
}

// IndexStats returns basic stats about the index.
func (idx *MemoryIndex) IndexStats() map[string]any {
	idx.mu.RLock()
	defer idx.mu.RUnlock()
	regimes := make(map[string]int, len(idx.byRegime))
	for k, v := range idx.byRegime {
		regimes[k] = len(v)
	}
	signals := make(map[string]int, len(idx.bySignal))
	for k, v := range idx.bySignal {
		signals[k] = len(v)
	}
	return map[string]any{
		"regimes":      regimes,
		"signal_types": signals,
		"time_buckets": len(idx.byTime),
	}
}

// ---------------------------------------------------------------------------
// DecayManager
// ---------------------------------------------------------------------------

// DecayManager applies exponential importance decay to MemoryRecords.
//
//	I(t) = max(floor, I₀ × exp(−λ × Δt))
//
// where λ = ln(2) / halfLife.
type DecayManager struct {
	decayLambda   float64
	floor         float64
	landmarkFloor float64
}

// NewDecayManager creates a DecayManager with the given configuration.
func NewDecayManager(halfLife time.Duration, floor, landmarkFloor float64) (*DecayManager, error) {
	if halfLife <= 0 {
		return nil, &ValidationError{Field: "halfLife", Message: "must be positive"}
	}
	return &DecayManager{
		decayLambda:   math.Log(2) / halfLife.Seconds(),
		floor:         floor,
		landmarkFloor: landmarkFloor,
	}, nil
}

// Decay mutates r.Importance in place.
func (dm *DecayManager) Decay(r *MemoryRecord, now time.Time) {
	elapsed := math.Max(0, now.Sub(r.CreatedAt).Seconds())
	decayed := r.Importance * math.Exp(-dm.decayLambda*elapsed)
	floor := dm.floor
	if r.IsLandmark {
		floor = dm.landmarkFloor
	}
	r.Importance = math.Max(floor, decayed)
}

// DecayAll applies Decay to every record in the slice.
func (dm *DecayManager) DecayAll(records []*MemoryRecord, now time.Time) {
	for _, r := range records {
		dm.Decay(r, now)
	}
}

// ShouldPrune returns true if the record is below threshold and not a landmark.
func (dm *DecayManager) ShouldPrune(r *MemoryRecord, threshold float64) bool {
	if r.IsLandmark {
		return false
	}
	return r.Importance < threshold
}

// ---------------------------------------------------------------------------
// ImportanceScorer
// ---------------------------------------------------------------------------

// ImportanceScorer ranks MemoryRecords by relevance to the current regime.
//
// score = wImportance×importance + wRecency×recency + wRegime×regimeMatch + wAccess×access
type ImportanceScorer struct {
	wImportance float64
	wRecency    float64
	wRegime     float64
	wAccess     float64
	recencyLambda float64
}

const recencyHalfLife = 30 * 24 * time.Hour

// NewImportanceScorer creates a scorer with the given weights (must sum to 1.0).
func NewImportanceScorer(wImportance, wRecency, wRegime, wAccess float64) (*ImportanceScorer, error) {
	total := wImportance + wRecency + wRegime + wAccess
	if math.Abs(total-1.0) > 1e-6 {
		return nil, &ValidationError{Field: "weights", Message: "must sum to 1.0"}
	}
	return &ImportanceScorer{
		wImportance:   wImportance,
		wRecency:      wRecency,
		wRegime:       wRegime,
		wAccess:       wAccess,
		recencyLambda: math.Log(2) / recencyHalfLife.Seconds(),
	}, nil
}

// DefaultImportanceScorer returns a scorer with canonical weights.
func DefaultImportanceScorer() *ImportanceScorer {
	s, _ := NewImportanceScorer(0.4, 0.3, 0.2, 0.1)
	return s
}

// Score computes the relevance score of a single record.
func (s *ImportanceScorer) Score(r *MemoryRecord, currentRegime string, now time.Time) float64 {
	age := math.Max(0, now.Sub(r.CreatedAt).Seconds())
	recency := math.Exp(-s.recencyLambda * age)
	regimeMatch := 0.0
	if r.RegimeTag == currentRegime {
		regimeMatch = 1.0
	}
	access := math.Tanh(float64(r.AccessCount) / 10.0)
	return s.wImportance*r.Importance + s.wRecency*recency + s.wRegime*regimeMatch + s.wAccess*access
}

// ScoredRecord pairs a score with a MemoryRecord pointer.
type ScoredRecord struct {
	Score  float64
	Record *MemoryRecord
}

// Rank returns records sorted descending by score, optionally capped at topK.
func (s *ImportanceScorer) Rank(records []*MemoryRecord, currentRegime string, now time.Time, topK int) []ScoredRecord {
	out := make([]ScoredRecord, 0, len(records))
	for _, r := range records {
		out = append(out, ScoredRecord{Score: s.Score(r, currentRegime, now), Record: r})
	}
	// sort descending by score (insertion sort; N is typically small)
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j].Score > out[j-1].Score; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	if topK > 0 && topK < len(out) {
		out = out[:topK]
	}
	return out
}

// ---------------------------------------------------------------------------
// ConsolidationPipeline
// ---------------------------------------------------------------------------

// ConsolidationResult summarises a single consolidation run.
type ConsolidationResult struct {
	RunID            string
	Timestamp        time.Time
	ShortTermBefore  int
	ShortTermAfter   int
	LongTermBefore   int
	LongTermAfter    int
	Pruned           int
	Consolidated     int
}

// ConsolidationConfig holds configuration for the pipeline.
type ConsolidationConfig struct {
	MinAge             time.Duration // memory must be this old before promotion
	PromotionThreshold float64       // minimum importance to promote
	PruneThreshold     float64       // prune short-term below this
	Interval           time.Duration // minimum time between consolidation runs
	DecayHalfLife      time.Duration
	LandmarkFloor      float64
}

// DefaultConsolidationConfig returns sensible defaults.
func DefaultConsolidationConfig() ConsolidationConfig {
	return ConsolidationConfig{
		MinAge:             time.Hour,
		PromotionThreshold: 0.3,
		PruneThreshold:     0.05,
		Interval:           15 * time.Minute,
		DecayHalfLife:      7 * 24 * time.Hour,
		LandmarkFloor:      0.3,
	}
}

// ConsolidationPipeline periodically merges short-term memories into
// long-term storage.  Go owns all scheduling and lifecycle; Python BOCPD
// math is called via the ChangePointDetector interface.
type ConsolidationPipeline struct {
	cfg     ConsolidationConfig
	decay   *DecayManager
	scorer  *ImportanceScorer
	index   *MemoryIndex
	cpd     ChangePointDetector // may be nil — disables changepoint enrichment

	mu               sync.Mutex
	shortTerm        map[string]*MemoryRecord
	longTerm         map[string]*MemoryRecord
	lastConsolidation time.Time
	history          []ConsolidationResult
}

// NewConsolidationPipeline creates a pipeline with the given config.
// cpd may be nil; if nil, changepoint detection is skipped.
func NewConsolidationPipeline(cfg ConsolidationConfig, cpd ChangePointDetector) (*ConsolidationPipeline, error) {
	dm, err := NewDecayManager(cfg.DecayHalfLife, 0, cfg.LandmarkFloor)
	if err != nil {
		return nil, err
	}
	return &ConsolidationPipeline{
		cfg:               cfg,
		decay:             dm,
		scorer:            DefaultImportanceScorer(),
		index:             NewMemoryIndex(),
		cpd:               cpd,
		shortTerm:         make(map[string]*MemoryRecord),
		longTerm:          make(map[string]*MemoryRecord),
		lastConsolidation: time.Now(),
	}, nil
}

// Add ingests a new memory into short-term storage.
func (p *ConsolidationPipeline) Add(r MemoryRecord) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.shortTerm[r.MemoryID] = &r
	p.index.Add(r)
	slog.Debug("memory added", "id", r.MemoryID[:8], "regime", r.RegimeTag, "signal", r.SignalType, "importance", r.Importance)
}

// Get retrieves a record from either store; updates access tracking.
func (p *ConsolidationPipeline) Get(id string) (*MemoryRecord, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	r := p.shortTerm[id]
	if r == nil {
		r = p.longTerm[id]
	}
	if r != nil {
		r.LastAccessed = time.Now()
		r.AccessCount++
	}
	return r, r != nil
}

// Query returns top-k records matching the given criteria, ranked by score.
func (p *ConsolidationPipeline) Query(regimeTag, signalType string, start, end *time.Time, currentRegime string, topK int) []ScoredRecord {
	p.mu.Lock()
	defer p.mu.Unlock()

	var candidateIDs map[string]struct{}

	intersect := func(ids map[string]struct{}) {
		if candidateIDs == nil {
			candidateIDs = ids
		} else {
			candidateIDs = Intersect(candidateIDs, ids)
		}
	}

	if regimeTag != "" {
		intersect(p.index.ByRegime(regimeTag))
	}
	if signalType != "" {
		intersect(p.index.BySignal(signalType))
	}
	if start != nil && end != nil {
		intersect(p.index.ByTimeRange(*start, *end))
	}

	now := time.Now()
	var records []*MemoryRecord
	if candidateIDs == nil {
		for _, r := range p.shortTerm {
			records = append(records, r)
		}
		for _, r := range p.longTerm {
			records = append(records, r)
		}
	} else {
		for id := range candidateIDs {
			if r, ok := p.shortTerm[id]; ok {
				records = append(records, r)
			} else if r, ok := p.longTerm[id]; ok {
				records = append(records, r)
			}
		}
	}

	return p.scorer.Rank(records, currentRegime, now, topK)
}

// MaybeConsolidate runs consolidation if the interval has elapsed.
func (p *ConsolidationPipeline) MaybeConsolidate() (*ConsolidationResult, error) {
	p.mu.Lock()
	elapsed := time.Since(p.lastConsolidation)
	p.mu.Unlock()
	if elapsed < p.cfg.Interval {
		return nil, nil
	}
	result, err := p.Consolidate()
	return &result, err
}

// Consolidate runs a full consolidation cycle immediately.
func (p *ConsolidationPipeline) Consolidate() (ConsolidationResult, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	now := time.Now()
	stBefore := len(p.shortTerm)
	ltBefore := len(p.longTerm)

	// 1. Apply decay to all memories
	allST := make([]*MemoryRecord, 0, len(p.shortTerm))
	for _, r := range p.shortTerm {
		allST = append(allST, r)
	}
	allLT := make([]*MemoryRecord, 0, len(p.longTerm))
	for _, r := range p.longTerm {
		allLT = append(allLT, r)
	}
	p.decay.DecayAll(allST, now)
	p.decay.DecayAll(allLT, now)

	// 2. Promote eligible short-term memories to long-term
	var toPromote []string
	for id, r := range p.shortTerm {
		age := now.Sub(r.CreatedAt)
		if age >= p.cfg.MinAge && r.Importance >= p.cfg.PromotionThreshold {
			toPromote = append(toPromote, id)
		}
	}
	consolidated := 0
	for _, id := range toPromote {
		r := p.shortTerm[id]
		delete(p.shortTerm, id)
		r.Consolidated = true
		p.longTerm[id] = r
		consolidated++
	}

	// 3. Prune low-importance short-term memories
	var toPrune []string
	for id, r := range p.shortTerm {
		if p.decay.ShouldPrune(r, p.cfg.PruneThreshold) {
			toPrune = append(toPrune, id)
		}
	}
	for _, id := range toPrune {
		r := p.shortTerm[id]
		delete(p.shortTerm, id)
		p.index.Remove(*r)
	}
	pruned := len(toPrune)

	p.lastConsolidation = now
	result := ConsolidationResult{
		RunID:           uuid.New().String(),
		Timestamp:       now,
		ShortTermBefore: stBefore,
		ShortTermAfter:  len(p.shortTerm),
		LongTermBefore:  ltBefore,
		LongTermAfter:   len(p.longTerm),
		Pruned:          pruned,
		Consolidated:    consolidated,
	}
	p.history = append(p.history, result)

	slog.Info("consolidation run",
		"run_id", result.RunID[:8],
		"promoted", consolidated,
		"pruned", pruned,
		"short_term", result.ShortTermAfter,
		"long_term", result.LongTermAfter,
	)
	return result, nil
}

// ShortTermSize returns the current short-term store size.
func (p *ConsolidationPipeline) ShortTermSize() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.shortTerm)
}

// LongTermSize returns the current long-term store size.
func (p *ConsolidationPipeline) LongTermSize() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.longTerm)
}

// LastConsolidationResult returns the most recent result, or nil.
func (p *ConsolidationPipeline) LastConsolidationResult() *ConsolidationResult {
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.history) == 0 {
		return nil
	}
	r := p.history[len(p.history)-1]
	return &r
}

// Stats returns a summary of the pipeline state.
func (p *ConsolidationPipeline) Stats() map[string]any {
	return map[string]any{
		"short_term":          p.ShortTermSize(),
		"long_term":           p.LongTermSize(),
		"consolidation_runs":  len(p.history),
		"index":               p.index.IndexStats(),
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func addToSet(m map[string]map[string]struct{}, key, id string) {
	if m[key] == nil {
		m[key] = make(map[string]struct{})
	}
	m[key][id] = struct{}{}
}

func addToSet64(m map[int64]map[string]struct{}, key int64, id string) {
	if m[key] == nil {
		m[key] = make(map[string]struct{})
	}
	m[key][id] = struct{}{}
}

func removeFromSet(m map[string]map[string]struct{}, key, id string) {
	if s, ok := m[key]; ok {
		delete(s, id)
	}
}

func removeFromSet64(m map[int64]map[string]struct{}, key int64, id string) {
	if s, ok := m[key]; ok {
		delete(s, id)
	}
}

func copySet(s map[string]struct{}) map[string]struct{} {
	out := make(map[string]struct{}, len(s))
	for k := range s {
		out[k] = struct{}{}
	}
	return out
}
