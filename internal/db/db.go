// Package db provides read-only access to the Omega SQLite state and memory databases.
// The Python node layer writes; this Go layer reads.
package db

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"time"

	_ "modernc.org/sqlite"
)

const (
	defaultStateDBPath  = "/tmp/omega_vectora_state.db"
	defaultMemoryDBPath = "/tmp/omega_vectora_memory.db"
	ChallengeDBPath     = "/tmp/omega_challenge_registry.db"
)

// StateDBPath returns the SQLite state DB path, honouring OMEGA_STATE_DB_PATH.
func StateDBPath() string {
	if p := os.Getenv("OMEGA_STATE_DB_PATH"); p != "" {
		return p
	}
	return defaultStateDBPath
}

// MemoryDBPath returns the SQLite memory DB path, honouring OMEGA_MEMORY_DB_PATH.
func MemoryDBPath() string {
	if p := os.Getenv("OMEGA_MEMORY_DB_PATH"); p != "" {
		return p
	}
	return defaultMemoryDBPath
}

// DB holds connections to both Omega SQLite databases.
type DB struct {
	state     *sql.DB
	memory    *sql.DB
	challenge *sql.DB // may be nil if challenge_registry.db doesn't exist yet
}

// New opens both databases in WAL mode for concurrent reads.
func New(stateDBPath, memoryDBPath string) (*DB, error) {
	state, err := openDB(stateDBPath)
	if err != nil {
		return nil, fmt.Errorf("open state db: %w", err)
	}
	memory, err := openDB(memoryDBPath)
	if err != nil {
		state.Close() //nolint:errcheck
		return nil, fmt.Errorf("open memory db: %w", err)
	}
	challengeDB, _ := openDB(ChallengeDBPath) // nil if file not yet created by Python
	d := &DB{state: state, memory: memory, challenge: challengeDB}
	if err := d.ensureBrainTables(); err != nil {
		state.Close()  //nolint:errcheck
		memory.Close() //nolint:errcheck
		if challengeDB != nil {
			challengeDB.Close() //nolint:errcheck
		}
		return nil, fmt.Errorf("ensure brain tables: %w", err)
	}
	return d, nil
}

func openDB(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite", path+"?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	return db, db.Ping()
}

func (d *DB) Close() {
	d.state.Close()  //nolint:errcheck
	d.memory.Close() //nolint:errcheck
	if d.challenge != nil {
		d.challenge.Close() //nolint:errcheck
	}
}

// ── Node types ──────────────────────────────────────────────────────────────

type Node struct {
	NodeID           string
	Name             string
	Version          string
	Capabilities     []string
	Health           float64
	Status           string
	RegisteredAt     float64
	LastUpdated      float64
	ExecutionsTotal  int64
	ErrorRate        float64
	AvgLatencyMS     float64
	P95LatencyMS     float64
	ImprovementCount int64
	LastExecution    *Execution
}

type Execution struct {
	ExecID     string
	NodeID     string
	NodeName   string
	TraceID    string
	SpanID     string
	Action     string
	StartedAt  float64
	EndedAt    *float64
	DurationMS *float64
	Success    bool
	ErrorText  string
	Metrics    map[string]float64
	Cycle      int64
}

type LatencyPoint struct {
	StartedAt  float64
	DurationMS float64
	Success    bool
}

// ── Trace types ─────────────────────────────────────────────────────────────

type TraceSummary struct {
	TraceID         string
	TraceStarted    float64
	TraceEnded      *float64
	TotalDurationMS float64
	SpanCount       int64
	ErrorSpans      int64
	Cycle           int64
}

type Span struct {
	SpanID       string
	TraceID      string
	ParentSpanID string
	NodeID       string
	NodeName     string
	Operation    string
	StartedAt    float64
	EndedAt      *float64
	DurationMS   *float64
	Status       string
	Cycle        int64
}

// ── Issue types ──────────────────────────────────────────────────────────────

type Issue struct {
	IssueID       string
	Detector      string
	Severity      string
	Description   string
	State         string
	OpenedAt      float64
	ResolvedAt    *float64
	CycleOpened   int64
	CycleResolved *int64
}

// ── Activity types ────────────────────────────────────────────────────────────

type ActivityEntry struct {
	LogID      string
	ActionType string
	EntityType string
	EntityID   string
	RecordedAt float64
	Cycle      int64
}

// ── Improvement types ─────────────────────────────────────────────────────────

type Improvement struct {
	ImproveID     string
	NodeID        string
	NodeName      string
	FromVersion   string
	ToVersion     string
	TriggeredBy   string
	RecordedAt    float64
	Cycle         int64
	BeforeMetrics map[string]float64
	AfterMetrics  map[string]float64
}

// ── Cost types ────────────────────────────────────────────────────────────────

type CostEntry struct {
	Provider     string
	NodeID       string
	Calls        int64
	TotalMS      float64
	TotalCostUSD float64
}

// ── Memory types ──────────────────────────────────────────────────────────────

type SemanticConcept struct {
	Concept       string
	Content       string
	Confidence    float64
	EvidenceCount int64
	Tags          []string
}

type EpisodeEntry struct {
	EpisodeID  string
	EventType  string
	Timestamp  float64
	Cycle      int64
	Importance float64
	Tags       []string
}

type ConvergencePoint struct {
	Cycle      int64
	Timestamp  float64
	Score      float64
	PipelineMS float64
}

// ── Health ────────────────────────────────────────────────────────────────────

type SystemHealth struct {
	Status         string
	CompositeScore float64
	AvgNodeHealth  float64
	NodeCount      int64
	OpenIssues     int64
	ErrorIssues    int64
	UptimeSeconds  float64
	TotalCycles    int64
}

// ── Brain config types ─────────────────────────────────────────────────────────

type BrainConfig struct {
	NodeID       string
	Provider     string
	Model        string
	Temperature  float64
	MaxTokens    int64
	SystemPrompt string
	ExtraConfig  map[string]string
	UpdatedAt    float64
}

type BrainExecutionEntry struct {
	ExecID           string
	NodeID           string
	Provider         string
	Model            string
	PromptTokens     int64
	CompletionTokens int64
	LatencyMS        float64
	Success          bool
	ErrorText        string
	ExecutedAt       float64
	Cycle            int64
}

// ── Brain config DB methods ────────────────────────────────────────────────────

func (d *DB) ensureBrainTables() error {
	_, err := d.state.Exec(`
		CREATE TABLE IF NOT EXISTS node_brain_config (
			node_id       TEXT PRIMARY KEY,
			provider      TEXT NOT NULL DEFAULT 'anthropic',
			model         TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
			temperature   REAL NOT NULL DEFAULT 0.7,
			max_tokens    INTEGER NOT NULL DEFAULT 4096,
			system_prompt TEXT NOT NULL DEFAULT '',
			extra_config  TEXT NOT NULL DEFAULT '{}',
			updated_at    REAL NOT NULL DEFAULT (unixepoch('now'))
		);
		CREATE TABLE IF NOT EXISTS brain_execution_log (
			exec_id           TEXT PRIMARY KEY,
			node_id           TEXT NOT NULL,
			provider          TEXT NOT NULL,
			model             TEXT NOT NULL,
			prompt_tokens     INTEGER NOT NULL DEFAULT 0,
			completion_tokens INTEGER NOT NULL DEFAULT 0,
			latency_ms        REAL NOT NULL DEFAULT 0,
			success           INTEGER NOT NULL DEFAULT 1,
			error_text        TEXT NOT NULL DEFAULT '',
			executed_at       REAL NOT NULL DEFAULT (unixepoch('now')),
			cycle             INTEGER NOT NULL DEFAULT 0
		);`)
	return err
}

func (d *DB) GetBrainConfig(nodeID string) (*BrainConfig, error) {
	row := d.state.QueryRow(`
		SELECT node_id, provider, model, temperature, max_tokens,
		       system_prompt, extra_config, updated_at
		FROM node_brain_config WHERE node_id = ?`, nodeID)
	c := &BrainConfig{}
	var extraJSON string
	err := row.Scan(&c.NodeID, &c.Provider, &c.Model, &c.Temperature,
		&c.MaxTokens, &c.SystemPrompt, &extraJSON, &c.UpdatedAt)
	if err == sql.ErrNoRows {
		return &BrainConfig{
			NodeID:      nodeID,
			Provider:    "anthropic",
			Model:       "claude-sonnet-4-6",
			Temperature: 0.7,
			MaxTokens:   4096,
		}, nil
	}
	if err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(extraJSON), &c.ExtraConfig) //nolint:errcheck
	return c, nil
}

func (d *DB) SetBrainConfig(c *BrainConfig) error {
	extraJSON, _ := json.Marshal(c.ExtraConfig)
	_, err := d.state.Exec(`
		INSERT INTO node_brain_config
			(node_id, provider, model, temperature, max_tokens, system_prompt, extra_config, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, unixepoch('now'))
		ON CONFLICT(node_id) DO UPDATE SET
			provider=excluded.provider, model=excluded.model,
			temperature=excluded.temperature, max_tokens=excluded.max_tokens,
			system_prompt=excluded.system_prompt, extra_config=excluded.extra_config,
			updated_at=excluded.updated_at`,
		c.NodeID, c.Provider, c.Model, c.Temperature,
		c.MaxTokens, c.SystemPrompt, string(extraJSON))
	return err
}

func (d *DB) GetBrainHistory(nodeID string, limit int) ([]*BrainExecutionEntry, error) {
	rows, err := d.state.Query(`
		SELECT exec_id, node_id, provider, model, prompt_tokens, completion_tokens,
		       latency_ms, success, error_text, executed_at, cycle
		FROM brain_execution_log WHERE node_id = ?
		ORDER BY executed_at DESC LIMIT ?`, nodeID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var entries []*BrainExecutionEntry
	for rows.Next() {
		e := &BrainExecutionEntry{}
		var success int
		if err := rows.Scan(&e.ExecID, &e.NodeID, &e.Provider, &e.Model,
			&e.PromptTokens, &e.CompletionTokens, &e.LatencyMS,
			&success, &e.ErrorText, &e.ExecutedAt, &e.Cycle); err != nil {
			return nil, err
		}
		e.Success = success == 1
		entries = append(entries, e)
	}
	return entries, nil
}

// ── Query methods ──────────────────────────────────────────────────────────────

func (d *DB) AllNodes() ([]*Node, error) {
	rows, err := d.state.Query(`
		SELECT node_id, name, version, capabilities_json, health, status,
		       registered_at, last_updated
		FROM nodes ORDER BY registered_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck

	var nodes []*Node
	for rows.Next() {
		n := &Node{}
		var capsJSON string
		if err := rows.Scan(&n.NodeID, &n.Name, &n.Version, &capsJSON,
			&n.Health, &n.Status, &n.RegisteredAt, &n.LastUpdated); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(capsJSON), &n.Capabilities) //nolint:errcheck
		nodes = append(nodes, n)
	}

	for _, n := range nodes {
		if err := d.enrichNode(n); err != nil {
			return nil, err
		}
	}
	return nodes, nil
}

func (d *DB) GetNode(nodeID string) (*Node, error) {
	row := d.state.QueryRow(`
		SELECT node_id, name, version, capabilities_json, health, status,
		       registered_at, last_updated
		FROM nodes WHERE node_id = ?`, nodeID)
	n := &Node{}
	var capsJSON string
	if err := row.Scan(&n.NodeID, &n.Name, &n.Version, &capsJSON,
		&n.Health, &n.Status, &n.RegisteredAt, &n.LastUpdated); err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(capsJSON), &n.Capabilities) //nolint:errcheck
	return n, d.enrichNode(n)
}

func (d *DB) enrichNode(n *Node) error {
	row := d.state.QueryRow(`
		SELECT COUNT(*),
		       SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),
		       AVG(duration_ms),
		       MAX(started_at)
		FROM node_executions WHERE node_id = ?`, n.NodeID)
	var total, failed int64
	var avgMS sql.NullFloat64
	var lastStarted sql.NullFloat64
	row.Scan(&total, &failed, &avgMS, &lastStarted) //nolint:errcheck

	n.ExecutionsTotal = total
	if total > 0 {
		n.ErrorRate = float64(failed) / float64(total)
	}
	if avgMS.Valid {
		n.AvgLatencyMS = avgMS.Float64
	}

	// p95 latency — two-query approach (SQLite rejects COUNT(*) inside OFFSET)
	var p95Count int64
	d.state.QueryRow(`SELECT COUNT(*) FROM node_executions WHERE node_id = ? AND duration_ms IS NOT NULL`, n.NodeID).Scan(&p95Count) //nolint:errcheck
	if p95Count > 0 {
		offset := int64(float64(p95Count) * 0.95)
		p95row := d.state.QueryRow(`
			SELECT duration_ms FROM node_executions
			WHERE node_id = ? AND duration_ms IS NOT NULL
			ORDER BY duration_ms
			LIMIT 1 OFFSET ?
		`, n.NodeID, offset)
		var p95 sql.NullFloat64
		p95row.Scan(&p95) //nolint:errcheck
		if p95.Valid {
			n.P95LatencyMS = p95.Float64
		}
	}

	row2 := d.state.QueryRow(
		`SELECT COUNT(*) FROM improvement_log WHERE node_id = ?`, n.NodeID)
	row2.Scan(&n.ImprovementCount) //nolint:errcheck

	lastExec, err := d.lastExecution(n.NodeID)
	if err == nil {
		n.LastExecution = lastExec
	}
	return nil
}

func (d *DB) lastExecution(nodeID string) (*Execution, error) {
	row := d.state.QueryRow(`
		SELECT exec_id, node_id, node_name, COALESCE(trace_id,''), COALESCE(span_id,''),
		       action, started_at, ended_at, duration_ms, success,
		       COALESCE(error_text,''), COALESCE(metrics_json,'{}'), cycle
		FROM node_executions WHERE node_id = ?
		ORDER BY started_at DESC LIMIT 1`, nodeID)
	return scanExecution(row)
}

func scanExecution(row *sql.Row) (*Execution, error) {
	e := &Execution{}
	var metricsJSON string
	var success int
	var endedAt, durationMS sql.NullFloat64
	err := row.Scan(&e.ExecID, &e.NodeID, &e.NodeName, &e.TraceID, &e.SpanID,
		&e.Action, &e.StartedAt, &endedAt, &durationMS, &success,
		&e.ErrorText, &metricsJSON, &e.Cycle)
	if err != nil {
		return nil, err
	}
	e.Success = success == 1
	if endedAt.Valid {
		v := endedAt.Float64
		e.EndedAt = &v
	}
	if durationMS.Valid {
		v := durationMS.Float64
		e.DurationMS = &v
	}
	json.Unmarshal([]byte(metricsJSON), &e.Metrics) //nolint:errcheck
	return e, nil
}

func (d *DB) GetExecutions(nodeID string, limit int) ([]*Execution, error) {
	query := `SELECT exec_id, node_id, node_name, COALESCE(trace_id,''), COALESCE(span_id,''),
		action, started_at, ended_at, duration_ms, success,
		COALESCE(error_text,''), COALESCE(metrics_json,'{}'), cycle
		FROM node_executions WHERE 1=1`
	args := []any{}
	if nodeID != "" {
		query += " AND node_id = ?"
		args = append(args, nodeID)
	}
	query += " ORDER BY started_at DESC LIMIT ?"
	args = append(args, limit)

	rows, err := d.state.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	return scanExecutions(rows)
}

func scanExecutions(rows *sql.Rows) ([]*Execution, error) {
	var result []*Execution
	for rows.Next() {
		e := &Execution{}
		var metricsJSON string
		var success int
		var endedAt, durationMS sql.NullFloat64
		if err := rows.Scan(&e.ExecID, &e.NodeID, &e.NodeName, &e.TraceID, &e.SpanID,
			&e.Action, &e.StartedAt, &endedAt, &durationMS, &success,
			&e.ErrorText, &metricsJSON, &e.Cycle); err != nil {
			return nil, err
		}
		e.Success = success == 1
		if endedAt.Valid {
			v := endedAt.Float64
			e.EndedAt = &v
		}
		if durationMS.Valid {
			v := durationMS.Float64
			e.DurationMS = &v
		}
		json.Unmarshal([]byte(metricsJSON), &e.Metrics) //nolint:errcheck
		result = append(result, e)
	}
	return result, nil
}

func (d *DB) LatencyHistory(nodeID string, limit int) ([]*LatencyPoint, error) {
	rows, err := d.state.Query(`
		SELECT started_at, duration_ms, success
		FROM node_executions
		WHERE node_id = ? AND duration_ms IS NOT NULL
		ORDER BY started_at DESC LIMIT ?`, nodeID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var points []*LatencyPoint
	for rows.Next() {
		p := &LatencyPoint{}
		var success int
		if err := rows.Scan(&p.StartedAt, &p.DurationMS, &success); err != nil {
			return nil, err
		}
		p.Success = success == 1
		points = append(points, p)
	}
	for i, j := 0, len(points)-1; i < j; i, j = i+1, j-1 {
		points[i], points[j] = points[j], points[i]
	}
	return points, nil
}

func (d *DB) RecentTraces(limit int) ([]*TraceSummary, error) {
	rows, err := d.state.Query(`
		SELECT trace_id,
		       MIN(started_at) as trace_started,
		       MAX(ended_at) as trace_ended,
		       (MAX(ended_at) - MIN(started_at)) * 1000 as total_duration_ms,
		       COUNT(*) as span_count,
		       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_spans,
		       MAX(cycle) as cycle
		FROM traces
		GROUP BY trace_id
		ORDER BY trace_started DESC
		LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var summaries []*TraceSummary
	for rows.Next() {
		t := &TraceSummary{}
		var traceEnded sql.NullFloat64
		if err := rows.Scan(&t.TraceID, &t.TraceStarted, &traceEnded,
			&t.TotalDurationMS, &t.SpanCount, &t.ErrorSpans, &t.Cycle); err != nil {
			return nil, err
		}
		if traceEnded.Valid {
			v := traceEnded.Float64
			t.TraceEnded = &v
		}
		summaries = append(summaries, t)
	}
	return summaries, nil
}

func (d *DB) GetTraceSpans(traceID string) ([]*Span, error) {
	rows, err := d.state.Query(`
		SELECT span_id, trace_id, COALESCE(parent_span_id,''),
		       COALESCE(node_id,''), COALESCE(node_name,''),
		       operation, started_at, ended_at, duration_ms, status, cycle
		FROM traces WHERE trace_id = ? ORDER BY started_at`, traceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var spans []*Span
	for rows.Next() {
		s := &Span{}
		var endedAt, durationMS sql.NullFloat64
		if err := rows.Scan(&s.SpanID, &s.TraceID, &s.ParentSpanID,
			&s.NodeID, &s.NodeName, &s.Operation,
			&s.StartedAt, &endedAt, &durationMS, &s.Status, &s.Cycle); err != nil {
			return nil, err
		}
		if endedAt.Valid {
			v := endedAt.Float64
			s.EndedAt = &v
		}
		if durationMS.Valid {
			v := durationMS.Float64
			s.DurationMS = &v
		}
		spans = append(spans, s)
	}
	return spans, nil
}

func (d *DB) GetIssues(stateFilter string) ([]*Issue, error) {
	query := `SELECT issue_id, detector, severity, description, state,
		opened_at, resolved_at, cycle_opened, cycle_resolved
		FROM issues WHERE 1=1`
	args := []any{}
	if stateFilter != "" && stateFilter != "all" {
		if stateFilter == "open" {
			query += " AND state != 'resolved'"
		} else {
			query += " AND state = ?"
			args = append(args, stateFilter)
		}
	}
	query += " ORDER BY opened_at DESC LIMIT 100"

	rows, err := d.state.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var issues []*Issue
	for rows.Next() {
		i := &Issue{}
		var resolvedAt sql.NullFloat64
		var cycleResolved sql.NullInt64
		if err := rows.Scan(&i.IssueID, &i.Detector, &i.Severity, &i.Description,
			&i.State, &i.OpenedAt, &resolvedAt, &i.CycleOpened, &cycleResolved); err != nil {
			return nil, err
		}
		if resolvedAt.Valid {
			v := resolvedAt.Float64
			i.ResolvedAt = &v
		}
		if cycleResolved.Valid {
			v := cycleResolved.Int64
			i.CycleResolved = &v
		}
		issues = append(issues, i)
	}
	return issues, nil
}

func (d *DB) RecentActivity(limit int) ([]*ActivityEntry, error) {
	rows, err := d.state.Query(`
		SELECT log_id, action_type, entity_type, entity_id, recorded_at, cycle
		FROM activity_log ORDER BY recorded_at DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var entries []*ActivityEntry
	for rows.Next() {
		e := &ActivityEntry{}
		if err := rows.Scan(&e.LogID, &e.ActionType, &e.EntityType,
			&e.EntityID, &e.RecordedAt, &e.Cycle); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, nil
}

func (d *DB) GetImprovements(nodeID string, limit int) ([]*Improvement, error) {
	query := `SELECT improve_id, node_id, node_name, from_version, to_version,
		triggered_by, recorded_at, cycle,
		COALESCE(before_metrics_json,'{}'), COALESCE(after_metrics_json,'{}')
		FROM improvement_log WHERE 1=1`
	args := []any{}
	if nodeID != "" {
		query += " AND node_id = ?"
		args = append(args, nodeID)
	}
	query += " ORDER BY recorded_at DESC LIMIT ?"
	args = append(args, limit)

	rows, err := d.state.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var imps []*Improvement
	for rows.Next() {
		imp := &Improvement{}
		var beforeJSON, afterJSON string
		if err := rows.Scan(&imp.ImproveID, &imp.NodeID, &imp.NodeName,
			&imp.FromVersion, &imp.ToVersion, &imp.TriggeredBy,
			&imp.RecordedAt, &imp.Cycle, &beforeJSON, &afterJSON); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(beforeJSON), &imp.BeforeMetrics) //nolint:errcheck
		json.Unmarshal([]byte(afterJSON), &imp.AfterMetrics)   //nolint:errcheck
		imps = append(imps, imp)
	}
	return imps, nil
}

func (d *DB) GetCosts() ([]*CostEntry, error) {
	rows, err := d.state.Query(`
		SELECT provider, node_id,
		       COUNT(*) as calls,
		       SUM(duration_ms) as total_ms,
		       SUM(estimated_cost_usd) as total_cost
		FROM cost_events GROUP BY provider, node_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var costs []*CostEntry
	for rows.Next() {
		c := &CostEntry{}
		if err := rows.Scan(&c.Provider, &c.NodeID, &c.Calls, &c.TotalMS, &c.TotalCostUSD); err != nil {
			return nil, err
		}
		costs = append(costs, c)
	}
	return costs, nil
}

func (d *DB) GetConvergence(limit int) ([]*ConvergencePoint, error) {
	rows, err := d.memory.Query(`
		SELECT cycle, timestamp, content_json
		FROM episodes WHERE event_type = 'cycle_summary'
		ORDER BY cycle ASC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var points []*ConvergencePoint
	for rows.Next() {
		p := &ConvergencePoint{}
		var contentJSON string
		if err := rows.Scan(&p.Cycle, &p.Timestamp, &contentJSON); err != nil {
			return nil, err
		}
		var content map[string]any
		if err := json.Unmarshal([]byte(contentJSON), &content); err == nil {
			if s, ok := content["score"].(float64); ok {
				p.Score = s
			}
			if ms, ok := content["pipeline_ms"].(float64); ok {
				p.PipelineMS = ms
			}
		}
		points = append(points, p)
	}
	return points, nil
}

func (d *DB) GetMemoryStats(namespace string) (int64, int64, []*SemanticConcept, []*EpisodeEntry, error) {
	var epCount, semCount int64

	query := "SELECT COUNT(*) FROM episodes"
	args := []any{}
	if namespace != "" {
		query += " WHERE namespace = ?"
		args = append(args, namespace)
	}
	d.memory.QueryRow(query, args...).Scan(&epCount) //nolint:errcheck

	semQuery := "SELECT COUNT(*) FROM semantic_memories"
	semArgs := []any{}
	if namespace != "" {
		semQuery += " WHERE namespace = ?"
		semArgs = append(semArgs, namespace)
	}
	d.memory.QueryRow(semQuery, semArgs...).Scan(&semCount) //nolint:errcheck

	semRowQuery := "SELECT concept, content, confidence, evidence_count, COALESCE(tags_json,'[]') FROM semantic_memories"
	if namespace != "" {
		semRowQuery += " WHERE namespace = ?"
	}
	semRowQuery += " ORDER BY confidence DESC LIMIT 20"
	semRows, err := d.memory.Query(semRowQuery, semArgs...)
	if err != nil {
		return epCount, semCount, nil, nil, err
	}
	defer semRows.Close() //nolint:errcheck
	var concepts []*SemanticConcept
	for semRows.Next() {
		c := &SemanticConcept{}
		var tagsJSON string
		if err := semRows.Scan(&c.Concept, &c.Content, &c.Confidence, &c.EvidenceCount, &tagsJSON); err != nil {
			return epCount, semCount, nil, nil, err
		}
		json.Unmarshal([]byte(tagsJSON), &c.Tags) //nolint:errcheck
		concepts = append(concepts, c)
	}

	epRowQuery := "SELECT episode_id, event_type, timestamp, cycle, importance, COALESCE(tags_json,'[]') FROM episodes"
	if namespace != "" {
		epRowQuery += " WHERE namespace = ?"
	}
	epRowQuery += " ORDER BY timestamp DESC LIMIT 20"
	epRows, err := d.memory.Query(epRowQuery, args...)
	if err != nil {
		return epCount, semCount, concepts, nil, err
	}
	defer epRows.Close() //nolint:errcheck
	var episodes []*EpisodeEntry
	for epRows.Next() {
		e := &EpisodeEntry{}
		var tagsJSON string
		if err := epRows.Scan(&e.EpisodeID, &e.EventType, &e.Timestamp, &e.Cycle, &e.Importance, &tagsJSON); err != nil {
			return epCount, semCount, concepts, nil, err
		}
		json.Unmarshal([]byte(tagsJSON), &e.Tags) //nolint:errcheck
		episodes = append(episodes, e)
	}

	return epCount, semCount, concepts, episodes, nil
}

func (d *DB) SystemHealth() (*SystemHealth, error) {
	nodes, err := d.AllNodes()
	if err != nil {
		return nil, err
	}

	if len(nodes) == 0 {
		return &SystemHealth{Status: "no_nodes"}, nil
	}

	var totalHealth float64
	var minHealth = 1.0
	for _, n := range nodes {
		totalHealth += n.Health
		if n.Health < minHealth {
			minHealth = n.Health
		}
	}
	avgHealth := totalHealth / float64(len(nodes))

	issues, _ := d.GetIssues("open")
	openCount := int64(len(issues))
	var errorIssues int64
	for _, i := range issues {
		if i.Severity == "error" {
			errorIssues++
		}
	}

	issuePenalty := float64(errorIssues) * 0.1
	if issuePenalty > 0.3 {
		issuePenalty = 0.3
	}
	composite := avgHealth - issuePenalty
	if composite < 0 {
		composite = 0
	}

	status := "healthy"
	if composite < 0.6 {
		status = "critical"
	} else if composite < 0.8 {
		status = "degraded"
	}

	minRegAt := float64(time.Now().Unix())
	for _, n := range nodes {
		if n.RegisteredAt < minRegAt && n.RegisteredAt > 0 {
			minRegAt = n.RegisteredAt
		}
	}
	uptime := float64(time.Now().Unix()) - minRegAt

	var totalCycles int64
	d.state.QueryRow("SELECT COALESCE(MAX(cycle), 0) FROM node_executions").Scan(&totalCycles) //nolint:errcheck

	return &SystemHealth{
		Status:         status,
		CompositeScore: round3(composite),
		AvgNodeHealth:  round3(avgHealth),
		NodeCount:      int64(len(nodes)),
		OpenIssues:     openCount,
		ErrorIssues:    errorIssues,
		UptimeSeconds:  uptime,
		TotalCycles:    totalCycles,
	}, nil
}

func round3(f float64) float64 {
	return float64(int(f*1000+0.5)) / 1000
}
