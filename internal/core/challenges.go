// challenges.go — Persistent store of challenges raised by the Devil's Advocate node.
//
// Each challenge targets a subsystem, has a severity, evidence, and lifecycle
// status. Unresolved CRITICAL challenges block deployments via HasBlockingChallenges.
// Resolution rate is tracked as a system health metric.
package core

import (
	"database/sql"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

// ChallengeSeverity is the severity level of a challenge.
type ChallengeSeverity string

const (
	SeverityCritical ChallengeSeverity = "critical"
	SeverityHigh     ChallengeSeverity = "high"
	SeverityMedium   ChallengeSeverity = "medium"
	SeverityLow      ChallengeSeverity = "low"
)

// ChallengeStatus is the lifecycle state of a challenge.
type ChallengeStatus string

const (
	StatusOpen         ChallengeStatus = "open"
	StatusAcknowledged ChallengeStatus = "acknowledged"
	StatusResolved     ChallengeStatus = "resolved"
	StatusWontfix      ChallengeStatus = "wontfix"
)

// ---------------------------------------------------------------------------
// Challenge struct
// ---------------------------------------------------------------------------

// Challenge is a recorded concern raised against a subsystem.
type Challenge struct {
	ChallengeID     string
	TargetSubsystem string
	Severity        ChallengeSeverity
	Description     string
	Evidence        string
	Status          ChallengeStatus
	ResolutionNotes string
	CreatedAt       float64
	UpdatedAt       float64
}

// ---------------------------------------------------------------------------
// Schema and seed data
// ---------------------------------------------------------------------------

type seedChallenge struct {
	targetSubsystem string
	severity        ChallengeSeverity
	description     string
	evidence        string
}

// seedChallenges covers both current architecture and planned subsystems.
var seedChallenges = []seedChallenge{
	// Current architecture
	{
		targetSubsystem: "orchestrator.convergence_loop",
		severity:        SeverityHigh,
		description: "Convergence detection uses a single metric delta threshold — the system " +
			"can stop improving a metric because it oscillates just below the threshold, " +
			"appearing converged while actually thrashing.",
		evidence: "orchestrator.py:run_convergence_loop — has_improved() checks only the last " +
			"two iterations; oscillation over a 4-iteration window is invisible to it.",
	},
	{
		targetSubsystem: "orchestrator.improvement_loop",
		severity:        SeverityMedium,
		description: "improve_system() sends identical feedback to every node regardless of " +
			"whether that node contributed to the failing metric. A slow " +
			"DataIngestionNode triggers improve() on SignalGenerationNode and " +
			"RiskManagementNode.",
		evidence: "orchestrator.py:improve_system — iterates all_nodes() with system-level " +
			"feedback; no per-node attribution of metric causality.",
	},
	{
		targetSubsystem: "memory.episodic_decay",
		severity:        SeverityHigh,
		description: "EpisodicStore importance decay is time-based, not outcome-based. A signal " +
			"that predicted a 40% crash correctly decays at the same rate as a noise " +
			"signal. High-importance rare events will be pruned before the system can " +
			"learn from them.",
		evidence: "memory.py — decay formula is exponential by age; no reinforcement signal " +
			"from downstream outcome evaluation.",
	},
	{
		targetSubsystem: "memory.semantic_consolidation",
		severity:        SeverityMedium,
		description: "Consolidator extracts patterns from episodic → semantic on a fixed cycle " +
			"interval. During rapid regime changes, the semantic store will lag reality " +
			"by at least one consolidation window, issuing stale guidance to nodes.",
		evidence: "memory.py:Consolidator — consolidates every N cycles; no trigger for " +
			"urgent consolidation when high-confidence contradictions appear.",
	},
	{
		targetSubsystem: "victoria.signal_generation",
		severity:        SeverityHigh,
		description: "SignalGenerationNode self-improvement unlocks new indicator types each " +
			"cycle. No check that adding a new indicator doesn't re-introduce a " +
			"highly-correlated signal already present. Correlated signals inflate " +
			"apparent alpha and degrade out-of-sample Sharpe.",
		evidence: "signal_generation.py — improve() appends to _enabled_indicators; no " +
			"correlation check against existing set.",
	},
	{
		targetSubsystem: "victoria.verification",
		severity:        SeverityMedium,
		description: "VerificationNode uses a fixed 30% regression threshold — arbitrary. " +
			"A 29% regression in Sharpe during high-volatility may be noise; " +
			"a 5% regression in max drawdown may be catastrophic. Thresholds should " +
			"be metric-specific and regime-aware.",
		evidence: "verification.py:REGRESSION_THRESHOLD = 0.3 — single constant applied " +
			"to all metrics regardless of scale or business impact.",
	},
	{
		targetSubsystem: "victoria.data_ingestion",
		severity:        SeverityHigh,
		description: "DataIngestionNode falls back to cached data on failure without staleness " +
			"bounds. If Binance and CoinGecko both fail for 24+ hours, the pipeline " +
			"continues on day-old data producing 'valid' signals with no staleness " +
			"warning in the output.",
		evidence: "data_ingestion.py — fallback path returns self._cache without timestamp " +
			"comparison; victoria_main.py logs a warning but does not halt the pipeline.",
	},
	{
		targetSubsystem: "state_store",
		severity:        SeverityLow,
		description: "StateStore uses a single SQLite connection with check_same_thread=False. " +
			"If the heartbeat loop gains async or threading support, concurrent writes " +
			"will corrupt the database silently.",
		evidence: "state_store.py:__init__ — sqlite3.connect(db_path, check_same_thread=False); " +
			"no write serialisation.",
	},
	{
		targetSubsystem: "orchestrator.node_selection",
		severity:        SeverityMedium,
		description: "Node selection always picks the highest-health node — greedy, no " +
			"exploration. A new improved node version starting at health=0.5 will " +
			"never be selected over a stale node at health=0.9, permanently blocking " +
			"the system from discovering that the new version is better.",
		evidence: "orchestrator.py:_select_node — max(candidates, key=health). " +
			"No epsilon-greedy or UCB exploration. New nodes are starved of execution data.",
	},
	{
		targetSubsystem: "victoria.strategy",
		severity:        SeverityHigh,
		description: "StrategyNode backtest uses the same data window for both signal training " +
			"and portfolio evaluation — look-ahead bias. Reported Sharpe ratios are " +
			"optimistic by an unknown but likely significant factor.",
		evidence: "strategy.py — signals and backtest share the same OHLCV window; " +
			"no walk-forward or out-of-sample holdout separation.",
	},
	// Planned architecture
	{
		targetSubsystem: "alignment.layer_architecture",
		severity:        SeverityHigh,
		description: "The planned 5-layer alignment architecture adds O(5n) overhead per " +
			"improvement cycle. At high heartbeat frequency or large node count, " +
			"the alignment layer itself becomes the bottleneck. What is the empirical " +
			"threshold, and is there a fast-path for low-risk improvements?",
		evidence: "Planned design: each improvement passes through 5 sequential alignment " +
			"checks before commit. No profiling baseline established yet.",
	},
	{
		targetSubsystem: "alignment.ewc_protection",
		severity:        SeverityCritical,
		description: "EWC (Elastic Weight Consolidation) protection assumes tasks are cleanly " +
			"separable with stable Fisher information estimates. Crypto regime " +
			"transitions are gradual and overlapping, not discrete. EWC importance " +
			"weights computed during one regime will incorrectly protect parameters " +
			"that should adapt during a transition, resisting beneficial updates.",
		evidence: "EWC design assumes clear task boundaries. Crypto markets exhibit " +
			"non-stationary overlapping regimes (bull/bear/sideways/high-vol) with " +
			"no ground-truth change point. BOCPD or HMM-based regime detection would " +
			"be needed to gate EWC application correctly.",
	},
	{
		targetSubsystem: "alignment.nash_welfare",
		severity:        SeverityCritical,
		description: "Nash welfare aggregation requires knowing all objectives upfront. " +
			"If a new objective emerges mid-operation (e.g. 'minimise drawdown during " +
			"regulatory crackdown'), adding it retroactively changes welfare scores " +
			"of all prior decisions, potentially invalidating the improvement history.",
		evidence: "Nash welfare: max ∏ u_i(x). Adding a new u_i reweights the product. " +
			"No mechanism in the planned design for objective versioning or retroactive " +
			"welfare recalculation.",
	},
	{
		targetSubsystem: "skills.iter_drag",
		severity:        SeverityCritical,
		description: "The IterDRAG research skill has no grounding mechanism. Retrieval from " +
			"a vector store followed by LLM generation can produce hallucinated " +
			"justifications for plausible-but-wrong documents. Hallucinated research " +
			"findings stored back into SemanticMemory propagate permanently to all " +
			"downstream nodes.",
		evidence: "RAG without verification: retrieval → generation → memory write. " +
			"No citation verification, no cross-referencing against live market data, " +
			"no confidence threshold before memory storage.",
	},
	{
		targetSubsystem: "alignment.vcg_pricing",
		severity:        SeverityHigh,
		description: "VCG pricing assumes rational, utility-maximising agents. LLM nodes are " +
			"not rational — they are stochastic functions that may 'misreport' their " +
			"true valuation due to prompt framing, temperature, or context window " +
			"effects. The VCG mechanism's incentive-compatibility guarantee breaks down.",
		evidence: "VCG correctness requires truthful bidding. LLM inference is " +
			"non-deterministic and context-sensitive; the same node may report " +
			"different 'valuations' for identical inputs across calls.",
	},
	{
		targetSubsystem: "memory.bocpd_regime_detection",
		severity:        SeverityHigh,
		description: "BOCPD (Bayesian Online Changepoint Detection) has O(t) memory growth — " +
			"the run-length distribution must track all possible changepoint hypotheses " +
			"back to t=0. On a long-running system with sub-minute heartbeats, this " +
			"will OOM within days unless a truncation scheme is implemented, and the " +
			"truncation point must be chosen carefully to not miss long-horizon regimes.",
		evidence: "BOCPD: P(r_t | x_{1:t}) computed over all r_t ∈ {0, 1, …, t}. " +
			"At 1000 heartbeats/day x 180 days = 180,000 hypotheses untruncated. " +
			"Hazard function truncation at window W loses detection of regimes > W.",
	},
	{
		targetSubsystem: "alignment.constitutional_constraints",
		severity:        SeverityHigh,
		description: "Constitutional constraints are described as 'nodes cannot override' but " +
			"the enforcement mechanism is trust-based, not structural. Any node that " +
			"calls improve() on itself can change its own behaviour. There is no " +
			"sandboxing, no capability revocation, and no cryptographic proof that " +
			"constitutional rules were actually checked.",
		evidence: "node.py:improve() is abstract — implementations are free to do anything. " +
			"The orchestrator calls improve() and trusts the return value. " +
			"No post-improvement audit of node behaviour against constitutional rules.",
	},
	{
		targetSubsystem: "skills.skill_system",
		severity:        SeverityMedium,
		description: "The skill system has no versioning or compatibility contract. If a skill " +
			"is updated while a long-running heartbeat loop is active, mid-loop " +
			"behaviour changes unpredictably. Skills loaded at startup may differ from " +
			"skills loaded on the next restart, making debugging intermittent failures " +
			"extremely difficult.",
		evidence: "omega/skills/ — no skill version pinning, no schema validation, " +
			"no compatibility matrix between skill versions and node versions.",
	},
}

// ---------------------------------------------------------------------------
// ChallengeRegistry
// ---------------------------------------------------------------------------

// ChallengeRegistry is a persistent store for Devil's Advocate challenges.
type ChallengeRegistry struct {
	db *sql.DB
}

// NewChallengeRegistry wraps the shared Postgres database.
// Schema is managed by internal/db/db.go.
func NewChallengeRegistry(db *sql.DB) (*ChallengeRegistry, error) {
	return &ChallengeRegistry{db: db}, nil
}

// Close is a no-op — the underlying db is shared and not owned by this registry.
func (cr *ChallengeRegistry) Close() error { return nil }

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

// Add inserts a new challenge and returns its ID.
func (cr *ChallengeRegistry) Add(targetSubsystem string, severity ChallengeSeverity, description, evidence string, challengeID string) (string, error) {
	cid := challengeID
	if cid == "" {
		cid = uuid.New().String()
	}
	now := float64(time.Now().UnixNano()) / 1e9
	_, err := cr.db.Exec(
		`INSERT INTO challenges
		 (challenge_id, target_subsystem, severity, description, evidence,
		  status, resolution_notes, created_at, updated_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		cid, targetSubsystem, string(severity), description, evidence,
		string(StatusOpen), "", now, now,
	)
	if err != nil {
		return "", fmt.Errorf("add challenge: %w", err)
	}
	return cid, nil
}

// Get retrieves a challenge by ID. Returns nil if not found.
func (cr *ChallengeRegistry) Get(challengeID string) (*Challenge, error) {
	row := cr.db.QueryRow("SELECT * FROM challenges WHERE challenge_id = $1", challengeID)
	return scanChallenge(row)
}

// UpdateStatus updates the status and optional resolution notes for a challenge.
// Returns false if the challenge was not found.
func (cr *ChallengeRegistry) UpdateStatus(challengeID string, status ChallengeStatus, resolutionNotes string) (bool, error) {
	now := float64(time.Now().UnixNano()) / 1e9
	result, err := cr.db.Exec(
		`UPDATE challenges SET status=$1, resolution_notes=$2, updated_at=$3 WHERE challenge_id=$4`,
		string(status), resolutionNotes, now, challengeID,
	)
	if err != nil {
		return false, fmt.Errorf("update challenge status: %w", err)
	}
	n, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	return n > 0, nil
}

// AllChallenges returns all challenges, optionally filtered by subsystem substring.
func (cr *ChallengeRegistry) AllChallenges(subsystem string) ([]Challenge, error) {
	var (
		rows *sql.Rows
		err  error
	)
	if subsystem == "" {
		rows, err = cr.db.Query("SELECT * FROM challenges ORDER BY created_at")
	} else {
		rows, err = cr.db.Query("SELECT * FROM challenges WHERE target_subsystem LIKE $1 ORDER BY created_at", "%"+subsystem+"%")
	}
	if err != nil {
		return nil, fmt.Errorf("all challenges: %w", err)
	}
	defer func() { _ = rows.Close() }()
	return scanChallenges(rows)
}

// OpenChallenges returns challenges with status=open, optionally filtered by severity.
func (cr *ChallengeRegistry) OpenChallenges(severity ChallengeSeverity) ([]Challenge, error) {
	var (
		rows *sql.Rows
		err  error
	)
	if severity == "" {
		rows, err = cr.db.Query("SELECT * FROM challenges WHERE status = 'open' ORDER BY created_at")
	} else {
		rows, err = cr.db.Query("SELECT * FROM challenges WHERE status = 'open' AND severity = $1 ORDER BY created_at", string(severity))
	}
	if err != nil {
		return nil, fmt.Errorf("open challenges: %w", err)
	}
	defer func() { _ = rows.Close() }()
	return scanChallenges(rows)
}

// ---------------------------------------------------------------------------
// Health metrics
// ---------------------------------------------------------------------------

// ResolutionRate returns the fraction of challenges that are resolved or wontfix.
func (cr *ChallengeRegistry) ResolutionRate() (float64, error) {
	row := cr.db.QueryRow(`
		SELECT
			COUNT(*) as total,
			COALESCE(SUM(CASE WHEN status IN ('resolved','wontfix') THEN 1 ELSE 0 END), 0) as closed
		FROM challenges`)
	var total, closed int
	if err := row.Scan(&total, &closed); err != nil {
		return 0, fmt.Errorf("resolution rate: %w", err)
	}
	if total == 0 {
		return 1.0, nil
	}
	return float64(closed) / float64(total), nil
}

// HasBlockingChallenges returns true if any CRITICAL challenge is still open.
func (cr *ChallengeRegistry) HasBlockingChallenges() (bool, error) {
	row := cr.db.QueryRow("SELECT COUNT(*) FROM challenges WHERE severity='critical' AND status='open'")
	var n int
	if err := row.Scan(&n); err != nil {
		return false, fmt.Errorf("has blocking challenges: %w", err)
	}
	return n > 0, nil
}

// ---------------------------------------------------------------------------
// Seeding
// ---------------------------------------------------------------------------

// SeedInitialChallenges inserts the pre-defined challenge set if not already present.
// Idempotent — skips challenges whose description already exists.
// Returns the number of challenges newly inserted.
func (cr *ChallengeRegistry) SeedInitialChallenges() (int, error) {
	rows, err := cr.db.Query("SELECT description FROM challenges")
	if err != nil {
		return 0, fmt.Errorf("seed: query existing: %w", err)
	}
	existing := make(map[string]bool)
	for rows.Next() {
		var desc string
		if err := rows.Scan(&desc); err != nil {
			_ = rows.Close()
			return 0, err
		}
		existing[desc] = true
	}
	_ = rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}

	inserted := 0
	for _, ch := range seedChallenges {
		if existing[ch.description] {
			continue
		}
		if _, err := cr.Add(ch.targetSubsystem, ch.severity, ch.description, ch.evidence, ""); err != nil {
			return inserted, fmt.Errorf("seed insert: %w", err)
		}
		inserted++
	}
	return inserted, nil
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

func scanChallenge(row *sql.Row) (*Challenge, error) {
	var c Challenge
	var severity, status string
	err := row.Scan(
		&c.ChallengeID,
		&c.TargetSubsystem,
		&severity,
		&c.Description,
		&c.Evidence,
		&status,
		&c.ResolutionNotes,
		&c.CreatedAt,
		&c.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("scan challenge: %w", err)
	}
	c.Severity = ChallengeSeverity(severity)
	c.Status = ChallengeStatus(status)
	return &c, nil
}

func scanChallenges(rows *sql.Rows) ([]Challenge, error) {
	var challenges []Challenge
	for rows.Next() {
		var c Challenge
		var severity, status string
		if err := rows.Scan(
			&c.ChallengeID,
			&c.TargetSubsystem,
			&severity,
			&c.Description,
			&c.Evidence,
			&status,
			&c.ResolutionNotes,
			&c.CreatedAt,
			&c.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan challenges row: %w", err)
		}
		c.Severity = ChallengeSeverity(severity)
		c.Status = ChallengeStatus(status)
		challenges = append(challenges, c)
	}
	return challenges, rows.Err()
}
