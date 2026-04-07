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
	"strings"
	"time"

	"github.com/benebsworth/omega/internal/db"
)

// TrainingHandler serves training-progress REST endpoints.
type TrainingHandler struct {
	db          *db.DB
	progressDir string // directory containing training_progress.json
}

// NewTrainingHandler creates a TrainingHandler.
// progressDir is the directory to search for training_progress.json (defaults to "data").
func NewTrainingHandler(database *db.DB, progressDir string) *TrainingHandler {
	if progressDir == "" {
		progressDir = "data"
	}
	return &TrainingHandler{db: database, progressDir: progressDir}
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
}

// ── JSON types ────────────────────────────────────────────────────────────────

type trainingProgress struct {
	RunID           string                    `json:"run_id"`
	TotalCycles     int                       `json:"total_cycles"`
	CurrentCycle    int                       `json:"current_cycle"`
	StartedAt       string                    `json:"started_at"`
	Status          string                    `json:"status"`
	PnLHistory      []trainingCyclePnL        `json:"pnl_history"`
	WinRateHistory  []trainingCycleWinRate    `json:"win_rate_history"`
	MemoryGrowth    []trainingMemoryPoint     `json:"memory_growth"`
	SignalConviction []trainingSignalConviction `json:"signal_conviction"`
	ActivityLog     []trainingActivity        `json:"activity_log"`
	CurrentRegime   trainingRegime            `json:"current_regime"`
	Config          trainingConfig            `json:"config"`
	Snapshots       []trainingSnapshot        `json:"snapshots"`
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
	Type    string `json:"type"`  // "trade" | "signal" | "memory"
	Message string `json:"message"`
}

type trainingRegime struct {
	Name          string  `json:"name"`
	Confidence    float64 `json:"confidence"`
	DominantSignal string `json:"dominant_signal"`
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
	TotalTrades     int                       `json:"total_trades"`
	WinRate         float64                   `json:"win_rate"`
	TotalPnL        float64                   `json:"total_pnl"`
	RealisedPnL     float64                   `json:"realised_pnl"`
	UnrealisedPnL   float64                   `json:"unrealised_pnl"`
	MemoryCount     trainingMemoryCount       `json:"memory_count"`
	SymbolBreakdown []trainingSymbolStats     `json:"symbol_breakdown"`
	RecentTrades    []trainingRecentTrade     `json:"recent_trades"`
	SignalHealth    []trainingSignalConviction `json:"signal_health"`
	CurrentCycle    int                       `json:"current_cycle"`
	TotalCycles     int                       `json:"total_cycles"`
	Status          string                    `json:"status"`
}

type trainingMemoryCount struct {
	Episodic int `json:"episodic"`
	Semantic int `json:"semantic"`
	Total    int `json:"total"`
}

type trainingSymbolStats struct {
	Symbol     string  `json:"symbol"`
	Trades     int     `json:"trades"`
	WinRate    float64 `json:"win_rate"`
	TotalPnL   float64 `json:"total_pnl"`
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

// handleProgress reads training_progress.json and returns it as-is.
func (h *TrainingHandler) handleProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	path := filepath.Join(h.progressDir, "training_progress.json")
	data, err := os.ReadFile(path) //nolint:gosec
	if err != nil {
		if os.IsNotExist(err) {
			// Return empty/default progress when no training run has started.
			writeJSON(w, trainingProgress{
				RunID:        "",
				TotalCycles:  0,
				CurrentCycle: 0,
				Status:       "idle",
				Snapshots:    []trainingSnapshot{},
			})
			return
		}
		http.Error(w, "failed to read progress file", http.StatusInternalServerError)
		return
	}

	var progress trainingProgress
	if err := json.Unmarshal(data, &progress); err != nil {
		http.Error(w, "failed to parse progress file", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(data)
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

	// Read progress file for cycle info and status.
	path := filepath.Join(h.progressDir, "training_progress.json")
	if data, err := os.ReadFile(path); err == nil { //nolint:gosec
		var p trainingProgress
		if json.Unmarshal(data, &p) == nil {
			metrics.CurrentCycle = p.CurrentCycle
			metrics.TotalCycles = p.TotalCycles
			metrics.Status = p.Status
			metrics.SignalHealth = p.SignalConviction
		}
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
	_ = sqlDB.QueryRowContext(ctx, `SELECT COUNT(*) FROM victoria_episodes`).Scan(&episodic)         //nolint:gosec
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
			// Read current progress.
			path := filepath.Join(h.progressDir, "training_progress.json")
			data, err := os.ReadFile(path) //nolint:gosec
			if err != nil {
				continue
			}
			var p trainingProgress
			if json.Unmarshal(data, &p) != nil {
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

	path := filepath.Join(h.progressDir, "training_progress.json")
	data, err := os.ReadFile(path) //nolint:gosec
	if err != nil {
		http.Error(w, "no active training run", http.StatusNotFound)
		return
	}

	var p trainingProgress
	if err := json.Unmarshal(data, &p); err != nil {
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

	// Append snapshot and persist.
	p.Snapshots = append(p.Snapshots, snap)
	updated, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		http.Error(w, "failed to marshal progress", http.StatusInternalServerError)
		return
	}
	if err := os.WriteFile(path, updated, 0600); err != nil { //nolint:gosec
		http.Error(w, "failed to write progress", http.StatusInternalServerError)
		return
	}

	writeJSON(w, snap)
}

// handleListSnapshots returns all snapshots from the progress file.
func (h *TrainingHandler) handleListSnapshots(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	path := filepath.Join(h.progressDir, "training_progress.json")
	data, err := os.ReadFile(path) //nolint:gosec
	if err != nil {
		writeJSON(w, []trainingSnapshot{})
		return
	}

	var p struct {
		Snapshots []trainingSnapshot `json:"snapshots"`
	}
	if err := json.Unmarshal(data, &p); err != nil {
		writeJSON(w, []trainingSnapshot{})
		return
	}

	snaps := p.Snapshots
	if snaps == nil {
		snaps = []trainingSnapshot{}
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

	var rows []json.RawMessage
	for _, line := range bytes.Split(bytes.TrimSpace(data), []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		if !json.Valid(line) {
			continue
		}
		rows = append(rows, json.RawMessage(line))
	}
	if rows == nil {
		rows = []json.RawMessage{}
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
							for _, line := range bytes.Split(buf[:n], []byte("\n")) {
								line = bytes.TrimSpace(line)
								if len(line) == 0 {
									continue
								}
								if !json.Valid(line) {
									continue
								}
								fmt.Fprintf(w, "data: %s\n\n", line) //nolint:errcheck
							}
							flusher.Flush()
						}
					}
				}
				f.Close() //nolint:errcheck
			}

			// Check if the training run has finished (results file present).
			if _, err := os.Stat(resultsPath); err == nil {
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

// ── String helpers ────────────────────────────────────────────────────────────

func trainingContains(s, substr string) bool {
	return strings.Contains(s, substr)
}

var _ = trainingContains // silence unused warning
