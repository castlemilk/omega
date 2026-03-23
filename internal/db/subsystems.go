package db

import (
	"database/sql"
	"encoding/json"
)

// ── Alignment ─────────────────────────────────────────────────────────────────

// AlignmentDecision is a single alignment layer decision.
type AlignmentDecision struct {
	DecisionID      string
	Cycle           int64
	Approved        bool
	Reasons         []string
	TargetSubsystem string
	RecordedAt      float64
}

// RecentAlignmentDecisions returns the most recent alignment decisions.
func (d *DB) RecentAlignmentDecisions(limit int) ([]*AlignmentDecision, error) {
	rows, err := d.db.Query(`
		SELECT decision_id, cycle, approved,
		       COALESCE(violations::text,'[]'), '',
		       recorded_at
		FROM alignment_decisions
		ORDER BY recorded_at DESC LIMIT $1`, limit)
	if err != nil {
		return []*AlignmentDecision{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*AlignmentDecision
	for rows.Next() {
		a := &AlignmentDecision{}
		var reasonsJSON string
		if err := rows.Scan(&a.DecisionID, &a.Cycle, &a.Approved,
			&reasonsJSON, &a.TargetSubsystem, &a.RecordedAt); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(reasonsJSON), &a.Reasons) //nolint:errcheck,gosec
		if a.Reasons == nil {
			a.Reasons = []string{}
		}
		out = append(out, a)
	}
	if out == nil {
		return []*AlignmentDecision{}, nil
	}
	return out, nil
}

// ── Adversarial ───────────────────────────────────────────────────────────────

// AdversarialResult is a single adversarial pressure result.
type AdversarialResult struct {
	ResultID   string
	Cycle      int64
	Ring       int32
	Flags      []string
	Severity   string
	RecordedAt float64
}

// RecentAdversarialResults returns the most recent adversarial results.
func (d *DB) RecentAdversarialResults(limit int) ([]*AdversarialResult, error) {
	rows, err := d.db.Query(`
		SELECT result_id, cycle, ring,
		       COALESCE(failure_cases::text,'[]'), 'low',
		       recorded_at
		FROM adversarial_results
		ORDER BY recorded_at DESC LIMIT $1`, limit)
	if err != nil {
		return []*AdversarialResult{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*AdversarialResult
	for rows.Next() {
		r := &AdversarialResult{}
		var flagsJSON string
		if err := rows.Scan(&r.ResultID, &r.Cycle, &r.Ring,
			&flagsJSON, &r.Severity, &r.RecordedAt); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(flagsJSON), &r.Flags) //nolint:errcheck,gosec
		if r.Flags == nil {
			r.Flags = []string{}
		}
		out = append(out, r)
	}
	if out == nil {
		return []*AdversarialResult{}, nil
	}
	return out, nil
}

// ── Goal tracking ─────────────────────────────────────────────────────────────

// GoalState is the most recent goal_tracking snapshot.
type GoalState struct {
	Cycle                int64
	ConstitutionalChecks map[string]bool
	ScorecardValues      map[string]float64
	ActiveTasks          []string
	RecordedAt           float64
}

// CurrentGoalState returns the most recent goal_tracking row, or nil if empty.
func (d *DB) CurrentGoalState() (*GoalState, error) {
	row := d.db.QueryRow(`
		SELECT cycle,
		       COALESCE(scorecard::text,'{}'),
		       COALESCE(scorecard::text,'{}'),
		       COALESCE(subtasks::text,'[]'),
		       recorded_at
		FROM goal_tracking
		ORDER BY recorded_at DESC LIMIT 1`)
	gs := &GoalState{}
	var checksJSON, scorecardJSON, tasksJSON string
	err := row.Scan(&gs.Cycle, &checksJSON, &scorecardJSON, &tasksJSON, &gs.RecordedAt)
	if err == sql.ErrNoRows || err != nil {
		return nil, nil //nolint
	}
	json.Unmarshal([]byte(checksJSON), &gs.ConstitutionalChecks)  //nolint:errcheck,gosec
	json.Unmarshal([]byte(scorecardJSON), &gs.ScorecardValues)    //nolint:errcheck,gosec
	json.Unmarshal([]byte(tasksJSON), &gs.ActiveTasks)            //nolint:errcheck,gosec
	if gs.ConstitutionalChecks == nil {
		gs.ConstitutionalChecks = map[string]bool{}
	}
	if gs.ScorecardValues == nil {
		gs.ScorecardValues = map[string]float64{}
	}
	if gs.ActiveTasks == nil {
		gs.ActiveTasks = []string{}
	}
	return gs, nil
}

// ── Challenges ────────────────────────────────────────────────────────────────

// Challenge is a devil's advocate challenge.
type Challenge struct {
	ChallengeID     string
	Status          string
	Severity        string
	TargetSubsystem string
	Description     string
	CreatedAt       float64
	UpdatedAt       float64
}

// ListChallenges returns challenges from the challenges table.
func (d *DB) ListChallenges(statusFilter string) ([]*Challenge, error) {
	query := `SELECT challenge_id, status, COALESCE(severity,'medium'),
	                 COALESCE(target_subsystem,''), COALESCE(description,''),
	                 created_at, COALESCE(updated_at, created_at)
	          FROM challenges`
	args := []any{}
	if statusFilter != "" && statusFilter != "all" {
		query += " WHERE status = $1"
		args = append(args, statusFilter)
	}
	query += " ORDER BY created_at DESC"
	rows, err := d.db.Query(query, args...)
	if err != nil {
		return []*Challenge{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*Challenge
	for rows.Next() {
		c := &Challenge{}
		if err := rows.Scan(&c.ChallengeID, &c.Status, &c.Severity,
			&c.TargetSubsystem, &c.Description, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	if out == nil {
		return []*Challenge{}, nil
	}
	return out, nil
}

// ── Memory stats ──────────────────────────────────────────────────────────────

// MemoryStats summarises the memory store sizes.
type MemoryStats struct {
	EpisodicCount      int64
	SemanticCount      int64
	RegimeHistory      []string
	ContradictionCount int64
}

// GetMemoryStatsSummary returns aggregate counts and regime history.
func (d *DB) GetMemoryStatsSummary() (*MemoryStats, error) {
	ms := &MemoryStats{RegimeHistory: []string{}}
	d.db.QueryRow(`SELECT COUNT(*) FROM episodes`).Scan(&ms.EpisodicCount)          //nolint:errcheck,gosec
	d.db.QueryRow(`SELECT COUNT(*) FROM semantic_memories`).Scan(&ms.SemanticCount) //nolint:errcheck,gosec
	d.db.QueryRow(`SELECT COUNT(*) FROM episodes WHERE tags::text LIKE '%contradiction%'`).Scan(&ms.ContradictionCount) //nolint:errcheck,gosec

	rows, err := d.db.Query(`
		SELECT DISTINCT event_type FROM episodes
		ORDER BY event_type DESC LIMIT 10`)
	if err == nil {
		defer rows.Close() //nolint:errcheck
		for rows.Next() {
			var t string
			rows.Scan(&t) //nolint:errcheck,gosec
			ms.RegimeHistory = append(ms.RegimeHistory, t)
		}
	}
	return ms, nil
}

// ── Verification gates ────────────────────────────────────────────────────────

// GateResult is a single verification gate check result.
type GateResult struct {
	GateID    string
	Cycle     int64
	GateName  string
	Result    string
	Details   string
	CheckedAt float64
}

// RecentGateResults returns the most recent verification gate results.
func (d *DB) RecentGateResults(limit int) ([]*GateResult, error) {
	rows, err := d.db.Query(`
		SELECT gate_id, cycle, gate_name,
		       result, COALESCE(details,''), checked_at
		FROM verification_gates
		ORDER BY checked_at DESC LIMIT $1`, limit)
	if err != nil {
		return []*GateResult{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*GateResult
	for rows.Next() {
		g := &GateResult{}
		if err := rows.Scan(&g.GateID, &g.Cycle, &g.GateName,
			&g.Result, &g.Details, &g.CheckedAt); err != nil {
			return nil, err
		}
		out = append(out, g)
	}
	if out == nil {
		return []*GateResult{}, nil
	}
	return out, nil
}

// ── Improvement history ───────────────────────────────────────────────────────

// ImprovementDetail augments improvement_log with alignment decision context.
type ImprovementDetail struct {
	ImproveID         string
	NodeID            string
	NodeName          string
	FromVersion       string
	ToVersion         string
	TriggeredBy       string
	RecordedAt        float64
	Cycle             int64
	BeforeMetrics     map[string]float64
	AfterMetrics      map[string]float64
	AlignmentApproved *bool
	AlignmentReasons  []string
}

// ImprovementHistory returns improvement records joined with alignment decisions.
func (d *DB) ImprovementHistory(limit int) ([]*ImprovementDetail, error) {
	rows, err := d.db.Query(`
		SELECT i.improve_id, i.node_id, i.node_name,
		       i.from_version, i.to_version, i.triggered_by,
		       i.recorded_at, i.cycle,
		       COALESCE(i.before_metrics::text,'{}'),
		       COALESCE(i.after_metrics::text,'{}'),
		       a.approved, COALESCE(a.violations::text,'[]')
		FROM improvement_log i
		LEFT JOIN alignment_decisions a ON a.cycle = i.cycle
		ORDER BY i.recorded_at DESC LIMIT $1`, limit)
	if err != nil {
		return []*ImprovementDetail{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*ImprovementDetail
	for rows.Next() {
		imp := &ImprovementDetail{}
		var beforeJSON, afterJSON, reasonsJSON string
		var approved sql.NullBool
		if err := rows.Scan(
			&imp.ImproveID, &imp.NodeID, &imp.NodeName,
			&imp.FromVersion, &imp.ToVersion, &imp.TriggeredBy,
			&imp.RecordedAt, &imp.Cycle,
			&beforeJSON, &afterJSON,
			&approved, &reasonsJSON,
		); err != nil {
			return nil, err
		}
		json.Unmarshal([]byte(beforeJSON), &imp.BeforeMetrics) //nolint:errcheck,gosec
		json.Unmarshal([]byte(afterJSON), &imp.AfterMetrics)   //nolint:errcheck,gosec
		if imp.BeforeMetrics == nil {
			imp.BeforeMetrics = map[string]float64{}
		}
		if imp.AfterMetrics == nil {
			imp.AfterMetrics = map[string]float64{}
		}
		if approved.Valid {
			v := approved.Bool
			imp.AlignmentApproved = &v
			json.Unmarshal([]byte(reasonsJSON), &imp.AlignmentReasons) //nolint:errcheck,gosec
		}
		if imp.AlignmentReasons == nil {
			imp.AlignmentReasons = []string{}
		}
		out = append(out, imp)
	}
	if out == nil {
		return []*ImprovementDetail{}, nil
	}
	return out, nil
}

// ── Terminal ──────────────────────────────────────────────────────────────────

// TerminalSessionRecord is a persisted terminal session.
type TerminalSessionRecord struct {
	ID            string
	WorkDir       string
	AutonomyLevel string
	Status        string
	CreatedAt     float64
	ClosedAt      float64 // 0 if still active
}

// TerminalCommandRecord is a single executed command within a session.
type TerminalCommandRecord struct {
	ID         string
	SessionID  string
	Command    string
	Args       string // JSON-encoded []string
	ExitCode   int
	Stdout     string
	Stderr     string
	DurationMS int64
	Truncated  bool
	ExecutedAt float64
}

// GetTerminalSession retrieves a session by ID. Returns nil, nil if not found.
func (d *DB) GetTerminalSession(id string) (*TerminalSessionRecord, error) {
	row := d.db.QueryRow(`
		SELECT id, work_dir, autonomy_level, status, created_at, COALESCE(closed_at, 0)
		FROM terminal_sessions WHERE id = $1`, id)
	s := &TerminalSessionRecord{}
	err := row.Scan(&s.ID, &s.WorkDir, &s.AutonomyLevel, &s.Status, &s.CreatedAt, &s.ClosedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return s, err
}

// GetTerminalCommands returns all commands for a session in execution order.
func (d *DB) GetTerminalCommands(sessionID string) ([]*TerminalCommandRecord, error) {
	rows, err := d.db.Query(`
		SELECT id, session_id, command, args::text, exit_code, stdout, stderr,
		       duration_ms, truncated, executed_at
		FROM terminal_commands WHERE session_id = $1
		ORDER BY executed_at ASC`, sessionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close() //nolint:errcheck
	var out []*TerminalCommandRecord
	for rows.Next() {
		c := &TerminalCommandRecord{}
		if err := rows.Scan(&c.ID, &c.SessionID, &c.Command, &c.Args,
			&c.ExitCode, &c.Stdout, &c.Stderr, &c.DurationMS, &c.Truncated, &c.ExecutedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	if out == nil {
		return []*TerminalCommandRecord{}, nil
	}
	return out, nil
}
