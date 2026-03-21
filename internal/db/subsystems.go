package db

import (
	"database/sql"
	"encoding/json"
)

// ── Alignment ─────────────────────────────────────────────────────────────────

// AlignmentDecision is a single alignment layer decision from the state DB.
type AlignmentDecision struct {
	DecisionID      string
	Cycle           int64
	Approved        bool
	Reasons         []string
	TargetSubsystem string
	RecordedAt      float64
}

// RecentAlignmentDecisions returns the most recent alignment decisions.
// Returns an empty slice (not an error) if the table doesn't exist yet.
func (d *DB) RecentAlignmentDecisions(limit int) ([]*AlignmentDecision, error) {
	rows, err := d.state.Query(`
		SELECT decision_id, cycle, approved,
		       COALESCE(reasons,'[]'), COALESCE(target_subsystem,''),
		       recorded_at
		FROM alignment_decisions
		ORDER BY recorded_at DESC LIMIT ?`, limit)
	if err != nil {
		// Table may not exist yet — return empty rather than error
		return []*AlignmentDecision{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*AlignmentDecision
	for rows.Next() {
		a := &AlignmentDecision{}
		var approved int
		var reasonsJSON string
		if err := rows.Scan(&a.DecisionID, &a.Cycle, &approved,
			&reasonsJSON, &a.TargetSubsystem, &a.RecordedAt); err != nil {
			return nil, err
		}
		a.Approved = approved == 1
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

// AdversarialResult is a single adversarial pressure result from the state DB.
type AdversarialResult struct {
	ResultID   string
	Cycle      int64
	Ring       int32
	Flags      []string
	Severity   string
	RecordedAt float64
}

// RecentAdversarialResults returns the most recent adversarial results.
// Returns an empty slice (not an error) if the table doesn't exist yet.
func (d *DB) RecentAdversarialResults(limit int) ([]*AdversarialResult, error) {
	rows, err := d.state.Query(`
		SELECT result_id, cycle, ring,
		       COALESCE(flags,'[]'), COALESCE(severity,'low'),
		       recorded_at
		FROM adversarial_results
		ORDER BY recorded_at DESC LIMIT ?`, limit)
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

// GoalState is the most recent goal_tracking snapshot from the state DB.
type GoalState struct {
	Cycle                int64
	ConstitutionalChecks map[string]bool
	ScorecardValues      map[string]float64
	ActiveTasks          []string
	RecordedAt           float64
}

// CurrentGoalState returns the most recent goal_tracking row, or nil if empty/absent.
func (d *DB) CurrentGoalState() (*GoalState, error) {
	row := d.state.QueryRow(`
		SELECT cycle,
		       COALESCE(constitutional_checks,'{}'),
		       COALESCE(scorecard_values,'{}'),
		       COALESCE(active_tasks,'[]'),
		       recorded_at
		FROM goal_tracking
		ORDER BY recorded_at DESC LIMIT 1`)
	gs := &GoalState{}
	var checksJSON, scorecardJSON, tasksJSON string
	err := row.Scan(&gs.Cycle, &checksJSON, &scorecardJSON, &tasksJSON, &gs.RecordedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		// Table may not exist yet
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

// Challenge is a devil's advocate challenge from challenge_registry.db.
type Challenge struct {
	ChallengeID     string
	Status          string // open | acknowledged | resolved
	Severity        string // low | medium | high | critical
	TargetSubsystem string
	Description     string
	CreatedAt       float64
	UpdatedAt       float64
}

// ListChallenges returns challenges from challenge_registry.db.
// statusFilter="" or "all" returns all statuses.
// Returns empty slice if challenge DB is nil or table doesn't exist.
func (d *DB) ListChallenges(statusFilter string) ([]*Challenge, error) {
	if d.challenge == nil {
		return []*Challenge{}, nil
	}
	query := `SELECT challenge_id, status, COALESCE(severity,'medium'),
	                 COALESCE(target_subsystem,''), COALESCE(description,''),
	                 created_at, COALESCE(updated_at, created_at)
	          FROM challenges`
	args := []any{}
	if statusFilter != "" && statusFilter != "all" {
		query += " WHERE status = ?"
		args = append(args, statusFilter)
	}
	query += " ORDER BY created_at DESC"
	rows, err := d.challenge.Query(query, args...)
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

// MemoryStats summarises the memory store sizes and contradiction events.
type MemoryStats struct {
	EpisodicCount      int64
	SemanticCount      int64
	RegimeHistory      []string
	ContradictionCount int64
}

// GetMemoryStatsSummary returns aggregate counts and regime history from the memory DB.
func (d *DB) GetMemoryStatsSummary() (*MemoryStats, error) {
	ms := &MemoryStats{RegimeHistory: []string{}}
	d.memory.QueryRow(`SELECT COUNT(*) FROM episodes`).Scan(&ms.EpisodicCount)          //nolint:errcheck,gosec
	d.memory.QueryRow(`SELECT COUNT(*) FROM semantic_memories`).Scan(&ms.SemanticCount) //nolint:errcheck,gosec
	_ = d.memory.QueryRow( //nolint:gosec
		`SELECT COUNT(*) FROM episodes WHERE tags LIKE '%contradiction%'`,
	).Scan(&ms.ContradictionCount)

	rows, err := d.memory.Query(`
		SELECT DISTINCT event_type FROM episodes
		ORDER BY timestamp DESC LIMIT 10`)
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

// GateResult is a single verification gate check result from the state DB.
type GateResult struct {
	GateID    string
	Cycle     int64
	GateName  string
	Result    string // pass | fail | warning
	Details   string
	CheckedAt float64
}

// RecentGateResults returns the most recent verification gate results.
// Returns an empty slice if the table doesn't exist yet.
func (d *DB) RecentGateResults(limit int) ([]*GateResult, error) {
	rows, err := d.state.Query(`
		SELECT gate_id, cycle, gate_name,
		       result, COALESCE(details,''), checked_at
		FROM verification_gates
		ORDER BY checked_at DESC LIMIT ?`, limit)
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

// ── Improvement history (with alignment context) ──────────────────────────────

// ImprovementDetail augments improvement_log with an alignment decision JOIN.
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
	rows, err := d.state.Query(`
		SELECT i.improve_id, i.node_id, i.node_name,
		       i.from_version, i.to_version, i.triggered_by,
		       i.recorded_at, i.cycle,
		       COALESCE(i.before_metrics,'{}'),
		       COALESCE(i.after_metrics,'{}'),
		       a.approved, COALESCE(a.reasons,'[]')
		FROM improvement_log i
		LEFT JOIN alignment_decisions a ON a.cycle = i.cycle
		ORDER BY i.recorded_at DESC LIMIT ?`, limit)
	if err != nil {
		return []*ImprovementDetail{}, nil
	}
	defer rows.Close() //nolint:errcheck
	var out []*ImprovementDetail
	for rows.Next() {
		imp := &ImprovementDetail{}
		var beforeJSON, afterJSON, reasonsJSON string
		var approved sql.NullInt64
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
			v := approved.Int64 == 1
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
