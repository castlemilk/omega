// Package db provides read/write access to the Omega PostgreSQL database.
// A single pgxpool-backed *sql.DB serves all tables (state, memory, challenges,
// Victoria trading state). LISTEN/NOTIFY is handled via a raw pgxpool.Pool.
package db

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/jackc/pgx/v5/stdlib"
)

// DatabaseURL returns the Postgres DSN.
// Reads DATABASE_URL; defaults to a local dev DSN.
func DatabaseURL() string {
	if u := os.Getenv("DATABASE_URL"); u != "" {
		return u
	}
	return "postgres://omega:omega@localhost:5432/omega?sslmode=disable"
}

// DB holds a connection pool to the Omega PostgreSQL database.
type DB struct {
	db   *sql.DB        // database/sql facade over pgxpool (all tables)
	pool *pgxpool.Pool  // raw pool for LISTEN/NOTIFY
}

// StateDB returns the underlying *sql.DB (backwards compat with health checkers).
func (d *DB) StateDB() *sql.DB { return d.db }

// MemoryDB returns the underlying *sql.DB (same pool — all tables coexist).
func (d *DB) MemoryDB() *sql.DB { return d.db }

// New opens (and bootstraps) the Omega PostgreSQL database.
func New(ctx context.Context) (*DB, error) {
	dsn := DatabaseURL()

	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, fmt.Errorf("pgxpool.New: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres ping: %w", err)
	}

	sqlDB := stdlib.OpenDBFromPool(pool)

	d := &DB{db: sqlDB, pool: pool}
	if err := d.ensureSchema(ctx); err != nil {
		sqlDB.Close() //nolint:errcheck,gosec
		pool.Close()
		return nil, fmt.Errorf("ensure schema: %w", err)
	}
	return d, nil
}

func (d *DB) Close() {
	d.db.Close()  //nolint:errcheck,gosec
	d.pool.Close()
}

// ── LISTEN/NOTIFY ─────────────────────────────────────────────────────────────

// Omega coordination pub/sub channels.
const (
	ChannelNodeStateChanged      = "omega_node_state_changed"
	ChannelCycleCompleted        = "omega_cycle_completed"
	ChannelImprovementTriggered  = "omega_improvement_triggered"
	ChannelIssueDetected         = "omega_issue_detected"
)

// Notify sends a NOTIFY on the given channel with the JSON-encoded payload.
func (d *DB) Notify(ctx context.Context, channel string, payload any) error {
	b, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal payload: %w", err)
	}
	conn, err := d.pool.Acquire(ctx)
	if err != nil {
		return fmt.Errorf("acquire conn: %w", err)
	}
	defer conn.Release()
	_, err = conn.Exec(ctx, "SELECT pg_notify($1, $2)", channel, string(b))
	return err
}

// Listen blocks and calls handler for each NOTIFY received on channel.
// Returns when ctx is cancelled. Reconnects on transient errors.
func (d *DB) Listen(ctx context.Context, channel string, handler func(payload string)) error {
	conn, err := d.pool.Acquire(ctx)
	if err != nil {
		return fmt.Errorf("acquire conn for listen: %w", err)
	}
	defer conn.Release()

	if _, err := conn.Exec(ctx, "LISTEN "+channel); err != nil {
		return fmt.Errorf("LISTEN %s: %w", channel, err)
	}
	for {
		n, err := conn.Conn().WaitForNotification(ctx)
		if err != nil {
			return err // ctx cancelled or connection lost
		}
		handler(n.Payload)
	}
}

// ── Schema bootstrap ──────────────────────────────────────────────────────────

var stateSchema = []string{
	`CREATE TABLE IF NOT EXISTS nodes (
		node_id           TEXT PRIMARY KEY,
		name              TEXT NOT NULL,
		version           TEXT NOT NULL DEFAULT '1.0',
		capabilities      JSONB NOT NULL DEFAULT '[]',
		health            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
		status            TEXT NOT NULL DEFAULT 'active',
		brain_config      JSONB NOT NULL DEFAULT '{"provider":"none"}',
		registered_at     DOUBLE PRECISION NOT NULL,
		last_updated      DOUBLE PRECISION NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS node_executions (
		exec_id      TEXT PRIMARY KEY,
		node_id      TEXT NOT NULL,
		node_name    TEXT NOT NULL,
		trace_id     TEXT,
		span_id      TEXT,
		action       TEXT NOT NULL,
		started_at   DOUBLE PRECISION NOT NULL,
		ended_at     DOUBLE PRECISION,
		duration_ms  DOUBLE PRECISION,
		success      BOOLEAN NOT NULL DEFAULT TRUE,
		error_text   TEXT,
		metrics      JSONB NOT NULL DEFAULT '{}',
		cycle        BIGINT NOT NULL DEFAULT 0,
		error_class  INTEGER NOT NULL DEFAULT 0,
		error_code   TEXT NOT NULL DEFAULT '',
		is_retryable BOOLEAN NOT NULL DEFAULT FALSE
	)`,
	`CREATE TABLE IF NOT EXISTS traces (
		span_id        TEXT PRIMARY KEY,
		trace_id       TEXT NOT NULL,
		parent_span_id TEXT,
		node_id        TEXT,
		node_name      TEXT,
		operation      TEXT NOT NULL,
		started_at     DOUBLE PRECISION NOT NULL,
		ended_at       DOUBLE PRECISION,
		duration_ms    DOUBLE PRECISION,
		status         TEXT NOT NULL DEFAULT 'ok',
		metadata       JSONB NOT NULL DEFAULT '{}',
		cycle          BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS cost_events (
		cost_id            TEXT PRIMARY KEY,
		node_id            TEXT NOT NULL,
		exec_id            TEXT,
		provider           TEXT NOT NULL,
		call_type          TEXT NOT NULL,
		duration_ms        DOUBLE PRECISION NOT NULL DEFAULT 0,
		estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		metadata           JSONB NOT NULL DEFAULT '{}',
		recorded_at        DOUBLE PRECISION NOT NULL,
		cycle              BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS issues (
		issue_id       TEXT PRIMARY KEY,
		detector       TEXT NOT NULL,
		severity       TEXT NOT NULL DEFAULT 'warning',
		description    TEXT NOT NULL,
		context        JSONB NOT NULL DEFAULT '{}',
		state          TEXT NOT NULL DEFAULT 'pending',
		opened_at      DOUBLE PRECISION NOT NULL,
		resolved_at    DOUBLE PRECISION,
		cycle_opened   BIGINT NOT NULL DEFAULT 0,
		cycle_resolved BIGINT
	)`,
	`CREATE TABLE IF NOT EXISTS activity_log (
		log_id      TEXT PRIMARY KEY,
		action_type TEXT NOT NULL,
		entity_type TEXT NOT NULL,
		entity_id   TEXT NOT NULL,
		data        JSONB NOT NULL DEFAULT '{}',
		recorded_at DOUBLE PRECISION NOT NULL,
		cycle       BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS improvement_log (
		improve_id          TEXT PRIMARY KEY,
		node_id             TEXT NOT NULL,
		node_name           TEXT NOT NULL,
		from_version        TEXT NOT NULL,
		to_version          TEXT NOT NULL,
		before_metrics      JSONB NOT NULL DEFAULT '{}',
		after_metrics       JSONB NOT NULL DEFAULT '{}',
		triggered_by        TEXT NOT NULL DEFAULT 'metrics',
		recorded_at         DOUBLE PRECISION NOT NULL,
		cycle               BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS config_revisions (
		revision_id TEXT PRIMARY KEY,
		node_id     TEXT NOT NULL,
		version     TEXT NOT NULL,
		config      JSONB NOT NULL DEFAULT '{}',
		recorded_at DOUBLE PRECISION NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS brain_executions (
		brain_exec_id  TEXT PRIMARY KEY,
		node_id        TEXT NOT NULL,
		node_name      TEXT NOT NULL,
		provider       TEXT NOT NULL DEFAULT 'none',
		model          TEXT NOT NULL DEFAULT '',
		operation      TEXT NOT NULL,
		action_decided TEXT NOT NULL,
		parameters     JSONB NOT NULL DEFAULT '{}',
		reasoning      TEXT NOT NULL DEFAULT '',
		confidence     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		outcome        TEXT NOT NULL DEFAULT 'pending',
		latency_ms     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		trace_id       TEXT NOT NULL DEFAULT '',
		recorded_at    DOUBLE PRECISION NOT NULL,
		cycle          BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS alignment_decisions (
		decision_id      TEXT PRIMARY KEY,
		cycle            BIGINT NOT NULL DEFAULT 0,
		approved         BOOLEAN NOT NULL DEFAULT TRUE,
		violations       JSONB NOT NULL DEFAULT '[]',
		pareto_ranks     JSONB NOT NULL DEFAULT '{}',
		adjustments      JSONB NOT NULL DEFAULT '{}',
		vcg_payments     JSONB NOT NULL DEFAULT '{}',
		goodhart_warning BOOLEAN NOT NULL DEFAULT FALSE,
		recorded_at      DOUBLE PRECISION NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS adversarial_results (
		result_id        TEXT PRIMARY KEY,
		cycle            BIGINT NOT NULL DEFAULT 0,
		ring             INTEGER NOT NULL DEFAULT 1,
		flagged          BOOLEAN NOT NULL DEFAULT FALSE,
		max_disagreement DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		scenario_count   BIGINT NOT NULL DEFAULT 0,
		failure_cases    JSONB NOT NULL DEFAULT '[]',
		details          JSONB NOT NULL DEFAULT '{}',
		recorded_at      DOUBLE PRECISION NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS goal_tracking (
		tracking_id    TEXT PRIMARY KEY,
		cycle          BIGINT NOT NULL DEFAULT 0,
		approved       BOOLEAN NOT NULL DEFAULT TRUE,
		composite_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		scorecard       JSONB NOT NULL DEFAULT '{}',
		nash_weights    JSONB NOT NULL DEFAULT '{}',
		tracking_error  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
		control_action  JSONB NOT NULL DEFAULT '{}',
		subtasks        JSONB NOT NULL DEFAULT '[]',
		violations      JSONB NOT NULL DEFAULT '[]',
		recorded_at     DOUBLE PRECISION NOT NULL
	)`,
	`CREATE TABLE IF NOT EXISTS terminal_sessions (
		id             TEXT PRIMARY KEY,
		work_dir       TEXT NOT NULL DEFAULT '',
		autonomy_level TEXT NOT NULL DEFAULT 'pico',
		status         TEXT NOT NULL DEFAULT 'active',
		created_at     DOUBLE PRECISION NOT NULL,
		closed_at      DOUBLE PRECISION
	)`,
	`CREATE TABLE IF NOT EXISTS terminal_commands (
		id          TEXT PRIMARY KEY,
		session_id  TEXT NOT NULL REFERENCES terminal_sessions(id),
		command     TEXT NOT NULL,
		args        JSONB NOT NULL DEFAULT '[]',
		exit_code   INTEGER NOT NULL DEFAULT 0,
		stdout      TEXT NOT NULL DEFAULT '',
		stderr      TEXT NOT NULL DEFAULT '',
		duration_ms BIGINT NOT NULL DEFAULT 0,
		truncated   BOOLEAN NOT NULL DEFAULT FALSE,
		executed_at DOUBLE PRECISION NOT NULL
	)`,
	`CREATE INDEX IF NOT EXISTS idx_terminal_commands_session ON terminal_commands(session_id)`,
	`CREATE TABLE IF NOT EXISTS node_brain_config (
		node_id       TEXT PRIMARY KEY,
		provider      TEXT NOT NULL DEFAULT 'anthropic',
		model         TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
		temperature   DOUBLE PRECISION NOT NULL DEFAULT 0.7,
		max_tokens    BIGINT NOT NULL DEFAULT 4096,
		system_prompt TEXT NOT NULL DEFAULT '',
		extra_config  JSONB NOT NULL DEFAULT '{}',
		updated_at    DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS brain_execution_log (
		exec_id           TEXT PRIMARY KEY,
		node_id           TEXT NOT NULL,
		provider          TEXT NOT NULL,
		model             TEXT NOT NULL,
		prompt_tokens     BIGINT NOT NULL DEFAULT 0,
		completion_tokens BIGINT NOT NULL DEFAULT 0,
		latency_ms        DOUBLE PRECISION NOT NULL DEFAULT 0,
		success           BOOLEAN NOT NULL DEFAULT TRUE,
		error_text        TEXT NOT NULL DEFAULT '',
		executed_at       DOUBLE PRECISION NOT NULL DEFAULT 0,
		cycle             BIGINT NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS verification_gates (
		gate_id    TEXT PRIMARY KEY,
		cycle      BIGINT NOT NULL DEFAULT 0,
		gate_name  TEXT NOT NULL,
		result     TEXT NOT NULL DEFAULT 'pass',
		details    TEXT NOT NULL DEFAULT '',
		checked_at DOUBLE PRECISION NOT NULL
	)`,
	// ── Memory tables (previously in a separate memory.db) ─────────────────────
	`CREATE TABLE IF NOT EXISTS episodes (
		episode_id   TEXT PRIMARY KEY,
		timestamp    DOUBLE PRECISION NOT NULL,
		cycle        BIGINT NOT NULL,
		event_type   TEXT NOT NULL,
		content      JSONB NOT NULL DEFAULT '{}',
		tags         JSONB NOT NULL DEFAULT '[]',
		importance   DOUBLE PRECISION NOT NULL DEFAULT 1.0,
		namespace    TEXT NOT NULL DEFAULT 'global'
	)`,
	`CREATE INDEX IF NOT EXISTS idx_episodes_event_type ON episodes(event_type)`,
	`CREATE INDEX IF NOT EXISTS idx_episodes_cycle ON episodes(cycle)`,
	`CREATE INDEX IF NOT EXISTS idx_episodes_namespace ON episodes(namespace)`,
	`CREATE TABLE IF NOT EXISTS semantic_memories (
		memory_id       TEXT PRIMARY KEY,
		concept         TEXT NOT NULL,
		content         TEXT NOT NULL,
		confidence      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
		evidence_count  INTEGER NOT NULL DEFAULT 1,
		last_reinforced DOUBLE PRECISION NOT NULL,
		tags            JSONB NOT NULL DEFAULT '[]',
		namespace       TEXT NOT NULL DEFAULT 'global'
	)`,
	`CREATE INDEX IF NOT EXISTS idx_semantic_concept ON semantic_memories(concept)`,
	`CREATE INDEX IF NOT EXISTS idx_semantic_namespace ON semantic_memories(namespace)`,
	`CREATE TABLE IF NOT EXISTS memory_ratings (
		rating_id TEXT PRIMARY KEY,
		memory_id TEXT NOT NULL,
		namespace TEXT NOT NULL DEFAULT 'global',
		quality   DOUBLE PRECISION NOT NULL,
		rated_at  DOUBLE PRECISION NOT NULL
	)`,
	// ── Challenge / devil's advocate tables ────────────────────────────────────
	`CREATE TABLE IF NOT EXISTS challenges (
		challenge_id      TEXT PRIMARY KEY,
		target_subsystem  TEXT NOT NULL DEFAULT '',
		severity          TEXT NOT NULL DEFAULT 'medium',
		description       TEXT NOT NULL DEFAULT '',
		evidence          TEXT NOT NULL DEFAULT '',
		status            TEXT NOT NULL DEFAULT 'open',
		resolution_notes  TEXT NOT NULL DEFAULT '',
		created_at        DOUBLE PRECISION NOT NULL,
		updated_at        DOUBLE PRECISION NOT NULL
	)`,
	// ── Victoria trading state tables (written by Python, read by Go) ──────────
	`CREATE TABLE IF NOT EXISTS victoria_portfolio (
		id              BIGSERIAL PRIMARY KEY,
		portfolio_value DOUBLE PRECISION NOT NULL DEFAULT 0,
		unrealised_pnl  DOUBLE PRECISION NOT NULL DEFAULT 0,
		realised_pnl    DOUBLE PRECISION NOT NULL DEFAULT 0,
		total_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0,
		total_return    DOUBLE PRECISION NOT NULL DEFAULT 0,
		ann_return      DOUBLE PRECISION NOT NULL DEFAULT 0,
		win_rate        DOUBLE PRECISION NOT NULL DEFAULT 0,
		profit_factor   DOUBLE PRECISION NOT NULL DEFAULT 0,
		sharpe          DOUBLE PRECISION NOT NULL DEFAULT 0,
		ann_vol         DOUBLE PRECISION NOT NULL DEFAULT 0,
		allocation      JSONB NOT NULL DEFAULT '[]',
		updated_at      DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_positions (
		sym      TEXT PRIMARY KEY,
		side     TEXT NOT NULL DEFAULT '',
		size     DOUBLE PRECISION NOT NULL DEFAULT 0,
		entry    DOUBLE PRECISION NOT NULL DEFAULT 0,
		mark     DOUBLE PRECISION NOT NULL DEFAULT 0,
		upnl     DOUBLE PRECISION NOT NULL DEFAULT 0,
		pct      DOUBLE PRECISION NOT NULL DEFAULT 0,
		notional DOUBLE PRECISION NOT NULL DEFAULT 0,
		leverage DOUBLE PRECISION NOT NULL DEFAULT 0,
		var95    DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_pnl (
		id             BIGSERIAL PRIMARY KEY,
		unrealised_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
		realised_pnl   DOUBLE PRECISION NOT NULL DEFAULT 0,
		total_pnl      DOUBLE PRECISION NOT NULL DEFAULT 0,
		total_return   DOUBLE PRECISION NOT NULL DEFAULT 0,
		ann_return     DOUBLE PRECISION NOT NULL DEFAULT 0,
		win_rate       DOUBLE PRECISION NOT NULL DEFAULT 0,
		profit_factor  DOUBLE PRECISION NOT NULL DEFAULT 0,
		sharpe         DOUBLE PRECISION NOT NULL DEFAULT 0,
		ann_vol        DOUBLE PRECISION NOT NULL DEFAULT 0,
		max_dd         DOUBLE PRECISION NOT NULL DEFAULT 0,
		var95          DOUBLE PRECISION NOT NULL DEFAULT 0,
		cvar95         DOUBLE PRECISION NOT NULL DEFAULT 0,
		sortino        DOUBLE PRECISION NOT NULL DEFAULT 0,
		calmar         DOUBLE PRECISION NOT NULL DEFAULT 0,
		updated_at     DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_signals (
		name          TEXT PRIMARY KEY,
		avg_ic        DOUBLE PRECISION NOT NULL DEFAULT 0,
		weight        DOUBLE PRECISION NOT NULL DEFAULT 0,
		half_life     INTEGER NOT NULL DEFAULT 0,
		color         TEXT NOT NULL DEFAULT '',
		conviction    DOUBLE PRECISION NOT NULL DEFAULT 0,
		brier_score   DOUBLE PRECISION NOT NULL DEFAULT 0,
		current_value DOUBLE PRECISION NOT NULL DEFAULT 0,
		trend         TEXT NOT NULL DEFAULT ''
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_signal_history (
		id          BIGSERIAL PRIMARY KEY,
		signal_name TEXT NOT NULL,
		t           INTEGER NOT NULL,
		ic          DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE INDEX IF NOT EXISTS idx_victoria_signal_history_name ON victoria_signal_history(signal_name)`,
	`CREATE TABLE IF NOT EXISTS victoria_trades (
		id          BIGSERIAL PRIMARY KEY,
		ts          TEXT NOT NULL DEFAULT '',
		sym         TEXT NOT NULL DEFAULT '',
		side        TEXT NOT NULL DEFAULT '',
		size        DOUBLE PRECISION NOT NULL DEFAULT 0,
		entry       DOUBLE PRECISION NOT NULL DEFAULT 0,
		exit_price  DOUBLE PRECISION NOT NULL DEFAULT 0,
		pnl         DOUBLE PRECISION NOT NULL DEFAULT 0,
		slippage    DOUBLE PRECISION NOT NULL DEFAULT 0,
		duration    TEXT NOT NULL DEFAULT '',
		recorded_at DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_backtest (
		id             BIGSERIAL PRIMARY KEY,
		sharpe_ann     DOUBLE PRECISION NOT NULL DEFAULT 0,
		sortino_ann    DOUBLE PRECISION NOT NULL DEFAULT 0,
		max_dd_pct     DOUBLE PRECISION NOT NULL DEFAULT 0,
		calmar         DOUBLE PRECISION NOT NULL DEFAULT 0,
		sharpe_is      DOUBLE PRECISION NOT NULL DEFAULT 0,
		sharpe_oos     DOUBLE PRECISION NOT NULL DEFAULT 0,
		var            DOUBLE PRECISION NOT NULL DEFAULT 0,
		cvar           DOUBLE PRECISION NOT NULL DEFAULT 0,
		mean_r         DOUBLE PRECISION NOT NULL DEFAULT 0,
		std_r          DOUBLE PRECISION NOT NULL DEFAULT 0,
		ann_return     DOUBLE PRECISION NOT NULL DEFAULT 0,
		total_return   DOUBLE PRECISION NOT NULL DEFAULT 0,
		portfolio_value DOUBLE PRECISION NOT NULL DEFAULT 0,
		max_dd_duration INTEGER NOT NULL DEFAULT 0,
		win_rate       DOUBLE PRECISION NOT NULL DEFAULT 0,
		profit_factor  DOUBLE PRECISION NOT NULL DEFAULT 0,
		train_end      INTEGER NOT NULL DEFAULT 0,
		updated_at     DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_equity_curve (
		id        BIGSERIAL PRIMARY KEY,
		date      TEXT NOT NULL DEFAULT '',
		i         INTEGER NOT NULL DEFAULT 0,
		omega     DOUBLE PRECISION NOT NULL DEFAULT 0,
		btc       DOUBLE PRECISION NOT NULL DEFAULT 0,
		dd        DOUBLE PRECISION NOT NULL DEFAULT 0,
		train_end INTEGER NOT NULL DEFAULT 0
	)`,
	`CREATE TABLE IF NOT EXISTS victoria_risk_metrics (
		id                BIGSERIAL PRIMARY KEY,
		ablation          JSONB NOT NULL DEFAULT '[]',
		regimes           JSONB NOT NULL DEFAULT '[]',
		current_regime_idx INTEGER NOT NULL DEFAULT 0,
		crashes           JSONB NOT NULL DEFAULT '[]',
		funding           JSONB NOT NULL DEFAULT '[]',
		adv_series        JSONB NOT NULL DEFAULT '[]',
		tpe_series        JSONB NOT NULL DEFAULT '[]',
		updated_at        DOUBLE PRECISION NOT NULL DEFAULT 0
	)`,
}

func (d *DB) ensureSchema(ctx context.Context) error {
	for _, stmt := range stateSchema {
		if _, err := d.db.ExecContext(ctx, stmt); err != nil {
			return fmt.Errorf("schema stmt failed: %w\nSQL: %s", err, stmt)
		}
	}
	return nil
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
	ExecID      string
	NodeID      string
	NodeName    string
	TraceID     string
	SpanID      string
	Action      string
	StartedAt   float64
	EndedAt     *float64
	DurationMS  *float64
	Success     bool
	ErrorText   string
	Metrics     map[string]float64
	Cycle       int64
	ErrorClass  int32
	ErrorCode   string
	IsRetryable bool
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

// ── Brain config DB methods ─────────────────────────────────────────────────

func (d *DB) GetBrainConfig(nodeID string) (*BrainConfig, error) {
	row := d.db.QueryRow(`
		SELECT node_id, provider, model, temperature, max_tokens,
		       system_prompt, extra_config, updated_at
		FROM node_brain_config WHERE node_id = $1`, nodeID)
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
	json.Unmarshal([]byte(extraJSON), &c.ExtraConfig) //nolint:errcheck,gosec
	return c, nil
}

func (d *DB) SetBrainConfig(c *BrainConfig) error {
	extraJSON, _ := json.Marshal(c.ExtraConfig)
	now := unixNow()
	_, err := d.db.Exec(`
		INSERT INTO node_brain_config
			(node_id, provider, model, temperature, max_tokens, system_prompt, extra_config, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT (node_id) DO UPDATE SET
			provider=EXCLUDED.provider, model=EXCLUDED.model,
			temperature=EXCLUDED.temperature, max_tokens=EXCLUDED.max_tokens,
			system_prompt=EXCLUDED.system_prompt, extra_config=EXCLUDED.extra_config,
			updated_at=EXCLUDED.updated_at`,
		c.NodeID, c.Provider, c.Model, c.Temperature,
		c.MaxTokens, c.SystemPrompt, string(extraJSON), now)
	return err
}

func (d *DB) GetBrainHistory(nodeID string, limit int) ([]*BrainExecutionEntry, error) {
	rows, err := d.db.Query(`
		SELECT exec_id, node_id, provider, model, prompt_tokens, completion_tokens,
		       latency_ms, success, error_text, executed_at, cycle
		FROM brain_execution_log WHERE node_id = $1
		ORDER BY executed_at DESC LIMIT $2`, nodeID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var entries []*BrainExecutionEntry
	for rows.Next() {
		e := &BrainExecutionEntry{}
		if err := rows.Scan(&e.ExecID, &e.NodeID, &e.Provider, &e.Model,
			&e.PromptTokens, &e.CompletionTokens, &e.LatencyMS,
			&e.Success, &e.ErrorText, &e.ExecutedAt, &e.Cycle); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, nil
}

// ── Query methods ────────────────────────────────────────────────────────────

func (d *DB) AllNodes() ([]*Node, error) {
	rows, err := d.db.Query(`
		SELECT node_id, name, version, capabilities, health, status,
		       registered_at, last_updated
		FROM nodes ORDER BY registered_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec

	var nodes []*Node
	for rows.Next() {
		n := &Node{}
		var capsJSON string
		if err := rows.Scan(&n.NodeID, &n.Name, &n.Version, &capsJSON,
			&n.Health, &n.Status, &n.RegisteredAt, &n.LastUpdated); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(capsJSON), &n.Capabilities) //nolint:errcheck,gosec
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
	row := d.db.QueryRow(`
		SELECT node_id, name, version, capabilities, health, status,
		       registered_at, last_updated
		FROM nodes WHERE node_id = $1`, nodeID)
	n := &Node{}
	var capsJSON string
	if err := row.Scan(&n.NodeID, &n.Name, &n.Version, &capsJSON,
		&n.Health, &n.Status, &n.RegisteredAt, &n.LastUpdated); err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(capsJSON), &n.Capabilities) //nolint:errcheck,gosec
	return n, d.enrichNode(n)
}

func (d *DB) enrichNode(n *Node) error {
	row := d.db.QueryRow(`
		SELECT COUNT(*),
		       SUM(CASE WHEN NOT success THEN 1 ELSE 0 END),
		       AVG(duration_ms),
		       MAX(started_at)
		FROM node_executions WHERE node_id = $1`, n.NodeID)
	var total, failed int64
	var avgMS sql.NullFloat64
	var lastStarted sql.NullFloat64
	row.Scan(&total, &failed, &avgMS, &lastStarted) //nolint:errcheck,gosec

	n.ExecutionsTotal = total
	if total > 0 {
		n.ErrorRate = float64(failed) / float64(total)
	}
	if avgMS.Valid {
		n.AvgLatencyMS = avgMS.Float64
	}

	// p95 latency
	var p95Count int64
	d.db.QueryRow(`SELECT COUNT(*) FROM node_executions WHERE node_id = $1 AND duration_ms IS NOT NULL`, n.NodeID).Scan(&p95Count) //nolint:errcheck,gosec
	if p95Count > 0 {
		offset := int64(float64(p95Count) * 0.95)
		p95row := d.db.QueryRow(`
			SELECT duration_ms FROM node_executions
			WHERE node_id = $1 AND duration_ms IS NOT NULL
			ORDER BY duration_ms
			LIMIT 1 OFFSET $2
		`, n.NodeID, offset)
		var p95 sql.NullFloat64
		p95row.Scan(&p95) //nolint:errcheck,gosec
		if p95.Valid {
			n.P95LatencyMS = p95.Float64
		}
	}

	row2 := d.db.QueryRow(
		`SELECT COUNT(*) FROM improvement_log WHERE node_id = $1`, n.NodeID)
	row2.Scan(&n.ImprovementCount) //nolint:errcheck,gosec

	lastExec, err := d.lastExecution(n.NodeID)
	if err == nil {
		n.LastExecution = lastExec
	}
	return nil
}

func (d *DB) lastExecution(nodeID string) (*Execution, error) {
	row := d.db.QueryRow(`
		SELECT exec_id, node_id, node_name, COALESCE(trace_id,''), COALESCE(span_id,''),
		       action, started_at, ended_at, duration_ms, success,
		       COALESCE(error_text,''), COALESCE(metrics::text,'{}'), cycle,
		       COALESCE(error_class,0), COALESCE(error_code,''), COALESCE(is_retryable,false)
		FROM node_executions WHERE node_id = $1
		ORDER BY started_at DESC LIMIT 1`, nodeID)
	return scanExecution(row)
}

func scanExecution(row *sql.Row) (*Execution, error) {
	e := &Execution{}
	var metricsJSON string
	var errorClass int32
	var endedAt, durationMS sql.NullFloat64
	err := row.Scan(&e.ExecID, &e.NodeID, &e.NodeName, &e.TraceID, &e.SpanID,
		&e.Action, &e.StartedAt, &endedAt, &durationMS, &e.Success,
		&e.ErrorText, &metricsJSON, &e.Cycle,
		&errorClass, &e.ErrorCode, &e.IsRetryable)
	if err != nil {
		return nil, err
	}
	e.ErrorClass = errorClass
	if endedAt.Valid {
		v := endedAt.Float64
		e.EndedAt = &v
	}
	if durationMS.Valid {
		v := durationMS.Float64
		e.DurationMS = &v
	}
	json.Unmarshal([]byte(metricsJSON), &e.Metrics) //nolint:errcheck,gosec
	return e, nil
}

func (d *DB) GetExecutions(nodeID string, limit int) ([]*Execution, error) {
	query := `SELECT exec_id, node_id, node_name, COALESCE(trace_id,''), COALESCE(span_id,''),
		action, started_at, ended_at, duration_ms, success,
		COALESCE(error_text,''), COALESCE(metrics::text,'{}'), cycle,
		COALESCE(error_class,0), COALESCE(error_code,''), COALESCE(is_retryable,false)
		FROM node_executions WHERE TRUE`
	args := []any{}
	argN := 1
	if nodeID != "" {
		query += fmt.Sprintf(" AND node_id = $%d", argN)
		args = append(args, nodeID)
		argN++
	}
	query += fmt.Sprintf(" ORDER BY started_at DESC LIMIT $%d", argN) //nolint:gosec
	args = append(args, limit)

	rows, err := d.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	return scanExecutions(rows)
}

func scanExecutions(rows *sql.Rows) ([]*Execution, error) {
	var result []*Execution
	for rows.Next() {
		e := &Execution{}
		var metricsJSON string
		var errorClass int32
		var endedAt, durationMS sql.NullFloat64
		if err := rows.Scan(&e.ExecID, &e.NodeID, &e.NodeName, &e.TraceID, &e.SpanID,
			&e.Action, &e.StartedAt, &endedAt, &durationMS, &e.Success,
			&e.ErrorText, &metricsJSON, &e.Cycle,
			&errorClass, &e.ErrorCode, &e.IsRetryable); err != nil {
			return nil, err
		}
		e.ErrorClass = errorClass
		if endedAt.Valid {
			v := endedAt.Float64
			e.EndedAt = &v
		}
		if durationMS.Valid {
			v := durationMS.Float64
			e.DurationMS = &v
		}
		json.Unmarshal([]byte(metricsJSON), &e.Metrics) //nolint:errcheck,gosec
		result = append(result, e)
	}
	return result, nil
}

func (d *DB) LatencyHistory(nodeID string, limit int) ([]*LatencyPoint, error) {
	rows, err := d.db.Query(`
		SELECT started_at, duration_ms, success
		FROM node_executions
		WHERE node_id = $1 AND duration_ms IS NOT NULL
		ORDER BY started_at DESC LIMIT $2`, nodeID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var points []*LatencyPoint
	for rows.Next() {
		p := &LatencyPoint{}
		if err := rows.Scan(&p.StartedAt, &p.DurationMS, &p.Success); err != nil {
			return nil, err
		}
		points = append(points, p)
	}
	for i, j := 0, len(points)-1; i < j; i, j = i+1, j-1 {
		points[i], points[j] = points[j], points[i]
	}
	return points, nil
}

func (d *DB) RecentTraces(limit int, nodeFilter string) ([]*TraceSummary, error) {
	var rows *sql.Rows
	var err error
	if nodeFilter != "" {
		rows, err = d.db.Query(`
			SELECT trace_id,
			       MIN(started_at) as trace_started,
			       MAX(ended_at) as trace_ended,
			       (MAX(ended_at) - MIN(started_at)) * 1000 as total_duration_ms,
			       COUNT(*) as span_count,
			       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_spans,
			       MAX(cycle) as cycle
			FROM traces
			WHERE trace_id IN (SELECT DISTINCT trace_id FROM traces WHERE node_name = $1)
			GROUP BY trace_id
			ORDER BY trace_started DESC
			LIMIT $2`, nodeFilter, limit)
	} else {
		rows, err = d.db.Query(`
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
			LIMIT $1`, limit)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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
	rows, err := d.db.Query(`
		SELECT span_id, trace_id, COALESCE(parent_span_id,''),
		       COALESCE(node_id,''), COALESCE(node_name,''),
		       operation, started_at, ended_at, duration_ms, status, cycle
		FROM traces WHERE trace_id = $1 ORDER BY started_at`, traceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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
		FROM issues WHERE TRUE`
	args := []any{}
	argN := 1
	if stateFilter != "" && stateFilter != "all" {
		if stateFilter == "open" {
			query += " AND state != 'resolved'"
		} else {
			query += fmt.Sprintf(" AND state = $%d", argN) //nolint:gosec
			args = append(args, stateFilter)
		}
	}
	query += " ORDER BY opened_at DESC LIMIT 100"

	rows, err := d.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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
	rows, err := d.db.Query(`
		SELECT log_id, action_type, entity_type, entity_id, recorded_at, cycle
		FROM activity_log ORDER BY recorded_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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
		COALESCE(before_metrics::text,'{}'), COALESCE(after_metrics::text,'{}')
		FROM improvement_log WHERE TRUE`
	args := []any{}
	argN := 1
	if nodeID != "" {
		query += fmt.Sprintf(" AND node_id = $%d", argN)
		args = append(args, nodeID)
		argN++
	}
	query += fmt.Sprintf(" ORDER BY recorded_at DESC LIMIT $%d", argN) //nolint:gosec
	args = append(args, limit)

	rows, err := d.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
	var imps []*Improvement
	for rows.Next() {
		imp := &Improvement{}
		var beforeJSON, afterJSON string
		if err := rows.Scan(&imp.ImproveID, &imp.NodeID, &imp.NodeName,
			&imp.FromVersion, &imp.ToVersion, &imp.TriggeredBy,
			&imp.RecordedAt, &imp.Cycle, &beforeJSON, &afterJSON); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(beforeJSON), &imp.BeforeMetrics) //nolint:errcheck,gosec
		json.Unmarshal([]byte(afterJSON), &imp.AfterMetrics)   //nolint:errcheck,gosec
		imps = append(imps, imp)
	}
	return imps, nil
}

func (d *DB) GetCosts() ([]*CostEntry, error) {
	rows, err := d.db.Query(`
		SELECT provider, node_id,
		       COUNT(*) as calls,
		       SUM(duration_ms) as total_ms,
		       SUM(estimated_cost_usd) as total_cost
		FROM cost_events GROUP BY provider, node_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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
	rows, err := d.db.Query(`
		SELECT cycle, timestamp, content::text
		FROM episodes WHERE event_type = 'cycle_summary'
		ORDER BY cycle ASC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck,gosec
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

	epQuery := "SELECT COUNT(*) FROM episodes"
	epArgs := []any{}
	if namespace != "" {
		epQuery += " WHERE namespace = $1"
		epArgs = append(epArgs, namespace)
	}
	d.db.QueryRow(epQuery, epArgs...).Scan(&epCount) //nolint:errcheck,gosec

	semQuery := "SELECT COUNT(*) FROM semantic_memories"
	semArgs := []any{}
	if namespace != "" {
		semQuery += " WHERE namespace = $1"
		semArgs = append(semArgs, namespace)
	}
	d.db.QueryRow(semQuery, semArgs...).Scan(&semCount) //nolint:errcheck,gosec

	semRowQuery := "SELECT concept, content, confidence, evidence_count, COALESCE(tags::text,'[]') FROM semantic_memories"
	if namespace != "" {
		semRowQuery += " WHERE namespace = $1"
	}
	semRowQuery += " ORDER BY confidence DESC LIMIT 20"
	semRows, err := d.db.Query(semRowQuery, semArgs...)
	if err != nil {
		return epCount, semCount, nil, nil, err
	}
	defer semRows.Close() //nolint:errcheck,gosec
	var concepts []*SemanticConcept
	for semRows.Next() {
		c := &SemanticConcept{}
		var tagsJSON string
		if err := semRows.Scan(&c.Concept, &c.Content, &c.Confidence, &c.EvidenceCount, &tagsJSON); err != nil {
			return epCount, semCount, nil, nil, err
		}
		json.Unmarshal([]byte(tagsJSON), &c.Tags) //nolint:errcheck,gosec
		concepts = append(concepts, c)
	}

	epRowQuery := "SELECT episode_id, event_type, timestamp, cycle, importance, COALESCE(tags::text,'[]') FROM episodes"
	if namespace != "" {
		epRowQuery += " WHERE namespace = $1"
	}
	epRowQuery += " ORDER BY timestamp DESC LIMIT 20"
	epRows, err := d.db.Query(epRowQuery, epArgs...)
	if err != nil {
		return epCount, semCount, concepts, nil, err
	}
	defer epRows.Close() //nolint:errcheck,gosec
	var episodes []*EpisodeEntry
	for epRows.Next() {
		e := &EpisodeEntry{}
		var tagsJSON string
		if err := epRows.Scan(&e.EpisodeID, &e.EventType, &e.Timestamp, &e.Cycle, &e.Importance, &tagsJSON); err != nil {
			return epCount, semCount, concepts, nil, err
		}
		json.Unmarshal([]byte(tagsJSON), &e.Tags) //nolint:errcheck,gosec
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
	minHealth := 1.0
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
	if composite < 0.5 {
		status = "degraded"
	}
	if composite < 0.3 {
		status = "critical"
	}

	var totalCycles int64
	d.db.QueryRow(`SELECT COALESCE(MAX(cycle),0) FROM node_executions`).Scan(&totalCycles) //nolint:errcheck,gosec

	var oldestStart float64
	d.db.QueryRow(`SELECT COALESCE(MIN(registered_at),0) FROM nodes`).Scan(&oldestStart) //nolint:errcheck,gosec
	var uptimeSec float64
	if oldestStart > 0 {
		uptimeSec = unixNow() - oldestStart
	}

	return &SystemHealth{
		Status:         status,
		CompositeScore: composite,
		AvgNodeHealth:  avgHealth,
		NodeCount:      int64(len(nodes)),
		OpenIssues:     openCount,
		ErrorIssues:    errorIssues,
		UptimeSeconds:  uptimeSec,
		TotalCycles:    totalCycles,
	}, nil
}

// unixNow returns the current time as a float64 Unix timestamp.
func unixNow() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}
