// Package handler — Training progress handler for the web dashboard.
// Serves /api/v1/training/* endpoints consumed by the TrainingPage.
package handler

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/benebsworth/omega/internal/db"
)

// TrainingHandler serves training-progress REST endpoints.
type TrainingHandler struct {
	db          *db.DB
	progressDir string // directory containing training_progress.json
	logDir      string // directory containing the victoria training_log markdown
}

// NewTrainingHandler creates a TrainingHandler.
// progressDir is the directory to search for training_progress.json (defaults to "data").
func NewTrainingHandler(database *db.DB, progressDir string) *TrainingHandler {
	if progressDir == "" {
		progressDir = "data"
	}
	return &TrainingHandler{
		db:          database,
		progressDir: progressDir,
		// Training-log markdown lives beside the data dir in the repo tree:
		// <repo>/data + <repo>/omega/nodes/victoria/training_log.
		logDir: filepath.Join(filepath.Dir(progressDir), "omega", "nodes", "victoria", "training_log"),
	}
}

// SetTrainingLogDir overrides the directory searched for training-log markdown
// (omega/nodes/victoria/training_log by default). Used by tests and by
// deployments where the repo tree is laid out differently.
func (h *TrainingHandler) SetTrainingLogDir(dir string) {
	if dir != "" {
		h.logDir = dir
	}
}

// RegisterRoutes mounts training endpoints on mux.
func (h *TrainingHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/v1/training/progress", h.handleProgress)
	mux.HandleFunc("/api/v1/training/metrics", h.handleMetrics)
	mux.HandleFunc("/api/v1/training/events/stream", h.handleStream)
	mux.HandleFunc("/api/v1/training/snapshot", h.handleSnapshot)
	mux.HandleFunc("/api/v1/training/snapshots", h.handleListSnapshots)
	mux.HandleFunc("/api/v1/training/jsonl", h.handleJSONL)
	mux.HandleFunc("/api/v1/training/stream", h.handleVersionStream)
	mux.HandleFunc("/api/v1/training/versions", h.handleVersions)
	mux.HandleFunc("/api/v1/training/compare", h.handleCompare)
	mux.HandleFunc("/api/v1/training/trade-details", h.handleTradeDetails)
	mux.HandleFunc("/api/v1/training/decision-traces", h.handleDecisionTraces)
	mux.HandleFunc("/api/v1/training/gates", h.handleGates)
	mux.HandleFunc("/api/v1/training/grid-ruler", h.handleGridRuler)
	mux.HandleFunc("/api/v1/training/forensics", h.handleForensics)
	mux.HandleFunc("/api/v1/training/log", h.handleTrainingLog)
	mux.HandleFunc("/api/v1/signals/correlation", h.handleSignalCorrelation)
}

// ── JSON types ────────────────────────────────────────────────────────────────

type trainingProgress struct {
	RunID            string                     `json:"run_id"`
	TotalCycles      int                        `json:"total_cycles"`
	CurrentCycle     int                        `json:"current_cycle"`
	StartedAt        string                     `json:"started_at"`
	Status           string                     `json:"status"`
	PnLHistory       []trainingCyclePnL         `json:"pnl_history"`
	WinRateHistory   []trainingCycleWinRate     `json:"win_rate_history"`
	MemoryGrowth     []trainingMemoryPoint      `json:"memory_growth"`
	SignalConviction []trainingSignalConviction `json:"signal_conviction"`
	ActivityLog      []trainingActivity         `json:"activity_log"`
	CurrentRegime    trainingRegime             `json:"current_regime"`
	Config           trainingConfig             `json:"config"`
	Snapshots        []trainingSnapshot         `json:"snapshots"`

	// Cycles carries the raw per-checkpoint rows exactly as scripts/run_training.py
	// wrote them. Populated only when the on-disk file is the array shape.
	Cycles []trainingCheckpoint `json:"cycles,omitempty"`
}

// trainingCheckpoint is one element of the ARRAY that
// scripts/run_training.py writes to data/{version}_progress.json (and
// data/training_progress.json) — see the "Periodic progress log" block in
// scripts/run_training.py (`progress.append(checkpoint); json.dump(progress, f)`).
// Fields absent from older runs simply decode as zero values.
type trainingCheckpoint struct {
	Cycle              int      `json:"cycle"`
	Timestamp          string   `json:"timestamp"`
	TradesOpen         int      `json:"trades_open"`
	TradesClosed       int      `json:"trades_closed"`
	TotalPnL           float64  `json:"total_pnl"`
	WinRate            float64  `json:"win_rate"`
	Regime             string   `json:"regime"`
	ImproveCalls       int      `json:"improve_calls,omitempty"`
	SemanticPatternsDB int      `json:"semantic_patterns_db,omitempty"`
	DataFreshnessMin   float64  `json:"data_freshness_min"`
	SitOutReason       string   `json:"sit_out_reason"`
	AvgCycleTimeS      float64  `json:"avg_cycle_time_s"`
	ElapsedS           float64  `json:"elapsed_s"`
	WatchdogZeroStreak int      `json:"watchdog_zero_streak,omitempty"`
	BreakerTripped     bool     `json:"breaker_tripped,omitempty"`
	VolLowThreshold    *float64 `json:"vol_low_threshold,omitempty"`
}

type trainingCyclePnL struct {
	Cycle int     `json:"cycle"`
	PnL   float64 `json:"pnl"`
}

type trainingCycleWinRate struct {
	Cycle   int     `json:"cycle"`
	WinRate float64 `json:"win_rate"`
}

type trainingMemoryPoint struct {
	Cycle    int `json:"cycle"`
	Episodic int `json:"episodic"`
	Semantic int `json:"semantic"`
}

type trainingSignalConviction struct {
	Name  string  `json:"name"`
	Value float64 `json:"value"`
}

type trainingActivity struct {
	Cycle   int    `json:"cycle"`
	Type    string `json:"type"` // "trade" | "signal" | "memory"
	Message string `json:"message"`
}

type trainingRegime struct {
	Name           string  `json:"name"`
	Confidence     float64 `json:"confidence"`
	DominantSignal string  `json:"dominant_signal"`
}

type trainingConfig struct {
	Symbols        []string `json:"symbols"`
	InitialCapital float64  `json:"initial_capital"`
	KellyFraction  float64  `json:"kelly_fraction"`
}

type trainingSnapshot struct {
	ID          string  `json:"id"`
	Cycle       int     `json:"cycle"`
	CreatedAt   string  `json:"created_at"`
	TotalPnL    float64 `json:"total_pnl"`
	WinRate     float64 `json:"win_rate"`
	TotalTrades int     `json:"total_trades"`
}

type trainingMetrics struct {
	TotalTrades     int                        `json:"total_trades"`
	WinRate         float64                    `json:"win_rate"`
	TotalPnL        float64                    `json:"total_pnl"`
	RealisedPnL     float64                    `json:"realised_pnl"`
	UnrealisedPnL   float64                    `json:"unrealised_pnl"`
	MemoryCount     trainingMemoryCount        `json:"memory_count"`
	SymbolBreakdown []trainingSymbolStats      `json:"symbol_breakdown"`
	RecentTrades    []trainingRecentTrade      `json:"recent_trades"`
	SignalHealth    []trainingSignalConviction `json:"signal_health"`
	CurrentCycle    int                        `json:"current_cycle"`
	TotalCycles     int                        `json:"total_cycles"`
	Status          string                     `json:"status"`
}

type trainingMemoryCount struct {
	Episodic int `json:"episodic"`
	Semantic int `json:"semantic"`
	Total    int `json:"total"`
}

type trainingSymbolStats struct {
	Symbol   string  `json:"symbol"`
	Trades   int     `json:"trades"`
	WinRate  float64 `json:"win_rate"`
	TotalPnL float64 `json:"total_pnl"`
}

type trainingRecentTrade struct {
	Ts    string  `json:"ts"`
	Sym   string  `json:"sym"`
	Side  string  `json:"side"`
	Size  float64 `json:"size"`
	Entry float64 `json:"entry"`
	Exit  float64 `json:"exit_price"`
	PnL   float64 `json:"pnl"`
}

// ── Handlers ─────────────────────────────────────────────────────────────────

// emptyProgress is what the API returns when no training run has started.
func emptyProgress() trainingProgress {
	return trainingProgress{
		Status:           "idle",
		PnLHistory:       []trainingCyclePnL{},
		WinRateHistory:   []trainingCycleWinRate{},
		MemoryGrowth:     []trainingMemoryPoint{},
		SignalConviction: []trainingSignalConviction{},
		ActivityLog:      []trainingActivity{},
		Snapshots:        []trainingSnapshot{},
	}
}

// runningWindow is how recently the progress file must have been written for a
// run to be reported as "running" (run_training.py rewrites it every
// log_interval cycles).
const runningWindow = 10 * time.Minute

// loadProgress reads a progress file and normalises BOTH on-disk shapes into
// trainingProgress:
//
//   - ARRAY  — what scripts/run_training.py actually writes: a list of
//     per-checkpoint dicts. This is the shape of every real
//     data/*_progress.json file; decoding it into the struct below is what
//     used to make GET /api/v1/training/progress fail with 500.
//   - OBJECT — the dashboard-oriented struct shape (also what handleSnapshot
//     used to persist). Still accepted so older/handwritten files keep working.
//
// modTime is used to infer run status for the array shape, which carries no
// explicit status field.
func loadProgress(data []byte, modTime time.Time) (trainingProgress, error) {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 {
		return emptyProgress(), nil
	}

	if trimmed[0] == '[' {
		var cycles []trainingCheckpoint
		if err := json.Unmarshal(trimmed, &cycles); err != nil {
			return emptyProgress(), err
		}
		return progressFromCycles(cycles, modTime), nil
	}

	p := emptyProgress()
	if err := json.Unmarshal(trimmed, &p); err != nil {
		return emptyProgress(), err
	}
	if p.Status == "" {
		p.Status = "idle"
	}
	if p.Snapshots == nil {
		p.Snapshots = []trainingSnapshot{}
	}
	return p, nil
}

// progressFromCycles projects the raw run_training.py checkpoint array onto the
// dashboard's progress shape (pnl/win-rate series, current cycle, regime).
func progressFromCycles(cycles []trainingCheckpoint, modTime time.Time) trainingProgress {
	p := emptyProgress()
	p.Cycles = cycles
	if len(cycles) == 0 {
		return p
	}

	for _, c := range cycles {
		p.PnLHistory = append(p.PnLHistory, trainingCyclePnL{Cycle: c.Cycle, PnL: c.TotalPnL})
		p.WinRateHistory = append(p.WinRateHistory, trainingCycleWinRate{Cycle: c.Cycle, WinRate: c.WinRate})
		if c.SemanticPatternsDB > 0 {
			p.MemoryGrowth = append(p.MemoryGrowth, trainingMemoryPoint{Cycle: c.Cycle, Semantic: c.SemanticPatternsDB})
		}
	}

	first := cycles[0]
	last := cycles[len(cycles)-1]
	p.StartedAt = first.Timestamp
	p.CurrentCycle = last.Cycle
	p.CurrentRegime = trainingRegime{Name: last.Regime}

	// The array shape has no status field; infer from file freshness.
	p.Status = "complete"
	if !modTime.IsZero() && time.Since(modTime) < runningWindow {
		p.Status = "running"
	}
	return p
}

// readProgressFile reads + normalises the shared training_progress.json.
// Returns ok=false (with a zero-value progress) when the file is absent.
func (h *TrainingHandler) readProgressFile() (trainingProgress, bool, error) {
	path := filepath.Join(h.progressDir, "training_progress.json")
	data, err := os.ReadFile(path) //nolint:gosec
	if err != nil {
		return emptyProgress(), false, err
	}
	var mod time.Time
	if fi, statErr := os.Stat(path); statErr == nil {
		mod = fi.ModTime()
	}
	p, err := loadProgress(data, mod)
	return p, true, err
}

// handleProgress reads training_progress.json and returns it in the normalised
// dashboard shape, accepting either on-disk shape (see loadProgress).
func (h *TrainingHandler) handleProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	progress, ok, err := h.readProgressFile()
	if !ok {
		if os.IsNotExist(err) {
			// Return empty/default progress when no training run has started.
			writeJSON(w, emptyProgress())
			return
		}
		http.Error(w, "failed to read progress file", http.StatusInternalServerError)
		return
	}
	if err != nil {
		http.Error(w, "failed to parse progress file", http.StatusInternalServerError)
		return
	}

	writeJSON(w, progress)
}

// handleMetrics queries postgres for real-time aggregated training metrics.
func (h *TrainingHandler) handleMetrics(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	metrics := &trainingMetrics{Status: "idle"}

	// Read progress file for cycle info and status (either on-disk shape).
	if p, ok, err := h.readProgressFile(); ok && err == nil {
		metrics.CurrentCycle = p.CurrentCycle
		metrics.TotalCycles = p.TotalCycles
		metrics.Status = p.Status
		metrics.SignalHealth = p.SignalConviction
	}

	// Query postgres for live trading metrics.
	sqlDB := h.db.StateDB()

	// Total trades + win rate + PnL from victoria_trades.
	var totalTrades int
	var wins int
	var totalPnL, realisedPnL float64
	row := sqlDB.QueryRowContext(ctx, //nolint:gosec
		`SELECT
			COUNT(*),
			SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
			COALESCE(SUM(pnl), 0),
			COALESCE(SUM(CASE WHEN exit_price > 0 THEN pnl ELSE 0 END), 0)
		FROM victoria_trades`)
	if err := row.Scan(&totalTrades, &wins, &totalPnL, &realisedPnL); err != nil && err != sql.ErrNoRows {
		// Table may not exist yet — fall back to zeros.
		totalTrades, wins, totalPnL, realisedPnL = 0, 0, 0, 0
	}

	metrics.TotalTrades = totalTrades
	metrics.TotalPnL = totalPnL
	metrics.RealisedPnL = realisedPnL
	metrics.UnrealisedPnL = totalPnL - realisedPnL
	if totalTrades > 0 {
		metrics.WinRate = float64(wins) / float64(totalTrades)
	}

	// Per-symbol breakdown.
	symRows, err := sqlDB.QueryContext(ctx, //nolint:gosec
		`SELECT sym,
			COUNT(*) AS trades,
			SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
			COALESCE(SUM(pnl), 0) AS total_pnl
		FROM victoria_trades
		GROUP BY sym
		ORDER BY total_pnl DESC
		LIMIT 10`)
	if err == nil {
		defer symRows.Close() //nolint:errcheck
		for symRows.Next() {
			var s trainingSymbolStats
			var symWins int
			if err := symRows.Scan(&s.Symbol, &s.Trades, &symWins, &s.TotalPnL); err == nil {
				if s.Trades > 0 {
					s.WinRate = float64(symWins) / float64(s.Trades)
				}
				metrics.SymbolBreakdown = append(metrics.SymbolBreakdown, s)
			}
		}
	}

	// Recent trades (last 20).
	tradeRows, err := sqlDB.QueryContext(ctx, //nolint:gosec
		`SELECT ts, sym, side, size, entry, COALESCE(exit_price,0), COALESCE(pnl,0)
		FROM victoria_trades
		ORDER BY recorded_at DESC
		LIMIT 20`)
	if err == nil {
		defer tradeRows.Close() //nolint:errcheck
		for tradeRows.Next() {
			var t trainingRecentTrade
			if err := tradeRows.Scan(&t.Ts, &t.Sym, &t.Side, &t.Size, &t.Entry, &t.Exit, &t.PnL); err == nil {
				metrics.RecentTrades = append(metrics.RecentTrades, t)
			}
		}
	}

	// Memory count from victoria state (if available).
	var episodic, semantic int
	_ = sqlDB.QueryRowContext(ctx, `SELECT COUNT(*) FROM victoria_episodes`).Scan(&episodic)        //nolint:gosec
	_ = sqlDB.QueryRowContext(ctx, `SELECT COUNT(*) FROM victoria_semantic_memory`).Scan(&semantic) //nolint:gosec
	metrics.MemoryCount = trainingMemoryCount{
		Episodic: episodic,
		Semantic: semantic,
		Total:    episodic + semantic,
	}

	// Null-safe defaults.
	if metrics.SymbolBreakdown == nil {
		metrics.SymbolBreakdown = []trainingSymbolStats{}
	}
	if metrics.RecentTrades == nil {
		metrics.RecentTrades = []trainingRecentTrade{}
	}
	if metrics.SignalHealth == nil {
		metrics.SignalHealth = []trainingSignalConviction{}
	}

	writeJSON(w, metrics)
}

// handleStream is an SSE endpoint that pushes training metrics every 5 seconds.
func (h *TrainingHandler) handleStream(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	fmt.Fprintf(w, "event: connected\ndata: {\"message\":\"training stream connected\"}\n\n") //nolint:errcheck
	flusher.Flush()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
			// Read current progress (either on-disk shape).
			p, ok, err := h.readProgressFile()
			if !ok || err != nil {
				continue
			}

			payload, _ := json.Marshal(map[string]any{
				"type":          "progress",
				"timestamp":     time.Now().UTC().Format(time.RFC3339),
				"current_cycle": p.CurrentCycle,
				"total_cycles":  p.TotalCycles,
				"status":        p.Status,
			})
			fmt.Fprintf(w, "event: progress\ndata: %s\n\n", payload) //nolint:errcheck
			flusher.Flush()
		}
	}
}

// handleSnapshot takes a snapshot of current metrics.
func (h *TrainingHandler) handleSnapshot(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	p, ok, err := h.readProgressFile()
	if !ok {
		http.Error(w, "no active training run", http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, "failed to parse progress", http.StatusInternalServerError)
		return
	}

	now := time.Now().UTC()
	snap := trainingSnapshot{
		ID:        fmt.Sprintf("snap_%d", now.UnixMilli()),
		Cycle:     p.CurrentCycle,
		CreatedAt: now.Format(time.RFC3339),
	}

	// Fill metrics from last pnl history entry.
	if len(p.PnLHistory) > 0 {
		snap.TotalPnL = p.PnLHistory[len(p.PnLHistory)-1].PnL
	}
	if len(p.WinRateHistory) > 0 {
		snap.WinRate = p.WinRateHistory[len(p.WinRateHistory)-1].WinRate
	}
	snap.TotalTrades = len(p.ActivityLog)
	if len(p.Cycles) > 0 {
		lastCycle := p.Cycles[len(p.Cycles)-1]
		snap.TotalPnL = lastCycle.TotalPnL
		snap.WinRate = lastCycle.WinRate
		snap.TotalTrades = lastCycle.TradesClosed
	}

	// Persist to a sidecar file. training_progress.json belongs to
	// scripts/run_training.py — a live run rewrites it every log_interval
	// cycles, so the API must never write over it.
	snaps := append(h.readSidecarSnapshots(), snap)
	updated, err := json.MarshalIndent(snaps, "", "  ")
	if err != nil {
		http.Error(w, "failed to marshal snapshots", http.StatusInternalServerError)
		return
	}
	if err := os.WriteFile(h.snapshotsPath(), updated, 0600); err != nil { //nolint:gosec
		http.Error(w, "failed to write snapshots", http.StatusInternalServerError)
		return
	}

	writeJSON(w, snap)
}

// snapshotsPath is the API-owned sidecar holding dashboard snapshots.
func (h *TrainingHandler) snapshotsPath() string {
	return filepath.Join(h.progressDir, "training_snapshots.json")
}

func (h *TrainingHandler) readSidecarSnapshots() []trainingSnapshot {
	data, err := os.ReadFile(h.snapshotsPath()) //nolint:gosec
	if err != nil {
		return []trainingSnapshot{}
	}
	var snaps []trainingSnapshot
	if json.Unmarshal(data, &snaps) != nil || snaps == nil {
		return []trainingSnapshot{}
	}
	return snaps
}

// handleListSnapshots returns all snapshots from the progress file.
func (h *TrainingHandler) handleListSnapshots(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Snapshots live in the API-owned sidecar, plus any embedded in an
	// object-shaped progress file (legacy writes).
	snaps := h.readSidecarSnapshots()
	if p, ok, err := h.readProgressFile(); ok && err == nil {
		snaps = append(snaps, p.Snapshots...)
	}

	// Reverse so newest first.
	for i, j := 0, len(snaps)-1; i < j; i, j = i+1, j-1 {
		snaps[i], snaps[j] = snaps[j], snaps[i]
	}

	writeJSON(w, snaps)
}

// handleJSONL serves the raw JSONL metrics for a training version as a JSON array.
// Query param: version (e.g. "v61"). Falls back to the most-recently-modified progress file.
func (h *TrainingHandler) handleJSONL(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	version := r.URL.Query().Get("version")
	if version == "" {
		// Infer from most-recently-modified {version}_progress.json in progressDir.
		entries, err := os.ReadDir(h.progressDir)
		if err == nil {
			var latest string
			var latestMod int64
			for _, e := range entries {
				if !strings.HasSuffix(e.Name(), "_progress.json") {
					continue
				}
				info, err := e.Info()
				if err != nil {
					continue
				}
				if info.ModTime().UnixNano() > latestMod {
					latestMod = info.ModTime().UnixNano()
					latest = strings.TrimSuffix(e.Name(), "_progress.json")
				}
			}
			version = latest
		}
	}
	if version == "" {
		writeJSON(w, []json.RawMessage{})
		return
	}

	jsonlPath := fmt.Sprintf("/tmp/%s_metrics.jsonl", version)
	data, err := os.ReadFile(jsonlPath) //nolint:gosec
	if err != nil {
		writeJSON(w, []json.RawMessage{})
		return
	}

	lines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	rows := make([]json.RawMessage, 0, len(lines))
	for _, line := range lines {
		if len(line) == 0 {
			continue
		}
		if !json.Valid(line) {
			continue
		}
		rows = append(rows, json.RawMessage(line))
	}
	writeJSON(w, rows)
}

// handleVersionStream is an SSE endpoint that streams per-cycle JSONL metrics
// for a specific training version in real time.
// Query param: version (e.g. "?version=v70"). Returns 400 if missing.
// Emits raw JSONL lines as SSE data events and a final "complete" event once
// the results file appears in progressDir.
func (h *TrainingHandler) handleVersionStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	version := r.URL.Query().Get("version")
	if version == "" {
		http.Error(w, "version query param required", http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	// Send initial connected event.
	connected, _ := json.Marshal(map[string]string{
		"version": version,
		"message": "stream connected",
	})
	fmt.Fprintf(w, "event: connected\ndata: %s\n\n", connected) //nolint:errcheck
	flusher.Flush()

	jsonlPath := fmt.Sprintf("/tmp/%s_metrics.jsonl", version)
	resultsPath := filepath.Join(h.progressDir, version+"_results.json")

	var lastOffset int64

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
			// Read new bytes from the JSONL file starting at lastOffset.
			f, err := os.Open(jsonlPath) //nolint:gosec
			if err == nil {
				fi, statErr := f.Stat()
				if statErr == nil && fi.Size() > lastOffset {
					if _, seekErr := f.Seek(lastOffset, 0); seekErr == nil {
						buf := make([]byte, fi.Size()-lastOffset)
						n, readErr := f.Read(buf)
						if readErr == nil || n > 0 {
							lastOffset += int64(n)
							for line := range bytes.SplitSeq(buf[:n], []byte("\n")) {
								line = bytes.TrimSpace(line)
								if len(line) == 0 {
									continue
								}
								if !json.Valid(line) {
									continue
								}
								fmt.Fprintf(w, "data: %s\n\n", line) //nolint:errcheck,gosec // SSE plain-text stream, not HTML; line validated as JSON above
							}
							flusher.Flush()
						}
					}
				}
				_ = f.Close()
			}

			// Check if the training run has finished (results file present).
			if _, err := os.Stat(resultsPath); err == nil { //nolint:gosec // G304/G703: resultsPath derived from validated version string
				complete, _ := json.Marshal(map[string]string{
					"version": version,
					"message": "training complete",
				})
				fmt.Fprintf(w, "event: complete\ndata: %s\n\n", complete) //nolint:errcheck
				flusher.Flush()
				return
			}
		}
	}
}

// ── Versions / Compare ───────────────────────────────────────────────────────

// trainingVersionInfo holds the normalised summary extracted from a v*_results.json file.
type trainingVersionInfo struct {
	Version     string  `json:"version"`
	TotalPnL    float64 `json:"total_pnl"`
	TotalTrades int     `json:"total_trades"`
	WinRate     float64 `json:"win_rate"`
	SharpeRatio float64 `json:"sharpe_ratio"`
}

// trainingCompareResponse is the response for the compare endpoint.
type trainingCompareResponse struct {
	Base            string  `json:"base"`
	Target          string  `json:"target"`
	PnLDelta        float64 `json:"pnl_delta"`
	WinRateDelta    float64 `json:"win_rate_delta"`
	TradeCountDelta int     `json:"trade_count_delta"`
	SharpeDelta     float64 `json:"sharpe_delta"`
	Verdict         string  `json:"verdict"`
}

// rawResults is a permissive struct that can decode both old and new results.json formats.
type rawResults struct {
	Version string `json:"version"`
	Trades  struct {
		TotalClosed int     `json:"total_closed"`
		WinRate     float64 `json:"win_rate"`
		TotalPnLUSD float64 `json:"total_pnl_usd"`
	} `json:"trades"`
	Eval struct {
		SharpeRatio float64 `json:"sharpe_ratio"`
	} `json:"eval"`
}

// parseResultsFile reads a v*_results.json file and normalises it into a trainingVersionInfo.
func parseResultsFile(path, versionHint string) (*trainingVersionInfo, error) {
	data, err := os.ReadFile(path) //nolint:gosec
	if err != nil {
		return nil, err
	}
	var r rawResults
	if err := json.Unmarshal(data, &r); err != nil {
		return nil, err
	}
	version := r.Version
	if version == "" {
		version = versionHint
	}
	return &trainingVersionInfo{
		Version:     version,
		TotalPnL:    r.Trades.TotalPnLUSD,
		TotalTrades: r.Trades.TotalClosed,
		WinRate:     r.Trades.WinRate,
		SharpeRatio: r.Eval.SharpeRatio,
	}, nil
}

// handleVersions scans progressDir for v*_results.json and returns version summaries.
func (h *TrainingHandler) handleVersions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	entries, err := os.ReadDir(h.progressDir)
	if err != nil {
		http.Error(w, "failed to read data directory", http.StatusInternalServerError)
		return
	}

	versions := make([]trainingVersionInfo, 0, len(entries))
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, "_results.json") {
			continue
		}
		versionHint := strings.TrimSuffix(name, "_results.json")
		if !strings.HasPrefix(versionHint, "v") {
			continue
		}
		info, err := parseResultsFile(filepath.Join(h.progressDir, name), versionHint)
		if err != nil {
			continue
		}
		versions = append(versions, *info)
	}

	if versions == nil {
		versions = []trainingVersionInfo{}
	}

	writeJSON(w, map[string]any{"versions": versions})
}

// handleCompare reads two results files and returns a delta comparison.
// Query params: base=<version> target=<version>  (e.g. ?base=v63&target=v71)
func (h *TrainingHandler) handleCompare(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	baseVer := r.URL.Query().Get("base")
	targetVer := r.URL.Query().Get("target")
	if baseVer == "" || targetVer == "" {
		http.Error(w, "base and target query params are required", http.StatusBadRequest)
		return
	}

	basePath := filepath.Join(h.progressDir, baseVer+"_results.json")
	baseInfo, err := parseResultsFile(basePath, baseVer)
	if err != nil {
		if os.IsNotExist(err) {
			http.Error(w, fmt.Sprintf("base version %q not found", baseVer), http.StatusNotFound)
			return
		}
		http.Error(w, "failed to read base results", http.StatusInternalServerError)
		return
	}

	targetPath := filepath.Join(h.progressDir, targetVer+"_results.json")
	targetInfo, err := parseResultsFile(targetPath, targetVer)
	if err != nil {
		if os.IsNotExist(err) {
			http.Error(w, fmt.Sprintf("target version %q not found", targetVer), http.StatusNotFound)
			return
		}
		http.Error(w, "failed to read target results", http.StatusInternalServerError)
		return
	}

	pnlDelta := targetInfo.TotalPnL - baseInfo.TotalPnL
	verdict := "neutral"
	switch {
	case pnlDelta > 0:
		verdict = "improved"
	case pnlDelta < 0:
		verdict = "regressed"
	}

	writeJSON(w, trainingCompareResponse{
		Base:            baseVer,
		Target:          targetVer,
		PnLDelta:        pnlDelta,
		WinRateDelta:    targetInfo.WinRate - baseInfo.WinRate,
		TradeCountDelta: targetInfo.TotalTrades - baseInfo.TotalTrades,
		SharpeDelta:     targetInfo.SharpeRatio - baseInfo.SharpeRatio,
		Verdict:         verdict,
	})
}

// handleTradeDetails serves per-trade signal waterfall records from
// /tmp/{version}_trade_details.jsonl written by run_training.py.
// Query param: version (e.g. "?version=v70"). If omitted, the most recent
// version is auto-detected from the progress directory.
func (h *TrainingHandler) handleTradeDetails(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	version := r.URL.Query().Get("version")
	if version == "" {
		// Auto-detect latest version from progressDir (same logic as handleJSONL).
		entries, err := os.ReadDir(h.progressDir)
		if err == nil {
			var latest string
			var latestMod int64
			for _, e := range entries {
				if e.IsDir() || !strings.HasSuffix(e.Name(), "_progress.json") {
					continue
				}
				info, err := e.Info()
				if err != nil {
					continue
				}
				if info.ModTime().UnixNano() > latestMod {
					latestMod = info.ModTime().UnixNano()
					latest = strings.TrimSuffix(e.Name(), "_progress.json")
				}
			}
			version = latest
		}
	}
	if version == "" {
		writeJSON(w, []json.RawMessage{})
		return
	}

	jsonlPath := fmt.Sprintf("/tmp/%s_trade_details.jsonl", version)
	data, err := os.ReadFile(jsonlPath) //nolint:gosec
	if err != nil {
		writeJSON(w, []json.RawMessage{})
		return
	}

	lines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	rows := make([]json.RawMessage, 0, len(lines))
	for _, line := range lines {
		if len(line) == 0 {
			continue
		}
		if !json.Valid(line) {
			continue
		}
		rows = append(rows, json.RawMessage(line))
	}
	writeJSON(w, rows)
}

// ── Decision Trace handler ─────────────────────────────────────────────────────

// handleDecisionTraces serves the extended per-cycle decision traces written by
// strategy.py's TraceWriter to data/decision_traces/{version}.jsonl.
//
// Query params:
//
//	version  (required) e.g. "v97"
//	limit    max records to return (default 200)
//	filter   "rejected_close" — only near-threshold rejections
//	ticker   filter by specific symbol
func (h *TrainingHandler) handleDecisionTraces(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	version := r.URL.Query().Get("version")
	if version == "" {
		http.Error(w, "version query param required", http.StatusBadRequest)
		return
	}

	limitStr := r.URL.Query().Get("limit")
	limit := 200
	if limitStr != "" {
		if n, err := parseInt(limitStr); err == nil && n > 0 {
			limit = n
		}
	}

	filterMode := r.URL.Query().Get("filter") // "rejected_close" or ""
	tickerFilter := r.URL.Query().Get("ticker")

	tracePath := filepath.Join(h.progressDir, "decision_traces", version+".jsonl")
	data, err := os.ReadFile(tracePath) //nolint:gosec
	if err != nil {
		writeJSON(w, map[string]any{"traces": []json.RawMessage{}, "total": 0})
		return
	}

	tLines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	rows := make([]json.RawMessage, 0, len(tLines))
	for _, line := range tLines {
		if len(line) == 0 || !json.Valid(line) {
			continue
		}

		// Apply ticker filter without full unmarshal (simple string search)
		if tickerFilter != "" {
			if !bytes.Contains(line, []byte(`"`+tickerFilter+`"`)) {
				continue
			}
		}

		// Apply near-threshold filter: unmarshal only needed fields
		if filterMode == "rejected_close" {
			var partial struct {
				FinalDecision  string  `json:"final_decision"`
				BlockingFilter string  `json:"blocking_filter"`
				ThresholdGap   float64 `json:"threshold_gap"`
			}
			if json.Unmarshal(line, &partial) == nil {
				if partial.FinalDecision != "FILTERED" {
					continue
				}
				isConvictionBlock := strings.HasPrefix(partial.BlockingFilter, "weighted_conviction") ||
					strings.HasPrefix(partial.BlockingFilter, "abs_min_conviction")
				if !isConvictionBlock {
					continue
				}
				if partial.ThresholdGap < -0.03 {
					continue // too far from threshold to be interesting
				}
			}
		}

		rows = append(rows, json.RawMessage(line))
		if len(rows) >= limit {
			break
		}
	}

	if rows == nil {
		rows = []json.RawMessage{}
	}
	writeJSON(w, map[string]any{"traces": rows, "total": len(rows)})
}

// ── Signal Correlation handler ─────────────────────────────────────────────────

// handleSignalCorrelation returns the rolling pairwise signal correlation matrix
// written by strategy.py's SignalCorrelationMonitor to /tmp/{version}_signal_correlation.json.
//
// Query params:
//
//	version  (required) e.g. "v97"
func (h *TrainingHandler) handleSignalCorrelation(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	version := r.URL.Query().Get("version")
	if version == "" {
		// Auto-detect latest version
		entries, err := os.ReadDir(h.progressDir)
		if err == nil {
			var latest string
			var latestMod int64
			for _, e := range entries {
				if !strings.HasSuffix(e.Name(), "_progress.json") {
					continue
				}
				info, err := e.Info()
				if err != nil {
					continue
				}
				if info.ModTime().UnixNano() > latestMod {
					latestMod = info.ModTime().UnixNano()
					latest = strings.TrimSuffix(e.Name(), "_progress.json")
				}
			}
			version = latest
		}
	}

	if version == "" {
		writeJSON(w, map[string]any{"signals": []string{}, "matrix": [][]float64{}, "n_observations": 0})
		return
	}

	corrPath := fmt.Sprintf("/tmp/%s_signal_correlation.json", version)
	data, err := os.ReadFile(corrPath) //nolint:gosec
	if err != nil {
		writeJSON(w, map[string]any{
			"signals":        []string{},
			"matrix":         [][]float64{},
			"n_observations": 0,
			"version":        version,
		})
		return
	}

	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		http.Error(w, "failed to parse correlation matrix", http.StatusInternalServerError)
		return
	}
	result["version"] = version
	writeJSON(w, result)
}

// ── Path safety ───────────────────────────────────────────────────────────────

// maxVersionLen bounds the version/cell identifier accepted from query params.
const maxVersionLen = 128

// isSafeVersion reports whether a version/cell identifier is safe to
// interpolate into a filename. Real cells look like "v49", "v206b",
// "bt_v132a_crisis", "v252_replay_2025-03-05" — alphanumerics, underscore and
// hyphen only. Anything containing a path separator, a dot, or NUL is rejected,
// which kills "../../etc/passwd" and "v1/../x" outright.
func isSafeVersion(v string) bool {
	if v == "" || len(v) > maxVersionLen {
		return false
	}
	for _, c := range v {
		switch {
		case c >= 'a' && c <= 'z':
		case c >= 'A' && c <= 'Z':
		case c >= '0' && c <= '9':
		case c == '_' || c == '-':
		default:
			return false
		}
	}
	return true
}

// ── Gate results ──────────────────────────────────────────────────────────────

// gateResultFileSuffix is the filename written by omega/eval/standing_gates.py
// (and, before 2026-08-18, omega/eval/v49_gates.py):
// `{version}_gate_result.json` in the audit/data dir.
const gateResultFileSuffix = "_gate_result.json"

// rawGateResult mirrors the JSON emitted by the gate modules. TWO shapes exist
// and both must round-trip:
//
//   - LEGACY (omega/eval/v49_gates.py): "gates" is map[string]bool, and the
//     summary keys are LITERAL "v48_summary"/"v49_summary" regardless of which
//     versions were actually compared (the module hard-codes its dataclass field
//     names); the real version names live inside each summary's "version".
//   - STANDING (omega/eval/standing_gates.py, 2026-08-18): "gates" is
//     map[string]object where each object carries a "status" of
//     pass|fail|not_evaluated plus the numbers, and the file carries a top-level
//     "verdict" (PASS|FAIL|NO_OP|NO_BASELINE|ERROR) and "family". It writes its
//     own summary under "candidate_summary" and has no baseline summary at all —
//     the standing floor, not a sibling run, is what it compares against.
//
// "gates" is therefore held as RawMessage per key and projected two ways: a
// lossy bool map for readers that predate the verdict vocabulary (not_evaluated
// is OMITTED from it rather than guessed at — a gate reported as absent renders
// as "not reported", which is true, whereas a guessed bool would be a lie), and
// an untouched passthrough in gate_details.
type rawGateResult struct {
	Passed    bool                       `json:"passed"`
	Verdict   string                     `json:"verdict"`
	Family    string                     `json:"family"`
	Gates     map[string]json.RawMessage `json:"gates"`
	Failures  []string                   `json:"failures"`
	Baseline  json.RawMessage            `json:"v48_summary"`
	Candidate json.RawMessage            `json:"v49_summary"`
	// Standing-shape only; absent (and omitted) for legacy files.
	Notes            []string        `json:"notes"`
	Sibling          json.RawMessage `json:"sibling_comparison"`
	StandingBaseline json.RawMessage `json:"standing_baseline_used"`
	StandingSummary  json.RawMessage `json:"candidate_summary"`
	Error            string          `json:"error"`
}

type gateResponse struct {
	Version          string                     `json:"version"`
	Passed           bool                       `json:"passed"`
	Verdict          string                     `json:"verdict,omitempty"`
	Family           string                     `json:"family,omitempty"`
	Gates            map[string]bool            `json:"gates"`
	GateDetails      map[string]json.RawMessage `json:"gate_details,omitempty"`
	Failures         []string                   `json:"failures"`
	BaselineSummary  json.RawMessage            `json:"baseline_summary,omitempty"`
	CandidateSummary json.RawMessage            `json:"candidate_summary,omitempty"`
	Notes            []string                   `json:"notes,omitempty"`
	SiblingComparson json.RawMessage            `json:"sibling_comparison,omitempty"`
	StandingBaseline json.RawMessage            `json:"standing_baseline_used,omitempty"`
	Error            string                     `json:"error,omitempty"`
	Raw              json.RawMessage            `json:"raw"`
	ResolvedLatest   bool                       `json:"resolved_latest"`
}

// gateStatus is the "status" field of a standing-gate entry.
type gateStatusEnvelope struct {
	Status string `json:"status"`
}

// projectGates splits the per-gate values into the legacy bool map and the
// verbatim detail map. A gate whose status is not_evaluated (or unrecognised) is
// left OUT of the bool map on purpose.
func projectGates(raw map[string]json.RawMessage) (map[string]bool, map[string]json.RawMessage) {
	bools := map[string]bool{}
	details := map[string]json.RawMessage{}
	for name, value := range raw {
		var b bool
		if err := json.Unmarshal(value, &b); err == nil {
			bools[name] = b
			continue
		}
		var env gateStatusEnvelope
		if err := json.Unmarshal(value, &env); err == nil && env.Status != "" {
			details[name] = value
			switch env.Status {
			case "pass":
				bools[name] = true
			case "fail":
				bools[name] = false
			}
			continue
		}
		// Unknown shape: pass it through untouched rather than dropping it.
		details[name] = value
	}
	if len(details) == 0 {
		details = nil
	}
	return bools, details
}

// latestGateVersion returns the version of the most recently written
// *_gate_result.json in dir. Modification time (not lexical order) decides
// "latest": cell names like "bt_v132a_crisis" and "v99" do not sort usefully.
func latestGateVersion(dir string) string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	var best string
	var bestMod int64
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), gateResultFileSuffix) {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		mod := info.ModTime().UnixNano()
		name := strings.TrimSuffix(e.Name(), gateResultFileSuffix)
		if mod > bestMod || (mod == bestMod && name > best) {
			bestMod, best = mod, name
		}
	}
	return best
}

// handleGates serves data/{version}_gate_result.json (produced by
// omega/eval/standing_gates.py via scripts/run_training.py; archived files come
// from the retired omega/eval/v49_gates.py). Both shapes round-trip.
// Query param: version (optional — defaults to the most recent gate file).
func (h *TrainingHandler) handleGates(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	version := r.URL.Query().Get("version")
	resolvedLatest := false
	if version == "" {
		version = latestGateVersion(h.progressDir)
		resolvedLatest = true
		if version == "" {
			http.Error(w, "no gate results found", http.StatusNotFound)
			return
		}
	}
	if !isSafeVersion(version) {
		http.Error(w, "invalid version parameter", http.StatusBadRequest)
		return
	}

	path := filepath.Join(h.progressDir, version+gateResultFileSuffix)
	data, err := os.ReadFile(path) //nolint:gosec // path built from an isSafeVersion-validated identifier
	if err != nil {
		if os.IsNotExist(err) {
			http.Error(w, fmt.Sprintf("no gate result for version %q", version), http.StatusNotFound)
			return
		}
		http.Error(w, "failed to read gate result", http.StatusInternalServerError)
		return
	}

	var raw rawGateResult
	if err := json.Unmarshal(data, &raw); err != nil {
		http.Error(w, "failed to parse gate result", http.StatusInternalServerError)
		return
	}
	if raw.Failures == nil {
		raw.Failures = []string{}
	}
	gates, details := projectGates(raw.Gates)

	// The standing-gate file has no baseline summary (it gates against a config
	// floor, not a sibling run) and writes its own summary under
	// "candidate_summary"; the legacy key stays authoritative when present.
	candidate := raw.Candidate
	if candidate == nil {
		candidate = raw.StandingSummary
	}

	writeJSON(w, gateResponse{
		Version:          version,
		Passed:           raw.Passed,
		Verdict:          raw.Verdict,
		Family:           raw.Family,
		Gates:            gates,
		GateDetails:      details,
		Failures:         raw.Failures,
		BaselineSummary:  raw.Baseline,
		CandidateSummary: candidate,
		Notes:            raw.Notes,
		SiblingComparson: raw.Sibling,
		StandingBaseline: raw.StandingBaseline,
		Error:            raw.Error,
		Raw:              json.RawMessage(data),
		ResolvedLatest:   resolvedLatest,
	})
}

// ── Grid ruler (campaign-level verdict) ───────────────────────────────────────

// gridVerdictFileSuffix is the filename written by omega/eval/grid_ruler.py via
// scripts/run_grid_ruler.py: `{run_label}_grid_verdict.json`.
//
// It is a SIBLING ROUTE to /gates rather than a `?grid=1` flag on it, because
// the grain differs: a gate result is per CELL (one 90-day window), a grid
// verdict is per GRID (a whole 32-window run). One version label maps to at most
// one gate file but a grid verdict covers many labels at once, so folding them
// into one response would force a reader to know which of the two subjects a
// field belonged to.
const gridVerdictFileSuffix = "_grid_verdict.json"

// rawGridVerdict mirrors omega/eval/grid_ruler.GridVerdict.to_dict(). Only ONE
// shape exists (there is no archive predating it), so unlike the gate handler
// nothing here has to be projected two ways. The per-family rulings are held as
// RawMessage and passed through untouched: the ruler decides what evidence a
// family carries, not this handler.
type rawGridVerdict struct {
	RunLabel   string                     `json:"run_label"`
	Verdict    string                     `json:"verdict"`
	Passed     bool                       `json:"passed"`
	Families   map[string]json.RawMessage `json:"families"`
	Coverage   json.RawMessage            `json:"coverage"`
	Failures   []string                   `json:"failures"`
	RulerNotes []string                   `json:"ruler_notes"`
	Standing   json.RawMessage            `json:"standing_distribution_used"`
	Provenance json.RawMessage            `json:"provenance"`
	Error      string                     `json:"error"`
}

type gridRulerResponse struct {
	RunLabel   string                     `json:"run_label"`
	Verdict    string                     `json:"verdict"`
	Passed     bool                       `json:"passed"`
	Families   map[string]json.RawMessage `json:"families,omitempty"`
	Coverage   json.RawMessage            `json:"coverage,omitempty"`
	Failures   []string                   `json:"failures"`
	RulerNotes []string                   `json:"ruler_notes,omitempty"`
	Standing   json.RawMessage            `json:"standing_distribution_used,omitempty"`
	Provenance json.RawMessage            `json:"provenance,omitempty"`
	Error      string                     `json:"error,omitempty"`
	Raw        json.RawMessage            `json:"raw"`
	// True when no run was asked for and the newest verdict file was picked.
	ResolvedLatest bool `json:"resolved_latest"`
	// True when the asked-for label had no verdict file of its own and the
	// longest grid-verdict label that PREFIXES it was served instead. This is
	// how a CELL label ("v246_wf_snap_wf_20230912") finds the GRID it belongs to
	// ("v246_wf"). It is surfaced, not hidden: the board must be able to say
	// "this is the grid's verdict, not this cell's".
	ResolvedPrefix bool `json:"resolved_prefix,omitempty"`
	// The label actually asked for, when it differs from run_label.
	Requested string `json:"requested,omitempty"`
}

// gridVerdictLabels lists the run labels with a *_grid_verdict.json in dir.
func gridVerdictLabels(dir string) []string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), gridVerdictFileSuffix) {
			continue
		}
		out = append(out, strings.TrimSuffix(e.Name(), gridVerdictFileSuffix))
	}
	return out
}

// latestGridVerdict returns the run label of the most recently written
// *_grid_verdict.json. Modification time decides "latest", for the same reason
// it does in latestGateVersion: run labels do not sort usefully.
func latestGridVerdict(dir string) string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	var best string
	var bestMod int64
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), gridVerdictFileSuffix) {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		mod := info.ModTime().UnixNano()
		name := strings.TrimSuffix(e.Name(), gridVerdictFileSuffix)
		if mod > bestMod || (mod == bestMod && name > best) {
			bestMod, best = mod, name
		}
	}
	return best
}

// longestGridPrefix returns the longest label in `labels` that is a prefix of
// `asked`, or "". Deterministic: on equal length the lexically greater wins, so
// two labels of the same length can never make the answer depend on ReadDir
// order.
func longestGridPrefix(labels []string, asked string) string {
	best := ""
	for _, label := range labels {
		if !strings.HasPrefix(asked, label) {
			continue
		}
		if len(label) > len(best) || (len(label) == len(best) && label > best) {
			best = label
		}
	}
	return best
}

// handleGridRuler serves data/{run}_grid_verdict.json (produced by
// omega/eval/grid_ruler.py via scripts/run_grid_ruler.py).
//
// Query param: run (optional — defaults to the most recent verdict file). When
// `run` names no verdict file of its own, the longest grid-verdict label that
// prefixes it is served with resolved_prefix=true, which is how the Gates board
// finds the grid a picked CELL belongs to.
func (h *TrainingHandler) handleGridRuler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	asked := r.URL.Query().Get("run")
	resolvedLatest := false
	resolvedPrefix := false
	run := asked

	if run == "" {
		run = latestGridVerdict(h.progressDir)
		resolvedLatest = true
		if run == "" {
			http.Error(w, "no grid verdicts found", http.StatusNotFound)
			return
		}
	}
	if !isSafeVersion(run) {
		http.Error(w, "invalid run parameter", http.StatusBadRequest)
		return
	}

	path := filepath.Join(h.progressDir, run+gridVerdictFileSuffix)
	data, err := os.ReadFile(path) //nolint:gosec // path built from an isSafeVersion-validated identifier
	if err != nil && os.IsNotExist(err) && !resolvedLatest {
		if prefix := longestGridPrefix(gridVerdictLabels(h.progressDir), run); prefix != "" {
			run = prefix
			resolvedPrefix = true
			path = filepath.Join(h.progressDir, run+gridVerdictFileSuffix)
			data, err = os.ReadFile(path) //nolint:gosec // label came from ReadDir of progressDir
		}
	}
	if err != nil {
		if os.IsNotExist(err) {
			http.Error(w, fmt.Sprintf("no grid verdict for run %q", asked), http.StatusNotFound)
			return
		}
		http.Error(w, "failed to read grid verdict", http.StatusInternalServerError)
		return
	}

	var raw rawGridVerdict
	if err := json.Unmarshal(data, &raw); err != nil {
		http.Error(w, "failed to parse grid verdict", http.StatusInternalServerError)
		return
	}
	if raw.Failures == nil {
		raw.Failures = []string{}
	}
	label := raw.RunLabel
	if label == "" {
		label = run
	}
	requested := ""
	if resolvedPrefix {
		requested = asked
	}

	writeJSON(w, gridRulerResponse{
		RunLabel:       label,
		Verdict:        raw.Verdict,
		Passed:         raw.Passed,
		Families:       raw.Families,
		Coverage:       raw.Coverage,
		Failures:       raw.Failures,
		RulerNotes:     raw.RulerNotes,
		Standing:       raw.Standing,
		Provenance:     raw.Provenance,
		Error:          raw.Error,
		Raw:            json.RawMessage(data),
		ResolvedLatest: resolvedLatest,
		ResolvedPrefix: resolvedPrefix,
		Requested:      requested,
	})
}

// ── Forensics ─────────────────────────────────────────────────────────────────

// forensicsFileSuffix is the naming used by omega/tools/forensics/run_diff.py
// (`data/{baseline}-{target}-forensics.json`, e.g. v93-v94-forensics.json).
const forensicsFileSuffix = "-forensics.json"

type forensicsEntry struct {
	Baseline   string `json:"baseline"`
	Target     string `json:"target"`
	File       string `json:"file"`
	SizeBytes  int64  `json:"size_bytes"`
	ModifiedAt string `json:"modified_at"`
}

// handleForensics serves data/{baseline}-{target}-forensics.json, or lists the
// available forensics runs when called without params.
// Query params: baseline, target.
func (h *TrainingHandler) handleForensics(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	baseline := r.URL.Query().Get("baseline")
	target := r.URL.Query().Get("target")

	if baseline == "" && target == "" {
		h.listForensics(w)
		return
	}
	if baseline == "" || target == "" {
		http.Error(w, "both baseline and target query params are required", http.StatusBadRequest)
		return
	}
	if !isSafeVersion(baseline) || !isSafeVersion(target) {
		http.Error(w, "invalid baseline or target parameter", http.StatusBadRequest)
		return
	}

	name := baseline + "-" + target + forensicsFileSuffix
	data, err := os.ReadFile(filepath.Join(h.progressDir, name)) //nolint:gosec // name built from isSafeVersion-validated identifiers
	if err != nil {
		if os.IsNotExist(err) {
			http.Error(w, fmt.Sprintf("no forensics report for %s -> %s", baseline, target), http.StatusNotFound)
			return
		}
		http.Error(w, "failed to read forensics report", http.StatusInternalServerError)
		return
	}
	if !json.Valid(data) {
		http.Error(w, "failed to parse forensics report", http.StatusInternalServerError)
		return
	}

	writeJSON(w, map[string]any{
		"baseline":  baseline,
		"target":    target,
		"file":      name,
		"forensics": json.RawMessage(data),
	})
}

// listForensics enumerates the vA-vB-forensics.json files in progressDir.
// Files that carry the -forensics.json suffix but not the paired A-B naming
// (e.g. v240_universe_forensics.json) are reported separately as "unpaired".
func (h *TrainingHandler) listForensics(w http.ResponseWriter) {
	entries, err := os.ReadDir(h.progressDir)
	if err != nil {
		http.Error(w, "failed to read data directory", http.StatusInternalServerError)
		return
	}

	reports := []forensicsEntry{}
	unpaired := []string{}
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasSuffix(name, "forensics.json") {
			continue
		}
		if !strings.HasSuffix(name, forensicsFileSuffix) {
			unpaired = append(unpaired, name)
			continue
		}
		pair := strings.TrimSuffix(name, forensicsFileSuffix)
		baseline, target, found := strings.Cut(pair, "-")
		if !found || baseline == "" || target == "" {
			unpaired = append(unpaired, name)
			continue
		}
		entry := forensicsEntry{Baseline: baseline, Target: target, File: name}
		if info, err := e.Info(); err == nil {
			entry.SizeBytes = info.Size()
			entry.ModifiedAt = info.ModTime().UTC().Format(time.RFC3339)
		}
		reports = append(reports, entry)
	}

	writeJSON(w, map[string]any{"forensics": reports, "unpaired": unpaired})
}

// ── Training log (markdown) ───────────────────────────────────────────────────

type trainingLogResponse struct {
	Version         string   `json:"version"`
	PreRegistration string   `json:"preRegistration,omitempty"`
	Verdict         string   `json:"verdict,omitempty"`
	Files           []string `json:"files"`
	VerdictFiles    []string `json:"verdictFiles,omitempty"`
}

type trainingLogEntry struct {
	Version            string   `json:"version"`
	HasPreRegistration bool     `json:"hasPreRegistration"`
	VerdictFiles       []string `json:"verdictFiles,omitempty"`
}

// isVersionStem reports whether a training_log markdown stem names a version
// cell (V49, V206b, V262-2, V255_B) rather than a standing doc (README,
// CAMPAIGN_STATUS, REFLECTION_V202).
func isVersionStem(stem string) bool {
	if len(stem) < 2 || (stem[0] != 'V' && stem[0] != 'v') {
		return false
	}
	return stem[1] >= '0' && stem[1] <= '9'
}

// handleTrainingLog serves the victoria training-log markdown for a version:
// omega/nodes/victoria/training_log/{VERSION}.md (pre-registration) and its
// {VERSION}*_VERDICT.md companion. Without a version param it lists the
// available entries. Filenames are matched case-insensitively because the real
// tree mixes cases (V206b.md, V132a, V255_B_VERDICT.md).
func (h *TrainingHandler) handleTrainingLog(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")

	version := r.URL.Query().Get("version")
	if version == "" {
		h.listTrainingLog(w)
		return
	}
	if !isSafeVersion(version) {
		http.Error(w, "invalid version parameter", http.StatusBadRequest)
		return
	}

	entries, err := os.ReadDir(h.logDir)
	if err != nil {
		http.Error(w, "failed to read training log directory", http.StatusNotFound)
		return
	}

	want := strings.ToLower(version)
	resp := trainingLogResponse{Version: version, Files: []string{}}
	var preFile string
	var verdictFiles []string

	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".md") {
			continue
		}
		stem := strings.ToLower(strings.TrimSuffix(e.Name(), filepath.Ext(e.Name())))
		switch {
		case stem == want:
			preFile = e.Name()
		case strings.HasPrefix(stem, want+"_") && strings.HasSuffix(stem, "_verdict"):
			verdictFiles = append(verdictFiles, e.Name())
		}
	}

	if preFile == "" && len(verdictFiles) == 0 {
		http.Error(w, fmt.Sprintf("no training log entry for version %q", version), http.StatusNotFound)
		return
	}

	if preFile != "" {
		if data, err := os.ReadFile(filepath.Join(h.logDir, preFile)); err == nil { //nolint:gosec // filename came from a directory listing
			resp.PreRegistration = string(data)
			resp.Files = append(resp.Files, preFile)
		}
	}
	if len(verdictFiles) > 0 {
		sort.Strings(verdictFiles)
		// Prefer the plain {VERSION}_VERDICT.md when present, else the first.
		chosen := verdictFiles[0]
		for _, f := range verdictFiles {
			if strings.EqualFold(f, version+"_VERDICT.md") {
				chosen = f
				break
			}
		}
		if data, err := os.ReadFile(filepath.Join(h.logDir, chosen)); err == nil { //nolint:gosec // filename came from a directory listing
			resp.Verdict = string(data)
			resp.Files = append(resp.Files, chosen)
		}
		resp.VerdictFiles = verdictFiles
	}

	writeJSON(w, resp)
}

// listTrainingLog enumerates the version cells present in the training log.
func (h *TrainingHandler) listTrainingLog(w http.ResponseWriter) {
	entries, err := os.ReadDir(h.logDir)
	if err != nil {
		writeJSON(w, map[string]any{"entries": []trainingLogEntry{}})
		return
	}

	stems := make([]string, 0, len(entries))
	verdicts := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".md") {
			continue
		}
		stem := strings.TrimSuffix(e.Name(), filepath.Ext(e.Name()))
		if !isVersionStem(stem) {
			continue
		}
		if strings.HasSuffix(strings.ToLower(stem), "_verdict") {
			verdicts = append(verdicts, e.Name())
			continue
		}
		stems = append(stems, stem)
	}
	sort.Strings(stems)

	byVersion := make(map[string]*trainingLogEntry, len(stems))
	order := make([]string, 0, len(stems))
	for _, s := range stems {
		byVersion[s] = &trainingLogEntry{Version: s, HasPreRegistration: true}
		order = append(order, s)
	}

	// Attach each verdict to its longest matching pre-registration stem
	// (V255_B_VERDICT.md -> V255_B, not V255).
	for _, vf := range verdicts {
		stem := strings.TrimSuffix(vf, filepath.Ext(vf))
		best := ""
		for _, s := range stems {
			if strings.HasPrefix(strings.ToLower(stem), strings.ToLower(s)+"_") && len(s) > len(best) {
				best = s
			}
		}
		if best == "" {
			best = strings.TrimSuffix(stem, "_VERDICT")
			if _, ok := byVersion[best]; !ok {
				byVersion[best] = &trainingLogEntry{Version: best}
				order = append(order, best)
			}
		}
		byVersion[best].VerdictFiles = append(byVersion[best].VerdictFiles, vf)
	}

	sort.Strings(order)
	out := make([]trainingLogEntry, 0, len(order))
	for _, v := range order {
		out = append(out, *byVersion[v])
	}
	writeJSON(w, map[string]any{"entries": out})
}

// parseInt parses a string into an int, returning an error on failure.
func parseInt(s string) (int, error) {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("invalid int: %s", s)
		}
		n = n*10 + int(c-'0')
	}
	return n, nil
}

// ── String helpers ────────────────────────────────────────────────────────────

func trainingContains(s, substr string) bool {
	return strings.Contains(s, substr)
}

var _ = trainingContains // silence unused warning
